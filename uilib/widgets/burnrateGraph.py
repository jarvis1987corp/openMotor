from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from motorlib.units import convertAll
from PyQt6.QtCore import QCoreApplication, QEvent

class BurnrateGraph(FigureCanvas):
    def __init__(self):
        super(BurnrateGraph, self).__init__(Figure())
        self.setParent(None)
        self.preferences = None
        self._labelUnits = None

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.figure.tight_layout()

        self.plot = self.figure.add_subplot(111)

    def setPreferences(self, pref):
        self.preferences = pref

    def cleanup(self):
        self._labelUnits = None
        self.plot.clear()
        self.draw()

    def showGraph(self, points):
        presUnit = self.preferences.getUnit('Pa')
        rateUnit = self.preferences.getUnit('m/s')
        # I really don't like this, but it is necessary for this graph and the c* output to coexist
        if rateUnit == 'ft/s':
            rateUnit = 'in/s'
        if rateUnit == 'm/s':
            rateUnit = 'mm/s'

        self.plot.plot(convertAll(points[0], 'Pa', presUnit), convertAll(points[1], 'm/s', rateUnit))
        self._labelUnits = presUnit, rateUnit
        self.updateLabels()
        self.plot.grid(True)
        self.figure.subplots_adjust(top=0.95, bottom=0.25)
        self.draw()

    def updateLabels(self):
        if self._labelUnits is not None:
            presUnit, rateUnit = self._labelUnits
            self.plot.set_xlabel(QCoreApplication.translate('BurnrateGraph', 'Pressure - {}').format(presUnit))
            self.plot.set_ylabel(QCoreApplication.translate('BurnrateGraph', 'Burn Rate - {}').format(rateUnit))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, '_labelUnits'):
            self.updateLabels()
            self.draw_idle()
        super().changeEvent(event)
