# Application localization

English (`en`) is the default source language, independent of the OS locale.
Russian (`ru`) covers the application-owned UI, all 14 Designer forms, model
parameter labels, tools, converters, diagnostics and matplotlib labels.
Choose Language in Preferences and press OK to save the stable code in the
existing `preferences.yaml` data. Older files without `language` use English.
Cancel leaves the saved language unchanged. Switching languages does not change
QLocale, units, physical calculations, project data or machine-readable exports.
See [AUDIT.md](AUDIT.md) for coverage, exceptions, terminology and validation.

## Runtime

The existing `uilib.localization.TranslationManager` owns installed QTranslators.
It loads `openmotor_<code>.qm` relative to its module, so source, wheel and frozen
builds use the same lookup. It also loads official `qtbase_<code>.qm` from the
bundled directory or `QLibraryInfo.TranslationsPath` for standard Qt buttons and
dialogs. Missing application catalogs fall back to English with a diagnostic.
The compiled application catalog is committed; users do not need Linguist.

Qt Designer forms already contain translation calls. Edit `.ui` sources and
regenerate with `pyuic6`; never edit generated `*_ui.py` manually. Widgets handle
`LanguageChange` by retranslating captions while retaining user edits, selection,
progress, numbers and cached results. Graphs update labels and legends on the
existing artists, preserving their data and zoom. Previews update cached alerts;
they do not regenerate grain/nozzle geometry or recalculate propellant curves.
Language-only preference updates have a separate signal and do not reset output.

## Model labels and stable values

`motorlib.localization` has **no Qt dependency**. Its `QT_TRANSLATE_NOOP` marks
literal English templates for pylupdate6, returning a `DisplayText` string with
context, template and formatting arguments. The underlying string remains
English, including formatted numbers. This preserves existing alert comparisons,
logging and CSV generation. Deep copies retain the template metadata.

Call `uilib.localization.display_text(marked_text)` at the UI boundary. It uses
QCoreApplication.translate, **then** formats arguments. This also retranslates
already computed alerts without translating a previously formatted string.

```python
# Model: an English diagnostic, with no Qt dependency.
message = QT_TRANSLATE_NOOP('SimulationAlerts', 'Grain {}').format(index + 1)
# UI: render the retained template through the installed QTranslator.
label.setText(display_text(message))
```

Mark Property.dispName, channel captions and diagnostics only. Never mark model
keys, grain geomName identities, enum values, units or serialized property values.
Geometry/enum label maps contain extraction markers, not Russian dictionaries.
QComboBox itemData/currentData stores stable values; captions can be translated
and retranslated under QSignalBlocker. User propellant names remain user data.

Use `self.tr("English source")` for QObject messages, or explicit
`QCoreApplication.translate("Context", "English source")` where needed. In shared
base classes, choose an explicit context when the concrete subclass would change
the context of self.tr. Preserve placeholders, their precision, HTML, links,
physical symbols and extensions. CSV/ENG/BurnSim retain canonical English headers,
XML fields, enum codes and numeric formatting; only exporter UI is localized.
PNG plot images use the current UI language and do not clear the live graph.

## Translation workflow

Use the repository virtual environment with PyQt6 installed. Qt Linguist
`lrelease` is required only to compile catalogs (Qt6 recommended; Qt5 .qm files
can also be loaded by Qt6). Debian/Ubuntu provides Qt6 Linguist via
`qt6-l10n-tools`. Override discovery with `LRELEASE` or `--lrelease`.

From the repository root:

```sh
.venv/bin/python scripts/translations.py update
# Edit the .ts catalog in Qt Linguist or an XML editor.
.venv/bin/python scripts/translations.py check
.venv/bin/python scripts/translations.py compile
# Or extract and compile together:
.venv/bin/python scripts/translations.py build
```

Extraction includes `app.py`, `uilib` (Python and Designer forms), `motorlib` and
`mathlib`, excluding generated `*_ui.py`. Retired messages are removed using
`--no-obsolete`. Compilation uses `-nounfinished`, so missing translations fall
back to English. `check` rejects unfinished/obsolete/empty translations, changed
format placeholders and unexplained unchanged English sources. Intentional
unchanged symbols, shortcuts and proper names need a translatorcomment.
Check in `.ts` and `.qm` together. Packaging includes application catalogs;
PyInstaller specs also include the official Russian Qt standard-dialog catalog.

To add a language, add its stable code and native name to `LANGUAGES`, create
`openmotor_<code>.ts` with the correct TS language, extract, translate, compile,
and include its official Qt catalog in frozen builds. Do not introduce a second
dictionary of translated application text in Python.

## Tests

Regenerate forms with the repository build_ui command, or directly according to
`pyuic.json` if pyqt-distutils is incompatible with installed setuptools:

```sh
for form in uilib/views/forms/*.ui; do
  .venv/bin/pyuic6 "$form" -o "uilib/views/$(basename "${form%.ui}")_ui.py"
done
PYTHONPATH=. .venv/bin/python test/unit.py
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m unittest discover -s test/localization -v
.venv/bin/python scripts/translations.py check
git diff --check
```

Tests isolate user configuration/cache directories. They check every compiled
message and fresh extraction, English → Russian → English, persisted preferences,
legacy preferences, stable model/enum identities, all parameter editors, cached
alerts, graphs, previews and exporter dialogs. Golden reference hashes verify
exact model/results/alerts for all 18 existing motor fixtures, plus CSV/ENG/BurnSim
and saved-project byte compatibility. UI tests exercise an already calculated
simulation and forbid rerunning simulation/geometry generation on language change.
Visual checks of native dialogs, DPI and packaged builds still need Windows.
