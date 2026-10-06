# Smart Design / Умный подбор

Open a configured motor, choose **Tools → Design Assistant**, then switch
**Mode** from **Manual** to **Smart Design**. Manual retains its existing
variables/targets/constraints and grid/random workflow.

1. **Project limits:** enter a positive maximum diameter, prefilled from the
   baseline. It bounds grain and nozzle-exit diameters. Casing wall thickness
   is not modelled, so reserve any required wall thickness yourself.
2. **Targets:** enable at least one of Burn Time, Total Impulse or Average Thrust.
   Other goals are optional. Set target values, weights and positive tolerances.
   Optional metric minimum/maximum bounds include thrust range, chamber pressure,
   mass flux and **propellant** mass. Total motor/hardware mass is unavailable.
   Conflicting bounds and targets outside their allowed ranges are rejected
   before starting. Other physical feasibility is checked by the existing engine.
3. **Allowed options:** allow all existing library entries, check several, or
   fix one. Keep the current grain types or check compatible alternate types.
   Grain count remains fixed. Baseline/library snapshots are captured when this
   window opens; reopen it after editing the library to pick up changes.
4. **Search quality:** Quick / Balanced / Thorough allow up to 60 / 180 / 540
   calculations respectively. Set a custom budget (1–10000), seed and Top N
   (default 10) if needed. The estimate includes finalist rechecks. Quality
   presets never alter timestep, mapDim or simulation accuracy.
5. **Run Smart Design:** one worker explores all selected variants, chooses
   admissible regions, refines them and rechecks globally selected finalists.
   Progress shows stage, counts, best score and elapsed time. Stop prevents new
   proposals and cooperates with the existing simulation callback. Completed
   summaries and diagnostics remain available. Geometry preparation/single
   solver calls cannot be interrupted until control returns to that callback.
6. **Results:** Top N is sorted by score, then stable candidate ID. Lower scores
   mean closer normalized weighted target agreement. Results show the existing
   library name, geometry, parameters, summary metrics, warnings and explanations.
   Details include target deviations and objective contributions. Ctrl/Shift-
   select 2–5 ranked rows and choose **Compare** for targets, actual values,
   deviations, constraint bounds, scores and warnings. **Open in Motor Editor**
   follows the existing unsaved-changes checks and creates a new unsaved document.
   The original .ric and baseline are not automatically changed or overwritten.

English → Русский → English preserves inputs, options, results, selection and
comparison records. Translations affect display only; library names, geometry
identities, property paths, numeric values and ranking remain canonical.

## Core contracts

- `LibraryEntry`: immutable exact existing material record, identified by its
  snapshot digest. No new recipes or chemical-property optimization.
- `SmartDesignRequirements`: project envelope, ordinary targets/constraints,
  allowed library/geometry identities, seed, budget, Top N and warning policy.
- `SearchSpaceBuilder`: returns an immutable `SmartSearchPlan` containing
  independent `SearchSpaceVariant`s and ordinary `DesignRequirements`.
- `CoarseToFineSearchStrategy`: ask/tell exploration, selection barriers,
  refinement around admissible elites and optional replay. Selection waits for
  all stage outcomes, making it independent of completion order.
- `SmartSearchStrategy`: fair round-robin scheduling across variants followed by
  global finalist replay. `context_for`, `requirements_for` and `request_for`
  associate each proposal with its exact variant. All requests use the existing
  CandidateGenerator and EngineAdapter; no new physical calculation layer.
- `SmartResultStore`: compact immutable evaluations, deduplication, ranking and
  comparison. Invalid rechecks remove earlier versions of the same design.
- `analyze_candidate`: per-target deviations, weighted contributions, constraint
  margins and English explanation templates derived from objective data.

Reproducibility uses the original baseline snapshot, library snapshots,
requirements/plan digests, seed and existing engine/runtime fingerprint. Exact
numeric replay requires the same fingerprint; cross-platform binary equality
is not assumed. EngineAdapter remains the sole new caller of runSimulation.

## Search boundaries and remaining limits

Ranges are baseline-centred heuristics: 25% spans, clamped to engine Property
metadata. For a smaller diameter envelope, radial search-space centres scale
proportionally; axial length is retained. This is parameter-space placement,
not a physical formula. Nozzle efficiency, losses, erosion/slag coefficients
and simulation configuration remain fixed. Use Manual for other numeric ranges.

Alternate grain types are offered only when every required property already
exists in each baseline grain, has the same property type and is accepted by
the existing setter. Missing dimensions, enum choices and custom shapes are
never invented. Every generated candidate still undergoes engine validation.

ERROR always excludes a candidate. WARNING stays in diagnostics and excludes
it only when warning rejection is selected. Rejected counts include error
candidates, with errors also shown as a subset, as in Manual.

A completed search with rechecks ranks only successful rechecked finalists.
Small budgets or restrictive constraints may yield fewer than Top N designs;
very small budgets may leave no budget for rechecks. Stopped results can be
provisional. Search data lives in memory; SQLite .omdesign, durable resume,
multiprocessing, caching and comparison curves are not implemented. Detailed
graphs/export remain available through the ordinary Motor Editor workflow.

Windows builds include the new Python modules and English/Russian catalogs.
Download **openMotor-QuickDesign-V2-Windows-x64** (including Manual, Smart and Quick)
from the successful
**Windows Standalone Build** run's Artifacts section, extract the whole ZIP,
and start `openMotor.exe` with `_internal` alongside it. Python is not required.
Native frozen checks cover Smart search, replay, language switching, comparison,
Stop and unsaved handoff. DPI, desktop themes and interactive file dialogs still
need manual Windows acceptance checks.
