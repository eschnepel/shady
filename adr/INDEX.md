# ADR Index

This is the authoritative list of all ADRs in this project, their current
status, and how they relate to one another. See
[`adr/000-coding-standards.md`](000-coding-standards.md) §7 for what
belongs in an ADR versus a code comment.

**This file must be updated whenever an ADR undergoes a structural
change** — a new ADR is added, one is split, superseded, or its status
otherwise changes — see ADR-000 §7 for the mandatory-update rule this
enforces.

| ADR | Status | Title |
|---|---|---|
| [000](000-coding-standards.md) | Accepted | Code Quality Standards, Programming Style & Core Concepts |
| [001](001-empirical-shading-model.md) | Accepted | Empirical, Forecast-Value-Based Shading Model — predictor, regression method, granularity, rolling window |
| [002](002-coordinator-update-strategy.md) | Accepted | Coordinator Update Strategy: Recalibration vs. Forecast Recompute |
| [003](003-yield-corrections-clipping-derating.md) | Superseded *(split into ADR-003a and ADR-003b, 2026-08-18)* | Optional Per-String Yield Corrections: Clipping and Derating |
| [003a](003a-inverter-clipping-exclusion.md) | Accepted | Optional Per-String Yield Correction: Inverter Clipping Exclusion *(split from ADR-003 §1/§1a)* |
| [003b](003b-temperature-derating-correction.md) | Accepted | Optional Per-String Yield Correction: Temperature Derating *(split from ADR-003 §2/§2a/§2b/§2c/§3)* |
| [003c](003c-temperature-forecast-via-learned-model.md) | Accepted | Temperature Derating: Forecasting the Target-Slot Temperature via a Learned Per-Slot Model *(amends ADR-003b §1a/§1b, ADR-012 §3, ADR-010)* |
| [004](004-diagnostics-select-and-scatter-sensor.md) | Accepted | Diagnostics: Selectable Diagnostic Modes and Scatter-Series Sensors (Per-String and Summed) *(§1 amended 2026-08-30: select dropdown + `DiagnosticMode` base class, replacing the original boolean switch; §5 amended again 2026-09-01: `DiagnosticMode` gains construction-time `ShadyCoordinator` access + `fit_cadence`/`compute_cadence` getters, dropping its zero-mocking purity guarantee)* |
| [005](005-aggregate-sum-and-integral-sensors.md) | Accepted | Cross-String Aggregate Sensors: Sums and Daily Integrals |
| [006](006-intraday-deviation-correction.md) | Accepted | Intraday Deviation Correction for the Remaining-Today Forecast |
| [007](007-coordinator-cache-split.md) | Accepted | Splitting the Coordinator: A Dedicated Cache Module *(storage/accessor design split out to ADR-007a, 2026-08-19)* |
| [007a](007a-cache-storage-and-accessor-design.md) | Accepted | `cache.py`: Storage Scheme and Accessor Design *(split from ADR-007 §1a–§1f)* |
| [008](008-numpy-backend-and-cache-array-accessor.md) | Accepted | Numeric Backend for `regression/`, and a Batched Cache Accessor |
| [009](009-baseline-forecast-sourcing.md) | Accepted | Baseline (Unshaded) Forecast Sourcing: Generic Attribute Discovery *(split from ADR-001 §5)* |
| [010](010-config-flow-shape.md) | Accepted | Config Flow Shape *(split from ADR-001 §6)* |
| [011](011-temporal-smoothing-and-neighbor-exclusion.md) | Accepted | Temporal Smoothing and Neighbor-Regime Exclusion for Slot Training Pools *(split from ADR-001 §3b/§3c/§3d)* |
| [012](012-provider-architecture.md) | Accepted | Provider Architecture: Shared Base Class and Cache Reuse for External Series |
| [013](013-whole-day-diagnostic-modes.md) | Proposed *(no implementation task; validates ADR-004's base class against future needs)* | Diagnostics: Whole-Day Comparison Modes (Draft — Future Work, Not Yet Scheduled) |
| [014](014-string-computation-module.md) | Accepted | `string_computation.py`: A Shared, Pure Per-String Fit/Predict Module *(discovered while scoping TASK-0015b; relocates computation out of `coordinator.py`, replaces the `diagnostics --> regression` edge with `diagnostics --> string_computation`)* |

**Status key:** `Accepted` — in force, implemented or scheduled for
implementation. `Superseded` — replaced by a later ADR, kept for history.
`Proposed` — design sketch only; no task exists yet and MVP scope does
not include it (see `tasks/adr-summary.md` §9 exclusions vs. this
document's own "not yet scheduled" framing — a `Proposed` ADR may still
be built later, unlike a permanent §9 exclusion).

Further ADRs (014 onward) will be added as brainstorming continues.
