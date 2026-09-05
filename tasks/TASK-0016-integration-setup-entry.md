# Task: Integration Setup Entry — Wiring & Startup-Ordering Guard

- **Status:** done
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
     Delivered Artifacts of TASK-0010/0011/0012/0013/0014/0015b, all
     `done` as of readiness (2026-09-05). -->
- `coordinator.ShadyCoordinator` from `custom_components/shady/coordinator.py`
  (→ task: TASK-0010-coordinator-recalibration-recompute-push):
  - `__init__(hass: HomeAssistant, entry: ConfigEntry) -> None` — safe
    to construct even when referenced entities don't exist yet
    (ADR-002 §1a); registers its own schedules/listeners immediately,
    so a discarded instance must be `shutdown()` before being dropped.
  - `missing_required_entities() -> list[str]` — every required entity
    (per-string actual-yield; per-string resolved baseline, if
    configured) currently absent from `hass.states`.
  - `async def async_startup(now: datetime | None = None) -> None` —
    the startup-fit entry point (ADR-002 §1).
  - `shutdown() -> None` — cancels every registered listener/schedule.
- `coordinator.ShadyCoordinator.async_restore_energy_state() -> None`
  from `custom_components/shady/coordinator.py` (→ task:
  TASK-0012-aggregate-sensors, 2026-08-26 "Known gap" note): restart-
  persistence entry point (ADR-005 §5/§6) — loads any previously-saved
  energy-integral totals from `Store`, applies the startup idempotency
  check, and only then registers the midnight-reset schedule. **Not**
  called from `__init__`/`async_startup` — this task must call it
  directly, exactly once per `async_setup_entry` run that actually
  retains the coordinator (both the immediate and the
  still-Home-Assistant-is-starting paths — it does not depend on
  `missing_required_entities()` being empty, only needs the coordinator
  to exist). Safe to call before platform forwarding.
- `coordinator.ShadyCoordinator.pin_diagnostic_slot(timestamp: datetime, now: datetime | None = None) -> bool`
  and `.clear_diagnostic_slot() -> None` — the two methods the
  `shady.select_diagnostic_slot` service handler this task registers
  must call (accept/reject semantics and the 5-minute-boundary rounding
  are `pin_diagnostic_slot`'s own responsibility, already implemented
  and tested; the service handler itself is purely a thin
  `hass.services.async_register` wrapper around them) — from
  `custom_components/shady/coordinator.py` (→ task:
  TASK-0015b-diagnostics-select-and-scatter-sensors, 2026-09-04
  scope-correction note).
- `sensor.py` / `select.py` / `button.py`'s platform-level
  `async def async_setup_entry(hass, entry, async_add_entities) -> None`
  (→ tasks: TASK-0011-forecast-sensor-and-recalculate-button,
  TASK-0012-aggregate-sensors, TASK-0013-intraday-deviation-correction,
  TASK-0014-temperature-forecast-learned-model,
  TASK-0015b-diagnostics-select-and-scatter-sensors): each reads
  `coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]`
  directly — `hass.data[DOMAIN][entry.entry_id]` must be the
  `ShadyCoordinator` instance itself, not a wrapper dict. `PLATFORMS`
  this task forwards: `["sensor", "select", "button"]` (`select`
  replacing `switch` per ADR-004's 2026-08-30 amendment — there is no
  `switch.py` anywhere in this project).
