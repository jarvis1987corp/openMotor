"""Stable engine property addresses; display names never participate in lookup."""

import math
import re
from copy import deepcopy
from dataclasses import dataclass
from numbers import Real

from motorlib.properties import EnumProperty, FloatProperty, IntProperty


class PropertyValidationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, order=True)
class PropertyPath:
    """Canonical paths: nozzle.throat, grains.0.coreDiameter, config.timestep.

    config/propellant paths are useful for inspection but are fixed in V1 searches.
    Tabular subproperties, geometry types and counts are deliberately not addressable.
    """

    value: str

    def __post_init__(self):
        if not isinstance(self.value, str) or not re.fullmatch(
            r"(?:(?:nozzle|config|propellant)\.[A-Za-z][A-Za-z0-9_]*|grains\.(?:0|[1-9][0-9]*)\.[A-Za-z][A-Za-z0-9_]*)",
            self.value,
        ):
            raise PropertyValidationError("invalid_path", "Invalid property path: {path}".format(path=self.value))

    def resolve(self, motor):
        parts = self.value.split(".")
        if parts[0] == "grains":
            index = int(parts[1])
            if index >= len(motor.grains):
                raise PropertyValidationError(
                    "invalid_path", "Grain index does not exist: {path}".format(path=self.value)
                )
            collection = motor.grains[index]
        else:
            collection = getattr(motor, parts[0])
        if collection is None or parts[-1] not in collection.props:
            raise PropertyValidationError("invalid_path", "Property does not exist: {path}".format(path=self.value))
        return collection.props[parts[-1]]

    def read(self, motor):
        return deepcopy(self.resolve(motor).getValue())

    def validate_numeric_variable(self, motor):
        prop = self.resolve(motor)
        if self.value.split(".")[0] not in ("nozzle", "grains"):
            raise PropertyValidationError("fixed_property", "Only nozzle and grain numeric properties can vary in V1.")
        if not isinstance(prop, (FloatProperty, IntProperty)):
            raise PropertyValidationError("non_numeric_property", "Only numeric properties can vary in V1.")
        return prop

    def write_validated(self, motor, value):
        """Validate type/bounds, call the existing setter, then always read back.

        Enum support here uses the engine's canonical values. Enum search variables
        are excluded by validate_numeric_variable, as required for V1.
        """
        prop = self.resolve(motor)
        if isinstance(prop, (FloatProperty, IntProperty)):
            if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
                raise PropertyValidationError("invalid_value", "Property value must be a finite number.")
            if isinstance(prop, IntProperty) and int(value) != value:
                raise PropertyValidationError("invalid_value", "Integer properties require integral values.")
            if not prop.min <= value <= prop.max:
                raise PropertyValidationError("out_of_bounds", "Property value is outside the engine bounds.")
        elif isinstance(prop, EnumProperty):
            if value not in prop.values:
                raise PropertyValidationError("invalid_enum", "Value is not a canonical enum value.")
        else:
            raise PropertyValidationError(
                "unsupported_property", "This property cannot be assigned through a design path."
            )
        prop.setValue(value)
        actual = prop.getValue()
        if actual != value:
            raise PropertyValidationError("setter_rejected", "Setter read-back differs from the requested value.")
        return deepcopy(actual)
