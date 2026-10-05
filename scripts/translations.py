"""Extract Qt messages and compile application catalogs without editing generated UI."""

import argparse
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from string import Formatter

ROOT = Path(__file__).resolve().parents[1]
CATALOGS = ROOT / "uilib" / "translations"


def update():
    # Use the same interpreter as the development environment, not system PyQt.
    command = [sys.executable, "-c", "from PyQt6.lupdate.pylupdate import main; raise SystemExit(main())"]
    for catalog in sorted(CATALOGS.glob("openmotor_*.ts")):
        subprocess.run(command + ["app.py", "uilib", "motorlib", "mathlib", "--exclude", "*_ui.py",
                                 "--no-obsolete", "--ts", str(catalog.relative_to(ROOT))], cwd=ROOT, check=True)


def placeholders(text):
    """Compare field names, conversions and number formatting, including repeats."""
    return Counter((field, spec, conversion) for _, field, spec, conversion in Formatter().parse(text)
                   if field is not None)


def check_catalogs():
    """Fail on missing/stale translations or altered formatting placeholders."""
    summaries = []
    for catalog in sorted(CATALOGS.glob("openmotor_*.ts")):
        root = ET.parse(catalog).getroot()
        total = translated = unchanged = 0
        errors = []
        for context in root.findall("context"):
            for message in context.findall("message"):
                total += 1
                source = message.findtext("source", "")
                translation = message.find("translation")
                text = message.findtext("translation", "")
                label = f"{context.findtext('name')}: {source!r}"
                if translation is None or translation.get("type") in ("unfinished", "obsolete", "vanished") or not text:
                    errors.append(f"Missing or stale translation: {label}")
                    continue
                if placeholders(source) != placeholders(text):
                    errors.append(f"Changed placeholders: {label}")
                protected = re.findall(r"https?://[^\s\"<>]+|\*?\.[a-zA-Z]{2,4}\b|\bKn\b|\bISP\b|\bIsp\b|c\*|M>1\.0|###",
                                       source)
                for token in protected:
                    if text.count(token) != source.count(token):
                        errors.append(f"Changed URL, format or physical notation {token!r}: {label}")
                if source == text:
                    unchanged += 1
                    if not message.findtext("translatorcomment"):
                        errors.append(f"Unexplained English fallback: {label}")
                else:
                    translated += 1
        if errors:
            raise SystemExit("\n".join(errors))
        summary = {"catalog": catalog.name, "messages": total, "translated": translated,
                   "intentionally_unchanged": unchanged, "unfinished": 0, "obsolete": 0}
        summaries.append(summary)
        print(summary)
    return summaries


def compile_catalogs(lrelease=None):
    executable = lrelease or os.environ.get("LRELEASE")
    if not executable:
        # Qt6 Linguist tools may not be on PATH on Linux.
        candidates = ["/usr/lib/qt6/bin/lrelease", "/usr/lib64/qt6/bin/lrelease"]
        executable = next((path for path in candidates if Path(path).is_file()), None)
        executable = executable or shutil.which("lrelease6") or shutil.which("lrelease")
    if not executable:
        raise SystemExit("Install Qt Linguist lrelease or set LRELEASE to its executable path.")
    for catalog in sorted(CATALOGS.glob("openmotor_*.ts")):
        subprocess.run([executable, "-nounfinished", str(catalog), "-qm", str(catalog.with_suffix(".qm"))],
                       cwd=ROOT, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("update", "compile", "build", "check"))
    parser.add_argument("--lrelease", help="Path to Qt Linguist lrelease")
    args = parser.parse_args()
    if args.command in ("update", "build"):
        update()
    if args.command in ("compile", "build"):
        compile_catalogs(args.lrelease)
    if args.command == "check":
        check_catalogs()


if __name__ == "__main__":
    main()
