# Task: Intraday Deviation Correction

- **Status:** done
- **Related ADRs:** [ADR-006 §1, ADR-006 §1a, ADR-006 §1b, ADR-006 §2, ADR-006 §3, ADR-006 §4, ADR-006 §5]
- **Dependencies:** [TASK-0011-forecast-sensor-and-recalculate-button, TASK-0008-forecast-adjustment, TASK-0012-aggregate-sensors]

## Goal
Implement the three-state (`off`/`ramping`/`blending`) intraday
deviation correction: `ramp_weight`, `intraday_correction_factor`,
`crossfade` pure functions in `aggregation.py`; per-string ramp/crossfade
state in `cache.py` (short-lived, not restart-persisted); the 5-minute
recorder-poll coordinator trigger; and wiring the correction into
`ShadyForecastSensor`'s pipeline **ahead of** `forecast_adjust.py`'s
final output clamp (TASK-0008) — never clamped mid-pipeline or per
crossfade side. Adds the transparency attributes
(`intraday_ratio`/`intraday_state`/`intraday_ramp_weight`/`values_raw`/
`intraday_blend_active`) to `ShadyForecastSensor`.

**Shared-file dependency:** this task extends `forecast_adjust.py`
(TASK-0008) to insert the correction step before its existing clamp, and
extends `coordinator.py`/`cache.py` alongside TASK-0012's edits to the
same files — sequenced after TASK-0012 to avoid concurrent modification.

## Acceptance Criteria
- Given a string's first active slot of the day, When Ramping or
  Blending is configured, Then both behave identically (nothing to blend
  against yet) — the ramp simply starts (ADR-006 §1b).
- Given `w(t) = min(1, active_slots_since_reset / ramp_slots)`, When
  computed at `w=0`, Then `effective_factor` is exactly `1` (no
  correction applied yet); at `w=1`, the full clamped ratio applies
  (ADR-006 §1a).
- Given Ramping and a provider update fires mid-day, When it fires, Then
  the rolling window empties and `w` resets to `0` (visible dip
  expected).
- Given Blending and a provider update fires mid-day, When it fires,
  Then the pre-update state freezes as `old_prediction` and crossfades
  toward `new_prediction` over `ramp_slots`, converging to the exact same
  steady-state value Ramping would reach for the same slot.
- Given `ratio_string`, When computed, Then it is clamped to `[1 -
  intraday_correction_cutoff, 1 + intraday_correction_cutoff]` (default
  ±0.10) before feeding `effective_factor`.
- Given a corrected value passes through this correction and then
  `forecast_adjust.py`'s clamp, When the full pipeline runs, Then the
  final `[0, FC]`/inverter-limit clamp is applied exactly **once**, after
  this correction — never applied separately to each side of a Blending
  crossfade.
- Given `ShadyFcDaySumSensor`/`ShadyFcRemainingTodaySensor` (TASK-0012),
  When this correction is active for a string, Then those aggregate
  sensors need no correction logic of their own — they simply sum
  whichever per-string values are now already-corrected.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/aggregation.py` (extended — 3 new pure functions)
- `custom_components/shady/forecast_adjust.py` (extended — correction
  step inserted ahead of the existing clamp)
- `custom_components/shady/coordinator.py` (extended — 5-minute trigger)
- `custom_components/shady/cache.py` (extended — ramp/crossfade dict store)
- `custom_components/shady/sensor.py` (extended — transparency attributes)
- `tests/test_aggregation_intraday.py` (zero-mocking),
  `tests/test_coordinator_intraday.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- TASK-0008's and TASK-0012's existing test suites still pass.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0011, TASK-0008, TASK-0012. -->
- `sensor.ShadyForecastSensor` from `custom_components/shady/sensor.py` (→ task: TASK-0011-forecast-sensor-and-recalculate-button)
- `forecast_adjust.<apply function / clamp step>` from `custom_components/shady/forecast_adjust.py` (→ task: TASK-0008-forecast-adjustment)
- `coordinator.ShadyCoordinator` / `cache.<Cache class>` (post-TASK-0012 state) from `custom_components/shady/coordinator.py` / `cache.py` (→ task: TASK-0012-aggregate-sensors)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/aggregation.py` adds the pure `ramp_weight`,
  `intraday_correction_factor`, and `crossfade` helpers.
- `custom_components/shady/cache.py` now stores short-lived intraday
  state per string.
- `custom_components/shady/forecast_adjust.py` applies intraday factors
  and optional crossfades before the final clamp.
- `custom_components/shady/coordinator.py` computes the intraday context
  on recompute, refreshes it on provider updates and 5-minute ticks, and
  clears it on midnight reset.
- `custom_components/shady/sensor.py` exposes the intraday transparency
  attributes on `ShadyForecastSensor`.
- `tests/test_aggregation.py`, `tests/test_forecast_adjust.py`,
  `tests/test_coordinator.py`, `tests/test_sensor_forecast.py`, and
  `tests/test_sensor_aggregates.py` cover the new behavior.
