"""Exercise Qt catalogs and preferences without touching the user's data directory."""

# UI imports must follow isolated directory setup, before the logger is loaded.
# ruff: noqa: E402

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import numpy as np

# Set these before importing the logger or constructing any widgets.
_data = tempfile.TemporaryDirectory(prefix="openmotor-localization-")
_environment = {name: os.environ.get(name) for name in (
    "QT_QPA_PLATFORM", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "MPLCONFIGDIR",
)}
os.environ["QT_QPA_PLATFORM"] = "offscreen"
for _name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "MPLCONFIGDIR"):
    os.environ[_name] = _data.name

# Windows platformdirs ignores XDG variables. Isolate both platforms explicitly.
_directory_patches = [
    patch("platformdirs.user_data_dir", return_value=str(Path(_data.name) / "openMotor")),
    patch("platformdirs.user_log_dir", return_value=str(Path(_data.name) / "logs")),
]
for _directory_patch in _directory_patches:
    _directory_patch.start()

# Select the repository backend before app.py imports pyplot in a headless run.
import uilib  # noqa: F401 -- initializes the matplotlib backend before app.py

# isort: split
from PyQt6.QtCore import QCoreApplication, QLocale
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtWidgets import QDialogButtonBox, QMessageBox

from app import App
from motorlib.grains import BatesGrain, grainTypes
from motorlib.localization import QT_TRANSLATE_NOOP, DisplayText
from motorlib.motor import Motor
from motorlib.nozzle import Nozzle
from motorlib.propellant import Propellant, PropellantTab
from motorlib.properties import EnumProperty
from motorlib.simResult import SimulationResult
from scripts.translations import check_catalogs
from uilib.converters import BurnSimExporter, BurnSimImporter, CsvExporter, EngExporter
from uilib.converters.engExporter import EngSettings
from uilib.defaults import DEFAULT_PREFERENCES
from uilib.fileIO import fileTypes, loadFile, saveFile
from uilib.localization import LANGUAGES, TRANSLATIONS_PATH, TranslationManager, display_text, geometry_name
from uilib.preferencesManager import Preferences, PreferencesManager
from uilib.widgets.collectionEditor import CollectionEditor
from uilib.widgets.grainPreviewWidget import GrainPreviewWidget
from uilib.widgets.nozzlePreviewWidget import NozzlePreviewWidget
from uilib.widgets.propellantPreviewWidget import PropellantPreviewWidget
from uilib.widgets.propellantTabEditor import PropellantTabEditor
from uilib.widgets.propertyEditor import PropertyEditor
from uilib.widgets.tabularEditor import TabularEditor

ROOT = Path(__file__).resolve().parents[2]
APP = None


def setUpModule():
    global APP
    APP = App([str(ROOT / "main.py")])


def tearDownModule():
    APP.translationManager.setLanguage("en")
    APP.processEvents()
    # Do not invoke Window.closeEvent, which exits the process or prompts to save.
    APP.window.hide()
    APP.preferencesManager.menu.hide()
    APP.window.aboutDialog.hide()
    for directory_patch in reversed(_directory_patches):
        directory_patch.stop()
    for name, value in _environment.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    # Windows cannot delete an open log file inside the temporary directory.
    from uilib.logger import logger
    logger._file.close()
    logger._file = None
    _data.cleanup()


