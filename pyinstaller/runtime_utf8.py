"""Keep redirected Windows frozen-console diagnostics Unicode-safe.

PyInstaller's isolated interpreter ignores PYTHONIOENCODING/PYTHONUTF8.
Windowed builds have no streams; leave them and the process locale untouched.
"""

import sys

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
