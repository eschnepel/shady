# Task: Coordinator — Recalibration, Recompute & Provider Push

- **Status:** done
- **Related ADRs:** [ADR-002 §1, ADR-002 §1a, ADR-002 §2, ADR-002 §3, ADR-002 §4, ADR-002 §5, ADR-012 §4]
- **Dependencies:** [TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor, TASK-0005-regression-fitting-pipeline, TASK-0007-yield-corrections, TASK-0008-forecast-adjustment, TASK-0003-baseline-forecast-discovery, TASK-0004-temperature-source-provider, TASK-0009-patch-1-manual-baseline-shape]

## Goal
Implement `coordinator.py`'s pure orchestration core: the daily
recalibration schedule (midnight+1min) and button-triggered recalibration
(exposing a single public refit method both call), the up-to-yesterday
training cutoff, the startup safety net, baseline-update-triggered
forecast recompute (today-remaining + tomorrow horizon, no debounce), and
the **one generic provider-push loop** — for every provider instance
whose `forward()` is overridden, register a listener that calls
`forward(now)`, converts to the cache's index scheme, and pushes with the
correct `not_before_index` guard. Also exposes `missing_required_entities()`
and the startup-fit entry point `__init__.py`/TASK-0016 needs to call
(immediately, or via its deferred `async_at_started` path) per ADR-002
§1a — this task does **not** itself implement `async_setup_entry`,
`ConfigEntryNotReady`, or the `async_at_started`/`async_schedule_reload`
wiring; that is TASK-0016's job, layered on top of what this task
exposes.

## Acceptance Criteria
- Given a manual button press and the scheduled midnight trigger, When
  either fires, Then both call the exact same refit code path, using
  only recorder data up to and including yesterday (ADR-002 §1).
- Given a config entry with no model fitted yet (or a last fit >24h old),
  When the coordinator's startup-fit entry point is called (by
  `__init__.py`, per ADR-002 §1a — immediately if Home Assistant is
  already running, or once it reports started otherwise), Then a fit
  runs immediately, in addition to the daily schedule (ADR-002 §1's
  safety net).
- Given a config entry's per-string actual-yield entity or resolved
  baseline entity does not currently exist in `hass.states`, When
  `missing_required_entities()` is called, Then it returns those
  entity IDs (and only those — never optional correction-tier entities,
  ADR-002 §1a).
- Given a baseline-provider update fires mid-day, When it fires, Then a
  forecast recompute happens immediately with no debounce, but no
  recalibration is triggered by this alone (ADR-002 §1/§2).
- Given a recompute, When it runs, Then it produces adjusted values only
  for the remainder of today plus tomorrow (if published), and never
  recomputes already-past slots (ADR-002 §3).
- Given a `ShadyForecastSensor`-shaped output value is computed for a
  slot, When it is first computed, Then it is immediately pushed into
  `cache.py` with `to_index=None` semantics (ADR-002 §3).
- Given both the baseline provider and the temperature provider override
  `forward()`, When a config entry sets up, Then exactly one generic
  coordinator listener is registered per such provider instance — no
  provider-specific listener code exists in `coordinator.py` (ADR-012
  §4).
- Given a provider's `forward()` returns a series, When the listener
  fires, Then `push(sensor_id, dict[index, value])` is called with
  `not_before_index` set to "the next upcoming slot after now" (ADR-012
  §4 / ADR-002 §4).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/coordinator.py`
- `tests/test_coordinator.py` (real `hass` fixture, fake time advancement)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0002, TASK-0006, TASK-0005, TASK-0007,
     TASK-0008, TASK-0003, TASK-0004, TASK-0009-patch-1. -->
- `cache.Cache` — `__init__(window_days, fetch_fn)`, `push(sensor_id, values: dict[int, float], not_before_index: int)`, `get_time_range(sensor_ids, start, end, *, on_invalid=...)`, `get_regression_pools(sensor_ids, smoothing_radius, *, reference)`, `validated_range(sensor_id)`, static `index_for(timestamp)`/`timestamp_for(index)` — from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor). `SLOT_DURATION`/`SLOTS_PER_DAY` module constants also consumed.
- `regression.base.FittedModel` (ABC, `.coefficients`, `.predict`/`.predict_unclamped`), `regression.base.build_pool(fc_by_offset, pv_by_offset, smoothing_radius, neighbor_fitting_cutoff) -> SamplePool`, and each of `regression.linear/kernel/wls2/wls3`'s module-level `fit(pool) -> FittedModel` — from `custom_components/shady/regression/` (→ task: TASK-0005-regression-fitting-pipeline)
- `yield_correction.exclude_clipped(actual, inverter_limit, clipping_threshold)`, `yield_correction.derate_actual_to_reference(actual, cell_temperature, coefficient_per_c, *, provider_already_corrects)`, `yield_correction.uplift_ambient_to_cell(ambient_temperature, baseline_forecast, baseline_rated_capacity, max_uplift_c)` — from `custom_components/shady/yield_correction.py` (→ task: TASK-0007-yield-corrections)
- `forecast_adjust.adjust_forecast(model, fc, target_cell_temperature, coefficient_per_c, inverter_limit, *, provider_already_corrects) -> (adjusted, confidence)` — from `custom_components/shady/forecast_adjust.py` (→ task: TASK-0008-forecast-adjustment)
- `providers.base.Provider` (ABC — `identify`/`fetch`/`forward`, `forward` defaulting to `None`) — from `custom_components/shady/providers/base.py` (→ task: TASK-0003-baseline-forecast-discovery)
- `providers.discovery.BaselineProvider(hass, entity_id, attribute, shape)` — `.fetch(start,end)`, `.forward(now)` — from `custom_components/shady/providers/discovery.py` (→ task: TASK-0003-baseline-forecast-discovery)
- `providers.temperature.TemperatureProvider(hass, entity_id, tier)` — `.fetch(start,end)`, `.forward(now)` — from `custom_components/shady/providers/temperature.py` (→ task: TASK-0004-temperature-source-provider)
- `const.py`'s full `CONF_*`/`DEFAULT_*` set (TASK-0009) plus the manual-shape addition (TASK-0009-patch-1) — from `custom_components/shady/const.py`

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/coordinator.py` → `class ShadyCoordinator`:
  - Construction: `__init__(hass, entry)` — resolves all config
    statically (no `hass.states` access), constructs `BaselineProvider`/
    `TemperatureProvider` instances, registers the midnight schedule and
    one state-change listener per `forward()`-overriding provider, all
    synchronously (safe to call before Home Assistant reports started —
    ADR-002 §1a).
  - `missing_required_entities() -> list[str]` and `async def
    async_startup(now: datetime | None = None) -> None` — TASK-0016's
    two Consumed Interfaces for the startup-ordering guard (ADR-002
    §1a).
  - `async def async_refit(now: datetime | None = None) -> None` — the
    one refit routine; `button.py` (TASK-0011) calls this directly.
  - `def shutdown() -> None` — cancels every registered listener/
    schedule; TASK-0016's `async_unload_entry` Consumed Interface.
  - `def forecast_sensor_id(string_index: int) -> str` — TASK-0011's
    Consumed Interface: the exact cache `sensor_id` a `ShadyForecastSensor`
    for string `string_index` must read via `cache.get_time_range`.
  - `self.cache: Cache` — exposed directly; TASK-0011/TASK-0012/
    TASK-0013/TASK-0015's sensors read through it.
  - Private (not a Consumed Interface for any other task, listed for
    completeness): `_StringConfig`, `_fetch_fn`,
    `_fetch_actual_yield_statistics`, `_fit_string`,
    `_apply_training_corrections`, `_recompute_string`, `_predict_day`
    (renamed `_predict_day_basis` by `TASK-0013`, which also split its
    former final-clamp step into a sibling `_clamp_basis` — see the
    scope-decision note below),
    `_push_provider_series`, `_make_listener`, `_now` (injectable
    clock — a plain callable attribute, not part of any public
    contract).
