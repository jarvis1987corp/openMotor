"""Locate bundled assets independently of the executable and working directory."""

from pathlib import Path


def resource_path(name):
    # PyInstaller sets module __file__ underneath its bundle directory, both
    # inside onedir/_internal and in the temporary extraction of onefile.
    return str(Path(__file__).resolve().parents[1] / "resources" / name)
