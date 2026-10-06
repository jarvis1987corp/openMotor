"""GUI checks for a frozen test executable; not part of the release application.

Run first, restart and english phases as separate processes with the same
--data-dir. All user data is isolated, including on Windows.
"""

# UI imports must follow directory/backend setup.
# ruff: noqa: E402
import argparse
import hashlib
import json
import os
import platform
import sys
import time
from pathlib import Path
from unittest.mock import patch

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--data-dir", type=Path, required=True)
parser.add_argument("--project", type=Path, required=True)
parser.add_argument("--phase", choices=("first", "restart", "english"), required=True)
arguments = parser.parse_args()
directory = arguments.data_dir.resolve()
directory.mkdir(parents=True, exist_ok=True)
for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "MPLCONFIGDIR"):
    os.environ[name] = str(directory)

import platformdirs

platformdirs.user_data_dir = lambda *args, **kwargs: str(directory / "preferences")
platformdirs.user_log_dir = lambda *args, **kwargs: str(directory / "logs")

import uilib  # noqa: F401 -- choose Qt before app.py imports pyplot

# isort: split
from PyQt6.QtCore import QItemSelectionModel
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtWidgets import QMessageBox

from app import App
from uilib.converters import BurnSimExporter, BurnSimImporter, CsvExporter, EngExporter
from uilib.fileIO import fileTypes, loadFile
from uilib.localization import TRANSLATIONS_PATH

assert getattr(sys, "frozen", False), "Run the frozen probe, not its source script"
assert (TRANSLATIONS_PATH / "openmotor_ru.qm").is_file()
assert (TRANSLATIONS_PATH / "qtbase_ru.qm").is_file()
expected_language = "ru" if arguments.phase == "restart" else "en"
preferences_path = directory / "preferences/preferences.yaml"
if arguments.phase == "first":
    assert not preferences_path.exists(), "Use an empty data directory for the first phase"
app = App([sys.argv[0]])
app.processEvents()
assert app.translationManager.language == expected_language
assert not app.icon.isNull()
assert not app.window.aboutDialog.ui.labelImage.pixmap().isNull()
messages = []
app.outputMessage = lambda *args, **kwargs: messages.append(str(args[0]))
failures = []
app.outputException = lambda *args, **kwargs: failures.append(str(args[0]))
assert app.fileManager.load(str(arguments.project.resolve()))
model = app.fileManager.getCurrentMotor().getDict()
saved_project = directory / "двигатель — сохранённый.ric"
with patch.object(app.fileManager, "showSaveDialog", return_value=str(saved_project)):
    app.fileManager.saveAs()
assert not failures, failures
assert loadFile(saved_project, fileTypes.MOTOR) == model
assert app.fileManager.load(str(saved_project))
assert app.fileManager.getCurrentMotor().getDict() == model

# Exercise the actual GUI simulation thread and its queued result signals.
app.window.runSimulation()
deadline = time.monotonic() + 60
while app.importExportManager.simRes is None and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.01)
assert app.importExportManager.simRes is not None, "Simulation timed out or failed"
app.simulationManager.currentSimThread.join(timeout=5)
assert not app.simulationManager.currentSimThread.is_alive()
app.processEvents()
result = app.importExportManager.simRes
assert result.success
widget = app.window.ui.resultsWidget
graph = widget.ui.widgetGraph
assert widget.simResult is result and graph.plot.lines
lines = list(graph.plot.lines)
limits = graph.plot.get_xlim(), graph.plot.get_ylim()
sim_thread = app.simulationManager.currentSimThread


def result_digest():
    values = {key: channel.data for key, channel in result.channels.items()}
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


