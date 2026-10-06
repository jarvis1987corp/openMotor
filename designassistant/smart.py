"""Immutable Smart Design inputs and metadata-driven, baseline-centred spaces.

Search bounds are exploration heuristics, not a physical model. All validation
and calculation of proposed motors remains in CandidateGenerator/EngineAdapter.
"""

import math
from copy import deepcopy
from dataclasses import dataclass

from motorlib.grains import grainTypes
from motorlib.motor import Motor
from motorlib.properties import FloatProperty, IntProperty

from .generator import CandidateGenerator
from .metrics import DEFAULT_METRICS, MetricRegistry
from .models import DesignRequirements, DesignVariable, ParameterRange, Snapshot, finite_number
from .paths import PropertyPath

QUALITY_BUDGETS = {"quick": 60, "balanced": 180, "thorough": 540}
CURRENT_GEOMETRY = "current"


@dataclass(frozen=True)
class LibraryEntry:
    """An exact snapshot of an existing user-library entry; never a new recipe."""

    key: str
    name: str
    snapshot: Snapshot

    def __post_init__(self):
        if not isinstance(self.snapshot, Snapshot) or self.key != self.snapshot.digest:
            raise ValueError("Library entries require an unchanged snapshot and its stable digest.")
        if self.name != self.snapshot.to_dict().get("name") or not isinstance(self.name, str):
            raise ValueError("Library entry names must match their existing snapshot.")

    @classmethod
    def from_dict(cls, value):
        snapshot = Snapshot.from_dict(value)
        return cls(snapshot.digest, value["name"], snapshot)


