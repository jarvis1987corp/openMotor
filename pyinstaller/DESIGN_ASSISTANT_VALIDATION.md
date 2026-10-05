# Design Assistant MVP validation

Validated on 2026-10-05 in the Linux cloud workspace using the locked Python
3.12 environment. This report covers the MVP changes after accepted Phase 1;
the earlier localization/Windows report remains historical.

## Automated results

| Suite | Tests | Result |
| --- | ---: | --- |
| Existing `test/unit.py` | 37 | PASS |
| `test/localization` | 36 | PASS |
| `test/designassistant` | 98 | PASS |
| `test/designassistant_gui` | 34 | PASS |
| `test/packaging` | 13 | PASS |
| **Total** | **218** | **PASS** |

This stage adds **39 tests**: 34 GUI/controller tests and five packaging tests.
The core suite includes all **18 existing fixture projects**. EngineAdapter
matches direct Motor.runSimulation exactly for summary getters, every channel
array and alerts. No tolerance or reference refresh was used. A comparison with
the pre-MVP file snapshot confirms no changes to motorlib or mathlib.

GUI/controller checks cover actual worker simulations, queued signal thread
affinity and a GUI heartbeat; deterministic grid/random searches; Stop before
and during simulation; failed generators, rejected setters, ERROR alerts,
NaN data and warning constraints; numeric sorting/filtering/details; language
changes during/after search; unchanged baselines and source files; new unsaved
handoff; editor Apply/Discard/Cancel; cancelled Save As and failed saves;
explicit candidate Save As; and closing during a running search.

Strict Ruff passed for the core, new GUI package and all changed Python files.
Repository-wide critical Ruff checks (`E9,F63,F7,F82`) and `git diff --check`
passed. The Russian catalog has **534 active messages**, **512 translated**,
22 intentionally unchanged, zero unfinished and zero obsolete. This stage
adds 130 translated messages. Catalog extraction and compiled-catalog parity
are checked by the localization/packaging suites.

Source test logs are in `/tmp/openmotor-mvp-{unit,localization,core,gui,packaging}.log`
in this workspace. Those temporary paths are evidence for this run, not files
to distribute with the application.

## Frozen application checks

The separate `packagingProbe.spec` executable uses the same Analysis helper,
modules, catalogs and resource inputs as the Windows release specs. The final
Linux test bundle is:

```text
/tmp/openmotor-mvp-frozen-final/dist/openMotor-check/openMotor-check
```

Its payload is **376,290,130 bytes (358.86 MiB), 678 regular files**, counting
symlinked library aliases once. The executable signature is Linux ELF, not
Windows PE. This is a validation binary, not the Windows release artifact.

All three frozen processes passed from a Cyrillic working directory:

| Phase | Initial language | Language saved for next process | Result |
| --- | --- | --- | --- |
| first | English (`en`) | Russian (`ru`) | PASS |
| restart | Russian (`ru`) | English (`en`) | PASS |
| english | English (`en`) | English (`en`) | PASS |

Each phase runs 19 checks: startup, images/catalogs, localization and persistence,
standard Qt buttons and Cyrillic glyphs, Unicode project save/reload, ordinary
GUI simulation and cached graphs, CSV/ENG/BurnSim compatibility, import/PNG
export, Design Assistant engine fingerprint, three-candidate grid search,
repeated random search with seed 1729, language preservation, Start/Stop,
new unsaved candidate handoff and unchanged source project.

Simulation channel digest in all phases:
`8fd6777cf7b99d158dc173c5d783f04087d43c6197d16400d192c622c4fc6a99`.
Reports: `/tmp/openmotor-mvp-frozen-final/проверка/report-{first,restart,english}.json`.

PyInstaller emitted an optional scipy hidden-import warning and Linux warnings
about Windows ctypes libraries. All frozen checks passed. These warnings do
not establish Windows behavior; the native runner remains required.

## Native Windows status

**No Windows EXE was built or run in this Linux environment.** Windows artifact
size and desktop checks remain unmeasured. Both Windows specs now receive the
Design Assistant modules, numerical distribution metadata and engine manifest
through `windows_common.py`, alongside existing application/Qt catalogs.
The GUI is Python code and requires no additional Designer UI resources.

