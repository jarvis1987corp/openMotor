import sys
from threading import Thread

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import QHeaderView, QMainWindow, QMessageBox, QTableWidgetItem

import motorlib
import uilib.widgets.aboutDialog
from uilib.designassistant.window import DesignAssistantWindow
from uilib.localization import QT_TRANSLATE_NOOP, display_text, geometry_name
from uilib.views.MainWindow_ui import Ui_MainWindow


class Window(QMainWindow):
    def __init__(self, app):
        QMainWindow.__init__(self)
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.app = app
        self.designAssistant = None
        self._closeAfterDesignSearch = False

        self.setWindowIcon(self.app.icon)

        self.appVersion = uilib.fileIO.appVersion
        self.appVersionStr = uilib.fileIO.appVersionStr

        self.app.preferencesManager.preferencesChanged.connect(self.applyPreferences)

        self.app.propellantManager.updated.connect(self.propListChanged)

        self.motorStatLabels = [
            self.ui.labelMotorDesignation,
            self.ui.labelImpulse,
            self.ui.labelDeliveredISP,
            self.ui.labelBurnTime,
            self.ui.labelVolumeLoading,
            self.ui.labelAveragePressure,
            self.ui.labelPeakPressure,
            self.ui.labelInitialKN,
            self.ui.labelPeakKN,
            self.ui.labelIdealThrustCoefficient,
            self.ui.labelPropellantMass,
            self.ui.labelPropellantDimensions,
            self.ui.labelPortThroatRatio,
            self.ui.labelPeakMassFlux,
            self.ui.labelDeliveredThrustCoefficient,
        ]

        self.app.fileManager.fileNameChanged.connect(self.updateWindowTitle)
        self.app.fileManager.newMotor.connect(lambda _: self.resetOutput(True))
        self.app.fileManager.newMotor.connect(self.getQuickResults)
        self.app.fileManager.recentFileLoaded.connect(self.motorImported)

        self.app.importExportManager.motorImported.connect(self.motorImported)

        self.app.simulationManager.newSimulationResult.connect(self.updateMotorStats)
        self.app.simulationManager.newSimulationResult.connect(self.ui.resultsWidget.showData)

        self.aboutDialog = uilib.widgets.aboutDialog.AboutDialog(self.appVersionStr)

        self.app.toolManager.setupMenu(self.ui.menuTools)
        self.app.toolManager.changeApplied.connect(self.postLoadUpdate)

        self.setupMotorStats()
        self.setupMotorEditor()
        self.setupGrainAddition()
        self.setupMenu()
        self.setupPropSelector()
        self.setupGrainTable()
        self.setupGraph()

    def updateWindowTitle(self, name, saved):
        if not name and saved:
            self.setWindowTitle("openMotor")
            return
        unsavedStr = "*" if not saved else ""
        displayName = name if name is not None else ""
        self.setWindowTitle("openMotor - {}{}".format(displayName, unsavedStr))

    def setupMotorStats(self):
        self._peakMassFluxText = None
        for label in self.motorStatLabels:
            label.setText("-")

    def doubleClickGrainSelector(self):
        self.editGrain()

    def setupMotorEditor(self):
        self.ui.motorEditor.setPreferences(self.app.preferencesManager.preferences)
        self.ui.pushButtonEditGrain.pressed.connect(self.editGrain)
        self.ui.motorEditor.changeApplied.connect(self.applyChange)
        # Enables only buttons for actions possible given the selected grain
        self.ui.motorEditor.closed.connect(self.checkGrainSelection)

    def setupGrainAddition(self):
        for name in motorlib.grains.grainTypes:
            self.ui.comboBoxGrainGeometry.addItem(geometry_name(name), name)
        self.ui.pushButtonAddGrain.pressed.connect(self.addGrain)

    def setupMenu(self):
        # File menu
        self.ui.actionNew.triggered.connect(self.newMotor)
        self.ui.actionSave.triggered.connect(self.app.fileManager.save)
        self.ui.actionSaveAs.triggered.connect(self.app.fileManager.saveAs)
        # Lambda because the signal passes in an argument
        self.ui.actionOpen.triggered.connect(lambda x: self.loadMotor(None))

        self.app.importExportManager.createMenus(self.ui.menuImport, self.ui.menuExport)
        self.app.fileManager.createRecentlyOpenedMenu(self.ui.menuOpen_Recent)

        self.ui.actionQuit.triggered.connect(self.closeEvent)

        # Edit menu
        self.ui.actionUndo.triggered.connect(self.undo)
        self.ui.actionRedo.triggered.connect(self.redo)
        self.ui.actionPreferences.triggered.connect(self.app.preferencesManager.showMenu)
        self.ui.actionPropellantEditor.triggered.connect(self.app.propellantManager.showMenu)

        # Sim
        self.ui.actionRunSimulation.triggered.connect(self.runSimulation)

        self.designAssistantAction = QAction(self.tr("Design Assistant"), self)
        self.designAssistantAction.triggered.connect(self.openDesignAssistant)
        self.ui.menuTools.addSeparator()
        self.ui.menuTools.addAction(self.designAssistantAction)

        # Help
        self.ui.actionAboutOpenMotor.triggered.connect(self.aboutDialog.show)

    def openDesignAssistant(self):
        if self.designAssistant is None:
            manager = self.app.fileManager
            self.designAssistant = DesignAssistantWindow(
                manager.getCurrentMotor().getDict(),
                self.app.preferencesManager.preferences,
                self,
                source_name=manager.fileName or "",
                open_candidate=self.openDesignCandidate,
            )
            self.designAssistant.setWindowIcon(self.app.icon)
            self.designAssistant.closed.connect(self._designClosed)
            self.designAssistant.controller.finished.connect(self._designFinished)
        self.designAssistant.show()
        self.designAssistant.raise_()
        self.designAssistant.activateWindow()

    def _designClosed(self):
        self.designAssistant = None

    def _designFinished(self, _):
        if self._closeAfterDesignSearch:
            self._closeAfterDesignSearch = False
            self.close()

    def openDesignCandidate(self, snapshot):
        editor = self.ui.motorEditor
        if editor.hasPendingChanges():
            choice = QMessageBox.question(
                self,
                self.tr("Unapplied Motor Editor changes"),
                self.tr("Apply the current Motor Editor changes before opening this candidate?"),
                QMessageBox.StandardButton.Apply
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                return False
            if choice == QMessageBox.StandardButton.Apply:
                editor.apply()
        if not self.app.fileManager.openUnsavedSnapshot(snapshot):
            return False
        editor.close()
        self.postLoadUpdate()
        self.raise_()
        self.activateWindow()
        return True

    def setupPropSelector(self):
        self.ui.pushButtonPropEditor.pressed.connect(self.app.propellantManager.showMenu)
        self.populatePropSelector()
        self.ui.comboBoxPropellant.currentIndexChanged.connect(self.propChooserChanged)
        self.updatePropBoxSelection()

    def populatePropSelector(self):
        self.ui.comboBoxPropellant.clear()
        self.ui.comboBoxPropellant.addItem("-")
        self.ui.comboBoxPropellant.addItems(self.app.propellantManager.getNames())

    def disablePropSelector(self):
        self.ui.comboBoxPropellant.blockSignals(True)

    def enablePropSelector(self):
        self.ui.comboBoxPropellant.blockSignals(False)

    def updatePropBoxSelection(self):
        self.disablePropSelector()
        prop = self.app.fileManager.getCurrentMotor().propellant
        if prop is None:
            self.ui.comboBoxPropellant.setCurrentText("-")
        else:
            self.ui.comboBoxPropellant.setCurrentText(prop.getProperty("name"))
        self.enablePropSelector()

    def setupGrainTable(self):
        self.ui.tableWidgetGrainList.clearContents()

        header = self.ui.tableWidgetGrainList.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        self.updateGrainTable()

        self.ui.pushButtonMoveGrainUp.pressed.connect(lambda: self.moveGrain(-1))
        self.ui.pushButtonMoveGrainDown.pressed.connect(lambda: self.moveGrain(1))
        self.ui.pushButtonDeleteGrain.pressed.connect(self.deleteGrain)
        self.ui.pushButtonCopyGrain.pressed.connect(self.copyGrain)

        self.ui.tableWidgetGrainList.itemSelectionChanged.connect(self.checkGrainSelection)
        self.checkGrainSelection()

        self.ui.tableWidgetGrainList.doubleClicked.connect(self.doubleClickGrainSelector)

    def setupGraph(self):
        self.ui.resultsWidget.resetPlot()
        self.ui.resultsWidget.setPreferences(self.app.preferencesManager.preferences)

    def applyChange(self, propDict):
        ind = self.ui.tableWidgetGrainList.selectionModel().selectedRows()
        cm = self.app.fileManager.getCurrentMotor()
        if len(ind) > 0:
            gid = ind[0].row()
            if gid < len(cm.grains):
                cm.grains[gid].setProperties(propDict)
            elif gid == len(cm.grains):
                cm.nozzle.setProperties(propDict)
            else:
                cm.config.setProperties(propDict)
        self.app.fileManager.addNewMotorHistory(cm)
        self.updateGrainTable()

    def propListChanged(self):
        self.resetOutput()
        self.disablePropSelector()
        self.populatePropSelector()
        self.updatePropBoxSelection()
        self.enablePropSelector()

    def propChooserChanged(self):
        cm = self.app.fileManager.getCurrentMotor()
        if self.ui.comboBoxPropellant.currentIndex() == 0:
            cm.propellant = None
        else:
            cm.propellant = self.app.propellantManager.propellants[self.ui.comboBoxPropellant.currentIndex() - 1]
        self.app.fileManager.addNewMotorHistory(cm)

    def updateGrainTable(self):
        cm = self.app.fileManager.getCurrentMotor()
        self.ui.tableWidgetGrainList.setRowCount(len(cm.grains) + 2)
        lengthUnit = self.app.preferencesManager.preferences.units.getProperty("m")
        for gid, grain in enumerate(cm.grains):
            self.ui.tableWidgetGrainList.setItem(gid, 0, QTableWidgetItem(geometry_name(grain.geomName)))
            self.ui.tableWidgetGrainList.setItem(
                gid, 1, QTableWidgetItem(display_text(grain.getDetailsString(lengthUnit)))
            )

        self.ui.tableWidgetGrainList.setItem(len(cm.grains), 0, QTableWidgetItem(self.tr("Nozzle")))
        self.ui.tableWidgetGrainList.setItem(
            len(cm.grains), 1, QTableWidgetItem(display_text(cm.nozzle.getDetailsString(lengthUnit)))
        )

        self.ui.tableWidgetGrainList.setItem(len(cm.grains) + 1, 0, QTableWidgetItem(self.tr("Config")))
        self.ui.tableWidgetGrainList.setItem(len(cm.grains) + 1, 1, QTableWidgetItem("-"))

    def toggleGrainEditButtons(self, state, grainTable=True):
        if grainTable:
            self.ui.tableWidgetGrainList.setEnabled(state)
        self.ui.pushButtonDeleteGrain.setEnabled(state)
        self.ui.pushButtonEditGrain.setEnabled(state)
        self.ui.pushButtonCopyGrain.setEnabled(state)
        self.ui.pushButtonMoveGrainDown.setEnabled(state)
        self.ui.pushButtonMoveGrainUp.setEnabled(state)

    def toggleGrainButtons(self, state):
        self.toggleGrainEditButtons(state)
        self.ui.comboBoxPropellant.setEnabled(state)
        self.ui.comboBoxGrainGeometry.setEnabled(state)
        self.ui.pushButtonAddGrain.setEnabled(state)

    def checkGrainSelection(self):
        ind = self.ui.tableWidgetGrainList.selectionModel().selectedRows()
        cm = self.app.fileManager.getCurrentMotor()
        if len(ind) > 0:
            gid = ind[0].row()
            self.toggleGrainButtons(True)
            if gid == 0:  # Top grain selected
                self.ui.pushButtonMoveGrainUp.setEnabled(False)
            if gid == len(cm.grains) - 1:  # Bottom grain selected
                self.ui.pushButtonMoveGrainDown.setEnabled(False)
            if gid >= len(cm.grains):  # Nozzle or config selected
                self.ui.pushButtonMoveGrainUp.setEnabled(False)
                self.ui.pushButtonMoveGrainDown.setEnabled(False)
                self.ui.pushButtonDeleteGrain.setEnabled(False)
                self.ui.pushButtonCopyGrain.setEnabled(False)
        else:
            self.toggleGrainEditButtons(False, False)

    def moveGrain(self, offset):
        cm = self.app.fileManager.getCurrentMotor()
        ind = self.ui.tableWidgetGrainList.selectionModel().selectedRows()
        if len(ind) > 0:
            gid = ind[0].row()
            if gid < len(cm.grains) and gid + offset < len(cm.grains) and gid + offset >= 0:
                cm.grains[gid + offset], cm.grains[gid] = cm.grains[gid], cm.grains[gid + offset]
                self.ui.tableWidgetGrainList.selectRow(gid + offset)
                self.app.fileManager.addNewMotorHistory(cm)
                self.updateGrainTable()

    def editGrain(self):
        ind = self.ui.tableWidgetGrainList.selectionModel().selectedRows()
        cm = self.app.fileManager.getCurrentMotor()
        if len(ind) > 0:
            gid = ind[0].row()
            if gid < len(cm.grains):
                self.ui.motorEditor.loadObject(cm.grains[gid])
            elif gid == len(cm.grains):
                self.ui.motorEditor.loadObject(cm.nozzle)
            else:
                self.ui.motorEditor.loadObject(cm.config)
            self.toggleGrainButtons(False)

    def copyGrain(self):
        ind = self.ui.tableWidgetGrainList.selectionModel().selectedRows()
        cm = self.app.fileManager.getCurrentMotor()
        if len(ind) > 0:
            gid = ind[0].row()
            if gid < len(cm.grains):
                cm.grains.append(cm.grains[gid])
                self.app.fileManager.addNewMotorHistory(cm)
                self.updateGrainTable()
                self.checkGrainSelection()

    def deleteGrain(self):
        ind = self.ui.tableWidgetGrainList.selectionModel().selectedRows()
        cm = self.app.fileManager.getCurrentMotor()
        if len(ind) > 0:
            gid = ind[0].row()
            if gid < len(cm.grains):
                del cm.grains[gid]
                self.app.fileManager.addNewMotorHistory(cm)
                self.updateGrainTable()
                self.checkGrainSelection()

    def addGrain(self):
        cm = self.app.fileManager.getCurrentMotor()
        newGrain = motorlib.grains.grainTypes[self.ui.comboBoxGrainGeometry.currentData()]()
        if len(cm.grains) != 0:
            newGrain.setProperty("diameter", cm.grains[-1].getProperty("diameter"))
        cm.grains.append(newGrain)
        self.app.fileManager.addNewMotorHistory(cm)
        self.updateGrainTable()
        self.ui.tableWidgetGrainList.selectRow(len(cm.grains) - 1)
        self.ui.motorEditor.loadObject(cm.grains[-1])
        self.checkGrainSelection()
        self.toggleGrainButtons(False)

    def formatMotorStat(self, quantity, inUnit):
        convUnit = self.app.preferencesManager.preferences.getUnit(inUnit)
        return "{:.2f} {}".format(motorlib.units.convert(quantity, inUnit, convUnit), convUnit)

    def updateMotorStats(self, simResult):
        self.ui.labelMotorDesignation.setText(
            "{} ({:.0%})".format(simResult.getDesignation(), simResult.getImpulseClassPercentage())
        )
        self.ui.labelImpulse.setText(self.formatMotorStat(simResult.getImpulse(), "Ns"))
        self.ui.labelDeliveredISP.setText(self.formatMotorStat(simResult.getISP(), "s"))
        self.ui.labelBurnTime.setText(self.formatMotorStat(simResult.getBurnTime(), "s"))
        self.ui.labelVolumeLoading.setText("{:.2f}%".format(simResult.getVolumeLoading()))

        self.ui.labelAveragePressure.setText(self.formatMotorStat(simResult.getAveragePressure(), "Pa"))
        self.ui.labelPeakPressure.setText(self.formatMotorStat(simResult.getMaxPressure(), "Pa"))
        self.ui.labelInitialKN.setText(self.formatMotorStat(simResult.getInitialKN(), ""))
        self.ui.labelPeakKN.setText(self.formatMotorStat(simResult.getPeakKN(), ""))
        self.ui.labelIdealThrustCoefficient.setText(self.formatMotorStat(simResult.getIdealThrustCoefficient(), ""))

        self.ui.labelPropellantMass.setText(self.formatMotorStat(simResult.getPropellantMass(), "kg"))
        propellantDimensionString = "⌀ {} x {}".format(
            self.formatMotorStat(simResult.getMaxPropellantDiameter(), "m"),
            self.formatMotorStat(simResult.getPropellantLength(), "m"),
        )
        self.ui.labelPropellantDimensions.setText(propellantDimensionString)

        # These only make sense for grains with cores, so blank them out for endburners
        if simResult.getPortRatio() is not None:
            self.ui.labelPortThroatRatio.setText(self.formatMotorStat(simResult.getPortRatio(), ""))
            peakMassFluxQuantity = self.formatMotorStat(simResult.getPeakMassFlux(), "kg/(m^2*s)")
            peakMassFluxGrain = simResult.getPeakMassFluxLocation() + 1
            self._peakMassFluxText = QT_TRANSLATE_NOOP("Window", "{} (G: {})").format(
                peakMassFluxQuantity, peakMassFluxGrain
            )
            self.ui.labelPeakMassFlux.setText(display_text(self._peakMassFluxText))

        else:
            self._peakMassFluxText = None
            self.ui.labelPortThroatRatio.setText("-")
            self.ui.labelPeakMassFlux.setText("-")
        self.ui.labelDeliveredThrustCoefficient.setText(
            self.formatMotorStat(simResult.getAdjustedThrustCoefficient(), "")
        )

    def getQuickResults(self, motor):
        def thread():
            self.showQuickResults(motor.getQuickResults())

        dataThread = Thread(target=thread)
        dataThread.start()

    def showQuickResults(self, results):
        self.ui.labelVolumeLoading.setText("{:.2f}%".format(results["volumeLoading"]))
        self.ui.labelInitialKN.setText(self.formatMotorStat(results["initialKn"], ""))
        propellantDimensionString = "⌀ {} x {}".format(
            self.formatMotorStat(results["diameter"], "m"), self.formatMotorStat(results["length"], "m")
        )
        self.ui.labelPropellantDimensions.setText(propellantDimensionString)
        self.ui.labelPropellantMass.setText(self.formatMotorStat(results["propellantMass"], "kg"))
        self.ui.labelPortThroatRatio.setText(self.formatMotorStat(results["portRatio"], ""))

    def runSimulation(self):
        self.resetOutput()
        cm = self.app.fileManager.getCurrentMotor()
        self.app.simulationManager.runSimulation(cm)

    def resetOutput(self, keepGrainChecks=True):
        self.setupMotorStats()
        self.ui.resultsWidget.resetPlot()
        self.updateGrainTable()
        self.ui.resultsWidget.setupGrainChecks(len(self.app.fileManager.getCurrentMotor().grains), keepGrainChecks)

    def undo(self):
        self.app.fileManager.undo()
        self.updateGrainTable()
        self.checkGrainSelection()
        self.updatePropBoxSelection()
        self.ui.motorEditor.close()

    def redo(self):
        self.app.fileManager.redo()
        self.updateGrainTable()
        self.checkGrainSelection()
        self.updatePropBoxSelection()
        self.ui.motorEditor.close()

    def newMotor(self):
        self.app.fileManager.newFile()
        self.updatePropBoxSelection()
        self.resetOutput()
        self.ui.motorEditor.close()

    def motorImported(self):
        self.ui.motorEditor.close()
        self.postLoadUpdate()
        self.getQuickResults(self.app.fileManager.getCurrentMotor())

    def loadMotor(self, path=None):
        self.disablePropSelector()
        if self.app.fileManager.load(path):
            self.postLoadUpdate()
            # Needed because postLoadUpdate clears results
            self.getQuickResults(self.app.fileManager.getCurrentMotor())
        self.enablePropSelector()
        self.ui.motorEditor.close()

    # Clear out all info related to old motor/sim in the interface
    def postLoadUpdate(self):
        self.disablePropSelector()  # It is enabled again at the end of updatePropBoxSelection
        self.resetOutput(False)
        self.updateGrainTable()
        self.populatePropSelector()
        self.updatePropBoxSelection()

    def closeEvent(self, event=None):
        if self.designAssistant is not None and self.designAssistant.controller.is_running:
            self._closeAfterDesignSearch = True
            self.designAssistant.stop_search()
            if event is not None and not isinstance(event, bool):
                event.ignore()
            return
        if self.app.fileManager.unsavedCheck():
            sys.exit()
            return
        if event is None or isinstance(event, bool):
            return
        event.ignore()

    def applyPreferences(self, prefDict):
        self.updateGrainTable()
        self.setupMotorStats()
        self.setupGraph()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, "motorStatLabels"):
            # Generated retranslateUi resets output placeholders and the title.
            # Repaint text only; do not reload the project, editors or results.
            values = [label.text() for label in self.motorStatLabels]
            title = self.windowTitle()
            self.ui.retranslateUi(self)
            self.designAssistantAction.setText(self.tr("Design Assistant"))
            for label, value in zip(self.motorStatLabels, values):
                label.setText(value)
            if self._peakMassFluxText is not None:
                self.ui.labelPeakMassFlux.setText(display_text(self._peakMassFluxText))
            self.setWindowTitle(title)
            combo = self.ui.comboBoxGrainGeometry
            for index in range(combo.count()):
                combo.setItemText(index, geometry_name(combo.itemData(index)))
            # Update existing table items without disturbing row selection.
            cm = self.app.fileManager.getCurrentMotor()
            unit = self.app.preferencesManager.preferences.getUnit("m")
            rows = [(geometry_name(g.geomName), display_text(g.getDetailsString(unit))) for g in cm.grains]
            rows.extend([(self.tr("Nozzle"), display_text(cm.nozzle.getDetailsString(unit))), (self.tr("Config"), "-")])
            for row, texts in enumerate(rows):
                for column, text in enumerate(texts):
                    item = self.ui.tableWidgetGrainList.item(row, column)
                    if item is not None:
                        item.setText(text)
        super().changeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            if len(self.ui.tableWidgetGrainList.selectedItems()) != 0:
                self.deleteGrain()
