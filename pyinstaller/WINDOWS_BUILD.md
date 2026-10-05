# Windows standalone build and acceptance checks

These are **native Windows** instructions. PyInstaller does not cross-compile:
running a Windows spec with Linux Python produces an ELF executable, not an EXE.
The stage 3 cloud workspace is Linux; no Windows build or Windows desktop checks
have been performed there. See [WINDOWS_VALIDATION.md](WINDOWS_VALIDATION.md) for
the actual checks and their limits. The subsequent Design Assistant MVP checks
and Windows artifact status are recorded in
[DESIGN_ASSISTANT_VALIDATION.md](DESIGN_ASSISTANT_VALIDATION.md).

## Build prerequisites

- Windows 10/11 x64 and **64-bit CPython 3.12** (`py -3.12`). Use the same Python
  minor version as the locked, tested environment.
- Visual Studio 2022 Build Tools: **Desktop development with C++**, MSVC x64/x86
  tools and Windows SDK. The project's Cython extension is compiled locally;
  Linux `.so` files cannot be reused on Windows.
- A complete checkout of the accepted localization changes. Include
  `resources/`, `.ui` sources, and the committed `openmotor_ru.ts/.qm` pair.
- Network access for dependency installation. The released application needs
  neither Python, a compiler, Qt Linguist nor network access to start.

Open PowerShell in the repository root. An **x64 Native Tools** developer shell
is suitable if MSVC is not discovered from ordinary PowerShell.

```powershell
py -3.12 -m pip install uv
uv sync --frozen --python 3.12 --no-install-project
uv pip install --python .venv\Scripts\python.exe -r pyinstaller\requirements-build.txt
$env:PYTHONUTF8 = "1"
.venv\Scripts\python.exe scripts\build_windows.py --mode onedir
```

`uv sync --frozen` uses `uv.lock`; the build requirements pin PyInstaller and its
hooks separately. The helper regenerates Designer Python modules from `.ui`,
compiles `mathlib._find_perimeter_cy` for Windows, checks the catalog and runs the
unit, localization, packaging, Design Assistant core (including 18 fixture
comparisons), and Design Assistant GUI/controller tests before freezing. It
stops on failure.
Do not edit generated `*_ui.py`, update dependencies or bypass failing tests to
produce a release.

The preferred standalone output is:

```text
dist\windows\onedir\openMotor\openMotor.exe
dist\windows\onedir\openMotor\_internal\...
```

Distribute **the entire `openMotor` directory**, including `_internal`. The EXE
alone is insufficient for onedir. ZIP that directory for transfer to a clean
machine. Launch `openMotor.exe` normally; no Python installation is required.

For onefile, or both distributions:

```powershell
.venv\Scripts\python.exe scripts\build_windows.py --mode onefile
.venv\Scripts\python.exe scripts\build_windows.py --mode both
```

The single-file output is `dist\windows\onefile\openMotor.exe`. It extracts its
runtime into a temporary `_MEI...` directory when launched. The helper validates
the Windows PE signature and records the actual file/folder sizes in
`dist\windows\build-info.json`. No Windows size estimate is presented as a
measurement.

## Included localization resources

Both release specs call `windows_common.analysis()` with absolute repository
paths, regardless of the directory used to invoke PyInstaller. The shared data
list includes:

- `uilib/translations/openmotor_*.qm`, including `openmotor_ru.qm`;
- official `qtbase_<code>.qm` from **the installed PyQt6/Qt runtime** for each
  compiled application language; Russian's `qtbase_ru.qm` goes beside the app
  catalog;
- the complete `resources/` directory, including the runtime window icon and
  About image.

The Design Assistant GUI is programmatic Python; it needs no additional `.ui`
files. Both specs explicitly include `designassistant`, the GUI window and
controller. They also include a generated `designassistant/engine-manifest.json`
and the numerical dependency metadata for frozen engine fingerprinting. This
changes packaging/provenance only, not motorlib or mathlib calculations.

Missing application or official Qt catalogs stop the build. QtCore, QtGui and
QtWidgets are the project's Qt modules; `qtbase_ru.qm` is the applicable standard
widget/dialog catalog. PyInstaller's PyQt6 hooks collect the native Qt libraries
and plugins, including the Windows platform plugin. There is no QML or
QtWebEngine runtime to translate. Matplotlib's existing Qt5Agg backend works with
PyQt6; its fonts and data are collected by the matplotlib hook.

