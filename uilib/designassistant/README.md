# Design Assistant: Manual and Smart Design

Open an existing motor, then choose **Tools → Design Assistant**. A separate
window captures the current motor as an independent baseline. Further edits or
file operations in the main editor do not change that baseline.

Choose **Manual / Ручной** to use the workflow below. The additional
**Smart Design / Умный подбор** mode provides a requirements form, automatic
search-space construction, coarse-to-fine search and summary comparisons.
See [SMART_DESIGN.md](../../SMART_DESIGN.md) for that workflow and its limits.

The separate **Tools → Quick Design...** wizard reuses this controller, Smart
backend, details and comparison dialogs. See [QUICK_DESIGN.md](../../QUICK_DESIGN.md).
Its Advanced handoff opens an independent Manual window with editable generated
ranges, objectives, constraints, budget and seed.
Inputs in both modes survive switching modes; starting a new search replaces
the current run's in-memory results.

1. **Variables:** choose a nozzle or grain numeric parameter, add it, enter
   minimum, maximum and number of grid values. Labels show the nozzle or grain
   number/geometry and translated parameter name; paths remain internal.
   A fixed range uses one value. The units come from preferences when this
   window opens and remain fixed throughout this search configuration.
2. **Targets:** select a summary metric, its target value, weight and positive
   normalization scale/tolerance in the displayed metric unit. Lower normalized
   weighted deviation scores are better. The initial Burn Time row is editable.
3. **Constraints:** optionally add metric bounds. Checkboxes enable each bound.
   ERROR always excludes a candidate. WARNING is retained and excludes a
   candidate only when warning rejection is enabled.
4. **Search Settings:** choose grid or seeded random sampling and a budget
   between 1 and 10000. The budget caps both strategies. Grid order is
   deterministic; the last declared variable varies fastest. A zero-variable
   grid evaluates the baseline once. Random sampling can repeat points.
5. **Start:** settings are locked while one QThread worker calculates candidates
   using the existing Qt-free core and EngineAdapter. Queued immutable results
   update the table, counters and progress bars. **Stop** sets a thread-safe
   cancellation event and prevents further proposals.
   The rejected counter includes error candidates; errors are also shown as
   a subset. Cancelled candidates have their own result status.
6. **Results:** sort any column, filter by status or text, and select **Details**
   for all summary metrics, parameter values and localized diagnostics. Rank is
   assigned only to feasible scored candidates; rejected/error rows have no
   competitive score. **Open in Motor Editor** regenerates the selected valid
   candidate from the fixed baseline and proposal.

Opening a candidate creates a new document with no filename and an unsaved
marker. It never automatically writes the original .ric, adopts its filename,
or changes the baseline. Unapplied editor changes offer Apply/Discard/Cancel;
the normal Save/Discard/Cancel check then protects the current document. A
cancelled or failed save blocks replacement. Saving the candidate invokes Save
As. Propellant library conflict/deduplication is not run during this transfer,
so the candidate retains the session's fixed propellant.

Language changes retranslate controls, labels, table rows and diagnostic
templates. They never recreate fields, clear outcomes, rerun a simulation or
translate internal identities. Source templates and arguments stay English in
the core; the GUI translates them before substitution. Standard Qt dialog
buttons use the application's existing Qt catalogs.

## Modules

- `window.py`: programmatic PyQt controls and details window; no generated UI
  files or additional runtime `.ui` resources.
- `controller.py`: single background worker, ask/tell orchestration, progress,
  cancellation and candidate regeneration.
- `presentation.py`: parameter labels, metric labels, core diagnostic templates
  and display-unit conversions using existing motorlib.units functions.
- `results.py`: table model, numeric sorting, status/text filtering and rank.
- `smart_form.py`: project limits, optional targets/constraints, allowed library
  and compatible geometry options, quality presets and simulation estimate.
- `smart_results.py`: Smart result table, explanations and comparison dialog.
- `smart_messages.py`: Qt extraction markers for new UI/core source templates.
- `editors.py`: numeric editors shared by both modes.
- `designassistant/`: Qt-free engine adapter, candidate validation, search
  strategies, Smart search-space construction and compact result analysis.

## MVP limits

Search settings/results live in memory until this window closes. There is no
SQLite `.omdesign`, durable session/resume, caching, multiprocessing, advanced
optimizer, full curve storage or graph-comparison UI. Use the
ordinary editor and simulation workflow for detailed candidate graphs/export.
Manual fixes geometry types/count, propellant and accuracy. Smart can compare
allowed existing library/compatible geometry variants while keeping count and
accuracy fixed. Closing an
active assistant stops it and defers destruction until the worker finishes;
application exit also waits asynchronously before the normal unsaved check.
Cancellation cannot interrupt geometry preparation or a single solver call.
The 10000-candidate budget bounds the in-memory results table; large grids are
truncated in deterministic order.

## Tests and packaging

```sh
QT_QPA_PLATFORM=offscreen PYTHONPATH=. .venv/bin/python -m unittest discover -s test/designassistant_gui -v
```

The tests exercise real worker simulations, GUI heartbeat/thread affinity,
language changes during and after search, Start/Stop, candidate-local failures,
constraints, seeded repeatability, sorting/filtering, details, source-file
preservation and unsaved document handoff. The core suite still compares all
18 existing fixtures directly against the engine.

Both Windows specs include these modules, application/Qt catalogs, numerical
dependency metadata and a build-time engine manifest. See
`pyinstaller/WINDOWS_BUILD.md` and `.github/workflows/windows-build.yml` for the
native Windows standalone build and downloadable ZIP artifact.
The runnable artifact is `openMotor-SmartDesign-Windows-x64`.
