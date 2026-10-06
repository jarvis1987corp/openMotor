"""Quick inputs compile into unchanged Smart/CandidateGenerator/EngineAdapter APIs."""

import ast
import copy
import dataclasses
import math
import unittest
from pathlib import Path
from unittest.mock import patch

from designassistant import (
    CandidateGenerator,
    CandidateProposal,
    EngineAdapter,
    LibraryEntry,
    MetricConstraint,
    MetricRegistry,
    Objective,
    OutcomeStatus,
    SmartSearchStrategy,
    Snapshot,
)
from designassistant.quick import (
    QUICK_METRICS,
    QuickCriterion,
    QuickDesignError,
    QuickDesignProblemBuilder,
    QuickDesignRequirements,
    QuickDesignRequirementsValidator,
    match_percentage,
    recommended_designs,
)
from motorlib.motor import Motor
from motorlib.simResult import SimulationResult
from test.designassistant.support import fixture_names, fixture_snapshot
from test.designassistant.test_smart import fake_evaluation, plan


def inputs(**changes):
    values = dict(
        criteria=(QuickCriterion("diameter", "maximum", 0.15), QuickCriterion("burn_time", "target", 2.0)), budget=12
    )
    values.update(changes)
    return QuickDesignRequirements(**values)


def problem(**changes):
    baseline = fixture_snapshot()
    return QuickDesignProblemBuilder().build(
        baseline, inputs(**changes), (LibraryEntry.from_dict(baseline["propellant"]),)
    )


def run(problem):
    strategy = SmartSearchStrategy(problem.plan)
    adapter = EngineAdapter(MetricRegistry(problem.plan.requirements.metric_definitions))
    objective = Objective(adapter.registry)
    trace = []
    while (proposal := strategy.ask()) is not None:
        trace.append(proposal)
        outcome = adapter.run(strategy.request_for(proposal))
        strategy.tell(objective.evaluate(outcome, strategy.requirements_for(proposal.candidate_id)))
    return strategy, tuple(trace)


