"""One background worker, queued DTO signals, cooperative cancellation."""

import math
import time
from dataclasses import dataclass
from threading import Event

from PyQt6.QtCore import QObject, QThread, pyqtSignal, pyqtSlot

from designassistant import (
    CandidateGenerator,
    EngineAdapter,
    GridSearchStrategy,
    MetricRegistry,
    Objective,
    OutcomeStatus,
    RandomSearchStrategy,
    SimulationOutcome,
    Snapshot,
)
from designassistant.models import diagnostic


@dataclass(frozen=True)
class SearchProgress:
    processed: int = 0
    feasible: int = 0
    rejected: int = 0
    errors: int = 0
    total: int = 0
    current: float = 0.0


@dataclass(frozen=True)
class SearchSummary:
    state: str
    progress: SearchProgress
    error: str = ""


class SearchWorker(QObject):
    candidateReady = pyqtSignal(object, object)
    progressChanged = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, baseline, requirements, strategy, budget, seed, stop_event):
        super().__init__()
        self.baseline, self.requirements = baseline, requirements
        self.strategy, self.budget, self.seed = strategy, budget, seed
        self.stop_event = stop_event

    @pyqtSlot()
    def run(self):
        total = self.budget
        if self.strategy == "grid":
            total = min(total, math.prod(v.range.points for v in self.requirements.variables))
        progress = SearchProgress(total=total)
        self.progressChanged.emit(progress)
        last_update = 0.0

        def on_progress(fraction):
            nonlocal last_update
            now = time.monotonic()
            if now - last_update >= 0.05:
                self.progressChanged.emit(
                    SearchProgress(
                        progress.processed,
                        progress.feasible,
                        progress.rejected,
                        progress.errors,
                        total,
                        max(0.0, min(1.0, fraction)),
                    )
                )
                last_update = now

        state, error = "completed", ""
        try:
            generator = CandidateGenerator(self.baseline.to_dict(), self.requirements)
            adapter = EngineAdapter()
            adapter.registry.validate_requirements(self.requirements)
            objective = Objective(adapter.registry)
            search = (
                GridSearchStrategy(self.requirements)
                if self.strategy == "grid"
                else RandomSearchStrategy(self.requirements, seed=self.seed, budget=total)
            )
            while progress.processed < total and not self.stop_event.is_set():
                proposal = search.ask()
                if proposal is None:
                    break
                try:
                    outcome = adapter.run(
                        generator.generate(proposal), should_cancel=self.stop_event.is_set, on_progress=on_progress
                    )
                except Exception as exception:
                    outcome = SimulationOutcome(
                        proposal.candidate_id,
                        OutcomeStatus.EXCEPTION,
                        False,
                        False,
                        diagnostics=(
                            diagnostic("candidate_exception", "Candidate failed: {reason}", reason=str(exception)),
                        ),
                        baseline_digest=generator.baseline_digest,
                        requirements_digest=generator.requirements_digest,
                        engine_fingerprint=adapter.fingerprint,
                    )
                evaluation = objective.evaluate(outcome, self.requirements)
                search.tell(evaluation)
                feasible = evaluation.constraints.feasible and evaluation.score is not None
                cancelled = outcome.status == OutcomeStatus.CANCELLED
                errors = not outcome.valid and not cancelled
                progress = SearchProgress(
                    progress.processed + 1,
                    progress.feasible + int(feasible),
                    progress.rejected + int(not feasible and not cancelled),
                    progress.errors + int(errors),
                    total,
                    0.0,
                )
                self.candidateReady.emit(proposal, evaluation)
                self.progressChanged.emit(progress)
            if self.stop_event.is_set():
                state = "stopped"
        except Exception as exception:
            state, error = "failed", str(exception)
        finally:
            self.finished.emit(SearchSummary(state, progress, error))


class DesignController(QObject):
    candidateReady = pyqtSignal(object, object)
    progressChanged = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, baseline, parent=None):
        super().__init__(parent)
        self.baseline = baseline if isinstance(baseline, Snapshot) else Snapshot.from_dict(baseline)
        self.requirements = None
        self.proposals = {}
        self.evaluations = {}
        self.thread = None
        self.worker = None
        self._stop = Event()
        self._summary = None

    @property
    def is_running(self):
        return self.thread is not None

    def start(self, requirements, *, strategy, budget, seed):
        if self.is_running:
            raise RuntimeError("A search is already running.")
        if strategy not in ("grid", "random") or type(budget) is not int or not 1 <= budget <= 10000:
            raise ValueError("Select a search strategy and a budget between 1 and 10000.")
        if type(seed) is not int:
            raise ValueError("Random seed must be an integer.")
        if not requirements.targets:
            raise ValueError("Add at least one target before starting the search.")
        MetricRegistry().validate_requirements(requirements)
        CandidateGenerator(self.baseline.to_dict(), requirements)
        self.requirements = requirements
        self.proposals.clear()
        self.evaluations.clear()
        self._summary = None
        self._stop.clear()
        self.thread = QThread(self)
        self.worker = SearchWorker(self.baseline, requirements, strategy, budget, seed, self._stop)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.candidateReady.connect(self._candidate)
        self.worker.progressChanged.connect(self.progressChanged)
        self.worker.finished.connect(self._record_summary)
        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._finished)
        self.thread.start()

    def stop(self):
        self._stop.set()

    @pyqtSlot(object, object)
    def _candidate(self, proposal, evaluation):
        self.proposals[proposal.candidate_id] = proposal
        self.evaluations[proposal.candidate_id] = evaluation
        self.candidateReady.emit(proposal, evaluation)

    @pyqtSlot(object)
    def _record_summary(self, summary):
        self._summary = summary

    @pyqtSlot()
    def _finished(self):
        thread, self.thread = self.thread, None
        self.worker = None
        thread.deleteLater()
        self.finished.emit(self._summary)

    def request_for(self, candidate_id):
        if self.is_running:
            raise RuntimeError("Stop the search before opening a candidate.")
        evaluation = self.evaluations[candidate_id]
        if not evaluation.outcome.valid:
            raise ValueError("This candidate has no valid simulation and cannot be opened.")
        return CandidateGenerator(self.baseline.to_dict(), self.requirements).generate(self.proposals[candidate_id])
