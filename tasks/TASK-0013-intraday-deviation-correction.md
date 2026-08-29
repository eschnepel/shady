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
- `custom_components/shady/aggregation.py` → functions `ramp_weight(active_slots_since_reset: int, ramp_slots: int) -> float`, `intraday_correction_factor(pv_energy_window: float, fc_energy_window: float, ramp_weight: float, intraday_correction_cutoff: float) -> float`, `crossfade(old_prediction: float, new_prediction: float, ramp_weight: float) -> float`
- `custom_components/shady/forecast_adjust.py` → new function `reverse_transformed_forecast(model, fc, target_cell_temperature, coefficient_per_c, *, provider_already_corrects=False) -> tuple[NDArray[float64], NDArray[float64]]` (steps 1–2 of the pipeline, unclamped, not yet intraday-corrected). `adjust_forecast` (TASK-0008) is unchanged in signature/behavior, now implemented on top of `reverse_transformed_forecast` + the existing `clamp_output`.
- `custom_components/shady/cache.py` → dataclasses `IntradayBasis` (`values: dict[int, float]`, `fc: dict[int, float]`, `inverter_limit: float | None`) and `IntradayState` (`reset_at: datetime`, `active_slots_since_reset: int`, `basis: IntradayBasis`, `ratio_string: float | None`, `effective_factor: float`, `frozen_basis: IntradayBasis | None`, `frozen_effective_factor: float | None`); `Cache.intraday_state(string_index: int) -> IntradayState | None`, `Cache.set_intraday_state(string_index: int, state: IntradayState | None) -> None`. Not restart-persisted.
- `custom_components/shady/coordinator.py` →
  - New config fields read in `__init__`: `self._intraday_correction_mode`, `self._intraday_correction_cutoff`, `self._window_slots`, `self._ramp_slots` (from `const.py`'s existing `CONF_INTRADAY_CORRECTION_MODE`/`CONF_INTRADAY_CORRECTION_CUTOFF`/`CONF_WINDOW_SLOTS`/`CONF_RAMP_SLOTS`, already wired end-to-end by `config_flow.py` since TASK-0009-patch-2 — no config_flow changes needed).
  - `ShadyCoordinator.raw_forecast_sensor_id(string_index: int) -> str` — the `values_raw` transparency cache key (`f"{forecast_sensor_id}_raw"`).
  - `ShadyCoordinator.intraday_attributes(string_index: int) -> dict[str, Any]` — returns `intraday_ratio`, `intraday_state`, `intraday_ramp_weight`, `intraday_blend_active` (the four scalar ADR-006 §4 attributes; `values_raw` is a time-series array read directly by `sensor.py`, not through this method).
  - `_recompute_string` restructured: assembles a per-string, whole-horizon pre-clamp basis via the new `_predict_day_basis` (replaces the old `_predict_day`), then either `_clamp_basis` (mode `"off"`) or `_apply_intraday_reset` (mode `"ramping"`/`"blending"`) before the single `cache.push`.
  - `_apply_intraday_reset`, `_compute_intraday_output`, `_intraday_energy_window`, `_advance_intraday_string` — the reset/tick logic described in the Goal.
  - `_register_intraday_schedule`, `_handle_intraday_tick` (`@callback`), `_async_intraday_tick`, `_intraday_tick_sync` — the independent 5-minute poll, only registered when `intraday_correction_mode != "off"`; dispatched via `hass.async_add_executor_job` (recorder access in `_intraday_energy_window`).
  - No new imports beyond `homeassistant.helpers.event.async_track_time_interval` and `dataclasses.replace`; no new external dependency.
- `custom_components/shady/sensor.py` → `ShadyForecastSensor.__init__` now stores `self._string_index`/`self._raw_sensor_id`; `extra_state_attributes` extended with `values_raw` (`{"today": [...], "tomorrow": [...]}`, read off `raw_forecast_sensor_id`) plus the four scalar keys from `coordinator.intraday_attributes`.
- `tests/test_aggregation_intraday.py` — 19 zero-mocking tests for the three new pure functions.
- `tests/test_coordinator_intraday.py` — 12 real-`hass`-fixture tests: reset semantics (first-activation parity, plain-basis-at-w=0), Ramping's linear ramp and cutoff clamp, the final-clamp guarantee, a provider-update mid-day reset, Blending's freeze/crossfade and convergence-to-Ramping's-steady-state, the four transparency attributes, and TASK-0012's aggregate sensors needing no correction logic of their own.
- Test-infrastructure changes to 4 existing test files (`test_coordinator.py`, `test_button.py`, `test_sensor_forecast.py`, `test_sensor_aggregates.py`): each file's hand-written `homeassistant.helpers.event` stub gained `async_track_time_interval` (non-auto-firing, same convention as `async_track_time_change`) so `coordinator.py`'s new import resolves; `test_sensor_forecast.py`'s `extra_state_attributes` key-set assertion updated to include the 4 new scalar keys plus `values_raw`.
- External dependencies added: none — see `tasks/DEPENDENCIES.md` (unchanged).