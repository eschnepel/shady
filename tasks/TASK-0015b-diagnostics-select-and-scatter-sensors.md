# Task: Diagnostics — Select Entity & Scatter/Accuracy Sensors

- **Status:** todo
- **Related ADRs:** [ADR-004 §1 (Amendment 2026-08-30), ADR-004 §2, ADR-004 §2a, ADR-004 §2b, ADR-004 §3, ADR-004 §4, ADR-004 §5 (Amendments 2026-08-30, 2026-09-01, 2026-09-02 x2), ADR-007a §6, ADR-000 §3/§6 (Amendment 2026-09-01), ADR-013 §1]
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
`ShadyDiagnosticsSensor` (per
string) + `ShadyDiagnosticsSumSensor` (per entry); the accuracy pure
function in `aggregation.py` (unchanged home — see ADR-004 §5 Amendment,
kept mode-independent so ADR-013's sketched future modes can reuse it
unmodified); `coordinator.py`'s `_diagnostic_modes` registry (per-
instance, built in `__init__` — ADR-004 §5, 2026-09-01) and dispatch; and
the `shady.select_diagnostic_slot` service registered in `__init__.py`.

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

**Reuses TASK-0013's 5-minute trigger** (ADR-004 §2 explicitly reuses
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
- Given `shady.select_diagnostic_slot` is called with a timestamp, When
  the resulting slot is within the available `FC` horizon, Then it pins
  every diagnostic sensor (per-string and summed alike) to that slot —
  there is exactly one diagnosed-slot state per config entry, not one per
  sensor (ADR-004 §2a).
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
- Given `ShadyDiagnosticsSumSensor`, When computed, Then it is the
  pointwise sum across strings at the one shared diagnosed slot, with
  `accuracy` derived from the *summed* predicted/actual values, not an
  average of per-string accuracies (ADR-004 §2b).
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
- Given `sensor.py`'s per-string `ShadyDiagnosticsSensor`, When it reads
  its `state`/`attributes`, Then it calls `compute()` once and finds its
  own entry in the returned `DiagnosticResult.sensors` by matching
  `sensor_id` — not a separate `compute()` call per sensor's own string
  in isolation (ADR-004 §5, 2026-09-02). `ShadyDiagnosticsSumSensor` does
  not call `compute()` at all — it reads the per-string sensors' own
  already-computed `state`/`attributes` and sums them itself.
- Given `const.py`'s `DIAGNOSTIC_MODES`, When a second entry were ever
  added (not in this task's scope — see ADR-013), Then `select.py`,
  `coordinator.py`'s `_diagnostic_modes` registry, and `sensor.py`'s
  lookup require no code change beyond registering the new
  `DiagnosticMode` subclass — this task's implementation must not
  hard-code `"compare_regressions"` anywhere outside the registry
  entry and the `const.py` option list itself.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/cache.py` (extended — `get_pinned_slot_pool`,
  `pinned_reference`)
- `custom_components/shady/const.py` (extended — `DIAGNOSTIC_MODES`,
  `DEFAULT_DIAGNOSTIC_MODE`)
- `custom_components/shady/select.py` (new — `ShadyDiagnosticModeSelect`;
  no `switch.py` — nothing else in the project used that platform)
- `custom_components/shady/diagnostics/compare_regressions.py` (new —
  `CompareRegressionsMode(DiagnosticMode)`)
- `custom_components/shady/sensor.py` (extended — `ShadyDiagnosticsSensor`,
  `ShadyDiagnosticsSumSensor`)
- `custom_components/shady/aggregation.py` (extended — accuracy function;
  stays here, not in `diagnostics/` — see ADR-004 §5 Amendment)
- `custom_components/shady/coordinator.py` (extended — `_diagnostic_modes`
  registry, per-instance, built in `__init__`; dispatch to the active
  mode's `extra_fit()` hooked to TASK-0013's 5-minute trigger, caching its
  `DiagnosticFitResult`)
- `custom_components/shady/__init__.py` (extended — service registration)
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
- `sensor.py`'s per-string `ShadyDiagnosticsSensor` calls `compute()`
  once and finds its own entry in the returned `DiagnosticResult.sensors`
  by matching `sensor_id` for its `state`/`attributes` — every
  per-string sensor's read recomputes every diagnostic entity this mode
  produces, not just its own (ADR-004 §5, third Amendment's accepted
  cost trade-off, unaffected by the fourth Amendment's shape change).
  `ShadyDiagnosticsSumSensor` does **not** call `compute()` — it reads
  the per-string sensors' own already-shaped `state`/`attributes`
  directly and sums them itself, unaffected by either restructuring.
- `coordinator.ShadyCoordinator.cache` (public attribute) and
  `coordinator.ShadyCoordinator.strings() -> list[tuple[int, str]]`
  (public method, from `TASK-0010-patch-2-string-enumeration`) — the two
  public accessors `CompareRegressionsMode` may call through its stored
  coordinator reference; `strings()` is also how `compute()`/`extra_fit()`
  learn which strings to build `DiagnosticSensorResult` entries for. See
  `TASK-0015a-patch-2`'s own Consumed Interfaces for the boundary rule on
  what else it may reach (from `custom_components/shady/coordinator.py`
  → task: TASK-0010-coordinator-recalibration-recompute-push).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
