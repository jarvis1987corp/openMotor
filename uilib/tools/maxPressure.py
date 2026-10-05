from motorlib.localization import QT_TRANSLATE_NOOP
import motorlib

from ..tool import Tool


class MaxPressureTool(Tool):
    def __init__(self, manager):
        props = {'pressure': motorlib.properties.FloatProperty(QT_TRANSLATE_NOOP('MotorProperties', 'Pressure'), 'Pa', 0, 7e7)}
        super().__init__(manager,
                         QT_TRANSLATE_NOOP('Tools', 'Max Pressure'),
                         QT_TRANSLATE_NOOP('Tools', 'Use this tool to set the nozzle throat to keep the chamber pressure below a certain value during the burn.'),
                         props,
                         True)

    def applyChanges(self, inp, motor, simulation):
        kn = motor.propellant.getKnFromPressure(inp['pressure'])
        surfArea = simulation.getPeakKN() * motorlib.geometry.circleArea(motor.nozzle.props['throat'].getValue())
        throatArea = surfArea / kn
        motor.nozzle.props['throat'].setValue(motorlib.geometry.circleDiameterFromArea(throatArea))
        self.manager.updateMotor(motor)
