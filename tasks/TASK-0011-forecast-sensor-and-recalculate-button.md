# Task: Corrected Forecast Sensor & Manual Recalculation

- **Status:** todo
- **Related ADRs:** [ADR-002 §3, ADR-002 §5, ADR-000 §3]
- **Dependencies:** [TASK-0010-coordinator-recalibration-recompute-push]

## Goal
Implement `sensor.py`'s `ShadyForecastSensor` (per string, today+
tomorrow horizon, reads coordinator state — stays thin, no business
logic), `button.py`'s `ShadyRecalculateButton` (calls the coordinator's
refit method, logs/swallows exceptions per ADR-000 §8), and complete
`__init__.py`'s wiring (`async_setup_entry`/`async_unload_entry`,
`PLATFORMS`) to actually instantiate `ShadyCoordinator` and store it in
`hass.data` (replacing the current skeleton's TODOs). **This is the
first fully end-to-end demonstrable capability** — a config entry can be
set up and produce a real corrected-forecast sensor.

This task does **not** depend on TASK-0009 (config flow) — `__init__.py`
reads `entry.data` by the field names ADR-010 already fixes, without
importing anything from `config_flow.py`.

## Acceptance Criteria
- Given a config entry with one configured string, seeded fake recorder/
  provider data, When `async_setup_entry` runs, Then `ShadyCoordinator` is
  instantiated, stored in `hass.data[DOMAIN][entry.entry_id]`, and
  `ShadyForecastSensor` exposes a plausible corrected value for that
  string.
- Given `ShadyRecalculateButton.async_press()` is called, When pressed,
  Then it triggers the exact same refit code path as the midnight
  schedule (TASK-0010), and any exception during refit is logged and
  swallowed, not raised (ADR-000 §8).
- Given `async_unload_entry` is called, When unloaded, Then platforms are
  unloaded and the entry's coordinator is removed from `hass.data`.
- Given the sensor's state and attributes, When inspected, Then
  `ShadyForecastSensor` contains no computation of its own — every value
  is read directly from what `coordinator.py` last pushed (thin-glue
  principle, ADR-000 §3).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/sensor.py` (new: `ShadyForecastSensor`)
- `custom_components/shady/button.py` (new: `ShadyRecalculateButton`)
- `custom_components/shady/__init__.py` (modified — replaces existing
  skeleton TODOs)
- `tests/test_sensor_forecast.py`, `tests/test_button.py`,
  `tests/test_init.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0010. -->
- `coordinator.ShadyCoordinator` (incl. its public refit method) from `custom_components/shady/coordinator.py` (→ task: TASK-0010-coordinator-recalibration-recompute-push)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
