# Task: Cross-String Aggregate Sensors

- **Status:** done
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

- `custom_components/shady/aggregation.py` (new — pure, zero-`hass`
  module, ADR-000 §6 tier):
  - `sum_values(values: Iterable[float | None]) -> float | None` —
    cross-string sum; `None` only when every input is `None`, treating
    absent strings as "not summed", not as zero.
  - `day_energy_total_wh(slot_values: Sequence[float | None]) -> float`
  - `remaining_energy_wh(slot_timestamps: Sequence[datetime],
    slot_values: Sequence[float | None], now: datetime) -> float`
  - `slot_energy_wh(power_w: float | None) -> float` (5-minute-slot
    Wh helper `day_energy_total_wh`/`remaining_energy_wh` both build on)
  - `trapezoidal_energy_increment(previous: tuple[datetime, float] |
    None, current: tuple[datetime, float]) -> float` — `0.0` when
    `previous is None` (first sample after any reset/restart).

- `custom_components/shady/cache.py` (extended):
  - `EnergyKind = Literal["pv", "fc"]` (new module-level type alias)
  - `Cache.energy_total(kind) -> float`
  - `Cache.set_energy_total(kind, value) -> None`
  - `Cache.last_energy_sample(kind) -> tuple[datetime, float] | None`
  - `Cache.set_last_energy_sample(kind, sample) -> None`
  - `Cache.last_reset_date() -> date | None`
  - `Cache.reset_energy_totals(today: date) -> None` — zeroes both
    totals, clears both last-samples, sets `last_reset_date`
  - `Cache.restore_energy_state(pv_total, fc_total, last_reset_date)
    -> None` — deliberately does **not** restore either
    `last_energy_sample` (stays whatever it already was — `None` on a
    freshly constructed `Cache`)

