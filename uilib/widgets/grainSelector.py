from PyQt6.QtWidgets import QGroupBox, QCheckBox, QRadioButton, QVBoxLayout
from PyQt6.QtCore import QEvent, pyqtSignal, Qt

class GrainSelector(QGroupBox):

    checksChanged = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent)

        self.checks = []
        self.setLayout(QVBoxLayout())
        self.setTitle(self.tr("Grains"))

    def resetChecks(self):
        for _ in range(0, len(self.checks)):
            self.layout().removeWidget(self.checks[-1])
            self.checks[-1].deleteLater()
            del self.checks[-1]

    def setupChecks(self, numGrains, multiselect):
        for gid in range(numGrains):
            checkTitle = self.tr("Grain {}").format(gid + 1)
            if multiselect:
                check = QCheckBox(checkTitle)
                check.setCheckState(Qt.CheckState.Checked)
            else:
                check = QRadioButton(checkTitle)
            self.layout().addWidget(check)
            self.checks.append(check)
            self.checks[-1].toggled.connect(self.checksChanged.emit)

    def getSelectedGrains(self):
        selected = []
        for checkId, check in enumerate(self.checks):
            if check.isChecked():
                selected.append(checkId)
        return selected

    def getUnselectedGrains(self):
        selected = []
        for checkId, check in enumerate(self.checks):
            if not check.isChecked():
                selected.append(checkId)
        return selected

    def setChecks(self, checks):
        for check in self.checks:
            check.setCheckState(Qt.CheckState.Unchecked)
        for check in checks:
            self.checks[check].setCheckState(Qt.CheckState.Checked)

    def getNumberChecks(self):
        return len(self.checks)

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange:
            self.setTitle(self.tr('Grains'))
            for index, check in enumerate(getattr(self, 'checks', [])):
                check.setText(self.tr('Grain {}').format(index + 1))
        super().changeEvent(event)
