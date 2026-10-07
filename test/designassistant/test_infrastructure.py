"""Dimensionless synthetic objectives and category spaces; no engine fixtures."""

import dataclasses
import random
import unittest
from types import SimpleNamespace

from designassistant.evaluation import Objective
from designassistant.hierarchical import QUALITY_BUDGETS, HierarchicalSearchStrategy, SearchOption
from designassistant.models import (
    MetricConstraint,
    MetricValue,
    OutcomeStatus,
    ParameterRange,
    SimulationOutcome,
    Target,
)
from designassistant.objectives import (
    TargetStatus,
    TargetTolerancePolicy,
    match_percentage,
    result_heading,
    target_errors,
)
from designassistant.smart_results import analyze_candidate


class NumericRegistry:
    def validate_requirements(self, requirements):
        pass


def requirements(*targets, constraints=(), variables=()):
    return SimpleNamespace(targets=targets, constraints=constraints, variables=variables, reject_warnings=False)


def evaluate(req, values, identity="synthetic", valid=True):
    outcome = SimulationOutcome(
        identity,
        OutcomeStatus.COMPLETED if valid else OutcomeStatus.INVALID_RESULT,
        valid,
        valid,
        tuple(MetricValue(key, value, "") for key, value in values.items()),
    )
    return Objective(NumericRegistry()).evaluate(outcome, req)


def options():
    path = SimpleNamespace(value="x")
    variable = SimpleNamespace(path=path, range=ParameterRange(0, 1, 3))
    req = requirements(Target("loss", 0, 1), variables=(variable,))
    return tuple(
        SearchOption(f"{a:02}:{b:02}:{c}", (("family", str(a)), ("style", str(b)), ("batch", str(c))), req, (0.5,))
        for a in range(20)
        for b in range(10)
        for c in range(2)
    )


def complete(search, proposal, invalid=False):
    option = search.option_for(proposal.candidate_id)
    a, b, c = map(int, option.key.split(":"))
    x = proposal.assignments[0].value
    loss = (x - 0.3) ** 2 + a / 100 + b / 200 + c / 400
    return evaluate(option.requirements, {"loss": loss}, proposal.candidate_id, valid=not invalid)


def run(search, invalid=False):
    trace = []
    while (proposal := search.ask()) is not None:
        trace.append(
            (
                search.option_for(proposal.candidate_id).key,
                search.stage_for(proposal.candidate_id),
                tuple(a.value for a in proposal.assignments),
            )
        )
        search.tell(complete(search, proposal, invalid=invalid))
    return tuple(trace)


class NumericAssessmentTests(unittest.TestCase):
    def targets(self, *actuals):
        req = requirements(*(Target(f"objective-{i}", 100, 10) for i in range(len(actuals))))
        return req, evaluate(req, {f"objective-{i}": actual for i, actual in enumerate(actuals)})

    def test_exact_objectives_match(self):
        _, result = self.targets(100, 100)
        self.assertEqual(match_percentage(result.score), 100)
        self.assertEqual(result.target_status, TargetStatus.MATCHED)

    def test_small_errors_have_high_match(self):
        _, result = self.targets(104, 105)
        self.assertGreater(match_percentage(result.score), 85)
        self.assertEqual(result.target_status, TargetStatus.MATCHED)
        self.assertEqual([e.relative_error for e in result.objective_errors], [0.04, 0.05])

    def test_catastrophic_error_is_not_hidden(self):
        for actuals in ((100, 18), (100, 100, 18), (100,) * 20 + (18,)):
            _, result = self.targets(*actuals)
            self.assertLess(match_percentage(result.score), 30)
            self.assertEqual(result.target_status, TargetStatus.MISSED)

    def test_constraints_and_targets_are_independent(self):
        req = requirements(Target("response", 100, 10), constraints=(MetricConstraint("cost", maximum=10),))
        result = evaluate(req, {"response": 18, "cost": 5})
        self.assertTrue(result.constraints.feasible)
        self.assertEqual(result.target_status, TargetStatus.MISSED)
        self.assertEqual(result_heading((result.target_status,)), "Closest candidates")

    def test_tolerance_policy_boundaries_and_invalid_values(self):
        policy = TargetTolerancePolicy()
        for error, status in ((0, "MATCHED"), (0.1, "MATCHED"), (0.1001, "NEAR"), (0.2, "NEAR"), (0.2001, "MISSED")):
            self.assertEqual(policy.status(error).value, status)
        for error in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                policy.status(error)
        with self.assertRaises(ValueError):
            TargetTolerancePolicy(0.2, 0.1)

    def test_matched_targets_do_not_override_failed_constraints(self):
        req = requirements(Target("response", 100, 10), constraints=(MetricConstraint("cost", maximum=10),))
        result = evaluate(req, {"response": 100, "cost": 20})
        self.assertFalse(result.constraints.feasible)
        self.assertEqual(result.target_status, TargetStatus.MATCHED)
        self.assertIsNone(result.score)

    def test_zero_target_uses_explicit_absolute_scale(self):
        req = requirements(Target("loss", 0, 2))
        result = evaluate(req, {"loss": 0.1})
        self.assertEqual(result.objective_errors[0].relative_error, 0.05)
        with self.assertRaises(ValueError):
            target_errors((SimpleNamespace(metric="loss", value=0, scale=0, weight=1),), lambda _: 1)

    def test_disabled_objective_does_not_change_match_or_status(self):
        req = requirements(Target("response", 100, 10), Target("ignored", 100, 10, 0))
        result = evaluate(req, {"response": 100, "ignored": 0})
        self.assertEqual(result.target_status, TargetStatus.MATCHED)
        self.assertEqual(result.score, 0)

    def test_analysis_reports_same_errors_as_scoring(self):
        req, result = self.targets(104, 18)
        analysis = analyze_candidate(result, req)
        self.assertEqual(
            [e.relative_error for e in analysis.targets], [e.relative_error for e in result.objective_errors]
        )
        self.assertEqual(analysis.target_status, result.target_status)