original_digest = result_digest()
export_bytes = {}
imported_models = []
standard_buttons = {}
manager = app.importExportManager
settings = {
    "diameter": 0.054,
    "length": 0.5,
    "hardwareMass": 0.5,
    "designation": "PackagedCheck",
    "manufacturer": "openMotor",
    "append": "Overwrite",
}
for language in ("en", "ru", "en"):
    menu = app.preferencesManager.menu
    menu.load(app.preferencesManager.preferences)
    menu.ui.comboBoxLanguage.setCurrentIndex(menu.ui.comboBoxLanguage.findData(language))
    menu.apply()
    for _ in range(3):
        app.processEvents()
    assert app.translationManager.language == language
    assert loadFile(preferences_path, fileTypes.PREFERENCES)["language"] == language
    assert widget.simResult is result and manager.simRes is result
    assert result_digest() == original_digest
    assert app.fileManager.getCurrentMotor().getDict() == model
    assert app.simulationManager.currentSimThread is sim_thread
    assert list(graph.plot.lines) == lines
    assert (graph.plot.get_xlim(), graph.plot.get_ylim()) == limits
    assert graph.plot.get_xlabel().startswith("Время" if language == "ru" else "Time")
    legend = " ".join(text.get_text() for text in graph.plot.get_legend().get_texts())
    assert ("Тяга" if language == "ru" else "Thrust") in legend
    assert app.window.ui.menuFile.title() == ("Файл" if language == "ru" else "File")
    assert app.window.ui.labelBurnTime.text() != "-"
    dialog = QMessageBox()
    dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
    button = dialog.button(QMessageBox.StandardButton.Cancel).text()
    assert button == ("Отмена" if language == "ru" else "Cancel")
    standard_buttons[language] = button
    if language == "ru":
        metrics = QFontMetrics(app.window.font())
        missing_glyphs = sorted({character for character in "ТягаДавлениеРусский" if not metrics.inFont(character)})
        assert not missing_glyphs, {
            "missing_glyphs": missing_glyphs,
            "font": app.window.font().toString(),
            "platform": app.platformName(),
        }
    for extension, exporter_type, config in (
        ("csv", CsvExporter, [[], []]),
        ("eng", EngExporter, settings),
        ("bsx", BurnSimExporter, None),
    ):
        exporter = next(converter for converter in manager.conversions if isinstance(converter, exporter_type))
        path = directory / f"экспорт — {language}.{extension}"
        exporter.doConversion(path, config)
        contents = path.read_bytes()
        if extension in export_bytes:
            assert contents == export_bytes[extension], (language, extension)
        export_bytes[extension] = contents
    importer = next(converter for converter in manager.conversions if isinstance(converter, BurnSimImporter))
    with patch.object(manager, "startFromMotor", side_effect=lambda motor: imported_models.append(motor.getDict())):
        importer.doConversion(directory / f"экспорт — {language}.bsx")
    image = directory / f"график — {language}.png"
    graph.saveImage(result, "time", ["force", "pressure"], [0], image)
    assert image.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert list(graph.plot.lines) == lines
assert imported_models[0] == imported_models[1] == imported_models[2]
assert not failures, failures

# Exercise the Design Assistant's actual worker inside the frozen application.
# Keep the release application entry point unchanged; this remains a test binary.
app.window.designAssistantAction.trigger()
assistant = app.window.designAssistant
assistant.add_variable("nozzle.throat")
variable = assistant.variable_rows[0]
original_value = variable.minimum.value()
variable.minimum.setValue(original_value * 0.99)
variable.maximum.setValue(original_value * 1.01)
variable.points.setValue(3)
assistant.budget.setValue(3)
baseline = assistant.controller.baseline
source_bytes = saved_project.read_bytes()


def wait_for_design_search():
    deadline = time.monotonic() + 60
    while assistant.controller.is_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    assert not assistant.controller.is_running, "Design Assistant search timed out"
    app.processEvents()


assistant.start_search()
wait_for_design_search()
assert assistant._state == "completed" and assistant._progress.processed == 3
assert all(e.outcome.valid for e in assistant.controller.evaluations.values())
requirements = assistant.build_requirements()
grid_rows = tuple(assistant.model.rows)
for language in ("en", "ru", "en"):
    app.translationManager.setLanguage(language)
    app.processEvents()
    assert assistant.tabs.tabText(0) == ("Переменные" if language == "ru" else "Variables")
    assert assistant.build_requirements() == requirements
    assert tuple(assistant.model.rows) == grid_rows
    assert assistant.controller.baseline == baseline
    assert app.fileManager.getCurrentMotor().getDict() == model
    assert manager.simRes is result and result_digest() == original_digest
assistant.strategy.setCurrentIndex(assistant.strategy.findData("random"))
assistant.seed.setValue(1729)
assistant.start_search()
wait_for_design_search()
random_rows = tuple(assistant.model.rows)
assistant.start_search()
wait_for_design_search()
assert tuple(assistant.model.rows) == random_rows

