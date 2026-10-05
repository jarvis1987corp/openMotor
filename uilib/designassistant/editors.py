"""Shared numeric editors; conversion stays at the presentation boundary."""

from PyQt6.QtWidgets import QCheckBox, QDoubleSpinBox, QHBoxLayout, QSpinBox, QWidget


def number_editor(value=1.0, minimum=-1e100, maximum=1e100, integer=False):
    editor = QSpinBox() if integer else QDoubleSpinBox()
    if not integer:
        editor.setDecimals(12)
        editor.setSingleStep(0.1)
    editor.setRange(int(minimum) if integer else minimum, int(maximum) if integer else maximum)
    editor.setValue(value)
    editor.setMinimumWidth(110)
    return editor


class OptionalBound(QWidget):
    def __init__(self, enabled=False):
        super().__init__()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 0, 2, 0)
        self.enabled = QCheckBox()
        self.value = number_editor()
        self.value.setEnabled(enabled)
        self.enabled.setChecked(enabled)
        self.enabled.toggled.connect(self.value.setEnabled)
        layout.addWidget(self.enabled)
        layout.addWidget(self.value)