- `tests/test_coordinator.py` → 12 tests across 8 test classes, one per
  acceptance criterion (`TestRefitSharedCodePath` covers the first with
  2 tests). Hand-written `homeassistant` stub extending TASK-0009's
  convention with `homeassistant.helpers.event`
  (`async_track_time_change`/`async_track_state_change_event`) and
  `homeassistant.components.recorder.statistics.statistics_during_period`
  — all real (non-`Mock`) stand-ins. `FakeHomeAssistant.async_create_task`
  schedules a real `asyncio.Task`; `FakeHomeAssistant.drain()` lets
  scheduled tasks (recompute, midnight-triggered refit) actually
  complete before assertions — a real, deterministic substitute for
  pumping HA's own event loop, not a mock.
- **Scope decision, this task (module docstring, ADR-003b §1):**
  temperature derating is fully implemented for the weather-integration
  tier only. The module/cell and ambient-sensor tiers structurally
  require ADR-003c's learned per-slot temperature-forecast model, which
  does not exist yet (`TASK-0014`, still `todo`) — a string resolving
  to a `sensor.*` temperature source is left with derating skipped
  entirely for now, exactly matching ADR-003b §1's own stated
  dependency chain. `TASK-0014`'s own job is to extend
  `_resolve_weather_temperature_entity`/`_apply_training_corrections`/
  `_predict_day` (renamed `_predict_day_basis` by `TASK-0013`, which
  also split the old function's final-clamp step out into a sibling
  `_clamp_basis` — same extension point, corrected name; not a
  Scenario C patch, since this was never a formal Consumed Interface,
  as this section's own opening line already says) to cover that tier
  once its learned-model machinery exists — flagged here as a known
  extension point, not a task-graph gap requiring a new task right now
  (`TASK-0014` already covers it).
- **Scope decision, this task:** `_last_fit_at` (ADR-002 §1's ">24h
  old" branch) is in-memory only, not persisted across Home Assistant
  restarts. Every restart already implies "no model fitted yet" in a
  fresh coordinator instance, which alone satisfies the startup safety
  net on every restart regardless of this timestamp — the acceptance
  criterion's own two conditions ("no model fitted yet" OR "last fit
  >24h old") are honored either way; only the specific cross-restart
  staleness scenario ADR-002 §1's own parenthetical example describes
  ("Home Assistant was offline through a scheduled midnight run") isn't
  distinguished from a fresh in-memory startup fit — which happens
  regardless in that scenario too. Cross-restart persistence (e.g. via
  `entry.data`) is a defensible future refinement, not implemented here
  since no acceptance criterion exercises it and it was not part of any
  ADR's explicit mechanism.
- No external dependencies added (numpy already present, TASK-0005).
- Gates: `ruff check`/`ruff format --check` clean on
  `coordinator.py`/`test_coordinator.py`. `mypy --config-file mypy.ini`
  clean, 30 source files. Suppressions per ADR-000 §2's exact-line
  convention: `@callback  # type: ignore[untyped-decorator]` (×2, on
  `_handle_midnight` and `_make_listener`'s inner `_handle`) and `return
  _handle  # type: ignore[no-any-return]` (the untyped `@callback`
  decorator collapses the wrapped function's inferred type to `Any`).
  `pytest`: full suite 150/150 (138 pre-existing + 12 new).
