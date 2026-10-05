"""Replay the pre-localization sources on the build host, without changing them.

Linux golden hashes remain committed and unchanged. Native Windows builds use
an independent replay of this pinned ancestor to test exact compatibility on
the same Python/numerical runtime, rather than compare Windows libm to Linux.
This is a build/test helper; it is not imported by the release application.
"""

import argparse
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE_COMMIT = "dcc7fd62045d55036451b833f60e16a786f4685d"
REFERENCE_ENV = "OPENMOTOR_COMPATIBILITY_REFERENCE_DIR"


def load_reference(name):
    """Select verified independent build-host references, or committed goldens."""
    directory = os.environ.get(REFERENCE_ENV)
    if not directory:
        return json.loads((ROOT / "test/localization/data" / name).read_text())
    directory = Path(directory)
    provenance = json.loads((directory / "provenance.json").read_text())
    runtime = {package: version(package) for package in ("numpy", "scipy", "scikit-fmm", "scikit-image")}
    if (
        provenance.get("source_commit") != BASE_COMMIT
        or provenance.get("platform") != sys.platform
        or provenance.get("python") != sys.version
        or provenance.get("numerical_runtime") != runtime
        or provenance.get("fixtures") != 18
    ):
        raise ValueError("Compatibility references must replay the pinned ancestor on this exact build runtime.")
    return json.loads((directory / name).read_text())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def replay(source, output, settings):
    # Imports must resolve to the archived ancestor, never the current engine.
    sys.path.insert(0, str(source))
    os.chdir(source)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["MPLCONFIGDIR"] = str(source / "user" / "matplotlib")
    import platformdirs

    data = source / "user" / "preferences"
    data.mkdir(parents=True)
    platformdirs.user_data_dir = lambda *args, **kwargs: str(data)
    platformdirs.user_log_dir = lambda *args, **kwargs: str(source / "user" / "logs")

    import uilib  # select the original application's Qt backend first
    from app import App
    from motorlib.motor import Motor
    from uilib.converters import BurnSimExporter, CsvExporter, EngExporter
    from uilib.defaults import DEFAULT_PREFERENCES
    from uilib.fileIO import fileTypes, loadFile, saveFile
    from uilib.preferencesManager import Preferences

    for module in ("motorlib.motor", "motorlib.simResult", "uilib.fileIO", "uilib.converters.engExporter"):
        assert Path(sys.modules[module].__file__).resolve().is_relative_to(source)
    assert Path(uilib.__file__).resolve().is_relative_to(source)
    app = App(["compatibility-baseline"])
    models = {}
    simple = None
    for path in sorted((source / "test/data").rglob("*.ric")):
        motor = Motor(loadFile(path, fileTypes.MOTOR))
        result = motor.runSimulation()
        models[path.relative_to(source).as_posix()] = digest(
            {
                "motor": motor.getDict(),
                "success": result.success,
                "channels": {key: channel.data for key, channel in result.channels.items()},
                "alerts": [(a.level.value, a.type.value, str(a.location), str(a.description)) for a in result.alerts],
            }
        )
        if path.relative_to(source).as_posix() == "test/data/regression/simple/motor.ric":
            simple = result
    assert simple is not None and len(models) == 18
    stage = {
        "source": f"Independent original source {BASE_COMMIT} on {platform.platform()}",
        "eng_config": settings,
        "channels_sha256": digest({key: channel.data for key, channel in simple.channels.items()}),
        "sha256": {},
    }
    manager = app.importExportManager
    manager.motor, manager.simRes = simple.motor, simple
    manager.preferences = Preferences(DEFAULT_PREFERENCES)
    for extension, kind, config in (
        ("csv", CsvExporter, [[], []]),
        ("eng", EngExporter, settings),
        ("bsx", BurnSimExporter, None),
    ):
        exporter = next(c for c in manager.conversions if isinstance(c, kind))
        exporter.doConversion(output / f"reference.{extension}", config)
    saveFile(output / "reference.ric", simple.motor.getDict(), fileTypes.MOTOR)
    for extension in ("csv", "eng", "bsx", "ric"):
        path = output / f"reference.{extension}"
        contents = path.read_bytes()
        if extension != "bsx":
            if sys.platform == "win32":
                assert b"\n" not in contents.replace(b"\r\n", b"")
            contents = contents.replace(b"\r\n", b"\n")
        stage["sha256"][path.name] = hashlib.sha256(contents).hexdigest()
    for name, value in (("model-reference.json", models), ("stage1-reference.json", stage)):
        (output / name).write_text(json.dumps(value, indent=2), encoding="utf-8")
    provenance = {
        "source_commit": BASE_COMMIT,
        "platform": sys.platform,
        "python": sys.version,
        "numerical_runtime": {name: version(name) for name in ("numpy", "scipy", "scikit-fmm", "scikit-image")},
        "fixtures": len(models),
    }
    (output / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"Replayed {len(models)} fixtures and original exports from {BASE_COMMIT}", flush=True)


def generate(output):
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    # A shallow checkout must fetch the pinned ancestor, not silently use HEAD.
    subprocess.run(["git", "cat-file", "-e", BASE_COMMIT + "^{commit}"], cwd=ROOT, check=True)
    subprocess.run(["git", "merge-base", "--is-ancestor", BASE_COMMIT, "HEAD"], cwd=ROOT, check=True)
    archive = subprocess.check_output(["git", "archive", BASE_COMMIT], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="openmotor-original-engine-") as directory:
        source = Path(directory)
        with tarfile.open(fileobj=io.BytesIO(archive)) as contents:
            contents.extractall(source, filter="data")
        kernel = Path("mathlib/_find_perimeter_cy.pyx")
        assert (source / kernel).read_text() == (ROOT / kernel).read_text(), (
            "Cython engine source differs from baseline"
        )
        binaries = list((ROOT / "mathlib").glob("_find_perimeter_cy*.pyd"))
        binaries += list((ROOT / "mathlib").glob("_find_perimeter_cy*.so"))
        if not binaries:
            raise RuntimeError("Compile the current, unchanged Cython source before the baseline replay.")
        for binary in binaries:
            shutil.copy2(binary, source / "mathlib" / binary.name)
        for form in sorted((source / "uilib/views/forms").glob("*.ui")):
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "PyQt6.uic.pyuic",
                    str(form),
                    "-o",
                    str(source / "uilib/views" / (form.stem + "_ui.py")),
                ],
                check=True,
            )
        settings = json.loads((ROOT / "test/localization/data/stage1-reference.json").read_text())["eng_config"]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(source)
        environment["PYTHONUNBUFFERED"] = "1"
        subprocess.run(
            [
                sys.executable,
                __file__,
                "--replay",
                str(source),
                "--output-dir",
                str(output),
                "--settings",
                json.dumps(settings),
            ],
            cwd=source,
            env=environment,
            check=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--settings")
    args = parser.parse_args()
    if args.replay:
        replay(args.replay.resolve(), args.output_dir.resolve(), json.loads(args.settings))
    else:
        generate(args.output_dir)


if __name__ == "__main__":
    main()
