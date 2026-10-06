"""Localized labels and unit conversion at the GUI boundary only."""

import json
from dataclasses import dataclass

from PyQt6.QtCore import QCoreApplication

from designassistant import MetricRegistry, OutcomeStatus, PropertyPath
from designassistant.quick import QUICK_METRICS
from motorlib.localization import QT_TRANSLATE_NOOP
from motorlib.motor import Motor
from motorlib.properties import FloatProperty, IntProperty
from motorlib.simResult import SimulationResult
from motorlib.units import convert
from uilib.localization import display_text, geometry_name

METRIC_LABELS = {
    "burn_time": QT_TRANSLATE_NOOP("DesignMetrics", "Burn Time"),
    "total_impulse": QT_TRANSLATE_NOOP("DesignMetrics", "Total Impulse"),
    "average_thrust": QT_TRANSLATE_NOOP("DesignMetrics", "Average Thrust"),
    "specific_impulse": QT_TRANSLATE_NOOP("DesignMetrics", "Specific Impulse"),
    "average_pressure": QT_TRANSLATE_NOOP("DesignMetrics", "Average Chamber Pressure"),
    "maximum_pressure": QT_TRANSLATE_NOOP("DesignMetrics", "Maximum Chamber Pressure"),
    "propellant_mass": QT_TRANSLATE_NOOP("DesignMetrics", "Propellant Mass"),
    "peak_mass_flux": QT_TRANSLATE_NOOP("DesignMetrics", "Peak Mass Flux"),
}
STATUS_LABELS = {
    "feasible": QT_TRANSLATE_NOOP("DesignAssistant", "Feasible"),
    "rejected": QT_TRANSLATE_NOOP("DesignAssistant", "Rejected"),
    "error": QT_TRANSLATE_NOOP("DesignAssistant", "Error"),
    "cancelled": QT_TRANSLATE_NOOP("DesignAssistant", "Cancelled"),
    "ready": QT_TRANSLATE_NOOP("DesignAssistant", "Ready"),
    "running": QT_TRANSLATE_NOOP("DesignAssistant", "Searching"),
    "stopping": QT_TRANSLATE_NOOP("DesignAssistant", "Stopping"),
    "completed": QT_TRANSLATE_NOOP("DesignAssistant", "Completed"),
    "stopped": QT_TRANSLATE_NOOP("DesignAssistant", "Stopped"),
    "failed": QT_TRANSLATE_NOOP("DesignAssistant", "Failed"),
}
QUICK_LABELS = {
    "peak_thrust": QT_TRANSLATE_NOOP("DesignMetrics", "Peak Thrust"),
    "propellant_length": QT_TRANSLATE_NOOP("DesignMetrics", "Propellant Stack Length"),
    "maximum_diameter": QT_TRANSLATE_NOOP("DesignMetrics", "Maximum Propellant Diameter"),
}

