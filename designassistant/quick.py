"""Quick requirements -> existing Smart Design. No simulation or physics here.

Dimensions use the engine's existing propellant-envelope getters. They exclude
casing, nozzle length and inter-grain gaps; the UI explicitly states this limit.
"""

import json
from dataclasses import dataclass

from motorlib.motor import Motor

from .metrics import DEFAULT_METRICS, ChannelMetricDefinition, MetricDefinition, MetricRegistry
from .models import (
    DesignRequirements,
    MetricConstraint,
    Snapshot,
    Target,
    TextRecord,
    finite_number,
)
from .objectives import match_percentage as match_percentage
from .quick_generation import QuickDesignGeometryFactory, QuickDesignSearchSpaceBuilder, QuickDimensions
from .smart import QUALITY_BUDGETS, SmartDesignRequirements, SmartSearchPlan

DIMENSION_METRICS = (
    MetricDefinition("propellant_length", "Propellant Stack Length", "m", "getPropellantLength"),
    MetricDefinition("maximum_diameter", "Maximum Propellant Diameter", "m", "getMaxPropellantDiameter"),
)
QUICK_METRICS = (
    DEFAULT_METRICS
    + DIMENSION_METRICS
    + (ChannelMetricDefinition("peak_thrust", "Peak Thrust", "N", "getMax", "force"),)
)
FIELD_METRICS = {
    "diameter": "maximum_diameter",
    "length": "propellant_length",
    "burn_time": "burn_time",
    "average_thrust": "average_thrust",
    "total_impulse": "total_impulse",
}
PRIORITIES = {
    "balanced": None,
    "burn_time": "burn_time",
    "average_thrust": "average_thrust",
    "total_impulse": "total_impulse",
}


def message(source, **kwargs):
    return TextRecord("QuickDesign", source, json.dumps({"args": [], "kwargs": kwargs}))


class QuickDesignError(ValueError):
    def __init__(self, source, **kwargs):
        self.message = message(source, **kwargs)
        super().__init__(source)


@dataclass(frozen=True)
class QuickCriterion:
    field: str
    mode: str
    value: float

    def __post_init__(self):
        if self.field not in FIELD_METRICS or self.mode not in ("target", "minimum", "maximum"):
            raise QuickDesignError("Select a supported requirement and Target, Minimum or Maximum.")
        if not finite_number(self.value) or self.value <= 0:
            raise QuickDesignError("Enter a positive finite value for {requirement}.", requirement=self.field)


@dataclass(frozen=True)
class QuickDesignRequirements:
    criteria: tuple[QuickCriterion, ...] = ()
    constraints: tuple[MetricConstraint, ...] = ()
    library_keys: tuple[str, ...] | None = None
    priority: str = "balanced"
    quality: str = "balanced"
    seed: int = 1729
    reject_warnings: bool = False
    # A headless/test override; the wizard exposes only the three quality presets.
    budget: int | None = None

    def __post_init__(self):
        object.__setattr__(self, "criteria", tuple(self.criteria))
        object.__setattr__(self, "constraints", tuple(self.constraints))
        if not all(isinstance(c, QuickCriterion) for c in self.criteria):
            raise QuickDesignError("Select supported project requirements.")
        if len({(c.field, c.mode) for c in self.criteria}) != len(self.criteria):
            raise QuickDesignError("The same requirement and mode cannot be entered twice.")
        if self.priority not in PRIORITIES or self.quality not in QUALITY_BUDGETS:
            raise QuickDesignError("Select a supported design priority and search quality.")
        if type(self.seed) is not int or type(self.reject_warnings) is not bool:
            raise QuickDesignError("Search seed must be an integer and warning policy must be boolean.")
        if self.budget is not None and (type(self.budget) is not int or not 1 <= self.budget <= 10000):
            raise QuickDesignError("Candidate budget must be between 1 and 10000.")
        if self.library_keys is not None:
            object.__setattr__(self, "library_keys", tuple(self.library_keys))
            if not self.library_keys or any(type(k) is not str for k in self.library_keys):
                raise QuickDesignError("Choose at least one existing library entry.")
            if len(set(self.library_keys)) != len(self.library_keys):
                raise QuickDesignError("Allowed library entries must be unique.")
        design = DesignRequirements(constraints=self.constraints)
        MetricRegistry(QUICK_METRICS).validate_requirements(design)

    @property
    def simulation_budget(self):
        return QUALITY_BUDGETS[self.quality] if self.budget is None else self.budget

    @property
    def digest(self):
        return Snapshot.from_dict(
            {
                "criteria": [vars(c) for c in self.criteria],
                "constraints": [vars(c) for c in self.constraints],
                "library_keys": self.library_keys,
                "priority": self.priority,
                "quality": self.quality,
                "seed": self.seed,
                "reject_warnings": self.reject_warnings,
                "budget": self.budget,
            }
        ).digest


