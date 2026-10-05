from motorlib.localization import QT_TRANSLATE_NOOP
from PyQt6.QtWidgets import QDialog, QApplication

from ..converter import Exporter

from ..views.CSVExporter_ui import Ui_CSVExporter
from ..localization import TranslatedForm

class CsvExportMenu(TranslatedForm, QDialog):
    def __init__(self, converter):
        QDialog.__init__(self)
        self.ui = Ui_CSVExporter()
        self.ui.setupUi(self)

        self.setWindowIcon(QApplication.instance().icon)

        self.converter = converter

    def exec(self):
        self.ui.channelSelector.resetChecks()
        self.ui.channelSelector.setupChecks(True, disabled=["time"], default=["time"])
        self.ui.grainSelector.resetChecks()
        self.ui.grainSelector.setupChecks(len(self.converter.manager.simRes.motor.grains), True)
        if super().exec():
            return [self.ui.channelSelector.getUnselectedChannels(), self.ui.grainSelector.getUnselectedGrains()]
        return None


class CsvExporter(Exporter):
    def __init__(self, manager):
        super().__init__(manager, QT_TRANSLATE_NOOP('Converters', 'CSV File'),
            QT_TRANSLATE_NOOP('Converters', 'Exports the results of a simulation in a csv.'), {'.csv': QT_TRANSLATE_NOOP('Converters', 'Comma separated value file')})
        self.menu = CsvExportMenu(self)
        self.reqNotMet = QT_TRANSLATE_NOOP('Converters', "Must have run a simulation to export a .CSV file.")

    def doConversion(self, path, config):
        with open(path, 'w') as outFile:
            outFile.write(self.manager.simRes.getCSV(self.manager.preferences, config[0], config[1]))

    def checkRequirements(self):
        return self.manager.simRes is not None