# Core stays Qt-free. Mark its canonical English diagnostics/errors here so the
# existing Qt extractor/catalog can translate them when they reach this GUI.
CORE_MESSAGES = (
    QT_TRANSLATE_NOOP("DesignAssistant", "Invalid assignment for {path}: {reason}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Missing assignment for {path}."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Simulation was cancelled."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Simulation did not complete."),
    QT_TRANSLATE_NOOP("DesignAssistant", "At least two simulation samples are required."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Simulation times must start at zero and increase strictly."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Nonfinite score."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Invalid simulation data: {reason}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Simulation failed: {reason}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Candidate failed: {reason}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Candidate has no valid completed simulation."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Candidate has simulation warnings."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Required metric is missing: {metric}."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Metric {metric} is below its minimum."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Metric {metric} exceeds its maximum."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Cannot score candidate: {reason}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Range bounds must be finite and ordered."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Range span must be finite."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Range points must be a positive integer; integer must be boolean."),
    QT_TRANSLATE_NOOP("DesignAssistant", "A one-point range must have identical bounds."),
    QT_TRANSLATE_NOOP("DesignAssistant", "A fixed range must contain exactly one point."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Integer ranges require integral bounds."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Integer grid points must be distinct."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Grid points collapse at floating-point precision."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Variable range exceeds the engine bounds."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Integer engine properties require integer ranges."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Target values must be finite and metric must be identified."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Target scale must be positive and weight nonnegative."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Total target weight must be finite and positive."),
    QT_TRANSLATE_NOOP("DesignAssistant", "A constraint requires a metric and at least one bound."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Constraint bounds must be finite."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Constraint bounds must be ordered."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Variable paths must be unique."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Target metrics must be unique."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Assignment is outside the declared parameter range."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Setter read-back differs from the requested value."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Property value must be a finite number."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Integer properties require integral values."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Property value is outside the engine bounds."),
    QT_TRANSLATE_NOOP("DesignAssistant", "A search is already running."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Select a search strategy and a budget between 1 and 10000."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Random seed must be an integer."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Add at least one target before starting the search."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Stop the search before opening a candidate."),
    QT_TRANSLATE_NOOP("DesignAssistant", "This candidate has no valid simulation and cannot be opened."),
)

DATA_ERROR_TEMPLATES = {
    "Missing or inconsistent channel samples: ": (
        "channel",
        QT_TRANSLATE_NOOP("DesignAssistant", "Missing or inconsistent channel samples: {channel}"),
    ),
    "Invalid grain channel width: ": (
        "channel",
        QT_TRANSLATE_NOOP("DesignAssistant", "Invalid grain channel width: {channel}"),
    ),
    "Nonfinite or nonnumeric channel data: ": (
        "channel",
        QT_TRANSLATE_NOOP("DesignAssistant", "Nonfinite or nonnumeric channel data: {channel}"),
    ),
    "Metric is boolean: ": ("metric", QT_TRANSLATE_NOOP("DesignAssistant", "Metric is boolean: {metric}")),
    "Metric is nonfinite: ": ("metric", QT_TRANSLATE_NOOP("DesignAssistant", "Metric is nonfinite: {metric}")),
}
CHANNEL_LABELS = {key: channel.name for key, channel in SimulationResult(Motor()).channels.items()}


def translate(source):
    return QCoreApplication.translate("DesignAssistant", source)


# Programmatic controls use this fixed context. Mark literal messages (including
# labels used through loops) because pylupdate cannot infer our translate helper.
UI_MESSAGES = (
    QT_TRANSLATE_NOOP("DesignAssistant", "Design Assistant"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Variables"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Targets"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Constraints"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Search Settings"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Progress"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Results"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Candidate Details"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Close"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Score: {score}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Summary Metrics"),
    QT_TRANSLATE_NOOP("DesignAssistant", "No diagnostics."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Rank"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Candidate"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Score"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Status"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Diagnostics"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Parameter"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Minimum"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Maximum"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Values"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Unit"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Metric"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Target Value"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Weight"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Normalization / Tolerance"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Add Variable"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Add Target"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Add Constraint"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Remove Selected"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Start"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Stop"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Details"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Open in Motor Editor"),
    QT_TRANSLATE_NOOP("DesignAssistant", "ERROR always rejects a candidate. WARNING is retained in diagnostics."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Reject candidates with WARNING alerts"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Warnings are accepted unless this constraint is enabled."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Grid Search"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Random Search"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Strategy"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Candidate Budget"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Random Seed"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Maximum candidates for either strategy (1–10000)."),
    QT_TRANSLATE_NOOP("DesignAssistant", "The same baseline, requirements and seed reproduce a random search."),
    QT_TRANSLATE_NOOP("DesignAssistant", "All Candidates"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Filter results…"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Cannot Start Search"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Cannot Open Candidate"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Search Failed"),
    QT_TRANSLATE_NOOP("DesignAssistant", "The current motor must contain grains and a propellant."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Nozzle — {parameter}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Grain {index} ({geometry}) — {parameter}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Grid contains {count} candidates; this run is limited to {budget}."),
    QT_TRANSLATE_NOOP(
        "DesignAssistant",
        "Baseline: {name}. Grain types, grain count, propellant and simulation settings remain fixed.",
    ),
    QT_TRANSLATE_NOOP("DesignAssistant", "Unsaved motor"),
    QT_TRANSLATE_NOOP(
        "DesignAssistant",
        "Processed: {processed}/{total}   Feasible: {feasible}   Rejected: {rejected}   Errors: {errors}",
    ),
    QT_TRANSLATE_NOOP("DesignAssistant", "Search: %v/%m"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Current candidate: %p%"),
    QT_TRANSLATE_NOOP("DesignAssistant", "No candidate running"),
)


@dataclass(frozen=True)
class VariableOption:
    path: PropertyPath
    property_name: object
    unit: str
    display_unit: str
    minimum: float
    maximum: float
    value: float
    integer: bool
    grain_index: int | None = None
    geometry: str = ""

    def label(self):
        name = display_text(self.property_name)
        if self.grain_index is None:
            return translate("Nozzle — {parameter}").format(parameter=name)
        return translate("Grain {index} ({geometry}) — {parameter}").format(
            index=self.grain_index + 1, geometry=geometry_name(self.geometry), parameter=name
        )


def available_variables(baseline, preferences):
    motor = Motor(baseline.to_dict())
    options = []
    for index, collection in [(None, motor.nozzle), *enumerate(motor.grains)]:
        for key, prop in collection.props.items():
            if not isinstance(prop, (FloatProperty, IntProperty)):
                continue
            path = PropertyPath(f"nozzle.{key}" if index is None else f"grains.{index}.{key}")
            unit = preferences.getUnit(prop.unit) if preferences is not None else prop.unit
            options.append(
                VariableOption(
                    path,
                    prop.dispName,
                    prop.unit,
                    unit,
                    prop.min,
                    prop.max,
                    prop.getValue(),
                    isinstance(prop, IntProperty),
                    index,
                    "" if index is None else collection.geomName,
                )
            )
    return tuple(options)


def metric_unit(key, preferences):
    unit = MetricRegistry(QUICK_METRICS).definition(key).unit
    return unit, preferences.getUnit(unit) if preferences is not None else unit


def metric_label(key):
    return display_text((METRIC_LABELS | QUICK_LABELS)[key])


def candidate_status(evaluation):
    if evaluation.outcome.status == OutcomeStatus.CANCELLED:
        return "cancelled"
    if not evaluation.outcome.valid:
        return "error"
    return "feasible" if evaluation.constraints.feasible and evaluation.score is not None else "rejected"


def reason_text(reason):
    for prefix, (argument, template) in DATA_ERROR_TEMPLATES.items():
        if reason.startswith(prefix):
            identity = reason[len(prefix) :]
            label = (
                metric_label(identity)
                if argument == "metric" and identity in (METRIC_LABELS | QUICK_LABELS)
                else (display_text(CHANNEL_LABELS.get(identity, identity)))
            )
            return display_text(template).format(**{argument: label})
    return translate(reason)


def diagnostic_text(diagnostic, options=()):
    labels = {o.path.value: o.label() for o in options}

    def argument(value):
        if isinstance(value, dict) and "context" in value and "source" in value:
            return render(value["context"], value["source"], value.get("args", []), value.get("kwargs", {}))
        return value

    def render(context, source, args, kwargs):
        values = {key: argument(value) for key, value in kwargs.items()}
        if "path" in values:
            values["path"] = labels.get(values["path"], values["path"])
        if "metric" in values and values["metric"] in (METRIC_LABELS | QUICK_LABELS):
            values["metric"] = metric_label(values["metric"])
        if "reason" in values:
            values["reason"] = reason_text(str(values["reason"]))
        return QCoreApplication.translate(context, source).format(*(argument(value) for value in args), **values)

    record = diagnostic.message
    values = json.loads(record.arguments_json)
    text = render(record.context, record.source, values.get("args", []), values.get("kwargs", {}))
    if diagnostic.location is not None:
        record = diagnostic.location
        values = json.loads(record.arguments_json)
        location = render(record.context, record.source, values.get("args", []), values.get("kwargs", {}))
        text = "{}: {}".format(location, text)
    level = QCoreApplication.translate("SimulationAlerts", diagnostic.level.title())
    return "{}: {}".format(level, text)


def display_number(value, unit, display_unit):
    return "{:.8g}".format(convert(value, unit, display_unit))
