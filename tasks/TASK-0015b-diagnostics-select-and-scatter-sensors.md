# Task: Diagnostics — Select Entity & Scatter/Accuracy Sensors

- **Status:** done
- **Related ADRs:** [ADR-004 §1 (Amendment 2026-08-30), ADR-004 §2, ADR-004 §2a, ADR-004 §2b (Amendment 2026-09-03), ADR-004 §3 (Amendment 2026-09-03), ADR-004 §4, ADR-004 §5 (Amendments 2026-08-30, 2026-09-01, 2026-09-02 x2, 2026-09-03), ADR-007a §6, ADR-000 §3/§6 (Amendment 2026-09-01), ADR-013 §1]
- **Dependencies:** [TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor, TASK-0010-coordinator-recalibration-recompute-push, TASK-0011-forecast-sensor-and-recalculate-button, TASK-0013-intraday-deviation-correction, TASK-0015a-diagnostic-mode-base-architecture, TASK-0017-string-computation-module, TASK-0015a-patch-2-diagnostic-mode-coordinator-access, TASK-0015a-patch-3-diagnostic-mode-multi-string-bundling, TASK-0015a-patch-4-diagnostic-mode-sensor-list-output]

## Goal
Implement `cache.py`'s `get_pinned_slot_pool` accessor + cache-wide
`pinned_reference: date | None` scalar (`pin_reference()`/
`clear_reference()`); `select.py`'s `ShadyDiagnosticModeSelect` (default
`"off"`, gates all diagnostic sensors and their extra fitting cost via
`const.py`'s `DIAGNOSTIC_MODES` option list); `diagnostics/
compare_regressions.py`'s `CompareRegressionsMode` (the one concrete
`DiagnosticMode` in scope, built on
TASK-0015a-diagnostic-mode-base-architecture's base class, constructed
with the owning `ShadyCoordinator` per
TASK-0015a-patch-2-diagnostic-mode-coordinator-access); `sensor.py`'s
`ShadyDiagnosticsSensor` — as of the 2026-09-03 ADR-004 amendment, one
generic instance per `(sensor_id, name)` pair
`coordinator.diagnostic_sensor_ids()` declares (one per configured
string plus one `"sum"` id for `CompareRegressionsMode`), not a
dedicated per-entry `ShadyDiagnosticsSumSensor` class; the accuracy pure
function in `aggregation.py` (unchanged home — see ADR-004 §5 Amendment,
kept mode-independent so ADR-013's sketched future modes can reuse it
unmodified); `coordinator.py`'s `_diagnostic_modes` registry (per-
instance, built in `__init__` — ADR-004 §5, 2026-09-01) and dispatch; and
the coordinator-level `pin_diagnostic_slot()`/`clear_diagnostic_slot()`/
`diagnosed_slot()` methods the `shady.select_diagnostic_slot` service
will call once `__init__.py` exists — the HA service *registration*
itself belongs to `TASK-0016-integration-setup-entry` (see this task's
2026-09-04 scope-correction note below), which already names it in its
own Goal.

**This task replaces the original TASK-0015-diagnostics-switch-and-
scatter-sensors**, split per the 2026-08-30 ADR-004 amendment (see
`tasks/INDEX.md`'s refinement log) — same acceptance criteria, same
scope, only the gating entity (`select` instead of `switch`) and the
calculation's home (a `DiagnosticMode` subclass instead of inline logic)
change.

**Additional dependencies added 2026-08-31 (Scenario B + C, see
`tasks/INDEX.md`'s refinement log):** `CompareRegressionsMode.extra_fit()`
needs `string_computation.py` (ADR-014, `TASK-0017` — a prerequisite
discovered while scoping this task's Consumed Interfaces) for its
fit/reverse-transform/clamp computation.

**Dependency superseded 2026-09-01 (Scenario C, see `tasks/INDEX.md`'s
refinement log):** the 2026-08-31 dependency on `TASK-0015a-patch-1-
diagnostic-fit-inputs` (carrying `extra_fit()`'s raw inputs through
`DiagnosticSlotSample.query_fc`/`.fit_inputs`) is replaced by a
dependency on `TASK-0015a-patch-2-diagnostic-mode-coordinator-access`,
which — on further review, before any code existed for either patch —
turned out to remove the receiving end of that mechanism too:
`DiagnosticContext`/`DiagnosticSlotSample` are deleted outright, and
`compute()`/`extra_fit()` take no parameter at all. `CompareRegressionsMode`
now gathers its raw inputs itself, at call time, via the
`ShadyCoordinator` reference it receives at construction
(`self._coordinator.cache.get_pinned_slot_pool(...)`, the resolved
temperature target via the coordinator's own provider access, string
config via `strings()`/whatever public accessor is added) — there is no
`DiagnosticContext` left to receive them through. See ADR-004 §5's second
Amendment for the full rationale.

**Dependency added 2026-09-02 (Scenario C, see `tasks/INDEX.md`'s
refinement log):** `TASK-0015a-patch-3-diagnostic-mode-multi-string-
bundling` is a new prerequisite, discovered while gathering this task's
own Consumed Interfaces. `coordinator.py`'s `_diagnostic_modes` holds one
shared `DiagnosticMode` instance per mode name, but this task needs one
`ShadyDiagnosticsSensor` per configured string, and `compute()`/
`extra_fit()` (both zero-argument since `TASK-0015a-patch-2`) have no way
for a shared instance to know which string a given call is for.
`TASK-0015a-patch-3` resolves this by having a single `compute()`/
`extra_fit()` call bundle every configured string's output at once
(`DiagnosticResult.by_string`/`DiagnosticFitResult.by_string`, keyed by
string index) rather than reintroducing a per-call parameter. See ADR-004
§5's third Amendment (2026-09-02) for the full rationale, including the
accepted per-read recompute-every-string cost trade-off.

**Second dependency added 2026-09-02, same day (Scenario C — see
`tasks/INDEX.md`'s refinement log):**
`TASK-0015a-patch-4-diagnostic-mode-sensor-list-output` supersedes
`TASK-0015a-patch-3`'s string-index-keyed shape immediately, caught while
reviewing that same-day decision against ADR-013's sketched
non-string-scoped modes (`compare_providers_daily` compares providers,
not strings). `DiagnosticResult.by_string`/`DiagnosticFitResult.by_string`
(both keyed by `int` string index) are replaced by a flat,
self-identifying shape: `DiagnosticResult.sensors: Sequence[DiagnosticSensorResult]`
(each entry carrying its own `sensor_id: str`, plus optional `name`/
`unit`/`device_class` hints) and `DiagnosticFitResult.by_sensor: Mapping[str, Mapping[str, float]]`
(keyed by `sensor_id`, not string index). This task's own
`CompareRegressionsMode` still produces one entry per configured string —
it just identifies each one by a `sensor_id` string of its own choosing
(e.g. the string index as text) rather than relying on the container's
key type to encode that. See ADR-004 §5's fourth Amendment (2026-09-02,
second same day) for the full rationale.

**Design correction 2026-09-03 (caught during implementation review,
before this task's own Gate 3/reviewer pass — see `tasks/INDEX.md`'s
refinement log):** two issues found in the still-in-progress code. (1)
Every per-string `ShadyDiagnosticsSensor` was calling `mode.compute()`
directly, on every poll, redoing every configured string's work each
time rather than sharing one call — `coordinator.py` now caches
`compute()`'s output via a new `diagnostic_result()` accessor, refreshed
once per tick through `compute_cadence()` (declared since
`TASK-0015a-patch-2` but never wired to anything until now). (2)
`ShadyDiagnosticsSumSensor` assembled the `"sum"` series in `sensor.py`
itself, from sibling sensors' already-formatted output via `zip()` — a
cross-string day-alignment bug, and also a shape (`sensor.py` hardcoding
"one per string plus one fixed sum") the fourth Amendment's own "the
container doesn't assume a mode's dimension" principle should have
covered but didn't, since it only applied to `DiagnosticResult` itself,
not to `sensor.py`'s entity-creation code. `DiagnosticMode` gains a new
required `sensor_ids()` getter; `ShadyDiagnosticsSumSensor` is removed,
replaced by one generic `ShadyDiagnosticsSensor` per declared
`sensor_id`; `CompareRegressionsMode.compute()` now builds the `"sum"`
entry itself, from raw per-string data, fixing the alignment bug in the
process. See ADR-004 §5's fifth Amendment (2026-09-03) for the full
rationale — this task's Acceptance Criteria/Consumed Interfaces below
are updated to match; no new task/dependency was needed since this
task's own code was not yet past review.

**Scope correction 2026-09-04 (human-directed, before this task's own
Gate 3/reviewer pass — see `tasks/INDEX.md`'s refinement log):**
`custom_components/shady/__init__.py` is removed from this task's own
scope. `__init__.py` is still Phase 0's placeholder skeleton — it does
not yet construct a `ShadyCoordinator` or populate `hass.data` at all —
and ADR-002 §1a's decision text already attributes the *entire*
`__init__.py` flow, service registration included, to
`TASK-0016-integration-setup-entry` as one coherent implementation
(the same reasoning that removed `__init__.py` from
`TASK-0011-forecast-sensor-and-recalculate-button`'s own scope on
2026-08-24 — see that refinement log entry). This task delivers the
coordinator-level methods the future service handler will call
(`pin_diagnostic_slot()`/`clear_diagnostic_slot()`/`diagnosed_slot()`,
already implemented and tested below) plus every diagnostic
sensor/select entity; `TASK-0016` — already depending on this task and
already naming `shady.select_diagnostic_slot` in its own Goal — owns
wiring the actual `hass.services.async_register` call to them.

 (ADR-004 §2 explicitly reuses
ADR-006 §1a's trigger rather than adding a third schedule) — this is a
genuine interface dependency, not just file overlap. Also extends
`cache.py` after TASK-0006 (both add accessors to the same file,
sequential).

## Acceptance Criteria
- Given the diagnostic mode select is `"off"`, When any diagnostic sensor
  is read, Then it reports `state: "disabled"` with no `series`
  attribute, and the coordinator performs no extra per-string fitting
  (zero cost when off, ADR-004 §1).
- Given the select is set to `"compare_regressions"` and auto-tracking,
  When the diagnosed slot is determined, Then it defaults to the **last
  complete** 5-minute slot, not the next upcoming one (ADR-004 §2).
- Given `shady.select_diagnostic_slot` is (eventually, via `TASK-0016`)
  called with a timestamp, When the resulting slot is within the
  available `FC` horizon, Then `coordinator.pin_diagnostic_slot(timestamp)`
  pins every diagnostic sensor (per-string and summed alike) to that
  slot and returns `True` — there is exactly one diagnosed-slot state
  per config entry, not one per sensor; When the timestamp falls at or
  beyond the horizon, Then it returns `False` with no state change
  (ADR-004 §2a). This task delivers and tests `pin_diagnostic_slot()`
  itself; the HA service call site is `TASK-0016`'s own scope (see the
  2026-09-04 scope-correction note above).
- Given a future-pinned slot, When rendered, Then `"selected {method}"`
  entries still appear (evaluated against the forward-looking `FC`), but
  `"selected actual"` is omitted from `series` and `accuracy` is an empty
  `{}` (ADR-004 §2/§2a).
- Given `get_pinned_slot_pool(sensor_ids, slot_of_day)` with no pin set,
  When called, Then its window resolves to `[today - window_days,
  today]`; with a pin to a past date, Then it resolves to `[pinned -
  window_days, pinned]`; with a pin to a future date, Then it falls back
  to the same today-anchored window as auto-tracking (ADR-007a §6).
- Given `"compare_regressions"` is active, When recalibration runs, Then
  `CompareRegressionsMode.extra_fit()` fits all four regression
  strategies for the diagnosed slot only (not all 288), and this extra
  cost disappears the moment the select is set back to `"off"`
  (ADR-004 §4).
- Given the `"sum"` diagnostic entity (§2b), When computed, Then it is the
  pointwise sum across strings at the one shared diagnosed slot, with
  `accuracy` derived from the *summed* predicted/actual values, not an
  average of per-string accuracies (ADR-004 §2b) — built by
  `CompareRegressionsMode.compute()` itself as one more
  `DiagnosticSensorResult` in the same call (`sensor_id="sum"`), not
  assembled in `sensor.py` from sibling sensors' output (ADR-004 §5,
  fifth Amendment).
- Given accuracy is computed, When `predicted_i` is more than 100% off
  from `PV_selected`, Then the displayed accuracy is clamped to `0%`, not
  a negative number (ADR-004 §2).
- Given `CompareRegressionsMode.compute()`, When it runs, Then it
  resolves the diagnosed slot's predicted/actual/pool values itself, via
  the `ShadyCoordinator` reference it was constructed with (ADR-004 §5,
  2026-09-01), building one `DiagnosticSensorResult` per configured
  string (each with its own `sensor_id`) and returning all of them as a
  single `DiagnosticResult.sensors` sequence in one call (ADR-004 §5,
  2026-09-02, second same-day amendment) — no `DiagnosticContext`/
  `DiagnosticSlotSample` is built or passed anywhere; those two types do
  not exist after `TASK-0015a-patch-2`. This is the first real caller to
  exercise `DiagnosticMode`'s no-argument, flat-sensor-list `compute()`/
  `extra_fit()` shape `TASK-0015a-patch-2`/`TASK-0015a-patch-4`'s
  acceptance criteria already established with dummy subclasses.
- Given `sensor.py`'s `ShadyDiagnosticsSensor`, When it reads its
  `state`/`attributes`, Then it looks up its own `sensor_id` in
  `coordinator.diagnostic_result()` — a cached accessor over the active
  mode's `compute()` output, refreshed once per tick via
  `compute_cadence()` — never calling `.compute()` itself (ADR-004 §5,
  fifth Amendment, 2026-09-03). Every declared `sensor_id`, `"sum"`
  included, is handled by this same one class and this same lookup —
  there is no separate sum-specific sensor class or sum-specific
  aggregation logic in `sensor.py` at all.
- Given `coordinator.py`'s `_diagnostic_modes` registry, When
  `async_setup_entry` runs, Then it creates exactly one
  `ShadyDiagnosticsSensor` per `(sensor_id, name)` pair returned by
  `coordinator.diagnostic_sensor_ids()` (the union of every *registered*
  mode's `sensor_ids()`, not just the active selection) — entities exist
  and stay stable across a `select.py` mode switch; a `sensor_id`
  belonging to a currently-inactive mode simply reads `"unavailable"`
  until that mode is selected (ADR-004 §5, fifth Amendment).
- Given `const.py`'s `DIAGNOSTIC_MODES`, When a second entry were ever
  added (not in this task's scope — see ADR-013), Then `select.py`,
  `coordinator.py`'s `_diagnostic_modes` registry, and `sensor.py`'s
  entity creation require no code change beyond registering the new
  `DiagnosticMode` subclass and its own `sensor_ids()` implementation —
  this task's implementation must not hard-code `"compare_regressions"`
  or a `"one per string plus one sum"` entity shape anywhere outside the
  registry entry, the `const.py` option list, and
  `CompareRegressionsMode`'s own `sensor_ids()`.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/cache.py` (extended — `get_pinned_slot_pool`,
  `pinned_reference`)
