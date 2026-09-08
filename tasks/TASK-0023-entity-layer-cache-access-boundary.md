# Task: Entity-Layer Cache-Access Boundary — Decision & Fix

- **Status:** todo
- **Related ADRs:** [ADR-000, ADR-002]
- **Dependencies:** [TASK-0011-forecast-sensor-and-recalculate-button, TASK-0012-aggregate-sensors]

## Goal
`AUDIT-0009-entity-layer` found a PARTIAL: three of `sensor.py`'s nine
entity classes (`ShadyForecastSensor`, `ShadyPvEnergyIntegralSensor`,
`ShadyFcEnergyIntegralSensor`) call `self._coordinator.cache.<method>(...)`
directly, reaching two hops past "coordinator" into `cache.py`'s own
public API — while the other six/seven sensor classes go through a
dedicated `coordinator.py` wrapper method (`pv_sum()`, `fc_sum()`, etc.)
that itself wraps the equivalent cache read. This was an explicit,
task-time-reviewed decision — `TASK-0011`'s own `Consumed Interfaces`
block authorizes `self.cache: Cache — exposed directly` — not an
unreviewed oversight. But it is not reflected in ADR-000 §3's module
diagram (`entity_glue --> coordinator` only, no `entity_glue --> cache`
edge) or its "`coordinator.py` [is] the only module that imports
`cache.py`" text, and it's internally inconsistent with `sensor.py`'s
own predominant convention within the same file.

## Known Decisions
- The behavior is correct today — this is a module-boundary
  consistency/documentation question, not a bug. `AUDIT-0009` found no
  incorrect sensor value anywhere in this layer.
- This is the same class of "reviewed exception vs. undocumented
  drift" question `TASK-0021`/`TASK-0022` raise for their own modules —
  if the human's answer to any of the three tends toward "tighten the
  boundary, don't just document the exception," consider handling all
  three with the same philosophy for consistency across the codebase
  (not a hard requirement, just worth asking about together).

## Open Questions for Execution
**This task cannot start implementation until the human picks one of
the following two paths.**

- **Option A — Amend ADR-000 §3.** Add the reviewed exception to the
  module diagram/text: note that `ShadyForecastSensor`,
  `ShadyPvEnergyIntegralSensor`, and `ShadyFcEnergyIntegralSensor`
  intentionally read `coordinator.cache` directly, with the rationale
  already on record in `TASK-0011`'s Consumed Interfaces (if that
  rationale is thin, the human may want to add a stronger one here).
  No code change.
- **Option B — Add thin coordinator wrapper methods.** Add
  `coordinator.py` methods for the two `cache` calls these three
  classes make today (e.g. `forecast_series(sensor_id, start, end)`
  wrapping `cache.get_time_range`, and an `energy_total(kind)`-style
  wrapper for the two integral sensors' `cache.energy_total(...)` call)
  so all nine sensor classes follow one uniform access pattern — no
  `sensor.py` class touches `cache.py` directly afterward.

## Decision
coordinator.cache should be a readonly accessor. So also a wrong implementation within a sensor should not harm the cache variable.

## Acceptance Criteria
- Given the human's decision recorded in this task's own `Open
  Questions` section, When implementation begins, Then the worker
  proceeds only along the recorded path.
- **Option A only:** Given `adr/000-coding-standards.md` §3, When read
  after this task, Then its module diagram/text documents the three
  reviewed exceptions by name, and `tasks/adr-summary.md` is updated to
  match. No `.py` file changes; full test suite unchanged.
- **Option B only:** Given `custom_components/shady/sensor.py`, When
  read after this task, Then `ShadyForecastSensor`,
  `ShadyPvEnergyIntegralSensor`, and `ShadyFcEnergyIntegralSensor` call
  only `coordinator.py` methods, never `self._coordinator.cache`
  directly (`grep -n "coordinator.cache\|_coordinator\.cache"
  sensor.py` returns nothing); the new `coordinator.py` wrapper
  method(s) are covered by at least one new or updated test in
  `tests/test_coordinator.py`, and the three sensor classes' own
  existing tests in `tests/test_sensor_forecast.py`/
  `tests/test_sensor_aggregates.py` pass unmodified in *assertion*
  (only their setup/mocking may need to target the new wrapper instead
  of the raw cache call).

## Estimated File / Module Footprint (hint, not a commitment)
- **Option A:** `adr/000-coding-standards.md`, `tasks/adr-summary.md`
  — no `.py` file.
- **Option B:** `custom_components/shady/coordinator.py`,
  `custom_components/shady/sensor.py`, `tests/test_coordinator.py`,
  `tests/test_sensor_forecast.py`, `tests/test_sensor_aggregates.py`.

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, stating which
  option was chosen
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/sensor.py` → `ShadyForecastSensor`,
  `ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor` — (→
  task: TASK-0011, TASK-0012) — the three classes in question.
- `custom_components/shady/cache.py` → `get_time_range`,
  `energy_total` (or the equivalent methods these three classes
  currently call — confirm exact names against the live file before
  implementing Option B) — (→ task: TASK-0002, TASK-0006) — the calls
  Option B's new wrapper method(s) must forward to unchanged.
- **Note on possible overlap with `TASK-0021`:** if `TASK-0021` chooses
  Option B (relocating the model cache), `coordinator.py`'s own shape
  will already be in flux from that task. If both `TASK-0021` and this
  task land Option B, sequence this task **after** `TASK-0021` closes,
  and re-pull `coordinator.py`'s Delivered Artifacts before starting,
  to avoid two workers independently editing the same file's cache-
  access surface in parallel.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
