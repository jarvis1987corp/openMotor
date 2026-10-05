"""Ranking, explanations and comparison derived solely from objective data."""

import json
from dataclasses import dataclass

from .models import TextRecord


@dataclass(frozen=True)
class SmartCandidateContext:
    variant_key: str
    stage: str
    verification_of: str | None = None


@dataclass(frozen=True)
class TargetDeviation:
    metric: str
    target: float
    actual: float
    deviation: float
    normalized_deviation: float
    contribution: float


@dataclass(frozen=True)
class ConstraintMargin:
    metric: str
    actual: float
    minimum: float | None
    maximum: float | None
    normalized_margin: float


@dataclass(frozen=True)
class CandidateAnalysis:
    targets: tuple[TargetDeviation, ...]
    constraints: tuple[ConstraintMargin, ...]
    explanations: tuple[TextRecord, ...]


def _message(source, **arguments):
    return TextRecord("DesignAssistant", source, json.dumps({"args": [], "kwargs": arguments}))


def analyze_candidate(evaluation, requirements, *, verified=False):
    targets, margins, explanations = [], [], []
    weight = sum(t.weight for t in requirements.targets)
    for target in requirements.targets:
        actual = evaluation.outcome.metric(target.metric)
        deviation = actual - target.value
        normalized = abs(deviation) / target.scale
        targets.append(
            TargetDeviation(
                target.metric, target.value, actual, deviation, normalized, target.weight / weight * normalized
            )
        )
    for constraint in requirements.constraints:
        actual = evaluation.outcome.metric(constraint.metric)
        gaps = []
        if constraint.minimum is not None:
            gaps.append((actual - constraint.minimum) / max(abs(constraint.minimum), 1e-12))
        if constraint.maximum is not None:
            gaps.append((constraint.maximum - actual) / max(abs(constraint.maximum), 1e-12))
        margins.append(ConstraintMargin(constraint.metric, actual, constraint.minimum, constraint.maximum, min(gaps)))
    active = [t for t, target in zip(targets, requirements.targets) if target.weight]
    if active:
        closest = min(active, key=lambda t: (t.normalized_deviation, t.metric))
        explanations.append(
            _message(
                "Closest target: {metric}; normalized deviation: {deviation}.",
                metric=closest.metric,
                deviation="{:.6g}".format(closest.normalized_deviation),
            )
        )
        if all(t.normalized_deviation <= 1 for t in active):
            explanations.append(_message("All active targets are within their specified tolerance."))
        if len(active) > 1:
            explanations.append(_message("Weighted trade-off between {count} targets.", count=len(active)))
    if margins:
        margin = min(margins, key=lambda m: (m.normalized_margin, m.metric))
        explanations.append(
            _message(
                "Smallest normalized constraint margin: {metric}; margin: {margin}.",
                metric=margin.metric,
                margin="{:.6g}".format(margin.normalized_margin),
            )
        )
    if verified:
        explanations.append(_message("Rechecked with unchanged simulation settings."))
    return CandidateAnalysis(tuple(targets), tuple(margins), tuple(explanations))


@dataclass(frozen=True)
class RankedCandidate:
    rank: int
    proposal: object
    evaluation: object
    variant: object
    context: SmartCandidateContext
    analysis: CandidateAnalysis


class SmartResultStore:
    """In-memory summaries only. Rechecks supersede, rather than duplicate, motors.

    Invalid rechecks remove the earlier result from ranking. Stopping a search
    leaves all completed evaluations available, including diagnostics.
    """

    def __init__(self, plan):
        self.plan = plan
        self.records = {}
        self.finalized = False

    def append(self, proposal, evaluation, context):
        if proposal.candidate_id != evaluation.candidate_id:
            raise ValueError("Smart result identifiers must agree.")
        self.plan.variant(context.variant_key)
        self.records[proposal.candidate_id] = (proposal, evaluation, context)

    def ranked(self, limit=None):
        latest = {}
        for candidate_id in sorted(self.records):
            proposal, evaluation, context = self.records[candidate_id]
            key = (context.variant_key, tuple((a.path.value, a.value) for a in proposal.assignments))
            latest[key] = (proposal, evaluation, context)
        feasible = sorted(
            (r for r in latest.values() if r[1].score is not None and r[1].constraints.feasible and r[1].outcome.valid),
            key=lambda r: (r[1].score, r[0].candidate_id),
        )
        if self.finalized and any(r[2].stage == "verification" for r in self.records.values()):
            feasible = [r for r in feasible if r[2].stage == "verification"]
        if limit is not None:
            feasible = feasible[:limit]
        results = []
        for rank, (proposal, evaluation, context) in enumerate(feasible, 1):
            variant = self.plan.variant(context.variant_key)
            results.append(
                RankedCandidate(
                    rank,
                    proposal,
                    evaluation,
                    variant,
                    context,
                    analyze_candidate(evaluation, variant.requirements, verified=context.stage == "verification"),
                )
            )
        return tuple(results)

    @property
    def top(self):
        return self.ranked(self.plan.requirements.top_n)

    def compare(self, candidate_ids):
        ids = tuple(candidate_ids)
        if not 2 <= len(ids) <= 5 or len(set(ids)) != len(ids):
            raise ValueError("Select 2–5 distinct ranked candidates to compare.")
        ranked = {r.proposal.candidate_id: r for r in self.ranked()}
        if any(key not in ranked for key in ids):
            raise ValueError("Only admissible ranked candidates can be compared.")
        return tuple(ranked[key] for key in ids)
