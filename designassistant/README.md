# Design Assistant core

This is an independent Python package. It does not construct GUI objects, import
Qt/uilib/matplotlib, load project files, manage workers, or change the simulation
model. GUI and headless callers share the same core.

Smart Design's search-space, coarse-to-fine and ranking contracts are described
in [SMART_DESIGN.md](../SMART_DESIGN.md).

## Pipeline and public API

```text
SearchStrategy.ask() -> CandidateProposal
CandidateGenerator.generate(proposal) -> CandidateRequest
EngineAdapter.run(request) -> SimulationOutcome
Objective.evaluate(outcome, requirements) -> CandidateEvaluation
SearchStrategy.tell(evaluation)
```

`DesignRequirements` contains ordered `DesignVariable`s, `Target`s,
`MetricConstraint`s, and an optional `reject_warnings` policy. All numbers use
the engine's units, with no UI unit conversion. `ParameterRange` defines finite,
inclusive bounds, the number of grid points and optional integer sampling.
One-point ranges must have equal bounds. Integer grid points are distinct.

`PropertyPath` uses stable engine identifiers, never labels:

| Path | Meaning |
| --- | --- |
| `nozzle.throat` | Nozzle numeric property |
| `grains.0.coreDiameter` | Numeric property of grain zero |
| `config.mapDim` | Inspectable fixed configuration property |
| `propellant.density` | Inspectable fixed propellant property |

The paths address `PropertyCollection.props`; the serialized grain's
`properties` wrapper is intentionally not part of the path syntax. Negative
indices, aliases, nonexistent keys, grain types/counts and tabular subpaths are
rejected. `write_validated` supports numeric and canonical enum values as a
validation utility; **V1 search variables allow only existing nozzle/grain
numeric properties**. Enum, boolean, polygon, propellant and config variables
are rejected. Integer properties require integer ranges, and fractional values
are rejected before the engine can silently truncate them.

`CandidateGenerator` deep-copies the baseline on entry and creates a fresh
`Motor(deepcopy(baseline_snapshot))` for every proposal. Each proposal must
assign every declared variable exactly once. It validates range/type, calls
the existing property setter, then reads the value back and compares it with
the requested value without a tolerance. Any rejection, mismatch or exception
produces an invalid request with diagnostics and no runnable snapshot. Existing
baseline geometry, grain count, propellant and configuration remain fixed.
Invalid geometry is subsequently handled by the existing engine's alerts.

`Snapshot` stores canonical JSON and returns fresh dictionaries on decoding.
It retains numeric values and canonical identifiers; nested tuples of polygon
coordinates are represented as JSON arrays. This in-memory transport does not
change `.ric`, CSV, ENG or BurnSim formats. Callers supply normalized snapshots
from `Motor.getDict()` after using the application's existing project loader
and migrations. No alternative project loader is introduced here.

`EngineAdapter` is the only new layer that calls `Motor.runSimulation()`. It
reconstructs a fresh Motor from the validated snapshot and extracts only
compact summary metrics through `SimulationResult` getters:

| Stable metric key | Existing getter | Engine unit |
| --- | --- | --- |
| `burn_time` | `getBurnTime` | s |
| `total_impulse` | `getImpulse` | Ns |
| `average_thrust` | `getAverageForce` | N |
| `specific_impulse` | `getISP` | s |
| `average_pressure` | `getAveragePressure` | Pa |
| `maximum_pressure` | `getMaxPressure` | Pa |
| `propellant_mass` | `getPropellantMass` | kg |
| `peak_mass_flux` | `getPeakMassFlux` | kg/(m^2*s) |

`MetricRegistry` can declare further existing getters; it cannot supply new
physical calculations. Metadata uses English source strings and unchanged
engine units. All engine channels are checked for completeness, matching
sample/grain counts and finite numeric values; time must start at zero and
increase strictly. Getter results are also checked for finiteness.

`SimulationOutcome.engine_success` reports the engine flag;
`SimulationOutcome.valid` additionally requires completion, no ERROR alerts and
valid data. WARNING/MESSAGE alerts remain in diagnostics. Partial, cancelled,
exceptional and late-ERROR results cannot compete in scoring. Outcomes contain
only immutable DTOs and primitive values: no Motor, SimulationResult or GUI
objects. Full channel arrays and FMM maps are discarded after each calculation.
Exceptions affect the current candidate; interrupts and process exits propagate.

