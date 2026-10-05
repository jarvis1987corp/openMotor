from motorlib.localization import QT_TRANSLATE_NOOP
import xml.etree.ElementTree as ET

import motorlib
from motorlib.constants import gasConstant, standardGravity
from PyQt6.QtCore import QCoreApplication
from ..localization import geometry_name

from ..converter import Importer

# BS type -> oM class for all grains we can import
SUPPORTED_GRAINS = {
    '1': motorlib.grains.BatesGrain,
    '2': motorlib.grains.DGrain,
    '3': motorlib.grains.MoonBurner,
    '5': motorlib.grains.CGrain,
    '6': motorlib.grains.XCore,
    '7': motorlib.grains.Finocyl
}

# BS type -> label for grains we know about but can't import
UNSUPPORTED_GRAINS = {
    '4': 'Star',
    '8': 'Tablet',
    '9': 'Pie Segment'
}

def inToM(value):
    """Converts a string containing a value in inches to a float of meters"""
    return motorlib.units.convert(float(value), 'in', 'm')

def importPropellant(node):
    errors = ''
    propellant = motorlib.propellant.Propellant()
    propTab = motorlib.propellant.PropellantTab()
    propellant.setProperty('name', node.attrib['Name'])
    ballN = float(node.attrib['BallisticN'])
    ballA = float(node.attrib['BallisticA']) * 1/(6895**ballN)
    propTab.setProperty('n', ballN)
    # Conversion only does in/s to m/s, the rest is handled above
    ballA = motorlib.units.convert(ballA, 'in/(s*psi^n)', 'm/(s*Pa^n)')
    propTab.setProperty('a', ballA)
    density = motorlib.units.convert(float(node.attrib['Density']), 'lb/in^3', 'kg/m^3')
    propellant.setProperty('density', density)
    gamma = float(node.attrib['SpecificHeatRatio'])
    propTab.setProperty('k', gamma)
    impMolarMass = node.attrib['MolarMass']
    # If the user didn't set molar mass, it'll come through as 0. If this happens, use a sensible default
    if impMolarMass == '0':
        molarMass = 23.67
        errors = QCoreApplication.translate('BurnSimImporter', "Propellant didn't specify molar mass, using default.\n")
    else:
        molarMass = float(impMolarMass)
    propTab.setProperty('m', molarMass)
    # Burnsim doesn't provide temperature (always 0), but we can back it out using things they do provide
    cstar = float(node.attrib['ISPStar']) * standardGravity
    temperature = (cstar ** 2) * gamma * ((2 / (gamma + 1))**((gamma + 1) / (gamma - 1))) / gasConstant * molarMass
    propTab.setProperty('t', temperature)

    propTab.setProperty('minPressure', 0)
    propTab.setProperty('maxPressure', 6.895e+06)
    propellant.setProperty('tabs', [propTab.getProperties()])
    return propellant, errors

class BurnSimImporter(Importer):
    def __init__(self, manager):
        super().__init__(manager, QT_TRANSLATE_NOOP('Converters', 'BurnSim File'), QT_TRANSLATE_NOOP('Converters', 'Loads motor files for BurnSim 3.0'), {'.bsx': QT_TRANSLATE_NOOP('Converters', 'BurnSim Files')})

    def doConversion(self, path):
        motor = motorlib.motor.Motor()
        motor.config.setProperties(self.manager.preferences.general.getProperties())
        tree = ET.parse(path)
        root = tree.getroot()
        errors = ''
        propSet = False
        if root.find('Grain') is None:
            errors += self.tr("Motor contains no grains, but the propellant and nozzle can still be imported.\n")
        for child in root:
            if child.tag == 'Nozzle':
                motor.nozzle.setProperty('throat', inToM(child.attrib['ThroatDia']))
                motor.nozzle.setProperty('exit', inToM(child.attrib['ExitDia']))
                motor.nozzle.setProperty('efficiency', float(child.attrib['NozzleEfficiency']) / 100)
                motor.nozzle.setProperty('divAngle', 15)
                motor.nozzle.setProperty('convAngle', 45)
                errors += self.tr('Nozzle angles not specified, assumed to be 15° and 45°.\n')
            if child.tag == 'Grain':
                if child.attrib['Type'] in SUPPORTED_GRAINS:
                    motor.grains.append(SUPPORTED_GRAINS[child.attrib['Type']]())
                    motor.grains[-1].setProperty('diameter', inToM(child.attrib['Diameter']))
                    motor.grains[-1].setProperty('length', inToM(child.attrib['Length']))

                    grainType = child.attrib['Type']

                    if child.attrib['EndsInhibited'] == '1':
                        motor.grains[-1].setProperty('inhibitedEnds', 'Top')
                    elif child.attrib['EndsInhibited'] == '2':
                        motor.grains[-1].setProperty('inhibitedEnds', 'Both')

                    if grainType in ('1', '3', '7'): # Grains with core diameter
                        motor.grains[-1].setProperty('coreDiameter', inToM(child.attrib['CoreDiameter']))

                    if grainType == '2': # D grain specific properties
                        motor.grains[-1].setProperty('slotOffset', inToM(child.attrib['EdgeOffset']))

                    elif grainType == '3': # Moonburner specific properties
                        motor.grains[-1].setProperty('coreOffset', inToM(child.attrib['CoreOffset']))

                    elif grainType == '5': # C grain specific properties
                        motor.grains[-1].setProperty('slotWidth', inToM(child.attrib['SlotWidth']))
                        radius = motor.grains[-1].getProperty('diameter') / 2
                        motor.grains[-1].setProperty('slotOffset', radius - inToM(child.attrib['SlotDepth']))

                    elif grainType == '6': # X core specific properties
                        motor.grains[-1].setProperty('slotWidth', inToM(child.attrib['SlotWidth']))
                        motor.grains[-1].setProperty('slotLength', inToM(child.attrib['CoreDiameter']) / 2)

                    elif grainType == '7': # Finocyl specific properties
                        motor.grains[-1].setProperty('finWidth', inToM(child.attrib['FinWidth']))
                        motor.grains[-1].setProperty('finLength', inToM(child.attrib['FinLength']))
                        motor.grains[-1].setProperty('numFins', int(child.attrib['FinCount']))

                    if not propSet: # Use propellant numbers from the forward grain
                        motor.propellant, propellantErrors = importPropellant(child.find('Propellant'))
                        if propellantErrors != '':
                            errors += propellantErrors
                        propSet = True

                else:
                    if child.attrib['Type'] in UNSUPPORTED_GRAINS:
                        errors += self.tr("File contains a {} grain, which can't be imported.\n").format(geometry_name(UNSUPPORTED_GRAINS[child.attrib['Type']]))
                    else:
                        errors += self.tr("File contains an unknown grain of type {}.\n").format(child.attrib['Type'])

            if child.tag == 'TestData':
                errors += self.tr("\nFile contains test data, which is not imported.")

            if child.tag == "Propellant":
                if not propSet:
                    motor.propellant, propellantErrors = importPropellant(child)
                    if propellantErrors != '':
                        errors += propellantErrors
                    propSet = True

        if errors != '':
            self.manager.app.outputMessage(errors + self.tr('\nThe rest of the motor will be imported.'))

        self.manager.startFromMotor(motor)
