"""Ask/tell strategies independent of simulation execution and GUI scheduling."""

import random
from abc import ABC, abstractmethod
from dataclasses import replace

from .models import Assignment, CandidateEvaluation, CandidateProposal, grid_combinations


class SearchStrategy(ABC):
    @abstractmethod
    def ask(self) -> CandidateProposal | None:
        """Return an issuable proposal, or None at exhaustion/a feedback barrier.

        Adaptive strategies expose ``exhausted`` so a future parallel scheduler
        can distinguish completion from waiting for already issued evaluations.
        """

    @abstractmethod
    def tell(self, evaluation: CandidateEvaluation) -> None:
        """Accept one completion for a previously asked candidate (any order)."""


class _FiniteSearch(SearchStrategy):
    def __init__(self, requirements):
        self.requirements = requirements
        self._issued = 0
        self._pending = set()
        self._evaluations = {}
        self._exhausted = False

    @property
    def exhausted(self):
        return self._exhausted

    @property
    def pending_count(self):
        return len(self._pending)

    @property
    def evaluations(self):
        # Completion order cannot affect result ordering, including later parallel execution.
        return tuple(self._evaluations[key] for key in sorted(self._evaluations))

    @property
    def ranked(self):
        return tuple(
            sorted(
                (e for e in self.evaluations if e.score is not None and e.constraints.feasible),
                key=lambda e: (e.score, e.candidate_id),
            )
        )

    def _proposal(self, values):
        candidate_id = "candidate-{:012d}".format(self._issued)
        self._issued += 1
        self._pending.add(candidate_id)
        return CandidateProposal(
            candidate_id, tuple(Assignment(v.path, value) for v, value in zip(self.requirements.variables, values))
        )

    def tell(self, evaluation):
        if not isinstance(evaluation, CandidateEvaluation):
            raise TypeError("tell requires a CandidateEvaluation.")
        if evaluation.candidate_id not in self._pending:
            raise ValueError("Candidate was never asked, or already completed.")
        self._pending.remove(evaluation.candidate_id)
        self._evaluations[evaluation.candidate_id] = evaluation


class GridSearchStrategy(_FiniteSearch):
    """Requirements variable order; last axis varies fastest; endpoints included."""

    def __init__(self, requirements):
        super().__init__(requirements)
        self._points = iter(grid_combinations(requirements.variables))

    def ask(self):
        try:
            return self._proposal(next(self._points))
        except StopIteration:
            self._exhausted = True
            return None


class RandomSearchStrategy(_FiniteSearch):
    """Local PRNG, fixed budget; no global random state or result-order dependency."""

    def __init__(self, requirements, *, seed: int, budget: int):
        if type(seed) is not int or type(budget) is not int or budget < 0:
            raise ValueError("Seed and budget must be integers; budget must be nonnegative.")
        super().__init__(requirements)
        self.seed = seed
        self.budget = budget
        self._random = random.Random(seed)

    def ask(self):
        if self._issued >= self.budget:
            self._exhausted = True
            return None
        values = []
        for variable in self.requirements.variables:
            bounds = variable.range
            if bounds.integer:
                values.append(self._random.randint(int(bounds.minimum), int(bounds.maximum)))
            else:
                values.append(self._random.uniform(bounds.minimum, bounds.maximum))
        return self._proposal(values)