- `custom_components/shady/const.py` (extended — `DIAGNOSTIC_MODES`,
  `DEFAULT_DIAGNOSTIC_MODE`)
- `custom_components/shady/select.py` (new — `ShadyDiagnosticModeSelect`;
  no `switch.py` — nothing else in the project used that platform)
- `custom_components/shady/diagnostics/compare_regressions.py` (new —
  `CompareRegressionsMode(DiagnosticMode)`)
- `custom_components/shady/sensor.py` (extended — one generic
  `ShadyDiagnosticsSensor`, no dedicated sum-sensor class)
- `custom_components/shady/aggregation.py` (extended — accuracy function;
  stays here, not in `diagnostics/` — see ADR-004 §5 Amendment)
- `custom_components/shady/coordinator.py` (extended — `_diagnostic_modes`
  registry, per-instance, built in `__init__`; dispatch to the active
  mode's `extra_fit()` hooked to TASK-0013's 5-minute trigger, caching its
  `DiagnosticFitResult`)
- `custom_components/shady/__init__.py` — **removed from scope**, see
  the 2026-09-04 scope-correction note above (`TASK-0016`'s own
  footprint)
- `tests/test_cache_pinned_slot_pool.py` (zero-mocking),
  `tests/test_diagnostics_compare_regressions.py` (no longer
  zero-mocking as of ADR-000 §6's 2026-09-01 update — follows
  `coordinator.py`'s own hand-written `homeassistant`-stub convention,
  TASK-0009, since `CompareRegressionsMode` now requires a constructible
  `ShadyCoordinator`, not a bare dataclass),
  `tests/test_diagnostics_select_and_sensors.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- TASK-0006's and TASK-0013's existing test suites still pass.
- `DiagnosticMode`/`DiagnosticResult`/`DiagnosticSensorResult`/
  `DiagnosticFitResult` are used exactly as declared in
  `TASK-0015a-diagnostic-mode-base-architecture`'s,
  `TASK-0015a-patch-2-diagnostic-mode-coordinator-access`'s, and
  `TASK-0015a-patch-4-diagnostic-mode-sensor-list-output`'s Delivered
  Artifacts — no invented or renamed fields/methods.
  `DiagnosticContext`/`DiagnosticSlotSample`/`DiagnosticStringResult` do
  not appear anywhere in this task's code — the first two are deleted as
  of `TASK-0015a-patch-2`, the third (and the `by_string`/`by_sensor`
  string-index-keyed shape it was part of) is superseded as of
  `TASK-0015a-patch-4`.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0002, TASK-0006, TASK-0010, TASK-0011,
     TASK-0013, TASK-0015a-diagnostic-mode-base-architecture,
     TASK-0015a-patch-2-diagnostic-mode-coordinator-access,
     TASK-0015a-patch-3-diagnostic-mode-multi-string-bundling,
     TASK-0015a-patch-4-diagnostic-mode-sensor-list-output. -->
- `cache.<Cache class>` (post-TASK-0006 state) from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor)
- `coordinator.ShadyCoordinator` from `custom_components/shady/coordinator.py` (→ task: TASK-0010-coordinator-recalibration-recompute-push)
- `sensor.ShadyForecastSensor` (entity patterns) from `custom_components/shady/sensor.py` (→ task: TASK-0011-forecast-sensor-and-recalculate-button)
- `coordinator.ShadyCoordinator` (5-minute trigger) from `custom_components/shady/coordinator.py` (→ task: TASK-0013-intraday-deviation-correction)
- `diagnostics.base.DiagnosticResult`, `DiagnosticSensorResult`,
  `DiagnosticFitResult` (as `TASK-0015a-patch-4` restructured them) from
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-patch-4-diagnostic-mode-sensor-list-output):
  - `DiagnosticSensorResult` — frozen dataclass, six fields:
    `sensor_id: str`, `state: str`, `attributes: dict[str, Any]` (all
    required), `name: str | None = None`, `unit: str | None = None`,
    `device_class: str | None = None`. `CompareRegressionsMode` chooses
    its own `sensor_id` convention for each configured string (e.g. the
    string index as text) — the base class does not impose one.
  - `DiagnosticResult` — frozen dataclass: exactly one field,
    `sensors: Sequence[DiagnosticSensorResult]` — a flat collection, not
    keyed by string index or any other dimension.
    `CompareRegressionsMode.compute()` must build one
    `DiagnosticSensorResult` per configured string in a single call and
    return them all as this sequence — not one call per string, and not
    a `by_string`/`by_sensor` mapping (that shape was `TASK-0015a-patch-3`'s,
    superseded by `TASK-0015a-patch-4` before this task started).
  - `DiagnosticFitResult` — frozen dataclass: exactly one field,
    `by_sensor: Mapping[str, Mapping[str, float]]`, keyed by the same
    `sensor_id` strings `DiagnosticResult`'s entries use (not string
    index); each inner `Mapping[str, float]` keyed by compared-source
    name (method or provider name), unchanged since before any of the
    2026-09-02 amendments. `CompareRegressionsMode.extra_fit()` (if it
    overrides the base `None` default) must build this the same way,
    using the same `sensor_id`s `compute()` uses for the matching
    strings.
- `diagnostics.base.DiagnosticMode` (as amended by
  `TASK-0015a-patch-2-diagnostic-mode-coordinator-access`; output shapes
  restructured twice more, same day, by
  `TASK-0015a-patch-3-diagnostic-mode-multi-string-bundling` then
  `TASK-0015a-patch-4-diagnostic-mode-sensor-list-output`, but its own
  signatures unchanged by either) from
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-patch-2-diagnostic-mode-coordinator-access,
  TASK-0015a-patch-4-diagnostic-mode-sensor-list-output):
  - `abc.ABC`, `key: ClassVar[str]`.
  - `__init__(self, coordinator: ShadyCoordinator) -> None` (required;
    concrete modes are expected to store this, e.g. `self._coordinator`).
  - `fit_cadence(self) -> Literal["daily", "hourly", "slot"]` (abstract,
    required); `CompareRegressionsMode` declares `"slot"`.
  - `compute_cadence(self) -> Literal["daily", "hourly", "slot"]`
    (abstract, required); `CompareRegressionsMode` declares `"slot"`.
    As of the fifth Amendment (2026-09-03), `coordinator.py` actually
    reads this to drive `diagnostic_result()`'s per-tick cache refresh
    — previously declared but unread by anything.
  - `sensor_ids(self) -> Sequence[tuple[str, str]]` (abstract, required
    as of ADR-004 §5's fifth Amendment, 2026-09-03) — every `(sensor_id,
    name)` pair `compute()` will ever produce, resolvable without
    calling `compute()` itself; `CompareRegressionsMode` returns one
    pair per configured string plus `("sum", "Diagnostics Sum")`.
  - `compute(self) -> DiagnosticResult` (abstract, required, no
    parameter beyond `self` — covers every diagnostic entity this mode
    produces in one call, per the flat `DiagnosticResult` shape above).
  - `extra_fit(self) -> DiagnosticFitResult | None` (optional, default
    `None`, no parameter beyond `self` — same one-call-covers-everything
    shape as `compute()` when overridden).
  - **Not consumed:** `DiagnosticContext`, `DiagnosticSlotSample`,
    `DiagnosticStringResult` — the first two were deleted by
    `TASK-0015a-patch-2`; `DiagnosticStringResult` (and the
    `by_string`/`by_sensor`-mapping shape it was part of) was
    `TASK-0015a-patch-3`'s, superseded by `TASK-0015a-patch-4` before
    this task started. Do not reference any of the three.
- `sensor.py`'s `ShadyDiagnosticsSensor` — one instance per `(sensor_id,
  name)` pair from `coordinator.diagnostic_sensor_ids()` — looks up its
  own `sensor_id` in `coordinator.diagnostic_result()` for its
  `state`/`attributes`, never calling `.compute()` itself (ADR-004 §5,
  fifth Amendment, 2026-09-03, superseding the third Amendment's
  "recomputes every read" cost trade-off with the tick-cached accessor
  described above). There is no separate sum-specific sensor class;
  `"sum"` is handled by this same class and this same lookup, like any
  other declared `sensor_id`.
- `coordinator.ShadyCoordinator.cache` (public attribute) and
  `coordinator.ShadyCoordinator.strings() -> list[tuple[int, str]]`
  (public method, from `TASK-0010-patch-2-string-enumeration`) — the two
  public accessors `CompareRegressionsMode` may call through its stored
  coordinator reference; `strings()` is also how `compute()`/
  `extra_fit()`/`sensor_ids()` learn which strings to build entries for.
  See `TASK-0015a-patch-2`'s own Consumed Interfaces for the boundary
  rule on what else it may reach (from
  `custom_components/shady/coordinator.py` → task:
  TASK-0010-coordinator-recalibration-recompute-push).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/cache.py` (extended) →
  - `Cache.pin_reference(reference: date) -> None`,
    `Cache.clear_reference() -> None`,
    `Cache.pinned_reference` (property) `-> date | None` — one
    cache-wide pinned reference date (ADR-007a §6).
  - `Cache.get_pinned_slot_pool(sensor_ids: Sequence[str], slot_of_day: int, on_invalid: OnInvalid = "skip") -> dict[str, list[float | None | str]]`
    (overloaded like `get_regression_pools`) — one value per day across
    `window_days` days at a fixed `slot_of_day`, oldest day first;
    window anchors on `pinned_reference` when set to a date no later
    than today, else today (ADR-007a §6). Also updates `trim()` to use
    `pinned_reference` as an additional floor so an old pin's data
    survives a trim.