- `const.DOMAIN` from `custom_components/shady/const.py` (pre-existing,
  not delivered by any task in this dependency list).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/__init__.py` (rewritten from placeholder) →
  - `async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool`
    — implements ADR-002 §1a's full 3-step decision exactly as
    specified: `hass.is_running` True + missing → `ConfigEntryNotReady`,
    coordinator constructed only to run the check then `shutdown()`,
    never stored/forwarded; True + all present → store + forward +
    `async_restore_energy_state()` + `async_startup()`, all before
    returning; False → store + forward + `async_restore_energy_state()`
    unconditionally, startup fit deferred via `async_at_started`.
  - `async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool`
    — `hass.config_entries.async_unload_platforms(entry, PLATFORMS)`,
    then on success pops `hass.data[DOMAIN][entry.entry_id]` and calls
    `coordinator.shutdown()`.
  - `PLATFORMS = ["sensor", "select", "button"]` (module-level list).
  - `SERVICE_SELECT_DIAGNOSTIC_SLOT = "select_diagnostic_slot"`,
    `ATTR_TIMESTAMP = "timestamp"` (module-level constants, single-use
    — ADR-000 §5 — not added to `const.py`).
  - `_register_services(hass: HomeAssistant) -> None` — registers
    `shady.select_diagnostic_slot` idempotently
    (`hass.services.has_service` guard) with a `vol.Schema({vol.Optional
    ("timestamp"): cv.datetime})`. Handler: omitted/`None` timestamp →
    `clear_diagnostic_slot()` on every loaded coordinator; given
    timestamp → `pin_diagnostic_slot(timestamp)` on every loaded
    coordinator, raising `homeassistant.exceptions.ServiceValidationError`
    naming any config entries that rejected it (beyond-horizon) — pins
    that *were* accepted elsewhere are not rolled back.
  - **Design note (not an ADR conflict, recorded per the Golden Rule):**
    neither ADR-004 nor this task's own text specifies what a
    domain-wide service call should do when more than one Shady config
    entry is loaded (no `config_entry_id`/`device_id` targeting
    parameter exists anywhere in the design). This delivery broadcasts
    pin/clear to every loaded coordinator — the only reading that
    requires no additional, undocumented parameter, and the ADR's own
    "calls that config entry's coordinator" phrasing already implicitly
    assumes the common single-entry case. Flagged here rather than
    silently decided; correctable via a Scenario-C patch task if the
    human wants per-entry targeting instead.
  - Gates: `ruff check`/`ruff format --check` clean; `mypy
    --config-file mypy.ini custom_components/ tests/` clean across all
    52 source files — **no new `mypy.ini` per-file suppression needed**
    for `shady` (`__init__.py`'s own module identity under
    `mypy_path = custom_components`); `warn_unused_ignores` stayed at
    its file-level default (`True`) throughout.
- `custom_components/shady/services.yaml` (new) — HA service-picker
  description for `select_diagnostic_slot` (name, description, one
  optional `timestamp` field with a `datetime` selector). Not called
  out in the Estimated Footprint but directly tied to this task's own
  service-registration deliverable; no other task or module reads it.
- `tests/test_init.py` (new) — extends `tests/test_button.py`'s
  hand-written `homeassistant` stub convention with this task's own
  additional surface: `homeassistant.exceptions`
  (`ConfigEntryNotReady`, `ServiceValidationError`),
  `homeassistant.helpers.start.async_at_started`,
  `homeassistant.helpers.config_validation.datetime`, and
  `hass.config_entries`/`hass.services` as real (non-`Mock`) stand-ins
  (`FakeConfigEntries`, `FakeServices`) plus `hass.is_running`/
  `hass._at_started_callbacks`/`async_finish_starting()` on
  `FakeHomeAssistant`. Fully self-contained (own copy of the full
  `homeassistant`/`shady.*` module-loading sequence), independent of
  any other test file's `sys.modules` state — including one internal
  fix required by that independence: monkeypatching this module's own
  `_MISSING_ENTITIES_RELOAD_DELAY_S`/calling `_register_services`
  mid-test must go through this file's own captured `_init_mod`
  reference (bound once, at load time), never a fresh `import shady`,
  since by the time a test *function* runs (as opposed to module
  *collection*, when every test file's top-level loading code has
  already run once each) `sys.modules["shady"]` reflects whichever
  test file loaded last, not necessarily this one.
  - `TestAsyncSetupEntryHassRunning` (3), `TestAsyncSetupEntryHassStarting`
    (3), `TestAsyncUnloadEntry` (2), `TestServiceRegistration` (5) — 13
    tests, covering all 7 acceptance criteria plus the pin/clear/reject
    service paths and two defensive no-op cases (unload of a never-
    loaded entry; service call with zero loaded entries).
- No external dependencies added — `voluptuous` and
  `homeassistant.helpers.config_validation`/`.start`/`.exceptions` were
  already available (`tasks/DEPENDENCIES.md` unchanged; the latter
  three are HA-bundled, same category as `Store`/`UnitOfPower`
  elsewhere in this project, not new packages).
- Full suite: 414/414 (401 pre-task + 13 this task).