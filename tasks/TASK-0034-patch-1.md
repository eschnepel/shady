# Task: Self-Heal a Frozen `history_entity_id` (Startup Retry, Not Just Discovery-Time)

- **Status:** done
- **Related ADRs:** \[ADR-009 §1c-further-Amendment, ADR-012 §1/§2a (unchanged,
  referenced), ADR-002 §1a (unchanged, referenced — the readiness gate this
  retry point piggybacks on), ADR-000 §8 (unchanged, referenced — graceful
  degradation, never an error)\]
- **Dependencies:** [TASK-0034-baseline-recorder-backed-history]

## Goal

Real-world bug report, same session as `TASK-0034`: a user saw
`Startup backfill for string 0 (...): baseline provider <forecast_solar config_entry_id> has no historical data for <today>`
despite the companion `sensor.power_production_now` genuinely having recorder
history. Root cause — **not** a race at backfill time, and **not** the
resolution-mechanism bug `TASK-0034` itself already fixed (composed `unique_id`
→ `translation_key`). It is a *different* race: `history_entity_id` is resolved
exactly once, at config/options-flow submission time (`config_flow.py`), and
that result is persisted into config entry data and simply re-read verbatim by
`coordinator.py`'s `__init__` (ADR-002 §1a: construction never touches `hass`)
on every restart since. If Forecast.Solar's companion sensor wasn't yet
registered at that one past moment, the persisted `None` is what every future
restart inherits — forever, regardless of the sensor existing, with plenty of
history, by the time any later restart runs. This task gives that one-time
resolution a startup-time retry with self-healing persistence, mirroring the
"awaited, non-racy retry" pattern `_refresh_forecast_solar_providers` already
established for the *forward* forecast side of this same integration.

## Acceptance Criteria

- Given a `forecast_solar`-shaped provider whose persisted `history_entity_id`
  is `None`, when `async_startup` runs and
  `resolve_forecast_solar_history_entity` now succeeds (the companion sensor is
  registered by this point), then the live `BaselineProvider`'s
  `history_entity_id()` reflects the resolved value for the remainder of this
  run — in particular, before `_backfill_elapsed_today_slots` runs in the same
  `async_startup` call, so a same-session recovery already unblocks that same
  run's own backfill.
- Given the same successful retry, when it completes, then the resolved value is
  persisted back into this config entry's own stored data (global
  `baseline_history_entity_id` or the specific string's override — whichever
  field(s) actually referenced this config entry, and only if that field was
  previously unset) via exactly one `hass.config_entries.async_update_entry`
  call covering every provider resolved that pass, not one call per provider.
- Given a `forecast_solar`-shaped provider whose `history_entity_id()` is
  already resolved (non-`None`), when `async_startup` runs, then no entity
  registry lookup is performed for it at all (no wasted rescan) and no
  `async_update_entry` call is made on its account.
- Given a `forecast_solar`-shaped provider whose companion sensor is *still* not
  registered, when the retry runs, then nothing raises, nothing is persisted,
  and the provider is left exactly as constructed — to be retried again next
  restart (ADR-000 §8: never an error).
