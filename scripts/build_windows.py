"""Build a native, standalone Windows distribution with the checked-in specs."""

import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args, reference_directory=None):
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join([str(ROOT), environment.get("PYTHONPATH", "")])
    if reference_directory is not None:
        environment["OPENMOTOR_COMPATIBILITY_REFERENCE_DIR"] = str(reference_directory)
    subprocess.run([sys.executable, *map(str, args)], cwd=ROOT, env=environment, check=True)


def prepare():
    for form in sorted((ROOT / "uilib/views/forms").glob("*.ui")):
        target = ROOT / "uilib/views" / (form.stem + "_ui.py")
        run("-m", "PyQt6.uic.pyuic", form, "-o", target)
    run("setup.py", "build_ext", "--inplace")
    references = None
    if sys.platform == "win32":
        references = ROOT / "build/compatibility-baseline"
        run("scripts/compatibility_baseline.py", "--output-dir", references)
    run("scripts/translations.py", "check")
    run("-m", "unittest", "discover", "-s", "test/packaging", "-v")
    run("test/unit.py")
    run("-m", "unittest", "discover", "-s", "test/localization", "-v", reference_directory=references)
    run("-m", "unittest", "discover", "-s", "test/designassistant", "-v")
    run("-m", "unittest", "discover", "-s", "test/designassistant_gui", "-v")
    run("-m", "ruff", "check", "designassistant", "uilib/designassistant", "test/designassistant_gui")


def artifact_info(path):
    # Count payload once, even if Qt libraries have symlink aliases on the host.
    files = [path] if path.is_file() else [file for file in path.rglob("*") if file.is_file() and not file.is_symlink()]
    return {"path": str(path), "bytes": sum(file.stat().st_size for file in files), "files": len(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("onedir", "onefile", "both"), default="onedir")
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows executables require Windows Python; PyInstaller cannot cross-compile from Linux/macOS.")
    if platform.machine().lower() not in ("amd64", "x86_64") or sys.maxsize <= 2**32:
        parser.error("Use 64-bit CPython on Windows x64 for this build.")

    prepare()
    modes = ("onedir", "onefile") if args.mode == "both" else (args.mode,)
    artifacts = []
    for mode in modes:
        spec = ROOT / "pyinstaller" / ("winMultiFile.spec" if mode == "onedir" else "winOneFile.spec")
        destination = ROOT / "dist/windows" / mode
        run(
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            destination,
            "--workpath",
            ROOT / "build/windows" / mode,
            spec,
        )
        output = destination / ("openMotor" if mode == "onedir" else "openMotor.exe")
        executable = output / "openMotor.exe" if mode == "onedir" else output
        signature = b""
        if executable.is_file():
            with executable.open("rb") as stream:
                signature = stream.read(2)
        if signature != b"MZ":
            raise RuntimeError(f"Windows PE executable was not created: {executable}")
        artifacts.append(artifact_info(output))

    report = ROOT / "dist/windows/build-info.json"
    report.write_text(
        json.dumps({"platform": platform.platform(), "python": sys.version, "artifacts": artifacts}, indent=2),
        encoding="utf-8",
    )
    print(report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