`TranslationManager` resolves `.qm` files beside its module. Images resolve from
the module's bundle root. These paths work for source, PyInstaller 6's
`_internal` directory and onefile extraction. They do not depend on the current
directory or the location of `sys.argv[0]`. Runtime `.ts` files and Linguist are
not required.

Diagnostic logs are written as UTF-8, so Cyrillic paths do not fail with a Western
Windows ANSI code page. This changes log encoding only; project/export formats
and numerical calculations are unchanged.

The checkout must contain history back to the pinned pre-localization ancestor
`dcc7fd62045d55036451b833f60e16a786f4685d`. The Actions checkout uses
`fetch-depth: 0`; for a local shallow clone, fetch its history before building.
The build helper independently replays that exact original source and exporters
on the Windows runtime, then compares localized output exactly against them.
Compiled Cython source must be unchanged. Linux's committed golden hashes stay
unchanged; numerical differences between Linux and Windows are not masked by
tolerances or new hashes from the current engine. The provenance and independent
reference JSON files are included in the validation artifact.

The committed `.qm` is checked against every active `.ts` message by the packaging
tests. If the translation source is edited, regenerate before building:

```powershell
.venv\Scripts\python.exe scripts\translations.py update
.venv\Scripts\python.exe scripts\translations.py check
.venv\Scripts\python.exe scripts\translations.py compile --lrelease "C:\Qt\6.11.0\msvc2022_64\bin\lrelease.exe"
```

Use the actual Qt Linguist installation path; it is a build tool only. Always
commit the updated `.ts` and `.qm` together.

## Repeat automated checks independently

```powershell
$env:PYTHONPATH = (Get-Location).Path
.venv\Scripts\python.exe test\unit.py
.venv\Scripts\python.exe -m unittest discover -s test\localization -v
.venv\Scripts\python.exe -m unittest discover -s test\packaging -v
.venv\Scripts\python.exe -m unittest discover -s test\designassistant -v
.venv\Scripts\python.exe -m unittest discover -s test\designassistant_gui -v
.venv\Scripts\python.exe scripts\translations.py check
.venv\Scripts\python.exe -m ruff check . --select E9,F63,F7,F82
git diff --check
```

## GitHub Actions downloadable Windows build

`.github/workflows/windows-build.yml` defines **Windows Standalone Build** on
Windows Server 2022 x64 with CPython 3.12 and MSVC. A push to `staging`, `main` or
`master` triggers it. For **Run workflow**, GitHub requires the workflow file to
exist on the repository's default branch; select the branch containing the
accepted changes.

The workflow installs locked dependencies, regenerates existing Designer code,
builds the Cython extension, runs all suites, builds release onedir, then builds
and executes the separate frozen GUI probe in first/restart/english phases.
The probe checks localization, Unicode paths, simulation/exports and the actual
Design Assistant worker, deterministic random search, Stop and unsaved handoff.

After a successful run, open **Actions → Windows Standalone Build → the run →
Artifacts → openMotor-Windows-x64**. GitHub downloads
**`openMotor-Windows-x64.zip`**. Extract the entire ZIP; its root contains
`openMotor.exe` and `_internal/`. Run `openMotor.exe`; do not extract only the EXE.
The ZIP is produced by GitHub's artifact service from the standalone folder,
so there is no second nested ZIP to unpack. Build/test reports are available as
`openMotor-Windows-validation`.

The workflow is prepared in source. A successful Windows run, artifact size and
Windows desktop behavior must be verified after push; they cannot be inferred
from tests on Linux. Original-source comparisons remain exact: a Windows result
that differs from the independent original-engine replay must be investigated;
do not alter the model or refresh references from current output to bypass it.

Localization tests explicitly isolate platformdirs on Windows and Linux, so they
do not change real user preferences. Text reference hashes account for Windows
CRLF **and assert that native line endings remain unchanged**; BurnSim XML bytes
remain exact. Numeric reference hashes remain strict. If a Windows numerical
baseline fails, retain the report and investigate the platform/dependency
variation; do not alter the calculation model to fix packaging or UI.

## Automated frozen GUI check (test artifact only)

`packagingProbe.spec` uses the same shared Analysis and resources with a testing
entry point. It does not add a flag or function to the released application.
Build it on Windows after the release build:

```powershell
.venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --distpath dist\windows\probe --workpath build\windows\probe pyinstaller\packagingProbe.spec
$probe = (Resolve-Path dist\windows\probe\openMotor-check\openMotor-check.exe).Path
$project = (Resolve-Path test\data\regression\simple\motor.ric).Path
$qa = Join-Path $env:TEMP ("openMotor-проверка-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $qa
Copy-Item $project (Join-Path $qa "двигатель исходный.ric")
$project = Join-Path $qa "двигатель исходный.ric"
$env:QT_QPA_PLATFORM = "windows"
Push-Location $qa
& $probe --data-dir $qa --project $project --phase first
& $probe --data-dir $qa --project $project --phase restart
& $probe --data-dir $qa --project $project --phase english
Pop-Location
Remove-Item Env:QT_QPA_PLATFORM
```

Each phase must return exit code 0 and `PASS`, writing `report-<phase>.json` to
`$qa`. The first leaves Russian saved, the second verifies a Russian startup and
saves English, and the third verifies an English startup. All three exercise
real GUI simulation signals, existing-project load/save/reload, English →
Russian → English via Preferences, Qt standard buttons, Cyrillic font coverage,
cached graph labels/data/zoom, Unicode filenames, CSV/ENG/BurnSim exports,
BurnSim import and PNG export. Export bytes must be identical between languages;
computed channels and the simulation thread must remain unchanged when the
language switches. All user data is confined to `$qa`.

The frozen probe uses the native Windows Qt platform, including system fonts;
source unit tests continue to use `offscreen`. The probe is additional evidence, not a substitute for the Windows
release EXE and native desktop checks below. Do not distribute the probe as the
application.

## Manual Windows acceptance checklist

Record Windows version, build mode, Qt version, screen DPI, theme and results.
Repeat with **onedir and onefile** on a clean Windows machine without Python.

| Check | Expected result |
| --- | --- |
| Extract/install under `C:\Тест openMotor\Сборка` and run from another working directory | App opens; icon, About image and translations load |
| Fresh Windows user / preferences without `language` | English is selected, regardless of Windows UI language |
| Preferences: English → Русский, OK, close, reopen | Menus/forms and standard Qt buttons are Russian; `preferences.yaml` contains stable `ru` |
| Return to English, restart; cancel a pending language change | English persists as `en`; Cancel does not save |
| Existing 0.4.x and current `.ric` files | Projects migrate/load, save and reopen; identifiers and units stay canonical |
| Save/open `двигатель №1.ric` under a Cyrillic user profile and folder | Names and paths survive restart and recent-files selection |
| Real Windows Open / Save / Save As dialogs | Correct app captions, file filters/extensions, Unicode paths and cancellation; OS-owned labels may follow the Windows language |
| Simulate a valid motor; switch languages while viewing results | Same numbers/data, changed alerts/table/axis/legend captions, preserved selections and graph zoom; no new simulation |
| CSV, ENG, BurnSim and PNG export; BurnSim import | Unicode filenames work; CSV/ENG/BSX schema and units stay compatible; graph PNG uses the UI language |
| Open exports in existing downstream tools (RASP/ENG consumer and BurnSim) | Files are accepted with the same behavior as the original formats |
| DPI **100%, 125%, 150%**; move between monitors | Long Russian captions fit, scroll controls remain usable, graphs/dialogs render crisply |
| Windows light and dark themes, restart app for each | Text, Qt buttons, icons, plots and legends remain readable; dark mode uses existing behavior |
| Cyrillic menus, warnings and graph glyphs | No missing squares, corrupted letters or font warnings |
| Read-only application directory / ordinary non-admin user | Preferences/logs save to user directories; no writes beside the EXE |
| Close/relaunch onefile repeatedly | Temporary extraction works; language preference survives extraction-directory changes |

On Windows the existing preferences directory is obtained with
`platformdirs.user_data_dir('openMotor', 'openMotor')` (normally
`%LOCALAPPDATA%\openMotor\openMotor`). Do not delete a user's settings merely to
test defaults: use a separate test account or back up/restore the test account's
data. The probe uses its own isolated directory.

Native file dialogs are provided by Windows. The application can translate its
caption and filter; the OS may retain its own language for shell controls. Verify
this behavior rather than assuming every OS-owned label follows QTranslator.