@dataclass(frozen=True)
class SmartDesignRequirements:
    maximum_diameter: float
    targets: tuple = ()
    constraints: tuple = ()
    library_keys: tuple[str, ...] = ()
    geometries: tuple[str, ...] = (CURRENT_GEOMETRY,)
    budget: int = 180
    seed: int = 1729
    top_n: int = 10
    reject_warnings: bool = False
    metric_definitions: tuple = DEFAULT_METRICS

    def __post_init__(self):
        for name in ("targets", "constraints", "library_keys", "geometries", "metric_definitions"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        if not finite_number(self.maximum_diameter) or self.maximum_diameter <= 0:
            raise ValueError("Enter a positive maximum outer diameter.")
        if not self.targets:
            raise ValueError("Enable at least one target: burn time, total impulse or average thrust.")
        requirements = DesignRequirements(
            targets=self.targets, constraints=self.constraints, reject_warnings=self.reject_warnings
        )
        MetricRegistry(self.metric_definitions).validate_requirements(requirements)
        if any(t.value <= 0 for t in self.targets):
            raise ValueError("Smart Design target values must be positive.")
        if not self.library_keys or any(not isinstance(k, str) for k in self.library_keys):
            raise ValueError("Select at least one existing propellant library entry.")
        if len(set(self.library_keys)) != len(self.library_keys):
            raise ValueError("Allowed library entries must be unique.")
        if not self.geometries or any(not isinstance(g, str) for g in self.geometries):
            raise ValueError("Select at least one compatible grain geometry.")
        if len(set(self.geometries)) != len(self.geometries):
            raise ValueError("Allowed geometries must be unique.")
        if type(self.budget) is not int or not 1 <= self.budget <= 10000:
            raise ValueError("Candidate budget must be between 1 and 10000.")
        if type(self.seed) is not int:
            raise ValueError("Random seed must be an integer.")
        if type(self.top_n) is not int or not 1 <= self.top_n <= 100:
            raise ValueError("Top N must be between 1 and 100.")
        bounds = {}
        for constraint in self.constraints:
            low, high = bounds.get(constraint.metric, (None, None))
            if constraint.minimum is not None:
                low = constraint.minimum if low is None else max(low, constraint.minimum)
            if constraint.maximum is not None:
                high = constraint.maximum if high is None else min(high, constraint.maximum)
            if low is not None and high is not None and low > high:
                raise ValueError("Constraints for the same metric contradict each other.")
            bounds[constraint.metric] = (low, high)
        for target in self.targets:
            low, high = bounds.get(target.metric, (None, None))
            if target.weight and (low is not None and target.value < low or high is not None and target.value > high):
                raise ValueError("A target value lies outside its allowed constraint range.")

    @property
    def digest(self):
        values = DesignRequirements(
            targets=self.targets, constraints=self.constraints, reject_warnings=self.reject_warnings
        ).to_dict()
        values.update(
            maximum_diameter=self.maximum_diameter,
            library_keys=self.library_keys,
            geometries=self.geometries,
            budget=self.budget,
            seed=self.seed,
            top_n=self.top_n,
        )
        if self.metric_definitions != DEFAULT_METRICS:
            values["metrics"] = [vars(d) for d in self.metric_definitions]
        return Snapshot.from_dict(values).digest


@dataclass(frozen=True)
class SearchSpaceVariant:
    key: str
    baseline: Snapshot
    requirements: DesignRequirements
    library_key: str
    library_name: str
    geometries: tuple[str, ...]

    @property
    def initial_values(self):
        motor = Motor(self.baseline.to_dict())
        values = []
        for variable in self.requirements.variables:
            value = variable.path.read(motor)
            value = min(variable.range.maximum, max(variable.range.minimum, value))
            values.append(int(value) if variable.range.integer else float(value))
        return tuple(values)


@dataclass(frozen=True)
class SmartSearchPlan:
    baseline: Snapshot
    requirements: SmartDesignRequirements
    variants: tuple[SearchSpaceVariant, ...]

    @property
    def digest(self):
        return Snapshot.from_dict(
            {
                "baseline": self.baseline.digest,
                "requirements": self.requirements.digest,
                "variants": [v.key for v in self.variants],
            }
        ).digest

    def variant(self, key):
        return next(v for v in self.variants if v.key == key)


class SearchSpaceBuilder:
    """Preserve count/configuration; select exact library entries and compatible types.

    Alternate types must have all their properties supplied by each baseline
    grain, with matching property types and accepted values. Custom shapes and
    missing geometry-specific dimensions are never fabricated.
    """

    @staticmethod
    def compatible_geometries(baseline):
        baseline = baseline if isinstance(baseline, Snapshot) else Snapshot.from_dict(baseline)
        motor = Motor(baseline.to_dict())
        options = [CURRENT_GEOMETRY]
        if not motor.grains:
            return tuple(options)
        current = tuple(g.geomName for g in motor.grains)
        for name, constructor in sorted(grainTypes.items()):
            if current == (name,) * len(current):
                continue
            compatible = True
            for grain in motor.grains:
                alternative = constructor()
                for key, prop in alternative.props.items():
                    if key not in grain.props or type(grain.props[key]) is not type(prop):
                        compatible = False
                        break
                    value = deepcopy(grain.getProperty(key))
                    prop.setValue(value)
                    if prop.getValue() != value:
                        compatible = False
                        break
                if not compatible:
                    break
            if compatible:
                options.append(name)
        return tuple(options)

    def build(self, baseline, requirements, library_entries):
        baseline = baseline if isinstance(baseline, Snapshot) else Snapshot.from_dict(baseline)
        if not isinstance(requirements, SmartDesignRequirements):
            raise TypeError("Smart Design requires validated project requirements.")
        motor = Motor(baseline.to_dict())
        if not motor.grains:
            raise ValueError("The baseline must contain at least one grain.")
        entries = {entry.key: entry for entry in library_entries}
        if any(key not in entries for key in requirements.library_keys):
            raise ValueError("An allowed propellant is not present in the existing library.")
        compatible = self.compatible_geometries(baseline)
        if any(key not in compatible for key in requirements.geometries):
            raise ValueError("A selected geometry requires parameters absent from the baseline.")
        count = len(requirements.library_keys) * len(requirements.geometries)
        if count > requirements.budget:
            raise ValueError("Increase the candidate budget or select fewer library and geometry options.")
        variants = []
        # Sort by stable keys; widget order and completion order cannot affect results.
        for library_key in sorted(requirements.library_keys):
            for geometry in sorted(requirements.geometries):
                candidate = Motor(deepcopy(baseline.to_dict()))
                data = deepcopy(baseline.to_dict())
                data["propellant"] = entries[library_key].snapshot.to_dict()
                if geometry != CURRENT_GEOMETRY:
                    data["grains"] = [
                        {
                            "type": geometry,
                            "properties": {k: deepcopy(g.getProperty(k)) for k in grainTypes[geometry]().props},
                        }
                        for g in candidate.grains
                    ]
                candidate = Motor(deepcopy(data))
                # The library snapshot must survive the existing setters exactly.
                if candidate.propellant.getProperties() != entries[library_key].snapshot.to_dict():
                    raise ValueError("An existing library entry contains values rejected by the engine.")
                variables = self._variables(candidate, requirements.maximum_diameter)
                design = DesignRequirements(
                    variables, requirements.targets, requirements.constraints, requirements.reject_warnings
                )
                snapshot = Snapshot.from_dict(data)
                CandidateGenerator(snapshot.to_dict(), design)
                key = Snapshot.from_dict({"snapshot": snapshot.digest, "requirements": design.digest}).digest
                variants.append(
                    SearchSpaceVariant(
                        key,
                        snapshot,
                        design,
                        library_key,
                        entries[library_key].name,
                        tuple(g.geomName for g in candidate.grains),
                    )
                )
        return SmartSearchPlan(baseline, requirements, tuple(variants))

    @staticmethod
    def _variables(motor, maximum_diameter):
        variables = []
        envelope = max([g.getProperty("diameter") for g in motor.grains] + [motor.nozzle.getProperty("exit")])
        radial_scale = min(1.0, maximum_diameter / envelope) if envelope > 0 else 1.0
        for index, collection in [(None, motor.nozzle), *enumerate(motor.grains)]:
            for key, prop in collection.props.items():
                # Nozzle loss/material coefficients stay fixed. Grain numeric geometry
                # is discovered from engine metadata, never display strings.
                if (
                    not isinstance(prop, (FloatProperty, IntProperty))
                    or index is None
                    and key not in ("throat", "exit")
                ):
                    continue
                value = prop.getValue()
                if not finite_number(value):
                    raise ValueError("Baseline geometry contains a nonfinite numeric property.")
                # Proportional search-space placement, not a physics calculation:
                # retain axial length, but fit baseline radial dimensions to a
                # smaller envelope before exploring their metadata-bounded ranges.
                if prop.unit == "m" and key != "length":
                    value *= radial_scale
                span = abs(value) * 0.25
                if isinstance(prop, IntProperty):
                    span = max(1, math.ceil(span))
                low, high = max(prop.min, value - span), min(prop.max, value + span)
                if key == "diameter" or index is None and key in ("throat", "exit"):
                    high = min(high, maximum_diameter)
                    if low > high:
                        low = max(prop.min, high * 0.75)
                if isinstance(prop, IntProperty):
                    low, high = math.ceil(low), math.floor(high)
                if low > high:
                    raise ValueError("The diameter limit is outside the engine property bounds.")
                points = 1 if low == high else (min(3, high - low + 1) if isinstance(prop, IntProperty) else 3)
                path = PropertyPath(f"nozzle.{key}" if index is None else f"grains.{index}.{key}")
                variables.append(DesignVariable(path, ParameterRange(low, high, points, isinstance(prop, IntProperty))))
        return tuple(variables)
