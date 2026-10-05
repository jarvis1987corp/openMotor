"""Load existing .ric fixtures through the existing migration code, in tests only.

The core accepts normalized snapshots and has no dependency on this UI file loader.
No QApplication or widgets are constructed. Logging paths are isolated on all OSes.
"""

import io
import os
import sys
import tempfile
from contextlib import redirect_stdout
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from unittest.mock import patch

from motorlib.motor import Motor

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = tuple(sorted((ROOT / "test/data").rglob("*.ric")))


@lru_cache(maxsize=1)
def _snapshots():
    with tempfile.TemporaryDirectory(prefix="openmotor-core-fixtures-") as directory:
        environment = {
            name: directory
            for name in ("XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "MPLCONFIGDIR")
        }
        environment["QT_QPA_PLATFORM"] = "offscreen"
        with (
            patch.dict(os.environ, environment),
            patch("platformdirs.user_data_dir", return_value=str(Path(directory) / "data")),
            patch("platformdirs.user_log_dir", return_value=str(Path(directory) / "logs")),
            redirect_stdout(io.StringIO()),
        ):
            from uilib.fileIO import fileTypes, loadFile

            snapshots = {
                path.relative_to(ROOT / "test/data").as_posix(): Motor(loadFile(str(path), fileTypes.MOTOR)).getDict()
                for path in FIXTURES
            }
            # Release Windows log handles before TemporaryDirectory cleanup.
            logger = sys.modules.get("uilib.logger")
            if logger is not None and logger.logger._file is not None:
                logger.logger._file.close()
                logger.logger._file = None
            return deepcopy(snapshots)


def fixture_snapshot(name="regression/simple/motor.ric"):
    return deepcopy(_snapshots()[name])


def fixture_names():
    return tuple(_snapshots())