class QuickRequirementsTests(unittest.TestCase):
    def test_defaults_use_balanced_budget_and_all_compatible_library(self):
        req = QuickDesignRequirements()
        self.assertEqual(req.simulation_budget, 180)
        self.assertIsNone(req.library_keys)
        self.assertEqual(req.priority, "balanced")

    def test_values_are_positive_finite_and_identifiers_stable(self):
        for value in (0, -1, math.nan, math.inf, True):
            with self.subTest(value=value), self.assertRaises(QuickDesignError):
                QuickCriterion("burn_time", "target", value)
        for field, mode in (("Время горения", "target"), ("burn_time", "Цель"), ("unknown", "maximum")):
            with self.assertRaises(QuickDesignError):
                QuickCriterion(field, mode, 1)

    def test_invalid_settings(self):
        for changes in (
            {"priority": "unknown"},
            {"quality": "custom"},
            {"seed": True},
            {"budget": 0},
            {"budget": 10001},
            {"reject_warnings": "yes"},
            {"library_keys": ()},
        ):
            with self.subTest(changes=changes), self.assertRaises(QuickDesignError):
                inputs(**changes)

    def test_input_collections_are_immutable(self):
        values = [QuickCriterion("length", "maximum", 0.5)]
        req = QuickDesignRequirements(values)
        values.clear()
        self.assertEqual(len(req.criteria), 1)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            req.seed = 1

    def test_repeated_field_and_mode_rejected(self):
        with self.assertRaises(QuickDesignError):
            inputs(criteria=(QuickCriterion("burn_time", "target", 2),) * 2)

    def test_partial_requirements_one_dimension_and_one_goal(self):
        self.assertEqual(len(problem().plan.requirements.targets), 1)
        p = problem(criteria=(QuickCriterion("length", "maximum", 0.5), QuickCriterion("total_impulse", "target", 100)))
        self.assertEqual(p.plan.requirements.targets[0].metric, "total_impulse")

    def test_underdefined_input_never_simulates(self):
        baseline = fixture_snapshot()
        entry = LibraryEntry.from_dict(baseline["propellant"])
        for criteria in (
            (),
            (QuickCriterion("diameter", "maximum", 0.1),),
            (QuickCriterion("burn_time", "target", 2),),
        ):
            with patch.object(Motor, "runSimulation") as simulation:
                v = QuickDesignRequirementsValidator().validate(baseline, inputs(criteria=criteria), (entry,))
                self.assertFalse(v.valid)
                self.assertTrue(
                    any(word in v.diagnostics[0].source for word in ("dimensional", "diameter", "burn time"))
                )
                simulation.assert_not_called()

    def test_target_and_both_bounds_convert_to_existing_contracts(self):
        p = problem(
            criteria=inputs().criteria
            + (QuickCriterion("burn_time", "minimum", 1), QuickCriterion("burn_time", "maximum", 3))
        )
        targets, constraints = p.plan.requirements.targets, p.plan.requirements.constraints
        self.assertEqual(targets[0].value, 2)
        self.assertEqual(targets[0].scale, 0.2)
        self.assertIn(MetricConstraint("burn_time", minimum=1), constraints)
        self.assertIn(MetricConstraint("burn_time", maximum=3), constraints)

    def test_limits_alone_infer_one_disclosed_performance_ranking_goal(self):
        p = problem(
            criteria=(QuickCriterion("diameter", "maximum", 0.15), QuickCriterion("average_thrust", "minimum", 10))
        )
        self.assertTrue(p.inferred_targets)
        self.assertEqual(p.plan.requirements.targets[0].metric, "average_thrust")
        self.assertEqual(p.plan.requirements.targets[0].value, 10)
        self.assertIn(MetricConstraint("average_thrust", minimum=10), p.plan.requirements.constraints)

    def test_conflicting_bounds(self):
        with self.assertRaisesRegex(QuickDesignError, "contradict"):
            problem(
                criteria=inputs().criteria
                + (QuickCriterion("length", "minimum", 0.6), QuickCriterion("length", "maximum", 0.5))
            )

    def test_target_outside_constraints(self):
        with self.assertRaisesRegex(QuickDesignError, "outside"):
            problem(constraints=(MetricConstraint("burn_time", maximum=1),))

    def test_priority_changes_only_existing_weights(self):
        criteria = inputs().criteria + (QuickCriterion("average_thrust", "target", 50),)
        balanced = problem(criteria=criteria)
        thrust = problem(criteria=criteria, priority="average_thrust")
        self.assertEqual([t.weight for t in balanced.plan.requirements.targets], [1, 1])
        self.assertEqual([t.weight for t in thrust.plan.requirements.targets], [1, 3])
        self.assertEqual(
            [t.value for t in balanced.plan.requirements.targets], [t.value for t in thrust.plan.requirements.targets]
        )
        self.assertEqual(
            balanced.plan.variants[0].requirements.variables, thrust.plan.variants[0].requirements.variables
        )

    def test_absent_priority_does_not_create_an_extra_goal(self):
        self.assertEqual(len(problem(priority="total_impulse").plan.requirements.targets), 1)

    def test_quality_changes_budget_without_changing_engine_configuration(self):
        plans = [problem(quality=q, budget=None) for q in ("quick", "balanced", "thorough")]
        self.assertEqual([p.requirements.simulation_budget for p in plans], [60, 180, 540])
        self.assertTrue(
            all(p.plan.variants[0].baseline.to_dict()["config"] == fixture_snapshot()["config"] for p in plans)
        )


