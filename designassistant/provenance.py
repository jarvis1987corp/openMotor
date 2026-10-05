"""Fingerprint actual engine sources and relevant numerical runtime versions."""

import hashlib
import json
import platform
import sys
from importlib.metadata import version
from pathlib import Path

import mathlib
import motorlib


def engine_manifest():
    """Build-time source manifest, also used for fingerprints in frozen apps."""
    files = {}
    for package in (motorlib, mathlib):
        root = Path(package.__file__).resolve().parent
        for path in sorted(root.rglob("*")):
            if path.suffix in (".py", ".pyx", ".so", ".pyd") and path.is_file():
                files[package.__name__ + "/" + path.relative_to(root).as_posix()] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    if not files:
        raise RuntimeError("Engine source manifest is unavailable; a frozen-build manifest is required.")
    return {"schema": 1, "files": files}


def engine_fingerprint():
    if getattr(sys, "frozen", False):
        manifest = json.loads((Path(__file__).resolve().parent / "engine-manifest.json").read_text(encoding="utf-8"))
        if manifest.get("schema") != 1 or not manifest.get("files"):
            raise ValueError("Invalid bundled engine manifest.")
    else:
        manifest = engine_manifest()
    runtime = {name: version(name) for name in ("numpy", "scipy", "scikit-fmm", "scikit-image")}
    runtime.update(python=platform.python_version(), system=platform.system(), machine=platform.machine())
    return hashlib.sha256(
        json.dumps({"files": manifest["files"], "runtime": runtime}, sort_keys=True).encode()
    ).hexdigest()