class CategoricalSearchTests(unittest.TestCase):
    def test_400_combinations_small_budget_fair_permutation_invariance(self):
        source = options()
        shuffled = list(source)
        random.Random(923).shuffle(shuffled)
        first = HierarchicalSearchStrategy(source, seed=17, budget=120)
        second = HierarchicalSearchStrategy(shuffled, seed=17, budget=120)
        self.assertEqual(run(first), run(second))
        report = first.diagnostics
        self.assertEqual(report["combinations_available"], 400)
        self.assertEqual(report["candidates_evaluated"], 120)
        self.assertLess(report["combinations_screened"], 400)
        for values in report["coverage"].values():
            self.assertTrue(all(count > 0 for count in values.values()))

    def test_deterministic_seed_and_independent_global_random(self):
        first = run(HierarchicalSearchStrategy(options(), seed=1, budget=60))
        random.seed(100)
        self.assertEqual(first, run(HierarchicalSearchStrategy(options(), seed=1, budget=60)))
        self.assertNotEqual(first, run(HierarchicalSearchStrategy(options(), seed=2, budget=60)))

    def test_quality_budgets_keep_broad_coverage_and_increase_depth(self):
        reports = []
        for budget in QUALITY_BUDGETS.values():
            search = HierarchicalSearchStrategy(options(), seed=3, budget=budget)
            run(search)
            report = search.diagnostics
            self.assertEqual(report["candidates_evaluated"], budget)
            self.assertTrue(all(n > 0 for values in report["coverage"].values() for n in values.values()))
            reports.append(report)
        self.assertEqual([r["combinations_screened"] for r in reports], [30, 64, 64])
        self.assertEqual([r["refinement_budget"] for r in reports], [30, 116, 476])

    def test_promising_set_gets_remaining_budget_after_screening(self):
        search = HierarchicalSearchStrategy(options(), seed=8, budget=120, promising=3)
        trace = run(search)
        screened = {key for key, stage, _ in trace if stage == "screening"}
        refined = {key for key, stage, _ in trace if stage != "screening"}
        self.assertLessEqual(len(refined), 3)
        self.assertTrue(refined.issubset(screened))
        self.assertIn("exploration", {stage for _, stage, _ in trace})
        self.assertIn("refinement", {stage for _, stage, _ in trace})

    def test_feedback_barrier_and_completion_order(self):
        first = HierarchicalSearchStrategy(options(), seed=5, budget=60)
        second = HierarchicalSearchStrategy(options(), seed=5, budget=60)
        for search, reverse in ((first, False), (second, True)):
            pending = []
            while (proposal := search.ask()) is not None:
                pending.append(proposal)
            self.assertFalse(search.exhausted)
            for proposal in reversed(pending) if reverse else pending:
                search.tell(complete(search, proposal))
        self.assertEqual(run(first), run(second))

    def test_stop_is_cooperative_and_pending_completion_is_retained(self):
        search = HierarchicalSearchStrategy(options(), seed=1, budget=60)
        proposal = search.ask()
        search.stop()
        self.assertIsNone(search.ask())
        self.assertFalse(search.exhausted)
        search.tell(complete(search, proposal))
        self.assertTrue(search.exhausted)
        self.assertEqual(search.diagnostics["candidates_evaluated"], 1)

    def test_invalid_candidates_do_not_abort_or_exceed_budget(self):
        search = HierarchicalSearchStrategy(options(), seed=1, budget=60)
        self.assertEqual(len(run(search, invalid=True)), 60)
        self.assertEqual(search.diagnostics["rejected"], 60)

    def test_too_small_budget_reports_partial_coverage_honestly(self):
        search = HierarchicalSearchStrategy(options(), seed=1, budget=3)
        run(search)
        self.assertEqual(search.diagnostics["combinations_screened"], 3)
        self.assertTrue(any(n == 0 for values in search.diagnostics["coverage"].values() for n in values.values()))

    def test_duplicate_keys_are_rejected(self):
        option = options()[0]
        with self.assertRaises(ValueError):
            HierarchicalSearchStrategy((option, option), seed=1, budget=60)

    def test_category_order_is_canonical(self):
        source = options()
        changed = tuple(dataclasses.replace(o, categories=tuple(reversed(o.categories))) for o in source)
        self.assertEqual(
            run(HierarchicalSearchStrategy(source, seed=1, budget=60)),
            run(HierarchicalSearchStrategy(changed, seed=1, budget=60)),
        )
