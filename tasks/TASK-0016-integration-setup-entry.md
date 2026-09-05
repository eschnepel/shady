# Task: Integration Setup Entry — Wiring & Startup-Ordering Guard

- **Status:** todo
- **Related ADRs:** [ADR-002 §1a, ADR-002 §5]
- **Dependencies:** [TASK-0010-coordinator-recalibration-recompute-push, TASK-0011-forecast-sensor-and-recalculate-button, TASK-0012-aggregate-sensors, TASK-0013-intraday-deviation-correction, TASK-0014-temperature-forecast-learned-model, TASK-0015b-diagnostics-select-and-scatter-sensors]

## Goal
Implement `custom_components/shady/__init__.py`'s `async_setup_entry`/
`async_unload_entry`: construct the coordinator, store it in
`hass.data`, forward this config entry's platforms (`sensor`, `select`,
`button` — `select` replacing `switch` as of ADR-004's 2026-08-30
amendment), register the `shady.select_diagnostic_slot` service
(ADR-002 §5's `__init__.py` bullet), and — the reason this task exists
— guard against Home Assistant's own boot-ordering race (ADR-002 §1a):
a config entry's referenced entities may not exist yet if the
integration(s) that provide them haven't finished loading. This task
was **not** part of the original Phase 2 task set — discovered as a gap
(no task existed for `__init__.py` at all) while gathering TASK-0010's
Consumed Interfaces, alongside the ADR-002 §1a amendment itself. See
`tasks/INDEX.md`'s refinement log for the full context.

## Acceptance Criteria
- Given `hass.is_running` is already `True` (config-entry reload, or
  Home Assistant already fully started) and one or more of the config
  entry's required entities (per-string actual-yield; per-string
  resolved baseline, if configured) does not exist in `hass.states`,
  When `async_setup_entry` runs, Then it raises
  `homeassistant.exceptions.ConfigEntryNotReady` and does **not**
  construct the coordinator or forward any platform (ADR-002 §1a).
- Given `hass.is_running` is already `True` and every required entity
  exists, When `async_setup_entry` runs, Then it constructs the
  coordinator, stores it in `hass.data[DOMAIN][entry.entry_id]`,
  forwards `sensor`/`select`/`button` platform setup, and runs the
  coordinator's startup fit (ADR-002 §1) — all before returning.
- Given `hass.is_running` is `False` (Home Assistant still starting),
  When `async_setup_entry` runs — regardless of whether the config
  entry's required entities currently exist — Then it still constructs
  the coordinator, stores it in `hass.data`, and forwards platform
  setup immediately (Shady's own entities register on the normal
  schedule), but defers the coordinator's startup fit via
  `homeassistant.helpers.start.async_at_started(hass, ...)` rather than
  running it inline, and does **not** raise `ConfigEntryNotReady`
  (ADR-002 §1a).
- Given the deferred `async_at_started` callback from the previous
  criterion fires and `missing_required_entities()` is still non-empty
  at that point, When the callback runs, Then it logs a warning and
  calls `hass.config_entries.async_schedule_reload(entry.entry_id)`
  after a short delay, rather than retrying the fit itself or inventing
  a second backoff mechanism (ADR-002 §1a).
- Given the deferred callback's re-check finds every required entity
  now present, When it runs, Then it runs the coordinator's startup fit
  exactly as the immediate path would have.
- Given `async_unload_entry`, When a config entry is unloaded/reloaded,
  Then all coordinator-registered listeners/schedules are cancelled and
  the entry's `hass.data` slot is removed, leaving no dangling
  `async_track_time_change`/state-change subscriptions behind.
- Given the `shady.select_diagnostic_slot` service, When
  `async_setup_entry` registers it, Then registration happens exactly
  once per Home Assistant instance (not once per config entry) — a
  second config entry setting up must not raise on re-registration or
  register a duplicate service.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/__init__.py`
- `tests/test_init.py` (real `hass`-stub fixture, mirroring
  `tests/test_config_flow.py`'s `homeassistant` stub convention —
  ADR-002 §1a's behavior hinges on `hass.is_running`/
  `ConfigEntryNotReady`/`async_at_started`/`async_schedule_reload`, all
  of which need real stand-ins, not mocks, to exercise meaningfully)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0010/0011/0012/0013/0014/0015 once
     each is `done`. Placeholder shape recorded now so this task's
     scope is unambiguous even though it cannot start until every
     dependency above is `done`. -->
- `coordinator.<Coordinator class>` — constructor, `missing_required_entities()`,
  the startup-fit entry point, and a shutdown/cleanup method — from
  `custom_components/shady/coordinator.py` (→ task: TASK-0010)
- Whatever `sensor.py`/`select.py`/`button.py` each need `__init__.py`
  to pass through `hass.data` (→ tasks: TASK-0011, TASK-0012, TASK-0013,
  TASK-0014, TASK-0015b-diagnostics-select-and-scatter-sensors)
- `coordinator.ShadyCoordinator.pin_diagnostic_slot(timestamp: datetime, now: datetime | None = None) -> bool`
  and `.clear_diagnostic_slot() -> None` — the two methods the
  `shady.select_diagnostic_slot` service handler this task registers
  must call (accept/reject semantics and the 5-minute-boundary rounding
  are `pin_diagnostic_slot`'s own responsibility, already implemented
  and tested; the service handler itself is purely a thin
  `hass.services.async_register` wrapper around them) — from
  `custom_components/shady/coordinator.py` (→ task:
  TASK-0015b-diagnostics-select-and-scatter-sensors, 2026-09-04
  scope-correction note)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
