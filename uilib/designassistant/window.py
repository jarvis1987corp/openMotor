"""Programmatic Qt form; changing language repaints labels, never input values."""

import math
import time
from dataclasses import dataclass

from PyQt6.QtCore import QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from designassistant import (
    DesignRequirements,
    DesignVariable,
    LibraryEntry,
    MetricConstraint,
    MetricRegistry,
    ParameterRange,
    Target,
)
from motorlib.units import convert
from uilib.localization import display_text

from .controller import DesignController, SearchProgress
from .editors import OptionalBound, number_editor
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
from .results import ID_ROLE, ResultsFilter, ResultsModel
from .smart_form import SmartDesignForm
from .smart_results import CandidateComparison, SmartResultsModel


@dataclass
class VariableRow:
    option: object
    minimum: object
    maximum: object
    points: object


@dataclass
class TargetRow:
    metric: str
    value: object
    weight: object
    scale: object


@dataclass
class ConstraintRow:
    metric: str
    minimum: OptionalBound
    maximum: OptionalBound


class CandidateDetails(QDialog):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.candidate_id = None
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.closeButton = QPushButton()
        self.closeButton.clicked.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)
        layout.addWidget(self.closeButton)
        self.resize(780, 580)
        self.retranslate()

    def show_candidate(self, candidate_id):
        self.candidate_id = candidate_id
        self.retranslate()
        self.show()
        self.raise_()

    def retranslate(self):
        self.setWindowTitle(translate("Candidate Details"))
        self.closeButton.setText(translate("Close"))
        if self.candidate_id not in self.window.controller.evaluations:
            return
        if getattr(self.window.model, "is_smart", False):
            self.text.setPlainText(self.window.model.detail_text(self.candidate_id))
            return
        proposal = self.window.controller.proposals[self.candidate_id]
        evaluation = self.window.controller.evaluations[self.candidate_id]
        lines = [
            display_text(STATUS_LABELS[candidate_status(evaluation)]),
            translate("Score: {score}").format(
                score="—" if evaluation.score is None else "{:.8g}".format(evaluation.score)
            ),
            "",
            translate("Variables"),
        ]
        for assignment in proposal.assignments:
            option = self.window.model.option(assignment.path)
            lines.append(
                "{}: {} {}".format(
                    option.label(),
                    display_number(assignment.value, option.unit, option.display_unit),
                    option.display_unit,
                )
            )
        lines.extend(["", translate("Summary Metrics")])
        for metric in evaluation.outcome.metrics:
            unit, display_unit = metric_unit(metric.key, self.window.preferences)
            lines.append(
                "{}: {} {}".format(
                    metric_label(metric.key), display_number(metric.value, unit, display_unit), display_unit
                )
            )
        lines.extend(["", translate("Diagnostics")])
        diagnostics = (*evaluation.outcome.diagnostics, *evaluation.constraints.violations)
        lines.extend(diagnostic_text(d, self.window.options) for d in diagnostics)
        if not diagnostics:
            lines.append(translate("No diagnostics."))
        self.text.setPlainText("\n".join(lines))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "text"):
            self.retranslate()
        super().changeEvent(event)


