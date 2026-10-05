"""Summary metadata and existing SimulationResult getters; no physics formulas."""

from dataclasses import dataclass

from motorlib.simResult import SimulationResult

from .models import MetricValue, finite_number


@dataclass(frozen=True)
class MetricDefinition:
    key: str
    source: str
    unit: str
    getter: str


DEFAULT_METRICS = (
    MetricDefinition("burn_time", "Burn Time", "s", "getBurnTime"),
    MetricDefinition("total_impulse", "Total Impulse", "Ns", "getImpulse"),
    MetricDefinition("average_thrust", "Average Thrust", "N", "getAverageForce"),
    MetricDefinition("specific_impulse", "Specific Impulse", "s", "getISP"),
    MetricDefinition("average_pressure", "Average Chamber Pressure", "Pa", "getAveragePressure"),
    MetricDefinition("maximum_pressure", "Maximum Chamber Pressure", "Pa", "getMaxPressure"),
    MetricDefinition("propellant_mass", "Propellant Mass", "kg", "getPropellantMass"),
    MetricDefinition("peak_mass_flux", "Peak Mass Flux", "kg/(m^2*s)", "getPeakMassFlux"),
)


class MetricRegistry:
    def __init__(self, definitions=DEFAULT_METRICS):
        self.definitions = tuple(definitions)
        if not self.definitions or len({d.key for d in self.definitions}) != len(self.definitions):
            raise ValueError("Metrics must be nonempty and have unique stable keys.")
        for definition in self.definitions:
            if not isinstance(definition, MetricDefinition) or not callable(
                getattr(SimulationResult, definition.getter, None)
            ):
                raise ValueError("Metrics must refer to an existing SimulationResult getter.")
        self._by_key = {d.key: d for d in self.definitions}

    def definition(self, key):
        return self._by_key[key]

    def validate_requirements(self, requirements):
        for item in (*requirements.targets, *requirements.constraints):
            if item.metric not in self._by_key:
                raise ValueError("Unknown metric: " + item.metric)

    def extract(self, result):
        values = []
        for definition in self.definitions:
            value = getattr(result, definition.getter)()
            # NumPy scalar getters are converted at the boundary; booleans are invalid.
            if isinstance(value, bool):
                raise ValueError("Metric is boolean: " + definition.key)
            value = float(value)
            if not finite_number(value):
                raise ValueError("Metric is nonfinite: " + definition.key)
            values.append(MetricValue(definition.key, value, definition.unit))
        return tuple(values)
