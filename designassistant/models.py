"""Immutable, serializable core contracts. All numbers use engine (SI) units."""

import hashlib
import itertools
import json
import math
from dataclasses import dataclass
from enum import Enum
from numbers import Integral, Real

from .paths import PropertyPath


def finite_number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


@dataclass(frozen=True)
class ParameterRange:
    minimum: float
    maximum: float
    points: int = 2
    integer: bool = False

    def __post_init__(self):
        if not finite_number(self.minimum) or not finite_number(self.maximum) or self.minimum > self.maximum:
            raise ValueError("Range bounds must be finite and ordered.")
        if not math.isfinite(self.maximum - self.minimum):
            raise ValueError("Range span must be finite.")
        if type(self.points) is not int or self.points < 1 or type(self.integer) is not bool:
            raise ValueError("Range points must be a positive integer; integer must be boolean.")
        if self.points == 1 and self.minimum != self.maximum:
            raise ValueError("A one-point range must have identical bounds.")
        if self.minimum == self.maximum and self.points != 1:
            raise ValueError("A fixed range must contain exactly one point.")
        if self.integer:
            if int(self.minimum) != self.minimum or int(self.maximum) != self.maximum:
                raise ValueError("Integer ranges require integral bounds.")
            if self.points > self.maximum - self.minimum + 1:
                raise ValueError("Integer grid points must be distinct.")

    def contains(self, value):
        return (
            finite_number(value) and self.minimum <= value <= self.maximum and (not self.integer or int(value) == value)
        )

    def grid_values(self):
        if self.points == 1:
            return (int(self.minimum) if self.integer else float(self.minimum),)
        values = [self.minimum + (self.maximum - self.minimum) * i / (self.points - 1) for i in range(self.points)]
        values[0], values[-1] = self.minimum, self.maximum
        if self.integer:
            values = tuple(round(v) for v in values)
        else:
            values = tuple(float(v) for v in values)
        if len(set(values)) != len(values):
            raise ValueError("Grid points collapse at floating-point precision.")
        return values


@dataclass(frozen=True)
class DesignVariable:
    path: PropertyPath
    range: ParameterRange

    def __post_init__(self):
        if not isinstance(self.path, PropertyPath) or not isinstance(self.range, ParameterRange):
            raise TypeError("DesignVariable requires a PropertyPath and ParameterRange.")


@dataclass(frozen=True)
class Target:
    metric: str
    value: float
    scale: float
    weight: float = 1.0

    def __post_init__(self):
        if (
            type(self.metric) is not str
            or not self.metric
            or not all(finite_number(v) for v in (self.value, self.scale, self.weight))
        ):
            raise ValueError("Target values must be finite and metric must be identified.")
        if self.scale <= 0 or self.weight < 0:
            raise ValueError("Target scale must be positive and weight nonnegative.")


@dataclass(frozen=True)
class MetricConstraint:
    metric: str
    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self):
        if type(self.metric) is not str or not self.metric or self.minimum is None and self.maximum is None:
            raise ValueError("A constraint requires a metric and at least one bound.")
        if any(v is not None and not finite_number(v) for v in (self.minimum, self.maximum)):
            raise ValueError("Constraint bounds must be finite.")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("Constraint bounds must be ordered.")


@dataclass(frozen=True)
class DesignRequirements:
    variables: tuple[DesignVariable, ...] = ()
    targets: tuple[Target, ...] = ()
    constraints: tuple[MetricConstraint, ...] = ()
    reject_warnings: bool = False

    def __post_init__(self):
        for name, expected in (("variables", DesignVariable), ("targets", Target), ("constraints", MetricConstraint)):
            values = tuple(getattr(self, name))
            if not all(isinstance(v, expected) for v in values):
                raise TypeError("Invalid requirements collection: " + name)
            object.__setattr__(self, name, values)
        if len({v.path for v in self.variables}) != len(self.variables):
            raise ValueError("Variable paths must be unique.")
        if len({t.metric for t in self.targets}) != len(self.targets):
            raise ValueError("Target metrics must be unique.")
        if self.targets:
            total = sum(t.weight for t in self.targets)
            if not finite_number(total) or total <= 0:
                raise ValueError("Total target weight must be finite and positive.")
        if type(self.reject_warnings) is not bool:
            raise TypeError("reject_warnings must be boolean.")

    def to_dict(self):
        return {
            "variables": [
                dict(
                    path=v.path.value,
                    minimum=v.range.minimum,
                    maximum=v.range.maximum,
                    points=v.range.points,
                    integer=v.range.integer,
                )
                for v in self.variables
            ],
            "targets": [dict(metric=t.metric, value=t.value, scale=t.scale, weight=t.weight) for t in self.targets],
            "constraints": [dict(metric=c.metric, minimum=c.minimum, maximum=c.maximum) for c in self.constraints],
            "reject_warnings": self.reject_warnings,
        }

    @classmethod
    def from_dict(cls, value):
        return cls(
            variables=tuple(
                DesignVariable(
                    PropertyPath(v["path"]), ParameterRange(v["minimum"], v["maximum"], v["points"], v["integer"])
                )
                for v in value["variables"]
            ),
            targets=tuple(Target(**t) for t in value["targets"]),
            constraints=tuple(MetricConstraint(**c) for c in value["constraints"]),
            reject_warnings=value["reject_warnings"],
        )

    @property
    def digest(self):
        return Snapshot.from_dict(self.to_dict()).digest


