"""Check the native build inputs without requiring a Windows host."""

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("windows_common", ROOT / "pyinstaller/windows_common.py")
windows_common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(windows_common)


class PackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt6.QtCore import QCoreApplication

        cls.application = QCoreApplication.instance() or QCoreApplication([])

    def test_compiled_catalog_is_current_and_loadable(self):
        from PyQt6.QtCore import QCoreApplication, QTranslator

        translator = QTranslator()
        path = ROOT / "uilib/translations/openmotor_ru.qm"
        self.assertTrue(translator.load(str(path)))
        catalog = ET.parse(path.with_suffix(".ts")).getroot()
        self.application.installTranslator(translator)
        try:
            for context in catalog.findall("context"):
                for message in context.findall("message"):
                    self.assertEqual(
                        QCoreApplication.translate(
                            context.findtext("name"), message.findtext("source"), message.findtext("comment")
                        ),
                        message.findtext("translation"),
                    )
        finally:
            self.application.removeTranslator(translator)

    def test_both_specs_resolve_inputs_from_the_shared_helper(self):
        for filename in ("winOneFile.spec", "winMultiFile.spec"):
            text = (ROOT / "pyinstaller" / filename).read_text()
            self.assertIn("Path(SPECPATH)", text)
            self.assertIn("from windows_common import ROOT, analysis", text)
            self.assertIn("a = analysis()", text)
            for obsolete in ("a.zipped_data", "a.zipfiles", "cipher=", "win_private_assemblies"):
                self.assertNotIn(obsolete, text)

    def test_runtime_resources_and_official_qt_catalog_are_included(self):
        from PyQt6.QtCore import QLibraryInfo

        datas = windows_common.runtime_datas()
        destinations = {Path(source).name: target for source, target in datas}
        self.assertEqual(destinations["resources"], "resources")
        self.assertEqual(destinations["openmotor_ru.qm"], "uilib/translations")
        self.assertEqual(destinations["qtbase_ru.qm"], "uilib/translations")
        qtbase = next(source for source, _ in datas if Path(source).name == "qtbase_ru.qm")
        self.assertEqual(Path(qtbase).parent, Path(QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)))
        self.assertTrue(all(Path(source).is_absolute() and Path(source).exists() for source, _ in datas))

    def test_catalog_paths_do_not_depend_on_cwd(self):
        original = os.getcwd()
        expected = windows_common.runtime_datas()
        with tempfile.TemporaryDirectory(prefix="openmotor-пути-") as directory:
            try:
                os.chdir(directory)
                self.assertEqual(windows_common.runtime_datas(), expected)
            finally:
                # Windows cannot remove a directory while it is the process cwd.
                os.chdir(original)

    def test_missing_application_catalog_fails_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "openmotor_ru.qm"):
                windows_common.runtime_datas(directory)

    def test_missing_official_qt_catalog_fails_before_build(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(FileNotFoundError, "qtbase_ru.qm"):
                windows_common.runtime_datas(qt_translations=directory)

    def test_engine_manifest_and_numerical_metadata_are_bundled(self):
        datas = windows_common.runtime_datas()
        manifest_path = next(Path(source) for source, target in datas if target == "designassistant")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], 1)
        self.assertIn("motorlib/motor.py", manifest["files"])
        self.assertIn("mathlib/_find_perimeter.py", manifest["files"])
        targets = [target for _, target in datas]
        for package in ("numpy", "scipy", "scikit_fmm", "scikit_image"):
            self.assertTrue(
                any(target.startswith(package + "-") and target.endswith(".dist-info") for target in targets)
            )

    def test_frozen_fingerprint_matches_source_manifest(self):
        import designassistant.provenance as provenance

        expected = provenance.engine_fingerprint()
        datas = windows_common.runtime_datas()
        source = next(Path(path) for path, target in datas if target == "designassistant")
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "engine-manifest.json").write_bytes(source.read_bytes())
            with (
                patch.object(provenance, "__file__", str(Path(directory) / "provenance.py")),
                patch.object(sys, "frozen", True, create=True),
            ):
                self.assertEqual(provenance.engine_fingerprint(), expected)

    def test_analysis_explicitly_includes_design_assistant(self):
        with patch("PyInstaller.building.build_main.Analysis") as analysis:
            windows_common.analysis()
        imports = analysis.call_args.kwargs["hiddenimports"]
        self.assertIn("designassistant", imports)
        self.assertIn("uilib.designassistant.window", imports)
        self.assertIn("uilib.designassistant.controller", imports)

    def test_windows_workflow_delivers_folder_as_downloadable_zip(self):
        import yaml

        workflow = yaml.load((ROOT / ".github/workflows/windows-build.yml").read_text(), Loader=yaml.BaseLoader)
        self.assertIn("workflow_dispatch", workflow["on"])
        job = workflow["jobs"]["windows"]
        self.assertEqual(job["runs-on"], "windows-2022")
        artifacts = [step for step in job["steps"] if step.get("uses") == "actions/upload-artifact@v4"]
        release = next(step for step in artifacts if step["with"]["name"] == "openMotor-Windows-x64")
        self.assertEqual(release["with"]["path"], "dist/windows/onedir/openMotor/")
        commands = "\n".join(step.get("run", "") for step in job["steps"])
        self.assertIn("--mode onedir", commands)
        self.assertIn("packagingProbe.spec", commands)
        self.assertIn('"first", "restart", "english"', commands)

    def test_windows_preparation_runs_core_and_gui_suites(self):
        from scripts.build_windows import prepare

        with patch("scripts.build_windows.run") as run:
            prepare()
        calls = [call.args for call in run.call_args_list]
        for suite in ("test/designassistant", "test/designassistant_gui"):
            self.assertIn(("-m", "unittest", "discover", "-s", suite, "-v"), calls)

    def test_windows_builder_refuses_cross_compilation(self):
        if sys.platform == "win32":
            with patch("scripts.build_windows.sys.platform", "linux"):
                from scripts.build_windows import main

                with patch.object(sys, "argv", ["build_windows.py"]):
                    with self.assertRaises(SystemExit) as error:
                        main()
                    self.assertEqual(error.exception.code, 2)
        else:
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/build_windows.py")],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("cannot cross-compile", result.stderr)

    def test_unicode_logging_with_a_legacy_windows_default_encoding(self):
        # Emulate a Western Windows ANSI default, without changing OS locale.
        # A Cyrillic path in a log must not stop the packaged application's UI.
        with tempfile.TemporaryDirectory(prefix="openmotor-журнал-") as directory:
            script = f"""
import builtins
from pathlib import Path
import platformdirs
platformdirs.user_log_dir = lambda *a, **k: {directory!r}
real_open = builtins.open
def legacy_open(path, mode="r", *args, **kwargs):
    if str(path).endswith("openMotor.log") and mode == "a":
        kwargs.setdefault("encoding", "cp1252")
    return real_open(path, mode, *args, **kwargs)
builtins.open = legacy_open
from uilib.logger import logger
message = "Путь C:/Двигатели/двигатель №1.ric"
logger.log(message)
logger._file.close()
assert message in (Path({directory!r}) / "openMotor.log").read_text(encoding="utf-8")
"""
            environment = dict(
                os.environ,
                PYTHONIOENCODING="utf-8",
                MPLCONFIGDIR=directory,
                XDG_CACHE_HOME=directory,
                XDG_STATE_HOME=directory,
            )
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                encoding="utf-8",
                timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