class DesignAssistantWindow(QDialog):
    closed = pyqtSignal()

    def __init__(self, baseline, preferences, parent=None, *, source_name="", open_candidate=None, library_entries=(),
                 registry=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.preferences, self.source_name = preferences, source_name
        self.open_candidate = open_candidate
        self.registry = registry or MetricRegistry()
        self.metric_keys = tuple(d.key for d in self.registry.definitions)
        self.controller = DesignController(baseline, self, registry=self.registry)
        self.options = available_variables(self.controller.baseline, preferences)
        self.variable_rows, self.target_rows, self.constraint_rows = [], [], []
        self._state = "ready"
        self._progress = SearchProgress()
        self._close_requested = False
        self._search_started = None
        self.resize(1180, 800)
        self.setMinimumSize(800, 600)
        layout = QVBoxLayout(self)
        self.baselineLabel = QLabel()
        self.baselineLabel.setWordWrap(True)
        layout.addWidget(self.baselineLabel)
        modes = QHBoxLayout()
        self.modeLabel, self.mode = QLabel(), QComboBox()
        self.mode.addItem("", "manual")
        self.mode.addItem("", "smart")
        modes.addWidget(self.modeLabel)
        modes.addWidget(self.mode)
        modes.addStretch()
        layout.addLayout(modes)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.variablesTable, self.variableChooser, self.addVariableButton, self.removeVariableButton = (
            self._input_table(5)
        )
        self.targetsTable, self.targetChooser, self.addTargetButton, self.removeTargetButton = self._input_table(5)
        self.constraintsTable, self.constraintChooser, self.addConstraintButton, self.removeConstraintButton = (
            self._input_table(4)
        )
        for option in self.options:
            self.variableChooser.addItem(option.label(), option.path.value)
        for chooser in (self.targetChooser, self.constraintChooser):
            for key in self.metric_keys:
                chooser.addItem(metric_label(key), key)
        self.addVariableButton.clicked.connect(lambda: self.add_variable(self.variableChooser.currentData()))
        self.addTargetButton.clicked.connect(lambda: self.add_target(self.targetChooser.currentData()))
        self.addConstraintButton.clicked.connect(lambda: self.add_constraint(self.constraintChooser.currentData()))
        self.removeVariableButton.clicked.connect(lambda: self._remove(self.variablesTable, self.variable_rows))
        self.removeTargetButton.clicked.connect(lambda: self._remove(self.targetsTable, self.target_rows))
        self.removeConstraintButton.clicked.connect(lambda: self._remove(self.constraintsTable, self.constraint_rows))
        constraints_layout = self.tabs.widget(2).layout()
        self.errorPolicyLabel = QLabel()
        self.errorPolicyLabel.setWordWrap(True)
        self.rejectWarnings = QCheckBox()
        constraints_layout.addWidget(self.errorPolicyLabel)
        constraints_layout.addWidget(self.rejectWarnings)
        self._search_settings()
        entries = tuple(e if isinstance(e, LibraryEntry) else LibraryEntry.from_dict(e) for e in library_entries)
        self.smart = SmartDesignForm(self.controller.baseline, preferences, entries, self)
        self.smartScroll = QScrollArea()
        self.smartScroll.setWidgetResizable(True)
        self.smartScroll.setWidget(self.smart)
        self.smartScroll.hide()
        layout.addWidget(self.smartScroll, 2)
        self._progress_controls(layout)
        self._results_controls(layout)
        self.details = CandidateDetails(self)
        self.comparison = CandidateComparison(self.preferences, self)
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.smart.top_n.valueChanged.connect(self._top_n_changed)
        self.controller.candidateReady.connect(self._candidate)
        self.controller.progressChanged.connect(self._update_progress)
        self.controller.finished.connect(self._finished)
        self.add_target("burn_time")
        self.retranslate()
        self.elapsedTimer = QTimer(self)
        self.elapsedTimer.setInterval(250)
        self.elapsedTimer.timeout.connect(self._elapsed)
        self.elapsedTimer.start()

    def load_requirements(self, requirements, *, budget, seed):
        """Explicit Quick -> Advanced handoff into an independent manual window."""
        if self.controller.is_running:
            raise RuntimeError("A search is already running.")
        self.registry.validate_requirements(requirements)
        for table, rows in ((self.variablesTable, self.variable_rows), (self.targetsTable, self.target_rows),
                            (self.constraintsTable, self.constraint_rows)):
            table.setRowCount(0)
            rows.clear()
        self.mode.setCurrentIndex(self.mode.findData("manual"))
        for variable in requirements.variables:
            self.add_variable(variable.path.value)
            row = self.variable_rows[-1]
            row.minimum.setValue(convert(variable.range.minimum, row.option.unit, row.option.display_unit))
            row.maximum.setValue(convert(variable.range.maximum, row.option.unit, row.option.display_unit))
            row.points.setValue(variable.range.points)
        for target in requirements.targets:
            self.add_target(target.metric)
            row = self.target_rows[-1]
            unit, display = metric_unit(target.metric, self.preferences)
            row.value.setValue(convert(target.value, unit, display))
            row.scale.setValue(convert(target.scale, unit, display))
            row.weight.setValue(target.weight)
        # Merge repeated bounds into the one row per metric used by Manual.
        for constraint in requirements.constraints:
            existing = any(row.metric == constraint.metric for row in self.constraint_rows)
            self.add_constraint(constraint.metric)
            row = next(r for r in self.constraint_rows if r.metric == constraint.metric)
            if not existing:
                # OptionalBound(True) is the interactive Manual default, not an
                # imported constraint. Begin with no bounds, then merge only the
                # values actually present in the transferred problem.
                row.minimum.enabled.setChecked(False)
                row.maximum.enabled.setChecked(False)
            unit, display = metric_unit(constraint.metric, self.preferences)
            for bound, value, choose in ((row.minimum, constraint.minimum, max),
                                        (row.maximum, constraint.maximum, min)):
                if value is not None:
                    number = convert(value, unit, display)
                    bound.value.setValue(choose(bound.value.value(), number) if bound.enabled.isChecked() else number)
                    bound.enabled.setChecked(True)
        self.rejectWarnings.setChecked(requirements.reject_warnings)
        self.strategy.setCurrentIndex(self.strategy.findData("random"))
        self.budget.setValue(budget)
        self.seed.setValue(seed)
        self.retranslate()

    def _input_table(self, columns):
        page = QWidget()
        layout = QVBoxLayout(page)
        table = QTableWidget(0, columns)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, columns):
            table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(table)
        controls = QHBoxLayout()
        chooser, add, remove = QComboBox(), QPushButton(), QPushButton()
        chooser.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        chooser.setMinimumContentsLength(35)
        controls.addWidget(chooser, 1)
        controls.addWidget(add)
        controls.addWidget(remove)
        layout.addLayout(controls)
        self.tabs.addTab(page, "")
        return table, chooser, add, remove

    def _search_settings(self):
        page = QWidget()
        layout = QFormLayout(page)
        self.strategy = QComboBox()
        self.strategy.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.strategy.addItem("", "grid")
        self.strategy.addItem("", "random")
        self.budget = QSpinBox()
        self.budget.setRange(1, 10000)
        self.budget.setValue(100)
        self.seed = QSpinBox()
        self.seed.setRange(0, 2147483647)
        self.seed.setValue(1729)
        self.searchLabels = [QLabel(), QLabel(), QLabel()]
        for label, control in zip(self.searchLabels, (self.strategy, self.budget, self.seed)):
            layout.addRow(label, control)
        self.gridLabel = QLabel()
        self.gridLabel.setWordWrap(True)
        layout.addRow(self.gridLabel)
        self.strategy.currentIndexChanged.connect(self._update_grid)
        self.budget.valueChanged.connect(self._update_grid)
        self.tabs.addTab(page, "")

    def _progress_controls(self, layout):
        self.progressGroup = QGroupBox()
        controls = QVBoxLayout(self.progressGroup)
        row = QHBoxLayout()
        self.statusLabel, self.countsLabel = QLabel(), QLabel()
        self.countsLabel.setWordWrap(True)
        self.startButton, self.stopButton = QPushButton(), QPushButton()
        self.stopButton.setEnabled(False)
        self.startButton.clicked.connect(self.start_search)
        self.stopButton.clicked.connect(self.stop_search)
        row.addWidget(self.statusLabel)
        row.addWidget(self.countsLabel, 1)
        row.addWidget(self.startButton)
        row.addWidget(self.stopButton)
        controls.addLayout(row)
        self.progressBar = QProgressBar()
        self.currentProgress = QProgressBar()
        controls.addWidget(self.progressBar)
        controls.addWidget(self.currentProgress)
        self.progressDetails = QLabel()
        self.progressDetails.setWordWrap(True)
        controls.addWidget(self.progressDetails)
        layout.addWidget(self.progressGroup)

    def _results_controls(self, layout):
        self.resultsGroup = QGroupBox()
        controls = QVBoxLayout(self.resultsGroup)
        filters = QHBoxLayout()
        self.statusFilter = QComboBox()
        self.statusFilter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        for key in ("all", "feasible", "rejected", "error", "cancelled"):
            self.statusFilter.addItem("", key)
        self.textFilter = QLineEdit()
        self.detailsButton, self.openButton, self.compareButton = QPushButton(), QPushButton(), QPushButton()
        self.detailsButton.clicked.connect(self.show_details)
        self.openButton.clicked.connect(self.open_selected)
        self.compareButton.clicked.connect(self.compare_selected)
        filters.addWidget(self.statusFilter)
        filters.addWidget(self.textFilter, 1)
        filters.addWidget(self.detailsButton)
        filters.addWidget(self.compareButton)
        filters.addWidget(self.openButton)
        controls.addLayout(filters)
        self.manualModel = ResultsModel(self.options, self.preferences, self)
        self.smartModel = SmartResultsModel(self.preferences, self)
        self.model = self.manualModel
        self.proxy = ResultsFilter(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setWordWrap(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.selectionModel().selectionChanged.connect(self._selection_changed)
        self.table.doubleClicked.connect(self.show_details)
        self.statusFilter.currentIndexChanged.connect(self._filter)
        self.textFilter.textChanged.connect(self._filter)
        controls.addWidget(self.table)
        self.smartResultHint = QLabel()
        self.smartResultHint.setWordWrap(True)
        controls.addWidget(self.smartResultHint)
        layout.addWidget(self.resultsGroup, 2)
        self._selection_changed()

    @staticmethod
    def _item(table, row, column, text):
        item = table.item(row, column)
        if item is None:
            item = QTableWidgetItem()
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            table.setItem(row, column, item)
        item.setText(text)
        item.setToolTip(text)

    def add_variable(self, path):
        if not path or any(row.option.path.value == path for row in self.variable_rows):
            return
        option = next(o for o in self.options if o.path.value == path)
        minimum = convert(option.minimum, option.unit, option.display_unit)
        maximum = convert(option.maximum, option.unit, option.display_unit)
        value = convert(option.value, option.unit, option.display_unit)
        row = VariableRow(
            option,
            number_editor(value, minimum, maximum, option.integer),
            number_editor(value, minimum, maximum, option.integer),
            number_editor(1, 1, 10000, True),
        )
        index = self.variablesTable.rowCount()
        self.variablesTable.insertRow(index)
        for column, widget in enumerate((row.minimum, row.maximum, row.points), 1):
            self.variablesTable.setCellWidget(index, column, widget)
            widget.valueChanged.connect(self._update_grid)
        self.variable_rows.append(row)
        self._refresh_rows()
        self._update_grid()

    def add_target(self, metric):
        if not metric or any(row.metric == metric for row in self.target_rows):
            return
        row = TargetRow(metric, number_editor(), number_editor(1, 0, 1e8), number_editor(1, 0, 1e100))
        index = self.targetsTable.rowCount()
        self.targetsTable.insertRow(index)
        for column, widget in enumerate((row.value, row.weight, row.scale), 1):
            self.targetsTable.setCellWidget(index, column, widget)
        self.target_rows.append(row)
        self._refresh_rows()

    def add_constraint(self, metric):
        if not metric or any(row.metric == metric for row in self.constraint_rows):
            return
        row = ConstraintRow(metric, OptionalBound(), OptionalBound(True))
        index = self.constraintsTable.rowCount()
        self.constraintsTable.insertRow(index)
        self.constraintsTable.setCellWidget(index, 1, row.minimum)
        self.constraintsTable.setCellWidget(index, 2, row.maximum)
        self.constraint_rows.append(row)
        self._refresh_rows()

    def _remove(self, table, rows):
        index = table.currentRow()
        if index >= 0:
            rows.pop(index)
            table.removeRow(index)
            self._refresh_rows()
            self._update_grid()

    def _refresh_rows(self):
        for index, row in enumerate(self.variable_rows):
            self._item(self.variablesTable, index, 0, row.option.label())
            self._item(self.variablesTable, index, 4, row.option.display_unit)
        for table, rows, column in (
            (self.targetsTable, self.target_rows, 4),
            (self.constraintsTable, self.constraint_rows, 3),
        ):
            for index, row in enumerate(rows):
                self._item(table, index, 0, metric_label(row.metric))
                self._item(table, index, column, metric_unit(row.metric, self.preferences)[1])

    def build_requirements(self):
        variables, targets, constraints = [], [], []
        for row in self.variable_rows:
            option = row.option
            minimum = convert(row.minimum.value(), option.display_unit, option.unit)
            maximum = convert(row.maximum.value(), option.display_unit, option.unit)
            variables.append(
                DesignVariable(option.path, ParameterRange(minimum, maximum, row.points.value(), option.integer))
            )
        for row in self.target_rows:
            unit, display_unit = metric_unit(row.metric, self.preferences)
            targets.append(
                Target(
                    row.metric,
                    convert(row.value.value(), display_unit, unit),
                    convert(row.scale.value(), display_unit, unit),
                    row.weight.value(),
                )
            )
        for row in self.constraint_rows:
            unit, display_unit = metric_unit(row.metric, self.preferences)
            bounds = [
                convert(bound.value.value(), display_unit, unit) if bound.enabled.isChecked() else None
                for bound in (row.minimum, row.maximum)
            ]
            constraints.append(MetricConstraint(row.metric, *bounds))
        return DesignRequirements(tuple(variables), tuple(targets), tuple(constraints), self.rejectWarnings.isChecked())

    def start_search(self):
        try:
            smart = self.mode.currentData() == "smart"
            if smart:
                plan = self.smart.build_plan()
                self.controller.start_smart(plan)
                self.model = self.smartModel
                self.smartModel.reset(self.controller.smart_store)
                self.proxy.setSourceModel(self.model)
                self.proxy.set_top_n(plan.requirements.top_n)
                self.statusFilter.setCurrentIndex(self.statusFilter.findData("feasible"))
                self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
                self._search_started_ui()
                return
            baseline = self.controller.baseline.to_dict()
            if not baseline["grains"] or baseline["propellant"] is None:
                raise ValueError("The current motor must contain grains and a propellant.")
            requirements = self.build_requirements()
            self.controller.registry = self.registry
            self.controller.start(
                requirements, strategy=self.strategy.currentData(), budget=self.budget.value(), seed=self.seed.value()
            )
        except (ValueError, TypeError, RuntimeError) as error:
            QMessageBox.warning(self, translate("Cannot Start Search"), translate(str(error)))
            return
        self.details.hide()
        self.comparison.hide()
        self.model = self.manualModel
        self.model.reset(requirements.variables)
        self.proxy.setSourceModel(self.model)
        self.proxy.set_top_n(None)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._search_started_ui()

    def _search_started_ui(self):
        self.details.hide()
        self.comparison.hide()
        self._search_started = time.monotonic()
        self._state = "running"
        self._set_running(True)
        self._update_progress(SearchProgress())

    def stop_search(self):
        self.controller.stop()
        self._state = "stopping"
        self.stopButton.setEnabled(False)
        self._update_progress(self._progress)

    def _set_running(self, running):
        self.tabs.setEnabled(not running)
        self.mode.setEnabled(not running)
        self.smartScroll.setEnabled(not running)
        self.startButton.setEnabled(not running)
        self.stopButton.setEnabled(running)
        self._selection_changed()

    def _candidate(self, proposal, evaluation):
        self.model.append(proposal, evaluation)

    def _update_progress(self, progress):
        self._progress = progress
        self.statusLabel.setText(display_text(STATUS_LABELS[self._state]))
        self.countsLabel.setText(
            translate(
                "Processed: {processed}/{total}   Feasible: {feasible}   Rejected: {rejected}   Errors: {errors}"
            ).format(
                processed=progress.processed,
                total=progress.total,
                feasible=progress.feasible,
                rejected=progress.rejected,
                errors=progress.errors,
            )
        )
        self.progressBar.setRange(0, max(1, progress.total))
        self.progressBar.setValue(progress.processed)
        self.progressBar.setFormat(translate("Search: %v/%m"))
        self.currentProgress.setValue(round(100 * progress.current))
        self.currentProgress.setFormat(translate("Current candidate: %p%"))
        if self._state not in ("running", "stopping"):
            self.currentProgress.setFormat(translate("No candidate running"))
        smart = getattr(self.model, "is_smart", False)
        self.progressDetails.setVisible(smart)
        if smart:
            sources = {
                "manual": "Ready",
                "exploration": "Exploration",
                "selection": "Selection",
                "refinement": "Refinement",
                "verification": "Finalist Recheck",
                "ranking": "Final Ranking",
            }
            elapsed = (
                time.monotonic() - self._search_started
                if self._state in ("running", "stopping") and self._search_started is not None
                else progress.elapsed
            )
            self.progressDetails.setText(
                translate("Stage: {stage}   Best score: {score}   Elapsed: {seconds} s").format(
                    stage=translate(sources[progress.stage]),
                    score="—" if progress.best_score is None else "{:.6g}".format(progress.best_score),
                    seconds="{:.1f}".format(elapsed),
                )
            )
        self.smartResultHint.setVisible(smart)
        if smart and self.controller.smart_store is not None:
            count = len(self.controller.smart_store.ranked())
            self.smartResultHint.setText(
                translate(
                    "Top {shown} of {count} admissible designs. Lower scores mean closer target agreement."
                ).format(shown=min(self.smart.top_n.value(), count), count=count)
                if count
                else translate("No admissible candidates yet. Review targets, limits or allowed options.")
            )

    def _elapsed(self):
        if self._state in ("running", "stopping"):
            self._update_progress(self._progress)

    def _finished(self, summary):
        self._state = summary.state
        self.model.retranslate()
        self._set_running(False)
        self._update_progress(summary.progress)
        if summary.error:
            QMessageBox.warning(self, translate("Search Failed"), translate(summary.error))
        if self._close_requested:
            self.close()

    def _update_grid(self):
        if not hasattr(self, "gridLabel"):
            return
        grid = math.prod(row.points.value() for row in self.variable_rows)
        self.gridLabel.setText(
            translate("Grid contains {count} candidates; this run is limited to {budget}.").format(
                count=grid, budget=min(grid, self.budget.value())
            )
        )
        self.seed.setEnabled(self.strategy.currentData() == "random")

    def _filter(self):
        self.proxy.set_filters(self.statusFilter.currentData(), self.textFilter.text())
        self._selection_changed()

    def _mode_changed(self):
        smart = self.mode.currentData() == "smart"
        self.tabs.setVisible(not smart)
        self.smartScroll.setVisible(smart)
        self.retranslate()

    def _top_n_changed(self):
        if getattr(self.model, "is_smart", False):
            self.proxy.set_top_n(self.smart.top_n.value())
            self._update_progress(self._progress)

    def selected_ids(self):
        return tuple(self.proxy.data(row, ID_ROLE) for row in self.table.selectionModel().selectedRows())

    def compare_selected(self):
        if self.controller.smart_store is None:
            return
        try:
            self.comparison.show_candidates(self.controller.smart_store.compare(self.selected_ids()))
        except ValueError as error:
            QMessageBox.warning(self, translate("Cannot Compare Candidates"), translate(str(error)))

    def selected_id(self):
        rows = self.table.selectionModel().selectedRows()
        return self.proxy.data(rows[0], ID_ROLE) if rows else None

    def _selection_changed(self):
        candidate_id = self.selected_id()
        self.detailsButton.setEnabled(candidate_id is not None)
        evaluation = self.controller.evaluations.get(candidate_id)
        self.openButton.setEnabled(
            not self.controller.is_running and evaluation is not None and evaluation.outcome.valid
        )
        self.compareButton.setVisible(getattr(self.model, "is_smart", False))
        ids = self.selected_ids()
        ranked = self.smartModel.ranks if getattr(self.model, "is_smart", False) else {}
        self.compareButton.setEnabled(
            not self.controller.is_running and 2 <= len(ids) <= 5 and all(key in ranked for key in ids)
        )

    def show_details(self, *_):
        candidate_id = self.selected_id()
        if candidate_id is not None:
            self.details.show_candidate(candidate_id)

    def open_selected(self):
        candidate_id = self.selected_id()
        if candidate_id is None or self.controller.is_running or self.open_candidate is None:
            return
        try:
            request = self.controller.request_for(candidate_id)
            if not request.valid:
                raise ValueError("This candidate has no valid simulation and cannot be opened.")
            self.open_candidate(request.snapshot.to_dict())
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, translate("Cannot Open Candidate"), translate(str(error)))

    def retranslate(self):
        self.setWindowTitle(translate("Design Assistant"))
        smart = self.mode.currentData() == "smart"
        self.modeLabel.setText(translate("Mode"))
        self.mode.setItemText(0, translate("Manual"))
        self.mode.setItemText(1, translate("Smart Design"))
        self.smart.retranslate()
        self.baselineLabel.setText(
            translate(
                "Baseline: {name}. Grain count and simulation settings remain fixed; "
                "options use existing library entries."
                if smart
                else "Baseline: {name}. Grain types, grain count, propellant and simulation settings remain fixed."
            ).format(name=self.source_name or translate("Unsaved motor"))
        )
        for index, source in enumerate(("Variables", "Targets", "Constraints", "Search Settings")):
            self.tabs.setTabText(index, translate(source))
        for chooser in (self.targetChooser, self.constraintChooser):
            for index in range(chooser.count()):
                chooser.setItemText(index, metric_label(chooser.itemData(index)))
        for index, option in enumerate(self.options):
            self.variableChooser.setItemText(index, option.label())
        for table, sources in (
            (self.variablesTable, ("Parameter", "Minimum", "Maximum", "Values", "Unit")),
            (self.targetsTable, ("Metric", "Target Value", "Weight", "Normalization / Tolerance", "Unit")),
            (self.constraintsTable, ("Metric", "Minimum", "Maximum", "Unit")),
        ):
            table.setHorizontalHeaderLabels([translate(source) for source in sources])
        for button, source in (
            (self.addVariableButton, "Add Variable"),
            (self.addTargetButton, "Add Target"),
            (self.addConstraintButton, "Add Constraint"),
            (self.removeVariableButton, "Remove Selected"),
            (self.removeTargetButton, "Remove Selected"),
            (self.removeConstraintButton, "Remove Selected"),
            (self.startButton, "Run Smart Design" if smart else "Start"),
            (self.stopButton, "Stop"),
            (self.detailsButton, "Details"),
            (self.openButton, "Open in Motor Editor"),
            (self.compareButton, "Compare"),
        ):
            button.setText(translate(source))
            button.setMinimumWidth(button.sizeHint().width())
        self.errorPolicyLabel.setText(
            translate("ERROR always rejects a candidate. WARNING is retained in diagnostics.")
        )
        self.rejectWarnings.setText(translate("Reject candidates with WARNING alerts"))
        self.rejectWarnings.setToolTip(translate("Warnings are accepted unless this constraint is enabled."))
        self.strategy.setItemText(0, translate("Grid Search"))
        self.strategy.setItemText(1, translate("Random Search"))
        for label, source in zip(self.searchLabels, ("Strategy", "Candidate Budget", "Random Seed")):
            label.setText(translate(source))
        self.budget.setToolTip(translate("Maximum candidates for either strategy (1–10000)."))
        self.seed.setToolTip(translate("The same baseline, requirements and seed reproduce a random search."))
        self.progressGroup.setTitle(translate("Progress"))
        self.resultsGroup.setTitle(translate("Results"))
        self.statusFilter.setItemText(0, translate("All Candidates"))
        for index in range(1, self.statusFilter.count()):
            self.statusFilter.setItemText(index, display_text(STATUS_LABELS[self.statusFilter.itemData(index)]))
        self.textFilter.setPlaceholderText(translate("Filter results…"))
        self._refresh_rows()
        self._update_grid()
        self._update_progress(self._progress)
        self.model.retranslate()
        self._selection_changed()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "model"):
            self.retranslate()
        super().changeEvent(event)

    def closeEvent(self, event):
        if self.controller.is_running:
            self._close_requested = True
            self.stop_search()
            event.ignore()
            return
        self.closed.emit()
        event.accept()
