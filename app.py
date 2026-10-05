import sys
import matplotlib.pyplot as plt
import matplotlib as mpl

from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtGui import QIcon
from PyQt6.QtCore import Qt

import motorlib
from motorlib import simResult
from uilib import preferencesManager, propellantManager, simulationManager, fileManager, toolManager
from uilib import importExportManager
import uilib.widgets.mainWindow
from uilib.logger import logger
from uilib.fileIO import appVersionStr
from uilib.localization import TranslationManager, display_text
from uilib.resources import resource_path

class App(QApplication):
    def __init__(self, args):
        super().__init__(args)

        self.icon = QIcon(resource_path('oMIconCyclesSmall.png'))

        self.headless = '-h' in args

        if not self.headless and self.isDarkMode():
            # Change these settings before any graph widgets are built, so they apply everywhere
            plt.style.use('dark_background')
            mpl.rcParams['axes.facecolor'] = '1e1e1e'
            mpl.rcParams['figure.facecolor'] = '1e1e1e'

        self.translationManager = TranslationManager(self)
        self.preferencesManager = uilib.preferencesManager.PreferencesManager(makeMenu=False)
        self.translationManager.setLanguage(self.preferencesManager.preferences.language)
        self.preferencesManager.languageChanged.connect(self.translationManager.setLanguage)
        self.preferencesManager.createMenu()

        self.propellantManager = uilib.propellantManager.PropellantManager()
        self.preferencesManager.preferencesChanged.connect(self.propellantManager.setPreferences)

        self.simulationManager = uilib.simulationManager.SimulationManager()
        self.preferencesManager.preferencesChanged.connect(self.simulationManager.setPreferences)

        self.fileManager = uilib.fileManager.FileManager(self)
        startupFileLoaded = False
        if len(args) > 1 and args[-1][0] != '-':
            startupFileLoaded = self.fileManager.load(args[-1])
        self.propellantManager.updated.connect(self.fileManager.updatePropellant)

        self.toolManager = uilib.toolManager.ToolManager(self)
        self.preferencesManager.preferencesChanged.connect(self.toolManager.setPreferences)

        self.importExportManager = uilib.importExportManager.ImportExportManager(self)
        self.preferencesManager.preferencesChanged.connect(self.importExportManager.setPreferences)
        self.simulationManager.newSimulationResult.connect(self.importExportManager.acceptSimRes)
        self.fileManager.newMotor.connect(self.importExportManager.acceptNewMotor)

        if self.headless:
            if len(args) < 3:
                print(self.tr('Not enough arguments. Headless mode requires an input file.'))
            elif not startupFileLoaded:
                print(self.tr('Could not load motor file'))
                sys.exit(1)
            else:
                motor = self.fileManager.getCurrentMotor()
                simulationResult = motor.runSimulation()
                for alert in simulationResult.alerts:
                    print('{} ({}, {}): {}'.format(display_text(motorlib.simResult.alertLevelNames[alert.level]),
                        display_text(motorlib.simResult.alertTypeNames[alert.type]),
                        display_text(alert.location),
                        display_text(alert.description)))
                print()
                if '-o' in args:
                    with open(args[args.index('-o') + 1], 'w') as outputFile:
                        outputFile.write(simulationResult.getCSV(self.preferencesManager.preferences))
                else:
                    print(simulationResult.getCSV(self.preferencesManager.preferences))
            sys.exit(0)

        else:
            usingDarkMode = self.isDarkMode()
            currentTheme = self.style().objectName()
            logger.log('openMotor version "{}"'.format(appVersionStr))
            logger.log('Opening window (dark mode: {}, default theme: "{}")'.format(usingDarkMode, currentTheme))
            if startupFileLoaded:
                logger.log('Loaded startup file from "{}"'.format(args[-1]))
            # Windows 10 and before don't have dark mode versions of their themes, so if the user wants dark mode, we have to switch to fusion
            if usingDarkMode and currentTheme in ['windows', 'windowsvista']:
                logger.log('Overriding theme to fusion to get dark mode')
                self.setStyle('fusion')
            self.window = uilib.widgets.mainWindow.Window(self)
            self.preferencesManager.publishPreferences()
            if startupFileLoaded:
                self.fileManager.sendTitleUpdate()
                self.window.getQuickResults(self.fileManager.getCurrentMotor())
                self.window.ui.resultsWidget.setupGrainChecks(len(self.fileManager.getCurrentMotor().grains), False)
            self.window.show()
            logger.log('Window opened')

    def isDarkMode(self):
        if self.headless:
            return False

        return self.styleHints().colorScheme() == Qt.ColorScheme.Dark

    def outputMessage(self, content, title='openMotor'):
        content, title = display_text(content), display_text(title)
        if self.headless:
            print(content)
        else:
            logger.log(content)
            msg = QMessageBox()
            msg.setWindowIcon(self.icon)
            msg.setText(content)
            msg.setWindowTitle(title)
            msg.exec()

    def promptYesNo(self, content, title='openMotor'):
        content, title = display_text(content), display_text(title)
        if self.headless:
            return input('{} (y/n): '.format(content)) == 'y'
        else:
            logger.log(content)
            msg = QMessageBox()
            msg.setWindowIcon(self.icon)
            msg.setText(content)
            msg.setWindowTitle(title)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            return msg.exec() == QMessageBox.StandardButton.Yes

    def outputException(self, exception, text, title=None):
        if title is None:
            title = self.tr('openMotor - Error')
        text, title = display_text(text), display_text(title)
        details = display_text(exception.args[0]) if len(exception.args) == 1 and hasattr(exception.args[0], 'source') else str(exception)
        if self.headless:
            print(text + " " + details)
        else:
            logger.error(text)
            logger.error(exception)
            msg = QMessageBox()
            msg.setWindowIcon(self.icon)
            msg.setText(text)
            msg.setInformativeText(details)
            msg.setWindowTitle(title)
            msg.exec()
