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
- `custom_components/shady/providers/temperature.py` → class `ShadyTemperatureProvider`, type alias `TemperatureTier`