`EngineAdapter.run(..., should_cancel=..., on_progress=...)` checks cancellation
before starting and through the existing engine callback after timesteps.
Cancellation cannot interrupt geometry preparation, a single numerical solve,
or final diagnostics; that is an existing engine limitation. Progress callbacks
run synchronously on the caller's thread. There is no worker/scheduler in V1.

`ConstraintEvaluator` checks validity, optional warning rejection and inclusive
metric bounds. `Objective` checks these constraints **before** calculating the
weighted mean of `abs(actual - target) / scale`; lower scores are better.
Scales are explicit positive values in the metric's engine unit. Weights are
finite and nonnegative, with positive finite total weight. A missing required
metric, score overflow or failed constraint produces `score=None`. At least one
positive-weight target is required to score a feasible result. Search ranking
excludes all infeasible/unscored results.

`SearchStrategy` is an ask/tell interface. `GridSearchStrategy` traverses the
Cartesian grid lazily in requirements order, last variable fastest.
`RandomSearchStrategy(requirements, seed=..., budget=...)` uses a local PRNG,
uniform floating-point sampling and inclusive integer sampling. It neither
touches global random state nor depends on completion order. Candidate IDs are
stable ordinals. `tell` accepts pending candidates in any order, once only;
ranking uses score followed by ID for ties. A zero-dimensional grid emits the
baseline once. Search budgets and stopping between candidates are managed by
the caller. Random sampling may repeat points, especially for integer ranges.

## Reproduction and future integration

Requests/outcomes carry baseline and requirements SHA-256 digests. The adapter
records a fingerprint of actual motorlib/mathlib sources/extensions, numerical
dependency versions, Python version and platform. Preserve the **complete**
baseline snapshot, `requirements.to_dict()`, strategy kind, seed/budget and
engine fingerprint to reproduce a search. A seed alone cannot promise identical
results across different numerical runtimes. Requirements variable order is
part of search reproducibility. No persisted session or resume format is added
in this phase. Frozen builds now carry a build-time engine source
manifest and numerical dependency metadata; this fingerprint API supports both
source checkouts and packaged applications.

`DesignRequirements.from_dict` reconstructs requirements for replay without
introducing a session file format.

Core diagnostics use stable codes, English templates, separate JSON arguments
and translation contexts. Engine `DisplayText` metadata (including nested
arguments and locations) is retained in `TextRecord` without Qt. A future GUI
can translate the source template before substitution and add core templates
and metric labels to the existing English/Russian catalog. Internal paths,
metric keys, enums and units must not be translated. Exception details are
debug text, not stable identifiers or translated program values.

Later layers can schedule the same requests, persist DTOs to `.omdesign`, render
the results, or regenerate an individual candidate for detailed graphs. No
changes to MainWindow, the editor, project serialization or calculation formulas
are required by this foundation. FMM maps and full SimulationResults are not
cached. The finite strategies keep compact evaluations in memory; they do not
implement a durable ResultStore.

## Verification

From the repository root, with the existing development environment:

```sh
PYTHONPATH=. .venv/bin/python -m unittest discover -s test/designassistant -v
.venv/bin/ruff check designassistant test/designassistant
git diff --check
```

The suite covers all 18 existing fixture projects, comparing every channel
without tolerance, summary getters and alerts against a direct simulation.
It also exercises copying, setters, invalid data, cancellation, constraints,
scoring, deterministic strategies and absence of GUI imports.

The small demonstration uses the existing fixture loader only to prepare JSON,
then runs the pipeline in a separate process without Qt imports:

```sh
PYTHONPATH=. .venv/bin/python -c 'import json; from pathlib import Path; from test.designassistant.support import fixture_snapshot; Path("/tmp/openmotor-baseline.json").write_text(json.dumps(fixture_snapshot()), encoding="utf-8")'
PYTHONPATH=. .venv/bin/python test/designassistant/demo.py /tmp/openmotor-baseline.json
```

It executes a three-point grid and repeats a five-candidate seeded search,
checking exact proposal, metric and ranking equality. It is a software pipeline
check rather than a motor-design recommendation or a new user workflow.
