# Task: Cache — Batched Regression-Pool Accessor

- **Status:** done
- **Related ADRs:** [ADR-008 §2, ADR-008 §3]
- **Dependencies:** [TASK-0002-cache-core-time-series-store]

## Goal
Extend `cache.py` (delivered by TASK-0002) with a `float64` shadow array
per sensor (NaN standing in for gap/unavailable), kept incrementally in
sync on every push/invalidate, and the batched
`get_regression_pools(sensor_ids, smoothing_radius) -> dict[sensor_id,
np.ndarray]` accessor for the full 288-slot sweep.

**This task modifies the same file as TASK-0002 — sequential, definer
(TASK-0002) first.**

## Acceptance Criteria
- Given a sensor with some `None`/`str` entries in its three-state list,
  When the shadow array is read, Then those positions are `NaN` and all
  `float` positions match exactly.
- Given a `push()` or `invalidate()` call, When the three-state list is
  mutated, Then the shadow array is updated in the same call (kept
  incrementally in sync, not rebuilt on read).
- Given `get_regression_pools(sensor_ids, smoothing_radius=1)`, When
  called, Then it returns one 2-D array per sensor of shape `(288,
  window_days * (2*1 + 1))` in a single call — not 864 individual
  per-slot calls.
- Given the existing `get_time_range` accessor from TASK-0002, When this
  task's changes are applied, Then `get_time_range`'s behavior and output
  are unaffected (regression test against TASK-0002's existing suite).
- Given a `NaN` entry in the returned pool, When `regression/base.py`
  (TASK-0005, not this task) would derive a weight mask, Then
  `~np.isnan(pool)` is a valid mask this accessor's shape supports (this
  task verifies shape/dtype only, not the weighting logic itself).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/cache.py` (extended, not recreated)
- `tests/test_cache_regression_pools.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- TASK-0002's existing test suite still passes unmodified.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0002. -->
- `cache.<Cache class>` from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/cache.py` → attribute `shadow`, method `get_regression_pools()`
