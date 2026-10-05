from PyQt6.QtCore import QCoreApplication, QEvent, pyqtSignal
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QVBoxLayout,
    QWidget,
)

from ..localization import display_text
from .propertyEditor import PropertyEditor


class CollectionEditor(QWidget):
    changeApplied = pyqtSignal(dict)
    closed = pyqtSignal()

    def __init__(self, parent, buttons=False):
        super(CollectionEditor, self).__init__(QWidget(parent))

        self.preferences = None

        self.propertyEditors = {}
        self.propertyLabels = {}
        self._pendingChanges = False
        self.setLayout(QVBoxLayout())
        self.layout().setSpacing(0)

        self.form = QFormLayout()
        self.layout().addLayout(self.form)

        self.stats = QVBoxLayout()
        self.layout().addLayout(self.stats)

        self.verticalSpacer = QSpacerItem(20, 40, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.layout().addItem(self.verticalSpacer)

        self.buttons = buttons
        if self.buttons:
            self.addButtons()

    def addButtons(self):
        self.buttons = QHBoxLayout()
        self.layout().addLayout(self.buttons)

        self.applyButton = QPushButton(QCoreApplication.translate("CollectionEditor", "Apply"))
        self.applyButton.pressed.connect(self.apply)
        self.applyButton.hide()

        self.cancelButton = QPushButton(QCoreApplication.translate("CollectionEditor", "Cancel"))
        self.cancelButton.pressed.connect(self.close)
        self.cancelButton.hide()

        self.buttons.addWidget(self.applyButton)
        self.buttons.addWidget(self.cancelButton)

    def propertyUpdate(self):
        pass

    def _markPendingChange(self):
        self._pendingChanges = True

    def hasPendingChanges(self):
        return self._pendingChanges

    def close(self):
        self.closed.emit()
        self.cleanup()

    def apply(self):
        res = self.getProperties()
        self.cleanup()
        self.changeApplied.emit(res)
        self.closed.emit()

    def setPreferences(self, pref):
        self.preferences = pref

    def loadProperties(self, obj):
        self.cleanup()
        for prop in obj.props:
            self.propertyEditors[prop] = PropertyEditor(self, obj.props[prop], self.preferences)
            self.propertyEditors[prop].valueChanged.connect(self.propertyUpdate)
            self.propertyEditors[prop].valueChanged.connect(self._markPendingChange)
            label = QLabel("{}:".format(display_text(obj.props[prop].dispName)))
            self.propertyLabels[prop] = label
            label.setSizePolicy(QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
            self.form.addRow(label, self.propertyEditors[prop])
        if self.buttons:
            self.applyButton.show()
            self.cancelButton.show()
        self.propertyUpdate()
        self._pendingChanges = False

    def cleanup(self):
        self._pendingChanges = False
        for _ in self.propertyEditors:
            self.form.removeRow(0)  # Removes the first row, but will delete all by the end of the loop
        self.propertyEditors = {}
        self.propertyLabels = {}

        if self.buttons:
            self.applyButton.hide()
            self.cancelButton.hide()

    def getProperties(self):
        res = {}
        for prop in self.propertyEditors:
            out = self.propertyEditors[prop].getValue()
            if out is not None:
                res[prop] = out
        return res

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange:
            if getattr(self, "buttons", False):
                self.applyButton.setText(QCoreApplication.translate("CollectionEditor", "Apply"))
                self.cancelButton.setText(QCoreApplication.translate("CollectionEditor", "Cancel"))
            for key, label in getattr(self, "propertyLabels", {}).items():
                label.setText("{}:".format(display_text(self.propertyEditors[key].prop.dispName)))
        super().changeEvent(event)
