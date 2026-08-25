# Task: Corrected Forecast Sensor & Manual Recalculation

- **Status:** done
- **Related ADRs:** [ADR-002 §3, ADR-002 §5, ADR-000 §3]
- **Dependencies:** [TASK-0010-coordinator-recalibration-recompute-push, TASK-0010-patch-1-recalibration-triggers-recompute, TASK-0010-patch-2-string-enumeration]

## Goal
Implement `sensor.py`'s `ShadyForecastSensor` (per string, today+
tomorrow horizon, reads coordinator state — stays thin, no business
logic) and `button.py`'s `ShadyRecalculateButton` (calls the
coordinator's refit method, logs/swallows exceptions per ADR-000 §8).
Each file owns its own **platform-level** `async_setup_entry(hass,
entry, async_add_entities)` (HA's standard per-platform entry point,
distinct from the integration-level one in `custom_components/shady/
__init__.py`) — reading the already-constructed `ShadyCoordinator` out
of `hass.data[DOMAIN][entry.entry_id]`.

**Correction at readiness time (Scenario A — caught before any code was
written, not after):** this task's original Phase-2 draft described
"completing `__init__.py`'s wiring" as part of its own scope. ADR-002
§1a's decision text (added mid-`TASK-0010`, after this task was already
drafted) explicitly attributes the *entire* `__init__.py` flow —
constructing the coordinator, building `hass.data`, forwarding
`sensor`/`switch`/`button` platforms via
`hass.config_entries.async_forward_entry_setups`, and the
`ConfigEntryNotReady`/`async_at_started`/`async_schedule_reload` guard —
to `TASK-0016` in one coherent implementation ("`__init__.py`,
TASK-0016" appears directly in ADR-002 §1a's decision steps). There is
no partial, guard-less version of that flow left for this task to own:
`TASK-0016` builds it from scratch, not on top of a partial version this
task would deliver. `coordinator.py`'s own `async_startup` docstring
(`TASK-0010`'s Delivered Artifacts) independently confirms this same
attribution ("called by `__init__.py` (TASK-0016)"). This task's scope
is corrected to exclude `__init__.py` entirely; `custom_components/
shady/__init__.py` is untouched by this task and remains the existing
skeleton until `TASK-0016` runs.

This also resolves an ordering question: `TASK-0016` depends on this
task (needs `sensor.py`/`button.py` to exist before it can forward
platforms to them), so this task cannot itself depend on `TASK-0016`'s
`__init__.py` wiring without a cycle. Testing this task's platform-level
`async_setup_entry`s therefore seeds `hass.data[DOMAIN][entry.entry_id]`
with a real `ShadyCoordinator` directly in the test — exactly how
`tests/test_coordinator.py`'s own `_make_coordinator()` fixture already
constructs one — rather than going through the (not-yet-existing)
integration-level `__init__.py`.

This task does **not** depend on TASK-0009 (config flow) — the
coordinator this task's platform files consume is built from
`entry.data` by the field names ADR-010 already fixes, without
importing anything from `config_flow.py`.

## Acceptance Criteria
- Given `hass.data[DOMAIN][entry.entry_id]` already holds a
  `ShadyCoordinator` for a config entry with one configured string and
  seeded fake recorder/provider data, When `sensor.py`'s
  `async_setup_entry` runs, Then one `ShadyForecastSensor` per configured
  string is added, and it exposes a plausible corrected value for that
  string (via `coordinator.strings()` + `coordinator.async_startup()`
  already having run against the seeded data before the assertion).
- Given `ShadyRecalculateButton.async_press()` is called, When pressed,
  Then it triggers the exact same refit code path as the midnight
  schedule (TASK-0010), and any exception during refit is logged and
  swallowed, not raised (ADR-000 §8).
- Given `button.py`'s `async_setup_entry` runs for a config entry, When
  entities are added, Then exactly one `ShadyRecalculateButton` is added
  (one per config entry, not per string).
- Given the sensor's state and attributes, When inspected, Then
  `ShadyForecastSensor` contains no computation of its own — every value
  is read directly from what `coordinator.py` last pushed (thin-glue
  principle, ADR-000 §3).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/sensor.py` (new: `ShadyForecastSensor` +
  platform-level `async_setup_entry`)
- `custom_components/shady/button.py` (new: `ShadyRecalculateButton` +
  platform-level `async_setup_entry`)
- `tests/test_sensor_forecast.py`, `tests/test_button.py` (real `hass`
  fixture, extending the `homeassistant`-stub convention TASK-0009/
  TASK-0010 established)
- `custom_components/shady/__init__.py` is **not** touched by this task
  (see Goal — corrected scope, now TASK-0016's alone)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0010 + TASK-0010-patch-1. -->
- `coordinator.ShadyCoordinator` from `custom_components/shady/coordinator.py`
  (→ task: TASK-0010-coordinator-recalibration-recompute-push,
  TASK-0010-patch-1-recalibration-triggers-recompute):
  - `__init__(hass, entry)` — safe to call unconditionally, no
    `hass.states` access at construction time; this task's tests
    construct one directly and seed it into `hass.data`, mirroring how
    `TASK-0016` will do so for real later.
  - `async def async_refit(now: datetime | None = None) -> None` — the
    one refit routine; `button.py`'s `ShadyRecalculateButton.async_press`
    calls this directly.
  - `def forecast_sensor_id(string_index: int) -> str` — the exact
    cache `sensor_id` `ShadyForecastSensor` reads via
    `cache.get_time_range`.
  - `self.cache: Cache` — exposed directly; read through it for the
    sensor's today+tomorrow values.
  - `def strings() -> list[tuple[int, str]]` (→ task:
    TASK-0010-patch-2-string-enumeration) — `(index, name)` pairs, in
    config order, for every configured string; `async_setup_entry` uses
    this to instantiate one `ShadyForecastSensor` per string. No private
    `_StringConfig` access needed.
- `cache.Cache.get_time_range(sensor_ids, start, end, *, on_invalid=...)`
  and `Cache.index_for`/`Cache.timestamp_for` (static) — from
  `custom_components/shady/cache.py` (→ task:
  TASK-0002-cache-core-time-series-store), for reading
  `ShadyForecastSensor`'s today+tomorrow horizon out of
  `coordinator.cache`.
- `const.py`'s `DOMAIN` — from `custom_components/shady/const.py`.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/sensor.py` →
  - `async def async_setup_entry(hass, entry, async_add_entities) -> None`
    — platform-level entry point; reads `hass.data[DOMAIN][entry.entry_id]`
    (built elsewhere — `TASK-0016`), adds one `ShadyForecastSensor` per
    `coordinator.strings()` pair.
  - `class ShadyForecastSensor(SensorEntity)` —
    `__init__(coordinator, entry, string_index, string_name)`;
    `_attr_unique_id` = `coordinator.forecast_sensor_id(string_index)`
    exactly (same identifier as the cache key, TASK-0010's Delivered
    Artifacts); `_attr_name` = `f"{string_name} Forecast"`;
    `_attr_device_class = SensorDeviceClass.POWER`,
    `_attr_native_unit_of_measurement = UnitOfPower.WATT`,
    `_attr_state_class = SensorStateClass.MEASUREMENT`; no
    `_attr_should_poll` override (defaults to HA's standard polling —
    this task's own scope decision, see Goal: no push mechanism exists
    from `coordinator.py` to entities). Public surface used by tests:
    `.native_value` (current-slot value, `float | None`, exactly what
    `cache.get_time_range([sensor_id], now, now, on_invalid="raw")`
    returns — legitimately `None` for the exact instant a recompute just
    ran against, per `not_before_index` freeze semantics,
    TASK-0010-patch-1), `.extra_state_attributes` (`{"today": [288
    values], "tomorrow": [288 values]}`, each `float | None`, read via
    `cache.get_time_range(..., on_invalid="raw")` over the calendar-day
    boundary), and `._now: Callable[[], datetime]` (injectable clock,
    defaults to `datetime.now(UTC)`, mirrors `coordinator.py`'s own
    `_now` convention — tests substitute a fixed value).
- `custom_components/shady/button.py` →
  - `async def async_setup_entry(hass, entry, async_add_entities) -> None`
    — platform-level entry point; adds exactly one
    `ShadyRecalculateButton` per config entry (not per string).
  - `class ShadyRecalculateButton(ButtonEntity)` —
    `__init__(coordinator, entry)`; `_attr_unique_id` =
    `f"{DOMAIN}_recalculate_{entry.entry_id}"`; `_attr_name` =
    `"Recalculate"`; `async def async_press() -> None` calls
    `coordinator.async_refit()` (the exact same code path
    `TASK-0010`'s midnight schedule uses) inside a broad `try/except
    Exception`, logging via `_LOGGER.exception` and swallowing — never
    raises (ADR-000 §8).
- `tests/test_sensor_forecast.py` → `TestAsyncSetupEntry` (1),
  `TestForecastSensorValue` (5) — 6 tests. Extends the per-test-file
  `homeassistant` stub convention with `homeassistant.components.sensor`
  (`SensorEntity`/`SensorDeviceClass`/`SensorStateClass`) and
  `homeassistant.const.UnitOfPower`. Fully self-contained (own
  `FakeHomeAssistant`/`_make_entry`/`_make_ready_coordinator`
  fixtures), independent of `test_coordinator.py`'s or any other test
  file's `sys.modules` state.
- `tests/test_button.py` → `TestAsyncSetupEntry` (2),
  `TestRecalculateButtonPress` (3) — 5 tests. Same stub convention,
  extended with `homeassistant.components.button.ButtonEntity`.
- No external dependencies added.
- **`custom_components/shady/__init__.py` untouched by this task** —
  scope corrected at readiness time (Scenario A, see this task's own
  Goal section and `tasks/INDEX.md`'s refinement log); remains
  `TASK-0016`'s.
- Gates: `ruff check`/`ruff format --check` clean on all 4 new files;
  `mypy --config-file mypy.ini custom_components/shady` clean across all
  20 source files (both new HA-entity subclasses needed a `# type:
  ignore[misc]` on the class statement, the exact same pattern
  `config_flow.py`'s `ShadyConfigFlow`/`ShadyOptionsFlow` already use for
  subclassing HA's `Any`-typed base classes — `mypy.ini`'s
  `[mypy-shady.sensor]`/`[mypy-shady.button]` sections already
  anticipated this and were pre-existing, unchanged by this task). Full
  suite: 165/165 (154 pre-task + 6 sensor + 5 button).
