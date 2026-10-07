"""Smart result summaries and comparison; no mutable simulation objects."""

import json

from PyQt6.QtCore import QAbstractTableModel, QEvent, QModelIndex, Qt
from PyQt6.QtWidgets import QDialog, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout

from designassistant import MetricRegistry
from motorlib.units import convert
from uilib.localization import display_text, geometry_name

from .assessment import assessment_lines
from .presentation import (
    STATUS_LABELS,
    available_variables,
    candidate_status,
    diagnostic_text,
    display_number,
    metric_label,
    metric_unit,
    translate,
)
from .results import ID_ROLE, SORT_ROLE, STATUS_ROLE


def explanation_text(record):
    data = json.loads(record.arguments_json)
    arguments = dict(data.get("kwargs", {}))
    if "metric" in arguments:
        arguments["metric"] = metric_label(arguments["metric"])
    return translate(record.source).format(*data.get("args", []), **arguments)


def geometry_label(variant):
    return " / ".join(dict.fromkeys(geometry_name(name) for name in variant.geometries))


class SmartResultsModel(QAbstractTableModel):
    is_smart = True

    def __init__(self, preferences, parent=None):
        super().__init__(parent)
        self.preferences = preferences
        self.rows, self.ranks, self.ranked = [], {}, {}
        self.store = None
        self.metrics = MetricRegistry().definitions
        self._options = {}

    def reset(self, store):
        self.beginResetModel()
        self.store = store
        self.rows.clear()
        self.ranks.clear()
        self.ranked.clear()
        self._options = {v.key: available_variables(v.baseline, self.preferences) for v in store.plan.variants}
        self.endResetModel()

    def append(self, proposal, evaluation):
        row = len(self.rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self.rows.append((proposal, evaluation))
        self.endInsertRows()
        self.ranked = {r.proposal.candidate_id: r for r in self.store.ranked()}
        self.ranks = {key: value.rank for key, value in self.ranked.items()}
        self.dataChanged.emit(self.index(0, 0), self.index(row, self.columnCount() - 1))

    def options_for(self, candidate_id):
        return self._options[self.store.records[candidate_id][2].variant_key]

    def parameter_text(self, proposal):
        options = {o.path: o for o in self.options_for(proposal.candidate_id)}
        return "; ".join(
            "{}: {} {}".format(
                options[a.path].label(),
                display_number(a.value, options[a.path].unit, options[a.path].display_unit),
                options[a.path].display_unit,
            )
            for a in proposal.assignments
        )

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 9 + len(self.metrics)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or role != Qt.ItemDataRole.DisplayRole:
            return super().headerData(section, orientation, role)
        labels = ("Rank", "Candidate", "Score", "Library Entry", "Geometry", "Status", "Parameters")
        if section < len(labels):
            return translate(labels[section])
        if section < len(labels) + len(self.metrics):
            metric = self.metrics[section - len(labels)]
            return f"{metric_label(metric.key)} ({metric_unit(metric.key, self.preferences)[1]})"
        return translate("Ranking Explanation" if section == len(labels) + len(self.metrics) else "Diagnostics")

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        proposal, evaluation = self.rows[index.row()]
        candidate_id = proposal.candidate_id
        if role == ID_ROLE:
            return candidate_id
        if role == STATUS_ROLE:
            return candidate_status(evaluation)
        if role not in (Qt.ItemDataRole.DisplayRole, SORT_ROLE, Qt.ItemDataRole.ToolTipRole):
            return None
        context = self.store.records[candidate_id][2]
        variant = self.store.plan.variant(context.variant_key)
        ranked = self.ranked.get(candidate_id)
        if role == Qt.ItemDataRole.ToolTipRole:
            explanations, diagnostics = self._notes(candidate_id, evaluation, ranked)
            return "\n".join((self.parameter_text(proposal), explanations, diagnostics))
        if role not in (Qt.ItemDataRole.DisplayRole, SORT_ROLE):
            return None
        numeric = role == SORT_ROLE
        column = index.column()
        if column == 0:
            return self.ranks.get(candidate_id, float("inf") if numeric else "—")
        if column == 1:
            return index.row() + 1
        if column == 2:
            return (
                (evaluation.score if evaluation.score is not None else float("inf"))
                if numeric
                else ("{:.8g}".format(evaluation.score) if evaluation.score is not None else "—")
            )
        if column == 3:
            return variant.library_name
        if column == 4:
            return geometry_label(variant)
        if column == 5:
            return display_text(STATUS_LABELS[candidate_status(evaluation)])
        if column == 6:
            return self.parameter_text(proposal)
        if column < 7 + len(self.metrics):
            definition = self.metrics[column - 7]
            try:
                value = evaluation.outcome.metric(definition.key)
            except KeyError:
                return float("inf") if numeric else "—"
            unit, display_unit = metric_unit(definition.key, self.preferences)
            return convert(value, unit, display_unit) if numeric else display_number(value, unit, display_unit)
        explanations, diagnostics = self._notes(candidate_id, evaluation, ranked)
        return explanations if column == 7 + len(self.metrics) else diagnostics

    def _notes(self, candidate_id, evaluation, ranked):
        explanations = "\n".join(explanation_text(r) for r in ranked.analysis.explanations) if ranked else ""
        diagnostics = "\n".join(
            diagnostic_text(d, self.options_for(candidate_id))
            for d in (*evaluation.outcome.diagnostics, *evaluation.constraints.violations)
        )
        return explanations, diagnostics

    def detail_text(self, candidate_id):
        proposal, evaluation, context = self.store.records[candidate_id]
        variant = self.store.plan.variant(context.variant_key)
        lines = [
            f"{translate('Library Entry')}: {variant.library_name}",
            f"{translate('Geometry')}: {geometry_label(variant)}",
            translate("Score: {score}").format(score=evaluation.score if evaluation.score is not None else "—"),
            "",
            translate("Parameters"),
            self.parameter_text(proposal),
            "",
            translate("Summary Metrics"),
        ]
        for metric in evaluation.outcome.metrics:
            unit, display = metric_unit(metric.key, self.preferences)
            lines.append(f"{metric_label(metric.key)}: {display_number(metric.value, unit, display)} {display}")
        record = self.ranked.get(candidate_id)
        if record:
            lines.extend(("", *assessment_lines(record.analysis, evaluation.constraints.feasible,
                                                label=metric_label)))
            lines.extend(("", translate("Target Deviations")))
            for target in record.analysis.targets:
                unit, display = metric_unit(target.metric, self.preferences)
                lines.append(
                    translate(
                        "{metric}: target {target}; actual {actual}; deviation {deviation}; "
                        "contribution {contribution}."
                    ).format(
                        metric=metric_label(target.metric),
                        target=f"{display_number(target.target, unit, display)} {display}",
                        actual=f"{display_number(target.actual, unit, display)} {display}",
                        deviation=f"{display_number(target.deviation, unit, display)} {display}",
                        contribution="{:.6g}".format(target.contribution),
                    )
                )
            lines.extend(("", translate("Ranking Explanation")))
            lines.extend(explanation_text(r) for r in record.analysis.explanations)
        lines.extend(("", translate("Diagnostics")))
        diagnostics = (*evaluation.outcome.diagnostics, *evaluation.constraints.violations)
        lines.extend(diagnostic_text(d, self.options_for(candidate_id)) for d in diagnostics)
        if not diagnostics:
            lines.append(translate("No diagnostics."))
        return "\n".join(lines)

    def retranslate(self):
        if self.store is not None:
            self.ranked = {r.proposal.candidate_id: r for r in self.store.ranked()}
            self.ranks = {key: record.rank for key, record in self.ranked.items()}
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, self.columnCount() - 1))


