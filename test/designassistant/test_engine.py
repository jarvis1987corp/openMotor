"""Actual engine regression plus late alerts, cancellation and corrupt results."""

import copy
import dataclasses
import math
import unittest
from unittest.mock import patch

import numpy as np

from designassistant import (
    CandidateGenerator,
    CandidateProposal,
    DesignRequirements,
    Diagnostic,
    EngineAdapter,
    Objective,
    OutcomeStatus,
    Target,
    TextRecord,
)
from motorlib.motor import Motor
from motorlib.simResult import SimAlert, SimAlertLevel, SimAlertType
from test.designassistant.support import fixture_names, fixture_snapshot


class EngineFailureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = fixture_snapshot()
        cls.adapter = EngineAdapter()
        cls.request = CandidateGenerator(cls.snapshot, DesignRequirements()).generate(CandidateProposal("candidate"))
        cls.result = Motor(copy.deepcopy(cls.snapshot)).runSimulation()

    def run_result(self, result):
        with patch.object(Motor, "runSimulation", return_value=result) as run:
            outcome = self.adapter.run(self.request)
        run.assert_called_once()
        return outcome

    def test_error_after_success_is_invalid(self):
        result = copy.deepcopy(self.result)
        result.addAlert(SimAlert(SimAlertLevel.ERROR, SimAlertType.CONSTRAINT, "Late ERROR", "Motor"))
        outcome = self.run_result(result)
        self.assertTrue(outcome.engine_success)
        self.assertFalse(outcome.valid)
        self.assertEqual(outcome.status, OutcomeStatus.INVALID_RESULT)
        self.assertTrue(any(d.message.source == "Late ERROR" for d in outcome.diagnostics))
        self.assertIsNone(Objective().evaluate(outcome, DesignRequirements(targets=(Target("burn_time", 1, 1),))).score)

    def test_warning_success_remains_valid(self):
        result = copy.deepcopy(self.result)
        result.addAlert(SimAlert(SimAlertLevel.WARNING, SimAlertType.GEOMETRY, "Test warning"))
        outcome = self.run_result(result)
        self.assertTrue(outcome.valid)
        self.assertIn("WARNING", [d.level for d in outcome.diagnostics])

    def test_nan_inf_scalar_and_non_summary_channels(self):
        for key in ("force", "pressure", "exitPressure", "dThroat"):
            for bad in (math.nan, math.inf, -math.inf):
                with self.subTest(key=key, bad=bad):
                    result = copy.deepcopy(self.result)
                    result.channels[key].data[-1] = bad
                    outcome = self.run_result(result)
                    self.assertFalse(outcome.valid)
                    self.assertTrue(outcome.engine_success)
                    self.assertEqual(outcome.status, OutcomeStatus.INVALID_RESULT)

    def test_nan_inf_grain_channels(self):
        for key in ("mass", "massFlux", "regression", "web", "machNumber"):
            for bad in (math.nan, math.inf):
                with self.subTest(key=key, bad=bad):
                    result = copy.deepcopy(self.result)
                    result.channels[key].data[-1] = [bad] * len(result.motor.grains)
                    self.assertFalse(self.run_result(result).valid)

    def test_nonfinite_getter_without_nonfinite_channels(self):
        for bad in (math.nan, math.inf):
            with self.subTest(bad=bad):
                result = copy.deepcopy(self.result)
                result.getBurnTime = lambda: bad
                outcome = self.run_result(result)
                self.assertFalse(outcome.valid)
                self.assertEqual(outcome.metrics, ())

    def test_getter_exception_preserves_engine_success(self):
        result = copy.deepcopy(self.result)
        result.getBurnTime = lambda: (_ for _ in ()).throw(RuntimeError("getter failed"))
        outcome = self.run_result(result)
        self.assertTrue(outcome.engine_success)
        self.assertFalse(outcome.valid)
        self.assertEqual(outcome.status, OutcomeStatus.INVALID_RESULT)

    def test_missing_empty_and_inconsistent_channels(self):
        for action in ("missing", "empty", "short"):
            with self.subTest(action=action):
                result = copy.deepcopy(self.result)
                if action == "missing":
                    del result.channels["pressure"]
                elif action == "empty":
                    result.channels["pressure"].data.clear()
                else:
                    result.channels["pressure"].data.pop()
                self.assertFalse(self.run_result(result).valid)

    def test_invalid_grain_width(self):
        result = copy.deepcopy(self.result)
        result.channels["mass"].data[-1] = ()
        self.assertFalse(self.run_result(result).valid)

    def test_time_order_start_and_insufficient_samples(self):
        for action in ("duplicate", "start", "one_sample"):
            with self.subTest(action=action):
                result = copy.deepcopy(self.result)
                if action == "duplicate":
                    result.channels["time"].data[1] = result.channels["time"].data[0]
                elif action == "start":
                    result.channels["time"].data[0] = 0.1
                else:
                    for channel in result.channels.values():
                        channel.data[:] = channel.data[:1]
                self.assertFalse(self.run_result(result).valid)

    def test_boolean_and_text_channel_data(self):
        for bad in (True, "1.0", None):
            with self.subTest(bad=bad):
                result = copy.deepcopy(self.result)
                result.channels["force"].data[-1] = bad
                self.assertFalse(self.run_result(result).valid)

    def test_engine_failure_with_no_data(self):
        result = copy.deepcopy(self.result)
        result.success = False
        result.alerts.clear()
        for channel in result.channels.values():
            channel.data.clear()
        outcome = self.run_result(result)
        self.assertEqual(outcome.status, OutcomeStatus.ENGINE_FAILED)
        self.assertFalse(outcome.engine_success)

    def test_partial_result_is_not_valid(self):
        result = copy.deepcopy(self.result)
        result.success = False
        result.alerts.clear()
        outcome = self.run_result(result)
        self.assertEqual(outcome.status, OutcomeStatus.PARTIAL)
        self.assertFalse(outcome.valid)
        self.assertEqual(outcome.metrics, ())

    def test_actual_geometry_error(self):
        baseline = copy.deepcopy(self.snapshot)
        baseline["nozzle"]["throat"] = 0
        request = CandidateGenerator(baseline, DesignRequirements()).generate(CandidateProposal("bad_geometry"))
        outcome = self.adapter.run(request)
        self.assertFalse(outcome.valid)
        self.assertEqual(outcome.status, OutcomeStatus.ENGINE_FAILED)
        self.assertIn("ERROR", [d.level for d in outcome.diagnostics])

    def test_cancel_before_engine_does_not_simulate(self):
        with patch.object(Motor, "runSimulation") as run:
            outcome = self.adapter.run(self.request, should_cancel=lambda: True)
        run.assert_not_called()
        self.assertEqual(outcome.status, OutcomeStatus.CANCELLED)
        self.assertFalse(outcome.valid)

    def test_actual_cancel_during_simulation_and_progress(self):
        progress = []
        outcome = self.adapter.run(self.request, on_progress=progress.append, should_cancel=lambda: len(progress) >= 3)
        self.assertEqual(len(progress), 3)
        self.assertTrue(all(0 <= value <= 1 for value in progress))
        self.assertEqual(outcome.status, OutcomeStatus.CANCELLED)
        self.assertFalse(outcome.valid)
        self.assertFalse(outcome.engine_success)

    def test_cancellation_during_final_engine_work_is_honored_on_return(self):
        with patch.object(Motor, "runSimulation", return_value=copy.deepcopy(self.result)):
            outcome = self.adapter.run(self.request, should_cancel=unittest.mock.Mock(side_effect=[False, True]))
        self.assertEqual(outcome.status, OutcomeStatus.CANCELLED)
        self.assertTrue(outcome.engine_success)
        self.assertFalse(outcome.valid)

    def test_progress_callback_exception_is_candidate_local(self):
        def fail(progress):
            raise RuntimeError("consumer failed")

        self.assertEqual(self.adapter.run(self.request, on_progress=fail).status, OutcomeStatus.EXCEPTION)
        self.assertTrue(self.adapter.run(self.request).valid)

    def test_engine_exception_does_not_prevent_next_candidate(self):
        for exception in (RuntimeError("failed"), ValueError("failed"), ZeroDivisionError("failed")):
            with self.subTest(exception=exception), patch.object(Motor, "runSimulation", side_effect=exception):
                self.assertEqual(self.adapter.run(self.request).status, OutcomeStatus.EXCEPTION)
        self.assertTrue(self.adapter.run(self.request).valid)

    def test_outcome_is_detached_from_result_and_motor(self):
        result = copy.deepcopy(self.result)
        outcome = self.run_result(result)
        before = dataclasses.asdict(outcome)
        result.channels["force"].data[:] = [math.nan]
        result.motor.nozzle.setProperty("throat", 0)
        result.alerts.clear()
        self.assertEqual(dataclasses.asdict(outcome), before)
        self.assertFalse(any(hasattr(outcome, name) for name in ("motor", "result", "channels")))

    def test_error_request_is_not_sent_to_engine(self):
        diagnostic = Diagnostic("bad", "ERROR", TextRecord("DesignAssistant", "Bad request"))
        request = dataclasses.replace(self.request, diagnostics=(diagnostic,))
        with patch.object(Motor, "runSimulation") as run:
            self.assertEqual(self.adapter.run(request).status, OutcomeStatus.INVALID_REQUEST)
        run.assert_not_called()


class FixtureRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = EngineAdapter()
        if len(fixture_names()) != 18:
            raise AssertionError("All 18 existing fixture projects must be compared.")


def regression_test(name):
    def test(self):
        baseline = fixture_snapshot(name)
        original = copy.deepcopy(baseline)
        direct = Motor(copy.deepcopy(baseline)).runSimulation()
        request = CandidateGenerator(baseline, DesignRequirements()).generate(CandidateProposal(name))
        captured = []
        run_simulation = Motor.runSimulation

        def capture(motor, callback=None):
            result = run_simulation(motor, callback)
            captured.append(result)
            return result

        with patch.object(Motor, "runSimulation", new=capture):
            outcome = self.adapter.run(request)
        self.assertEqual(len(captured), 1)
        adapted = captured[0]
        self.assertEqual(direct.success, outcome.engine_success)
        self.assertTrue(outcome.valid, outcome.diagnostics)
        for definition in self.adapter.registry.definitions:
            self.assertEqual(
                outcome.metric(definition.key), float(getattr(direct, definition.getter)()), definition.key
            )
        for key in direct.channels:
            np.testing.assert_array_equal(direct.channels[key].getData(), adapted.channels[key].getData(), err_msg=key)
        direct_alerts = [(a.level.name, a.type.name, str(a.description), str(a.location)) for a in direct.alerts]
        adapted_alerts = [(a.level.name, a.type.name, str(a.description), str(a.location)) for a in adapted.alerts]
        self.assertEqual(direct_alerts, adapted_alerts)
        self.assertEqual(baseline, original)
        self.assertEqual(request.baseline_digest, outcome.baseline_digest)
        self.assertEqual(request.requirements_digest, outcome.requirements_digest)
        self.assertEqual(len(outcome.engine_fingerprint), 64)

    return test


# Separate test cases make it visible if any fixture fails or is accidentally omitted.
for _name in fixture_names():
    _test_name = "test_regression_" + _name.removesuffix(".ric").replace("/", "_")
    setattr(FixtureRegressionTests, _test_name, regression_test(_name))


if __name__ == "__main__":
    unittest.main()
