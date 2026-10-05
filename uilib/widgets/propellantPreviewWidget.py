from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import QEvent

import motorlib

from ..views.PropellantPreview_ui import Ui_PropellantPreview
from ..localization import update_alert_list

class PropellantPreviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.ui = Ui_PropellantPreview()
        self.ui.setupUi(self)
        self.alerts = []

    def setPreferences(self, pref):
        self.ui.tabBurnRate.setPreferences(pref)
        self.ui.tabPressure.setPreferences(pref)

    def loadPropellant(self, propellant):
        self.ui.tabAlerts.clear()
        self.ui.tabBurnRate.cleanup()
        self.ui.tabPressure.cleanup()
        alerts = propellant.getErrors()
        self.alerts = alerts
        update_alert_list(self.ui.tabAlerts, alerts)

        for alert in alerts:
            if alert.level == motorlib.simResult.SimAlertLevel.ERROR:
                return

        burnrateData = [[], []]
        minPres = int(propellant.getMinimumValidPressure()) + 1 # Add 1 Pa to avoid crashing on burnrate for 0 Pa
        maxPres = int(propellant.getMaximumValidPressure())
        for pres in range(minPres, maxPres, 2000):
            burnrateData[0].append(pres)
            burnrateData[1].append(propellant.getBurnRate(pres))
        self.ui.tabBurnRate.showGraph(burnrateData)

        pressureData = [[], []]
        for kn in range(1, 750, 10):
            pressureData[0].append(kn)
            pressureData[1].append(propellant.getPressureFromKn(kn))
        self.ui.tabPressure.showGraph(pressureData)

    def cleanup(self):
        self.alerts = []
        self.ui.tabAlerts.clear()
        self.ui.tabBurnRate.cleanup()
        self.ui.tabPressure.cleanup()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, 'alerts'):
            self.ui.retranslateUi(self)
            update_alert_list(self.ui.tabAlerts, self.alerts)
        super().changeEvent(event)
