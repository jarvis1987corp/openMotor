"""Smart inputs, metadata spaces, deterministic strategies and objective data."""

import copy
import dataclasses
import math
import random
import unittest
from unittest.mock import patch

from designassistant import (
    CandidateEvaluation,
    CoarseToFineSearchStrategy,
    ConstraintEvaluation,
    EngineAdapter,
    LibraryEntry,
    MetricConstraint,
    MetricRegistry,
    MetricValue,
    Objective,
    OutcomeStatus,
    SearchSpaceBuilder,
    SimulationOutcome,
    SmartDesignRequirements,
    SmartResultStore,
    SmartSearchStrategy,
    Snapshot,
    Target,
    analyze_candidate,
)
from designassistant.models import diagnostic
from motorlib.motor import Motor
from test.designassistant.support import fixture_names, fixture_snapshot
from test.designassistant.test_core import requirements, variable


def smart_inputs(**changes):
    baseline = fixture_snapshot()
    entry = LibraryEntry.from_dict(baseline["propellant"])
    values = dict(
        maximum_diameter=0.15, targets=(Target("burn_time", 2.0, 1.0),), library_keys=(entry.key,), budget=12, seed=93
    )
    values.update(changes)
    return baseline, (entry,), SmartDesignRequirements(**values)


def plan(**changes):
    baseline, entries, inputs = smart_inputs(**changes)
    return SearchSpaceBuilder().build(baseline, inputs, entries)


def fake_evaluation(proposal, score=None, *, valid=True, warnings=False):
    metrics = (MetricValue("burn_time", 2.1, "s"), MetricValue("average_thrust", 10.0, "N")) if valid else ()
    outcome = SimulationOutcome(
        proposal.candidate_id,
        OutcomeStatus.COMPLETED if valid else OutcomeStatus.ENGINE_FAILED,
        valid,
        valid,
        metrics,
        (diagnostic("warn", "A warning", level="WARNING"),) if warnings else (),
    )
    if score is None and valid:
        score = sum(a.value for a in proposal.assignments)
    return CandidateEvaluation(outcome, ConstraintEvaluation(proposal.candidate_id, valid), score if valid else None)


def run_fake(strategy, *, invalid=False):
    proposals, stages = [], []
    while (proposal := strategy.ask()) is not None:
        proposals.append(proposal)
        if isinstance(strategy, CoarseToFineSearchStrategy):
            stages.append(strategy.stage_for(proposal.candidate_id))
        else:
            stages.append(strategy.context_for(proposal.candidate_id).stage)
        strategy.tell(fake_evaluation(proposal, valid=not invalid))
    return tuple(proposals), tuple(stages)


