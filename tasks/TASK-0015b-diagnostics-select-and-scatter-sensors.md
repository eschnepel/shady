# Task: Diagnostics — Select Entity & Scatter/Accuracy Sensors

- **Status:** todo
- **Related ADRs:** [ADR-004 §1 (Amendment 2026-08-30), ADR-004 §2, ADR-004 §2a, ADR-004 §2b, ADR-004 §3, ADR-004 §4, ADR-004 §5 (Amendments 2026-08-30 and 2026-09-01), ADR-007a §6, ADR-000 §3/§6 (Amendment 2026-09-01)]
- **Dependencies:** [TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor, TASK-0010-coordinator-recalibration-recompute-push, TASK-0011-forecast-sensor-and-recalculate-button, TASK-0013-intraday-deviation-correction, TASK-0015a-diagnostic-mode-base-architecture, TASK-0017-string-computation-module, TASK-0015a-patch-2-diagnostic-mode-coordinator-access]

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
  2026-09-01) — no `DiagnosticContext`/`DiagnosticSlotSample` is built or
  passed anywhere; those two types do not exist after
  `TASK-0015a-patch-2`. This is the first real caller to exercise
  `DiagnosticMode`'s no-argument `compute()`/`extra_fit()` shape
  `TASK-0015a-patch-2`'s acceptance criteria already established with a
  dummy subclass.
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
- `DiagnosticMode`/`DiagnosticResult`/`DiagnosticFitResult` are used
  exactly as declared in `TASK-0015a-diagnostic-mode-base-architecture`'s
  and `TASK-0015a-patch-2-diagnostic-mode-coordinator-access`'s Delivered
  Artifacts — no invented or renamed fields/methods.
  `DiagnosticContext`/`DiagnosticSlotSample` do not appear anywhere in
  this task's code — both are deleted as of `TASK-0015a-patch-2`.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0002, TASK-0006, TASK-0010, TASK-0011,
     TASK-0013, TASK-0015a-diagnostic-mode-base-architecture,
     TASK-0015a-patch-2-diagnostic-mode-coordinator-access. -->
- `cache.<Cache class>` (post-TASK-0006 state) from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor)
- `coordinator.ShadyCoordinator` from `custom_components/shady/coordinator.py` (→ task: TASK-0010-coordinator-recalibration-recompute-push)
- `sensor.ShadyForecastSensor` (entity patterns) from `custom_components/shady/sensor.py` (→ task: TASK-0011-forecast-sensor-and-recalculate-button)
- `coordinator.ShadyCoordinator` (5-minute trigger) from `custom_components/shady/coordinator.py` (→ task: TASK-0013-intraday-deviation-correction)
- `diagnostics.base.DiagnosticResult`, `DiagnosticFitResult` from
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-diagnostic-mode-base-architecture, unchanged by the patch
  below):
  - `DiagnosticResult` — frozen dataclass: `state: str`, `attributes: dict[str, Any]`.
  - `DiagnosticFitResult` — frozen dataclass: `predictions: Mapping[str, float]`.
- `diagnostics.base.DiagnosticMode` (as amended by
  `TASK-0015a-patch-2-diagnostic-mode-coordinator-access`) from
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-patch-2-diagnostic-mode-coordinator-access):
  - `abc.ABC`, `key: ClassVar[str]`.
  - `__init__(self, coordinator: ShadyCoordinator) -> None` (required;
    concrete modes are expected to store this, e.g. `self._coordinator`).
  - `fit_cadence(self) -> Literal["daily", "hourly", "slot"]` (abstract,
    required); `CompareRegressionsMode` declares `"slot"`.
  - `compute_cadence(self) -> Literal["daily", "hourly", "slot"]`
    (abstract, required); `CompareRegressionsMode` declares `"slot"`.
  - `compute(self) -> DiagnosticResult` (abstract, required, no
    parameter beyond `self`).
  - `extra_fit(self) -> DiagnosticFitResult | None` (optional, default
    `None`, no parameter beyond `self`).
  - **Not consumed:** `DiagnosticContext`, `DiagnosticSlotSample` —
    `TASK-0015a` originally delivered both, but `TASK-0015a-patch-2`
    deletes them before this task starts; do not reference either.
- `coordinator.ShadyCoordinator.cache` (public attribute) and
  `coordinator.ShadyCoordinator.strings() -> list[tuple[int, str]]`
  (public method, from `TASK-0010-patch-2-string-enumeration`) — the two
  public accessors `CompareRegressionsMode` may call through its stored
  coordinator reference; see `TASK-0015a-patch-2`'s own Consumed
  Interfaces for the boundary rule on what else it may reach (from
  `custom_components/shady/coordinator.py` → task:
  TASK-0010-coordinator-recalibration-recompute-push).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
