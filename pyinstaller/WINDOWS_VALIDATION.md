# Stage 3: packaging validation

Date: 2026-10-05. **Windows EXE not built or executed.** The available host is
Linux x86_64 with glibc 2.41; no Windows Python or Windows runner is available.
PyInstaller cannot cross-compile Windows binaries. Windows artifact location and
size are therefore **not available**, rather than inferred from Linux builds.

Native Windows commands, expected EXE paths, prerequisites and the complete
manual checklist are in [WINDOWS_BUILD.md](WINDOWS_BUILD.md). The preferred target
is `dist/windows/onedir/openMotor/openMotor.exe` with its complete `_internal`
directory. The optional target is `dist/windows/onefile/openMotor.exe`. Actual
Windows sizes will be recorded in `dist/windows/build-info.json` by the helper.

## Real builds made on the available Linux host

Both **release specs** were built using native Linux Python. These are Linux ELF
artifacts, not Windows EXEs. A separate test executable uses the same shared
Analysis inputs and resources for GUI automation.

| Artifact | Location relative to repository | Payload size |
| --- | --- | --- |
| Release onedir | `dist/linux-check/onedir/openMotor/` | 375,819,906 bytes / 358.41 MiB |
| Release onefile | `dist/linux-check/onefile/openMotor` | 141,699,304 bytes / 135.13 MiB |
| Frozen GUI test executable and runtime | `dist/linux-check/GUI проверка/openMotor-check/` | 375,878,514 bytes / 358.47 MiB |

Folder sizes sum regular file lengths once, excluding symlink aliases; allocated
disk space differs (`du -sh` for the release onedir reports 361M). The test
artifact is not a release application. Build products are ignored by Git.

Build environment: CPython 3.12, PyInstaller 6.22.3,
pyinstaller-hooks-contrib 2026.8, PyQt6 6.11.0 / Qt 6.11.2,
matplotlib 3.11.1, NumPy 2.5.2, SciPy 1.18.1, scikit-fmm 2025.6.23.
The application lockfile and calculation dependencies were not changed.

## Automatic verification

| Check | Result on Linux |
| --- | --- |
| Existing unit suite | **37 passed** |
| Localization suite, including all 18 existing motor fixtures | **36 passed** |
| Packaging suite | **8 passed** |
| Catalog validation | 404 active messages: 382 translated, 22 intentional unchanged; 0 unfinished, 0 obsolete |
| Ruff `E9,F63,F7,F82` | Passed |
| `git diff --check` | Passed |
| Production onedir and onefile GUI startup | Passed with Qt offscreen; real release entry point reached `Window opened` |
| Production CLI simulation and CSV export | Passed; English/ Russian and onedir/onefile CSV bytes are identical |
| Onedir resource listing and onefile CArchive inspection | App/official Qt catalogs, runtime image and DejaVuSans font present |
| Frozen GUI: first / restart / english in separate processes | Passed: `en → ru`, `ru → en`, `en → en` saved/startup language |
| Unicode installation directory, working directory, project/export filenames | Passed in the frozen Linux checks |
| Unicode temporary onefile extraction directory | Passed in the Linux release CLI check |
| Legacy Windows ANSI log encoding emulation | Passed: Cyrillic log messages remain UTF-8 |
| Windows PE executable, native Qt Windows platform plugin, Windows desktop | **Not tested**; native Windows build required |

The frozen GUI probe verifies English → Russian → English through Preferences,
stable language codes saved to the isolated `preferences.yaml`, existing project
load/save/reload, a real simulation through the application's GUI thread/signals,
result statistics, cached graph labels/legend/zoom, Qt standard buttons and
Cyrillic font glyph coverage. CSV/ENG/BurnSim bytes are identical between languages;
BurnSim import dictionaries are identical; PNG files with Unicode names render
and retain the live graph. The simulation object, channel digest and simulation
thread stay unchanged during language switching. Test data lives outside the
repository under a Cyrillic path; no real user settings are modified.

