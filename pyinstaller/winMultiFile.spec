# -*- mode: python -*-
from pathlib import Path
import sys

sys.path.insert(0, str(Path(SPECPATH)))
from windows_common import ROOT, analysis

a = analysis()
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="openMotor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    contents_directory="_internal",
    icon=str(ROOT / "resources" / "oMIconCycles.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="openMotor",
)
