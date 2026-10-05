"""Compact candidate table with numeric sorting and stable identity selection."""

from bisect import insort

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt

from designassistant import MetricRegistry
from motorlib.units import convert
from uilib.localization import display_text

from .presentation import (
    STATUS_LABELS,
    candidate_status,
    diagnostic_text,
    display_number,
    metric_label,
    metric_unit,
    translate,
)

SORT_ROLE = int(Qt.ItemDataRole.UserRole) + 1
ID_ROLE = int(Qt.ItemDataRole.UserRole) + 2
STATUS_ROLE = int(Qt.ItemDataRole.UserRole) + 3


class ResultsModel(QAbstractTableModel):
    def __init__(self, options, preferences, parent=None):
        super().__init__(parent)
        self.options, self.preferences = options, preferences
        self.variables = ()
        self.rows = []
        self.ranks = {}
        self._ranked = []
        self.metrics = MetricRegistry().definitions

    def reset(self, variables):
        self.beginResetModel()
        self.variables = tuple(variables)
        self.rows.clear()
        self.ranks.clear()
        self._ranked.clear()
        self.endResetModel()

    def append(self, proposal, evaluation):
        row = len(self.rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self.rows.append((proposal, evaluation))
        self.endInsertRows()
        if candidate_status(evaluation) == "feasible":
            insort(self._ranked, (evaluation.score, evaluation.candidate_id))
            self.ranks = {candidate_id: i + 1 for i, (_, candidate_id) in enumerate(self._ranked)}
            self.dataChanged.emit(self.index(0, 0), self.index(row, 0))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 5 + len(self.variables) + len(self.metrics)

    def option(self, path):
        return next(o for o in self.options if o.path == path)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal or role not in (
            Qt.ItemDataRole.DisplayRole,
            Qt.ItemDataRole.ToolTipRole,
        ):
            return super().headerData(section, orientation, role)
        if section < 5:
            return tuple(map(translate, ("Rank", "Candidate", "Score", "Status", "Diagnostics")))[section]
        if section < 5 + len(self.variables):
            option = self.option(self.variables[section - 5].path)
            return "{} ({})".format(option.label(), option.display_unit) if option.display_unit else option.label()
        metric = self.metrics[section - 5 - len(self.variables)]
        _, unit = metric_unit(metric.key, self.preferences)
        return "{} ({})".format(metric_label(metric.key), unit) if unit else metric_label(metric.key)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        proposal, evaluation = self.rows[index.row()]
        if role == ID_ROLE:
            return proposal.candidate_id
        if role == STATUS_ROLE:
            return candidate_status(evaluation)
        diagnostics = (*evaluation.outcome.diagnostics, *evaluation.constraints.violations)
        if role == Qt.ItemDataRole.ToolTipRole:
            return "\n".join(diagnostic_text(d, self.options) for d in diagnostics)
        if role not in (Qt.ItemDataRole.DisplayRole, SORT_ROLE):
            return None
        column = index.column()
        numeric = role == SORT_ROLE
        if column == 0:
            return self.ranks.get(proposal.candidate_id, float("inf") if numeric else "—")
        if column == 1:
            return index.row() + 1
        if column == 2:
            return (
                (evaluation.score if evaluation.score is not None else float("inf"))
                if numeric
                else ("{:.8g}".format(evaluation.score) if evaluation.score is not None else "—")
            )
        if column == 3:
            return display_text(STATUS_LABELS[candidate_status(evaluation)])
        if column == 4:
            return len(diagnostics) if numeric else "\n".join(diagnostic_text(d, self.options) for d in diagnostics)
        if column < 5 + len(self.variables):
            path = self.variables[column - 5].path
            value = next(a.value for a in proposal.assignments if a.path == path)
            option = self.option(path)
            return (
                convert(value, option.unit, option.display_unit)
                if numeric
                else display_number(value, option.unit, option.display_unit)
            )
        definition = self.metrics[column - 5 - len(self.variables)]
        try:
            value = evaluation.outcome.metric(definition.key)
        except KeyError:
            return float("inf") if numeric else "—"
        unit, display_unit = metric_unit(definition.key, self.preferences)
        return convert(value, unit, display_unit) if numeric else display_number(value, unit, display_unit)

    def retranslate(self):
        self.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, self.columnCount() - 1)
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, self.columnCount() - 1))


class ResultsFilter(QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.status = "all"
        self.text = ""
        self.top_n = None
        self.setSortRole(SORT_ROLE)

    def set_filters(self, status, text):
        self.status, self.text = status, text.casefold()
        self.invalidateFilter()

    def set_top_n(self, value):
        self.top_n = value
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row, parent):
        model = self.sourceModel()
        if self.top_n is not None and model.data(model.index(source_row, 0), STATUS_ROLE) == "feasible":
            rank = model.data(model.index(source_row, 0), SORT_ROLE)
            if rank > self.top_n:
                return False
        if self.status != "all" and model.data(model.index(source_row, 0), STATUS_ROLE) != self.status:
            return False
        return not self.text or any(
            self.text in str(model.data(model.index(source_row, column))).casefold()
            for column in range(model.columnCount())
        )
