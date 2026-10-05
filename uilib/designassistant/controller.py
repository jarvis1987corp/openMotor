"""One background worker, queued DTO signals, cooperative cancellation."""

import math
import time
from dataclasses import dataclass, replace
from threading import Event

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal, pyqtSlot

from designassistant import (
    CandidateGenerator,
    EngineAdapter,
    GridSearchStrategy,
    MetricRegistry,
    Objective,
    OutcomeStatus,
    RandomSearchStrategy,
    SimulationOutcome,
    SmartResultStore,
    SmartSearchPlan,
    SmartSearchStrategy,
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
    stage: str = "manual"
    best_score: float | None = None
    elapsed: float = 0.0


@dataclass(frozen=True)
class SearchSummary:
    state: str
    progress: SearchProgress
    error: str = ""


class SearchWorker(QObject):
    candidateReady = pyqtSignal(object, object)
    smartCandidateReady = pyqtSignal(object, object, object)
    progressChanged = pyqtSignal(object)
    finished = pyqtSignal(object)

    def __init__(self, baseline, requirements, strategy, budget, seed, stop_event, *, smart_plan=None):
        super().__init__()
        self.baseline, self.requirements = baseline, requirements
        self.strategy, self.budget, self.seed = strategy, budget, seed
        self.stop_event = stop_event
        self.smart_plan = smart_plan

    @pyqtSlot()
    def run(self):
        total = self.budget
        if self.strategy == "grid":
            total = min(total, math.prod(v.range.points for v in self.requirements.variables))
        progress = SearchProgress(total=total)
        self.progressChanged.emit(progress)
        last_update = 0.0
        started = time.monotonic()

        def on_progress(fraction):
            nonlocal last_update
            now = time.monotonic()
            if now - last_update >= 0.05:
                self.progressChanged.emit(
                    replace(progress, current=max(0.0, min(1.0, fraction)), elapsed=now - started)
                )
                last_update = now

        state, error = "completed", ""
        try:
            generator = (
                None if self.smart_plan is not None else CandidateGenerator(self.baseline.to_dict(), self.requirements)
            )
            adapter = EngineAdapter()
            adapter.registry.validate_requirements(self.requirements)
            objective = Objective(adapter.registry)
            search = (
                SmartSearchStrategy(self.smart_plan)
                if self.smart_plan is not None
                else (
                    GridSearchStrategy(self.requirements)
                    if self.strategy == "grid"
                    else RandomSearchStrategy(self.requirements, seed=self.seed, budget=total)
                )
            )
            while progress.processed < total and not self.stop_event.is_set():
                proposal = search.ask()
                if proposal is None:
                    break
                context = search.context_for(proposal.candidate_id) if self.smart_plan is not None else None
                requirements = search.requirements_for(proposal.candidate_id) if context else self.requirements
                if context:
                    if progress.stage == "exploration" and context.stage == "refinement":
                        self.progressChanged.emit(
                            replace(progress, stage="selection", elapsed=time.monotonic() - started)
                        )
                    progress = replace(progress, stage=context.stage, elapsed=time.monotonic() - started)
                    self.progressChanged.emit(progress)
                try:
                    outcome = adapter.run(
                        search.request_for(proposal) if context else generator.generate(proposal),
                        should_cancel=self.stop_event.is_set,
                        on_progress=on_progress,
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
                        baseline_digest=self.smart_plan.variant(context.variant_key).baseline.digest
                        if context
                        else generator.baseline_digest,
                        requirements_digest=requirements.digest,
                        engine_fingerprint=adapter.fingerprint,
                    )
                evaluation = objective.evaluate(outcome, requirements)
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
                    progress.stage,
                    (search.results.ranked(1)[0].evaluation.score if search.results.top else None)
                    if context
                    else (search.ranked[0].score if search.ranked else None),
                    time.monotonic() - started,
                )
                if context:
                    self.smartCandidateReady.emit(proposal, evaluation, context)
                else:
                    self.candidateReady.emit(proposal, evaluation)
                self.progressChanged.emit(progress)
                # Release the Python GIL between candidates so queued GUI slots
                # and Stop can run even during a long stream of short simulations.
                # This is scheduler pacing; engine timestep/accuracy are untouched.
                self.stop_event.wait(0.001)
            if self.stop_event.is_set():
                state = "stopped"
            elif self.smart_plan is not None:
                progress = replace(progress, stage="ranking", elapsed=time.monotonic() - started)
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
        self.smart_plan = None
        self.smart_store = None

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
        self.smart_plan, self.smart_store = None, None
        self._launch(requirements, strategy, budget, seed)

    def start_smart(self, plan):
        if self.is_running:
            raise RuntimeError("A search is already running.")
        if not isinstance(plan, SmartSearchPlan) or plan.baseline != self.baseline:
            raise ValueError("Smart Design must use the unchanged current baseline.")
        self.smart_plan, self.smart_store = plan, SmartResultStore(plan)
        self.requirements = plan.variants[0].requirements
        self._launch(self.requirements, "coarse_to_fine", plan.requirements.budget, plan.requirements.seed)

    def _launch(self, requirements, strategy, budget, seed):
        self.proposals.clear()
        self.evaluations.clear()
        self._summary = None
        self._stop.clear()
        self.thread = QThread(self)
        self.worker = SearchWorker(
            self.baseline, requirements, strategy, budget, seed, self._stop, smart_plan=self.smart_plan
        )
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.candidateReady.connect(self._candidate, Qt.ConnectionType.QueuedConnection)
        self.worker.smartCandidateReady.connect(self._smart_candidate, Qt.ConnectionType.QueuedConnection)
        self.worker.progressChanged.connect(self._progress_received, Qt.ConnectionType.QueuedConnection)
        self.worker.finished.connect(self._record_summary, Qt.ConnectionType.QueuedConnection)
        # QThread.quit is thread-safe; worker shutdown must not wait on GUI painting.
        self.worker.finished.connect(self.thread.quit, Qt.ConnectionType.DirectConnection)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self._finished)
        self.thread.start()

    def stop(self):
        self._stop.set()

    @pyqtSlot(object)
    def _progress_received(self, progress):
        self.progressChanged.emit(progress)

    @pyqtSlot(object, object)
    def _candidate(self, proposal, evaluation):
        self.proposals[proposal.candidate_id] = proposal
        self.evaluations[proposal.candidate_id] = evaluation
        self.candidateReady.emit(proposal, evaluation)

    @pyqtSlot(object, object, object)
    def _smart_candidate(self, proposal, evaluation, context):
        self.smart_store.append(proposal, evaluation, context)
        self._candidate(proposal, evaluation)

    @pyqtSlot(object)
    def _record_summary(self, summary):
        if self.smart_store is not None:
            self.smart_store.finalized = summary.state == "completed"
            ranked = self.smart_store.top
            summary = replace(
                summary, progress=replace(summary.progress, best_score=ranked[0].evaluation.score if ranked else None)
            )
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
        if self.smart_plan is not None:
            _, _, context = self.smart_store.records[candidate_id]
            variant = self.smart_plan.variant(context.variant_key)
            return CandidateGenerator(variant.baseline.to_dict(), variant.requirements).generate(
                self.proposals[candidate_id]
            )
        return CandidateGenerator(self.baseline.to_dict(), self.requirements).generate(self.proposals[candidate_id])
