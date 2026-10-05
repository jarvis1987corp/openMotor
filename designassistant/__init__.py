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
from .search import (
    CoarseToFineSearchStrategy,
    GridSearchStrategy,
    RandomSearchStrategy,
    SearchStrategy,
    SmartSearchStrategy,
)
from .smart import LibraryEntry, SearchSpaceBuilder, SmartDesignRequirements, SmartSearchPlan
from .smart_results import CandidateAnalysis, SmartCandidateContext, SmartResultStore, analyze_candidate

__all__ = [
    "Assignment",
    "CandidateEvaluation",
    "CandidateAnalysis",
    "CandidateGenerator",
    "CandidateProposal",
    "CandidateRequest",
    "ConstraintEvaluation",
    "ConstraintEvaluator",
    "CoarseToFineSearchStrategy",
    "DEFAULT_METRICS",
    "DesignRequirements",
    "DesignVariable",
    "Diagnostic",
    "EngineAdapter",
    "GridSearchStrategy",
    "LibraryEntry",
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
    "SearchSpaceBuilder",
    "SmartCandidateContext",
    "SmartDesignRequirements",
    "SmartResultStore",
    "SmartSearchPlan",
    "SmartSearchStrategy",
    "SimulationOutcome",
    "Snapshot",
    "Target",
    "TextRecord",
    "engine_fingerprint",
    "analyze_candidate",
]