- `custom_components/shady/const.py` (extended) →
  `DIAGNOSTIC_MODES: tuple[str, ...] = ("off", "compare_regressions")`,
  `DEFAULT_DIAGNOSTIC_MODE = "off"`.
- `custom_components/shady/select.py` (new) →
  `ShadyDiagnosticModeSelect(SelectEntity)` — options from
  `const.DIAGNOSTIC_MODES`, `current_option`/`async_select_option`
  delegate to `coordinator.active_diagnostic_mode()`/
  `coordinator.set_active_diagnostic_mode()`; `async_setup_entry(hass, entry, async_add_entities)`
  adds exactly one instance.
- `custom_components/shady/diagnostics/compare_regressions.py` (new) →
  `CompareRegressionsMode(DiagnosticMode)` — `key = "compare_regressions"`,
  `fit_cadence()`/`compute_cadence()` both `"slot"`, `sensor_ids()`
  (one `(str(string_index), name)` pair per configured string plus
  `("sum", "Diagnostics Sum")`), `compute()` (one `DiagnosticSensorResult`
  per configured string plus a `"sum"` entry, built from raw per-string
  pool data via new NaN-aware helpers, fixing the cross-string
  day-alignment bug described in the 2026-09-03 design-correction note
  above), `extra_fit()` (fits all four regression strategies for the
  diagnosed slot only, via `string_computation.py`). Private helpers:
  `_GatheredPool`, `_StringDiagnostic`, `_to_float_array`.
