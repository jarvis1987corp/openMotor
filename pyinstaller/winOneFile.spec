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
    a.binaries,
    a.datas,
    [],
    name="openMotor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    icon=str(ROOT / "resources" / "oMIconCycles.ico"),
)
