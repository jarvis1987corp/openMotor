from PyQt6.QtCore import pyqtSignal, QObject
from PyQt6.QtGui import QAction

from .converter import Importer
from .converters import BurnSimImporter, BurnSimExporter, EngExporter, CsvExporter, ImageExporter
from .localization import display_text

class ImportExportManager(QObject):

    motorImported = pyqtSignal()
    propellantImported = pyqtSignal()

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.menuActions = []
        app.translationManager.languageChanged.connect(self.retranslateMenu)
        self.conversions = [BurnSimImporter(self),
                            BurnSimExporter(self), EngExporter(self), CsvExporter(self), ImageExporter(self)]
        self.preferences = None # TODO: change?

        self.simRes = None
        self.motor = None

    def acceptSimRes(self, simRes):
        self.simRes = simRes

    def acceptNewMotor(self, motor):
        self.motor = motor
        self.simRes = None # Invalidate old simRes because it doesn't apply to the new motor

    def setPreferences(self, pref):
        self.preferences = pref

    def unsavedCheck(self):
        return self.app.fileManager.unsavedCheck()

    def startFromMotor(self, motor):
        self.app.fileManager.startFromMotor(motor)
        self.motorImported.emit()

    def createMenus(self, importMenu, exportMenu):
        for conversion in self.conversions:
            if isinstance(conversion, Importer):
                action = QAction(display_text(conversion.name), importMenu)
                importMenu.addAction(action)
            else:
                action = QAction(display_text(conversion.name), exportMenu)
                exportMenu.addAction(action)
            action.setStatusTip(display_text(conversion.description))
            self.menuActions.append((action, conversion))
            action.triggered.connect(conversion.exec)

    def retranslateMenu(self):
        for action, converter in self.menuActions:
            action.setText(display_text(converter.name))
            action.setStatusTip(display_text(converter.description))
