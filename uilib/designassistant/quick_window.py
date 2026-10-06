"""Three-step Quick wizard using the existing controller/results/comparison UI."""

import json
import time
from dataclasses import dataclass, replace

from PyQt6.QtCore import QCoreApplication, QEvent, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from designassistant import LibraryEntry, MetricConstraint, MetricRegistry
from designassistant.quick import (
    FIELD_METRICS,
    QUICK_METRICS,
    QuickCriterion,
    QuickDesignError,
    QuickDesignRequirements,
    QuickDesignRequirementsValidator,
    match_percentage,
    recommended_designs,
)
from designassistant.smart import CURRENT_GEOMETRY, QUALITY_BUDGETS, SearchSpaceBuilder
from motorlib.units import convert
from uilib.localization import geometry_name

from .controller import DesignController, SearchProgress
from .editors import OptionalBound, number_editor
from .presentation import METRIC_LABELS, diagnostic_text, display_number, metric_label, metric_unit, translate
from .smart_results import CandidateComparison, SmartResultsModel, explanation_text, geometry_label
from .window import CandidateDetails


def quick_translate(source):
    return QCoreApplication.translate("QuickDesign", source)


def render(record):
    data = json.loads(record.arguments_json)
    kwargs = dict(data.get("kwargs", {}))
    if "requirement" in kwargs:
        kwargs["requirement"] = metric_label(FIELD_METRICS[kwargs["requirement"]])
    if "geometry" in kwargs:
        kwargs["geometry"] = (
            geometry_name(kwargs["geometry"])
            if kwargs["geometry"] != "current"
            else quick_translate("Current geometry")
        )
    if "reason" in kwargs:
        kwargs["reason"] = quick_translate(kwargs["reason"])
        if kwargs["reason"] == data["kwargs"]["reason"]:
            kwargs["reason"] = translate(kwargs["reason"])
    return QCoreApplication.translate(record.context, record.source).format(*data.get("args", []), **kwargs)


@dataclass
class KnownRow:
    source: str
    enabled: object
    mode: object
    value: object
    unit: str
    display_unit: str
    label: object = None


class LibraryChooser(QDialog):
    """Translate an open chooser without losing selection or stable item data."""

    def __init__(self, window):
        super().__init__(window)
        layout = QVBoxLayout(self)
        self.compatible = QCheckBox()
        self.compatible.setChecked(window.allowed_keys is None)
        self.items = QListWidget()
        for entry in window.library_entries:
            item = QListWidgetItem(entry.name)
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if window.allowed_keys is None or entry.key in window.allowed_keys
                else Qt.CheckState.Unchecked
            )
            self.items.addItem(item)
        self.items.setEnabled(not self.compatible.isChecked())
        self.compatible.toggled.connect(lambda checked: self.items.setEnabled(not checked))
        layout.addWidget(self.compatible)
        layout.addWidget(self.items)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.retranslate()

    def selected_keys(self):
        return tuple(
            self.items.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.items.count())
            if self.items.item(i).checkState() == Qt.CheckState.Checked
        )

    def retranslate(self):
        self.setWindowTitle(quick_translate("Allowed library entries"))
        self.compatible.setText(quick_translate("Use compatible library entries"))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "items"):
            self.retranslate()
        super().changeEvent(event)