class LocalizationTests(unittest.TestCase):
    @classmethod
    def reference_result(cls):
        if not hasattr(cls, "_result"):
            motor = Motor(loadFile(ROOT / "test/data/regression/simple/motor.ric", fileTypes.MOTOR))
            cls._result = motor.runSimulation()
        return cls._result

    def setUp(self):
        APP.translationManager.setLanguage("en")
        APP.processEvents()

    def tearDown(self):
        APP.translationManager.setLanguage("en")
        APP.processEvents()

    def select_language(self, language):
        self.assertTrue(APP.translationManager.setLanguage(language))
        APP.processEvents()

    def test_english_by_default(self):
        self.assertEqual(Preferences().language, "en")
        self.assertEqual(Preferences(DEFAULT_PREFERENCES).language, "en")
        self.assertEqual(APP.translationManager.language, "en")
        self.assertEqual(APP.window.ui.menuFile.title(), "File")
        self.assertEqual(APP.preferencesManager.menu.windowTitle(), "Preferences")

    def test_images_load_outside_repository_working_directory(self):
        from PyQt6.QtGui import QIcon, QPixmap
        from uilib.resources import resource_path

        original = os.getcwd()
        with tempfile.TemporaryDirectory(prefix="openmotor-изображения-") as directory:
            try:
                os.chdir(directory)
                self.assertFalse(QIcon(resource_path("oMIconCyclesSmall.png")).isNull())
                self.assertFalse(QPixmap(resource_path("oMIconCyclesSmall.png")).isNull())
                self.assertFalse(APP.icon.isNull())
                self.assertFalse(APP.window.aboutDialog.ui.labelImage.pixmap().isNull())
            finally:
                # Restore cwd before cleanup so Windows can remove this folder.
                os.chdir(original)

    def test_switch_languages_for_existing_and_new_widgets(self):
        window = APP.window
        menu = APP.preferencesManager.menu
        about = window.aboutDialog
        for code, file_title, pref_title, about_title, cancel in (
            ("ru", "Файл", "Настройки", "Об openMotor", "Отмена"),
            ("en", "File", "Preferences", "About openMotor", "Cancel"),
        ):
            self.select_language(code)
            self.assertEqual(window.ui.menuFile.title(), file_title)
            self.assertEqual(menu.windowTitle(), pref_title)
            self.assertEqual(about.windowTitle(), about_title)
            self.assertIn(window.appVersionStr, about.ui.labelText.text())
            self.assertNotIn("###", about.ui.labelText.text())
            self.assertEqual(menu.ui.buttonBox.button(QDialogButtonBox.StandardButton.Cancel).text(), cancel)
            dialog = QMessageBox()
            dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
            self.assertEqual(dialog.button(QMessageBox.StandardButton.Cancel).text(), cancel)

    def test_menu_disambiguation_and_basic_buttons(self):
        self.select_language("ru")
        ui = APP.window.ui
        self.assertEqual(ui.menuEdit.title(), "Правка")
        self.assertEqual(ui.pushButtonEditGrain.text(), "Изменить")
        self.assertEqual(ui.actionSave.text(), "Сохранить")
        self.assertEqual(ui.actionPreferences.text(), "Настройки")
        self.assertEqual(ui.pushButtonAddGrain.text(), "Добавить шашку")
        self.assertEqual(ui.actionSave.shortcut().toString(), "Ctrl+S")
        self.assertEqual(APP.window.ui.motorEditor.applyButton.text(), "Применить")
        self.assertEqual(APP.window.ui.motorEditor.cancelButton.text(), "Отмена")

    def test_unknown_language_and_missing_catalog_fall_back(self):
        for invalid in ("de", "Русский", None, 123, ["ru"]):
            values = copy.deepcopy(DEFAULT_PREFERENCES)
            values["language"] = invalid
            self.assertEqual(Preferences(values).language, "en")
        with tempfile.TemporaryDirectory() as directory:
            manager = TranslationManager(APP, directory)
            with self.assertLogs("uilib.localization", level="WARNING"):
                self.assertFalse(manager.setLanguage("ru"))
            self.assertEqual(manager.language, "en")
            manager.deleteLater()

    def test_language_does_not_change_locale_or_units(self):
        locale = QLocale().name()
        preferences = Preferences(DEFAULT_PREFERENCES)
        units = preferences.getDict()["units"]
        self.select_language("ru")
        self.assertEqual(QLocale().name(), locale)
        self.assertEqual(preferences.getDict()["units"], units)
        self.assertEqual(preferences.getUnit("Pa"), "psi")

    def test_save_and_reload_stable_language_code(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = directory + os.sep
            with patch("uilib.preferencesManager.getConfigPath", return_value=config_path):
                manager = PreferencesManager(makeMenu=False)
                for language in ("ru", "en"):
                    values = manager.preferences.getDict()
                    values["language"] = language
                    manager.newPreferences(values)
                    saved = loadFile(Path(directory) / "preferences.yaml", fileTypes.PREFERENCES)
                    self.assertEqual(saved["language"], language)
                    restored = PreferencesManager(makeMenu=False)
                    self.assertEqual(restored.preferences.language, language)
                    self.assertEqual(saved["general"], manager.preferences.getDict()["general"])
                    self.assertEqual(saved["units"], manager.preferences.getDict()["units"])

    def test_old_preferences_without_language(self):
        old = Preferences(DEFAULT_PREFERENCES).getDict()
        del old["language"]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.yaml"
            saveFile(path, old, fileTypes.PREFERENCES)
            with patch("uilib.preferencesManager.getConfigPath", return_value=directory + os.sep):
                restored = PreferencesManager(makeMenu=False)
                self.assertEqual(restored.preferences.language, "en")
                self.assertEqual(restored.preferences.getDict()["general"], old["general"])
                self.assertEqual(restored.preferences.getDict()["units"], old["units"])
                # Loading alone does not rewrite the old file.
                self.assertNotIn("language", loadFile(path, fileTypes.PREFERENCES))

    def test_preferences_choice_uses_item_data_and_cancel_does_not_save(self):
        manager = APP.preferencesManager
        manager.preferences.language = "en"
        menu = manager.menu
        menu.load(manager.preferences)
        combo = menu.ui.comboBoxLanguage
        self.assertEqual([(combo.itemData(i), combo.itemText(i)) for i in range(combo.count())], list(LANGUAGES))
        combo.setCurrentIndex(combo.findData("ru"))
        spy = QSignalSpy(menu.preferencesApplied)
        with patch.object(manager, "savePreferences") as save:
            menu.cancel()
            self.assertEqual(len(spy), 0)
            self.assertEqual(manager.preferences.language, "en")
            save.assert_not_called()
        menu.load(manager.preferences)
        self.assertEqual(combo.currentData(), "en")

    def test_language_only_apply_preserves_settings_and_results(self):
        manager = APP.preferencesManager
        manager.preferences.language = "en"
        before = manager.preferences.getDict()
        menu = manager.menu
        menu.load(manager.preferences)
        APP.window.ui.labelImpulse.setText("123.45 Ns")
        spy = QSignalSpy(manager.preferencesChanged)
        combo = menu.ui.comboBoxLanguage
        combo.setCurrentIndex(combo.findData("ru"))
        original_label = combo.currentText()
        # The displayed label is arbitrary; only itemData is saved.
        combo.setItemText(combo.currentIndex(), "Russian display label")
        try:
            with patch.object(manager, "savePreferences"):
                menu.apply()
            APP.processEvents()
            self.assertEqual(manager.preferences.language, "ru")
            self.assertEqual(APP.translationManager.language, "ru")
            self.assertEqual(len(spy), 0)
            self.assertEqual(manager.preferences.getDict()["general"], before["general"])
            self.assertEqual(manager.preferences.getDict()["units"], before["units"])
            self.assertEqual(APP.window.ui.labelImpulse.text(), "123.45 Ns")
        finally:
            combo.setItemText(combo.findData("ru"), original_label)
            manager.preferences.applyDict(before)

    def test_switch_preserves_unsaved_editor_values_and_window_title(self):
        menu = APP.preferencesManager.menu
        menu.load(APP.preferencesManager.preferences)
        editor = menu.ui.settingsEditorGeneral.propertyEditors["timestep"].editor
        editor.setValue(0.04)
        APP.window.setWindowTitle("openMotor - sample.ric*")
        APP.window.ui.labelBurnTime.setText("4.56 s")
        combo = APP.window.ui.comboBoxGrainGeometry
        combo.setCurrentIndex(combo.findData("BATES"))
        self.select_language("ru")
        self.assertEqual(editor.value(), 0.04)
        self.assertEqual(APP.window.windowTitle(), "openMotor - sample.ric*")
        self.assertEqual(APP.window.ui.labelBurnTime.text(), "4.56 s")
        self.assertEqual(combo.currentData(), "BATES")

    def test_enum_values_are_independent_of_display_labels(self):
        prop = EnumProperty("Inhibited ends", ["Neither", "Top", "Bottom", "Both"])
        prop.setValue("Both")
        editor = PropertyEditor(APP.window, prop, None)
        editor.editor.setItemText(editor.editor.currentIndex(), "Оба")
        self.assertEqual(editor.getValue(), "Both")
        editor.editor.setCurrentIndex(editor.editor.findData("Neither"))
        editor.editor.setItemText(editor.editor.currentIndex(), "Ни один")
        self.assertEqual(editor.getValue(), "Neither")
        editor.deleteLater()

    def test_grain_creation_uses_stable_identity(self):
        combo = APP.window.ui.comboBoxGrainGeometry
        index = combo.findData("BATES")
        original = combo.itemText(index)
        combo.setCurrentIndex(index)
        combo.setItemText(index, "Шашка BATES")
        history = copy.deepcopy(APP.fileManager.fileHistory)
        current = APP.fileManager.currentVersion
        try:
            APP.window.addGrain()
            self.assertIsInstance(APP.fileManager.getCurrentMotor().grains[-1], BatesGrain)
            self.assertEqual(APP.fileManager.getCurrentMotor().getDict()["grains"][-1]["type"], "BATES")
        finally:
            combo.setItemText(index, original)
            APP.fileManager.fileHistory = history
            APP.fileManager.currentVersion = current
            APP.window.ui.motorEditor.cleanup()
            APP.window.updateGrainTable()

    def test_file_dialogs_and_unsaved_prompt(self):
        self.select_language("ru")
        manager = APP.fileManager
        with patch("uilib.fileManager.QFileDialog.getSaveFileName", return_value=("sample", "")) as dialog:
            self.assertEqual(manager.showSaveDialog(), "sample.ric")
            self.assertEqual(dialog.call_args.args[1], "Сохранить двигатель")
            self.assertEqual(dialog.call_args.args[3], "Файлы двигателей (*.ric)")
        with patch("uilib.fileManager.QFileDialog.getOpenFileName", return_value=("", "")) as dialog:
            with patch.object(manager, "unsavedCheck", return_value=True):
                self.assertFalse(manager.load())
            self.assertEqual(dialog.call_args.args[1], "Открыть двигатель")
        original = manager.currentVersion
        manager.currentVersion = manager.savedVersion + 1
        observed = []

        def cancel(dialog):
            observed.append((dialog.windowTitle(), dialog.text()))
            return QMessageBox.StandardButton.Cancel

        try:
            with patch.object(QMessageBox, "exec", cancel):
                self.assertFalse(manager.unsavedCheck())
            self.assertEqual(observed[0][0], "Закрыть без сохранения?")
            self.assertIn("несохранённые изменения", observed[0][1])
        finally:
            manager.currentVersion = original
        self.assertEqual(manager.recentlyOpenedMenu.actions()[0].text(), "Нет недавних файлов")

    def test_simulation_and_project_formats_are_unchanged(self):
        data = loadFile(ROOT / "test/data/regression/simple/motor.ric", fileTypes.MOTOR)
        snapshots = []
        for language in ("en", "ru", "en"):
            self.select_language(language)
            motor = Motor(copy.deepcopy(data))
            before = motor.getDict()
            result = motor.runSimulation()
            self.assertTrue(result.success)
            self.assertGreater(result.getImpulse(), 0)
            self.assertGreater(result.getBurnTime(), 0)
            self.assertEqual(motor.getDict(), before)
            snapshots.append((result, result.getCSV(Preferences(DEFAULT_PREFERENCES))))
        baseline, csv = snapshots[0]
        for result, output in snapshots[1:]:
            self.assertEqual(output, csv)
            self.assertEqual([(a.level, a.type, a.location, a.description) for a in result.alerts],
                             [(a.level, a.type, a.location, a.description) for a in baseline.alerts])
            for name, channel in baseline.channels.items():
                np.testing.assert_array_equal(result.channels[name].data, channel.data)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "motor.ric"
            saveFile(path, motor.getDict(), fileTypes.MOTOR)
            self.assertEqual(Motor(loadFile(path, fileTypes.MOTOR)).getDict(), motor.getDict())

    def test_saved_language_is_applied_before_ui_construction(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "openMotor"
            data_dir.mkdir()
            values = Preferences(DEFAULT_PREFERENCES).getDict()
            values["language"] = "ru"
            saveFile(data_dir / "preferences.yaml", values, fileTypes.PREFERENCES)
            environment = os.environ.copy()
            for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "MPLCONFIGDIR"):
                environment[name] = directory
            script = (
                "import platformdirs; "
                f"platformdirs.user_data_dir = lambda *a, **k: {str(data_dir)!r}; "
                f"platformdirs.user_log_dir = lambda *a, **k: {str(Path(directory) / 'logs')!r}; "
                "import uilib; from app import App; app = App(['main.py']); "
                "assert app.translationManager.language == 'ru'; "
                "assert app.window.ui.menuFile.title() == 'Файл'; "
                "assert app.preferencesManager.menu.windowTitle() == 'Настройки'; "
                "assert app.window.aboutDialog.windowTitle() == 'Об openMotor'"
            )
            result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=environment,
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_catalog_is_complete_and_preserves_placeholders(self):
        root = ET.parse(TRANSLATIONS_PATH / "openmotor_ru.ts").getroot()
        self.assertEqual(root.attrib["language"], "ru_RU")
        messages = root.findall("context/message")
        finished = [m for m in messages if m.find("translation").get("type") != "unfinished"]
        self.assertGreater(len(finished), 400)
        self.assertEqual(len(finished), len(messages))
        summary = check_catalogs()[0]
        self.assertEqual(summary["messages"], len(messages))
        self.assertEqual(summary["unfinished"], 0)
        self.assertEqual(summary["obsolete"], 0)
        self.assertTrue((TRANSLATIONS_PATH / "openmotor_ru.qm").is_file())
        self.select_language("ru")
        self.assertEqual(QCoreApplication.translate("MainWindow", "Burn Time:"), "Время горения:")
        for message in finished:
            source = message.findtext("source")
            translated = message.findtext("translation")
            if "*.ric" in source:
                self.assertIn("*.ric", translated)
            if "###" in source:
                self.assertIn("###", translated)
                self.assertIn("https://github.com/reilleya/openMotor", translated)

    def test_compiled_catalog_matches_every_source_message(self):
        self.select_language("ru")
        for context in ET.parse(TRANSLATIONS_PATH / "openmotor_ru.ts").getroot().findall("context"):
            for message in context.findall("message"):
                source = message.findtext("source")
                with self.subTest(context=context.findtext("name"), source=source):
                    self.assertEqual(QCoreApplication.translate(context.findtext("name"), source,
                                                               message.findtext("comment")),
                                     message.findtext("translation"))

    def test_catalog_matches_fresh_extraction_including_all_forms(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "extracted.ts"
            command = [sys.executable, "-c", "from PyQt6.lupdate.pylupdate import main; main()",
                       "app.py", "uilib", "motorlib", "mathlib", "--exclude", "*_ui.py",
                       "--no-obsolete", "--no-summary", "--ts", str(target)]
            subprocess.run(command, cwd=ROOT, check=True, capture_output=True, timeout=30)

            def identities(path):
                return {(context.findtext("name"), message.findtext("source"), message.findtext("comment"))
                        for context in ET.parse(path).getroot().findall("context")
                        for message in context.findall("message")}

            self.assertEqual(identities(target), identities(TRANSLATIONS_PATH / "openmotor_ru.ts"))
            contexts = {context for context, _, _ in identities(target)}
            for form in (ROOT / "uilib/views/forms").glob("*.ui"):
                self.assertIn(ET.parse(form).getroot().findtext("class"), contexts)

    def test_all_property_labels_translate_without_changing_values(self):
        motor = self.reference_result().motor
        preferences = Preferences(DEFAULT_PREFERENCES)
        objects = [motor.nozzle, motor.config, motor.propellant, PropellantTab(), EngSettings(),
                   preferences.general, preferences.units, *(constructor() for constructor in grainTypes.values())]
        editors = []
        try:
            for obj in objects:
                editor = CollectionEditor(APP.window)
                editor.setPreferences(preferences)
                editor.loadProperties(obj)
                before = editor.getProperties()
                spies = [QSignalSpy(prop.valueChanged) for prop in editor.propertyEditors.values()]
                for prop in obj.props.values():
                    self.assertIsInstance(prop.dispName, DisplayText)
                editors.append((editor, before, spies))
            for language in ("ru", "en"):
                self.select_language(language)
                for editor, values, spies in editors:
                    self.assertEqual(editor.getProperties(), values)
                    self.assertTrue(all(len(spy) == 0 for spy in spies))
                    for key, label in editor.propertyLabels.items():
                        source = editor.propertyEditors[key].prop.dispName
                        self.assertEqual(label.text(), display_text(source) + ":")
                        if language == "ru" and source != "Kn":
                            self.assertNotEqual(display_text(source), str(source))
        finally:
            for editor, _, _ in editors:
                editor.cleanup()
                editor.deleteLater()

    def test_all_geometry_choices_keep_stable_identities(self):
        combo = APP.window.ui.comboBoxGrainGeometry
        stable = [combo.itemData(index) for index in range(combo.count())]
        self.assertEqual(stable, list(grainTypes))
        for language in ("ru", "en"):
            self.select_language(language)
            for index, identity in enumerate(stable):
                self.assertEqual(combo.itemData(index), identity)
                self.assertEqual(combo.itemText(index), geometry_name(identity))
                self.assertEqual(grainTypes[identity]().geomName, identity)
                if language == "ru" and identity not in ("BATES", "Finocyl"):
                    self.assertNotEqual(combo.itemText(index), identity)

    def test_tool_menus_dialogs_and_values_update_without_running_tools(self):
        manager = APP.toolManager
        tools = [tool for group in manager.tools.values() for tool in group]
        snapshots = []
        try:
            for tool in tools:
                tool.editor.loadProperties(tool.propCollection)
                snapshots.append(tool.editor.getProperties())
            spy = QSignalSpy(manager.changeApplied)
            with patch.object(manager, "requestSimulation") as request:
                for language in ("ru", "en"):
                    self.select_language(language)
                    for tool, values in zip(tools, snapshots):
                        self.assertEqual(tool.windowTitle(), display_text(tool.name))
                        self.assertEqual(tool.descLabel.text(), display_text(tool.description))
                        self.assertEqual(tool.editor.getProperties(), values)
                    for action, tool in manager.menuActions:
                        self.assertEqual(action.text(), display_text(tool.name))
                        self.assertEqual(action.statusTip(), display_text(tool.description))
                    self.assertEqual(manager.menuCategories[0][0].title(), "Задать" if language == "ru" else "Set")
                request.assert_not_called()
                self.assertEqual(len(spy), 0)
        finally:
            for tool in tools:
                tool.editor.cleanup()

    def test_exporter_enum_data_dialogs_and_file_filters(self):
        settings = EngSettings()
        settings.setProperty("append", "Overwrite")
        editor = PropertyEditor(APP.window, settings.props["append"], None)
        spy = QSignalSpy(editor.valueChanged)
        try:
            self.select_language("ru")
            self.assertEqual(editor.editor.currentText(), "Перезаписать")
            self.assertEqual(editor.getValue(), "Overwrite")
            for converter in APP.importExportManager.conversions:
                for extension in converter.fileTypes:
                    self.assertIn("(*" + extension + ")", converter.getFileTypeString())
                if converter.menu is not None:
                    self.assertNotIn("Export", converter.menu.windowTitle())
            exporter = next(c for c in APP.importExportManager.conversions if isinstance(c, EngExporter))
            with patch("uilib.converter.QFileDialog.getSaveFileName", return_value=("sample", "")) as dialog:
                self.assertEqual(exporter.showFileSelector(), "sample.eng")
                self.assertEqual(dialog.call_args.args[1], "Экспорт Файл ENG")
                self.assertEqual(dialog.call_args.args[3], "Файлы RASP (*.eng)")
            self.select_language("en")
            self.assertEqual(editor.editor.currentText(), "Overwrite")
            self.assertEqual(editor.getValue(), "Overwrite")
            self.assertEqual(len(spy), 0)
        finally:
            editor.deleteLater()

    def test_cached_dynamic_alerts_retranslate_templates_with_numbers(self):
        propellant = Propellant({"tabs": [{"minPressure": 123, "maxPressure": 123}]})
        alerts = propellant.getErrors()
        self.assertEqual(str(alerts[0].description), "Tab #1 has the same minimum and maximum pressures.")
        result = SimulationResult(Motor())
        result.alerts = alerts
        dialog = APP.simulationManager.alertsDialog
        dialog.displayAlerts(result)
        try:
            with patch.object(propellant, "getErrors", side_effect=AssertionError("Recomputed diagnostics")):
                for language, description in (("ru", "В диапазоне №1 минимальное и максимальное давления совпадают."),
                                              ("en", "Tab #1 has the same minimum and maximum pressures.")):
                    self.select_language(language)
                    table = dialog.ui.tableWidgetAlerts
                    self.assertEqual(table.item(0, 3).text(), description)
                    self.assertEqual(table.item(0, 3).toolTip(), description)
                    self.assertEqual(table.item(0, 0).text(), "Ошибка" if language == "ru" else "Error")
                    self.assertEqual(table.item(0, 2).text(), "Топливо" if language == "ru" else "Propellant")
            self.assertEqual(str(alerts[0].description), "Tab #1 has the same minimum and maximum pressures.")
        finally:
            dialog.alerts = []
            dialog.hide()

    def test_preview_warnings_update_without_regenerating_geometry(self):
        grain = BatesGrain()
        nozzle = Nozzle()
        propellant = Propellant({"tabs": [{"minPressure": 1, "maxPressure": 1}]})
        previews = [(GrainPreviewWidget(), grain, "loadGrain"),
                    (NozzlePreviewWidget(), nozzle, "loadNozzle"),
                    (PropellantPreviewWidget(), propellant, "loadPropellant")]
        try:
            for widget, obj, method in previews:
                if hasattr(widget, "setPreferences"):
                    widget.setPreferences(Preferences(DEFAULT_PREFERENCES))
                getattr(widget, method)(obj)
                self.assertGreater(widget.ui.tabAlerts.count(), 0)
            for language in ("ru", "en"):
                with patch.object(BatesGrain, "getRegressionData", side_effect=AssertionError("Regenerated")), \
                     patch.object(Nozzle, "getGeometryErrors", side_effect=AssertionError("Revalidated nozzle")), \
                     patch.object(Propellant, "getErrors", side_effect=AssertionError("Revalidated propellant")):
                    self.select_language(language)
                    for widget, _, _ in previews:
                        text = display_text(widget.alerts[0].description)
                        self.assertEqual(widget.ui.tabAlerts.item(0).text(), text)
                        self.assertEqual(widget.ui.tabAlerts.item(0).toolTip(), text)
                        title = "Предупреждения" if language == "ru" else "Alerts"
                        self.assertEqual(widget.ui.tabWidget.tabText(0), title)
        finally:
            for widget, _, _ in previews:
                widget.hide()
                widget.deleteLater()

    def test_propellant_graphs_and_characteristic_velocity_retranslate_cached_data(self):
        widget = PropellantPreviewWidget()
        widget.setPreferences(Preferences(DEFAULT_PREFERENCES))
        widget.ui.tabBurnRate.showGraph([[1e6, 2e6], [0.002, 0.004]])
        widget.ui.tabPressure.showGraph([[100, 200], [1e6, 2e6]])
        editor = PropellantTabEditor(APP.window)
        editor.setPreferences(Preferences(DEFAULT_PREFERENCES))
        editor.loadProperties(self.reference_result().motor.propellant.props["tabs"].tabs[0])
        before = editor.getProperties()
        cstar = editor._cStarText
        spy = QSignalSpy(editor.modified)
        lines = [widget.ui.tabBurnRate.plot.lines[0], widget.ui.tabPressure.plot.lines[0]]
        try:
            with patch.object(editor, "propertyUpdate", side_effect=AssertionError("Recomputed c*")), \
                 patch.object(Propellant, "getBurnRate", side_effect=AssertionError("Recomputed burn rate")):
                for language in ("ru", "en"):
                    self.select_language(language)
                    self.assertEqual(editor.getProperties(), before)
                    self.assertEqual(editor._cStarText, cstar)
                    self.assertEqual(editor.labelCStar.text(), display_text(cstar))
                    self.assertEqual(len(spy), 0)
                    self.assertIs(widget.ui.tabBurnRate.plot.lines[0], lines[0])
                    self.assertIs(widget.ui.tabPressure.plot.lines[0], lines[1])
                    self.assertEqual(widget.ui.tabPressure.plot.get_xlabel(), "Kn")
                    pressure_label = widget.ui.tabPressure.plot.get_ylabel()
                    burn_rate_label = widget.ui.tabBurnRate.plot.get_ylabel()
                    self.assertIn("Давление" if language == "ru" else "Pressure", pressure_label)
                    self.assertIn("Скорость горения" if language == "ru" else "Burn Rate", burn_rate_label)
        finally:
            widget.deleteLater()
            editor.cleanup()
            editor.deleteLater()

    def test_results_graph_tables_and_stats_keep_existing_simulation(self):
        result = self.reference_result()
        widget = APP.window.ui.resultsWidget
        APP.window.updateMotorStats(result)
        widget.showData(result)
        widget.ui.horizontalSliderTime.setValue(10)
        graph = widget.ui.widgetGraph
        # Explicitly include a grain channel to verify translated legend templates.
        widget.ui.channelSelectorY.checks["mass"].setChecked(True)
        lines = tuple(graph.plot.lines)
        datasets = [(line.get_xdata().copy(), line.get_ydata().copy()) for line in lines]
        channels = copy.deepcopy({key: channel.data for key, channel in result.channels.items()})
        selected = widget.ui.channelSelectorY.getSelectedChannels()
        graph.plot.set_xlim(0, 1)
        limits = graph.plot.get_xlim(), graph.plot.get_ylim()
        progress = widget.ui.labelTimeProgress.text()
        spy = QSignalSpy(widget.ui.channelSelectorY.checksChanged)
        try:
            with patch.object(Motor, "runSimulation", side_effect=AssertionError("Re-ran simulation")), \
                 patch.object(BatesGrain, "getRegressionData", side_effect=AssertionError("Regenerated result images")):
                for language in ("ru", "en"):
                    self.select_language(language)
                    self.assertIs(widget.simResult, result)
                    self.assertEqual(tuple(graph.plot.lines), lines)
                    self.assertEqual((graph.plot.get_xlim(), graph.plot.get_ylim()), limits)
                    self.assertEqual(widget.ui.channelSelectorY.getSelectedChannels(), selected)
                    self.assertEqual(widget.ui.horizontalSliderTime.value(), 10)
                    self.assertEqual(widget.ui.labelTimeProgress.text(), progress)
                    self.assertEqual(len(spy), 0)
                    self.assertIn("Время" if language == "ru" else "Time", graph.plot.get_xlabel())
                    legend = [text.get_text() for text in graph.plot.get_legend().texts]
                    self.assertTrue(any(("шашка" if language == "ru" else "Grain") in text for text in legend))
                    self.assertEqual(widget.ui.tableWidgetGrains.horizontalHeaderItem(0).text(),
                                     "Шашка 1" if language == "ru" else "Grain 1")
                    self.assertIn("шашка:" if language == "ru" else "G:", APP.window.ui.labelPeakMassFlux.text())
                    for line, (x, y) in zip(lines, datasets):
                        np.testing.assert_array_equal(line.get_xdata(), x)
                        np.testing.assert_array_equal(line.get_ydata(), y)
                    for key, data in channels.items():
                        np.testing.assert_array_equal(result.channels[key].data, data)
        finally:
            widget.ui.channelSelectorY.checks["mass"].setChecked(False)
            widget.resetPlot()
            APP.window.setupMotorStats()

    def test_long_channel_labels_fit_after_language_change(self):
        for language in ("ru", "en"):
            self.select_language(language)
            APP.processEvents()
            ui = APP.window.ui.resultsWidget.ui
            for selector in (ui.channelSelectorX, ui.channelSelectorY):
                for checkbox in selector.checks.values():
                    self.assertGreaterEqual(checkbox.width(), checkbox.minimumSizeHint().width())
            self.assertTrue(APP.window.ui.labelPeakMassFluxText.wordWrap())
            self.assertTrue(APP.window.ui.labelPortThroatRatioText.wordWrap())

    def test_nozzle_preview_and_expansion_ratio_retranslate_without_recalculation(self):
        editor = APP.window.ui.motorEditor
        editor.loadObject(self.reference_result().motor.nozzle)
        APP.processEvents()
        polygon = editor.nozzlePreview.upper.polygon()
        coordinates = [(point.x(), point.y()) for point in polygon]
        values = editor.getProperties()
        ratio = editor._expRatioText
        try:
            with patch.object(editor, "propertyUpdate", side_effect=AssertionError("Recomputed ratio")), \
                 patch.object(editor.nozzlePreview, "loadNozzle", side_effect=AssertionError("Regenerated nozzle")):
                for language in ("ru", "en"):
                    self.select_language(language)
                    self.assertEqual(editor.getProperties(), values)
                    self.assertEqual(editor.expRatioLabel.text(), display_text(ratio))
                    self.assertEqual([(point.x(), point.y()) for point in editor.nozzlePreview.upper.polygon()],
                                     coordinates)
        finally:
            editor.cleanup()

    def test_image_export_preserves_live_plot_and_language_refresh(self):
        result = self.reference_result()
        graph = APP.window.ui.resultsWidget.ui.widgetGraph
        graph.showData(result, "time", ["force"], [0])
        lines = tuple(graph.plot.lines)
        figure = graph.figure
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "plot.png"
                graph.saveImage(result, "time", ["pressure"], [0], path)
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.select_language("ru")
            self.assertIs(graph.figure, figure)
            self.assertEqual(tuple(graph.plot.lines), lines)
            self.assertEqual(graph.plot.get_legend().texts[0].get_text(),
                             "Тяга - " + graph.preferences.getUnit("N"))
        finally:
            graph.resetPlot()

    def test_tabular_navigation_state_and_values_survive_language_changes(self):
        widget = TabularEditor()
        widget.setPreferences(Preferences(DEFAULT_PREFERENCES))
        tab = self.reference_result().motor.propellant.props["tabs"].tabs[0]
        widget.addTab(tab)
        widget.addTab(tab)
        before = widget.getTabs()
        spy = QSignalSpy(widget.updated)
        try:
            for language in ("ru", "en"):
                self.select_language(language)
                self.assertEqual(widget.ui.labelCurrentTab.text(), "2/2")
                self.assertEqual(widget.ui.stackedWidget.currentIndex(), 1)
                self.assertEqual(widget.getTabs(), before)
                self.assertEqual(len(spy), 0)
                self.assertEqual(widget.ui.pushButtonAdd.text(),
                                 "Добавить диапазон давления" if language == "ru" else "Add Pressure Range")
        finally:
            widget.deleteLater()

    def test_calculations_projects_and_exports_match_stage_one_byte_for_byte(self):
        reference = json.loads((ROOT / "test/localization/data/stage1-reference.json").read_text())
        result = self.reference_result()
        channels = {key: channel.data for key, channel in result.channels.items()}
        encoded = json.dumps(channels, sort_keys=True, separators=(",", ":")).encode()
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), reference["channels_sha256"])
        manager = APP.importExportManager
        original = manager.motor, manager.simRes, manager.preferences
        manager.motor, manager.simRes = result.motor, result
        manager.preferences = Preferences(DEFAULT_PREFERENCES)
        try:
            with tempfile.TemporaryDirectory() as directory:
                for language in ("en", "ru", "en"):
                    self.select_language(language)
                    for extension, exporter_type, config in (("csv", CsvExporter, [[], []]),
                                                              ("eng", EngExporter, reference["eng_config"]),
                                                              ("bsx", BurnSimExporter, None)):
                        exporter = next(c for c in manager.conversions if isinstance(c, exporter_type))
                        path = Path(directory) / f"reference.{extension}"
                        exporter.doConversion(path, config)
                        digest = hashlib.sha256(self.reference_file_bytes(path)).hexdigest()
                        self.assertEqual(digest, reference["sha256"][path.name], (language, extension))
                        if extension == "eng":
                            append = dict(config, append="Append")
                            size = path.stat().st_size
                            exporter.doConversion(path, append)
                            self.assertEqual(path.stat().st_size, size * 2)
                    path = Path(directory) / "reference.ric"
                    saveFile(path, result.motor.getDict(), fileTypes.MOTOR)
                    self.assertEqual(hashlib.sha256(self.reference_file_bytes(path)).hexdigest(), reference["sha256"][path.name])
                    restored = Motor(loadFile(path, fileTypes.MOTOR))
                    self.assertEqual(restored.getDict(), result.motor.getDict())
                    self.assertTrue(all(type(grain["type"]) is str for grain in restored.getDict()["grains"]))
        finally:
            manager.motor, manager.simRes, manager.preferences = original

    def reference_file_bytes(self, path):
        contents = path.read_bytes()
        if path.suffix != ".bsx":
            # Golden files were recorded on Linux. Preserve native newline
            # behavior on Windows, then compare identical logical text bytes.
            if sys.platform == "win32":
                self.assertNotIn(b"\n", contents.replace(b"\r\n", b""))
            else:
                self.assertNotIn(b"\r\n", contents)
            contents = contents.replace(b"\r\n", b"\n")
        return contents

    def test_burnsim_import_is_independent_of_language(self):
        manager = APP.importExportManager
        exporter = next(c for c in manager.conversions if isinstance(c, BurnSimExporter))
        importer = next(c for c in manager.conversions if isinstance(c, BurnSimImporter))
        original = manager.motor
        manager.motor = self.reference_result().motor
        results = []
        messages = []
        try:
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "motor.bsx"
                exporter.doConversion(path, None)
                for language in ("en", "ru", "en"):
                    self.select_language(language)
                    def capture(motor):
                        results.append(motor.getDict())

                    with patch.object(manager, "startFromMotor", side_effect=capture), \
                         patch.object(APP, "outputMessage", side_effect=lambda text: messages.append(text)):
                        importer.doConversion(path)
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0], results[2])
            self.assertIn("Nozzle angles", messages[0])
            self.assertIn("Углы сопла", messages[1])
            self.assertEqual(messages[0], messages[2])
        finally:
            manager.motor = original

    def test_all_existing_motor_fixtures_match_original_calculations_and_alerts(self):
        references = json.loads((ROOT / "test/localization/data/model-reference.json").read_text())
        self.select_language("ru")
        for relative, expected in references.items():
            with self.subTest(project=relative):
                motor = Motor(loadFile(ROOT / relative, fileTypes.MOTOR))
                result = motor.runSimulation()
                values = {
                    "motor": motor.getDict(), "success": result.success,
                    "channels": {key: channel.data for key, channel in result.channels.items()},
                    "alerts": [(alert.level.value, alert.type.value, str(alert.location), str(alert.description))
                               for alert in result.alerts],
                }
                encoded = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
                self.assertEqual(hashlib.sha256(encoded).hexdigest(), expected)

    def test_model_translation_metadata_stays_english_and_qt_free(self):
        template = QT_TRANSLATE_NOOP("SimulationAlerts", "Initial port/throat ratio of {:.3f} was less than {:.3f}")
        marked = template.format(1.25, 2.0)
        self.assertEqual(str(marked), "Initial port/throat ratio of 1.250 was less than 2.000")
        self.select_language("ru")
        self.assertEqual(display_text(copy.deepcopy(marked)),
                         "Начальное отношение площади канала к критическому сечению 1.250 меньше 2.000")
        self.assertEqual(marked, "Initial port/throat ratio of 1.250 was less than 2.000")
        script = "import motorlib; import sys; assert not any(m.startswith('PyQt6') for m in sys.modules)"
        command = [sys.executable, "-c", script]
        process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(process.returncode, 0, process.stderr)

    def test_error_dialog_translates_application_details(self):
        self.select_language("ru")
        error = ValueError(QT_TRANSLATE_NOOP("FileIO", "Loaded data type did not match expected type."))
        observed = []

        def observe(dialog):
            observed.append((dialog.windowTitle(), dialog.informativeText()))
            return QMessageBox.StandardButton.Ok

        with patch.object(QMessageBox, "exec", observe):
            APP.outputException(error, "test")
        self.assertEqual(observed[0], ("openMotor — Ошибка", "Тип загруженных данных не соответствует ожидаемому."))


if __name__ == "__main__":
    unittest.main()