@dataclass(frozen=True)
class QuickDesignProblem:
    requirements: QuickDesignRequirements
    plan: SmartSearchPlan
    diagnostics: tuple[TextRecord, ...]
    inferred_targets: bool = False
    total_combinations: int = 0
    target_warning: TextRecord | None = None

    @property
    def digest(self):
        return Snapshot.from_dict({"requirements": self.requirements.digest, "plan": self.plan.digest}).digest


@dataclass(frozen=True)
class QuickValidation:
    problem: QuickDesignProblem | None
    diagnostics: tuple[TextRecord, ...]

    @property
    def valid(self):
        return self.problem is not None


class QuickDesignRequirementsValidator:
    def validate(self, baseline, requirements, library_entries):
        try:
            problem = QuickDesignProblemBuilder().build(baseline, requirements, library_entries)
            return QuickValidation(problem, problem.diagnostics)
        except QuickDesignError as error:
            return QuickValidation(None, (error.message,))
        except (ValueError, TypeError, KeyError) as error:
            return QuickValidation(None, (message("Cannot build a search space: {reason}", reason=str(error)),))


class QuickDesignProblemBuilder:
    def build(self, baseline, requirements, library_entries):
        if not isinstance(requirements, QuickDesignRequirements):
            raise QuickDesignError("Enter validated Quick Design requirements.")
        baseline = baseline if isinstance(baseline, Snapshot) else Snapshot.from_dict(baseline)
        fields = {c.field: c for c in requirements.criteria}
        modes = {"diameter": "maximum", "length": "maximum", "burn_time": "target"}
        if any(field not in fields for field in modes):
            raise QuickDesignError("Enter maximum diameter, maximum length and desired burn time before searching.")
        if len(fields) != len(requirements.criteria) or any(fields[k].mode != mode for k, mode in modes.items()):
            raise QuickDesignError("Diameter and length must be maximum limits; burn time must be a target.")
        if any(c.mode != "target" for c in requirements.criteria if c.field not in modes):
            raise QuickDesignError("Optional thrust and impulse must be targets; use Other limits for bounds.")
        dimensions = QuickDimensions(fields["diameter"].value, fields["length"].value)
        targets = [
            self._target(FIELD_METRICS[c.field], c.value, requirements.priority)
            for c in requirements.criteria
            if c.mode == "target"
        ]
        constraints = list(requirements.constraints) + [
            MetricConstraint("maximum_diameter", maximum=dimensions.maximum_diameter),
            MetricConstraint("propellant_length", maximum=dimensions.maximum_length),
        ]
        self._check_bounds(targets, constraints)
        entries, diagnostics = self._library(Motor(), requirements.library_keys, library_entries)
        target_warning = None
        if "average_thrust" in fields and "total_impulse" in fields:
            estimated_impulse = fields["average_thrust"].value * fields["burn_time"].value
            impulse = fields["total_impulse"].value
            if abs(estimated_impulse - impulse) > 0.25 * max(estimated_impulse, impulse):
                target_warning = message(
                    "Average thrust × burn time differs substantially from the requested total impulse. "
                    "These targets may conflict; simulation results will determine the trade-off."
                )
                diagnostics.append(target_warning)
        smart = SmartDesignRequirements(
            dimensions.maximum_diameter,
            tuple(targets),
            tuple(constraints),
            tuple(e.key for e in entries),
            tuple(sorted(QuickDesignGeometryFactory.PROFILES)),
            requirements.simulation_budget,
            requirements.seed,
            15,
            requirements.reject_warnings,
            QUICK_METRICS,
        )
        try:
            plan, skipped, total = QuickDesignSearchSpaceBuilder().build(baseline, smart, entries, dimensions)
        except ValueError as error:
            raise QuickDesignError("Cannot build a search space: {reason}", reason=str(error)) from error
        diagnostics.extend(skipped)
        return QuickDesignProblem(requirements, plan, tuple(diagnostics), False, total, target_warning)

    @staticmethod
    def _target(metric, value, priority):
        return Target(metric, value, max(value * 0.1, 1e-12), 3.0 if PRIORITIES[priority] == metric else 1.0)

    @staticmethod
    def _check_bounds(targets, constraints):
        bounds = {}
        for constraint in constraints:
            low, high = bounds.get(constraint.metric, (None, None))
            low = (
                max(low, constraint.minimum)
                if low is not None and constraint.minimum is not None
                else (constraint.minimum if constraint.minimum is not None else low)
            )
            high = (
                min(high, constraint.maximum)
                if high is not None and constraint.maximum is not None
                else (constraint.maximum if constraint.maximum is not None else high)
            )
            if low is not None and high is not None and low > high:
                raise QuickDesignError("Minimum and maximum requirements contradict each other.")
            bounds[constraint.metric] = low, high
        for target in targets:
            low, high = bounds.get(target.metric, (None, None))
            if low is not None and target.value < low or high is not None and target.value > high:
                raise QuickDesignError("A desired target lies outside its configured limits.")

    @staticmethod
    def _library(motor, keys, library_entries):
        available = {e.key: e for e in library_entries}
        if keys is not None and any(key not in available for key in keys):
            raise QuickDesignError("A chosen library entry is no longer available. Reopen Quick Design.")
        entries, diagnostics = [], []
        for key in sorted(available if keys is None else keys):
            entry = available[key]
            try:
                probe = Motor(motor.getDict())
                data = probe.getDict()
                data["propellant"] = entry.snapshot.to_dict()
                probe = Motor(data)
                if probe.propellant.getProperties() != entry.snapshot.to_dict() or probe.propellant.getErrors():
                    raise ValueError("Library data failed existing engine validation.")
                entries.append(entry)
            except (ValueError, KeyError, TypeError):
                diagnostics.append(
                    message("Skipped library entry {name}: stored data failed engine validation.", name=entry.name)
                )
        if not entries:
            raise QuickDesignError("No compatible existing library entries are available.")
        return tuple(entries), diagnostics


def recommended_designs(store, limit=5, diversity=0.03):
    """Greedy deterministic diversity filter over the existing ranked finalists."""
    if type(limit) is not int or not 1 <= limit <= 5 or not finite_number(diversity) or not 0 <= diversity <= 1:
        raise ValueError("Recommendations require a limit of 1–5 and diversity between 0 and 1.")
    selected = []
    metrics = ("burn_time", "average_thrust", "total_impulse", "propellant_length", "maximum_diameter")
    for record in store.ranked():
        duplicate = False
        for other in selected:
            if (record.variant.library_key, record.variant.geometries) != (
                other.variant.library_key,
                other.variant.geometries,
            ):
                continue
            distances = []
            for metric in metrics:
                try:
                    a, b = record.evaluation.outcome.metric(metric), other.evaluation.outcome.metric(metric)
                    distances.append(abs(a - b) / max(abs(a), abs(b), 1e-12))
                except KeyError:
                    continue
            if distances and max(distances) <= diversity:
                duplicate = True
                break
        if not duplicate:
            selected.append(record)
            if len(selected) == limit:
                break
    return tuple(selected)
