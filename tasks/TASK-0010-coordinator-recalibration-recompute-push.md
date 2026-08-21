# Task: Coordinator — Recalibration, Recompute & Provider Push

- **Status:** done
- **Related ADRs:** [ADR-002 §1, ADR-002 §2, ADR-002 §3, ADR-002 §4, ADR-002 §5, ADR-012 §4]
- **Dependencies:** [TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor, TASK-0005-regression-fitting-pipeline, TASK-0007-yield-corrections, TASK-0008-forecast-adjustment, TASK-0003-baseline-forecast-discovery, TASK-0004-temperature-source-provider]

## Goal
Implement `coordinator.py`'s pure orchestration core: the daily
recalibration schedule (midnight+1min) and button-triggered recalibration
(exposing a single public refit method both call), the up-to-yesterday
training cutoff, the startup safety net, baseline-update-triggered
forecast recompute (today-remaining + tomorrow horizon, no debounce), and
the **one generic provider-push loop** — for every provider instance
whose `forward()` is overridden, register a listener that calls
`forward(now)`, converts to the cache's index scheme, and pushes with the
correct `not_before_index` guard.

## Acceptance Criteria
- Given a manual button press and the scheduled midnight trigger, When
  either fires, Then both call the exact same refit code path, using
  only recorder data up to and including yesterday (ADR-002 §1).
- Given a config entry with no model fitted yet (or a last fit >24h old),
  When `async_setup_entry` runs, Then a fit runs immediately on startup
  in addition to the daily schedule (ADR-002 §1's safety net).
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
     TASK-0008, TASK-0003, TASK-0004. -->
- `cache.<Cache class>` (incl. `get_time_range`, `push`, `invalidate`, `trim`) from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store)
- `cache.<Cache class>.get_regression_pools` from `custom_components/shady/cache.py` (→ task: TASK-0006-cache-batched-regression-pool-accessor)
- `regression.base.<strategy classes>` / `.fit`/`.predict` from `custom_components/shady/regression/` (→ task: TASK-0005-regression-fitting-pipeline)
- `yield_correction.<forward/reverse functions>` from `custom_components/shady/yield_correction.py` (→ task: TASK-0007-yield-corrections)
- `forecast_adjust.<apply function>` from `custom_components/shady/forecast_adjust.py` (→ task: TASK-0008-forecast-adjustment)
- `providers.discovery.<Provider>` / `providers.normalize.<canonical mapping>` from `custom_components/shady/providers/` (→ task: TASK-0003-baseline-forecast-discovery)
- `providers.temperature.<Provider>` from `custom_components/shady/providers/temperature.py` (→ task: TASK-0004-temperature-source-provider)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/coordinator.py` implements the shared
  orchestration core: startup refit safety net, midnight+1min daily refit
  registration, provider-push listeners for forward-overridden providers,
  push-to-cache slot conversion, and today/tomorrow recompute filtering.
- `tests/test_coordinator.py` verifies listener registration, provider
  push indexing, recompute triggering, and recompute horizon limits.
