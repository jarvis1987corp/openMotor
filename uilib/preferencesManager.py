from os.path import join
from os import replace

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QApplication

from motorlib.properties import PropertyCollection, EnumProperty
from motorlib.units import unitLabels, getAllConversions
from motorlib.motor import MotorConfig

from .fileIO import loadFile, saveFile, getConfigPath, fileTypes
from .defaults import DEFAULT_PREFERENCES
from .widgets import preferencesMenu
from .logger import logger
from .localization import DEFAULT_LANGUAGE, normalize_language

class Preferences():
    def __init__(self, propDict=None):
        self.language = DEFAULT_LANGUAGE
        self.general = MotorConfig()
        self.units = PropertyCollection()
        for unit in unitLabels:
            self.units.props[unit] = EnumProperty(unitLabels[unit], getAllConversions(unit))

        if propDict is not None:
            self.applyDict(propDict)

    def getDict(self):
        prefDict = {}
        prefDict['general'] = self.general.getProperties()
        prefDict['units'] = self.units.getProperties()
        prefDict['language'] = self.language
        return prefDict

    def applyDict(self, dictionary):
        self.general.setProperties(dictionary['general'])
        self.units.setProperties(dictionary['units'])
        self.language = normalize_language(dictionary.get('language', DEFAULT_LANGUAGE))

    def getUnit(self, fromUnit):
        if fromUnit in self.units.props:
            return self.units.getProperty(fromUnit)
        return fromUnit


class PreferencesManager(QObject):

    preferencesChanged = pyqtSignal(object)
    languageChanged = pyqtSignal(str)

    def __init__(self, makeMenu=True):
        super().__init__()
        self.preferences = Preferences(DEFAULT_PREFERENCES)
        self.loadPreferences()
        if makeMenu:
            self.createMenu()

    def createMenu(self):
        self.menu = preferencesMenu.PreferencesMenu()
        self.menu.preferencesApplied.connect(self.newPreferences)

    def newPreferences(self, prefDict):
        logger.log('Updating preferences')
        previous = self.preferences.getDict()
        self.preferences.applyDict(prefDict)
        self.savePreferences()
        if previous['language'] != self.preferences.language:
            self.languageChanged.emit(self.preferences.language)
        current = self.preferences.getDict()
        # A language-only change must not clear displayed simulation results.
        if previous['general'] != current['general'] or previous['units'] != current['units']:
            self.publishPreferences()

    def loadPreferences(self):
        preferencesPath = join(getConfigPath(), 'preferences.yaml')
        try:
            prefDict = loadFile(preferencesPath, fileTypes.PREFERENCES)
            self.preferences.applyDict(prefDict)
            self.publishPreferences()
        except FileNotFoundError:
            logger.warn('Preferences file does not exist, creating new file')
            self.savePreferences()
        except Exception as error:
            backupPath = join(getConfigPath(), 'preferences_backup.yaml')
            logger.warn('Error loading preferences: {}'.format(error))
            QApplication.instance().outputException(error, self.tr("Failed to load preferences. Backing up file to '{}' and starting fresh.").format(backupPath))
            replace(preferencesPath, backupPath)
            self.savePreferences()

    def savePreferences(self):
        try:
            destinationPath = getConfigPath() + 'preferences.yaml'
            logger.log('Saving preferences to "{}"'.format(destinationPath))
            saveFile(destinationPath, self.preferences.getDict(), fileTypes.PREFERENCES)
        except:
            logger.warn('Unable to save preferences')

    def showMenu(self):
        logger.log('Showing preferences menu')
        self.menu.load(self.preferences)
        self.menu.show()

    def publishPreferences(self):
        self.preferencesChanged.emit(self.preferences)
