"""Exercise real widgets, background calculations and explicit document handoff."""

import ast
import copy
import dataclasses
import json
import math
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

# Reuse the existing cross-platform isolation BEFORE App/logger imports.
from test.localization import test_localization as isolation

# isort: split
from PyQt6.QtCore import QCoreApplication, QItemSelectionModel, Qt, QThread, QTimer
from PyQt6.QtWidgets import QMessageBox

from designassistant import CandidateGenerator, MetricValue, OutcomeStatus, SimulationOutcome, Snapshot
from designassistant.quick import QuickCriterion
from motorlib.motor import Motor
from motorlib.units import convert
from uilib.designassistant.presentation import CORE_MESSAGES, UI_MESSAGES, diagnostic_text
from uilib.designassistant.results import ID_ROLE
from uilib.designassistant.smart_messages import SMART_MESSAGES
from uilib.fileIO import fileTypes, loadFile, saveFile
from uilib.localization import TRANSLATIONS_PATH

ROOT = Path(__file__).resolve().parents[2]
APP = None
BASELINE = None
SOURCE = None


def setUpModule():
    global APP, BASELINE, SOURCE
    isolation.setUpModule()
    APP = isolation.APP
    BASELINE = Motor(loadFile(ROOT / "test/data/regression/simple/motor.ric", fileTypes.MOTOR)).getDict()
    APP.propellantManager.propellants.append(Motor(copy.deepcopy(BASELINE)).propellant)
    SOURCE = Path(isolation._data.name) / "исходный двигатель.ric"


def tearDownModule():
    isolation.tearDownModule()


