from motorlib.localization import QT_TRANSLATE_NOOP
import motorlib

from ..tool import Tool


class InitialKNTool(Tool):
    def __init__(self, manager):
        props = {'Kn': motorlib.properties.FloatProperty(QT_TRANSLATE_NOOP('MotorProperties', 'Kn'), '', 0, 1000)}
        super().__init__(manager,
                         QT_TRANSLATE_NOOP('Tools', 'Initial Kn'),
                         QT_TRANSLATE_NOOP('Tools', 'Use this tool to set the nozzle throat to achieve a specific Kn at startup.'),
                         props,
                         False)

    def applyChanges(self, inp, motor, simulation):
        for grain in motor.grains:
            grain.simulationSetup(self.preferences)
        surfArea = motor.calcBurningSurfaceArea([0 for grain in motor.grains])
        throatArea = surfArea / inp['Kn']
        motor.nozzle.props['throat'].setValue(motorlib.geometry.circleDiameterFromArea(throatArea))
        self.manager.updateMotor(motor)
