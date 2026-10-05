# -*- mode: python -*-
# Testing entry point only; the release application is built by the Windows specs.
from pathlib import Path
import sys

sys.path.insert(0, str(Path(SPECPATH)))
from windows_common import ROOT, analysis

a = analysis(ROOT / "test" / "packaging" / "frozen_probe.py")
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="openMotor-check",
    debug=False,
    strip=False,
    upx=False,
    console=True,
    contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="openMotor-check")
