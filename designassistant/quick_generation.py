"""Dimension-driven initial designs, using only existing engine properties.

Fractions below are documented search heuristics, not ballistics equations.
Discrete library/geometry/count choices are snapshots for the existing Smart
ask/tell optimizer. No simulations, material changes or Qt objects belong here.
"""

import json
import math
import random
from copy import deepcopy
from dataclasses import dataclass

from motorlib.grains import grainTypes
from motorlib.motor import Motor
from motorlib.nozzle import Nozzle
from motorlib.properties import FloatProperty, IntProperty
from motorlib.simResult import SimAlertLevel

from .generator import CandidateGenerator
from .models import DesignRequirements, DesignVariable, ParameterRange, Snapshot, TextRecord, finite_number
from .paths import PropertyPath
from .smart import SearchSpaceVariant, SmartSearchPlan


@dataclass(frozen=True)
class QuickDimensions:
    maximum_diameter: float
    maximum_length: float

    def __post_init__(self):
        if any(not finite_number(v) or v <= 0 for v in (self.maximum_diameter, self.maximum_length)):
            raise ValueError("Dimensions must be positive finite values.")


@dataclass(frozen=True)
class GeometryTemplate:
    geometry: str
    properties: Snapshot
    ranges: tuple[tuple[str, ParameterRange], ...]


def _set(collection, key, value):
    """Set all kinds of engine properties with mandatory exact read-back."""
    collection.setProperty(key, deepcopy(value))
    if collection.getProperty(key) != value:
        raise ValueError("Engine setter read-back rejected an initial property.")


def _range(collection, key, low, high, initial):
    prop = collection.props[key]
    if not isinstance(prop, (FloatProperty, IntProperty)):
        raise ValueError("Automatic ranges require numeric engine metadata.")
    low, high = max(prop.min, low), min(prop.max, high)
    integer = isinstance(prop, IntProperty)
    if integer:
        low, high = math.ceil(low), math.floor(high)
    if low > high:
        raise ValueError("Dimensions do not allow an engine property range.")
    initial = min(high, max(low, initial))
    _set(collection, key, int(initial) if integer else initial)
    return key, ParameterRange(low, high, 1 if low == high else 3, integer)


class QuickDesignGeometryFactory:
    """Separate validated presets for every current openMotor geometry.

    Custom Grain starts with one square core in SI units; imported DXF data is
    never borrowed from the user's motor. Its polygon is fixed during this
    search. End Burner has a single grain because the engine requires it first.
    """

    # key -> (low, high, initial), as fractions of the requested diameter.
    PROFILES = {
        "BATES": {"coreDiameter": (0.10, 0.50, 0.30)},
        "End Burner": {},
        "C Grain": {"slotWidth": (0.05, 0.18, 0.10), "slotOffset": (-0.12, 0.12, 0.0)},
        "D Grain": {"slotOffset": (-0.15, 0.15, 0.0)},
        "Conical": {"forwardCoreDiameter": (0.12, 0.25, 0.18), "aftCoreDiameter": (0.30, 0.48, 0.40)},
        "Custom Grain": {},
        "Finocyl": {
            "coreDiameter": (0.20, 0.40, 0.30),
            "finLength": (0.04, 0.08, 0.06),
            "finWidth": (0.02, 0.04, 0.03),
        },
        "Moon Burner": {"coreDiameter": (0.12, 0.30, 0.20), "coreOffset": (0.03, 0.12, 0.08)},
        "Rod and Tube": {
            "coreDiameter": (0.30, 0.50, 0.40),
            "rodDiameter": (0.16, 0.22, 0.20),
            "supportDiameter": (0.04, 0.08, 0.06),
        },
        "Star Grain": {"pointLength": (0.12, 0.24, 0.18), "pointWidth": (0.03, 0.06, 0.04)},
        "X Core": {"slotWidth": (0.04, 0.12, 0.08), "slotLength": (0.12, 0.25, 0.20)},
    }

    def grain_counts(self, dimensions):
        # A finite exploration limit, not a manufacturing/physical limit.
        # Very short envelopes still allow one grain; length ranges are always
        # capped by the actual maximum length divided among the selected count.
        largest = int(min(6, max(1, dimensions.maximum_length / dimensions.maximum_diameter * 2)))
        return tuple(range(1, largest + 1))

    def create(self, geometry, dimensions, count=1):
        if geometry not in self.PROFILES or geometry not in grainTypes:
            raise ValueError("This geometry has no automatic parameterization.")
        if type(count) is not int or count not in self.grain_counts(dimensions):
            raise ValueError("Grain count is outside the dimension-driven exploration range.")
        if geometry == "End Burner" and count != 1:
            raise ValueError("The existing engine requires an end burner to be the forward-most grain.")
        grain = grainTypes[geometry]()
        diameter = min(dimensions.maximum_diameter, grain.props["diameter"].max)
        length = min(dimensions.maximum_length / count, grain.props["length"].max)
        ranges = [
            _range(grain, "diameter", diameter * 0.60, diameter * 0.98, diameter * 0.90),
            _range(grain, "length", length * 0.15, length * 0.98, length * 0.70),
        ]
        for key, fractions in self.PROFILES[geometry].items():
            ranges.append(_range(grain, key, *(diameter * fraction for fraction in fractions)))
        if geometry == "Finocyl":
            ranges.append(_range(grain, "numFins", 3, 8, 6))
            _set(grain, "invertedFins", False)
        elif geometry == "Star Grain":
            ranges.append(_range(grain, "numPoints", 3, 8, 6))
        elif geometry == "Custom Grain":
            side = diameter * 0.10
            _set(grain, "points", [[[-side, -side], [side, -side], [side, side], [-side, side]]])
            _set(grain, "dxfUnit", "m")
        errors = [alert.description for alert in grain.getGeometryErrors() if alert.level == SimAlertLevel.ERROR]
        if errors:
            raise ValueError("; ".join(errors))
        return GeometryTemplate(geometry, Snapshot.from_dict(grain.getProperties()), tuple(ranges))


