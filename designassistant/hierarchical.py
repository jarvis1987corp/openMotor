"""Generic categorical screening and feedback-driven refinement.

No generator, domain metric, material library or simulation is imported here.
Only supplied alternatives can be screened; unavailable combinations are never
invented. Stage barriers make feedback arrival order irrelevant.
"""

import hashlib
import random
from collections import Counter
from dataclasses import dataclass, replace

from .search import CoarseToFineSearchStrategy

QUALITY_BUDGETS = {"quick": 60, "balanced": 180, "thorough": 540}


@dataclass(frozen=True)
class NumericAssignment:
    path: object
    value: float


@dataclass(frozen=True)
class NumericProposal:
    candidate_id: str
    assignments: tuple


def numeric_proposal(identity, pairs):
    return NumericProposal(identity, tuple(NumericAssignment(path, value) for path, value in pairs))


@dataclass(frozen=True)
class SearchOption:
    key: str
    categories: tuple[tuple[str, str], ...]
    requirements: object
    initial_values: tuple

    def __post_init__(self):
        object.__setattr__(self, "categories", tuple(sorted(self.categories)))
        object.__setattr__(self, "initial_values", tuple(self.initial_values))
        if not self.key or len({k for k, _ in self.categories}) != len(self.categories):
            raise ValueError("Options require unique category names and stable nonempty keys.")
        if len(self.initial_values) != len(self.requirements.variables) or any(
            not v.range.contains(x) for v, x in zip(self.requirements.variables, self.initial_values)
        ):
            raise ValueError("Initial values must lie inside the supplied ranges.")


def stratified_options(options, limit, seed):
    """Canonical input + seeded ties + uncovered levels + balanced marginals.

    Guarantees marginal representation when greedy coverage fits the budget;
    otherwise returns measured partial coverage, never claims completeness.
    This is not exhaustive Cartesian-product coverage.
    """
    pool = sorted(options, key=lambda o: o.key)
    if len({o.key for o in pool}) != len(pool):
        raise ValueError("Option keys must be unique.")
    random.Random(seed).shuffle(pool)
    remaining = {level for o in pool for level in o.categories}
    counts, chosen = Counter(), []
    while pool and len(chosen) < limit:
        option = max(
            pool,
            key=lambda o: (
                sum(level in remaining for level in o.categories),
                sum(1.0 / (1 + counts[level]) for level in o.categories),
            ),
        )
        pool.remove(option)
        chosen.append(option)
        remaining.difference_update(option.categories)
        counts.update(option.categories)
    return tuple(chosen)


class HierarchicalSearchStrategy:
    """Broad representatives -> promising options -> existing coarse-to-fine.

    Budget includes every issuance, including invalid candidates. Stop prevents
    new work while accepting pending completions. Finalist validation belongs
    to the caller, which can reserve a portion of its total budget beforehand.
    """

    def __init__(self, options, *, seed, budget, promising=8, proposal_factory=numeric_proposal):
        self.options = tuple(sorted(options, key=lambda o: o.key))
        if type(budget) is not int or budget < 1 or type(seed) is not int or not self.options:
            raise ValueError("Supply options, integer seed and positive integer budget.")
        if type(promising) is not int or promising < 1:
            raise ValueError("Promising option count must be positive.")
        self.seed, self.budget, self.promising = seed, budget, promising
        self.proposal_factory = proposal_factory
        levels = Counter(k for k, _ in {level for o in self.options for level in o.categories})
        size = min(len(self.options), budget, max(max(levels.values(), default=1), min(64, max(1, budget // 2))))
        self.screening = stratified_options(self.options, size, seed)
        self._by_key = {o.key: o for o in self.options}
        self._issued, self._pending, self._evaluations = {}, set(), {}
        self._cursor, self._searches, self._stopped = 0, None, False
        self._local = {}

    @property
    def exhausted(self):
        if self._stopped:
            return not self._pending
        return self._searches is not None and all(s.exhausted for _, s in self._searches) and not self._pending

    def stop(self):
        self._stopped = True

    def option_for(self, candidate_id):
        return self._by_key[self._issued[candidate_id][0]]

    def stage_for(self, candidate_id):
        return self._issued[candidate_id][1]

    def _register(self, option, stage, proposal):
        identity = "hierarchical-{:012d}".format(len(self._issued))
        self._issued[identity] = (option.key, stage)
        self._pending.add(identity)
        return replace(proposal, candidate_id=identity)

    def ask(self):
        if self._stopped:
            return None
        if self._cursor < len(self.screening):
            option = self.screening[self._cursor]
            self._cursor += 1
            proposal = self.proposal_factory(
                "screen", tuple((v.path, x) for v, x in zip(option.requirements.variables, option.initial_values))
            )
            return self._register(option, "screening", proposal)
        if self._searches is None:
            if self._pending:
                return None
            remaining = self.budget - len(self._issued)
            ranked = sorted(
                self.screening,
                key=lambda o: (
                    min(
                        (e.score for key, e in self._evaluations.values() if key == o.key and e.score is not None),
                        default=float("inf"),
                    ),
                    o.key,
                ),
            )
            selected = ranked[: min(self.promising, remaining)]
            self._searches = []
            if selected:
                quotient, remainder = divmod(remaining, len(selected))
                for i, option in enumerate(selected):
                    local_seed = self.seed + int(hashlib.sha256(option.key.encode()).hexdigest()[:16], 16)
                    search = CoarseToFineSearchStrategy(
                        option.requirements,
                        seed=local_seed,
                        budget=quotient + int(i < remainder),
                        initial_values=None,
                        verify_finalists=False,
                        proposal_factory=self.proposal_factory,
                    )
                    self._searches.append((option, search))
        for option, search in self._searches:
            local = search.ask()
            if local is not None:
                proposal = self._register(option, search.stage_for(local.candidate_id), local)
                self._local[proposal.candidate_id] = (search, local)
                return proposal
        return None

    def tell(self, evaluation):
        identity = evaluation.candidate_id
        if identity not in self._pending:
            raise ValueError("Candidate was never asked, or already completed.")
        self._pending.remove(identity)
        self._evaluations[identity] = (self._issued[identity][0], evaluation)
        if identity in self._local:
            search, local = self._local[identity]
            search.tell(
                replace(
                    evaluation,
                    outcome=replace(evaluation.outcome, candidate_id=local.candidate_id),
                    constraints=replace(evaluation.constraints, candidate_id=local.candidate_id),
                )
            )

    @property
    def diagnostics(self):
        screened = {key for identity, (key, stage) in self._issued.items()
                    if stage == "screening" and identity in self._evaluations}
        coverage = {}
        for option in self.options:
            for category, value in option.categories:
                coverage.setdefault(category, {}).setdefault(value, 0)
        for key in screened:
            for category, value in self._by_key[key].categories:
                coverage[category][value] += 1
        valid = sum(e.outcome.valid and e.constraints.feasible and e.score is not None
                    for _, e in self._evaluations.values())
        return {
            "combinations_available": len(self.options),
            "combinations_screened": len(screened),
            "candidates_evaluated": len(self._evaluations),
            "valid": valid,
            "rejected": len(self._evaluations) - valid,
            "coverage": coverage,
            "screening_budget": len(self.screening),
            "refinement_budget": self.budget - len(self.screening),
        }
