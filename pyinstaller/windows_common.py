"""Shared PyInstaller inputs for both Windows distributions and packaging checks."""

import json
from pathlib import Path

from PyQt6.QtCore import QLibraryInfo

ROOT = Path(__file__).resolve().parents[1]


def runtime_datas(root=ROOT, qt_translations=None):
    root = Path(root)
    catalogs = sorted((root / "uilib" / "translations").glob("openmotor_*.qm"))
    if not any(path.name == "openmotor_ru.qm" for path in catalogs):
        raise FileNotFoundError("Missing uilib/translations/openmotor_ru.qm; compile the translation catalog first.")
    qt_translations = Path(qt_translations or QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath))
    datas = [(str(root / "resources"), "resources")]
    for path in catalogs:
        datas.append((str(path), "uilib/translations"))
        code = path.stem.removeprefix("openmotor_")
        if code == "en":
            continue
        qt_catalog = qt_translations / f"qtbase_{code}.qm"
        if not qt_catalog.is_file():
            raise FileNotFoundError(f"Missing official Qt translation catalog: {qt_catalog}")
        datas.append((str(qt_catalog), "uilib/translations"))
    if not (root / "resources" / "oMIconCyclesSmall.png").is_file():
        raise FileNotFoundError("Missing application resources; build from a complete checkout.")
    from PyInstaller.utils.hooks import copy_metadata

    from designassistant.provenance import engine_manifest

    manifest = root / "build" / "packaging" / "engine-manifest.json"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(engine_manifest(), sort_keys=True), encoding="utf-8")
    datas.append((str(manifest), "designassistant"))
    for package in ("numpy", "scipy", "scikit-fmm", "scikit-image"):
        datas.extend(copy_metadata(package))
    return datas


def analysis(entry=None):
    from PyInstaller.building.build_main import Analysis

    return Analysis(
        [str(entry or ROOT / "main.py")],
        pathex=[str(ROOT)],
        binaries=[],
        datas=runtime_datas(),
        hiddenimports=[
            "designassistant",
            "designassistant.smart",
            "designassistant.smart_results",
            "designassistant.quick",
            "designassistant.quick_generation",
            "uilib.designassistant.window",
            "uilib.designassistant.controller",
            "uilib.designassistant.smart_form",
            "uilib.designassistant.smart_results",
            "uilib.designassistant.quick_window",
            "uilib.designassistant.quick_messages",
        ],
        hookspath=[],
        hooksconfig={"matplotlib": {"backends": ["Qt5Agg"]}},
        runtime_hooks=[str(ROOT / "pyinstaller/runtime_utf8.py")],
        excludes=[],
        noarchive=False,
    )
