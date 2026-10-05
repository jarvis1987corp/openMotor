from motorlib.localization import QT_TRANSLATE_NOOP
import motorlib

from ..tool import Tool
from motorlib.constants import maximumRefDiameter

class ChangeDiameterTool(Tool):
    def __init__(self, manager):
        props = {'diameter': motorlib.properties.FloatProperty(QT_TRANSLATE_NOOP('MotorProperties', 'Diameter'), 'm', 0, maximumRefDiameter)}
        super().__init__(manager,
                         QT_TRANSLATE_NOOP('Tools', 'Motor Diameter'),
                         QT_TRANSLATE_NOOP('Tools', 'Use this tool to set the diameter of all grains in the motor.'),
                         props,
                         False)

    def applyChanges(self, inp, motor, simulation):
        for grain in motor.grains:
            grain.setProperties({'diameter': inp['diameter']})
        self.manager.updateMotor(motor)
