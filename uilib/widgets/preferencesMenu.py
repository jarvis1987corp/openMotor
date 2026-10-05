from PyQt6.QtWidgets import QDialog, QApplication
from PyQt6.QtCore import QEvent, pyqtSignal

from ..views.Preferences_ui import Ui_PreferencesDialog
from ..localization import LANGUAGES


class PreferencesMenu(QDialog):

    preferencesApplied = pyqtSignal(dict)

    def __init__(self):
        QDialog.__init__(self)

        self.ui = Ui_PreferencesDialog()
        self.ui.setupUi(self)
        for code, label in LANGUAGES:
            self.ui.comboBoxLanguage.addItem(label, code)

        self.setWindowIcon(QApplication.instance().icon)

        self.ui.buttonBox.accepted.connect(self.apply)
        self.ui.buttonBox.rejected.connect(self.cancel)

    def load(self, pref):
        self.ui.comboBoxLanguage.setCurrentIndex(self.ui.comboBoxLanguage.findData(pref.language))
        self.ui.settingsEditorGeneral.setPreferences(pref)
        self.ui.settingsEditorGeneral.loadProperties(pref.general)
        self.ui.settingsEditorUnits.loadProperties(pref.units)
        # Opening the dialog may round converted spinbox values. Changing only
        # the language must not persist those round trips as motor settings.
        self._original = pref.getDict()
        self._loadedGeneral = self.ui.settingsEditorGeneral.getProperties()
        self._loadedUnits = self.ui.settingsEditorUnits.getProperties()

    def apply(self):
        general = self.ui.settingsEditorGeneral.getProperties()
        units = self.ui.settingsEditorUnits.getProperties()
        if general == self._loadedGeneral:
            general = self._original['general']
        if units == self._loadedUnits:
            units = self._original['units']
        self.preferencesApplied.emit({'language': self.ui.comboBoxLanguage.currentData(),
                                      'general': general, 'units': units})
        self.hide()

    def cancel(self):
        self.hide()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, 'ui'):
            # Retain the selected code and edits in both settings editors.
            self.ui.retranslateUi(self)
        super().changeEvent(event)
