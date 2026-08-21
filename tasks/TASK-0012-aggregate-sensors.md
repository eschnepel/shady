# Task: Cross-String Aggregate Sensors

- **Status:** todo
- **Related ADRs:** [ADR-005 §1, ADR-005 §2, ADR-005 §3, ADR-005 §4, ADR-005 §5, ADR-005 §6]
- **Dependencies:** [TASK-0011-forecast-sensor-and-recalculate-button, TASK-0002-cache-core-time-series-store]

## Goal
Implement the six config-entry-level sensors (`ShadyPvSumSensor`,
`ShadyFcSumSensor`, `ShadyFcDaySumSensor`, `ShadyFcRemainingTodaySensor`,
`ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor`), the
trapezoidal energy-increment pure function in `aggregation.py`, the
fourth (midnight-reset) coordinator schedule, and restart-persisted
integral totals with `last_reset_date` idempotency.

**Shared-file note:** this task and TASK-0013 (intraday correction) both
add a new schedule to `coordinator.py`. TASK-0013 additionally depends on
this task to sequence the two coordinator.py edits.

## Acceptance Criteria
- Given a previous `(timestamp, power)` sample and a new one, When the
  trapezoidal energy-increment function runs, Then it returns the
  correct Wh increment for that interval — pure function, zero mocking.
- Given `ShadyFcDaySumSensor`, When built via
  `get_time_range(sensor_ids, start=00:00, end=23:55,
  group_by="slot")`, Then its `slot_values` are the cross-string sum at
  each of today's 288 slots, including already-past ones.
- Given the midnight-reset trigger fires, When it fires, Then
  `ShadyPvEnergyIntegralSensor`/`ShadyFcEnergyIntegralSensor` reset to
  zero and `last_reset_date` updates to today.
- Given a restart lands inside `[00:00, 00:01)`, When `async_setup_entry`
  runs, Then the idempotency check (`last_reset_date` already today →
  keep restored total; otherwise → zero immediately) produces exactly
  one reset, never zero or two, regardless of whether the scheduled
  trigger also fires in the same narrow window.
- Given the integral totals, When Home Assistant restarts mid-day, Then
  the exact accumulated value survives (restore-state wiring) — unlike
  every other cache in this design.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/aggregation.py` (new)
- `custom_components/shady/sensor.py` (extended — 6 new sensor classes)
- `custom_components/shady/coordinator.py` (extended — midnight-reset
  trigger, integral read/write via `cache.py`)
- `custom_components/shady/cache.py` (extended — 2 restart-persisted
  totals + `last_reset_date`)
- `tests/test_aggregation.py` (zero-mocking), `tests/test_sensor_aggregates.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0011 and TASK-0002. -->
- `coordinator.ShadyCoordinator` from `custom_components/shady/coordinator.py` (→ task: TASK-0011-forecast-sensor-and-recalculate-button)
- `sensor.ShadyForecastSensor` (push pattern) from `custom_components/shady/sensor.py` (→ task: TASK-0011-forecast-sensor-and-recalculate-button)
- `cache.<Cache class>.get_time_range` from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
