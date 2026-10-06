# Quick Design / Быстрое проектирование

Open a configured motor, then **Tools → Quick Design...**. The separate wizard
uses the existing Smart Design backend. **Tools → Design Assistant** retains
its Manual and Smart modes.

1. **What is known?** Enable a diameter or length requirement and at least one
   performance characteristic: burn time, average thrust or total impulse.
   Target is a soft objective; Minimum/Maximum is a hard constraint. Other
   limits are optional. Inputs use preferences units, converted to SI once at
   the GUI boundary. The baseline provides dimensions, grain count, configuration
   and existing geometry parameters; an empty/unconfigured motor cannot be used.
2. **Review and search quality:** use compatible existing library entries or
   choose one/several. Read the skipped-option diagnostics. Priority changes
   enabled target weights only (3 for the selected priority, otherwise 1).
   Tolerance is 10% of the target. If only performance limits are entered, a
   stated performance boundary also becomes the ranking target, as disclosed
   in the review. Hard limits remain mandatory. Quality allows up to 60/180/540
   calculations, default Balanced, including finalist rechecks. Seed defaults
   to 1729; Advanced exposes it. Engine accuracy never changes.
3. **Find Designs:** the same one-worker Smart controller performs exploration,
   refinement and global rechecks. Stop uses its existing cooperative callback.
   Completed results remain available after stopping and may be provisional.
   At most five cards show metrics, library, geometry, limits and warnings.
   Why this design? uses existing objective/constraint explanations. Technical
   details expose the ordinary parameter summary. Select 2–3 cards to use the
   existing comparison dialog. Open in Motor Editor creates a new unsaved
   project with the existing Apply/Discard/Cancel checks; source files are not
   automatically changed or overwritten.

**Open in Design Assistant** opens an independent Manual window with generated
ranges, objectives, constraints, budget and seed. A selected recommendation
chooses its library/geometry; otherwise the first stable option is used. The
ordinary Manual controls permit editing all transferred settings. Existing
Design Assistant windows and the current Motor Editor project are preserved.

English → Русский → English preserves inputs, canonical identifiers, the compiled
problem, selection and ranking. Library names remain the user's original names.

## Core boundary

`designassistant.quick` is Qt-free. `QuickCriterion` and
`QuickDesignRequirements` use stable keys and SI values.
`QuickDesignRequirementsValidator` rejects insufficient/conflicting tasks and
unavailable libraries before any simulation. `QuickDesignProblemBuilder` returns
an immutable `QuickDesignProblem` with the ordinary `SmartSearchPlan`. Setter
read-back is mandatory when placing dimensional search centres. CandidateGenerator,
SmartSearchStrategy, EngineAdapter, Objective and SmartResultStore are reused.
EngineAdapter remains the only Design Assistant caller of Motor.runSimulation.

The Quick metric registry adds only existing SimulationResult getters:
getPropellantLength and getMaxPropellantDiameter. Default Manual/Smart metrics
and the engine remain unchanged. The registry is passed explicitly through the
same runner; it is also used for the Advanced handoff and comparison.

Requirements, exact baseline/library snapshots, seed, plan digest and existing
engine fingerprint determine replay. Option ordering is independent of objective
weights and widget language. Binary equality requires the same engine/runtime
fingerprint.

## Recommendations and limits

Match (%) is a display index `100 / (1 + normalized score)`, not a probability,
safety claim or alternative score. All hard constraints are evaluated before
the existing weighted objective. The deterministic greedy diversity filter
removes designs from the same library/geometry whose burn time, average thrust,
impulse and envelope metrics differ by no more than 3%. Different existing
library/geometry choices remain distinct. There can be fewer than five results.

Dimensions are the **propellant envelope**, not the external assembled motor.
Length excludes casing, nozzle length and gaps; reserve hardware space yourself.
Diameter excludes casing thickness, while the search also caps nozzle exit to
the entered maximum diameter. Mass is propellant mass, excluding hardware.
These limits are stated prominently in the wizard; no hardware model or physical
formula is invented.

Ranges remain metadata-clamped, baseline-centred heuristics (about 25%). Stated
dimensions move search centres using existing setters, without changing the
baseline. A maximum stack length caps each grain's allocated length; final
constraints still use the engine getter. Alternate types are only those Smart
Design can initialize using existing baseline properties. Skipped types/entries
retain diagnostic reasons. Structural preflight does not guarantee physical
feasibility: every actual candidate goes through the existing engine checks.

No new recipes, physical equations, simulation accuracy changes, file formats,
second optimizer/comparison engine, cloud API or AI service are introduced.
SQLite sessions, multiprocessing, persistent resume and comparison curves remain
outside this implementation.

## Windows

The **Windows Standalone Build** workflow on `design-assistant-mvp` publishes
**openMotor-QuickDesign-Windows-x64** after source suites and all native frozen
checks pass. Download that artifact ZIP, extract it completely, and run
`openMotor.exe` with `_internal` alongside it. Python is not required. Frozen
checks cover the wizard, seeded replay, language round trip, cards, comparison,
Advanced/unsaved handoffs and Stop alongside the existing simulation/export checks.
Desktop DPI, theme/layout and interactive file dialogs need manual acceptance.
