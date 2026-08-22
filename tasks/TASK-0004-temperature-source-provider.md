# Task: Temperature Source Provider

- **Status:** done
- **Related ADRs:** [ADR-003b §1a, ADR-012 §1]
- **Dependencies:** [TASK-0001-provider-base-architecture]

## Goal
Implement `providers/temperature.py`: resolve the config-selected
temperature source across the three-tier hierarchy (module/cell sensor,
ambient sensor, weather-integration) and provide `fetch()`/`forward()`
per tier. This class is later reused as-is for ADR-003c's independent
weather-forecast-temperature predictor field (TASK-0014) — no
tier-specific behavior should be hardcoded elsewhere.

## Acceptance Criteria
- Given a config-selected `sensor.*` entity with `device_class:
  temperature` (module/cell or ambient tier), When `fetch()` is called
  for a past range, Then it returns that sensor's own recorded history,
  with no discovery/scoring step (ADR-003b §1a: "a plain entity selector
  ... is sufficient").
- Given a config-selected `weather.*` entity (weather-integration tier),
  When `fetch()` is called, Then it uses the entity's `forecast`
  attribute for the prediction-time case, per ADR-003b §1b.
- Given a `sensor.*`-tier instance, When `forward(now)` is called, Then
  it returns `None` (base class default left in place — no forecasting
  concept for a plain sensor, ADR-003c Context).
- Given a `weather.*`-tier instance, When `forward(now)` is called, Then
  it returns a non-`None`, genuinely forward-looking series (this is the
  tier ADR-003c §3 later reuses for its own predictor field).
- Given `identify()` is called on any tier, When resolved, Then it
  returns exactly the config-flow-selected entity with no ranking step.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/providers/temperature.py`
- `tests/test_providers_temperature.py` (real `hass` fixture, per ADR-000 §6's exception)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0001. -->
- `providers.base.<ProviderBase>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)
- `providers.base.<state_value_mapping_helper>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)
- `providers.base.<series_tuple_assembly_helper>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/providers/temperature.py`:
  - `TemperatureTier = Literal["sensor", "weather"]` — `"sensor"` covers
    **both** the module/cell and ambient tiers (ADR-003b §1a): they are
    the same fetch mechanism here (a plain reading, no discovery/
    scoring), since the uplift formula that tells them apart lives in
    `yield_correction.py` (not yet implemented, later task), not in this
    provider.
  - `TemperatureProvider(Provider)` — constructor
    `TemperatureProvider(hass: HomeAssistant, entity_id: str, tier: TemperatureTier)`.
    Takes an **already config-flow-confirmed** entity + tier, mirroring
    TASK-0003's `BaselineProvider` design decision — no ranking/discovery
    step exists on this class (ADR-003b §1a: "a plain entity selector...
    is sufficient"); the config flow (ADR-010, TASK-0009) is responsible
    for presenting a `device_class: temperature` `sensor.*`/`weather.*`
    picker and constructing this class with the confirmed selection.
    - `identify(self) -> EntityRef | None` → `EntityRef(entity_id, None)`
      for the `"sensor"` tier (the reading *is* the entity's main
      state); `EntityRef(entity_id, "temperature")` for the `"weather"`
      tier (the current-condition attribute, ADR-003b §1a).
    - `fetch(self, start, end) -> list[float | None | str]` — `"sensor"`
      tier: the entity's current `state.state` reading, repeated across
      every slot in `[start, end)` (no genuine per-slot history exists
      to query yet — see scope-boundary note below, same as TASK-0003's).
      `"weather"` tier: a slot with a matching entry in the live
      `forecast` attribute uses that forecast value (the "prediction-time
      case", ADR-003b §1b); every other slot falls back to the current
      `temperature` attribute reading (the "training-set case", ADR-003b
      §1a) — one `fetch()` naturally serves both cases depending on
      which slots the live forecast happens to cover.
    - `forward(self, now) -> list[tuple[datetime, float]] | None` —
      `"sensor"` tier: always `None` (no forecasting concept for a plain
      sensor, ADR-003c Context — this is an explicit conditional
      override that *returns* the base class's default value, since one
      shared class handles both tiers per this task's own "no
      tier-specific behavior hardcoded elsewhere" directive; it is not
      literally "no override exists," but the observable behavior
      matches the base default exactly). `"weather"` tier: the live
      `forecast` attribute's series, filtered to `timestamp >= now` —
      always a list (possibly empty) when the entity resolves, `None`
      only when the entity itself is unresolvable.
  - `_parse_forecast_series(forecast_raw) -> list[tuple[datetime, float]]`
    (module-private) — resolves a `weather.*` `forecast` attribute using
    fixed, stable key names (`"datetime"`, `"temperature"`) with **no**
    alias-table/scoring step, per ADR-003b §1a's explicit contrast with
    ADR-009's baseline-discovery heuristics. Reuses
    `providers.base.assemble_series` (ADR-012 §1a), same pattern as
    TASK-0003's `normalize.py`.
  - **Reuse note for TASK-0014 (ADR-003c's predictor field):** construct
    a second `TemperatureProvider(hass, weather_entity_id, "weather")` —
    this class is used as-is, no subclassing or new tier needed, since
    the predictor field is always weather-tier by definition (ADR-003c
    §3).
  - **Known scope boundary (same class of limitation as TASK-0003's
    `BaselineProvider`, flagged for TASK-0010):** the `"sensor"` tier's
    `fetch()` has no genuine historical archive to query yet (a plain
    `sensor.*` entity's *own* recorder state history would be the
    correct source once TASK-0010 wires up recorder access — this task's
    footprint was scoped to `providers/temperature.py` + tests only, no
    recorder import). Today it repeats the current live reading across
    the whole requested range — correct for a first-ever validation pass
    or in tests, a placeholder for genuine backfill otherwise. Same
    caveat applies to the weather tier's "training-set case" fallback
    value.
- `tests/test_providers_temperature.py` → 12 tests (4 test classes)
  against a real (non-Mock) `FakeHomeAssistant`/`FakeState`/`FakeStates`
  fixture (same shape as TASK-0003's, duplicated per that task's own
  note rather than shared via cross-test-file import), covering all 5
  acceptance criteria: sensor-tier fetch = own reading, no
  discovery/scoring (AC1); weather-tier fetch uses `forecast` for
  matching slots (AC2); sensor-tier `forward()` is `None` (AC3);
  weather-tier `forward()` is genuinely forward-looking and filtered to
  `now` (AC4); `identify()` returns exactly the selected entity on both
  tiers (AC5).
- External dependencies added: none — pure stdlib plus the existing
  `providers.base` helpers (`EntityRef`, `Provider`, `assemble_series`,
  `map_state_value`).
- Gates: `ruff check` passes with zero errors. `mypy --config-file
  mypy.ini` passes with zero issues (21 source files total). `pytest` —
  full suite 84 tests, all pass (72 prior + 12 new). **`ruff format`
  note:** same sandbox tool bug as TASK-0003 (`ruff format` 0.16.4
  corrupts `except (TypeError, ValueError):` into invalid syntax) hits
  one line in this file too; left in valid, standard form — confirmed
  via `ruff format --check --diff` that this is the *only* remaining
  diff for both new files.
