# Task: Temperature-Forecast Learned Model

- **Status:** todo
- **Related ADRs:** [ADR-003c §1, ADR-003c §2, ADR-003c §3, ADR-003c §4, ADR-003c §5, ADR-003c §6, ADR-003c §7]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0006-cache-batched-regression-pool-accessor, TASK-0004-temperature-source-provider, TASK-0007-yield-corrections, TASK-0010-coordinator-recalibration-recompute-push, TASK-0005-patch-4-recency-weight]

## Goal
Implement the cell/ambient-tier per-slot temperature forecasting model:
one learned model per 5-minute slot (same 288-slot grid, same rolling
window), reusing `regression/`'s fitting mechanics only (no
`magnitude_weight_i`, no ADR-011 smoothing/exclusion), trained against a
second instance of `providers/temperature.py` (TASK-0004's class,
reused as-is, pointed at the dedicated weather-forecast-entity config
field) as predictor and the tier's own sensor as target. Feeds
`yield_correction.py`'s reverse transform (TASK-0007) with a real
target-slot temperature forecast. Requires no new coordinator listener
code — TASK-0010's generic `forward()`-push loop already picks this
predictor up automatically once it overrides `forward()`.

**Readiness-time note (added after `TASK-0005-patch-4`, ADR-001 §4a):**
`regression.base.build_pool` — this task's shared fitting mechanics —
now also requires a `recency_decay_max` argument (ADR-001 §4a's
day-recency weighting). Whether this second, temperature-predicting fit
should reuse the same `self._recency_decay_max` the yield fit uses, or
its own value (e.g. `0.0`, since a learned *temperature* model has no a
priori reason to expect the same seasonal-regime-shift behavior a
shading pattern does), is this task's own decision to make at
implementation time — this note only flags that the call site now needs
*some* value, not which one. Whichever is chosen, state it explicitly
in this task's own Delivered Artifacts.

## Acceptance Criteria
- Given historical predictor/target pairs for a slot, When the model
  fits using the shared `regression/` strategies (TASK-0005), Then
  `magnitude_weight_i` downweighting is **not** applied (ADR-003c §2 —
  temperature has no near-zero degeneracy).
- Given the weather-forecast-entity config field is set, When
  `forward()` is called on the second `providers/temperature.py`
  instance, Then it returns a non-`None` series without any new
  provider-specific coordinator code (TASK-0010's generic loop handles
  it).
- Given the cell tier, When `predicted_temp` is produced, Then it is used
  directly as `target_cell_temperature` with no ambient→cell uplift
  applied on top (category-error guard, ADR-003c §4).
- Given the ambient tier, When `predicted_temp` is produced, Then it
  passes through the existing ambient→cell uplift formula (TASK-0007)
  unchanged, exactly as a live reading would have.
- Given no weather-forecast entity is configured (or a string on the
  cell/ambient tier has none available), When derating is evaluated,
  Then both the forward and reverse transforms are skipped entirely for
  that string — not degraded to a naive fallback (ADR-003c §5).
- Given the predictor and target series, When read, Then both go through
  `cache.py`'s existing `get_time_range`/`get_regression_pools`
  accessors with no `cache.py` changes required (ADR-003c §6).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/coordinator.py` (extended — instantiates the
  second `providers/temperature.py` instance and the per-slot temperature
  fit, calling into `regression/` a second time)
- `tests/test_coordinator_temperature_forecast.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0005, TASK-0006, TASK-0004, TASK-0007,
     TASK-0010. -->
- `regression.base.<strategy classes>` / `.fit`/`.predict` from `custom_components/shady/regression/` (→ task: TASK-0005-regression-fitting-pipeline)
- `cache.<Cache class>.get_regression_pools` from `custom_components/shady/cache.py` (→ task: TASK-0006-cache-batched-regression-pool-accessor)
- `providers.temperature.<Provider>` from `custom_components/shady/providers/temperature.py` (→ task: TASK-0004-temperature-source-provider)
- `yield_correction.<reverse_transform_function>` from `custom_components/shady/yield_correction.py` (→ task: TASK-0007-yield-corrections)
- `coordinator.ShadyCoordinator` (generic `forward()`-push loop) from `custom_components/shady/coordinator.py` (→ task: TASK-0010-coordinator-recalibration-recompute-push)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
