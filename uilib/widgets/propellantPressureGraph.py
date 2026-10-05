from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from motorlib.units import convertAll
from PyQt6.QtCore import QCoreApplication, QEvent

class PropellantPressureGraph(FigureCanvas):
    def __init__(self):
        super(PropellantPressureGraph, self).__init__(Figure())
        self.setParent(None)
        self.preferences = None
        self._labelUnit = None

        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.figure.tight_layout()

        self.plot = self.figure.add_subplot(111)

    def setPreferences(self, pref):
        self.preferences = pref

    def cleanup(self):
        self._labelUnit = None
        self.plot.clear()
        self.draw()

    def showGraph(self, points):
        presUnit = self.preferences.getUnit('Pa')

        self.plot.plot(points[0], convertAll(points[1], 'Pa', presUnit))
        self.plot.set_xlabel('Kn')
        self._labelUnit = presUnit
        self.updateLabels()
        self.plot.grid(True)
        self.figure.subplots_adjust(top=0.95, bottom=0.25)
        self.draw()

    def updateLabels(self):
        if self._labelUnit is not None:
            self.plot.set_ylabel(QCoreApplication.translate('PropellantPressureGraph', 'Pressure - {}').format(self._labelUnit))

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, '_labelUnit'):
            self.updateLabels()
            self.draw_idle()
        super().changeEvent(event)