- `custom_components/shady/aggregation.py` (extended, unchanged home) →
  `diagnostic_accuracy(predicted: float, actual: float) -> float`
  (clamped to `[0, 1]`), `sum_predicted`, `sum_values` (NaN-aware
  cross-string summation helpers).
- `custom_components/shady/sensor.py` (extended) →
  `ShadyDiagnosticsSensor(SensorEntity)` — one generic class per
  `(sensor_id, name)` pair from `coordinator.diagnostic_sensor_ids()`;
  `native_value`/`extra_state_attributes` look up `sensor_id` in
  `coordinator.diagnostic_result()` only, never calling `.compute()`
  itself (verified in `tests/test_sensor_diagnostics.py`). No dedicated
  sum-sensor class — `ShadyDiagnosticsSumSensor` was deleted per the
  2026-09-03 design correction. `async_setup_entry` creates one instance
  per declared `(sensor_id, name)` pair.
- `custom_components/shady/coordinator.py` (extended) →
  - `DiagnosedSlot` (frozen dataclass): `index: int`, `slot_of_day: int`,
    `is_elapsed: bool`.
  - `ShadyCoordinator.diagnosed_slot(now: datetime | None = None) -> DiagnosedSlot`,
    `.pin_diagnostic_slot(timestamp: datetime, now: datetime | None = None) -> bool`
    (rounds down to the 5-minute boundary; rejects — returns `False`,
    no state change — a timestamp at or beyond the end of tomorrow;
    accepts any timestamp within that horizon including the past),
    `.clear_diagnostic_slot() -> None`.
  - `ShadyCoordinator.active_diagnostic_mode() -> str`,
    `.set_active_diagnostic_mode(mode: str) -> None`,
    `.diagnostic_mode() -> DiagnosticMode | None`,
    `.diagnostic_result() -> DiagnosticResult | None` (caches the active
    mode's `compute()` output, refreshed once per tick via
    `compute_cadence()`, invalidated on mode switch / slot pin / slot
    clear), `.diagnostic_sensor_ids() -> list[tuple[str, str]]` (union
    of every *registered* mode's declared ids, first-registration-wins
    dedup, available even while off), `.now() -> datetime` (public read
    of the injectable clock).
  - `ShadyCoordinator._diagnostic_modes` (per-instance registry, built
    in `__init__`), `_diagnostics_tick_sync(now: datetime) -> None`
    (runs `extra_fit()` before `compute()` within one tick, each gated
    independently by its own cadence — hooked to TASK-0013's existing
    5-minute trigger, no new schedule).
  - **Known scope boundary, not a gap:** `__init__.py` wiring
    (constructing a `ShadyCoordinator` from a real config entry,
    registering the `shady.select_diagnostic_slot` HA service that
    calls `pin_diagnostic_slot`/`clear_diagnostic_slot`) is explicitly
    out of this task's scope — see the 2026-09-04 scope-correction note
    above. `TASK-0016-integration-setup-entry` owns it.