@dataclass(frozen=True)
class Snapshot:
    """Canonical JSON is immutable; to_dict returns a fresh independent object."""

    json: str

    def __post_init__(self):
        decoded = json.loads(self.json, parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
        if not isinstance(decoded, dict):
            raise ValueError("A snapshot must be an object.")
        object.__setattr__(self, "json", json.dumps(decoded, sort_keys=True, separators=(",", ":"), allow_nan=False))

    @classmethod
    def from_dict(cls, value):
        return cls(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False))

    def to_dict(self):
        return json.loads(self.json)

    @property
    def digest(self):
        return hashlib.sha256(self.json.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Assignment:
    path: PropertyPath
    value: float

    def __post_init__(self):
        if not isinstance(self.path, PropertyPath) or type(self.value) not in (int, float):
            raise TypeError("Assignments require a stable path and numeric value.")


@dataclass(frozen=True)
class CandidateProposal:
    candidate_id: str
    assignments: tuple[Assignment, ...] = ()

    def __post_init__(self):
        if not isinstance(self.candidate_id, str) or not self.candidate_id:
            raise ValueError("A candidate must have a nonempty stable identifier.")
        object.__setattr__(self, "assignments", tuple(self.assignments))
        if not all(isinstance(a, Assignment) for a in self.assignments):
            raise TypeError("Invalid candidate assignment.")

    @classmethod
    def from_values(cls, candidate_id, values):
        return cls(candidate_id, tuple(Assignment(PropertyPath(path), value) for path, value in values.items()))


@dataclass(frozen=True)
class TextRecord:
    """English source/template metadata, including nested engine DisplayText args.

    No translation or Qt dependency. A future GUI can translate source before
    interpolation. Arguments are stored as JSON to avoid mutable payloads.
    """

    context: str
    source: str
    arguments_json: str = '{"args":[],"kwargs":{}}'

    def __post_init__(self):
        if not all(type(v) is str for v in (self.context, self.source, self.arguments_json)):
            raise TypeError("Text records contain only strings.")
        # Validate JSON; never retain mutable arguments or Qt objects.
        arguments = Snapshot(self.arguments_json)
        object.__setattr__(self, "arguments_json", arguments.json)

    @classmethod
    def from_engine(cls, value):
        def freeze(item):
            if hasattr(item, "context") and hasattr(item, "source"):
                return {
                    "context": item.context,
                    "source": item.source,
                    "args": [freeze(v) for v in item.args],
                    "kwargs": {k: freeze(v) for k, v in item.kwargs.items()},
                }
            if isinstance(item, dict):
                return {str(k): freeze(v) for k, v in item.items()}
            if isinstance(item, (list, tuple)):
                return [freeze(v) for v in item]
            if item is None or type(item) in (str, bool, int, float):
                # Nonfinite diagnostics remain text; they are not numeric results.
                return str(item) if isinstance(item, float) and not math.isfinite(item) else item
            if isinstance(item, Real):
                # NumPy scalars must retain numbers for translated {:.3f} alerts.
                value = int(item) if isinstance(item, Integral) else float(item)
                return value if math.isfinite(value) else str(item)
            return str(item)

        return cls(
            str(getattr(value, "context", "DesignAssistant")),
            str(getattr(value, "source", value)),
            json.dumps(
                {
                    "args": [freeze(v) for v in getattr(value, "args", ())],
                    "kwargs": {k: freeze(v) for k, v in getattr(value, "kwargs", {}).items()},
                },
                sort_keys=True,
                allow_nan=False,
            ),
        )


@dataclass(frozen=True)
class Diagnostic:
    code: str
    level: str
    message: TextRecord
    category: str = "core"
    location: TextRecord | None = None

    def __post_init__(self):
        if not all(type(v) is str for v in (self.code, self.level, self.category)):
            raise TypeError("Diagnostic identifiers must be strings.")
        if self.level not in ("ERROR", "WARNING", "MESSAGE"):
            raise ValueError("Unknown diagnostic level.")
        if (
            not isinstance(self.message, TextRecord)
            or self.location is not None
            and not isinstance(self.location, TextRecord)
        ):
            raise TypeError("Diagnostics require immutable TextRecord messages.")


def diagnostic(code, source, *, level="ERROR", **arguments):
    return Diagnostic(code, level, TextRecord("DesignAssistant", source, json.dumps({"args": [], "kwargs": arguments})))


@dataclass(frozen=True)
class CandidateRequest:
    proposal: CandidateProposal
    snapshot: Snapshot | None
    baseline_digest: str
    requirements_digest: str
    diagnostics: tuple[Diagnostic, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if (
            not isinstance(self.proposal, CandidateProposal)
            or self.snapshot is not None
            and not isinstance(self.snapshot, Snapshot)
        ):
            raise TypeError("Requests require immutable proposal/snapshot objects.")
        if not all(isinstance(d, Diagnostic) for d in self.diagnostics):
            raise TypeError("Requests require immutable diagnostics.")
        if not all(type(v) is str for v in (self.baseline_digest, self.requirements_digest)):
            raise TypeError("Request digests must be strings.")

    @property
    def valid(self):
        return self.snapshot is not None and not any(d.level == "ERROR" for d in self.diagnostics)


class OutcomeStatus(str, Enum):
    COMPLETED = "completed"
    INVALID_REQUEST = "invalid_request"
    ENGINE_FAILED = "engine_failed"
    INVALID_RESULT = "invalid_result"
    CANCELLED = "cancelled"
    PARTIAL = "partial"
    EXCEPTION = "exception"


@dataclass(frozen=True)
class MetricValue:
    key: str
    value: float
    unit: str

    def __post_init__(self):
        if type(self.key) is not str or type(self.unit) is not str or not finite_number(self.value):
            raise ValueError("Metric values require string identifiers/units and a finite number.")


@dataclass(frozen=True)
class SimulationOutcome:
    candidate_id: str
    status: OutcomeStatus
    engine_success: bool
    valid: bool
    metrics: tuple[MetricValue, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    baseline_digest: str = ""
    requirements_digest: str = ""
    engine_fingerprint: str = ""

    def __post_init__(self):
        object.__setattr__(self, "metrics", tuple(self.metrics))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        if not all(
            type(v) is str
            for v in (self.candidate_id, self.baseline_digest, self.requirements_digest, self.engine_fingerprint)
        ):
            raise TypeError("Outcome identifiers must be strings.")
        if (
            type(self.engine_success) is not bool
            or type(self.valid) is not bool
            or not isinstance(self.status, OutcomeStatus)
        ):
            raise TypeError("Outcome status and success/validity flags must be typed.")
        if not all(isinstance(m, MetricValue) and finite_number(m.value) for m in self.metrics):
            raise ValueError("Outcome metrics must be finite immutable MetricValue objects.")
        if not all(isinstance(d, Diagnostic) for d in self.diagnostics):
            raise TypeError("Outcome diagnostics must be immutable Diagnostic objects.")
        if len({m.key for m in self.metrics}) != len(self.metrics):
            raise ValueError("Outcome metric keys must be unique.")
        if self.valid and (
            not self.engine_success
            or self.status != OutcomeStatus.COMPLETED
            or any(d.level == "ERROR" for d in self.diagnostics)
        ):
            raise ValueError("Only completed successful outcomes without ERROR can be valid.")

    def metric(self, key):
        for metric in self.metrics:
            if metric.key == key:
                return metric.value
        raise KeyError(key)


@dataclass(frozen=True)
class ConstraintEvaluation:
    candidate_id: str
    feasible: bool
    violations: tuple[Diagnostic, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "violations", tuple(self.violations))
        if type(self.candidate_id) is not str or type(self.feasible) is not bool:
            raise TypeError("Constraint evaluation requires a string identifier and boolean feasibility.")
        if not all(isinstance(d, Diagnostic) for d in self.violations):
            raise TypeError("Constraint violations require immutable diagnostics.")
        if self.feasible and self.violations:
            raise ValueError("A feasible evaluation cannot have violations.")


@dataclass(frozen=True)
class CandidateEvaluation:
    outcome: SimulationOutcome
    constraints: ConstraintEvaluation
    score: float | None
    objective_errors: tuple = ()

    @property
    def target_status(self):
        from .objectives import target_status

        return target_status(self.objective_errors)

    def __post_init__(self):
        object.__setattr__(self, "objective_errors", tuple(self.objective_errors))
        if not isinstance(self.outcome, SimulationOutcome) or not isinstance(self.constraints, ConstraintEvaluation):
            raise TypeError("Evaluations require immutable outcome/constraint objects.")
        if self.outcome.candidate_id != self.constraints.candidate_id:
            raise ValueError("Evaluation identifiers must agree.")
        if self.score is not None and (
            not finite_number(self.score) or self.score < 0 or not self.outcome.valid or not self.constraints.feasible
        ):
            raise ValueError("Only feasible valid outcomes may have a finite nonnegative score.")

    @property
    def candidate_id(self):
        return self.outcome.candidate_id


def grid_combinations(variables):
    # itertools.product is lazy over combinations (not over each small axis).
    return itertools.product(*(v.range.grid_values() for v in variables))
