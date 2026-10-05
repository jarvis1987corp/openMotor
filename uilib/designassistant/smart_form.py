"""Simplified project requirements without exposing internal property paths."""

from dataclasses import dataclass

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from designassistant import LibraryEntry, MetricConstraint, SearchSpaceBuilder, SmartDesignRequirements, Target
from designassistant.smart import CURRENT_GEOMETRY, QUALITY_BUDGETS
from motorlib.units import convert
from uilib.localization import geometry_name

from .editors import OptionalBound, number_editor
from .presentation import METRIC_LABELS, metric_label, metric_unit, translate


@dataclass
class SmartTargetRow:
    enabled: object
    value: object
    weight: object
    tolerance: object
    label: object
    weight_label: object
    tolerance_label: object


class SmartDesignForm(QWidget):
    def __init__(self, baseline, preferences, library_entries, parent=None):
        super().__init__(parent)
        self.baseline, self.preferences = baseline, preferences
        self.library_entries = tuple({entry.key: entry for entry in library_entries}.values())
        self.labels, self.groups = [], []
        layout = QVBoxLayout(self)
        self.help = QLabel()
        self.help.setWordWrap(True)
        layout.addWidget(self.help)

        limits = self._group(layout, "1. Project limits (required)")
        self.diameter_unit = preferences.getUnit("m") if preferences is not None else "m"
        data = baseline.to_dict()
        diameter = max([g["properties"]["diameter"] for g in data["grains"]] + [data["nozzle"]["exit"], 0.001])
        self.maximum_diameter = number_editor(convert(diameter, "m", self.diameter_unit), 0, 1e100)
        self.diameter_label = QLabel()
        limits.addRow(self.diameter_label, self.maximum_diameter)
        self.engine_limits = QLabel()
        self.engine_limits.setWordWrap(True)
        limits.addRow(self.engine_limits)

        targets = self._group(layout, "2. Targets (enable at least one)")
        self.targets = {}
        for metric, value in (("burn_time", 2.0), ("total_impulse", 100.0), ("average_thrust", 50.0)):
            row = SmartTargetRow(
                QCheckBox(),
                number_editor(value, 0),
                number_editor(1, 0, 1e8),
                number_editor(value * 0.1, 0),
                QLabel(),
                QLabel(),
                QLabel(),
            )
            self.targets[metric] = row
            contents = QHBoxLayout()
            for widget in (row.enabled, row.value, row.weight_label, row.weight, row.tolerance_label, row.tolerance):
                contents.addWidget(widget)
            targets.addRow(row.label, contents)
            for control in (row.value, row.weight, row.tolerance):
                control.setEnabled(False)
                row.enabled.toggled.connect(control.setEnabled)

        constraints = self._group(layout, "Optional constraints")
        self.constraints = {}
        for metric in METRIC_LABELS:
            minimum, maximum = OptionalBound(), OptionalBound()
            label = QLabel()
            contents = QHBoxLayout()
            low_label, high_label = QLabel(), QLabel()
            self.labels.extend([(low_label, "Minimum"), (high_label, "Maximum")])
            for widget in (low_label, minimum, high_label, maximum):
                contents.addWidget(widget)
            constraints.addRow(label, contents)
            self.constraints[metric] = (minimum, maximum, label)
        self.reject_warnings = QCheckBox()
        constraints.addRow(self.reject_warnings)

        options = self._group(layout, "3. Allowed options")
        self.all_library = QCheckBox()
        self.library = QListWidget()
        self.library.setMaximumHeight(130)
        original = LibraryEntry.from_dict(data["propellant"]).key if data["propellant"] else None
        for index, entry in enumerate(self.library_entries):
            item = QListWidgetItem(entry.name)
            item.setData(Qt.ItemDataRole.UserRole, entry.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                Qt.CheckState.Checked
                if entry.key == original or original is None and index == 0
                else Qt.CheckState.Unchecked
            )
            self.library.addItem(item)
        if self.library.count() and not self._checked(self.library):
            self.library.item(0).setCheckState(Qt.CheckState.Checked)
        self.all_library.toggled.connect(lambda checked: self.library.setEnabled(not checked))
        options.addRow(self.all_library)
        self._label_row(options, "Existing propellant library", self.library)
        self.geometry = QListWidget()
        self.geometry.setMaximumHeight(100)
        for key in SearchSpaceBuilder.compatible_geometries(baseline):
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if key == CURRENT_GEOMETRY else Qt.CheckState.Unchecked)
            self.geometry.addItem(item)
        self._label_row(options, "Existing grain geometries", self.geometry)
        self.geometry_help = QLabel()
        self.geometry_help.setWordWrap(True)
        options.addRow(self.geometry_help)

        search = self._group(layout, "4. Search quality")
        self.quality = QComboBox()
        for key in QUALITY_BUDGETS:
            self.quality.addItem("", key)
        self.quality.addItem("", "custom")
        self.quality.setCurrentIndex(self.quality.findData("balanced"))
        self.budget = number_editor(QUALITY_BUDGETS["balanced"], 1, 10000, True)
        self.seed = number_editor(1729, 0, 2147483647, True)
        self.top_n = number_editor(10, 1, 100, True)
        for source, control in (
            ("Quality", self.quality),
            ("Candidate Budget", self.budget),
            ("Random Seed", self.seed),
            ("Top N", self.top_n),
        ):
            self._label_row(search, source, control)
        self.estimate = QLabel()
        self.estimate.setWordWrap(True)
        search.addRow(self.estimate)
        self.quality.currentIndexChanged.connect(self._quality_changed)
        self.budget.valueChanged.connect(self._budget_changed)
        layout.addStretch()
        self.retranslate()

    @staticmethod
    def _checked(widget):
        return tuple(
            widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(widget.count())
            if widget.item(i).checkState() == Qt.CheckState.Checked
        )

    def _group(self, layout, source):
        group = QGroupBox()
        self.groups.append((group, source))
        layout.addWidget(group)
        return QFormLayout(group)

    def _label_row(self, layout, source, control):
        label = QLabel()
        self.labels.append((label, source))
        layout.addRow(label, control)

    def _quality_changed(self):
        if self.quality.currentData() in QUALITY_BUDGETS:
            self.budget.setValue(QUALITY_BUDGETS[self.quality.currentData()])
        self._estimate()

    def _budget_changed(self):
        if QUALITY_BUDGETS.get(self.quality.currentData()) != self.budget.value():
            self.quality.setCurrentIndex(self.quality.findData("custom"))
        self._estimate()

    def _estimate(self):
        self.estimate.setText(
            translate("Up to {count} simulations, including finalist rechecks. Engine accuracy stays fixed.").format(
                count=self.budget.value()
            )
        )

    def build_requirements(self):
        targets, constraints = [], []
        for metric, row in self.targets.items():
            if row.enabled.isChecked():
                unit, display = metric_unit(metric, self.preferences)
                targets.append(
                    Target(
                        metric,
                        convert(row.value.value(), display, unit),
                        convert(row.tolerance.value(), display, unit),
                        row.weight.value(),
                    )
                )
        for metric, (minimum, maximum, _) in self.constraints.items():
            unit, display = metric_unit(metric, self.preferences)
            bounds = tuple(
                convert(b.value.value(), display, unit) if b.enabled.isChecked() else None for b in (minimum, maximum)
            )
            if bounds != (None, None):
                constraints.append(MetricConstraint(metric, *bounds))
        keys = (
            tuple(e.key for e in self.library_entries) if self.all_library.isChecked() else self._checked(self.library)
        )
        return SmartDesignRequirements(
            convert(self.maximum_diameter.value(), self.diameter_unit, "m"),
            tuple(targets),
            tuple(constraints),
            keys,
            self._checked(self.geometry),
            self.budget.value(),
            self.seed.value(),
            self.top_n.value(),
            self.reject_warnings.isChecked(),
        )

    def build_plan(self):
        return SearchSpaceBuilder().build(self.baseline, self.build_requirements(), self.library_entries)

    def retranslate(self):
        self.help.setText(
            translate("Set a diameter limit and one or more targets, choose existing options, then run Smart Design.")
        )
        for widget, source in (*self.groups, *self.labels):
            if isinstance(widget, QGroupBox):
                widget.setTitle(translate(source))
            else:
                widget.setText(translate(source))
        self.diameter_label.setText(translate("Maximum outer diameter (required)") + f" ({self.diameter_unit})")
        self.maximum_diameter.setToolTip(
            translate("Applies to grain diameter and nozzle exit. Casing wall thickness and hardware are not modelled.")
        )
        self.engine_limits.setText(
            translate("Existing motor simulation limits also apply. ERROR always rejects a candidate.")
        )
        for metric, row in self.targets.items():
            row.label.setText(f"{metric_label(metric)} ({metric_unit(metric, self.preferences)[1]})")
            row.weight_label.setText(translate("Weight"))
            row.tolerance_label.setText(translate("Tolerance"))
        for metric, (_, _, label) in self.constraints.items():
            label.setText(f"{metric_label(metric)} ({metric_unit(metric, self.preferences)[1]})")
            if metric == "propellant_mass":
                label.setToolTip(translate("Propellant mass excludes casing and nozzle hardware."))
        self.reject_warnings.setText(translate("Reject candidates with WARNING alerts"))
        self.all_library.setText(translate("Allow all existing library entries"))
        self.geometry_help.setText(
            translate(
                "Alternate geometries use the same grain count and only parameters already present in the baseline."
            )
        )
        for index in range(self.geometry.count()):
            item = self.geometry.item(index)
            key = item.data(Qt.ItemDataRole.UserRole)
            item.setText(translate("Keep current grain types") if key == CURRENT_GEOMETRY else geometry_name(key))
        for index, source in enumerate(("Quick", "Balanced", "Thorough", "Custom budget")):
            self.quality.setItemText(index, translate(source))
        self._estimate()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "quality"):
            self.retranslate()
        super().changeEvent(event)