class QuickProblemTests(unittest.TestCase):
    def test_geometry_selection_reuses_compatibility_and_reports_skipped_types(self):
        p = problem()
        self.assertGreater(len(p.plan.variants), 1)
        self.assertTrue(any("Skipped geometry" in d.source for d in p.diagnostics))
        self.assertEqual(p.plan.variants[0].baseline.to_dict()["config"], fixture_snapshot()["config"])

    def test_library_all_subset_and_fixed_are_exact_snapshots(self):
        baseline = fixture_snapshot()
        first = LibraryEntry.from_dict(baseline["propellant"])
        other = copy.deepcopy(baseline["propellant"])
        other["name"] += " existing entry"
        second = LibraryEntry.from_dict(other)
        for keys, count in ((None, 2), ((first.key,), 1), ((first.key, second.key), 2)):
            p = QuickDesignProblemBuilder().build(baseline, inputs(library_keys=keys), (second, first))
            self.assertEqual(len({v.library_key for v in p.plan.variants}), count)
            for variant in p.plan.variants:
                expected = first if variant.library_key == first.key else second
                self.assertEqual(variant.baseline.to_dict()["propellant"], expected.snapshot.to_dict())

    def test_invalid_library_is_skipped_and_reported(self):
        baseline = fixture_snapshot()
        good = LibraryEntry.from_dict(baseline["propellant"])
        bad = copy.deepcopy(baseline["propellant"])
        bad["name"] = "Invalid existing entry"
        bad["density"] = -1
        bad = LibraryEntry.from_dict(bad)
        p = QuickDesignProblemBuilder().build(baseline, inputs(), (bad, good))
        self.assertEqual({v.library_key for v in p.plan.variants}, {good.key})
        self.assertTrue(any("Skipped library" in d.source for d in p.diagnostics))
        with self.assertRaisesRegex(QuickDesignError, "No compatible"):
            QuickDesignProblemBuilder().build(baseline, inputs(library_keys=(bad.key,)), (bad, good))

    def test_missing_library_and_empty_library(self):
        with self.assertRaisesRegex(QuickDesignError, "No compatible"):
            QuickDesignProblemBuilder().build(fixture_snapshot(), inputs(), ())
        with self.assertRaisesRegex(QuickDesignError, "no longer available"):
            problem(library_keys=("missing",))

    def test_silently_rejected_dimensional_setter_prevents_search(self):
        from motorlib.properties import FloatProperty

        original = FloatProperty.setValue

        def reject_diameter(prop, value):
            if prop.unit == "m" and value == 0.12:
                return
            return original(prop, value)

        baseline = fixture_snapshot()
        entry = LibraryEntry.from_dict(baseline["propellant"])
        criteria = (QuickCriterion("diameter", "target", 0.12), QuickCriterion("burn_time", "target", 2))
        with (
            patch.object(FloatProperty, "setValue", reject_diameter),
            patch.object(Motor, "runSimulation") as run_engine,
        ):
            validation = QuickDesignRequirementsValidator().validate(baseline, inputs(criteria=criteria), (entry,))
        self.assertFalse(validation.valid)
        self.assertIn("Setter read-back", validation.diagnostics[0].arguments_json)
        run_engine.assert_not_called()

    def test_unconfigured_baseline_rejected_before_search(self):
        baseline = fixture_snapshot()
        entries = (LibraryEntry.from_dict(baseline["propellant"]),)
        baseline["grains"] = []
        self.assertFalse(QuickDesignRequirementsValidator().validate(baseline, inputs(), entries).valid)

    def test_dimension_target_and_minimum_can_place_a_larger_space(self):
        p = problem(
            criteria=(
                QuickCriterion("diameter", "target", 0.12),
                QuickCriterion("length", "minimum", 0.4),
                QuickCriterion("burn_time", "target", 2),
            )
        )
        motor = Motor(p.plan.variants[0].baseline.to_dict())
        self.assertAlmostEqual(SimulationResult(motor).getMaxPropellantDiameter(), 0.12)
        self.assertAlmostEqual(SimulationResult(motor).getPropellantLength(), 0.4)

    def test_small_dimension_caps_apply_to_every_candidate(self):
        p = problem(
            criteria=(
                QuickCriterion("diameter", "maximum", 0.06),
                QuickCriterion("length", "maximum", 0.2),
                QuickCriterion("burn_time", "target", 2),
            )
        )
        for variant in p.plan.variants:
            gen = CandidateGenerator(variant.baseline.to_dict(), variant.requirements)
            proposal = CandidateProposal.from_values(
                "upper", {v.path.value: v.range.maximum for v in variant.requirements.variables}
            )
            request = gen.generate(proposal)
            self.assertTrue(request.valid)
            motor = Motor(request.snapshot.to_dict())
            self.assertLessEqual(SimulationResult(motor).getPropellantLength(), 0.2 + 1e-15)
            self.assertLessEqual(SimulationResult(motor).getMaxPropellantDiameter(), 0.06)
            self.assertLessEqual(motor.nozzle.getProperty("exit"), 0.06)

    def test_baseline_and_nested_polygon_unchanged_after_hundreds_of_requests(self):
        # Retain the existing custom shape exactly while numeric dimensions vary.
        name = next(n for n in fixture_names() if "custom" in n.lower())
        baseline = fixture_snapshot(name)
        original = copy.deepcopy(baseline)
        entry = LibraryEntry.from_dict(baseline["propellant"])
        p = QuickDesignProblemBuilder().build(baseline, inputs(), (entry,))
        for i in range(300):
            variant = p.plan.variants[i % len(p.plan.variants)]
            gen = CandidateGenerator(variant.baseline.to_dict(), variant.requirements)
            proposal = CandidateProposal.from_values(
                str(i),
                {v.path.value: value for v, value in zip(variant.requirements.variables, variant.initial_values)},
            )
            request = gen.generate(proposal)
            self.assertTrue(request.valid)
            data = request.snapshot.to_dict()
            data["grains"].clear()
        self.assertEqual(baseline, original)
        self.assertEqual(p.plan.baseline, Snapshot.from_dict(original))

    def test_same_seed_exact_proposals_outcomes_and_ranking(self):
        p = problem()
        first, trace = run(p)
        second, other_trace = run(p)
        self.assertEqual(trace, other_trace)
        self.assertEqual(first.results.ranked(), second.results.ranked())
        self.assertTrue(first.results.top)

    def test_invalid_candidates_do_not_stop_the_existing_backend(self):
        p = problem()
        strategy = SmartSearchStrategy(p.plan)
        adapter = EngineAdapter(MetricRegistry(QUICK_METRICS))
        objective = Objective(adapter.registry)
        count = 0
        while (proposal := strategy.ask()) is not None:
            request = strategy.request_for(proposal)
            if count == 0:
                request = dataclasses.replace(request, snapshot=None)
            strategy.tell(objective.evaluate(adapter.run(request), strategy.requirements_for(proposal.candidate_id)))
            count += 1
        self.assertGreater(count, 1)
        self.assertEqual(next(iter(strategy.results.records.values()))[1].outcome.status, OutcomeStatus.INVALID_REQUEST)
        self.assertTrue(strategy.results.top)

    def test_extended_summary_getters_exact_match_direct_engine_on_18_fixtures(self):
        registry = MetricRegistry(QUICK_METRICS)
        self.assertEqual(len(fixture_names()), 18)
        for name in fixture_names():
            with self.subTest(fixture=name):
                baseline = fixture_snapshot(name)
                direct = Motor(copy.deepcopy(baseline)).runSimulation()
                from designassistant import DesignRequirements

                gen = CandidateGenerator(baseline, DesignRequirements())
                outcome = EngineAdapter(registry).run(gen.generate(CandidateProposal("baseline")))
                self.assertTrue(outcome.valid)
                self.assertEqual(outcome.metrics, registry.extract(direct))

    def test_quick_has_no_qt_or_gui_or_simulation_calls(self):
        source = Path(__file__).resolve().parents[2] / "designassistant/quick.py"
        tree = ast.parse(source.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                self.assertFalse((node.module or "").startswith(("PyQt", "uilib")))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertNotEqual(node.func.attr, "runSimulation")


class QuickRecommendationsTests(unittest.TestCase):
    def test_match_is_monotonic_display_index(self):
        self.assertEqual(match_percentage(0), 100)
        self.assertEqual(match_percentage(1), 50)
        self.assertLess(match_percentage(2), match_percentage(1))
        for value in (-1, math.inf, math.nan, True):
            with self.assertRaises(ValueError):
                match_percentage(value)

    def test_top_five_diversity_and_explanations_reuse_smart_data(self):
        from designassistant import SmartResultStore
        from designassistant.smart_results import SmartCandidateContext

        store = SmartResultStore(plan())
        variant = store.plan.variants[0]
        for i in range(10):
            proposal = CandidateProposal.from_values(f"candidate-{i:02d}", {"nozzle.throat": 0.01 + i * 0.001})
            evaluation = fake_evaluation(proposal, score=i)
            # fake helper outcomes agree on metrics, so all are near duplicates.
            store.append(proposal, evaluation, SmartCandidateContext(variant.key, "refinement"))
        self.assertEqual(len(recommended_designs(store)), 1)
        self.assertTrue(recommended_designs(store)[0].analysis.explanations)
        from designassistant import MetricValue

        for i, (proposal, evaluation, context) in enumerate(tuple(store.records.values())):
            outcome = dataclasses.replace(
                evaluation.outcome,
                metrics=(MetricValue("burn_time", 2.1 + i, "s"), MetricValue("average_thrust", 10, "N")),
            )
            store.records[proposal.candidate_id] = proposal, dataclasses.replace(evaluation, outcome=outcome), context
        recommendations = recommended_designs(store)
        self.assertEqual(len(recommendations), 5)
        self.assertEqual([r.evaluation.score for r in recommendations], [0, 1, 2, 3, 4])

    def test_error_warning_policy_uses_existing_objective(self):
        p = problem(reject_warnings=True)
        strategy = SmartSearchStrategy(p.plan)
        proposal = strategy.ask()
        evaluation = fake_evaluation(proposal, warnings=True)
        from designassistant import MetricValue

        outcome = dataclasses.replace(
            evaluation.outcome, metrics=evaluation.outcome.metrics + (MetricValue("maximum_diameter", 0.1, "m"),)
        )
        evaluated = Objective(MetricRegistry(QUICK_METRICS)).evaluate(outcome, p.plan.variants[0].requirements)
        self.assertFalse(evaluated.constraints.feasible)
        self.assertIsNone(evaluated.score)
        accepted = Objective(MetricRegistry(QUICK_METRICS)).evaluate(
            outcome, dataclasses.replace(p.plan.variants[0].requirements, reject_warnings=False)
        )
        self.assertTrue(accepted.constraints.feasible)


if __name__ == "__main__":
    unittest.main()