- Tests (all zero-mocking or hand-written-`homeassistant`-stub per
  ADR-000 §6, per-file convention noted below):
  - `tests/test_cache_pinned_slot_pool.py` (zero-mocking, 17 tests) —
    `pin_reference`/`clear_reference`/`pinned_reference`; window
    resolution (no pin, past pin, pinned-to-today, future-pin fallback);
    shape/ordering; `on_invalid` variants; single-fetch-call validation;
    `trim()` interaction.
  - `tests/test_select.py` (zero-mocking, 8 tests) — options list,
    `current_option`/`async_select_option` delegation, per-entry unique
    IDs, `async_setup_entry` entity count.
  - `tests/test_diagnostics_compare_regressions.py` (hand-written
    `homeassistant` stub, reuses `test_coordinator.py`'s harness, 8
    tests) — `sensor_ids()` resolvable without computing; `"sum"` entry
    day-alignment across a real two-string coordinator with mismatched
    gap patterns; `"sum"` unavailable when nothing contributes; selected
    aggregates summed independently (the confirmed-and-kept asymmetry);
    future-pinned slot omits `"selected actual"`/keeps `accuracy` empty.
  - `tests/test_coordinator.py` (appended, 20 new tests across 4
    classes) — `TestDiagnosedSlotAutoTracking`/`TestPinDiagnosticSlot`
    (auto-tracking default, 5-minute rounding, horizon
    accept/reject, `is_elapsed`, clear-reverts-to-auto-tracking);
    `TestDiagnosticResultCaching`/`TestDiagnosticSensorIds` (per-tick
    caching, cadence gating, invalidation on mode switch/pin/clear,
    union-of-registered-modes dedup).
  - `tests/test_sensor_diagnostics.py` (new, 4 tests, reuses
    `test_sensor_forecast.py`'s HA-stub harness) — proves
    `ShadyDiagnosticsSensor` never calls `.compute()` itself: many
    reads across many sensor instances add no `compute()` calls beyond
    the one priming read; disabled/unavailable states resolve without
    any `compute()` call.
  - `tests/test_sensor_forecast.py` (pre-existing, entity-count
    assertion updated for the new one-per-declared-id shape).
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged.
- Full suite: 401/401 passing; `mypy --strict` clean on 51 source files;
  `ruff check` clean repo-wide; `ruff format --check` clean on every
  file this task touched (two pre-existing, unrelated drift files —
  `adr/004-diagnostics-select-and-scatter-sensor.md`'s superseded code
  sketch and `tests/test_regression.py` — left untouched, out of scope,
  per this project's own established convention for pre-existing drift
  not introduced by the task at hand).