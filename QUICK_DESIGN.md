# Quick Design V2 / Быстрое проектирование

**Tools → Quick Design...** creates a design from requirements. No existing grain,
geometry, configured nozzle, selected propellant or DesignVariables are required.
The source project supplies only its general simulation/environment settings.
**Tools → Design Assistant** keeps the existing Manual and Smart workflows.

1. Enter all three required fields: **maximum diameter**, **maximum length** and
   **desired burn time**. They start empty. Diameter and length are hard upper
   limits; burn time is a scoring target with 10% normalization. Optionally enable
   desired average thrust and/or total impulse. Missing optional goals are never
   inferred or maximized. Other limits and WARNING rejection remain optional.
2. Use compatible **existing library entries**, or choose one/several. Quality is
   Quick/Balanced/Thorough (60/180/540 calculations including rechecks). The review
   lists actual geometries, grain counts, library count and budgeted combinations.
   Priority changes enabled target weights only (3 for the selected priority,
   otherwise 1). The seed is 1729; Advanced exposes it. Input units follow
   preferences and are converted to SI at the GUI boundary.
3. **Find Designs** delegates to the same one-worker Smart Design optimizer:
   exploration, refinement and global finalist rechecks. Stop uses the existing
   cooperative callback. At most five recommendations show actual summary metrics (including peak thrust through the existing force
   channel getter),
   library, geometry, grain count, bounds and warnings. Unrequested thrust/impulse
   are marked **Obtained result**. Why this design? uses existing deterministic
   objective/constraint explanations. Details and 2–3 design comparisons reuse
   the existing UI. English → Русский → English preserves inputs and results.

When all performance goals are enabled, a discrepancy greater than 25% between
average thrust × burn time and total impulse triggers a preflight warning. This
is an approximate consistency notice, not a new constraint or physics formula.
It does not modify targets or stop the existing engine from evaluating them.

**Open in Motor Editor** uses the existing Apply/Discard/Cancel checks and creates
an unsaved project; the original `.ric` is not overwritten automatically.
**Open in Design Assistant** requires a recommendation. It opens a separate
Manual window whose baseline is the **actual calculated candidate**, including
its exact nozzle, grains, count and existing material. Smart's metadata-clamped,
baseline-relative ranges are then centred on that result; targets, constraints,
budget and seed remain editable. The existing Advanced window is preserved.

## Generation boundary

`QuickDesignRequirementsValidator` → existing-library selection →
`QuickDesignGeometryFactory` → `QuickDesignNozzleFactory` →
`QuickDesignSearchSpaceBuilder` → existing `SmartSearchPlan`/`SmartSearchStrategy`
→ `CandidateGenerator` → `EngineAdapter` → constraints → objective → ranking.

The new generation layer is Qt-free and never calls `Motor.runSimulation`.
EngineAdapter remains the only Design Assistant caller. The engine, equations,
material library, simulation accuracy and project formats are unchanged.
Every initial setter has exact value read-back; numeric casts that preserve the
value are accepted. Independent normalized snapshots preserve the source config.
Every proposed point still undergoes the ordinary generator and engine checks.
Preflight uses properties and validation; it performs **zero simulations**.

## Geometry coverage

All 11 current geometry types have separate presets created through their own
constructors and property metadata. Geometry is never copied from baseline.

| Existing type | Independently initialized properties |
| --- | --- |
| BATES | diameter, length, coreDiameter |
| End Burner | diameter, length; one grain, as required by engine ordering |
| Finocyl | coreDiameter, finLength, finWidth, numFins; ordinary non-inverted fins |
| Moon Burner | coreDiameter, coreOffset |
| Star Grain | numPoints, pointLength, pointWidth |
| X Core | slotWidth, slotLength |
| C Grain | slotWidth, slotOffset |
| D Grain | slotOffset |
| Rod and Tube | coreDiameter, rodDiameter, supportDiameter |
| Conical | distinct forwardCoreDiameter and aftCoreDiameter |
| Custom Grain | one square polygon core in m; polygon stays fixed during search |