class RecommendationCard(QGroupBox):
    def __init__(self, window, index, record):
        super().__init__(window)
        self.window, self.index, self.record = window, index, record
        layout = QVBoxLayout(self)
        self.selected = QCheckBox()
        self.selected.toggled.connect(window._selection_changed)
        self.summary, self.limits, self.warnings, self.why = QLabel(), QLabel(), QLabel(), QLabel()
        for label in (self.summary, self.limits, self.warnings, self.why):
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
        self.why.hide()
        layout.addWidget(self.selected)
        for label in (self.summary, self.limits, self.warnings, self.why):
            layout.addWidget(label)
        buttons = QHBoxLayout()
        self.why_button, self.details_button, self.open_button = QPushButton(), QPushButton(), QPushButton()
        self.why_button.clicked.connect(lambda: self.why.setVisible(not self.why.isVisible()))
        candidate_id = record.proposal.candidate_id
        self.details_button.clicked.connect(lambda: window.show_details(candidate_id))
        self.open_button.clicked.connect(lambda: window.open_candidate_id(candidate_id))
        for button in (self.why_button, self.details_button, self.open_button):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        self.retranslate()

    def retranslate(self):
        record, preferences = self.record, self.window.preferences
        self.setTitle(quick_translate("Recommended Design {number}").format(number=self.index))
        self.selected.setText(quick_translate("Select for comparison"))
        lines = [
            quick_translate("Match: {percent}%").format(
                percent="{:.1f}".format(match_percentage(record.evaluation.score))
            )
        ]
        self.summary.setToolTip(
            quick_translate("Match is 100 / (1 + normalized score), not a probability or guarantee.")
        )
        for key in (
            "burn_time",
            "average_thrust",
            "peak_thrust",
            "total_impulse",
            "propellant_length",
            "maximum_diameter",
        ):
            unit, display = metric_unit(key, preferences)
            obtained = key in ("average_thrust", "total_impulse") and not any(
                target.metric == key for target in record.analysis.targets
            )
            lines.append(
                f"{metric_label(key)}: {display_number(record.evaluation.outcome.metric(key), unit, display)} {display}"
                + (" — " + quick_translate("Obtained result") if obtained else "")
            )
        lines.extend(
            (
                quick_translate("Library entry: {name}").format(name=record.variant.library_name),
                quick_translate("Geometry: {geometry}").format(geometry=geometry_label(record.variant)),
                quick_translate("Grains: {count}").format(count=len(record.variant.geometries)),
            )
        )
        self.summary.setText("\n".join(lines))
        bounds = []
        for constraint in record.analysis.constraints:
            unit, display = metric_unit(constraint.metric, preferences)
            for mode, value in (("Minimum", constraint.minimum), ("Maximum", constraint.maximum)):
                if value is not None:
                    bounds.append(
                        f"{metric_label(constraint.metric)} — {quick_translate(mode)}: "
                        f"{display_number(value, unit, display)} {display}"
                    )
        self.limits.setText(
            quick_translate("Meets configured constraints") + ("\n" + "\n".join(bounds) if bounds else "")
        )
        warnings = [d for d in record.evaluation.outcome.diagnostics if d.level == "WARNING"]
        self.warnings.setText(
            quick_translate("Warnings: {count}").format(count=len(warnings))
            + ("\n" + "\n".join(diagnostic_text(d) for d in warnings) if warnings else "")
        )
        self.why.setText("\n".join(explanation_text(r) for r in record.analysis.explanations))
        self.why_button.setText(quick_translate("Why this design?"))
        self.details_button.setText(quick_translate("Technical details"))
        self.open_button.setText(quick_translate("Open in Motor Editor"))