The prepared `.github/workflows/windows-build.yml` has not been pushed or run.
It uses Windows Server 2022, x64 Python 3.12, MSVC, locked dependencies and
pinned build tools. It runs all suites, builds release onedir and executes the
same three frozen probe phases before publishing the runnable artifact.

After push to staging/main/master, or an available manual workflow dispatch:

1. Open **Actions → Windows Standalone Build → successful run → Artifacts**.
2. Download **openMotor-Windows-x64**, supplied by GitHub as
   **openMotor-Windows-x64.zip**.
3. Extract the whole ZIP and run its root **openMotor.exe**. Keep `_internal/`
   beside it. No Python installation is required.
4. The release output before upload is
   `dist/windows/onedir/openMotor/openMotor.exe`; measured sizes are recorded
   in `dist/windows/build-info.json` and the validation artifact.

`openMotor-Windows-validation` contains build information, log and frozen JSON
reports. Manual dispatch requires the workflow file on the default branch.
Exact local commands are in [WINDOWS_BUILD.md](WINDOWS_BUILD.md).

## Manual Windows acceptance checklist

- Launch the full extracted artifact on a clean Windows 10/11 machine without
  Python, including from a different working directory and a read-only install
  directory.
- Open **Tools → Design Assistant**, configure nozzle and multiple grain
  variables, targets/constraints and both search strategies. Verify progress,
  responsive controls, Start/Stop, sorting/filtering and candidate details.
- Switch English → Русский → English before/during/after search; preserve
  values, results and selection. Restart to verify preference persistence.
- Check 100%, 125%, 150% DPI, moving between monitors, long Russian labels,
  table scrolling/resizing, native Qt dialogs and Cyrillic glyphs.
- Check existing light/dark theme behavior and readable tables/buttons/plots.
- Use Cyrillic Windows profile/directory/project/export filenames. Exercise
  real native Open/Save/Save As dialogs, cancellation and file filters.
- Open a candidate with saved and unsaved source projects; exercise editor
  Apply/Discard/Cancel and document Save/Discard/Cancel. Cancelled/failed save
  must prevent replacement. Candidate must have no filename and show `*`.
- Save the candidate under a new filename, reload it, simulate it in the
  ordinary editor, view graphs and import/export CSV/ENG/BurnSim/PNG. Confirm
  the original project file remains unchanged unless explicitly saved.
- Inspect native Windows test/probe reports. Investigate any platform numeric
  discrepancy without changing engine formulas or replacing golden references.

## MVP limits

One worker; at most 10,000 candidates per search; in-memory settings/results
only. Stop is cooperative and cannot interrupt geometry preparation or an
individual solver call. ERROR always rejects; WARNING rejection is optional.
The rejected counter includes error candidates; errors are also reported as
a subset. No SQLite `.omdesign`, durable resume, multiprocessing, cache,
advanced optimizer, coarse-to-fine, stored full curves or graph-comparison UI.
Use the ordinary Motor Editor for detailed simulation/graphs/export. Grain
types/count, propellant and simulation accuracy remain fixed per baseline.
Unknown external exception details remain debug text after a translated prefix.

## Files changed in this stage

Added:

- `.github/workflows/windows-build.yml`
- `uilib/designassistant/{__init__.py,controller.py,presentation.py,results.py,window.py,README.md}`
- `test/designassistant_gui/{__init__.py,test_gui.py}`
- `pyinstaller/DESIGN_ASSISTANT_VALIDATION.md`

Modified:

- `.github/workflows/tests.yml`
- `designassistant/{provenance.py,README.md}`
- `uilib/fileManager.py`
- `uilib/widgets/{mainWindow.py,collectionEditor.py}`
- `uilib/translations/{openmotor_ru.ts,openmotor_ru.qm}`
- `pyinstaller/{windows_common.py,WINDOWS_BUILD.md}`
- `scripts/build_windows.py`
- `test/packaging/{test_packaging.py,frozen_probe.py}`

There are **10 added and 13 modified files** relative to the pre-MVP snapshot.
Earlier accepted changes in the uncommitted workspace are excluded from this
list. Windows spec files already use the shared helper and need no edits in
this stage. No generated `*_ui.py` files were edited manually.