# Smart Design uses the same engine and a requirements form, not manual paths.
assistant.mode.setCurrentIndex(assistant.mode.findData("smart"))
smart_target = assistant.smart.targets["burn_time"]
smart_target.enabled.setChecked(True)
smart_target.value.setValue(result.getBurnTime())
smart_target.tolerance.setValue(1)
assistant.smart.budget.setValue(8)
assistant.smart.top_n.setValue(2)
assistant.start_search()
wait_for_design_search()
assert assistant._state == "completed"
smart_ranked = assistant.controller.smart_store.top
assert len(smart_ranked) == 2
assert all(r.context.stage == "verification" for r in smart_ranked)
smart_requirements = assistant.smart.build_requirements()
for language in ("en", "ru", "en"):
    app.translationManager.setLanguage(language)
    app.processEvents()
    assert assistant.mode.currentText() == ("Умный подбор" if language == "ru" else "Smart Design")
    assert assistant.smart.build_requirements() == smart_requirements
    assert assistant.controller.smart_store.top == smart_ranked
    assert assistant.controller.baseline == baseline
    assert app.fileManager.getCurrentMotor().getDict() == model
    assert manager.simRes is result and result_digest() == original_digest
assistant.start_search()
wait_for_design_search()
assert assistant.controller.smart_store.top == smart_ranked
for record in smart_ranked:
    source_row = next(
        i for i, (p, _) in enumerate(assistant.model.rows) if p.candidate_id == record.proposal.candidate_id
    )
    index = assistant.proxy.mapFromSource(assistant.model.index(source_row, 0))
    assistant.table.selectionModel().select(
        index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
    )
assert assistant.compareButton.isEnabled()
assistant.compare_selected()
assert assistant.comparison.records == smart_ranked
assistant.comparison.hide()
candidate_id = smart_ranked[0].proposal.candidate_id
candidate = assistant.controller.request_for(candidate_id).snapshot
assistant.table.clearSelection()
source_row = next(i for i, (p, _) in enumerate(assistant.model.rows) if p.candidate_id == candidate_id)
assistant.table.selectRow(assistant.proxy.mapFromSource(assistant.model.index(source_row, 0)).row())
assistant.open_selected()
assert app.fileManager.fileName is None and app.fileManager.savedVersion == -1
from designassistant import Snapshot

assert Snapshot.from_dict(app.fileManager.getCurrentMotor().getDict()) == candidate
assert saved_project.read_bytes() == source_bytes
assert assistant.controller.baseline == baseline
assistant.smart.budget.setValue(10000)
assistant.start_search()
assistant.stop_search()
wait_for_design_search()
assert assistant._state == "stopped" and assistant._progress.processed < 10000
assistant.mode.setCurrentIndex(assistant.mode.findData("manual"))
assistant.budget.setValue(10000)
assistant.start_search()
assistant.stop_search()
wait_for_design_search()
assert assistant._state == "stopped" and assistant._progress.processed < 10000
assistant.close()
app.processEvents()

# The Quick wizard delegates to that same Smart backend and comparison dialog.
# The preceding handoff deliberately left an unsaved candidate. Choose Discard
# explicitly in this isolated QA directory; an unattended test must not await
# the real unsaved-changes modal before loading its saved baseline again.
with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Discard):
    assert app.fileManager.load(str(saved_project))
app.window.postLoadUpdate()
app.window.quickDesignAction.trigger()
quick = app.window.quickDesign
quick.allowed_keys = smart_requirements.library_keys
quick.rows["burn_time"].enabled.setChecked(True)
quick.rows["burn_time"].value.setValue(result.getBurnTime())
quick.next()
assert quick.pages.currentIndex() == 1 and quick.problem is not None
quick.start_search(budget=16)
deadline = time.monotonic() + 60
while quick.controller.is_running and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.005)
assert not quick.controller.is_running and quick._state == "completed"
assert 2 <= len(quick.recommendations) <= 5
quick_ranked = quick.recommendations
quick_requirements = quick.build_requirements()
for language in ("en", "ru", "en"):
    app.translationManager.setLanguage(language)
    app.processEvents()
    assert quick.windowTitle() == ("Быстрое проектирование" if language == "ru" else "Quick Design")
    assert quick.build_requirements() == quick_requirements
    assert quick.recommendations == quick_ranked
    assert quick.controller.baseline == baseline
    assert app.fileManager.getCurrentMotor().getDict() == model
    assert result_digest() == original_digest
