"""Isolation, validation, feasibility and ask/tell contracts."""

import ast
import copy
import dataclasses
import json
import math
import pickle
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from designassistant import (
    Assignment,
    CandidateEvaluation,
    CandidateGenerator,
    CandidateProposal,
    ConstraintEvaluation,
    ConstraintEvaluator,
    DesignRequirements,
    DesignVariable,
    Diagnostic,
    EngineAdapter,
    GridSearchStrategy,
    MetricConstraint,
    MetricDefinition,
    MetricRegistry,
    MetricValue,
    Objective,
    OutcomeStatus,
    ParameterRange,
    PropertyPath,
    PropertyValidationError,
    RandomSearchStrategy,
    SimulationOutcome,
    Snapshot,
    Target,
    TextRecord,
    engine_fingerprint,
)
from motorlib.grains import Finocyl
from motorlib.localization import QT_TRANSLATE_NOOP
from motorlib.motor import Motor
from test.designassistant.support import ROOT, fixture_snapshot


def variable(path="nozzle.throat", minimum=0.01, maximum=0.02, points=3, integer=False):
    return DesignVariable(PropertyPath(path), ParameterRange(minimum, maximum, points, integer))


def requirements(*variables, targets=None, constraints=(), reject_warnings=False):
    if targets is None:
        targets = (Target("burn_time", 2.0, 2.0),)
    return DesignRequirements(variables, targets, constraints, reject_warnings)


def completed(candidate_id="candidate", **metrics):
    if not metrics:
        metrics = {"burn_time": 3.0, "maximum_pressure": 10.0}
    return SimulationOutcome(
        candidate_id, OutcomeStatus.COMPLETED, True, True, tuple(MetricValue(k, v, "") for k, v in metrics.items())
    )


def evaluation(candidate_id, score=1.0):
    outcome = completed(candidate_id)
    return CandidateEvaluation(outcome, ConstraintEvaluation(candidate_id, True), score)