class CoarseToFineSearchStrategy(_FiniteSearch):
    """Seeded exploration, barrier/selection, local refinement and finalist replay.

    A stage advances only after all its issued proposals have been told, so
    completion order cannot influence region selection. None while pending is
    a scheduling barrier; ``exhausted`` distinguishes it from completion.
    Budgets include rechecks and no engine settings are modified.
    """

    def __init__(self, requirements, *, seed, budget, top_n=10, initial_values=None, verify_finalists=True):
        if type(seed) is not int or type(budget) is not int or budget < 1:
            raise ValueError("Seed and budget must be integers; budget must be positive.")
        if type(top_n) is not int or top_n < 1:
            raise ValueError("Top N must be positive.")
        super().__init__(requirements)
        self.seed, self.budget = seed, budget
        self._random = random.Random(seed)
        self._proposals, self._stages, self._verification_sources = {}, {}, {}
        self._initial = None if initial_values is None else tuple(initial_values)
        if self._initial is not None and (
            len(self._initial) != len(requirements.variables)
            or any(not v.range.contains(x) for v, x in zip(requirements.variables, self._initial))
        ):
            raise ValueError("Initial values must lie inside the search space.")
        verification = min(top_n, budget // 4) if verify_finalists else 0
        self._exploration_end = max(1, (budget - verification + 1) // 2)
        self._refinement_end = budget - verification
        self.stage = "exploration"
        self._elites, self._finalists = (), ()
        self._verification_index = 0

    def stage_for(self, candidate_id):
        return self._stages[candidate_id]

    def verification_source(self, candidate_id):
        return self._verification_sources.get(candidate_id)

    def _sample(self, centre=None):
        values = []
        for index, variable in enumerate(self.requirements.variables):
            bounds = variable.range
            low, high = bounds.minimum, bounds.maximum
            if centre is not None:
                radius = (high - low) * 0.2
                low, high = max(low, centre[index] - radius), min(high, centre[index] + radius)
            if bounds.integer:
                import math

                low, high = math.ceil(low), math.floor(high)
                values.append(self._random.randint(low, high))
            else:
                values.append(self._random.uniform(low, high))
        return tuple(values)

    def _select(self, limit):
        if limit <= 0:
            return ()
        selected, seen = [], set()
        for evaluation in self.ranked:
            proposal = self._proposals[evaluation.candidate_id]
            signature = tuple((a.path.value, a.value) for a in proposal.assignments)
            if signature not in seen:
                selected.append(proposal)
                seen.add(signature)
            if len(selected) >= limit:
                break
        return tuple(selected)

    def ask(self):
        if self._exhausted:
            return None
        if self.stage == "exploration" and self._issued >= self._exploration_end:
            if self._pending:
                return None
            self._elites = self._select(3)
            self.stage = "refinement"
        if self.stage == "refinement" and self._issued >= self._refinement_end:
            if self._pending:
                return None
            self._finalists = self._select(self.budget - self._refinement_end)
            self.stage = "verification"
        if (
            self._issued >= self.budget
            or self.stage == "verification"
            and (self._verification_index >= len(self._finalists))
        ):
            self._exhausted = not self._pending
            return None
        source = None
        if self.stage == "verification":
            source = self._finalists[self._verification_index]
            self._verification_index += 1
            values = tuple(a.value for a in source.assignments)
        elif not self._issued and self._initial is not None:
            values = self._initial
        elif self.stage == "refinement" and self._elites:
            elite = self._elites[(self._issued - self._exploration_end) % len(self._elites)]
            values = self._sample(tuple(a.value for a in elite.assignments))
        else:
            values = self._sample()
        proposal = self._proposal(values)
        self._proposals[proposal.candidate_id] = proposal
        self._stages[proposal.candidate_id] = self.stage
        if source is not None:
            self._verification_sources[proposal.candidate_id] = source.candidate_id
        return proposal


class SmartSearchStrategy(SearchStrategy):
    """Fair round-robin search over exact library/geometry variants, one budget.

    Each variant has an independent seed and ask/tell state. The GUI/runner
    schedules proposals and hands their immutable requests to EngineAdapter.
    """

    def __init__(self, plan):
        from .generator import CandidateGenerator
        from .smart_results import SmartResultStore

        self.plan = plan
        self.results = SmartResultStore(plan)
        self._verification_budget = min(plan.requirements.top_n, (plan.requirements.budget - len(plan.variants)) // 2)
        quotient, remainder = divmod(plan.requirements.budget - self._verification_budget, len(plan.variants))
        self._searches = tuple(
            CoarseToFineSearchStrategy(
                v.requirements,
                seed=plan.requirements.seed + i,
                budget=quotient + int(i < remainder),
                top_n=plan.requirements.top_n,
                initial_values=v.initial_values,
                verify_finalists=False,
            )
            for i, v in enumerate(plan.variants)
        )
        self._generators = tuple(CandidateGenerator(v.baseline.to_dict(), v.requirements) for v in plan.variants)
        self._issued, self._cursor = {}, 0
        self._finalists = None
        self._verification_index = 0
        self._rechecks = {}
        self._pending_rechecks = set()

    @property
    def exhausted(self):
        return (
            all(s.exhausted for s in self._searches)
            and self._finalists is not None
            and self._verification_index >= len(self._finalists)
            and not self._pending_rechecks
        )

    @staticmethod
    def _global_id(index, candidate_id):
        return f"smart-{index:04d}-{candidate_id}"

    def ask(self):
        for _ in self._searches:
            index = self._cursor
            self._cursor = (self._cursor + 1) % len(self._searches)
            local = self._searches[index].ask()
            if local is not None:
                global_proposal = replace(local, candidate_id=self._global_id(index, local.candidate_id))
                self._issued[global_proposal.candidate_id] = (index, local)
                return global_proposal
        if not all(s.exhausted for s in self._searches):
            return None
        if self._finalists is None:
            self._finalists = self.results.ranked(self._verification_budget)
        if self._verification_index >= len(self._finalists):
            if not self._pending_rechecks:
                self.results.finalized = True
            return None
        record = self._finalists[self._verification_index]
        candidate_id = f"smart-recheck-{self._verification_index:012d}"
        self._verification_index += 1
        index, local = self._issued[record.proposal.candidate_id]
        proposal = replace(local, candidate_id=candidate_id)
        self._issued[candidate_id] = (index, local)
        self._rechecks[candidate_id] = record.proposal.candidate_id
        self._pending_rechecks.add(candidate_id)
        return proposal

    def context_for(self, candidate_id):
        from .smart_results import SmartCandidateContext

        index, proposal = self._issued[candidate_id]
        if candidate_id in self._rechecks:
            return SmartCandidateContext(self.plan.variants[index].key, "verification", self._rechecks[candidate_id])
        strategy = self._searches[index]
        source = strategy.verification_source(proposal.candidate_id)
        return SmartCandidateContext(
            self.plan.variants[index].key,
            strategy.stage_for(proposal.candidate_id),
            None if source is None else self._global_id(index, source),
        )

    def requirements_for(self, candidate_id):
        index, _ = self._issued[candidate_id]
        return self.plan.variants[index].requirements

    def request_for(self, proposal):
        index, local = self._issued[proposal.candidate_id]
        if proposal.assignments != local.assignments:
            raise ValueError("A proposal must match its issued assignments.")
        return self._generators[index].generate(proposal)

    def tell(self, evaluation):
        index, local = self._issued[evaluation.candidate_id]
        if evaluation.candidate_id in self._rechecks:
            if evaluation.candidate_id not in self._pending_rechecks:
                raise ValueError("Candidate was never asked, or already completed.")
            self._pending_rechecks.remove(evaluation.candidate_id)
        else:
            self._searches[index].tell(
                replace(
                    evaluation,
                    outcome=replace(evaluation.outcome, candidate_id=local.candidate_id),
                    constraints=replace(evaluation.constraints, candidate_id=local.candidate_id),
                )
            )
        proposal = replace(local, candidate_id=evaluation.candidate_id)
        self.results.append(proposal, evaluation, self.context_for(evaluation.candidate_id))