class QuickDesignNozzleFactory:
    """Existing nozzle type, initialized independently of the source project."""

    def create(self, dimensions, geometry=None):
        nozzle = Nozzle()
        diameter = min(dimensions.maximum_diameter, nozzle.props["throat"].max, nozzle.props["exit"].max)
        ranges = (
            _range(
                nozzle,
                "throat",
                diameter * 0.06,
                diameter * 0.30,
                diameter * (0.06 if geometry == "End Burner" else 0.15),
            ),
            _range(nozzle, "exit", diameter * 0.31, diameter * 0.60, diameter * 0.40),
        )
        for key, value in (("efficiency", 1.0), ("divAngle", 15.0), ("convAngle", 45.0)):
            _set(nozzle, key, value)
        errors = [alert.description for alert in nozzle.getGeometryErrors() if alert.level == SimAlertLevel.ERROR]
        if errors:
            raise ValueError("; ".join(errors))
        return Snapshot.from_dict(nozzle.getProperties()), ranges


class QuickDesignSearchSpaceBuilder:
    """Budgeted discrete coverage followed by the unchanged Smart optimizer.

    Cover libraries, supported geometries and counts before additional seeded
    combinations. The budget need not enumerate the entire Cartesian product.
    Selection depends on dimensions, library keys and seed, never on targets,
    labels or source grain/nozzle properties.
    """

    def build(self, baseline, requirements, entries, dimensions):
        factory = QuickDesignGeometryFactory()
        templates, diagnostics = {}, []
        for geometry in sorted(grainTypes):
            for count in (1,) if geometry == "End Burner" else factory.grain_counts(dimensions):
                try:
                    templates[geometry, count] = factory.create(geometry, dimensions, count)
                except ValueError as error:
                    diagnostics.append(
                        TextRecord(
                            "QuickDesign",
                            "Skipped geometry {geometry}, {count} grains: {reason}",
                            json.dumps(
                                {"args": [], "kwargs": {"geometry": geometry, "count": count, "reason": str(error)}}
                            ),
                        )
                    )
        if not templates:
            raise ValueError(json.loads(diagnostics[0].arguments_json)["kwargs"]["reason"])
        pool = [(entry, geometry, count) for entry in entries for geometry, count in sorted(templates)]
        random.Random(requirements.seed).shuffle(pool)
        geometries = {geometry for geometry, _ in templates}
        counts = {count for _, count in templates}
        libraries = {entry.key for entry in entries}
        uncovered = (set(libraries), set(geometries), set(counts))
        chosen = []
        while any(uncovered):

            def coverage(option):
                entry, geometry, count = option
                return sum(value in remaining for value, remaining in zip((entry.key, geometry, count), uncovered))

            option = max(pool, key=coverage)
            pool.remove(option)
            chosen.append(option)
            for value, remaining in zip((option[0].key, option[1], option[2]), uncovered):
                remaining.discard(value)
        if len(chosen) > requirements.budget:
            raise ValueError("Increase search quality or select fewer existing library entries.")
        limit = min(len(pool) + len(chosen), max(len(chosen), requirements.budget // 8))
        chosen.extend(pool[: limit - len(chosen)])
        variants = []
        config = Motor().config.getProperties()
        config.update(deepcopy(baseline.to_dict().get("config", {})))
        for entry, geometry, count in sorted(chosen, key=lambda o: (o[0].key, o[1], o[2])):
            nozzle, nozzle_ranges = QuickDesignNozzleFactory().create(dimensions, geometry)
            template = templates[geometry, count]
            data = Motor().getDict()
            data.update(
                config=deepcopy(config),
                nozzle=nozzle.to_dict(),
                propellant=entry.snapshot.to_dict(),
                grains=[{"type": geometry, "properties": template.properties.to_dict()} for _ in range(count)],
            )
            candidate = Motor(deepcopy(data))
            if candidate.getDict() != data:
                raise ValueError("Engine setter rejected generated design or project configuration.")
            variables = [DesignVariable(PropertyPath("nozzle." + key), bounds) for key, bounds in nozzle_ranges]
            for index in range(count):
                variables.extend(
                    DesignVariable(PropertyPath(f"grains.{index}.{key}"), bounds) for key, bounds in template.ranges
                )
            design = DesignRequirements(
                tuple(variables), requirements.targets, requirements.constraints, requirements.reject_warnings
            )
            snapshot = Snapshot.from_dict(candidate.getDict())
            CandidateGenerator(snapshot.to_dict(), design)
            key = Snapshot.from_dict({"snapshot": snapshot.digest, "requirements": design.digest}).digest
            variants.append(SearchSpaceVariant(key, snapshot, design, entry.key, entry.name, (geometry,) * count))
        return (
            SmartSearchPlan(baseline, requirements, tuple(variants)),
            tuple(diagnostics),
            len(templates) * len(entries),
        )