class RangeAndPathTests(unittest.TestCase):
    def test_range_validation(self):
        for args in (
            (math.nan, 1),
            (0, math.inf),
            (2, 1),
            (0, 1, 0),
            (0, 1, True),
            (0, 1, 1),
            (0, 0, 2),
            (0, 1, 3, True),
            (0.5, 1, 2, True),
            (-1e308, 1e308),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                ParameterRange(*args)

    def test_float_grid_endpoints(self):
        self.assertEqual(ParameterRange(0.1, 0.3, 3).grid_values(), (0.1, 0.2, 0.3))
        self.assertEqual(ParameterRange(2, 2, 1).grid_values(), (2.0,))

    def test_integer_grid_is_distinct_and_integral(self):
        values = ParameterRange(1, 10, 4, True).grid_values()
        self.assertEqual(values, (1, 4, 7, 10))
        self.assertTrue(all(type(v) is int for v in values))

    def test_precision_collapsed_grid_rejected(self):
        bounds = ParameterRange(1.0, math.nextafter(1.0, math.inf), 3)
        with self.assertRaises(ValueError):
            bounds.grid_values()

    def test_invalid_path_syntax(self):
        for path in (
            "",
            "Nozzle.Throat Diameter",
            "nozzle",
            "grains.-1.length",
            "grains.01.length",
            "grains.True.length",
            "grains.0.properties.length",
            "grains.0.type",
            "__dict__.nozzle",
            "propellant.tabs.0.a",
            "nozzle.throat.extra",
        ):
            # 'type' has valid syntax but must fail resolution, below.
            if path == "grains.0.type":
                continue
            with self.subTest(path=path), self.assertRaises(PropertyValidationError):
                PropertyPath(path)

    def test_unknown_property_and_grain(self):
        motor = Motor(fixture_snapshot())
        for path in ("nozzle.unknown", "grains.999.length", "grains.0.type", "config.unknown", "propellant.unknown"):
            with self.subTest(path=path), self.assertRaises(PropertyValidationError):
                PropertyPath(path).read(motor)
        motor.propellant = None
        with self.assertRaises(PropertyValidationError):
            PropertyPath("propellant.density").read(motor)

    def test_numeric_values_and_silent_int_truncation(self):
        motor = Motor(fixture_snapshot())
        path = PropertyPath("config.mapDim")
        before = path.read(motor)
        for value in (250.5, True, "500", math.nan, math.inf, 249, 2001):
            with self.subTest(value=value), self.assertRaises(PropertyValidationError):
                path.write_validated(motor, value)
            self.assertEqual(path.read(motor), before)
        self.assertEqual(path.write_validated(motor, 500.0), 500)
        self.assertIs(type(path.read(motor)), int)

    def test_enum_canonical_values(self):
        motor = Motor(fixture_snapshot())
        path = PropertyPath("grains.0.inhibitedEnds")
        self.assertEqual(path.write_validated(motor, "Both"), "Both")
        for value in ("Оба", "both", "unknown", 1):
            with self.subTest(value=value), self.assertRaises(PropertyValidationError):
                path.write_validated(motor, value)
        self.assertEqual(path.read(motor), "Both")

    def test_enum_silent_rejection_read_back(self):
        motor = Motor(fixture_snapshot())
        path = PropertyPath("grains.0.inhibitedEnds")
        prop = path.resolve(motor)
        other = next(v for v in prop.values if v != prop.getValue())
        with patch.object(prop, "setValue", return_value=None), self.assertRaises(PropertyValidationError) as error:
            path.write_validated(motor, other)
        self.assertEqual(error.exception.code, "setter_rejected")

    def test_nested_reads_are_copies(self):
        motor = Motor(fixture_snapshot("regression/custom/motor.ric"))
        path = PropertyPath("grains.0.points")
        before = copy.deepcopy(motor.getDict())
        polygons = path.read(motor)
        polygons[0].append([999, 999])
        self.assertEqual(motor.getDict(), before)
        with self.assertRaises(PropertyValidationError):
            path.write_validated(motor, polygons)


class CandidateTests(unittest.TestCase):
    def setUp(self):
        self.baseline = fixture_snapshot()
        self.req = requirements(variable())
        self.generator = CandidateGenerator(self.baseline, self.req)

    def test_input_and_generator_baseline_are_independent(self):
        original = copy.deepcopy(self.baseline)
        self.baseline["nozzle"]["throat"] = 0
        returned = self.generator.baseline_snapshot
        returned["config"]["mapDim"] = 999
        self.assertEqual(self.generator.baseline_snapshot, original)

    def test_candidate_snapshots_are_independent(self):
        a = self.generator.generate(CandidateProposal.from_values("a", {"nozzle.throat": 0.01}))
        b = self.generator.generate(CandidateProposal.from_values("b", {"nozzle.throat": 0.02}))
        self.assertTrue(a.valid and b.valid)
        motor_a, motor_b = Motor(a.snapshot.to_dict()), Motor(b.snapshot.to_dict())
        motor_a.nozzle.setProperty("throat", 0.03)
        motor_a.grains[0].setProperty("length", 0.05)
        motor_a.config.setProperty("mapDim", 500)
        motor_a.propellant.setProperty("density", 1000)
        motor_a.propellant.props["tabs"].tabs[0].setProperty("a", 0.001)
        self.assertEqual(motor_b.getDict(), b.snapshot.to_dict())
        self.assertEqual(a.snapshot.to_dict()["nozzle"]["throat"], 0.01)
        self.assertEqual(self.generator.baseline_snapshot, self.baseline)

    def test_polygon_deepcopy_at_motor_construction(self):
        baseline = fixture_snapshot("regression/custom/motor.ric")
        # Exercise mutable coordinate pairs too; .ric also supports tuple pairs.
        baseline["grains"][0]["properties"]["points"] = [
            [list(point) for point in polygon] for polygon in baseline["grains"][0]["properties"]["points"]
        ]
        original = copy.deepcopy(baseline)
        generator = CandidateGenerator(baseline, DesignRequirements())
        baseline["grains"][0]["properties"]["points"][0][0][0] = 999
        motors = []

        def capture(snapshot):
            motor = Motor(snapshot)
            motors.append(motor)
            return motor

        with patch("designassistant.generator.Motor", side_effect=capture):
            a = generator.generate(CandidateProposal("a"))
            b = generator.generate(CandidateProposal("b"))
        original_b = copy.deepcopy(motors[1].getDict())
        points = motors[0].grains[0].getProperty("points")
        points[0][0][0] = 777
        points[0].append([888, 888])
        self.assertEqual(generator.baseline_snapshot, original)
        self.assertEqual(motors[1].getDict(), original_b)
        self.assertEqual(Snapshot.from_dict(motors[1].getDict()), b.snapshot)
        self.assertEqual(a.snapshot, b.snapshot)

    def test_hundreds_of_candidates_leave_all_baseline_properties_unchanged(self):
        baseline = fixture_snapshot("regression/custom/motor.ric")
        original = copy.deepcopy(baseline)
        generator = CandidateGenerator(baseline, self.req)
        search = RandomSearchStrategy(self.req, seed=1234, budget=500)
        for _ in range(500):
            request = generator.generate(search.ask())
            self.assertTrue(request.valid)
            candidate = Motor(request.snapshot.to_dict())
            candidate.nozzle.setProperty("throat", 0)
            candidate.config.setProperty("mapDim", 500)
            candidate.propellant.setProperty("density", 1000)
            candidate.propellant.props["tabs"].tabs[0].setProperty("a", 0.001)
            candidate.grains[0].setProperty("length", 0.05)
            candidate.grains[0].getProperty("points")[0].append([999, 999])
        self.assertEqual(baseline, original)
        self.assertEqual(generator.baseline_snapshot, original)

    def test_grain_numeric_variable(self):
        req = requirements(variable("grains.0.length", 0.02, 0.04))
        request = CandidateGenerator(self.baseline, req).generate(
            CandidateProposal.from_values("a", {"grains.0.length": 0.03})
        )
        self.assertTrue(request.valid)
        self.assertEqual(request.snapshot.to_dict()["grains"][0]["properties"]["length"], 0.03)
        self.assertEqual(request.snapshot.to_dict()["propellant"], self.baseline["propellant"])
        self.assertEqual(request.snapshot.to_dict()["config"], self.baseline["config"])

    def test_integer_geometry_variable(self):
        baseline = copy.deepcopy(self.baseline)
        baseline["grains"] = [{"type": "Finocyl", "properties": Finocyl().getProperties()}]
        req = requirements(variable("grains.0.numFins", 1, 5, 3, True))
        generator = CandidateGenerator(baseline, req)
        request = generator.generate(CandidateProposal.from_values("a", {"grains.0.numFins": 3}))
        self.assertTrue(request.valid)
        self.assertEqual(request.snapshot.to_dict()["grains"][0]["properties"]["numFins"], 3)
        request = generator.generate(CandidateProposal.from_values("b", {"grains.0.numFins": 3.5}))
        self.assertFalse(request.valid)
        with self.assertRaises(PropertyValidationError):
            CandidateGenerator(baseline, requirements(variable("grains.0.numFins", 1, 5)))

    def test_fixed_and_non_numeric_variables_rejected(self):
        for path in ("config.timestep", "config.mapDim", "propellant.density", "grains.0.inhibitedEnds"):
            with self.subTest(path=path), self.assertRaises(PropertyValidationError):
                CandidateGenerator(self.baseline, requirements(variable(path)))
        baseline = fixture_snapshot("regression/custom/motor.ric")
        with self.assertRaises(PropertyValidationError):
            CandidateGenerator(baseline, requirements(variable("grains.0.points")))

    def test_unknown_variable_definition_rejected(self):
        for path in ("nozzle.unknown", "grains.999.length"):
            with self.subTest(path=path), self.assertRaises(PropertyValidationError):
                CandidateGenerator(self.baseline, requirements(variable(path)))

    def test_variable_engine_bounds_rejected(self):
        with self.assertRaises(PropertyValidationError):
            CandidateGenerator(self.baseline, requirements(variable("nozzle.throat", -1, 1)))

    def test_out_of_range_nan_inf_assignments_invalid(self):
        for value in (0.001, 0.03, math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                request = self.generator.generate(CandidateProposal.from_values("bad", {"nozzle.throat": value}))
                self.assertFalse(request.valid)
                self.assertIsNone(request.snapshot)
                self.assertEqual(request.diagnostics[0].code, "out_of_range")

    def test_rejected_setter_blocks_simulation(self):
        def reject(snapshot):
            motor = Motor(snapshot)
            motor.nozzle.props["throat"].setValue = lambda value: None
            return motor

        with patch("designassistant.generator.Motor", side_effect=reject):
            request = self.generator.generate(CandidateProposal.from_values("bad", {"nozzle.throat": 0.02}))
        self.assertEqual(request.diagnostics[0].code, "setter_rejected")
        with patch.object(Motor, "runSimulation") as run:
            outcome = EngineAdapter().run(request)
        run.assert_not_called()
        self.assertEqual(outcome.status, OutcomeStatus.INVALID_REQUEST)

    def test_modified_setter_value_blocks_simulation(self):
        def alter(snapshot):
            motor = Motor(snapshot)
            prop = motor.nozzle.props["throat"]
            original = prop.setValue
            prop.setValue = lambda value: original(value + 0.00001)
            return motor

        with patch("designassistant.generator.Motor", side_effect=alter):
            request = self.generator.generate(CandidateProposal.from_values("bad", {"nozzle.throat": 0.02}))
        self.assertFalse(request.valid)
        self.assertEqual(request.diagnostics[0].code, "setter_rejected")

    def test_setter_exception_is_candidate_local(self):
        def fail(snapshot):
            motor = Motor(snapshot)
            motor.nozzle.props["throat"].setValue = lambda value: (_ for _ in ()).throw(RuntimeError("setter failure"))
            return motor

        with patch("designassistant.generator.Motor", side_effect=fail):
            request = self.generator.generate(CandidateProposal.from_values("bad", {"nozzle.throat": 0.02}))
        self.assertFalse(request.valid)
        self.assertTrue(self.generator.generate(CandidateProposal.from_values("good", {"nozzle.throat": 0.02})).valid)

    def test_unknown_missing_undeclared_and_duplicate_assignments(self):
        proposals = (
            (CandidateProposal("missing"), "missing_assignment"),
            (CandidateProposal.from_values("unknown", {"nozzle.missing": 1}), "invalid_path"),
            (CandidateProposal.from_values("fixed", {"config.timestep": 0.01}), "undeclared_variable"),
            (
                CandidateProposal(
                    "duplicate",
                    (Assignment(PropertyPath("nozzle.throat"), 0.01), Assignment(PropertyPath("nozzle.throat"), 0.02)),
                ),
                "duplicate_assignment",
            ),
        )
        for proposal, code in proposals:
            with self.subTest(code=code):
                request = self.generator.generate(proposal)
                self.assertFalse(request.valid)
                self.assertIn(code, [d.code for d in request.diagnostics])

    def test_no_shared_runtime_grain_state(self):
        motors = []

        def capture(snapshot):
            motor = Motor(snapshot)
            motors.append(motor)
            return motor

        with patch("designassistant.generator.Motor", side_effect=capture):
            for name in ("a", "b"):
                self.generator.generate(CandidateProposal.from_values(name, {"nozzle.throat": 0.01}))
        for a, b in zip(motors[0].grains, motors[1].grains):
            self.assertIsNot(a, b)
            self.assertIsNot(a.props, b.props)


class EvaluationTests(unittest.TestCase):
    def test_relative_weighted_and_worst_deviation(self):
        req = requirements(targets=(Target("burn_time", 2, 2, 1), Target("maximum_pressure", 6, 4, 3)))
        result = Objective().evaluate(completed(), req)
        self.assertTrue(result.constraints.feasible)
        self.assertAlmostEqual(result.score, 31 / 48)

    def test_exact_target_zero_score(self):
        result = Objective().evaluate(completed(burn_time=2.0), requirements())
        self.assertEqual(result.score, 0)

    def test_zero_weight_target_is_ignored(self):
        req = requirements(targets=(Target("burn_time", 2, 2), Target("maximum_pressure", 1, 1, 0)))
        self.assertEqual(Objective().evaluate(completed(burn_time=3), req).score, 0.5)

    def test_constraints_inclusive_bounds(self):
        req = requirements(constraints=(MetricConstraint("maximum_pressure", 10, 10),))
        self.assertTrue(ConstraintEvaluator().evaluate(completed(), req).feasible)

    def test_constraint_failure_precedes_scoring(self):
        req = requirements(constraints=(MetricConstraint("maximum_pressure", maximum=9),))
        with patch("designassistant.evaluation.math.fsum", side_effect=AssertionError("must not score")):
            result = Objective().evaluate(completed(), req)
        self.assertFalse(result.constraints.feasible)
        self.assertIsNone(result.score)
        self.assertEqual(result.constraints.violations[0].code, "constraint_maximum")

    def test_minimum_constraint(self):
        req = requirements(constraints=(MetricConstraint("burn_time", minimum=4),))
        self.assertEqual(ConstraintEvaluator().evaluate(completed(), req).violations[0].code, "constraint_minimum")

    def test_invalid_engine_candidate_never_scores(self):
        outcome = SimulationOutcome("bad", OutcomeStatus.INVALID_RESULT, True, False)
        result = Objective().evaluate(outcome, requirements())
        self.assertFalse(result.constraints.feasible)
        self.assertIsNone(result.score)

    def test_warning_policy(self):
        warning = Diagnostic("engine_alert", "WARNING", TextRecord("SimulationAlerts", "Warning"))
        outcome = dataclasses.replace(completed(), diagnostics=(warning,))
        self.assertIsNotNone(Objective().evaluate(outcome, requirements()).score)
        self.assertIsNone(Objective().evaluate(outcome, requirements(reject_warnings=True)).score)

    def test_missing_constraint_metric(self):
        req = requirements(constraints=(MetricConstraint("maximum_pressure", maximum=20),))
        result = Objective().evaluate(completed(burn_time=3), req)
        self.assertIsNone(result.score)
        self.assertEqual(result.constraints.violations[0].code, "missing_metric")

    def test_missing_target_metric(self):
        result = Objective().evaluate(completed(maximum_pressure=10), requirements())
        self.assertIsNone(result.score)
        self.assertFalse(result.constraints.feasible)

    def test_unknown_metric_is_configuration_error(self):
        for req in (
            requirements(targets=(Target("unknown", 0, 1),)),
            requirements(constraints=(MetricConstraint("unknown", maximum=1),)),
        ):
            with self.subTest(req=req), self.assertRaises(ValueError):
                Objective().evaluate(completed(), req)

    def test_invalid_targets_constraints_and_weights(self):
        for args in (
            ("burn_time", math.nan, 1),
            ("burn_time", 1, 0),
            ("burn_time", 1, -1),
            ("burn_time", 1, 1, -1),
            ("burn_time", 1, 1, math.inf),
        ):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Target(*args)
        for args in (("burn_time",), ("burn_time", math.nan, 2), ("burn_time", 3, 2)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                MetricConstraint(*args)
        with self.assertRaises(ValueError):
            requirements(targets=(Target("burn_time", 0, 1, 0),))
        with self.assertRaises(ValueError):
            requirements(targets=(Target("burn_time", 0, 1, 1e308), Target("maximum_pressure", 0, 1, 1e308)))

    def test_score_overflow_is_ineligible(self):
        req = requirements(targets=(Target("burn_time", -1e308, 1e-308),))
        result = Objective().evaluate(completed(burn_time=1e308), req)
        self.assertIsNone(result.score)
        self.assertFalse(result.constraints.feasible)

    def test_empty_objective_and_duplicate_requirements(self):
        with self.assertRaises(ValueError):
            Objective().evaluate(completed(), requirements(targets=()))
        with self.assertRaises(ValueError):
            requirements(variable(), variable())
        with self.assertRaises(ValueError):
            requirements(targets=(Target("burn_time", 0, 1), Target("burn_time", 1, 1)))

    def test_illegal_competitive_scores_rejected(self):
        outcome = SimulationOutcome("bad", OutcomeStatus.INVALID_RESULT, True, False)
        with self.assertRaises(ValueError):
            CandidateEvaluation(outcome, ConstraintEvaluation("bad", False), 0)
        with self.assertRaises(ValueError):
            CandidateEvaluation(completed(), ConstraintEvaluation("other", True), 0)


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.req = requirements(variable("nozzle.throat", 0.01, 0.02, 2), variable("grains.0.length", 0.02, 0.04, 3))

    @staticmethod
    def all_proposals(search):
        proposals = []
        while (proposal := search.ask()) is not None:
            proposals.append(proposal)
        return proposals

    def test_grid_deterministic_order(self):
        a = self.all_proposals(GridSearchStrategy(self.req))
        b = self.all_proposals(GridSearchStrategy(self.req))
        self.assertEqual(a, b)
        self.assertEqual(
            [tuple(p.value for p in proposal.assignments) for proposal in a],
            [(0.01, 0.02), (0.01, 0.03), (0.01, 0.04), (0.02, 0.02), (0.02, 0.03), (0.02, 0.04)],
        )
        self.assertEqual(len({p.candidate_id for p in a}), 6)

    def test_zero_dimensional_grid_baseline_once(self):
        strategy = GridSearchStrategy(requirements())
        self.assertEqual(strategy.ask().assignments, ())
        self.assertIsNone(strategy.ask())
        self.assertTrue(strategy.exhausted)

    def test_random_same_seed_exact_assignments(self):
        a = self.all_proposals(RandomSearchStrategy(self.req, seed=42, budget=1000))
        b = self.all_proposals(RandomSearchStrategy(self.req, seed=42, budget=1000))
        c = self.all_proposals(RandomSearchStrategy(self.req, seed=43, budget=1000))
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        for proposal in a:
            for assignment, definition in zip(proposal.assignments, self.req.variables):
                self.assertTrue(definition.range.contains(assignment.value))

    def test_random_global_state_untouched(self):
        before = random.getstate()
        self.all_proposals(RandomSearchStrategy(self.req, seed=42, budget=20))
        self.assertEqual(random.getstate(), before)

    def test_integer_random_and_fixed_range(self):
        req = requirements(variable("grains.0.numFins", 1, 5, 3, True), variable("nozzle.throat", 0.01, 0.01, 1))
        proposals = self.all_proposals(RandomSearchStrategy(req, seed=17, budget=100))
        self.assertEqual({p.assignments[0].value for p in proposals}, set(range(1, 6)))
        self.assertTrue(all(type(p.assignments[0].value) is int and p.assignments[1].value == 0.01 for p in proposals))

    def test_out_of_order_tell_and_tie_ranking(self):
        a, b = GridSearchStrategy(self.req), GridSearchStrategy(self.req)
        pa, pb = self.all_proposals(a), self.all_proposals(b)
        for proposal in pa:
            a.tell(evaluation(proposal.candidate_id, 1))
        for proposal in reversed(pb):
            b.tell(evaluation(proposal.candidate_id, 1))
        self.assertEqual(a.evaluations, b.evaluations)
        self.assertEqual(a.ranked, b.ranked)
        self.assertEqual(a.pending_count, 0)

    def test_tell_order_cannot_change_random_generation(self):
        a = RandomSearchStrategy(self.req, seed=23, budget=20)
        b = RandomSearchStrategy(self.req, seed=23, budget=20)
        for _ in range(20):
            pa, pb = a.ask(), b.ask()
            self.assertEqual(pa, pb)
            a.tell(evaluation(pa.candidate_id))
        self.assertIsNone(a.ask())
        self.assertIsNone(b.ask())

    def test_unknown_duplicate_and_wrong_type_tell(self):
        strategy = GridSearchStrategy(self.req)
        with self.assertRaises(ValueError):
            strategy.tell(evaluation("unknown"))
        proposal = strategy.ask()
        strategy.tell(evaluation(proposal.candidate_id))
        with self.assertRaises(ValueError):
            strategy.tell(evaluation(proposal.candidate_id))
        with self.assertRaises(TypeError):
            strategy.tell(completed())

    def test_invalid_outcomes_excluded_from_ranking(self):
        strategy = GridSearchStrategy(self.req)
        bad, good = strategy.ask(), strategy.ask()
        outcome = SimulationOutcome(bad.candidate_id, OutcomeStatus.EXCEPTION, False, False)
        strategy.tell(Objective().evaluate(outcome, self.req))
        strategy.tell(evaluation(good.candidate_id))
        self.assertEqual([e.candidate_id for e in strategy.ranked], [good.candidate_id])

    def test_invalid_random_configuration(self):
        for args in ((True, 10), (1, -1), (1.1, 10), (1, True)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                RandomSearchStrategy(self.req, seed=args[0], budget=args[1])
        strategy = RandomSearchStrategy(self.req, seed=0, budget=0)
        self.assertIsNone(strategy.ask())
        self.assertTrue(strategy.exhausted)


class BoundaryTests(unittest.TestCase):
    def test_full_headless_demo_and_repeat_search(self):
        with tempfile.TemporaryDirectory(prefix="openmotor-ядро-") as directory:
            path = Path(directory) / "исходный.json"
            path.write_text(json.dumps(fixture_snapshot()), encoding="utf-8")
            process = subprocess.run(
                [sys.executable, str(ROOT / "test/designassistant/demo.py"), str(path)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
        report = json.loads(process.stdout)
        self.assertTrue(report["qt_free"] and report["repeat_identical"])
        self.assertEqual(report["grid"]["asked"], 3)
        self.assertEqual(report["grid"]["feasible"], 3)
        self.assertEqual(report["random"]["asked"], 5)
        self.assertEqual(report["random"]["feasible"], 5)

    def test_core_imports_no_qt_ui_or_matplotlib_in_fresh_process(self):
        script = """
import sys
import designassistant
blocked = [name for name in sys.modules if name.startswith(('uilib', 'PyQt', 'PySide', 'matplotlib'))]
assert not blocked, blocked
print('Qt-free import OK')
"""
        process = subprocess.run([sys.executable, "-c", script], cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn("Qt-free import OK", process.stdout)

    def test_core_static_imports_and_single_engine_call_site(self):
        call_sites = []
        for path in (ROOT / "designassistant").glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [item.name for item in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [node.module or ""]
                else:
                    imports = []
                self.assertFalse(any(name.startswith(("uilib", "PyQt", "PySide", "matplotlib")) for name in imports))
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "runSimulation"
                ):
                    call_sites.append(path.name)
        self.assertEqual(call_sites, ["engine.py"])

    def test_immutable_pickle_roundtrip_outcome(self):
        outcome = completed()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            outcome.valid = False
        self.assertEqual(pickle.loads(pickle.dumps(outcome)), outcome)
        self.assertEqual(pickle.loads(pickle.dumps(requirements(variable()))), requirements(variable()))

    def test_mutable_and_nonfinite_outcome_payloads_rejected(self):
        for value in (math.nan, math.inf, -math.inf, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                MetricValue("burn_time", value, "s")
        with self.assertRaises(ValueError):
            SimulationOutcome("a", OutcomeStatus.COMPLETED, True, True, metrics=(Motor(),))
        with self.assertRaises(TypeError):
            Diagnostic("bad", "ERROR", Motor())
        with self.assertRaises(TypeError):
            TextRecord("context", "source", {})
        with self.assertRaises(ValueError):
            dataclasses.replace(completed(), diagnostics=(Diagnostic("error", "ERROR", TextRecord("c", "error")),))

    def test_translation_templates_survive_nested_arguments(self):
        grain = QT_TRANSLATE_NOOP("SimulationLocations", "Grain {}").format(2)
        message = QT_TRANSLATE_NOOP("SimulationAlerts", "Problem at {}: {}").format(grain, 1.5)
        record = TextRecord.from_engine(message)
        arguments = json.loads(record.arguments_json)
        self.assertEqual(record.source, "Problem at {}: {}")
        self.assertEqual(record.context, "SimulationAlerts")
        self.assertEqual(arguments["args"][0]["source"], "Grain {}")
        self.assertEqual(arguments["args"][0]["args"], [2])
        self.assertEqual(arguments["args"][1], 1.5)

    def test_snapshot_canonical_digest_and_independent_decode(self):
        a, b = Snapshot.from_dict({"b": [1, {"x": 2}], "a": 0}), Snapshot.from_dict({"a": 0, "b": [1, {"x": 2}]})
        self.assertEqual(a, b)
        self.assertEqual(a.digest, b.digest)
        decoded = a.to_dict()
        decoded["b"][1]["x"] = 99
        self.assertEqual(a.to_dict()["b"][1]["x"], 2)
        with self.assertRaises(ValueError):
            Snapshot('{"a":NaN}')

    def test_provenance_changes_with_requirements_and_baseline(self):
        req = requirements(variable())
        req2 = requirements(variable(), targets=(Target("burn_time", 3, 2),))
        self.assertNotEqual(req.digest, req2.digest)
        baseline = fixture_snapshot()
        a = CandidateGenerator(baseline, req)
        baseline["nozzle"]["throat"] *= 1.01
        b = CandidateGenerator(baseline, req)
        self.assertNotEqual(a.baseline_digest, b.baseline_digest)
        self.assertEqual(engine_fingerprint(), engine_fingerprint())

    def test_requirements_json_roundtrip_for_replay(self):
        req = requirements(
            variable(), constraints=(MetricConstraint("maximum_pressure", maximum=10),), reject_warnings=True
        )
        restored = DesignRequirements.from_dict(json.loads(json.dumps(req.to_dict())))
        self.assertEqual(restored, req)
        self.assertEqual(restored.digest, req.digest)
        self.assertEqual(
            SearchTests.all_proposals(RandomSearchStrategy(req, seed=7, budget=20)),
            SearchTests.all_proposals(RandomSearchStrategy(restored, seed=7, budget=20)),
        )

    def test_metric_registry_only_existing_getters(self):
        with self.assertRaises(ValueError):
            MetricRegistry((MetricDefinition("bad", "Bad", "", "inventPhysics"),))
        with self.assertRaises(ValueError):
            MetricRegistry(())
        definitions = MetricRegistry().definitions
        with self.assertRaises(ValueError):
            MetricRegistry((definitions[0], definitions[0]))


if __name__ == "__main__":
    unittest.main()
