"""Qt-free Design Assistant Phase 1. Importing this package never imports uilib."""

from .engine import EngineAdapter
from .evaluation import ConstraintEvaluator, Objective
from .generator import CandidateGenerator
from .metrics import DEFAULT_METRICS, MetricDefinition, MetricRegistry
from .models import (
    Assignment,
    CandidateEvaluation,
    CandidateProposal,
    CandidateRequest,
    ConstraintEvaluation,
    DesignRequirements,
    DesignVariable,
    Diagnostic,
    MetricConstraint,
    MetricValue,
    OutcomeStatus,
    ParameterRange,
    SimulationOutcome,
    Snapshot,
    Target,
    TextRecord,
)
from .paths import PropertyPath, PropertyValidationError
from .provenance import engine_fingerprint
from .search import GridSearchStrategy, RandomSearchStrategy, SearchStrategy

__all__ = [
    "Assignment",
    "CandidateEvaluation",
    "CandidateGenerator",
    "CandidateProposal",
    "CandidateRequest",
    "ConstraintEvaluation",
    "ConstraintEvaluator",
    "DEFAULT_METRICS",
    "DesignRequirements",
    "DesignVariable",
    "Diagnostic",
    "EngineAdapter",
    "GridSearchStrategy",
    "MetricConstraint",
    "MetricDefinition",
    "MetricRegistry",
    "MetricValue",
    "Objective",
    "OutcomeStatus",
    "ParameterRange",
    "PropertyPath",
    "PropertyValidationError",
    "RandomSearchStrategy",
    "SearchStrategy",
    "SimulationOutcome",
    "Snapshot",
    "Target",
    "TextRecord",
    "engine_fingerprint",
]