class QuickDesignWindow(QDialog):
    closed = pyqtSignal()

    def __init__(
        self,
        baseline,
        preferences,
        parent=None,
        *,
        library_entries=(),
        open_candidate=None,
        open_advanced=None,
        source_name="",
    ):
        super().__init__(parent, Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.preferences, self.source_name = preferences, source_name
        self.library_entries = tuple(
            {
                e.key: e
                for e in (e if isinstance(e, LibraryEntry) else LibraryEntry.from_dict(e) for e in library_entries)
            }.values()
        )
        self.open_candidate, self.open_advanced_callback = open_candidate, open_advanced
        self.controller = DesignController(baseline, self)
        self.allowed_keys = None
        self.problem, self.recommendations = None, ()
        self.cards, self.rows, self.constraints = {}, {}, {}
        self._state, self._progress = "ready", SearchProgress()
        self._close_requested = False
        self._started = None
        self.resize(850, 780)
        self.setMinimumSize(650, 550)
        layout = QVBoxLayout(self)
        self.step_label, self.notice = QLabel(), QLabel()
        self.notice.setWordWrap(True)
        self.notice.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.step_label)
        layout.addWidget(self.notice)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self._requirements_page()
        self._options_page()
        self._results_page()
        controls = QHBoxLayout()
        self.back_button, self.next_button, self.find_button, self.advanced_button, self.close_button = (
            QPushButton() for _ in range(5)
        )
        self.find_button.setMinimumHeight(40)
        self.back_button.clicked.connect(self.back)
        self.next_button.clicked.connect(self.next)
        self.find_button.clicked.connect(self.start_search)
        self.advanced_button.clicked.connect(self.open_advanced)
        self.close_button.clicked.connect(self.close)
        for button in (self.back_button, self.next_button, self.find_button, self.advanced_button, self.close_button):
            controls.addWidget(button)
        layout.addLayout(controls)
        self.model = SmartResultsModel(preferences, self)
        self.model.metrics = QUICK_METRICS
        self.details = CandidateDetails(self)
        self.comparison = CandidateComparison(preferences, self, registry=MetricRegistry(QUICK_METRICS))
        self.controller.progressChanged.connect(self._update_progress)
        self.controller.finished.connect(self._finished)
        self.elapsed_timer = QTimer(self)
        self.elapsed_timer.setInterval(250)
        self.elapsed_timer.timeout.connect(self._elapsed)
        self.elapsed_timer.start()
        self.retranslate()

    def _page(self):
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.pages.addWidget(scroll)
        return QVBoxLayout(page)

    def _requirements_page(self):
        layout = self._page()
        self.requirements_help, self.dimension_notice = QLabel(), QLabel()
        for label in (self.requirements_help, self.dimension_notice):
            label.setWordWrap(True)
            layout.addWidget(label)
        self.known_group = QGroupBox()
        form = QFormLayout(self.known_group)
        layout.addWidget(self.known_group)
        self.requirements_layout = layout
        self.optional_group = QGroupBox()
        optional_form = QFormLayout(self.optional_group)
        layout.addWidget(self.optional_group)
        for field, source in (
            ("diameter", "Maximum diameter"),
            ("length", "Maximum motor length"),
            ("burn_time", "Desired burn time"),
            ("average_thrust", "Desired average thrust"),
            ("total_impulse", "Desired total impulse"),
        ):
            required = field in ("diameter", "length", "burn_time")
            unit, display = metric_unit(FIELD_METRICS[field], self.preferences)
            row = KnownRow(source, QCheckBox(), QComboBox(), number_editor(0, 0), unit, display, QLabel())
            row.enabled.setParent(self.known_group if required else self.optional_group)
            row.mode.setParent(self.known_group if required else self.optional_group)
            for mode in ("target", "maximum", "minimum"):
                row.mode.addItem("", mode)
            row.mode.setCurrentIndex(row.mode.findData("maximum" if field in ("diameter", "length") else "target"))
            row.mode.hide()
            row.enabled.setChecked(required)
            row.enabled.setVisible(not required)
            row.value.setEnabled(required)
            row.enabled.toggled.connect(row.value.setEnabled)
            controls = QHBoxLayout()
            if not required:
                controls.addWidget(row.enabled)
            controls.addWidget(row.value)
            (form if required else optional_form).addRow(row.label, controls)
            self.rows[field] = row
        self.other_group = QGroupBox()
        self.other_group.setCheckable(True)
        self.other_group.setChecked(False)
        self.other_contents = QWidget()
        other_layout = QVBoxLayout(self.other_group)
        other_layout.addWidget(self.other_contents)
        optional = QFormLayout(self.other_contents)
        self.other_contents.hide()
        self.other_group.toggled.connect(self.other_contents.setVisible)
        for key in METRIC_LABELS:
            minimum, maximum, label = OptionalBound(), OptionalBound(), QLabel()
            contents = QHBoxLayout()
            contents.addWidget(minimum)
            contents.addWidget(maximum)
            optional.addRow(label, contents)
            self.constraints[key] = (minimum, maximum, label)
        self.reject_warnings = QCheckBox()
        optional.addRow(self.reject_warnings)
        layout.addWidget(self.other_group)
        layout.addStretch()

    def _options_page(self):
        layout = self._page()
        self.options_group = QGroupBox()
        form = QFormLayout(self.options_group)
        self.requirements_layout.insertWidget(4, self.options_group)
        self.library_label, self.library_status = QLabel(), QLabel()
        self.library_status.setWordWrap(True)
        self.choose_button = QPushButton()
        self.choose_button.clicked.connect(self.choose_library)
        library = QHBoxLayout()
        library.addWidget(self.library_status, 1)
        library.addWidget(self.choose_button)
        form.addRow(self.library_label, library)
        self.priority_label, self.quality_label = QLabel(), QLabel()
        self.priority, self.quality = QComboBox(), QComboBox()
        for key in ("balanced", "burn_time", "average_thrust", "total_impulse"):
            self.priority.addItem("", key)
        for key in QUALITY_BUDGETS:
            self.quality.addItem("", key)
        self.quality.setCurrentIndex(self.quality.findData("balanced"))
        self.quality.currentIndexChanged.connect(self._estimate)
        form.addRow(self.priority_label, self.priority)
        form.addRow(self.quality_label, self.quality)
        self.estimate_label, self.review_label = QLabel(), QLabel()
        self.review = QPlainTextEdit()
        self.review.setReadOnly(True)
        self.estimate_label.setWordWrap(True)
        form.addRow(self.estimate_label)
        layout.addWidget(self.review_label)
        layout.addWidget(self.review, 1)

    def _results_page(self):
        layout = self._page()
        self.status_label, self.counts_label = QLabel(), QLabel()
        self.counts_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addWidget(self.counts_label)
        self.progress_bar = QProgressBar()
        layout.addWidget(self.progress_bar)
        row = QHBoxLayout()
        self.stop_button, self.compare_button = QPushButton(), QPushButton()
        self.stop_button.clicked.connect(self.stop_search)
        self.compare_button.clicked.connect(self.compare_selected)
        row.addWidget(self.stop_button)
        row.addWidget(self.compare_button)
        row.addStretch()
        layout.addLayout(row)
        self.results_label, self.results_hint = QLabel(), QLabel()
        self.results_hint.setWordWrap(True)
        layout.addWidget(self.results_label)
        layout.addWidget(self.results_hint)
        self.cards_layout = QVBoxLayout()
        layout.addLayout(self.cards_layout)
        layout.addStretch()

    def build_requirements(self, *, budget=None):
        criteria = tuple(
            QuickCriterion(key, row.mode.currentData(), convert(row.value.value(), row.display_unit, row.unit))
            for key, row in self.rows.items()
            if row.enabled.isChecked()
        )
        constraints = []
        if self.other_group.isChecked():
            for metric, (minimum, maximum, _) in self.constraints.items():
                unit, display = metric_unit(metric, self.preferences)
                bounds = [
                    convert(b.value.value(), display, unit) if b.enabled.isChecked() else None
                    for b in (minimum, maximum)
                ]
                if any(v is not None for v in bounds):
                    constraints.append(MetricConstraint(metric, *bounds))
        return QuickDesignRequirements(
            criteria,
            tuple(constraints),
            self.allowed_keys,
            self.priority.currentData(),
            self.quality.currentData(),
            reject_warnings=self.other_group.isChecked() and self.reject_warnings.isChecked(),
            budget=budget,
        )

    def _validated(self, budget=None):
        try:
            validation = QuickDesignRequirementsValidator().validate(
                self.controller.baseline, self.build_requirements(budget=budget), self.library_entries
            )
            if not validation.valid:
                QMessageBox.warning(
                    self, quick_translate("Cannot find designs"), "\n".join(render(d) for d in validation.diagnostics)
                )
                return None
            return validation.problem
        except (ValueError, TypeError) as error:
            text = render(error.message) if isinstance(error, QuickDesignError) else translate(str(error))
            QMessageBox.warning(self, quick_translate("Cannot find designs"), text)
            return None

    def next(self):
        problem = self._validated()
        if problem is not None:
            self.problem = problem
            self.pages.setCurrentIndex(1)
            self._review()
            self.retranslate()

    def back(self):
        if not self.controller.is_running:
            self.pages.setCurrentIndex(max(0, self.pages.currentIndex() - 1))
            self.retranslate()

    def choose_library(self):
        dialog = LibraryChooser(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            keys = dialog.selected_keys()
            if dialog.compatible.isChecked() or keys:
                self.allowed_keys = None if dialog.compatible.isChecked() else keys
            else:
                QMessageBox.warning(
                    self,
                    quick_translate("Cannot find designs"),
                    quick_translate("Choose at least one existing library entry."),
                )
            self.retranslate()
        dialog.deleteLater()

    def start_search(self, _checked=False, *, budget=None):
        if self.controller.is_running:
            return
        problem = self._validated(budget)
        if problem is None:
            return
        if problem.target_warning is not None:
            QMessageBox.warning(
                self, quick_translate("Potentially conflicting targets"), render(problem.target_warning)
            )
        self.problem = problem
        self.controller.start_smart(problem.plan)
        self.model.reset(self.controller.smart_store)
        self.details.hide()
        self.comparison.hide()
        self._clear_cards()
        self.recommendations = ()
        self._state, self._started = "running", time.monotonic()
        self.pages.setCurrentIndex(2)
        self._update_progress(SearchProgress(total=problem.requirements.simulation_budget))
        self.retranslate()

    def stop_search(self):
        self.controller.stop()
        self._state = "stopping"
        self._update_progress(self._progress)

    def _update_progress(self, progress):
        self._progress = progress
        running = self.controller.is_running
        elapsed = time.monotonic() - self._started if running and self._started else progress.elapsed
        self.status_label.setText(
            quick_translate(
                {
                    "ready": "Ready",
                    "running": "Searching for suitable designs...",
                    "stopping": "Stopping...",
                    "stopped": "Search stopped",
                    "completed": "Search completed",
                    "failed": "Search failed",
                }[self._state]
            )
        )
        self.counts_label.setText(
            quick_translate(
                "Simulations: {completed}/{total}   Valid: {valid}   Rejected: {rejected}   "
                "Best match: {match}   Elapsed: {seconds} s"
            ).format(
                completed=progress.processed,
                total=progress.total,
                valid=progress.feasible,
                rejected=progress.rejected,
                match="—" if progress.best_score is None else "{:.1f}%".format(match_percentage(progress.best_score)),
                seconds="{:.1f}".format(elapsed),
            )
        )
        self.progress_bar.setRange(0, max(1, progress.total))
        self.progress_bar.setValue(progress.processed)
        self.stop_button.setEnabled(running and self._state != "stopping")

    def _elapsed(self):
        if self.controller.is_running:
            self._update_progress(self._progress)

    def _finished(self, summary):
        self._state = summary.state
        self.model.retranslate()
        self.recommendations = recommended_designs(self.controller.smart_store)
        self._clear_cards()
        for index, record in enumerate(self.recommendations, 1):
            card = RecommendationCard(self, index, record)
            self.cards[record.proposal.candidate_id] = card
            self.cards_layout.addWidget(card)
        self._update_progress(summary.progress)
        self.retranslate()
        if summary.error:
            QMessageBox.warning(self, quick_translate("Search failed"), translate(summary.error))
        if self._close_requested:
            self.close()

    def _clear_cards(self):
        self.cards.clear()
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def selected_ids(self):
        return tuple(key for key, card in self.cards.items() if card.selected.isChecked())

    def _selection_changed(self):
        ids = self.selected_ids()
        for card in self.cards.values():
            card.selected.setEnabled(card.selected.isChecked() or len(ids) < 3)
        self.compare_button.setEnabled(not self.controller.is_running and 2 <= len(ids) <= 3)

    def compare_selected(self):
        if not self.controller.is_running and 2 <= len(self.selected_ids()) <= 3:
            self.comparison.show_candidates(self.controller.smart_store.compare(self.selected_ids()))

    def show_details(self, candidate_id):
        self.model.retranslate()
        self.details.show_candidate(candidate_id)

    def open_candidate_id(self, candidate_id):
        if self.controller.is_running or self.open_candidate is None:
            return
        try:
            request = self.controller.request_for(candidate_id)
            if request.valid:
                return self.open_candidate(request.snapshot.to_dict())
        except (ValueError, RuntimeError) as error:
            QMessageBox.warning(self, quick_translate("Cannot open design"), translate(str(error)))

    def open_advanced(self):
        if self.controller.is_running or self.open_advanced_callback is None:
            return
        problem = self._validated()
        if problem is None:
            return
        ids = self.selected_ids()
        record = next((r for r in self.recommendations if ids and r.proposal.candidate_id == ids[0]), None)
        record = record or (self.recommendations[0] if self.recommendations else None)
        if record is None:
            QMessageBox.warning(
                self,
                quick_translate("Cannot open design"),
                quick_translate("Run the search before opening a recommendation in Design Assistant."),
            )
            return
        request = self.controller.request_for(record.proposal.candidate_id)
        if not request.valid or request.snapshot is None:
            return
        # Advanced improves the actual selected result, with its full geometry,
        # count, nozzle and exact existing propellant. Smart's baseline-relative
        # ranges intentionally start here rather than at the Quick preset.
        smart = replace(
            problem.plan.requirements, library_keys=(record.variant.library_key,), geometries=(CURRENT_GEOMETRY,)
        )
        try:
            variant = SearchSpaceBuilder().build(request.snapshot, smart, self.library_entries).variants[0]
            return self.open_advanced_callback(problem, variant)
        except (ValueError, TypeError) as error:
            QMessageBox.warning(self, quick_translate("Cannot open design"), translate(str(error)))

    def _estimate(self):
        self.estimate_label.setText(
            quick_translate("Estimated budget: up to {count} simulations, including rechecks.").format(
                count=QUALITY_BUDGETS[self.quality.currentData()]
            )
        )

    def _review(self):
        if self.problem is None:
            return
        lines = []
        for criterion in self.problem.requirements.criteria:
            row = self.rows[criterion.field]
            lines.append(
                f"{quick_translate(row.source)} — {quick_translate(criterion.mode.title())}: "
                f"{display_number(criterion.value, row.unit, row.display_unit)} {row.display_unit}"
            )
        lines.append(
            quick_translate(
                "Automatic options: {libraries} library entries, {variants} library/geometry combinations."
            ).format(
                libraries=len({v.library_key for v in self.problem.plan.variants}),
                variants=len(self.problem.plan.variants),
            )
        )
        lines.append(
            quick_translate("Geometries to explore: {geometries}").format(
                geometries=", ".join(
                    geometry_name(g) for g in sorted({v.geometries[0] for v in self.problem.plan.variants})
                )
            )
        )
        lines.append(
            quick_translate("Grain counts to explore: {counts}").format(
                counts=", ".join(str(n) for n in sorted({len(v.geometries) for v in self.problem.plan.variants}))
            )
        )
        lines.append(
            quick_translate(
                "The budget covers {selected} of {total} possible library/geometry/count combinations."
            ).format(selected=len(self.problem.plan.variants), total=self.problem.total_combinations)
        )
        lines.append(self.estimate_label.text())
        lines.extend(render(d) for d in self.problem.diagnostics)
        self.review.setPlainText("\n".join(lines))

    def retranslate(self):
        self.setWindowTitle(quick_translate("Quick Design"))
        self.notice.setText(
            quick_translate(
                "Results are simulation-based and depend on the entered model, material data and constraints."
            )
        )
        sources = ("1. What is known?", "2. Review and search quality", "3. Recommended designs")
        self.step_label.setText(quick_translate(sources[self.pages.currentIndex()]))
        self.requirements_help.setText(
            quick_translate(
                "Enter maximum diameter, maximum length and desired burn time. "
                "Quick Design creates grains and a nozzle automatically; "
                "the current motor provides only general settings."
            )
        )
        self.dimension_notice.setText(
            quick_translate(
                "Dimensions describe the propellant envelope. Allow extra space for casing, nozzle and gaps. "
                "Mass limits cover propellant only."
            )
        )
        self.known_group.setTitle(quick_translate("Required"))
        self.optional_group.setTitle(quick_translate("Optional targets"))
        for key, row in self.rows.items():
            required = key in ("diameter", "length", "burn_time")
            row.label.setText(quick_translate(row.source) + (" *" if required else "") + f" ({row.display_unit})")
            row.enabled.setText(quick_translate("Set target value"))
            for i, mode in enumerate(("Target", "Maximum", "Minimum")):
                row.mode.setItemText(i, quick_translate(mode))
        self.other_group.setTitle(quick_translate("Other limits (optional)"))
        for key, (minimum, maximum, label) in self.constraints.items():
            label.setText(f"{metric_label(key)} ({metric_unit(key, self.preferences)[1]})")
            minimum.enabled.setText(quick_translate("Minimum"))
            maximum.enabled.setText(quick_translate("Maximum"))
        self.reject_warnings.setText(quick_translate("Reject candidates with WARNING alerts"))
        self.options_group.setTitle(quick_translate("Allowed options and search"))
        self.library_label.setText(quick_translate("Allowed library entries"))
        self.library_status.setText(
            quick_translate("Use compatible library entries")
            if self.allowed_keys is None
            else quick_translate("Selected library entries: {count}").format(count=len(self.allowed_keys))
        )
        self.choose_button.setText(quick_translate("Choose..."))
        self.priority_label.setText(quick_translate("Design priority"))
        self.priority.setToolTip(
            quick_translate("Priority changes only weights of enabled targets; it does not create missing targets.")
        )
        self.quality_label.setText(quick_translate("Search quality"))
        for i, source in enumerate(("Balanced", "Match burn time", "Match thrust", "Match total impulse")):
            self.priority.setItemText(i, quick_translate(source))
        for i, source in enumerate(("Quick", "Balanced", "Thorough")):
            self.quality.setItemText(i, quick_translate(source))
        self.review_label.setText(quick_translate("Search problem and skipped options"))
        self._estimate()
        self._review()
        for button, source in (
            (self.back_button, "Back"),
            (self.next_button, "Next"),
            (self.find_button, "Find Designs"),
            (self.advanced_button, "Open in Design Assistant"),
            (self.close_button, "Close"),
            (self.stop_button, "Stop"),
            (self.compare_button, "Compare"),
        ):
            button.setText(quick_translate(source))
        running, page = self.controller.is_running, self.pages.currentIndex()
        self.back_button.setEnabled(not running and page > 0)
        self.next_button.setVisible(page == 0)
        self.find_button.setVisible(True)
        self.find_button.setEnabled(not running)
        self.advanced_button.setEnabled(not running and bool(self.recommendations))
        self.pages.widget(0).setEnabled(not running)
        self.pages.widget(1).setEnabled(not running)
        self.results_label.setText(quick_translate("Recommended designs"))
        self.results_hint.setText(
            quick_translate("Stopped results may be provisional.")
            if self._state == "stopped"
            else quick_translate("Best matches found; similar designs are filtered. Up to five recommendations.")
            if self.recommendations
            else quick_translate("No admissible designs yet. Review requirements or allowed options.")
        )
        for card in self.cards.values():
            card.retranslate()
        self._selection_changed()
        self._update_progress(self._progress)

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