class CandidateComparison(QDialog):
    def __init__(self, preferences, parent=None, *, registry=None):
        super().__init__(parent)
        self.preferences = preferences
        self.records = ()
        self.definitions = (registry or MetricRegistry()).definitions
        self.table = QTableWidget()
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.close_button = QPushButton()
        self.close_button.clicked.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.table)
        layout.addWidget(self.close_button)
        self.resize(1100, 650)
        self.retranslate()

    def show_candidates(self, records):
        self.records = tuple(records)
        self.retranslate()
        self.show()
        self.raise_()

    def _cell(self, row, column, text, tooltip=""):
        item = QTableWidgetItem(str(text))
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        item.setToolTip(tooltip or str(text))
        self.table.setItem(row, column, item)

    def retranslate(self):
        self.setWindowTitle(translate("Compare Candidates"))
        self.close_button.setText(translate("Close"))
        self.table.clear()
        self.table.setColumnCount(1 + len(self.records) * 2)
        headers = [translate("Metric / Requirement")]
        for record in self.records:
            title = translate("Rank {rank}: {name}").format(rank=record.rank, name=record.variant.library_name)
            headers.extend((title + " — " + translate("Actual"), translate("Deviation")))
        self.table.setHorizontalHeaderLabels(headers)
        if not self.records:
            self.table.setRowCount(0)
            return
        definitions = self.definitions
        self.table.setRowCount(4 + len(definitions))
        for row, source in enumerate(("Score", "Geometry", "Warnings", "Ranking Explanation")):
            self._cell(row, 0, translate(source))
        for index, record in enumerate(self.records):
            column = 1 + index * 2
            warnings = [d for d in record.evaluation.outcome.diagnostics if d.level == "WARNING"]
            self._cell(0, column, "{:.8g}".format(record.evaluation.score))
            self._cell(1, column, geometry_label(record.variant))
            self._cell(2, column, len(warnings), "\n".join(diagnostic_text(d) for d in warnings))
            self._cell(3, column, "\n".join(explanation_text(r) for r in record.analysis.explanations))
            for row, definition in enumerate(definitions, 4):
                unit, display = metric_unit(definition.key, self.preferences)
                targets = [t for t in record.analysis.targets if t.metric == definition.key]
                bounds = [c for c in record.analysis.constraints if c.metric == definition.key]
                label = f"{metric_label(definition.key)} ({display})"
                if targets:
                    label += "\n" + translate("Target Value") + ": " + display_number(targets[0].target, unit, display)
                for bound in bounds:
                    for source, value in (("Minimum", bound.minimum), ("Maximum", bound.maximum)):
                        if value is not None:
                            label += "\n" + translate(source) + ": " + display_number(value, unit, display)
                self._cell(row, 0, label)
                self._cell(row, column, display_number(record.evaluation.outcome.metric(definition.key), unit, display))
                self._cell(row, column + 1, display_number(targets[0].deviation, unit, display) if targets else "—")
        self.table.resizeRowsToContents()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "table"):
            self.retranslate()
        super().changeEvent(event)
