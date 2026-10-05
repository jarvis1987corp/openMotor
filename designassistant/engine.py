"""The sole Design Assistant boundary calling the existing simulation engine."""

import math
from copy import deepcopy
from numbers import Real

from motorlib.motor import Motor
from motorlib.simResult import multiValueChannels, singleValueChannels

from .metrics import MetricRegistry
from .models import Diagnostic, OutcomeStatus, SimulationOutcome, TextRecord, diagnostic
from .provenance import engine_fingerprint


class EngineAdapter:
    """Synchronous, one calculation at a time; no Qt and no worker management."""

    def __init__(self, registry=None):
        self.registry = registry if registry is not None else MetricRegistry()
        self.fingerprint = engine_fingerprint()

    def run(self, request, *, should_cancel=None, on_progress=None):
        diagnostics = list(request.diagnostics)

        def outcome(status, success=False, valid=False, metrics=()):
            return SimulationOutcome(
                request.proposal.candidate_id,
                status,
                bool(success),
                valid,
                metrics,
                tuple(diagnostics),
                request.baseline_digest,
                request.requirements_digest,
                self.fingerprint,
            )

        if not request.valid:
            return outcome(OutcomeStatus.INVALID_REQUEST)
        cancelled = False
        result = None

        def callback(progress):
            nonlocal cancelled
            if on_progress is not None:
                on_progress(float(progress))
            cancelled = bool(should_cancel is not None and should_cancel())
            return cancelled

        try:
            if should_cancel is not None and should_cancel():
                diagnostics.append(diagnostic("cancelled", "Simulation was cancelled.", level="MESSAGE"))
                return outcome(OutcomeStatus.CANCELLED)
            motor = Motor(deepcopy(request.snapshot.to_dict()))
            result = motor.runSimulation(callback if should_cancel is not None or on_progress is not None else None)
            for alert in result.alerts:
                diagnostics.append(
                    Diagnostic(
                        "engine_alert",
                        alert.level.name,
                        TextRecord.from_engine(alert.description),
                        alert.type.name,
                        None if alert.location is None else TextRecord.from_engine(alert.location),
                    )
                )
            if cancelled or should_cancel is not None and should_cancel():
                diagnostics.append(diagnostic("cancelled", "Simulation was cancelled.", level="MESSAGE"))
                return outcome(OutcomeStatus.CANCELLED, result.success)
            if any(d.level == "ERROR" for d in diagnostics):
                return outcome(
                    OutcomeStatus.INVALID_RESULT if result.success else OutcomeStatus.ENGINE_FAILED, result.success
                )
            if not result.success:
                has_data = any(channel.getData() for channel in result.channels.values())
                diagnostics.append(
                    diagnostic("partial_result" if has_data else "engine_failed", "Simulation did not complete.")
                )
                return outcome(OutcomeStatus.PARTIAL if has_data else OutcomeStatus.ENGINE_FAILED)
            self._validate_data(result, len(motor.grains))
            metrics = self.registry.extract(result)
            return outcome(OutcomeStatus.COMPLETED, result.success, True, metrics)
        except Exception as error:
            # Candidate-local failures never terminate a search. KeyboardInterrupt/SystemExit propagate.
            # Preserve the engine flag if extraction/validation failed after the engine returned.
            if result is not None:
                diagnostics.append(
                    diagnostic("invalid_result_data", "Invalid simulation data: {reason}", reason=str(error))
                )
                return outcome(OutcomeStatus.INVALID_RESULT, result.success)
            diagnostics.append(diagnostic("engine_exception", "Simulation failed: {reason}", reason=str(error)))
            return outcome(OutcomeStatus.EXCEPTION)

    @staticmethod
    def _validate_data(result, grain_count):
        """Check the engine's full channel schema, including unused/non-summary data."""
        time = result.channels["time"].getData()
        if len(time) < 2:
            raise ValueError("At least two simulation samples are required.")
        for key in (*singleValueChannels, *multiValueChannels):
            data = result.channels[key].getData()
            if len(data) != len(time):
                raise ValueError("Missing or inconsistent channel samples: " + key)
            for frame in data:
                if key in multiValueChannels:
                    if not isinstance(frame, (list, tuple)) or len(frame) != grain_count:
                        raise ValueError("Invalid grain channel width: " + key)
                    numbers = frame
                else:
                    numbers = (frame,)
                if any(isinstance(v, bool) or not isinstance(v, Real) or not math.isfinite(v) for v in numbers):
                    raise ValueError("Nonfinite or nonnumeric channel data: " + key)
        if time[0] != 0 or any(b <= a for a, b in zip(time, time[1:])):
            raise ValueError("Simulation times must start at zero and increase strictly.")