quick.start_search(budget=16)
deadline = time.monotonic() + 60
while quick.controller.is_running and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.005)
assert not quick.controller.is_running and quick.recommendations == quick_ranked
for record in quick_ranked[:2]:
    quick.cards[record.proposal.candidate_id].selected.setChecked(True)
quick.compare_selected()
assert quick.comparison.records == quick_ranked[:2]
quick.comparison.hide()
advanced = quick.open_advanced()
assert advanced.mode.currentData() == "manual" and advanced.variable_rows
assert advanced.build_requirements().targets[0].metric == "burn_time"
transferred_bounds = {c.metric: c for c in advanced.build_requirements().constraints}
expected_diameter = quick.problem.plan.requirements.maximum_diameter
assert abs(transferred_bounds["maximum_diameter"].maximum - expected_diameter) < 1e-10
assert transferred_bounds["maximum_diameter"].minimum is None
assert app.fileManager.getCurrentMotor().getDict() == model
advanced.close()
app.processEvents()
quick_id = quick_ranked[0].proposal.candidate_id
quick_candidate = quick.controller.request_for(quick_id).snapshot
quick.open_candidate_id(quick_id)
assert app.fileManager.fileName is None and app.fileManager.savedVersion == -1
assert Snapshot.from_dict(app.fileManager.getCurrentMotor().getDict()) == quick_candidate
assert saved_project.read_bytes() == source_bytes
quick.start_search(budget=10000)
quick.stop_search()
deadline = time.monotonic() + 60
while quick.controller.is_running and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.005)
assert not quick.controller.is_running and quick._state == "stopped"
assert quick._progress.processed < 10000
quick.close()
app.processEvents()

# Leave Russian saved for the next process, then English after restart checks.
final_language = "ru" if arguments.phase == "first" else "en"
menu.load(app.preferencesManager.preferences)
menu.ui.comboBoxLanguage.setCurrentIndex(menu.ui.comboBoxLanguage.findData(final_language))
menu.apply()
app.processEvents()
assert loadFile(preferences_path, fileTypes.PREFERENCES)["language"] == final_language
report = {
    "platform": platform.platform(),
    "frozen": True,
    "phase": arguments.phase,
    "initial_language": expected_language,
    "saved_language": final_language,
    "bundle": str(TRANSLATIONS_PATH),
    "cwd": os.getcwd(),
    "project": str(saved_project),
    "channels_sha256": original_digest,
    "standard_buttons": standard_buttons,
    "exports_sha256": {ext: hashlib.sha256(data).hexdigest() for ext, data in export_bytes.items()},
    "checks": [
        "startup",
        "resource images",
        "bundled catalogs",
        "language round trip",
        "persistent language",
        "Qt standard buttons",
        "Cyrillic font glyphs",
        "Unicode project load/save/reload",
        "GUI simulation",
        "cached results and graph",
        "CSV/ENG/BurnSim language-independent bytes",
        "BurnSim import",
        "Unicode PNG export",
        "Design Assistant frozen fingerprint",
        "Design Assistant grid and seeded random search",
        "Design Assistant language round trip",
        "Design Assistant Start/Stop",
        "Smart Design frozen search space and coarse-to-fine ranking",
        "Smart Design seeded reproducibility and finalist recheck",
        "Smart Design language round trip and comparison",
        "Smart Design Start/Stop and unchanged baseline",
        "Quick Design wizard and existing Smart backend",
        "Quick Design language round trip and seeded reproducibility",
        "Quick Design cards, comparison and Advanced handoff",
        "Quick Design Start/Stop, unsaved handoff and unchanged source",
        "candidate unsaved handoff",
        "unchanged source project",
    ],
}
report_path = directory / f"report-{arguments.phase}.json"
report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"PASS: {arguments.phase}: {report_path}")
app.window.hide()
app.preferencesManager.menu.hide()
app.simulationManager.alertsDialog.hide()
