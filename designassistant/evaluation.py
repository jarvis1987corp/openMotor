"""Feasibility first; normalized weighted target deviation (lower is better)."""

import math

from .metrics import MetricRegistry
from .models import CandidateEvaluation, ConstraintEvaluation, diagnostic


class ConstraintEvaluator:
    def __init__(self, registry=None):
        self.registry = registry if registry is not None else MetricRegistry()

    def evaluate(self, outcome, requirements):
        self.registry.validate_requirements(requirements)
        violations = []
        if not outcome.valid:
            violations.append(diagnostic("invalid_candidate", "Candidate has no valid completed simulation."))
        if requirements.reject_warnings and any(d.level == "WARNING" for d in outcome.diagnostics):
            violations.append(diagnostic("warning_constraint", "Candidate has simulation warnings."))
        for constraint in requirements.constraints:
            try:
                value = outcome.metric(constraint.metric)
            except KeyError:
                violations.append(
                    diagnostic("missing_metric", "Required metric is missing: {metric}.", metric=constraint.metric)
                )
                continue
            if constraint.minimum is not None and value < constraint.minimum:
                violations.append(
                    diagnostic("constraint_minimum", "Metric {metric} is below its minimum.", metric=constraint.metric)
                )
            if constraint.maximum is not None and value > constraint.maximum:
                violations.append(
                    diagnostic("constraint_maximum", "Metric {metric} exceeds its maximum.", metric=constraint.metric)
                )
        return ConstraintEvaluation(outcome.candidate_id, not violations, tuple(violations))


class Objective:
    def __init__(self, registry=None):
        self.constraints = ConstraintEvaluator(registry)

    def evaluate(self, outcome, requirements):
        evaluation = self.constraints.evaluate(outcome, requirements)
        if not evaluation.feasible:
            return CandidateEvaluation(outcome, evaluation, None)
        if not requirements.targets:
            raise ValueError("Scoring requires at least one target.")
        weight_sum = sum(t.weight for t in requirements.targets)
        try:
            # Divide each weight first to avoid unnecessary weighted-sum overflow.
            score = math.fsum(
                (t.weight / weight_sum) * abs(outcome.metric(t.metric) - t.value) / t.scale
                for t in requirements.targets
                if t.weight
            )
            if not math.isfinite(score):
                raise ValueError("Nonfinite score.")
        except (KeyError, ValueError, OverflowError) as error:
            violation = diagnostic("invalid_score", "Cannot score candidate: {reason}", reason=str(error))
            return CandidateEvaluation(outcome, ConstraintEvaluation(outcome.candidate_id, False, (violation,)), None)
        return CandidateEvaluation(outcome, evaluation, score)