class DesignGuiTests(unittest.TestCase):
    def setUp(self):
        APP.translationManager.setLanguage("en")
        APP.processEvents()
        APP.window.ui.motorEditor.close()
        saveFile(SOURCE, copy.deepcopy(BASELINE), fileTypes.MOTOR)
        APP.fileManager.startFromMotor(Motor(copy.deepcopy(BASELINE)), str(SOURCE), checkPropellant=False)
        APP.window.postLoadUpdate()
        self.original_snapshot = Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict())
        APP.window.designAssistantAction.trigger()
        self.window = APP.window.designAssistant
        self.warnings = patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok)
        self.warning = self.warnings.start()

    def tearDown(self):
        self.window.controller.stop()
        self.wait_finished()
        APP.translationManager.setLanguage("en")
        APP.processEvents()
        self.window.close()
        APP.processEvents()
        APP.processEvents()
        APP.window.ui.motorEditor.close()
        self.warnings.stop()

    def wait_finished(self, timeout=30):
        deadline = time.monotonic() + timeout
        while self.window.controller.is_running and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.002)
        APP.processEvents()
        self.assertFalse(self.window.controller.is_running, "Worker failed to finish")

    def configure(self, *, minimum=None, maximum=None, points=3, budget=3, strategy="grid", seed=123):
        self.window.add_variable("nozzle.throat")
        row = self.window.variable_rows[0]
        value = convert(BASELINE["nozzle"]["throat"], row.option.unit, row.option.display_unit)
        row.minimum.setValue(value * 0.99 if minimum is None else minimum)
        row.maximum.setValue(value * 1.01 if maximum is None else maximum)
        row.points.setValue(points)
        self.window.budget.setValue(budget)
        self.window.strategy.setCurrentIndex(self.window.strategy.findData(strategy))
        self.window.seed.setValue(seed)

    def search(self):
        self.window.startButton.click()
        self.wait_finished()
        self.warning.assert_not_called()
        return self.window.controller.evaluations

    def select_source_row(self, row):
        proxy_index = self.window.proxy.mapFromSource(self.window.model.index(row, 0))
        self.window.table.selectRow(proxy_index.row())
        APP.processEvents()

    def test_menu_opens_separate_window_and_reuses_active_window(self):
        self.assertTrue(self.window.isWindow())
        APP.window.designAssistantAction.trigger()
        self.assertIs(APP.window.designAssistant, self.window)
        self.assertEqual(self.window.controller.baseline, self.original_snapshot)

    def test_available_variables_use_friendly_labels_and_fixed_paths(self):
        labels = [self.window.variableChooser.itemText(i) for i in range(self.window.variableChooser.count())]
        paths = [self.window.variableChooser.itemData(i) for i in range(self.window.variableChooser.count())]
        self.assertIn("nozzle.throat", paths)
        self.assertIn("grains.0.length", paths)
        self.assertFalse(any(path.startswith(("config.", "propellant.")) for path in paths))
        self.assertFalse(any("nozzle." in label or "grains." in label for label in labels))

    def test_input_units_convert_to_engine_units_once(self):
        self.configure(minimum=0.4, maximum=0.5)
        requirements = self.window.build_requirements()
        option = self.window.variable_rows[0].option
        self.assertEqual(requirements.variables[0].range.minimum, convert(0.4, option.display_unit, option.unit))
        self.window.add_target("maximum_pressure")
        row = self.window.target_rows[-1]
        row.value.setValue(100)
        row.scale.setValue(10)
        target = self.window.build_requirements().targets[-1]
        unit = APP.preferencesManager.preferences.getUnit("Pa")
        self.assertEqual(target.value, convert(100, unit, "Pa"))
        self.assertEqual(target.scale, convert(10, unit, "Pa"))

    def test_grid_budget_and_order(self):
        self.configure(points=5, budget=3)
        self.search()
        proposals = list(self.window.controller.proposals.values())
        values = [p.assignments[0].value for p in proposals]
        self.assertEqual(len(values), 3)
        self.assertEqual(values, sorted(values))
        self.assertEqual(self.window._progress.total, 3)
        self.assertEqual(self.window._progress.processed, 3)

    def test_zero_variable_grid_runs_baseline_once(self):
        self.window.budget.setValue(100)
        self.assertEqual(len(self.search()), 1)

    def test_random_search_same_seed_includes_identical_metrics(self):
        self.configure(strategy="random", budget=8, seed=91)
        self.search()
        first = tuple(self.window.model.rows)
        self.search()
        self.assertEqual(tuple(self.window.model.rows), first)
        self.window.seed.setValue(92)
        self.search()
        self.assertNotEqual(tuple(p for p, _ in self.window.model.rows), tuple(p for p, _ in first))

    def test_gui_heartbeat_and_signal_thread_affinity(self):
        self.configure(strategy="random", budget=15)
        ticks, receivers = [], []
        timer = QTimer()
        timer.setInterval(1)
        timer.timeout.connect(lambda: ticks.append(True))
        self.window.controller.candidateReady.connect(lambda *_: receivers.append(QThread.currentThread()))
        timer.start()
        original = Motor.runSimulation

        def slow_calculation(motor, callback=None):
            time.sleep(0.02)
            return original(motor, callback)

        with patch.object(Motor, "runSimulation", slow_calculation):
            self.search()
        timer.stop()
        self.assertGreater(len(ticks), 5)
        self.assertTrue(receivers)
        self.assertTrue(all(thread == APP.thread() for thread in receivers))

    def test_stop_prevents_new_candidates(self):
        self.configure(strategy="random", budget=1000)
        self.window.start_search()
        self.window.stopButton.click()
        self.wait_finished()
        self.assertEqual(self.window._state, "stopped")
        self.assertLess(self.window._progress.processed, 1000)
        self.assertTrue(self.window.startButton.isEnabled())

    def test_stop_during_engine_callback(self):
        self.configure(strategy="random", budget=1000)
        self.window.controller.progressChanged.connect(
            lambda p: self.window.stop_search() if p.current > 0 and self.window.controller.is_running else None
        )
        self.window.start_search()
        self.wait_finished()
        self.assertEqual(self.window._state, "stopped")
        self.assertLess(self.window._progress.processed, 1000)

    def test_invalid_candidate_does_not_abort_search(self):
        self.configure(minimum=0, points=2, budget=2)
        self.search()
        evaluations = list(self.window.controller.evaluations.values())
        self.assertFalse(evaluations[0].outcome.valid)
        self.assertTrue(evaluations[1].outcome.valid)
        self.assertEqual(self.window._progress.errors, 1)
        self.assertEqual(self.window._progress.rejected, 1)
        self.assertEqual(self.window._progress.feasible, 1)
        self.select_source_row(0)
        self.assertFalse(self.window.openButton.isEnabled())

    def test_engine_exception_does_not_abort_search(self):
        self.configure(points=3)
        original = Motor.runSimulation
        count = 0

        def fail_once(motor, callback=None):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("Injected candidate failure")
            return original(motor, callback)

        with patch.object(Motor, "runSimulation", fail_once):
            self.search()
        self.assertEqual(self.window._progress.processed, 3)
        self.assertEqual(self.window._progress.errors, 1)
        self.assertEqual(self.window._progress.feasible, 2)

    def test_generator_exception_is_candidate_local(self):
        self.configure(points=3)
        original = CandidateGenerator.generate
        count = 0

        def fail_once(generator, proposal):
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("Injected generator failure")
            return original(generator, proposal)

        with patch.object(CandidateGenerator, "generate", fail_once):
            self.search()
        self.assertEqual(self.window._progress.processed, 3)
        self.assertEqual(self.window._progress.errors, 1)
        self.assertEqual(self.window._progress.feasible, 2)

    def test_rejected_setter_never_reaches_engine(self):
        self.configure(points=3)
        original = CandidateGenerator.generate
        run = Motor.runSimulation
        count = 0
        simulated = []

        def generate(generator, proposal):
            nonlocal count
            count += 1
            if count == 1:

                def reject(snapshot):
                    motor = Motor(snapshot)
                    motor.nozzle.props["throat"].setValue = lambda value: None
                    return motor

                with patch("designassistant.generator.Motor", side_effect=reject):
                    return original(generator, proposal)
            return original(generator, proposal)

        def simulate(motor, callback=None):
            simulated.append(True)
            return run(motor, callback)

        with patch.object(CandidateGenerator, "generate", generate), patch.object(Motor, "runSimulation", simulate):
            self.search()
        self.assertEqual(len(simulated), 2)
        self.assertEqual(self.window._progress.errors, 1)

    def _draft_and_select_candidate(self):
        self.configure()
        self.search()
        APP.window.ui.tableWidgetGrainList.selectRow(0)
        APP.window.editGrain()
        editor = APP.window.ui.motorEditor
        editor.propertyEditors["length"].editor.setValue(editor.propertyEditors["length"].editor.value() + 0.01)
        self.select_source_row(0)
        return editor

    def test_apply_draft_then_cancel_handoff_preserves_current_document(self):
        editor = self._draft_and_select_candidate()
        source = SOURCE.read_bytes()
        with (
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Apply),
            patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel),
        ):
            self.window.open_selected()
        self.assertFalse(editor.hasPendingChanges())
        self.assertEqual(APP.fileManager.fileName, str(SOURCE))
        self.assertEqual(APP.fileManager.currentVersion, 1)
        self.assertEqual(SOURCE.read_bytes(), source)
        self.assertEqual(self.window.controller.baseline, self.original_snapshot)

    def test_discard_editor_draft_allows_unsaved_candidate_handoff(self):
        editor = self._draft_and_select_candidate()
        source = SOURCE.read_bytes()
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Discard):
            self.window.open_selected()
        self.assertFalse(editor.hasPendingChanges())
        self.assertIsNone(APP.fileManager.fileName)
        self.assertEqual(APP.fileManager.savedVersion, -1)
        self.assertEqual(SOURCE.read_bytes(), source)

    def test_main_window_exit_defers_until_worker_stops_then_checks_unsaved(self):
        self.configure(strategy="random", budget=1000)
        self.window.start_search()
        with patch.object(APP.fileManager, "unsavedCheck", return_value=False) as check:
            APP.window.close()
            self.wait_finished()
            APP.processEvents()
            check.assert_called_once()
        self.assertFalse(APP.window._closeAfterDesignSearch)
        self.assertEqual(self.window._state, "stopped")

    def test_constraints_and_warning_policy(self):
        self.configure()
        self.window.add_constraint("maximum_pressure")
        bound = self.window.constraint_rows[0].maximum
        bound.value.setValue(0)
        self.search()
        self.assertTrue(all(e.score is None for e in self.window.controller.evaluations.values()))
        self.assertEqual(self.window._progress.rejected, 3)
        self.assertEqual(self.window._progress.errors, 0)
        self.window.constraint_rows.clear()
        self.window.constraintsTable.setRowCount(0)
        self.window.rejectWarnings.setChecked(True)
        self.search()
        for evaluation in self.window.controller.evaluations.values():
            if any(d.level == "WARNING" for d in evaluation.outcome.diagnostics):
                self.assertIsNone(evaluation.score)

    def test_invalid_settings_preserve_existing_results(self):
        self.configure()
        self.search()
        before = tuple(self.window.model.rows)
        self.window.variable_rows[0].points.setValue(1)
        self.window.start_search()
        self.warning.assert_called_once()
        self.assertEqual(tuple(self.window.model.rows), before)
        self.assertFalse(self.window.controller.is_running)

    def test_missing_target_rejected_before_start(self):
        self.window.target_rows.clear()
        self.window.targetsTable.setRowCount(0)
        self.window.start_search()
        self.warning.assert_called_once()
        self.assertFalse(self.window.controller.is_running)

    def test_language_roundtrip_preserves_inputs_results_selection_and_details(self):
        self.configure(strategy="random", budget=5)
        self.window.add_constraint("maximum_pressure")
        self.window.constraint_rows[0].maximum.value.setValue(100000)
        self.search()
        self.select_source_row(2)
        selected = self.window.selected_id()
        self.window.show_details()
        requirements = self.window.build_requirements()
        rows = tuple(self.window.model.rows)
        for language in ("en", "ru", "en"):
            APP.translationManager.setLanguage(language)
            APP.processEvents()
            self.assertEqual(self.window.build_requirements(), requirements)
            self.assertEqual(tuple(self.window.model.rows), rows)
            self.assertEqual(self.window.selected_id(), selected)
            self.assertEqual(self.window.details.candidate_id, selected)
            self.assertEqual(self.window.tabs.tabText(0), "Переменные" if language == "ru" else "Variables")
            self.assertEqual(
                APP.window.designAssistantAction.text(),
                "Помощник проектирования" if language == "ru" else "Design Assistant",
            )
            self.assertIn(
                "Средняя тяга" if language == "ru" else "Average Thrust", self.window.details.text.toPlainText()
            )

    def test_switch_language_during_search(self):
        self.configure(strategy="random", budget=10)
        requirements = self.window.build_requirements()
        self.window.start_search()
        APP.translationManager.setLanguage("ru")
        APP.processEvents()
        self.wait_finished()
        self.assertEqual(self.window.build_requirements(), requirements)
        self.assertEqual(len(self.window.model.rows), 10)
        APP.translationManager.setLanguage("en")
        APP.processEvents()
        self.assertEqual(len(self.window.model.rows), 10)

    def test_sorting_and_status_text_filtering(self):
        self.configure(minimum=0, points=3)
        self.search()
        self.window.statusFilter.setCurrentIndex(self.window.statusFilter.findData("error"))
        self.assertEqual(self.window.proxy.rowCount(), 1)
        self.window.textFilter.setText("definitely no matching text")
        self.assertEqual(self.window.proxy.rowCount(), 0)
        self.window.textFilter.clear()
        self.window.statusFilter.setCurrentIndex(self.window.statusFilter.findData("feasible"))
        self.assertEqual(self.window.proxy.rowCount(), 2)
        self.window.proxy.sort(2, Qt.SortOrder.AscendingOrder)
        ids = [self.window.proxy.data(self.window.proxy.index(i, 0), ID_ROLE) for i in range(2)]
        scores = [self.window.controller.evaluations[key].score for key in ids]
        self.assertEqual(scores, sorted(scores))

    def test_open_candidate_is_new_unsaved_document_with_no_source_write(self):
        self.configure()
        original_bytes = SOURCE.read_bytes()
        history = copy.deepcopy(APP.fileManager.fileHistory)
        self.search()
        self.assertEqual(APP.fileManager.fileHistory, history)
        self.select_source_row(1)
        candidate_id = self.window.selected_id()
        expected = self.window.controller.request_for(candidate_id).snapshot
        self.window.openButton.click()
        self.assertIsNone(APP.fileManager.fileName)
        self.assertEqual(APP.fileManager.savedVersion, -1)
        self.assertEqual(APP.fileManager.currentVersion, 0)
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), expected)
        self.assertTrue(APP.window.windowTitle().endswith("*"))
        self.assertEqual(SOURCE.read_bytes(), original_bytes)
        self.assertEqual(self.window.controller.baseline, self.original_snapshot)
        self.assertFalse(APP.fileManager.canUndo())
        self.assertFalse(APP.fileManager.canRedo())

    def test_cancel_unsaved_original_prevents_candidate_handoff(self):
        self.configure()
        self.search()
        motor = APP.fileManager.getCurrentMotor()
        motor.nozzle.setProperty("throat", motor.nozzle.getProperty("throat") * 1.02)
        APP.fileManager.addNewMotorHistory(motor)
        history = copy.deepcopy(APP.fileManager.fileHistory)
        self.select_source_row(0)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            self.window.open_selected()
        self.assertEqual(APP.fileManager.fileHistory, history)
        self.assertEqual(APP.fileManager.fileName, str(SOURCE))

    def test_cancel_save_as_does_not_discard_unsaved_candidate(self):
        APP.fileManager.openUnsavedSnapshot(copy.deepcopy(BASELINE))
        history = copy.deepcopy(APP.fileManager.fileHistory)
        with (
            patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Save),
            patch.object(APP.fileManager, "showSaveDialog", return_value=None),
        ):
            self.assertFalse(APP.fileManager.openUnsavedSnapshot(copy.deepcopy(BASELINE)))
        self.assertEqual(APP.fileManager.fileHistory, history)
        self.assertIsNone(APP.fileManager.fileName)
        self.assertEqual(APP.fileManager.savedVersion, -1)

    def test_failed_save_does_not_allow_document_replacement(self):
        APP.fileManager.savedVersion = -1
        with (
            patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Save),
            patch("uilib.fileManager.saveFile", side_effect=OSError("Injected failure")),
            patch.object(APP, "outputException"),
        ):
            self.assertFalse(APP.fileManager.unsavedCheck())
        self.assertEqual(APP.fileManager.fileName, str(SOURCE))

    def test_unapplied_editor_cancel_preserves_draft_and_project(self):
        self.configure()
        self.search()
        APP.window.ui.tableWidgetGrainList.selectRow(0)
        APP.window.editGrain()
        editor = APP.window.ui.motorEditor
        widget = editor.propertyEditors["length"].editor
        widget.setValue(widget.value() + 0.01)
        self.assertTrue(editor.hasPendingChanges())
        history = copy.deepcopy(APP.fileManager.fileHistory)
        self.select_source_row(0)
        with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel):
            self.window.open_selected()
        self.assertTrue(editor.hasPendingChanges())
        self.assertEqual(APP.fileManager.fileHistory, history)

    def test_unsaved_candidate_save_as_keeps_original_file(self):
        before = SOURCE.read_bytes()
        APP.fileManager.openUnsavedSnapshot(copy.deepcopy(BASELINE))
        destination = SOURCE.parent / "выбранный кандидат.ric"
        with patch.object(APP.fileManager, "showSaveDialog", return_value=str(destination)):
            APP.fileManager.save()
        self.assertEqual(SOURCE.read_bytes(), before)
        self.assertEqual(APP.fileManager.fileName, str(destination))
        self.assertEqual(APP.fileManager.savedVersion, 0)
        self.assertEqual(loadFile(destination, fileTypes.MOTOR), BASELINE)

    def test_close_window_stops_worker_without_blocking(self):
        self.configure(strategy="random", budget=1000)
        self.window.start_search()
        started = time.monotonic()
        self.window.close()
        self.assertLess(time.monotonic() - started, 0.2)
        self.wait_finished()
        self.assertIsNone(APP.window.designAssistant)
        # WA_DeleteOnClose deletes the dialog later; avoid a second close in teardown.
        self.window = self._replacement_window()

    def _replacement_window(self):
        APP.window.openDesignAssistant()
        return APP.window.designAssistant

    def test_localized_diagnostic_keeps_english_core_unchanged(self):
        self.configure(minimum=0, points=2, budget=2)
        self.search()
        evaluation = next(iter(self.window.controller.evaluations.values()))
        diagnostic = evaluation.outcome.diagnostics[0]
        before = dataclasses.asdict(diagnostic)
        english = diagnostic_text(diagnostic, self.window.options)
        APP.translationManager.setLanguage("ru")
        APP.processEvents()
        russian = diagnostic_text(diagnostic, self.window.options)
        self.assertNotEqual(english, russian)
        self.assertEqual(dataclasses.asdict(diagnostic), before)

    def test_nonfinite_result_is_rejected_with_localized_channel_diagnostic(self):
        self.configure(points=2, budget=2)
        original = Motor.runSimulation

        def nonfinite(motor, callback=None):
            result = original(motor, callback)
            result.channels["pressure"].data[-1] = math.nan
            return result

        with patch.object(Motor, "runSimulation", nonfinite):
            self.search()
        self.assertEqual(self.window._progress.errors, 2)
        self.assertTrue(all(e.score is None for e in self.window.controller.evaluations.values()))
        APP.translationManager.setLanguage("ru")
        APP.processEvents()
        diagnostic = list(self.window.controller.evaluations.values())[0].outcome.diagnostics[-1]
        text = diagnostic_text(diagnostic, self.window.options)
        self.assertIn("Давление в камере", text)
        self.assertNotIn("Nonfinite", text)

    def test_all_programmatic_and_core_messages_are_in_catalog(self):
        root = ET.parse(TRANSLATIONS_PATH / "openmotor_ru.ts").getroot()
        identities = {
            (c.findtext("name"), m.findtext("source")) for c in root.findall("context") for m in c.findall("message")
        }
        for message in (*CORE_MESSAGES, *UI_MESSAGES):
            self.assertIn((message.context, message.source), identities)
        literals = set()
        for filename in ("window.py", "results.py", "presentation.py"):
            tree = ast.parse((ROOT / "uilib/designassistant" / filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "translate":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        literals.add(node.args[0].value)
        for source in literals:
            self.assertIn(("DesignAssistant", source), identities)
        for source in ("Search: %v/%m", "Current candidate: %p%"):
            self.assertEqual(QCoreApplication.translate("DesignAssistant", source), source)

    def test_numeric_sort_is_not_lexicographic(self):
        # Table sorting must distinguish 2 vs 10 without formatting affecting order.
        self.configure(points=2, budget=2)
        self.search()
        model = self.window.model
        for index, value in enumerate((10.0, 2.0)):
            proposal, evaluation = model.rows[index]
            metrics = tuple(
                MetricValue(m.key, value if m.key == "burn_time" else m.value, m.unit)
                for m in evaluation.outcome.metrics
            )
            outcome = dataclasses.replace(evaluation.outcome, metrics=metrics)
            model.rows[index] = proposal, dataclasses.replace(evaluation, outcome=outcome)
        self.window.proxy.sort(5 + len(model.variables), Qt.SortOrder.AscendingOrder)
        first = self.window.proxy.data(self.window.proxy.index(0, 0), ID_ROLE)
        self.assertEqual(first, model.rows[1][0].candidate_id)

    def test_outcome_does_not_acquire_gui_objects(self):
        self.configure()
        self.search()
        for evaluation in self.window.controller.evaluations.values():
            self.assertIsInstance(evaluation.outcome, SimulationOutcome)
            self.assertEqual(evaluation.outcome.status, OutcomeStatus.COMPLETED)
            json.dumps(dataclasses.asdict(evaluation.outcome), allow_nan=False)


class SmartGuiTests(unittest.TestCase):
    tearDown = DesignGuiTests.tearDown
    wait_finished = DesignGuiTests.wait_finished

    def setUp(self):
        DesignGuiTests.setUp(self)
        self.window.mode.setCurrentIndex(self.window.mode.findData("smart"))
        row = self.window.smart.targets["burn_time"]
        row.enabled.setChecked(True)
        row.value.setValue(2)
        row.tolerance.setValue(1)
        self.window.smart.budget.setValue(12)
        self.window.smart.top_n.setValue(3)

    def search(self):
        self.window.startButton.click()
        self.wait_finished()
        self.warning.assert_not_called()
        self.assertEqual(self.window._state, "completed")
        return self.window.controller.smart_store.top

    def select_candidates(self, records):
        selection = self.window.table.selectionModel()
        selection.clearSelection()
        for record in records:
            row = next(
                i for i, (p, _) in enumerate(self.window.model.rows) if p.candidate_id == record.proposal.candidate_id
            )
            index = self.window.proxy.mapFromSource(self.window.model.index(row, 0))
            self.assertTrue(index.isValid())
            selection.select(index, QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
        APP.processEvents()

    def test_modes_preserve_manual_inputs(self):
        self.window.mode.setCurrentIndex(0)
        self.window.add_variable("nozzle.throat")
        before = self.window.build_requirements()
        self.window.mode.setCurrentIndex(1)
        self.assertFalse(self.window.tabs.isVisible())
        self.assertTrue(self.window.smartScroll.isVisible())
        self.assertEqual(self.window.mode.currentData(), "smart")
        self.window.mode.setCurrentIndex(0)
        self.assertEqual(self.window.build_requirements(), before)
        self.assertTrue(self.window.tabs.isVisible())

    def test_partial_targets_launch_without_manual_variables(self):
        self.assertFalse(self.window.variable_rows)
        ranked = self.search()
        self.assertTrue(ranked)
        self.assertLessEqual(len(ranked), 3)
        self.assertTrue(all(r.context.stage == "verification" for r in ranked))
        self.assertEqual(self.window._progress.stage, "ranking")
        self.assertIsNotNone(self.window._progress.best_score)
        self.assertGreater(self.window._progress.elapsed, 0)
        self.assertLessEqual(self.window._progress.processed, 12)

    def test_quality_changes_budget_only_and_estimates_simulations(self):
        from designassistant.smart import QUALITY_BUDGETS

        original = self.window.controller.baseline.to_dict()["config"]
        for key, budget in QUALITY_BUDGETS.items():
            self.window.smart.quality.setCurrentIndex(self.window.smart.quality.findData(key))
            self.assertEqual(self.window.smart.budget.value(), budget)
            self.assertIn(str(budget), self.window.smart.estimate.text())
            for variant in self.window.smart.build_plan().variants:
                self.assertEqual(variant.baseline.to_dict()["config"], original)

    def test_missing_target_reports_specific_error_without_losing_results(self):
        self.search()
        before = tuple(self.window.model.rows)
        self.window.smart.targets["burn_time"].enabled.setChecked(False)
        self.window.start_search()
        self.assertIn("Enable at least one target", self.warning.call_args.args[2])
        self.assertEqual(tuple(self.window.model.rows), before)

    def test_conflicting_requirements_prevent_worker_start(self):
        maximum = self.window.smart.constraints["burn_time"][1]
        maximum.enabled.setChecked(True)
        maximum.value.setValue(1)
        self.window.start_search()
        self.assertFalse(self.window.controller.is_running)
        self.assertIn("outside", self.warning.call_args.args[2])

    def test_library_all_subset_and_fixed_selection_use_stable_existing_keys(self):
        widget = self.window.smart
        widget.all_library.setChecked(True)
        req = widget.build_requirements()
        self.assertEqual(set(req.library_keys), {e.key for e in widget.library_entries})
        widget.all_library.setChecked(False)
        for i in range(widget.library.count()):
            widget.library.item(i).setCheckState(Qt.CheckState.Checked if i < 2 else Qt.CheckState.Unchecked)
        self.assertEqual(len(widget.build_requirements().library_keys), 2)
        widget.library.item(1).setCheckState(Qt.CheckState.Unchecked)
        self.assertEqual(len(widget.build_requirements().library_keys), 1)

    def test_compatible_geometry_selection_preserves_count_and_accuracy(self):
        widget = self.window.smart
        for i in range(widget.geometry.count()):
            widget.geometry.item(i).setCheckState(Qt.CheckState.Checked)
        built = widget.build_plan()
        self.assertGreater(len(built.variants), 1)
        for variant in built.variants:
            self.assertEqual(len(variant.baseline.to_dict()["grains"]), len(BASELINE["grains"]))
            self.assertEqual(variant.baseline.to_dict()["config"], BASELINE["config"])

    def test_same_seed_ranking_and_metrics_repeat(self):
        first = self.search()
        second = self.search()
        self.assertEqual(first, second)
        self.window.smart.seed.setValue(self.window.smart.seed.value() + 1)
        self.assertNotEqual(first, self.search())

    def test_language_roundtrip_keeps_inputs_results_selection_comparison(self):
        ranked = self.search()
        self.select_candidates(ranked[:2])
        self.window.compare_selected()
        self.window.show_details()
        inputs = self.window.smart.build_requirements()
        rows = tuple(self.window.model.rows)
        ids = self.window.selected_ids()
        comparison = self.window.comparison.records
        for language in ("en", "ru", "en"):
            APP.translationManager.setLanguage(language)
            APP.processEvents()
            self.assertEqual(self.window.smart.build_requirements(), inputs)
            self.assertEqual(tuple(self.window.model.rows), rows)
            self.assertEqual(self.window.selected_ids(), ids)
            self.assertEqual(self.window.comparison.records, comparison)
            self.assertEqual(self.window.controller.smart_store.top, ranked)
            self.assertEqual(self.window.mode.currentText(), "Умный подбор" if language == "ru" else "Smart Design")
            self.assertEqual(self.window.compareButton.text(), "Сравнить" if language == "ru" else "Compare")
            self.assertIn(
                "Суммарный импульс" if language == "ru" else "Total Impulse", self.window.details.text.toPlainText()
            )

    def test_language_does_not_influence_ranking(self):
        english = self.search()
        APP.translationManager.setLanguage("ru")
        APP.processEvents()
        self.assertEqual(self.search(), english)

    def test_top_n_filter_is_numeric_and_limits_visible_results(self):
        self.search()
        self.window.smart.top_n.setValue(2)
        APP.processEvents()
        self.assertLessEqual(self.window.proxy.rowCount(), 2)
        self.assertEqual(self.window.proxy.data(self.window.proxy.index(0, 0)), 1)
        self.window.textFilter.setText("no matching candidate")
        self.assertEqual(self.window.proxy.rowCount(), 0)

    def test_comparison_table_includes_targets_deviations_constraints_score_and_warnings(self):
        maximum = self.window.smart.constraints["maximum_pressure"][1]
        maximum.enabled.setChecked(True)
        maximum.value.setValue(1e7)
        ranked = self.search()
        self.assertGreaterEqual(len(ranked), 2)
        self.select_candidates(ranked[:2])
        self.assertTrue(self.window.compareButton.isEnabled())
        self.window.compareButton.click()
        table = self.window.comparison.table
        text = "\n".join(
            table.item(r, c).text()
            for r in range(table.rowCount())
            for c in range(table.columnCount())
            if table.item(r, c) is not None
        )
        self.assertIn("Score", text)
        self.assertIn("Warnings", text)
        self.assertIn("Target Value", text)
        self.assertIn("Maximum", text)
        self.assertEqual(table.columnCount(), 5)
        self.assertEqual(self.window.comparison.records, tuple(ranked[:2]))

    def test_invalid_candidate_does_not_terminate_smart_search(self):
        original = Motor.runSimulation
        calls = 0

        def fail_once(motor, callback=None):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("Injected Smart candidate failure")
            return original(motor, callback)

        with patch.object(Motor, "runSimulation", fail_once):
            ranked = self.search()
        self.assertTrue(ranked)
        self.assertEqual(self.window._progress.errors, 1)

    def test_warning_policy_uses_existing_constraint_evaluator(self):
        self.window.smart.reject_warnings.setChecked(True)
        ranked = self.search()
        self.assertTrue(self.window.controller.smart_plan.requirements.reject_warnings)
        self.assertTrue(all(not any(d.level == "WARNING" for d in r.evaluation.outcome.diagnostics) for r in ranked))

    def test_stop_retains_finished_results_and_baseline(self):
        self.window.smart.budget.setValue(1000)
        self.window.controller.progressChanged.connect(
            lambda p: self.window.stop_search() if p.processed >= 1 and self.window.controller.is_running else None
        )
        self.window.start_search()
        self.wait_finished()
        self.assertEqual(self.window._state, "stopped")
        self.assertGreaterEqual(len(self.window.model.rows), 1)
        self.assertLess(self.window._progress.processed, 1000)
        self.assertEqual(self.window.controller.baseline, self.original_snapshot)
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), self.original_snapshot)

    def test_smart_worker_keeps_gui_timer_and_receivers_on_gui_thread(self):
        ticks, receivers = [], []
        timer = QTimer()
        timer.setInterval(2)
        timer.timeout.connect(lambda: ticks.append(time.monotonic()))
        self.window.controller.candidateReady.connect(lambda *_: receivers.append(QThread.currentThread()))
        timer.start()
        original = Motor.runSimulation

        def slow_calculation(motor, callback=None):
            time.sleep(0.02)
            return original(motor, callback)

        with patch.object(Motor, "runSimulation", slow_calculation):
            self.search()
        timer.stop()
        self.assertGreater(len(ticks), 5)
        self.assertTrue(receivers)
        self.assertTrue(all(thread == APP.thread() for thread in receivers))

    def test_unsaved_handoff_contains_selected_library_and_parameters_without_source_write(self):
        source = SOURCE.read_bytes()
        ranked = self.search()
        self.select_candidates(ranked[:1])
        request = self.window.controller.request_for(ranked[0].proposal.candidate_id)
        self.window.open_selected()
        self.assertIsNone(APP.fileManager.fileName)
        self.assertEqual(APP.fileManager.savedVersion, -1)
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), request.snapshot)
        self.assertEqual(SOURCE.read_bytes(), source)
        self.assertEqual(self.window.controller.baseline, self.original_snapshot)

    def test_unsaved_check_cancel_blocks_smart_handoff(self):
        ranked = self.search()
        self.select_candidates(ranked[:1])
        APP.fileManager.savedVersion = -1
        history = copy.deepcopy(APP.fileManager.fileHistory)
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            self.window.open_selected()
        self.assertEqual(APP.fileManager.fileHistory, history)
        self.assertEqual(APP.fileManager.fileName, str(SOURCE))

    def test_smart_messages_and_literals_have_complete_russian_catalog_entries(self):
        root = ET.parse(TRANSLATIONS_PATH / "openmotor_ru.ts").getroot()
        messages = {
            (c.findtext("name"), m.findtext("source")): m for c in root.findall("context") for m in c.findall("message")
        }
        for marker in SMART_MESSAGES:
            message = messages[(marker.context, marker.source)]
            self.assertTrue(message.findtext("translation"))
            self.assertNotEqual(message.find("translation").get("type"), "unfinished")
        for filename in ("smart_form.py", "smart_results.py"):
            tree = ast.parse((ROOT / "uilib/designassistant" / filename).read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "translate":
                    if node.args and isinstance(node.args[0], ast.Constant):
                        self.assertIn(("DesignAssistant", node.args[0].value), messages)


class QuickDesignGuiTests(unittest.TestCase):
    def setUp(self):
        APP.translationManager.setLanguage("en")
        APP.processEvents()
        APP.window.ui.motorEditor.close()
        saveFile(SOURCE, copy.deepcopy(BASELINE), fileTypes.MOTOR)
        APP.fileManager.startFromMotor(Motor(copy.deepcopy(BASELINE)), str(SOURCE), checkPropellant=False)
        APP.window.postLoadUpdate()
        self.original = Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict())
        self.source_bytes = SOURCE.read_bytes()
        APP.window.quickDesignAction.trigger()
        self.window = APP.window.quickDesign
        self.window.allowed_keys = (Snapshot.from_dict(BASELINE["propellant"]).digest,)
        self.warnings = patch.object(QMessageBox, "warning", return_value=QMessageBox.StandardButton.Ok)
        self.warning = self.warnings.start()

    def tearDown(self):
        self.window.controller.stop()
        self.wait_finished()
        for advanced in list(APP.window.quickAdvancedWindows):
            advanced.controller.stop()
            deadline = time.monotonic() + 30
            while advanced.controller.is_running and time.monotonic() < deadline:
                APP.processEvents()
                time.sleep(0.002)
            advanced.close()
        if APP.window.designAssistant is not None:
            APP.window.designAssistant.stop_search()
            APP.window.designAssistant.close()
        APP.translationManager.setLanguage("en")
        APP.processEvents()
        self.window.close()
        APP.processEvents()
        APP.processEvents()
        APP.window.ui.motorEditor.close()
        self.warnings.stop()

    def wait_finished(self):
        deadline = time.monotonic() + 30
        while self.window.controller.is_running and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.002)
        APP.processEvents()
        self.assertFalse(self.window.controller.is_running)

    def configure(self):
        for key, value in (("diameter", 0.05), ("length", 0.02), ("burn_time", 2)):
            row = self.window.rows[key]
            row.value.setValue(convert(value, row.unit, row.display_unit))

    def search(self, budget=12):
        self.configure()
        self.window.start_search(budget=budget)
        self.wait_finished()
        self.warning.assert_not_called()
        self.assertEqual(self.window._state, "completed")
        self.assertTrue(self.window.recommendations)
        return self.window.recommendations

    def test_separate_tools_action_and_manual_window_preserved(self):
        APP.window.designAssistantAction.trigger()
        advanced = APP.window.designAssistant
        self.assertEqual(advanced.mode.currentData(), "manual")
        self.assertEqual(self.window.windowTitle(), "Quick Design")
        self.assertIsNot(self.window, advanced)
        self.window.next_button.click()
        self.warning.assert_called_once()
        self.assertEqual(advanced.mode.currentData(), "manual")

    def test_no_target_does_not_start_worker(self):
        self.window.find_button.click()
        self.warning.assert_called_once()
        self.assertFalse(self.window.controller.is_running)
        self.assertEqual(self.window.controller.evaluations, {})

    def test_three_step_workflow(self):
        self.configure()
        self.assertEqual(self.window.pages.currentIndex(), 0)
        self.window.next_button.click()
        self.assertEqual(self.window.pages.currentIndex(), 1)
        self.assertTrue(self.window.problem)
        self.assertIn("Automatic options", self.window.review.toPlainText())
        self.window.start_search(budget=12)
        self.assertEqual(self.window.pages.currentIndex(), 2)
        self.wait_finished()
        self.assertLessEqual(len(self.window.cards), 5)
        self.assertTrue(self.window.cards)
        self.window.back_button.click()
        self.assertEqual(self.window.pages.currentIndex(), 1)

    def test_mm_m_conversion_and_si_problem_boundary(self):
        from uilib.designassistant.quick_window import QuickDesignWindow
        from uilib.preferencesManager import Preferences

        pref = Preferences(APP.preferencesManager.preferences.getDict())
        pref.units.setProperty("m", "mm")
        window = QuickDesignWindow(BASELINE, pref, library_entries=[BASELINE["propellant"]])
        try:
            window.rows["diameter"].value.setValue(100)
            window.rows["length"].enabled.setChecked(True)
            window.rows["length"].value.setValue(500)
            window.rows["burn_time"].enabled.setChecked(True)
            window.rows["burn_time"].value.setValue(3)
            requirements = window.build_requirements()
            self.assertEqual(
                requirements.criteria,
                (
                    QuickCriterion("diameter", "maximum", 0.1),
                    QuickCriterion("length", "maximum", 0.5),
                    QuickCriterion("burn_time", "target", 3),
                ),
            )
            self.assertEqual(window.rows["burn_time"].unit, "s")
            self.assertEqual(window.rows["average_thrust"].unit, "N")
            self.assertEqual(window.rows["total_impulse"].unit, "Ns")
        finally:
            window.close()
            APP.processEvents()

    def test_thrust_impulse_and_time_convert_using_existing_units(self):
        self.configure()
        for key, internal_value in (("burn_time", 3), ("average_thrust", 50), ("total_impulse", 100)):
            row = self.window.rows[key]
            row.enabled.setChecked(True)
            row.value.setValue(convert(internal_value, row.unit, row.display_unit))
        req = self.window.build_requirements()
        self.assertEqual(
            {c.field: c.value for c in req.criteria if c.field not in ("diameter", "length")},
            {"burn_time": 3, "average_thrust": 50, "total_impulse": 100},
        )

    def test_mandatory_modes_are_stable_and_hidden(self):
        self.configure()
        before = self.window.build_requirements()
        APP.translationManager.setLanguage("ru")
        APP.processEvents()
        self.assertEqual(self.window.rows["diameter"].mode.currentData(), "maximum")
        self.assertEqual(self.window.rows["burn_time"].mode.currentData(), "target")
        self.assertTrue(all(row.mode.isHidden() for row in self.window.rows.values()))
        self.assertEqual(self.window.build_requirements(), before)

    def test_conflicting_target_and_optional_limit_do_not_launch(self):
        self.configure()
        self.window.other_group.setChecked(True)
        maximum = self.window.constraints["burn_time"][1]
        maximum.enabled.setChecked(True)
        maximum.value.setValue(1)
        self.window.start_search(budget=12)
        self.warning.assert_called_once()
        self.assertFalse(self.window.controller.is_running)

    def test_quality_estimate_uses_existing_presets(self):
        self.configure()
        for key, value in (("quick", 60), ("balanced", 180), ("thorough", 540)):
            self.window.quality.setCurrentIndex(self.window.quality.findData(key))
            self.assertIn(str(value), self.window.estimate_label.text())
            self.assertEqual(self.window.build_requirements().simulation_budget, value)

    def test_library_chooser_language_preserves_checked_stable_keys(self):
        from uilib.designassistant.quick_window import LibraryChooser

        chooser = LibraryChooser(self.window)
        try:
            chooser.compatible.setChecked(False)
            keys = chooser.selected_keys()
            for language in ("ru", "en"):
                APP.translationManager.setLanguage(language)
                APP.processEvents()
                self.assertEqual(chooser.selected_keys(), keys)
                self.assertEqual(
                    chooser.windowTitle(),
                    "Допустимые варианты библиотеки" if language == "ru" else "Allowed library entries",
                )
        finally:
            chooser.close()
            chooser.deleteLater()

    def test_candidate_exception_does_not_abort_quick_search(self):
        from designassistant import EngineAdapter

        original = EngineAdapter.run
        calls = []

        def fail_one(adapter, request, **kwargs):
            calls.append(request.proposal.candidate_id)
            if len(calls) == 1:
                raise RuntimeError("Candidate test failure")
            return original(adapter, request, **kwargs)

        with patch.object(EngineAdapter, "run", fail_one):
            self.search()
        self.assertGreater(len(calls), 1)
        self.assertGreater(self.window._progress.errors, 0)
        self.assertTrue(self.window.recommendations)

    def test_quick_unapplied_editor_cancel_preserves_project(self):
        result = self.search()[0]
        with (
            patch.object(APP.window.ui.motorEditor, "hasPendingChanges", return_value=True),
            patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Cancel),
        ):
            self.window.cards[result.proposal.candidate_id].open_button.click()
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), self.original)
        self.assertEqual(SOURCE.read_bytes(), self.source_bytes)

    def test_exact_same_seed_search(self):
        first = self.search()
        second = self.search()
        self.assertEqual(first, second)

    def test_cards_explanations_and_technical_details(self):
        results = self.search()
        card = self.window.cards[results[0].proposal.candidate_id]
        self.assertIn("Match:", card.summary.text())
        self.assertIn("Peak Thrust", card.summary.text())
        self.assertIn("Library entry", card.summary.text())
        self.assertNotIn("grains.", card.summary.text())
        self.assertTrue(card.why.text())
        card.why_button.click()
        self.assertFalse(card.why.isHidden())
        card.details_button.click()
        self.assertEqual(self.window.details.candidate_id, results[0].proposal.candidate_id)
        self.assertIn("Parameters", self.window.details.text.toPlainText())
        self.assertIn("simulation-based", self.window.notice.text())

    def test_compare_two_to_three_reuses_smart_dialog(self):
        results = self.search()
        self.assertGreaterEqual(len(results), 2)
        for record in results[:2]:
            self.window.cards[record.proposal.candidate_id].selected.setChecked(True)
        self.assertTrue(self.window.compare_button.isEnabled())
        self.window.compare_button.click()
        self.assertEqual(self.window.comparison.records, results[:2])
        self.assertEqual(len(self.window.comparison.definitions), 11)

    def test_english_russian_english_preserves_problem_cards_and_selection(self):
        results = self.search()
        before = self.window.build_requirements()
        first_id = results[0].proposal.candidate_id
        self.window.cards[first_id].selected.setChecked(True)
        for language in ("en", "ru", "en"):
            APP.translationManager.setLanguage(language)
            APP.processEvents()
            self.assertEqual(self.window.build_requirements(), before)
            self.assertEqual(self.window.recommendations, results)
            self.assertEqual(self.window.selected_ids(), (first_id,))
            self.assertEqual(
                self.window.windowTitle(), "Быстрое проектирование" if language == "ru" else "Quick Design"
            )
            self.assertEqual(
                APP.window.quickDesignAction.text(),
                "Быстрое проектирование..." if language == "ru" else "Quick Design...",
            )
            self.assertIn("Соответствие:" if language == "ru" else "Match:", self.window.cards[first_id].summary.text())
            self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), self.original)

    def test_language_independent_ranking(self):
        before = self.search()
        APP.translationManager.setLanguage("ru")
        APP.processEvents()
        after = self.search()
        self.assertEqual(before, after)

    def test_stop_retains_completed_results(self):
        self.configure()
        self.window.start_search(budget=10000)
        deadline = time.monotonic() + 30
        while not self.window.controller.evaluations and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.002)
        self.assertTrue(self.window.controller.evaluations)
        self.window.stop_button.click()
        self.wait_finished()
        self.assertEqual(self.window._state, "stopped")
        self.assertLess(self.window._progress.processed, 10000)
        self.assertTrue(self.window.controller.evaluations)
        self.assertIn("provisional", self.window.results_hint.text())

    def test_gui_responsive_while_existing_simulation_runs(self):
        self.configure()
        ticks = []
        timer = QTimer()
        timer.setInterval(2)
        timer.timeout.connect(lambda: ticks.append(QThread.currentThread()))
        timer.start()
        original = Motor.runSimulation

        def delayed(motor, callback=None):
            time.sleep(0.02)
            return original(motor, callback)

        with patch.object(Motor, "runSimulation", delayed):
            self.window.start_search(budget=12)
            self.wait_finished()
        timer.stop()
        self.assertGreater(len(ticks), 5)
        self.assertTrue(all(thread == APP.thread() for thread in ticks))

    def test_baseline_and_source_file_unchanged_after_search(self):
        self.search()
        self.assertEqual(self.window.controller.baseline, self.original)
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), self.original)
        self.assertEqual(SOURCE.read_bytes(), self.source_bytes)

    def test_open_candidate_creates_new_unsaved_project(self):
        result = self.search()[0]
        expected = self.window.controller.request_for(result.proposal.candidate_id).snapshot
        self.window.cards[result.proposal.candidate_id].open_button.click()
        self.assertIsNone(APP.fileManager.fileName)
        self.assertEqual(APP.fileManager.savedVersion, -1)
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), expected)
        self.assertEqual(self.window.controller.baseline, self.original)
        self.assertEqual(SOURCE.read_bytes(), self.source_bytes)

    def test_unsaved_project_cancel_preserves_original(self):
        result = self.search()[0]
        APP.fileManager.savedVersion = -1
        with patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.Cancel):
            self.window.cards[result.proposal.candidate_id].open_button.click()
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), self.original)
        self.assertEqual(SOURCE.read_bytes(), self.source_bytes)

    def test_quick_to_advanced_transfers_editable_problem_and_preserves_existing_window(self):
        self.configure()
        self.window.other_group.setChecked(True)
        low, high, _ = self.window.constraints["burn_time"]
        low.enabled.setChecked(True)
        low.value.setValue(0.001)
        high.enabled.setChecked(True)
        high.value.setValue(100)
        mass_minimum = self.window.constraints["propellant_mass"][0]
        mass_minimum.enabled.setChecked(True)
        from uilib.designassistant.presentation import metric_unit

        unit, display = metric_unit("propellant_mass", self.window.preferences)
        mass_minimum.value.setValue(convert(0.0001, unit, display))
        APP.window.designAssistantAction.trigger()
        original_advanced = APP.window.designAssistant
        results = self.search()
        selected_snapshot = self.window.controller.request_for(results[0].proposal.candidate_id).snapshot
        window = self.window.open_advanced()
        self.assertEqual(window.controller.baseline, selected_snapshot)
        self.assertIs(APP.window.designAssistant, original_advanced)
        self.assertIsNot(window, original_advanced)
        self.assertEqual(window.mode.currentData(), "manual")
        problem = self.window._validated()
        variant = results[0].variant
        transferred = window.build_requirements()
        self.assertTrue(transferred.variables)
        self.assertEqual(len(transferred.variables), len(variant.requirements.variables))
        self.assertEqual([t.metric for t in transferred.targets], [t.metric for t in variant.requirements.targets])
        bounds = {}
        for constraint in variant.requirements.constraints:
            low, high = bounds.get(constraint.metric, (None, None))
            if constraint.minimum is not None:
                low = constraint.minimum if low is None else max(low, constraint.minimum)
            if constraint.maximum is not None:
                high = constraint.maximum if high is None else min(high, constraint.maximum)
            bounds[constraint.metric] = low, high
        self.assertEqual({c.metric for c in transferred.constraints}, set(bounds))
        for constraint in transferred.constraints:
            for expected, actual in zip(bounds[constraint.metric], (constraint.minimum, constraint.maximum)):
                if expected is None:
                    self.assertIsNone(actual)
                else:
                    self.assertAlmostEqual(actual, expected, places=10)
        self.assertEqual(window.seed.value(), problem.requirements.seed)
        self.assertEqual(window.budget.value(), problem.requirements.simulation_budget)
        self.assertEqual(len(window.controller.registry.definitions), 11)
        self.assertEqual(Snapshot.from_dict(APP.fileManager.getCurrentMotor().getDict()), self.original)
        window.budget.setValue(2)
        window.start_search()
        deadline = time.monotonic() + 30
        while window.controller.is_running and time.monotonic() < deadline:
            APP.processEvents()
            time.sleep(0.002)
        self.assertFalse(window.controller.is_running)
        self.assertEqual(window._state, "completed")
        self.warning.assert_not_called()

    def test_selected_option_survives_changed_goals_on_advanced_handoff(self):
        results = self.search()
        record = results[-1]
        self.window.cards[record.proposal.candidate_id].selected.setChecked(True)
        self.window.rows["burn_time"].value.setValue(3)
        advanced = self.window.open_advanced()
        data = advanced.controller.baseline.to_dict()
        self.assertEqual(Snapshot.from_dict(data["propellant"]).digest, record.variant.library_key)
        self.assertEqual(tuple(g["type"] for g in data["grains"]), record.variant.geometries)
        self.assertEqual(advanced.build_requirements().targets[0].value, 3)

    def test_v2_numpy_numeric_warning_translates_without_formatting_exception(self):
        import numpy as np

        from designassistant.models import Diagnostic, TextRecord
        from motorlib.localization import QT_TRANSLATE_NOOP

        before = TextRecord.from_engine(
            QT_TRANSLATE_NOOP("SimulationAlerts", "Initial port/throat ratio of {:.3f} was less than {:.3f}").format(
                np.float64(1.25), np.float32(2)
            )
        )
        diagnostic = Diagnostic("engine_alert", "WARNING", before)
        for language in ("en", "ru", "en"):
            APP.translationManager.setLanguage(language)
            APP.processEvents()
            text = diagnostic_text(diagnostic)
            self.assertIn("1.250", text)
            self.assertIn("2.000", text)
            self.assertEqual(diagnostic.message, before)

    def test_v2_required_fields_and_first_page_library_quality(self):
        self.assertEqual(self.window.pages.currentIndex(), 0)
        for key in ("diameter", "length", "burn_time"):
            row = self.window.rows[key]
            self.assertTrue(row.enabled.isChecked())
            self.assertTrue(row.enabled.isHidden())
            self.assertTrue(row.value.isEnabled())
            self.assertIn("*", row.label.text())
        for key in ("average_thrust", "total_impulse"):
            row = self.window.rows[key]
            self.assertFalse(row.enabled.isChecked())
            self.assertFalse(row.value.isEnabled())
        self.assertTrue(self.window.quality.isVisibleTo(self.window.pages.widget(0)))
        self.assertTrue(self.window.choose_button.isVisibleTo(self.window.pages.widget(0)))
        self.assertFalse(self.window.find_button.isHidden())
        self.assertFalse(self.window.advanced_button.isEnabled())

    def test_v2_empty_editor_full_search_and_safe_advanced_handoff(self):
        self.window.close()
        APP.processEvents()
        empty = Motor().getDict()
        empty["config"] = copy.deepcopy(BASELINE["config"])
        empty = Motor(empty).getDict()
        APP.fileManager.startFromMotor(Motor(empty), None, checkPropellant=False)
        APP.window.postLoadUpdate()
        APP.window.quickDesignAction.trigger()
        self.window = APP.window.quickDesign
        self.window.allowed_keys = (Snapshot.from_dict(BASELINE["propellant"]).digest,)
        results = self.search()
        self.assertEqual(self.window.controller.baseline, Snapshot.from_dict(empty))
        self.assertEqual(APP.fileManager.getCurrentMotor().getDict(), empty)
        self.assertEqual(SOURCE.read_bytes(), self.source_bytes)
        record = results[0]
        snapshot = self.window.controller.request_for(record.proposal.candidate_id).snapshot
        advanced = self.window.open_advanced()
        self.assertEqual(advanced.controller.baseline, snapshot)
        self.assertTrue(advanced.variable_rows)
        self.assertEqual([t.metric for t in advanced.build_requirements().targets], ["burn_time"])
        self.assertEqual(APP.fileManager.getCurrentMotor().getDict(), empty)
        self.assertEqual(SOURCE.read_bytes(), self.source_bytes)

    def test_v2_review_lists_created_geometries_and_grain_counts(self):
        self.configure()
        for key, value in (("diameter", 0.1), ("length", 0.8)):
            row = self.window.rows[key]
            row.value.setValue(convert(value, row.unit, row.display_unit))
        self.window.next()
        text = self.window.review.toPlainText()
        self.assertIn("Geometries to explore", text)
        self.assertIn("Star Grain", text)
        self.assertIn("Custom Grain", text)
        self.assertIn("Grain counts to explore: 1, 2, 3, 4, 5, 6", text)
        self.assertNotIn("baseline parameters cannot initialize", text)
        self.assertFalse(self.window.controller.is_running)

    def test_v2_optional_goals_are_absent_until_enabled(self):
        self.configure()
        req = self.window._validated()
        self.assertEqual([t.metric for t in req.plan.requirements.targets], ["burn_time"])
        row = self.window.rows["average_thrust"]
        row.enabled.setChecked(True)
        row.value.setValue(50)
        self.assertEqual(
            [t.metric for t in self.window._validated().plan.requirements.targets], ["burn_time", "average_thrust"]
        )

    def test_v2_unrequested_thrust_and_impulse_are_labelled_as_results(self):
        results = self.search()
        card = self.window.cards[results[0].proposal.candidate_id]
        self.assertEqual(card.summary.text().count("Obtained result"), 2)
        APP.translationManager.setLanguage("ru")
        APP.processEvents()
        self.assertEqual(card.summary.text().count("Полученный результат"), 2)
        self.assertIn("Число шашек", card.summary.text())
        self.assertEqual(results, self.window.recommendations)

    def test_v2_conflicting_goals_warn_before_starting_worker(self):
        self.configure()
        for key, value in (("average_thrust", 50), ("total_impulse", 10000)):
            row = self.window.rows[key]
            row.enabled.setChecked(True)
            row.value.setValue(value)
        order = []
        original = self.window.controller.start_smart

        def start(plan):
            order.append("start")
            return original(plan)

        self.warning.side_effect = lambda *args, **kwargs: order.append("warning")
        with patch.object(self.window.controller, "start_smart", side_effect=start):
            self.window.start_search(budget=12)
            self.window.stop_search()
            self.wait_finished()
        self.assertEqual(order, ["warning", "start"])
        self.assertTrue(self.window.problem.target_warning)

    def test_v2_language_round_trip_preserves_mandatory_fields_and_optional_flags(self):
        self.configure()
        row = self.window.rows["total_impulse"]
        row.enabled.setChecked(True)
        row.value.setValue(80)
        before = self.window.build_requirements()
        for language in ("ru", "en"):
            APP.translationManager.setLanguage(language)
            APP.processEvents()
            self.assertEqual(self.window.build_requirements(), before)
            self.assertEqual(self.window.rows["diameter"].mode.currentData(), "maximum")
            self.assertTrue(row.enabled.isChecked())
            self.assertIn("*", self.window.rows["burn_time"].label.text())

    def test_all_quick_literals_and_markers_have_complete_catalog_entries(self):
        from uilib.designassistant.quick_messages import QUICK_MESSAGES

        catalog = ET.parse(TRANSLATIONS_PATH / "openmotor_ru.ts").getroot()
        messages = {
            (c.findtext("name"), m.findtext("source")): m
            for c in catalog.findall("context")
            for m in c.findall("message")
        }
        for marker in QUICK_MESSAGES:
            entry = messages[(marker.context, marker.source)]
            self.assertTrue(entry.findtext("translation"))
            self.assertNotEqual(entry.find("translation").get("type"), "unfinished")
        tree = ast.parse((ROOT / "uilib/designassistant/quick_window.py").read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "quick_translate":
                if node.args and isinstance(node.args[0], ast.Constant):
                    self.assertIn(("QuickDesign", node.args[0].value), messages)


if __name__ == "__main__":
    unittest.main()
