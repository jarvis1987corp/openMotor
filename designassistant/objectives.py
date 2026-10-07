"""Numeric goal assessment, independent of candidate generation or simulation."""

import math
from dataclasses import dataclass
from enum import Enum


class TargetStatus(str, Enum):
    MATCHED = "MATCHED"
    NEAR = "NEAR"
    MISSED = "MISSED"


@dataclass(frozen=True)
class TargetTolerancePolicy:
    """10% matches the existing default target scale; NEAR is twice that band.

    These are search/reporting tolerances, not uncertainty or physical accuracy.
    A zero reference has no relative error: use the explicitly supplied scale.
    """

    matched: float = 0.10
    near: float = 0.20

    def __post_init__(self):
        if not (math.isfinite(self.matched) and math.isfinite(self.near) and 0 <= self.matched <= self.near):
            raise ValueError("Tolerance bands must be finite, nonnegative and ordered.")

    def status(self, error):
        if not math.isfinite(error) or error < 0:
            raise ValueError("Error must be finite and nonnegative.")
        if error <= self.matched:
            return TargetStatus.MATCHED
        return TargetStatus.NEAR if error <= self.near else TargetStatus.MISSED


DEFAULT_TARGET_POLICY = TargetTolerancePolicy()


@dataclass(frozen=True)
class ObjectiveError:
    metric: str
    target: float
    actual: float
    signed_relative_error: float
    relative_error: float
    status: TargetStatus
    weight: float


def target_errors(targets, metric, policy=DEFAULT_TARGET_POLICY):
    errors = []
    for target in targets:
        if target.weight == 0:
            continue
        actual = metric(target.metric)
        denominator = abs(target.value) if target.value != 0 else target.scale
        if not all(math.isfinite(v) for v in (actual, target.value, denominator, target.weight)):
            raise ValueError("Goals and observations must be finite.")
        if denominator <= 0 or target.weight < 0:
            raise ValueError("A zero target requires a positive scale; weights cannot be negative.")
        signed = (actual - target.value) / denominator
        error = abs(signed)
        errors.append(
            ObjectiveError(target.metric, target.value, actual, signed, error, policy.status(error), target.weight)
        )
    return tuple(errors)


def objective_score(errors):
    active = [e for e in errors if e.weight > 0]
    if not active:
        raise ValueError("Scoring requires an active target.")
    weight = math.fsum(e.weight for e in active)
    mean = math.fsum(e.weight / weight * e.relative_error for e in active)
    score = 0.5 * mean + 0.5 * max(e.relative_error for e in active)
    if not math.isfinite(score):
        raise ValueError("Nonfinite score.")
    return score


def match_percentage(score):
    if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score) or score < 0:
        raise ValueError("A match index requires a finite nonnegative score.")
    return 100.0 * math.exp(-3.0 * score)


def target_status(errors):
    active = [e.status for e in errors if e.weight > 0]
    if not active or TargetStatus.MISSED in active:
        return TargetStatus.MISSED
    return TargetStatus.NEAR if TargetStatus.NEAR in active else TargetStatus.MATCHED


def result_heading(statuses):
    return "Recommended designs" if any(s == TargetStatus.MATCHED for s in statuses) else "Closest candidates"
