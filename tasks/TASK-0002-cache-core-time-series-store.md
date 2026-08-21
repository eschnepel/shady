# Task: Cache Core — Time-Series Store & Contiguous-Range Accessor

- **Status:** todo
- **Related ADRs:** [ADR-007, ADR-007a §1, ADR-007a §2, ADR-007a §3, ADR-007a §4, ADR-007a §5]
- **Dependencies:** []

## Goal
Build `cache.py`'s foundational time-series storage: the three-state
(`float|None|str`) index-addressable store, validated-range tracking,
push/invalidate, `trim()`, injected `fetch_fn` with validate-before-read,
and the `get_time_range` contiguous-range accessor. This is the shared
storage layer nearly every later task builds on — keep it free of any
`hass` import.

## Acceptance Criteria
- Given a cache constructed with a fake `fetch_fn` returning canned
  three-state data and no valid data yet for a sensor, When
  `get_time_range` is called for that sensor, Then the validation
  function fetches the sensor's entire configured `window_days` history
  in one call before returning results (ADR-007a §4).
- Given a sensor already valid except for a missing recent tail, When
  `get_time_range` is called, Then only the missing tail is fetched.
- Given a `push(sensor_id, {index: value, ...})` call whose lowest index
  is below a supplied `not_before_index`, When the push is applied, Then
  entries below that boundary are silently dropped and never written
  (ADR-007a §3's frozen-history guarantee).
- Given a `to_index=None` sensor (Shady-pushed, e.g. a stand-in for
  `ShadyForecastSensor`), When values are pushed, Then `validated`'s
  `to_index` extends without ever being re-queried.
- Given `get_time_range(sensor_ids, start, end, group_by="sensor")` vs.
  `group_by="slot"`, When called against the same data, Then the two
  return the documented complementary shapes (`{sensor_id: [v...]}` vs.
  `[{sensor_id: v}, ...]`) per ADR-007a §5.
- Given `cache.trim()` is called after the rolling window has advanced,
  When trimming occurs, Then `list_offset` advances and `validated`
  ranges stay meaningful (no off-by-one against the new offset).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/cache.py` (storage core only — no
  `get_pinned_slot_pool`/`get_regression_pools` yet, see TASK-0006/TASK-0015)
- `tests/test_cache_core.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- Zero-mocking test suite (ADR-000 §6): no `unittest.mock`, no fake
  `hass`, loaded via direct file-path import.

## Consumed Interfaces
<!-- None — this task has no dependencies. -->

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
