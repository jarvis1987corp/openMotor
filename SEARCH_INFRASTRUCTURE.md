# Universal search infrastructure

The scheduler consumes **only supplied alternatives**. Existing Quick candidate
generation, geometry profiles, domain ranges and physical equations are unchanged.
The adapter cannot screen combinations that a generator has not supplied. Its
coverage denominator is the actual available catalogue, not a larger theoretical
Cartesian product. No physical performance benchmark or target-specific tuning
is part of this change.

## Scheduling

Previously every supplied alternative received an equal local coarse-to-fine
budget. Now all work shares a screening barrier before promising alternatives
receive remaining evaluations through the existing coarse-to-fine mechanism.
Global finalist rechecks retain the existing API and consume the overall budget.
Every issuance counts, including invalid candidates; there are no hidden retries.

Canonical stable keys remove input-order dependence. Seeded ties choose uncovered
category levels first and then balance marginal representation. This measures
coverage rather than claiming exhaustive coverage. Unrepresented levels are
reported explicitly when the budget is too small. Stable option-derived seeds and
feedback barriers remove global RNG and completion-order dependencies. Cooperative
Stop prevents further work and retains completed or pending results.

Quick/Balanced/Thorough retain total budgets of 60/180/540. The generic screening
budget is bounded by available options and budget, and otherwise is the larger of
the maximum category cardinality and min(64, floor(budget/2)). Remaining budget is
allocated to up to eight promising options. The adapter first reserves its existing
final-validation budget, so its exact phase counts may differ from standalone use.

For the 400-option dimensionless synthetic catalogue (20 × 10 × 2 categories),
standalone screening is 30/64/64 evaluations and remaining coarse/refinement work
is 30/116/476. Every level is represented in each preset. Screening does not
re-evaluate its representative when handing an option to coarse search.

## Objective assessment

Previously score was the weighted mean of abs(actual-target)/scale, and Match was
100/(1+score). A configured scale determined normalization; target satisfaction
had no independent centralized status model.

Now e_i = abs(actual-target)/abs(target). For a zero target, explicitly configured
positive scale defines an absolute reference instead. Disabled (zero-weight)
objectives do not affect assessment. Nonfinite errors cannot be ranked.

score = 0.5 × weighted_mean(e_i) + 0.5 × max(e_i)

Match = 100 × exp(-3 × score)

The worst objective always supplies at least half its error, even with many exact
objectives or a small priority weight. Match is bounded, monotonic and descriptive,
not a probability or a proof of feasibility. Per-objective relative errors and
statuses are retained with evaluation data and shown separately from constraints.
Weighted-mean contributions in analysis do not include the separate worst penalty.

`TargetTolerancePolicy` uses MATCHED ≤10%, NEAR ≤20%, otherwise MISSED. The 10% band
matches the former Quick target scale convention; NEAR is twice that band. These
are reporting tolerances, not model accuracy or domain guarantees. An aggregate
target status uses the worst active status. When none of the displayed candidates
matches all targets, the UI says Closest candidates and limits its claim to the
completed search. Satisfied hard constraints do not imply matched objectives.

All new optimization tests use synthetic numeric objectives and abstract category
labels. Existing regression suites verify the engine and stored formats unchanged.
