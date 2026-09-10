# Task: Entity-Layer Cache-Access Boundary — Decision & Fix

- **Status:** done
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
- **Option chosen:** Neither A nor B as originally drafted. The human's
  recorded `## Decision` ("coordinator.cache should be a readonly
  accessor... a wrong implementation within a sensor should not harm
  the cache variable") describes a third path this task's own
  Acceptance Criteria weren't written for. The Lead Agent found the
  enforcement-strictness question itself ambiguous (a runtime-
  restricted wrapper object exposing only read methods? a type-checker-
  only `Protocol`? attribute-level read-only?) and asked; the human
  clarified directly: "the local cache variable in coordinator should
  be readonly. like a getter without a setter" — resolving it to
  attribute-level read-only, the narrowest and lowest-risk of the three
  candidates. The three sensor classes `AUDIT-0009` flagged
  (`ShadyForecastSensor`, `ShadyPvEnergyIntegralSensor`,
  `ShadyFcEnergyIntegralSensor`) are **unaffected** by this decision —
  they still call `coordinator.cache.<method>(...)` directly, exactly
  as `TASK-0011` originally reviewed and authorized; this task does not
  reopen that call. Verified before implementing: repo-wide
  `grep -rn ".cache\s*=\s*[^=]"` across `custom_components/shady/*.py`
  and `tests/*.py` found exactly one assignment to `coordinator.cache`
  anywhere in the codebase — the one in `__init__` itself — so
  converting it to a getter-only property was safe with zero call-site
  breakage anywhere else.
- `custom_components/shady/coordinator.py` → `__init__` now sets
  `self._cache = Cache(...)` (private backing field) instead of
  `self.cache = Cache(...)`. New `cache` property (getter only, no
  setter) added immediately after `__init__` returns `self._cache`.
  `coordinator.cache = anything` now raises `AttributeError` from any
  call site, anywhere; `coordinator.cache.<any method>(...)` — reads
  and writes alike — is completely unaffected, since the property
  returns the same real `Cache` instance every time, not a restricted
  wrapper. Every one of `coordinator.py`'s own internal `self.cache.
  <method>(...)` call sites (read and write) continues to work
  unchanged, since `self.cache` still resolves through the new property
  to the same object as before.
- `adr/000-coding-standards.md` → new top-of-file `**2026-09-08**`
  pointer bullet; new `## Amendment — 2026-09-08` block (placed after
  the existing 2026-08-22 Amendment block, before `## Context`,
  matching this file's own established amendment-placement convention
  — not the end-of-file placement used for ADR-007/007a/009, which
  don't have a pre-established convention of their own) recording the
  `AUDIT-0009` finding, the decision, and the exact clarification
  exchange. §3's `coordinator.py` bullet updated to mention the
  read-only property; §3's `entity_glue` bullet updated to name the
  three reviewed-exception sensor classes explicitly (the "Option A"-
  style documentation half of closing this gap, folded into the same
  edit) and note that the module diagram's `entity_glue --> coordinator`
  edge needed no change, since `sensor.py` still never *imports*
  `cache.py` — only reaches a `Cache` instance through an already-
  in-scope `coordinator` reference, at the attribute/method level, not
  the module level.
- `tasks/adr-summary.md` → §2's `cache.py`/`coordinator.py` bullets
  updated to match: the `coordinator.py` bullet now mentions the
  read-only `cache` property and names the three reviewed-exception
  sensor classes. Also caught and fixed a **separate, pre-existing
  stale claim** in the same `cache.py` bullet — "simple dict stores
  (model cache, ramp state)" — left over from `TASK-0021`'s relocation
  work (that task's own edit to this file only touched §5's dedicated
  `cache.py`-design section, missing this earlier, shorter mention in
  §2's module-boundaries overview); corrected to describe the actual
  `get_model`/`set_model`/`invalidate_models` shape.
- `tests/test_coordinator.py` → new `import pytest` (not previously
  imported in this file); new `TestCacheAttributeIsReadOnly` class, two
  tests: `test_assignment_raises_attribute_error` (`coordinator.cache =
  object()` raises `AttributeError` via `pytest.raises`) and
  `test_reading_and_calling_methods_on_it_still_works` (a plain read
  plus a real `get_model` call on the returned object, proving the
  property blocks only reassignment, not read access or the cache's own
  API).
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged.
- `git status --short` confirms exactly the four files above changed.
  Full test suite: 443 → 445/445 passed (2 new, zero deleted). `mypy
  --config-file mypy.ini custom_components/ tests/` clean on 53 source
  files. `ruff check .` clean repo-wide. `ruff format --check .` shows
  only the one pre-existing, unrelated, already-documented drift file,
  untouched — identical to every prior task's baseline in this batch.