class SmartRequirementsTests(unittest.TestCase):
    def test_partial_requirements_need_only_diameter_one_target_and_library(self):
        _, _, req = smart_inputs()
        self.assertEqual(len(req.targets), 1)
        self.assertEqual(req.constraints, ())
        self.assertFalse(req.reject_warnings)

    def test_no_targets_is_underdefined(self):
        with self.assertRaisesRegex(ValueError, "Enable at least one target"):
            smart_inputs(targets=())

    def test_diameter_must_be_positive_and_finite(self):
        for value in (0, -1, math.inf, math.nan, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                smart_inputs(maximum_diameter=value)

    def test_no_library_selection(self):
        with self.assertRaisesRegex(ValueError, "library entry"):
            smart_inputs(library_keys=())

    def test_no_geometry_selection(self):
        with self.assertRaisesRegex(ValueError, "grain geometry"):
            smart_inputs(geometries=())

    def test_target_outside_constraints(self):
        with self.assertRaisesRegex(ValueError, "outside"):
            smart_inputs(constraints=(MetricConstraint("burn_time", maximum=1),))

    def test_repeated_constraints_intersection(self):
        with self.assertRaisesRegex(ValueError, "contradict"):
            smart_inputs(
                constraints=(
                    MetricConstraint("average_thrust", minimum=5),
                    MetricConstraint("average_thrust", maximum=4),
                )
            )

    def test_budget_seed_and_top_n_validation(self):
        for changes in (
            {"budget": 0},
            {"budget": 10001},
            {"budget": True},
            {"seed": 1.5},
            {"top_n": 0},
            {"top_n": 101},
            {"top_n": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                smart_inputs(**changes)

    def test_zero_negative_targets_and_unknown_metric(self):
        for target in (Target("burn_time", 0, 1), Target("burn_time", -1, 1), Target("unknown", 1, 1)):
            with self.subTest(target=target), self.assertRaises(ValueError):
                smart_inputs(targets=(target,))

    def test_digest_contains_seed_budget_limits_and_targets(self):
        original = smart_inputs()[2]
        for changes in (
            {"seed": 1},
            {"budget": 15},
            {"maximum_diameter": 0.1},
            {"top_n": 2},
            {"targets": (Target("total_impulse", 100, 10),)},
        ):
            self.assertNotEqual(original.digest, smart_inputs(**changes)[2].digest)
        self.assertEqual(original.digest, smart_inputs()[2].digest)


class SearchSpaceTests(unittest.TestCase):
    def test_stable_paths_metadata_and_engine_bounds(self):
        built = plan(maximum_diameter=0.06)
        variant = built.variants[0]
        motor = Motor(variant.baseline.to_dict())
        self.assertTrue(variant.requirements.variables)
        for var in variant.requirements.variables:
            prop = var.path.resolve(motor)
            self.assertGreaterEqual(var.range.minimum, prop.min)
            self.assertLessEqual(var.range.maximum, prop.max)
            self.assertFalse(var.path.value.startswith(("config.", "propellant.")))
            if var.path.value.endswith(".diameter") or var.path.value in ("nozzle.throat", "nozzle.exit"):
                self.assertLessEqual(var.range.maximum, 0.06)
        self.assertEqual(motor.config.getProperties(), built.baseline.to_dict()["config"])

    def test_smaller_envelope_scales_radial_search_space_without_changing_baseline(self):
        built = plan(maximum_diameter=0.02)
        search = SmartSearchStrategy(built)
        request = search.request_for(search.ask())
        candidate = Motor(request.snapshot.to_dict())
        self.assertTrue(request.valid)
        for grain in candidate.grains:
            self.assertLessEqual(grain.getProperty("diameter"), 0.02)
            self.assertLess(grain.getProperty("coreDiameter"), grain.getProperty("diameter"))
            self.assertFalse(any(a.level.name == "ERROR" for a in grain.getGeometryErrors()))
        self.assertEqual(built.baseline, Snapshot.from_dict(fixture_snapshot()))

    def test_baseline_and_library_never_mutated(self):
        baseline, entries, req = smart_inputs()
        before = copy.deepcopy(baseline)
        library_before = entries[0].snapshot
        built = SearchSpaceBuilder().build(baseline, req, entries)
        strategy = SmartSearchStrategy(built)
        proposals, _ = run_fake(strategy)
        for proposal in proposals:
            request = strategy.request_for(proposal)
            data = request.snapshot.to_dict()
            data["propellant"]["tabs"][0]["a"] = -999
            data["config"]["timestep"] = 999
            data["grains"][0]["properties"]["diameter"] = 999
        self.assertEqual(baseline, before)
        self.assertEqual(entries[0].snapshot, library_before)
        self.assertEqual(built.baseline.to_dict(), before)

    def test_exact_existing_library_options_and_fair_budget(self):
        baseline, entries, req = smart_inputs(budget=15, top_n=2)
        second = next(
            LibraryEntry.from_dict(fixture_snapshot(n)["propellant"])
            for n in fixture_names()
            if fixture_snapshot(n)["propellant"] != baseline["propellant"]
        )
        req = dataclasses.replace(req, library_keys=(entries[0].key, second.key))
        built = SearchSpaceBuilder().build(baseline, req, (*entries, second))
        self.assertEqual(len(built.variants), 2)
        self.assertEqual(
            {v.baseline.to_dict()["propellant"]["name"] for v in built.variants}, {entries[0].name, second.name}
        )
        search = SmartSearchStrategy(built)
        proposals, _ = run_fake(search)
        counts = [
            sum(
                search.context_for(p.candidate_id).variant_key == v.key
                and search.context_for(p.candidate_id).stage != "verification"
                for p in proposals
            )
            for v in built.variants
        ]
        self.assertLessEqual(abs(counts[0] - counts[1]), 1)
        self.assertEqual(len(proposals), 15)

    def test_unknown_library_entry_rejected(self):
        baseline, entries, req = smart_inputs(library_keys=("unknown",))
        with self.assertRaisesRegex(ValueError, "not present"):
            SearchSpaceBuilder().build(baseline, req, entries)

    def test_library_setter_rejection_is_not_silent(self):
        baseline, _, req = smart_inputs()
        invalid = copy.deepcopy(baseline["propellant"])
        invalid["density"] = -1
        entry = LibraryEntry.from_dict(invalid)
        req = dataclasses.replace(req, library_keys=(entry.key,))
        with self.assertRaisesRegex(ValueError, "rejected"):
            SearchSpaceBuilder().build(baseline, req, (entry,))

    def test_library_identity_cannot_be_forged(self):
        entry = smart_inputs()[1][0]
        with self.assertRaises(ValueError):
            dataclasses.replace(entry, key="bad")
        with self.assertRaises(ValueError):
            dataclasses.replace(entry, name="invented")

    def test_compatible_geometries_preserve_count_common_properties_and_config(self):
        baseline, entries, req = smart_inputs()
        geometries = SearchSpaceBuilder.compatible_geometries(baseline)
        self.assertIn("current", geometries)
        self.assertIn("End Burner", geometries)
        self.assertNotIn("Custom", geometries)
        req = dataclasses.replace(req, geometries=("current", "End Burner"))
        built = SearchSpaceBuilder().build(baseline, req, entries)
        for variant in built.variants:
            data = variant.baseline.to_dict()
            self.assertEqual(len(data["grains"]), len(baseline["grains"]))
            self.assertEqual(data["config"], baseline["config"])
            self.assertEqual(data["grains"][0]["properties"]["length"], baseline["grains"][0]["properties"]["length"])

    def test_missing_geometry_parameters_are_not_invented(self):
        baseline, entries, req = smart_inputs(geometries=("Finocyl",))
        with self.assertRaisesRegex(ValueError, "absent"):
            SearchSpaceBuilder().build(baseline, req, entries)

    def test_budget_covers_every_option(self):
        baseline, entries, req = smart_inputs(geometries=("current", "End Burner"), budget=1)
        with self.assertRaisesRegex(ValueError, "Increase"):
            SearchSpaceBuilder().build(baseline, req, entries)

    def test_grains_required_but_library_can_supply_missing_baseline_propellant(self):
        baseline, entries, req = smart_inputs()
        baseline["propellant"] = None
        self.assertEqual(len(SearchSpaceBuilder().build(baseline, req, entries).variants), 1)
        baseline["grains"] = []
        with self.assertRaisesRegex(ValueError, "grain"):
            SearchSpaceBuilder().build(baseline, req, entries)

    def test_every_existing_fixture_builds_space_without_mutation(self):
        for name in fixture_names():
            with self.subTest(name=name):
                baseline = fixture_snapshot(name)
                entry = LibraryEntry.from_dict(baseline["propellant"])
                before = copy.deepcopy(baseline)
                req = SmartDesignRequirements(1.0, (Target("burn_time", 2, 1),), library_keys=(entry.key,), budget=4)
                built = SearchSpaceBuilder().build(baseline, req, (entry,))
                self.assertEqual(baseline, before)
                self.assertEqual(built.variants[0].baseline, Snapshot.from_dict(baseline))


class CoarseToFineTests(unittest.TestCase):
    def make_search(self, **kwargs):
        values = dict(seed=91, budget=20, top_n=3)
        values.update(kwargs)
        return CoarseToFineSearchStrategy(requirements(variable()), **values)

    def test_stages_budget_finalist_replay(self):
        search = self.make_search()
        proposals, stages = run_fake(search)
        self.assertEqual(len(proposals), 20)
        self.assertEqual(set(stages), {"exploration", "refinement", "verification"})
        self.assertEqual(stages, tuple(sorted(stages, key=("exploration", "refinement", "verification").index)))
        by_id = {p.candidate_id: p for p in proposals}
        for proposal in proposals:
            original = search.verification_source(proposal.candidate_id)
            if original:
                self.assertEqual(proposal.assignments, by_id[original].assignments)

    def test_same_seed_complete_trace_is_identical(self):
        self.assertEqual(run_fake(self.make_search()), run_fake(self.make_search()))
        self.assertNotEqual(run_fake(self.make_search()), run_fake(self.make_search(seed=92)))

    def test_no_global_random_state(self):
        before = random.getstate()
        run_fake(self.make_search())
        self.assertEqual(random.getstate(), before)

    def test_completion_order_independent_selection(self):
        def trace(reverse):
            search = self.make_search()
            proposals = []
            while not search.exhausted:
                pending = []
                while (p := search.ask()) is not None:
                    pending.append(p)
                    proposals.append(p)
                for p in reversed(pending) if reverse else pending:
                    search.tell(fake_evaluation(p))
            return tuple(proposals)

        self.assertEqual(trace(False), trace(True))

    def test_invalid_candidates_cannot_select_elite_regions(self):
        search = self.make_search()
        proposals, stages = run_fake(search, invalid=True)
        self.assertTrue(proposals)
        self.assertNotIn("verification", stages)
        self.assertFalse(search.ranked)

    def test_small_budgets_and_fixed_integer_ranges(self):
        for budget in (1, 2, 3, 4, 20):
            req = requirements(variable("grains.0.finCount", 2, 2, 1, True))
            search = CoarseToFineSearchStrategy(req, seed=1, budget=budget)
            proposals, _ = run_fake(search)
            self.assertLessEqual(len(proposals), budget)
            self.assertTrue(all(p.assignments[0].value == 2 for p in proposals))

    def test_initial_baseline_proposal_is_clamped_and_validated(self):
        search = self.make_search(initial_values=(0.015,))
        self.assertEqual(search.ask().assignments[0].value, 0.015)
        with self.assertRaises(ValueError):
            self.make_search(initial_values=(0.5,))

    def test_tell_rejects_duplicate_completions(self):
        search = self.make_search()
        proposal = search.ask()
        search.tell(fake_evaluation(proposal))
        with self.assertRaises(ValueError):
            search.tell(fake_evaluation(proposal))

    def test_smart_round_robin_is_seeded_and_uses_distinct_contexts(self):
        built = plan(geometries=("current", "End Burner"), budget=16)
        self.assertEqual(run_fake(SmartSearchStrategy(built)), run_fake(SmartSearchStrategy(built)))


class SmartResultsTests(unittest.TestCase):
    def setUp(self):
        self.plan = plan(budget=30)
        self.search = SmartSearchStrategy(self.plan)
        self.proposals, _ = run_fake(self.search)
        self.store = self.search.results

    def test_top_n_sorted_score_and_stable_ties(self):
        ranked = self.store.ranked()
        self.assertEqual([r.evaluation.score for r in ranked], sorted(r.evaluation.score for r in ranked))
        self.assertLessEqual(len(self.store.top), 10)
        self.assertEqual([r.rank for r in ranked], list(range(1, len(ranked) + 1)))
        self.assertEqual(self.store.ranked(2), ranked[:2])

    def test_verification_does_not_duplicate_same_motor(self):
        ranked = self.store.ranked()
        keys = [(r.variant.key, r.proposal.assignments) for r in ranked]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertTrue(any(r.context.stage == "verification" for r in ranked))

    def test_failed_recheck_removes_previous_motor_from_ranking(self):
        verified = next(r for r in self.store.ranked() if r.context.stage == "verification")
        self.store.append(verified.proposal, fake_evaluation(verified.proposal, valid=False), verified.context)
        self.assertFalse(any(r.proposal.assignments == verified.proposal.assignments for r in self.store.ranked()))

    def test_arrival_order_does_not_change_ranking(self):
        other = SmartResultStore(self.plan)
        other.finalized = self.store.finalized
        for record in reversed(tuple(self.store.records.values())):
            other.append(*record)
        self.assertEqual(other.ranked(), self.store.ranked())

    def test_explanations_derive_from_targets_and_constraint_margins(self):
        req = dataclasses.replace(
            self.plan.variants[0].requirements,
            targets=(Target("burn_time", 2, 1, 2), Target("average_thrust", 20, 5, 1)),
            constraints=(MetricConstraint("average_thrust", 1, 30),),
        )
        evaluation = fake_evaluation(self.proposals[0])
        analysis = analyze_candidate(evaluation, req, verified=True)
        self.assertAlmostEqual(analysis.targets[0].deviation, 0.1)
        self.assertEqual(analysis.targets[1].deviation, -10)
        self.assertAlmostEqual(analysis.targets[1].contribution, 2 / 3)
        self.assertGreater(analysis.constraints[0].normalized_margin, 0)
        sources = [m.source for m in analysis.explanations]
        self.assertTrue(any("Closest target" in m for m in sources))
        self.assertTrue(any("trade-off" in m for m in sources))
        self.assertTrue(any("constraint margin" in m for m in sources))
        self.assertTrue(any("Rechecked" in m for m in sources))

    def test_compare_two_to_five_ranked_candidates(self):
        ids = tuple(r.proposal.candidate_id for r in self.store.top[:3])
        comparison = self.store.compare(ids)
        self.assertEqual(tuple(r.proposal.candidate_id for r in comparison), ids)
        for selected in ((ids[0],), (ids[0], ids[0]), (*ids, "bad"), tuple(str(i) for i in range(6))):
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                self.store.compare(selected)

    def test_warning_and_error_policy_matches_existing_objective(self):
        req = self.plan.variants[0].requirements
        outcome = fake_evaluation(self.proposals[0], warnings=True).outcome
        accepted = Objective().evaluate(outcome, req)
        self.assertIsNotNone(accepted.score)
        rejected = Objective().evaluate(outcome, dataclasses.replace(req, reject_warnings=True))
        self.assertIsNone(rejected.score)
        error = dataclasses.replace(
            outcome, status=OutcomeStatus.INVALID_RESULT, valid=False, diagnostics=(diagnostic("error", "Error"),)
        )
        self.assertIsNone(Objective().evaluate(error, req).score)

    def test_candidate_error_does_not_end_following_proposals(self):
        search = SmartSearchStrategy(plan())
        first = search.ask()
        search.tell(fake_evaluation(first, valid=False))
        proposals, _ = run_fake(search)
        self.assertTrue(proposals)
        self.assertTrue(search.results.top)


class SmartEngineTests(unittest.TestCase):
    def test_initial_smart_candidates_match_direct_engine_on_all_18_fixtures(self):
        registry = MetricRegistry()
        for name in fixture_names():
            with self.subTest(name=name):
                baseline = fixture_snapshot(name)
                original = copy.deepcopy(baseline)
                entry = LibraryEntry.from_dict(baseline["propellant"])
                req = SmartDesignRequirements(1, (Target("burn_time", 2, 1),), library_keys=(entry.key,), budget=4)
                built = SearchSpaceBuilder().build(baseline, req, (entry,))
                search = SmartSearchStrategy(built)
                proposal = search.ask()
                request = search.request_for(proposal)
                # Existing Motor setters normalize absent/default FloatProperty
                # integer zero to 0.0 when reconstructing any candidate.
                self.assertEqual(request.snapshot, Snapshot.from_dict(Motor(copy.deepcopy(baseline)).getDict()))
                direct = Motor(copy.deepcopy(baseline)).runSimulation()
                adapted = EngineAdapter().run(request)
                self.assertEqual(adapted.engine_success, direct.success)
                if adapted.valid:
                    self.assertEqual(adapted.metrics, registry.extract(direct))
                self.assertEqual(baseline, original)

    def test_rejected_setter_stays_before_simulation(self):
        search = SmartSearchStrategy(plan())
        first = search.ask()
        second = search.ask()
        search.tell(fake_evaluation(first))
        original = Motor

        def reject(data):
            motor = original(data)
            motor.nozzle.props["throat"].setValue = lambda _: None
            return motor

        with patch("designassistant.generator.Motor", side_effect=reject):
            request = search.request_for(second)
        self.assertFalse(request.valid)
        with patch.object(Motor, "runSimulation") as simulation:
            outcome = EngineAdapter().run(request)
        simulation.assert_not_called()
        self.assertEqual(outcome.status, OutcomeStatus.INVALID_REQUEST)

    def test_hundreds_of_proposals_leave_baseline_and_config_unchanged(self):
        built = plan(budget=400)
        before = built.baseline
        search = SmartSearchStrategy(built)
        count = 0
        while (proposal := search.ask()) is not None:
            request = search.request_for(proposal)
            self.assertTrue(request.valid)
            self.assertEqual(request.snapshot.to_dict()["config"], before.to_dict()["config"])
            search.tell(fake_evaluation(proposal))
            count += 1
        self.assertEqual(count, 400)
        self.assertEqual(built.baseline, before)