- `custom_components/shady/coordinator.py` (extended,
  `ShadyCoordinator`):
  - `pv_sum() -> float | None` (ADR-005 §1)
  - `fc_sum(now=None) -> float | None` (ADR-005 §2)
  - `fc_day_array(now=None) -> tuple[list[datetime], list[float |
    None]]` (ADR-005 §3, single `get_time_range(group_by="slot")` call)
  - `fc_day_energy_total(now=None) -> float` (ADR-005 §3's sensor state)
  - `fc_remaining_energy(now=None) -> float` (ADR-005 §4)
  - `_numeric_state(entity_id) -> float | None` (private helper §1 uses)
  - `_accumulate_energy(kind, now, power) -> None` (private, hass-free)
  - `_accumulate_fc_energy(now) -> None` (private; shared by both
    recompute triggers)
  - `_maybe_reset_energy_totals(now) -> bool` (private, idempotent
    day-boundary guard)
  - `async_restore_energy_state() -> None` (public; **not** called from
    `__init__`/`async_startup` — see Known gap below)
  - `_async_persist_energy_state() -> None` (private)
  - `_register_energy_reset_schedule()` / `_handle_energy_reset(now)`
    (private — the fourth coordinator schedule, `hour=0, minute=0,
    second=0`; registered only by `async_restore_energy_state`, not
    `__init__`)
  - `_register_actual_yield_listeners()` /
    `_handle_actual_yield_update(event)` (private — new state-change
    listener, registered from `__init__`, separate from
    `_register_provider_listeners`)
  - `_refit_sync` and `_async_recompute` both now call
    `_accumulate_fc_energy(now)` after recomputing, and `async_refit`/
    `_async_recompute` each `await self._async_persist_energy_state()`
    directly afterward (both are already coroutines on the event loop;
    only the two synchronous `@callback`s above use
    `hass.async_create_task` for this).
  - `self._energy_store: Store[dict[str, Any]]` — new instance
    attribute, `Store(hass, 1, f"{DOMAIN}_{entry.entry_id}
    _energy_totals")`, constructed in `__init__`.
  - New import: `from homeassistant.helpers.storage import Store`
    (bundled with Home Assistant itself — not a new external
    dependency; no `tasks/DEPENDENCIES.md` entry, matching every other
    `homeassistant.*` import already used in this module).

- `custom_components/shady/sensor.py` (extended):
  - `ShadyPvSumSensor(SensorEntity)` — POWER/W/MEASUREMENT
  - `ShadyFcSumSensor(SensorEntity)` — POWER/W/MEASUREMENT
  - `ShadyFcDaySumSensor(SensorEntity)` — ENERGY/Wh/TOTAL;
    `extra_state_attributes` exposes `slot_timestamps`/`slot_values`
  - `ShadyFcRemainingTodaySensor(SensorEntity)` — ENERGY/Wh/TOTAL
  - `ShadyPvEnergyIntegralSensor(SensorEntity)` — ENERGY/Wh/
    TOTAL_INCREASING
  - `ShadyFcEnergyIntegralSensor(SensorEntity)` — ENERGY/Wh/
    TOTAL_INCREASING
  - `async_setup_entry` extended to add all 6 of the above alongside
    the existing per-string `ShadyForecastSensor`s (7 entities total
    for a single-string config entry).
  - New import: `UnitOfEnergy` from `homeassistant.const` (bundled;
    no `DEPENDENCIES.md` entry needed).

- Tests (all real, non-mocked stand-ins per ADR-000 §6):
  - `tests/test_aggregation.py` — pre-existing at session start, 19
    tests, zero-mocking tier, all green; untouched this session.
  - `tests/test_cache_core.py` — new `TestEnergyIntegralTotals` class
    (6 tests), zero-mocking tier.
  - `tests/test_coordinator.py` — new classes `TestPvSum`, `TestFcSum`,
    `TestFcDayArray`, `TestFcDayEnergyTotalAndRemaining`,
    `TestEnergyAccumulation`, `TestActualYieldTriggeredAccumulation`,
    `TestEnergyRestorePersistence`, `TestRecomputeTriggersFcAccumulation`
    (28 tests); own copy of the `homeassistant` stub extended with
    `FakeStore`/`homeassistant.helpers.storage`, `FakeStates.set`'s new
    `state=` parameter, and a `_set_state` helper (fires a state-change
    listener from inside a running event loop, draining any
    fire-and-forget task it schedules).
  - `tests/test_sensor_aggregates.py` (new file) — own independent
    `homeassistant`/`sensor`/`const` stub (not sharing `sys.modules`
    state with any other test file), 17 tests covering all 6 new
    sensor classes' device/state classes, unique IDs, and values.
  - `tests/test_button.py`, `tests/test_sensor_forecast.py` — each
    file's own independent `_install_ha_stub()` copy extended with
    `FakeStore`/`homeassistant.helpers.storage` and `FakeStates.set`'s
    `state=` parameter (both files construct `ShadyCoordinator`
    directly, which now constructs a `Store`).
    `test_sensor_forecast.py`'s `test_one_sensor_per_configured_string`
    was renamed
    `test_one_sensor_per_configured_string_plus_six_aggregates` and its
    assertion updated from 1 to 7 entities, since
    `async_setup_entry` now adds the 6 new aggregates too.
- External dependencies added: none (`tasks/DEPENDENCIES.md`
  unchanged — `Store` and `UnitOfEnergy` are both bundled with Home
  Assistant, matching precedent for every other `homeassistant.*`
  import already used in this project).

**Known gap, by design (matches this task's own Dependencies — TASK-0016
does not exist yet):** `async_restore_energy_state()` is implemented and
covered by its own tests (`TestEnergyRestorePersistence`), but is not
called anywhere during real coordinator construction — the acceptance
criterion's "When `async_setup_entry` runs" step is `TASK-0016`'s job
(`__init__.py` does not exist yet). Until `TASK-0016` adds that call,
the midnight-reset schedule is also never registered (it's registered
by `async_restore_energy_state` itself, deliberately, so it cannot fire
before a restore has run) and the two integral totals stay at zero
across a real restart. `TASK-0016`'s own task file should list this
task as a dependency and its Consumed Interfaces should reference
`async_restore_energy_state` from this delivery.

**Environment/tooling note, unrelated to this task's own scope (see
`tasks/INDEX.md`'s refinement log for the full, corrected account):**
`custom_components/shady/providers/normalize.py` (×2),
`custom_components/shady/providers/temperature.py` (×1), and this
task's own new `coordinator.py::_numeric_state` all use
`except (TypeError, ValueError):`. The unparenthesized form
(`except TypeError, ValueError:`) is equally valid — PEP 758, Python
3.14 — and is what `ruff format` will produce by default given this
project's `requires-python = ">=3.14"`, since every dev/CI environment
actually available so far only has Python 3.12/3.13. `pyproject.toml`'s
`[tool.ruff]` now pins `target-version = "py313"` (one feature-release
behind the project's actual `requires-python`/`mypy` target) so
`ruff format`/`ruff check` keep the parenthesized, broadly-compatible
form regardless. This is a cosmetic-only pin — it does not change what
Python version the integration itself targets or runs on.
