"""Ask/tell strategies independent of simulation execution and GUI scheduling."""

import random
from abc import ABC, abstractmethod

from .models import Assignment, CandidateEvaluation, CandidateProposal, grid_combinations


class SearchStrategy(ABC):
    @abstractmethod
    def ask(self) -> CandidateProposal | None:
        """Return the next proposal, or None when no further proposals exist."""

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
