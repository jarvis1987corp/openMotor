"""Common result presentation; callers supply names and value formatting."""

from PyQt6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from designassistant.objectives import TargetStatus

MESSAGES = (
    QT_TRANSLATE_NOOP("DesignAssistant", "Constraint status: {status}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Target status: {status}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Satisfied"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Not satisfied"),
    QT_TRANSLATE_NOOP("DesignAssistant", "MATCHED"),
    QT_TRANSLATE_NOOP("DesignAssistant", "NEAR"),
    QT_TRANSLATE_NOOP("DesignAssistant", "MISSED"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Closest candidates"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Closest candidate {number}"),
    QT_TRANSLATE_NOOP(
        "DesignAssistant", "No candidate matched all targets within this search. Closest candidates follow."
    ),
    QT_TRANSLATE_NOOP("DesignAssistant", "{metric}: target {target}; actual {actual}; error {error}; {status}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Match = 100 × exp(-3 × score); score includes a worst-objective penalty."),
    QT_TRANSLATE_NOOP("DesignAssistant", "Combinations screened: {screened}/{available}"),
    QT_TRANSLATE_NOOP("DesignAssistant", "Broad screening"),
)


def tr(source):
    return QCoreApplication.translate("DesignAssistant", source)


def assessment_lines(analysis, feasible, *, label=lambda key: key, value=lambda key, number: f"{number:.6g}"):
    lines = [
        tr("Constraint status: {status}").format(status=tr("Satisfied" if feasible else "Not satisfied")),
        tr("Target status: {status}").format(status=tr(analysis.target_status.value)),
    ]
    for error in analysis.targets:
        if error.weight <= 0:
            continue
        signed = error.relative_error * (-1 if error.deviation < 0 else 1)
        lines.append(
            tr("{metric}: target {target}; actual {actual}; error {error}; {status}").format(
                metric=label(error.metric),
                target=value(error.metric, error.target),
                actual=value(error.metric, error.actual),
                error=f"{signed:+.1%}",
                status=tr(error.status.value),
            )
        )
    return tuple(lines)


def closest_only(records):
    return bool(records) and not any(r.analysis.target_status == TargetStatus.MATCHED for r in records)