- Given a non-`forecast_solar` provider (every other baseline shape), when the
  retry runs, then it is silently skipped — no `AttributeError`, no lookup, no
  write.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/providers/discovery.py` — promote
  `_resolve_forecast_solar_history_entity` to public
  `resolve_forecast_solar_history_entity`; add
  `BaselineProvider. set_history_entity_id`.
- `custom_components/shady/coordinator.py` — new
  `_resolve_stale_forecast_solar_history_entities` method; one new call site in
  `async_startup`, before `_backfill_elapsed_today_slots`.
- `tests/support_ha.py` — `FakeConfigEntries.async_update_entry`.
- `tests/test_coordinator.py`, `tests/test_providers_discovery.py` — new tests.

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected — `hass.config_entries`/`homeassistant.helpers.entity_registry` are
  core Home Assistant, already relied on elsewhere in this project)

## Consumed Interfaces

- `providers/discovery.py`'s `BaselineProvider` (constructor, `shape`,
  `history_entity_id()`) — from `TASK-0034-baseline-recorder-backed-history`'s
  Delivered Artifacts.
- `providers/discovery.py`'s (then-private)
  `_resolve_forecast_solar_history_entity(hass, config_entry_id) -> str | None`
  — from `TASK-0034-baseline-recorder-backed-history`'s Delivered Artifacts;
  promoted to public as part of this task's own Delivered Artifacts (see below)
  since it gained a second, legitimate caller.
- `coordinator.py`'s existing `_entity_providers: dict[str, Provider]`,
  `self.entry` (the `ConfigEntry`), and `async_startup`/
  `_backfill_elapsed_today_slots` ordering — all pre-existing, `coordinator.py`
  is a Worker-and-Reviewer-inline task with full-file context, not a minimal
  cross-task interface handoff.

## Delivered Artifacts

- `custom_components/shady/providers/discovery.py`:
  - `_resolve_forecast_solar_history_entity` renamed to public
    `resolve_forecast_solar_history_entity(hass, config_entry_id: str) -> str | None`
    — same signature and behavior, now importable from outside this module.
  - `BaselineProvider.set_history_entity_id(self, history_entity_id: str) -> None`
    — new setter; the one post-construction mutation this field ever undergoes,
    `None` → resolved only in practice (the caller's own guard, not this method,
    enforces that direction).
- `custom_components/shady/coordinator.py`:
  - `ShadyCoordinator._resolve_stale_forecast_solar_history_entities(self) -> None`
    — new method; iterates `_entity_providers`, retries
    `resolve_forecast_solar_history_entity` for every `forecast_solar`-shaped
    provider whose `history_entity_id()` is still `None`, applies successes
    in-memory (`provider.set_history_entity_id`) and persists them via a single
    `hass.config_entries.async_update_entry(self.entry, data=new_data)` call
    covering both the global `CONF_BASELINE_HISTORY_ENTITY_ID` field and any
    per-string `CONF_STRING_BASELINE_HISTORY_ENTITY_ID` override that referenced
    the same config entry and was itself still unset.
  - New import: `resolve_forecast_solar_history_entity` added to the existing
    `from .providers.discovery import BaselineProvider, ...` line.
  - `ShadyCoordinator.async_startup` — one new call,
    `self._resolve_stale_forecast_solar_history_entities()`, immediately before
    the existing `self._backfill_elapsed_today_slots(resolved_now)` call.
- `tests/support_ha.py`:
  - `FakeConfigEntries.async_update_entry(self, entry, *, data=None) -> bool` —
    new; mutates `entry.data` in place and records `(entry, data)` in a new
    `self.update_calls` list for test assertions. No update-listener dispatch
    (nothing in this project registers one).
- `tests/test_coordinator.py`: new
  `TestResolveStaleForecastSolarHistoryEntities` class (8 tests) —
  global-baseline resolve+persist, per-string-override resolve+persist,
  still-unresolved leaves everything untouched, an already-resolved provider is
  never re-scanned, a non-`forecast_solar` provider is a silent no-op, one
  `async_update_entry` call covers two simultaneously-resolved providers, and an
  end-to-end `async_startup`-level test proving a same-session self-heal already
  unblocks that same run's own backfill (the exact real-world race report this
  task fixes).
- `tests/test_providers_discovery.py`: two new tests on the existing
  `TestBaselineProviderHistoryEntityId` class — `set_history_entity_id` updates
  a `None` default, and can also replace an already-resolved value (the setter
  itself has no direction restriction; the caller's guard is what prevents
  redundant re-resolution in practice).
- External dependencies added: none — see `tasks/DEPENDENCIES.md` (unchanged).

**Verification (fresh, full run):** `pytest` — 569 passed (560 baseline + 9 new:
7 in `test_coordinator.py`, 2 in `test_providers_discovery.py`);
`mypy --config-file mypy.ini custom_components/ tests/` — clean, 58 files;
`ruff check .` — clean (4 line-length violations in the new tests, fixed via
`ruff format`); `ruff format --check .` — clean, 174 files; `mdformat --check` —
clean on every edited `.md` file.