The numeric fixtures retain strict full-value hashes. Existing projects,
canonical enum/geometry identifiers, units and export structures remain
compatible. Source hashes taken at the start of stage 3 confirm **no changes to
any `motorlib/` or `mathlib/` file** since accepted stage 2. No golden hashes were
regenerated. Windows text-file tests account for native CRLF without changing
application export code or weakening the numerical checks.

Machine-readable results and copied logs are in
`dist/linux-check/validation/summary.json`, `report-first.json`,
`report-restart.json`, `report-english.json` and the adjacent build/test logs.
The summary explicitly identifies the platform as Linux and has
`windows_artifact: null`.

## Packaging corrections and stage 3 file list

The old specs used obsolete PyInstaller APIs and paths relative to the working
directory. Onefile omitted runtime resources. Both now share an absolute-path
data list, include the compiled app and official Qt catalogs, stop if catalogs
are absent, use current PyInstaller 6 APIs and disable optional UPX processing.
The obsolete PyWavelets hidden import was removed: the application does not
depend on it.

Runtime images previously resolved relative to the executable or current working
directory. They now resolve from the module's bundle root, compatible with
PyInstaller 6 `_internal` and onefile extraction. Designer-generated modules were
not edited. The entry point now selects the existing Qt matplotlib backend
before importing pyplot; this fixed the observed offscreen startup failure.
The log uses explicit UTF-8 to prevent Unicode paths failing on Windows ANSI
code pages. This change concerns the diagnostic log only.

Changed existing files, relative to the accepted stage 2 snapshot:

- `.gitignore` — ignore Windows Cython `.pyd` build products.
- `app.py` — resolve the runtime window icon from bundled resources.
- `main.py` — initialize the existing Qt backend before pyplot.
- `pyinstaller/winOneFile.spec` — current API, shared inputs and resources.
- `pyinstaller/winMultiFile.spec` — current API, shared inputs and `_internal`.
- `uilib/widgets/aboutDialog.py` — load the About image from bundled resources.
- `uilib/logger.py` — UTF-8 diagnostic log encoding.
- `test/localization/test_localization.py` — image checks, Windows data isolation,
  log cleanup and native newline compatibility assertions.
- `test/localization/data/README.md` — explain Windows reference comparisons.

Added files:

- `uilib/resources.py` — common source/frozen resource path helper.
- `pyinstaller/windows_common.py` — shared Analysis, runtime data and Qt catalogs.
- `pyinstaller/requirements-build.txt` — pinned freezer and hooks.
- `scripts/build_windows.py` — native Windows build/check/size-report helper.
- `pyinstaller/packagingProbe.spec` — frozen test entry, using the shared inputs.
- `test/packaging/frozen_probe.py` — isolated three-process GUI checks.
- `test/packaging/test_packaging.py` — resource/catalog/path/encoding checks.
- `pyinstaller/WINDOWS_BUILD.md` — Windows commands and manual acceptance matrix.
- `pyinstaller/WINDOWS_VALIDATION.md` — this measured validation report.

## Remaining Windows verification and observed limits

Run the native builder and offscreen probe, then verify the **actual release EXE**
on a clean Windows machine without Python. Repeat onedir and onefile for DPI
100%, 125%, 150%, light/dark themes, long Russian captions, mixed-DPI monitors,
native Open/Save dialogs, Cyrillic user/install/temp paths, non-admin/read-only
installation and downstream CSV/ENG/BurnSim consumers. Offscreen Linux checks do
not establish Windows layout, font fallback, theme, DLL, native dialog or shell
behavior. Windows-owned dialog labels may follow the OS language.

During the original frozen startup check, matplotlib failed because the backend
was configured after pyplot imported; the entry-point fix passed source and
frozen checks. The remaining SciPy nozzle solver RuntimeWarnings also occur in
the existing reference simulations; strict channel/alert hashes pass, so the
calculation model was left unchanged. PyInstaller emits expected Linux warnings
for a Windows icon and conditional Windows-only ctypes libraries. These are
not evidence that Windows DLL packaging was tested.

No application features, calculation changes or Design Assistant work were
introduced. No Windows release or subsequent stage was started remotely.