All types also receive independent outer diameter and length ranges. Preset
fractions are **search heuristics**, documented in `quick_generation.py`, not
physical equations or manufacturing recommendations. Outer diameter explores
60–98% of the requested maximum; each grain length explores 15–98% of its equal
share of maximum stack length. Additional dimensions use type-specific fractions,
clamped to existing metadata. Conical core ranges do not overlap; rod/support/core
ranges are ordered. Stock enum defaults remain unchanged. Custom Grain explores
numeric dimensions, not arbitrary polygon topology or imported DXF shapes.

Nozzle throat and exit are independent search variables with ordered ranges
(6–30% and 31–60% of maximum diameter). Its initial throat is 15%, or 6% for End
Burner; initial exit is 40%. Efficiency starts at 1, divergence/convergence angles
at 15/45 degrees; other properties retain constructor defaults. The angle
assumptions match the existing BurnSim importer. Unit efficiency is an explicit
generation preset: the constructor's zero efficiency fails stock validation.
These fixed values are not fitted to improve score. Throat length, slag and
erosion remain at constructor defaults (zero); no empirical/model parameter is
an optimization variable. These are starting/search presets, not a prediction
of the appropriate nozzle. Expansion ratio is derived by the existing
`Nozzle.calcExpansion()` from the jointly searched throat and exit diameters;
it is not a third independent variable.

The exploration count is 1 through min(6, floor(2 × maximum length / maximum
diameter)), with at least one grain. This aspect-ratio heuristic limits search
size, not the engine's supported count. End Burner uses one because the engine
requires every end burner to be forward-most. Homogeneous configurations are
searched; mixed geometry stacks are outside this version.

Library/geometry/count combinations are selected deterministically using the
seed and available budget. Every available library, supported geometry and
exploration count is covered before additional seeded combinations. Quality
allocates further exploration/refinement, without enumerating the complete
Cartesian product. The review discloses selected/possible counts. A too-small
headless budget fails explicitly. Unsupported future types or metadata bounds
retain specific skip reasons; no current type requires baseline parameters.

## Limits and reproducibility

Dimensions describe the **propellant envelope**, not the externally assembled
motor. Length excludes casing, nozzle length and gaps; diameter excludes casing
thickness. Nozzle exit also fits the entered diameter. Mass is propellant only.
The wizard states this prominently because the existing engine has no hardware
layout model. Reserve hardware space when entering limits.

Match (%) is `100 / (1 + normalized score)`, a display index rather than a
probability, safety claim or separate objective. The existing hard constraints
precede scoring. A deterministic 3% diversity filter avoids nearly identical
same-library/geometry results; there can be fewer than five recommendations.
There is no guarantee of feasibility or a global optimum. Broad generated
ranges can yield invalid candidates, retained in diagnostics without aborting
search. Numeric engine warnings remain available without altering engine code.

Requirements, exact baseline/library snapshots, seed, plan digest and engine
fingerprint determine replay. Labels and target weights do not change initial
option scheduling. Exact numerical replay needs the same engine/runtime.
SQLite sessions, multiprocessing, persistent resume and comparison curves remain
outside this implementation.

## Windows

**Windows Standalone Build** publishes **openMotor-QuickDesign-V2-Windows-x64**
after source suites and native frozen checks pass. Download the artifact ZIP,
extract it completely, then run `openMotor.exe` with `_internal` alongside it.
Python is not required. Frozen checks start Quick from an empty Motor Editor,
check all 11 generated types/counts, run searches, reproduce seeded results,
switch languages and verify comparison, candidate-based Advanced, Stop and
protected unsaved handoff. Existing simulation, graph and export checks remain.
Desktop DPI, themes/layout and interactive native dialogs need manual acceptance.
