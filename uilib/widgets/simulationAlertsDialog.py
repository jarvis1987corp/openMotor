from PyQt6.QtWidgets import QDialog, QHeaderView, QApplication
from PyQt6.QtCore import QEvent

from ..views.SimulationAlertsDialog_ui import Ui_SimAlertsDialog
from ..localization import update_alert_table

class SimulationAlertsDialog(QDialog):
    def __init__(self):
        QDialog.__init__(self)
        self.ui = Ui_SimAlertsDialog()
        self.ui.setupUi(self)
        self.alerts = []

        self.setWindowIcon(QApplication.instance().icon)

        header = self.ui.tableWidgetAlerts.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        self.hide()

    def displayAlerts(self, simRes):
        self.alerts = simRes.alerts
        self.ui.tableWidgetAlerts.setRowCount(0) # Clear the table
        if len(simRes.alerts) == 0:
            return

        update_alert_table(self.ui.tableWidgetAlerts, simRes.alerts)
        self.show()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, 'alerts'):
            self.ui.retranslateUi(self)
            update_alert_table(self.ui.tableWidgetAlerts, self.alerts)
        super().changeEvent(event)
