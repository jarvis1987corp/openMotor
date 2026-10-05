from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PyQt6.QtCore import QCoreApplication, QEvent
from ..localization import display_text

def selectGrains(data, grains):
    # Returns the data corresponding to specific grains from data structured like [[G1, G2], [G1, G2], [G1, G2]...]
    out = []
    for frame in data:
        out.append([])
        for grain in grains:
            out[-1].append(frame[grain])
    return out

class GraphWidget(FigureCanvas):
    def __init__(self, parent):
        super(GraphWidget, self).__init__(Figure())
        self.setParent(None)
        self.setupPlot()
        self.preferences = None
        self._labelData = None

    def setPreferences(self, pref):
        self.preferences = pref

    def setupPlot(self):
        self.figure = Figure()
        self.canvas = FigureCanvas(self.figure)
        self.plot = self.figure.add_subplot(111)
        self.figure.tight_layout()

    def plotData(self, simResult, xChannel, yChannels, grains):
        self.plot.clear()
        self._labelData = (simResult, xChannel, list(yChannels), list(grains))

        xAxisUnit = self.preferences.getUnit(simResult.channels[xChannel].unit)

        if simResult.channels[xChannel].valueType in (list, tuple):
            if len(grains) > 0:
                xData = selectGrains(simResult.channels[xChannel].getData(xAxisUnit), grains)
            else:
                return
        else:
            xData = simResult.channels[xChannel].getData(xAxisUnit)

        for channelName in yChannels:
            channel = simResult.channels[channelName]
            yUnit = self.preferences.getUnit(channel.unit)
            if channel.valueType in (list, tuple) and len(grains) > 0:
                yData = selectGrains(channel.getData(yUnit), grains)
                self.plot.plot(xData, yData)
            elif channel.valueType in (int, float):
                self.plot.plot(xData, channel.getData(yUnit))
        self.updateLabels()
        self.plot.grid(True)

    def updateLabels(self):
        if self._labelData is None:
            return
        simResult, xChannel, yChannels, grains = self._labelData
        xAxisUnit = self.preferences.getUnit(simResult.channels[xChannel].unit)
        legend = []
        for channelName in yChannels:
            channel = simResult.channels[channelName]
            name = display_text(channel.name)
            yUnit = self.preferences.getUnit(channel.unit)
            if channel.valueType in (int, float):
                if yUnit != '':
                    legend.append('{} - {}'.format(name, yUnit))
                else:
                    legend.append(name)
            elif channel.valueType in (list, tuple):
                for i in range(len(channel.data[0])):
                    if i in grains:
                        if yUnit != '':
                            legend.append(QCoreApplication.translate('GraphWidget', '{} - Grain {} - {}').format(name, i + 1, yUnit))
                        else:
                            legend.append(QCoreApplication.translate('GraphWidget', '{} - Grain {}').format(name, i + 1))
        self.plot.legend(legend)
        self.plot.set_xlabel('{} - {}'.format(display_text(simResult.channels[xChannel].name), xAxisUnit))
        self.figure.tight_layout()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange and hasattr(self, '_labelData'):
            self.updateLabels()
            self.draw_idle()
        super().changeEvent(event)

    def saveImage(self, simResult, xChannel, yChannels, grains, path):
        # Export a separate figure so subsequent language changes retain the UI
        # plot, its selected channels and zoom. This uses already computed data.
        original = self.figure, self.plot, self._labelData
        try:
            self.figure = Figure()
            self.plot = self.figure.add_subplot(111)
            self.plotData(simResult, xChannel, yChannels, grains)
            self.plot.set_title(simResult.getFullDesignation())
            self.figure.savefig(path, bbox_inches="tight")
        finally:
            self.figure, self.plot, self._labelData = original

    def showData(self, simResult, xChannel, yChannels, grains):
        self.plotData(simResult, xChannel, yChannels, grains)
        self.draw()

    def resetPlot(self):
        self._labelData = None
        self.plot.clear()
        self.draw()
