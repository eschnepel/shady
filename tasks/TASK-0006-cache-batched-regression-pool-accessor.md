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
- `cache.Cache` from `custom_components/shady/cache.py` (→ task:
  TASK-0002-cache-core-time-series-store) — extending this class in
  place, not recreating it. Relevant existing members this task builds
  on directly: `Cache.__init__(window_days, fetch_fn)`,
  `Cache.index_for`/`Cache.timestamp_for` (staticmethods),
  `Cache._ensure_sensor`, `Cache._write` (the single choke point for
  every mutation — both the push path and the fetch-and-store path route
  through it), `Cache._validate_range` (validate-before-read, reused
  as-is for this task's own window), `Cache.trim`, `Cache._values`/
  `Cache._list_offset` (the three-state list + its alignment offset,
  which this task's shadow array must stay in lockstep with).
- `custom_components/shady/cache.py`'s module constants: `SLOT_MINUTES`,
  `SLOT_DURATION`, `SLOTS_PER_DAY`, `EPOCH`, `FetchFn`, `OnInvalid` — all
  reused unchanged.
- ADR-000 §4 Amendment (NDArray[np.float64] typing convention) applies
  from this task onward — see `tasks/INDEX.md` refinement log,
  2026-08-22.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/cache.py` (extended in place; every existing
  TASK-0002 symbol name/signature is unchanged):
  - `Cache.__init__` now also initializes `self._shadow: dict[str,
    NDArray[np.float64]] = {}`.
  - `Cache._ensure_sensor` now also seeds an empty `float64` shadow array
    for a newly-seen `sensor_id`.
  - `Cache._write` (the single choke point for every mutation — both the
    push path and the fetch-and-store path) now also updates the shadow
    array at the same relative position, growing/prepending it in
    lockstep with the three-state list (same length, same
    `list_offset`, always).
  - `Cache.trim` now also slices the shadow array by the exact same
    `drop_count` used for the three-state list, in the same loop
    iteration — never drifts out of alignment.
  - `_shadow_value(value: float | None | str) -> float` (module-level
    helper) — the three-state → shadow encoding: `float` passes through,
    `None`/`str` both become `NaN`.
  - `Cache.get_regression_pools(sensor_ids: list[str], smoothing_radius: int, reference: datetime | None = None) -> dict[str, NDArray[np.float64]]`
    — the new accessor (ADR-008 §2). Per sensor: `_validate_range` is
    called first (validate-before-read, same as `get_time_range`), then
    the pool is built via broadcast/gather over the shadow array. Shape
    `(288, window_days * (2*smoothing_radius + 1))`, `dtype=float64`.
    **Column layout:** offsets concatenated in ascending order
    (`-radius, ..., 0, ..., +radius`), each contributing exactly
    `window_days` columns, oldest day first within each block — matches
    `regression/base.py`'s `build_pool` convention exactly, so a caller
    (TASK-0010) slices out each `window_days`-wide block in this same
    order to build `build_pool`'s `dict[int, NDArray]`-per-offset input.
    **Window:** the most recent `window_days` *complete* days ending
    yesterday (never today — ADR-002 §1 never trains on incomplete-day
    data). **`reference` parameter** (not in ADR-008 §2's literal
    signature): anchors "today", defaults to `datetime.now(UTC)`,
    exposed for zero-mocking testability — the same pattern `trim()`
    already establishes; omitting it reproduces the ADR's real-time
    behavior exactly, so this is an addition, not a deviation.
    **288-slot day-boundary wraparound:** resolved via plain
    absolute-index arithmetic (`day_start(d) + slot + offset`), correct
    whether or not `slot + offset` under/overflows `[0, 288)`, with no
    explicit modulo step. When that arithmetic lands outside this call's
    own window (the earliest day's negative-offset neighbors; the
    latest/yesterday's positive-offset neighbors reaching into today),
    the cell is `NaN` — no fetch beyond the configured window is ever
    attempted for these edge cells.
- `tests/test_cache_regression_pools.py` → 10 zero-mocking tests (7 test
  classes) covering all 5 acceptance criteria plus one extra class
  (`TestDayBoundaryWraparound`) exercising the 288-slot wraparound edge
  case that follows directly from ADR-008 §2 / `regression/base.py`'s
  documented gap but wasn't separately called out in the acceptance
  criteria.
- External dependencies added: none (`numpy` already declared;
  `numpy.typing` ships with it).
- CI gate: `mypy --strict` (0 issues, 24 files), `ruff check` + `ruff
  format --check` (clean), `pytest` — `tests/test_cache_core.py`'s 8
  TASK-0002 tests pass **unmodified** (regression check, this task's own
  Definition-of-Done requirement); full suite 116/116 (106 pre-existing
  + 10 new).
