# Task: Diagnostics — Select Entity & Scatter/Accuracy Sensors

- **Status:** todo
- **Related ADRs:** [ADR-004 §1 (Amendment 2026-08-30), ADR-004 §2, ADR-004 §2a, ADR-004 §2b, ADR-004 §3, ADR-004 §4, ADR-004 §5 (Amendment 2026-08-30), ADR-007a §6]
- **Dependencies:** [TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor, TASK-0010-coordinator-recalibration-recompute-push, TASK-0011-forecast-sensor-and-recalculate-button, TASK-0013-intraday-deviation-correction, TASK-0015a-diagnostic-mode-base-architecture, TASK-0017-string-computation-module, TASK-0015a-patch-1-diagnostic-fit-inputs]

## Goal
Implement `cache.py`'s `get_pinned_slot_pool` accessor + cache-wide
`pinned_reference: date | None` scalar (`pin_reference()`/
`clear_reference()`); `select.py`'s `ShadyDiagnosticModeSelect` (default
`"off"`, gates all diagnostic sensors and their extra fitting cost via
`const.py`'s `DIAGNOSTIC_MODES` option list); `diagnostics/
compare_regressions.py`'s `CompareRegressionsMode` (the one concrete
`DiagnosticMode` in scope, built on
TASK-0015a-diagnostic-mode-base-architecture's base class); `sensor.py`'s
`ShadyDiagnosticsSensor` (per
string) + `ShadyDiagnosticsSumSensor` (per entry); the accuracy pure
function in `aggregation.py` (unchanged home — see ADR-004 §5 Amendment,
kept mode-independent so ADR-013's sketched future modes can reuse it
unmodified); `coordinator.py`'s `_DIAGNOSTIC_MODES` registry and
dispatch; and the `shady.select_diagnostic_slot` service registered in
`__init__.py`.

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
fit/reverse-transform/clamp computation, and needs
`DiagnosticSlotSample`'s two new fields (`query_fc`, `fit_inputs`) plus
the new `DiagnosticFitInputs` dataclass (`TASK-0015a-patch-1`) to carry
that computation's raw inputs through `DiagnosticContext` without
`diagnostics/` importing `cache.py`/`homeassistant.*` itself.

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
- Given `CompareRegressionsMode`, When it builds a `DiagnosticContext` for
  the diagnosed slot, Then it passes exactly one `DiagnosticSlotSample` —
  the one-sample case TASK-0015a-diagnostic-mode-base-architecture's
  acceptance criteria already established, exercised here for the first
  time by a real caller.
- Given `const.py`'s `DIAGNOSTIC_MODES`, When a second entry were ever
  added (not in this task's scope — see ADR-013), Then `select.py`,
  `coordinator.py`'s `_DIAGNOSTIC_MODES` registry, and `sensor.py`'s
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
- `custom_components/shady/coordinator.py` (extended — `_DIAGNOSTIC_MODES`
  registry, dispatch to the active mode's `extra_fit()` hooked to
  TASK-0013's 5-minute trigger, caching its `DiagnosticFitResult`)
- `custom_components/shady/__init__.py` (extended — service registration)
- `tests/test_cache_pinned_slot_pool.py` (zero-mocking),
  `tests/test_diagnostics_compare_regressions.py` (zero-mocking, mirrors
  `test_providers_base.py`'s dynamic-subclass pattern),
  `tests/test_diagnostics_select_and_sensors.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- TASK-0006's and TASK-0013's existing test suites still pass.
- TASK-0015a-diagnostic-mode-base-architecture's `DiagnosticMode`/
  `DiagnosticContext`/`DiagnosticSlotSample`/`DiagnosticResult`/
  `DiagnosticFitResult` are used exactly as declared in its Delivered
  Artifacts — no invented or renamed fields/methods.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0002, TASK-0006, TASK-0010, TASK-0011,
     TASK-0013, TASK-0015a-diagnostic-mode-base-architecture. -->
- `cache.<Cache class>` (post-TASK-0006 state) from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor)
- `coordinator.ShadyCoordinator` from `custom_components/shady/coordinator.py` (→ task: TASK-0010-coordinator-recalibration-recompute-push)
- `sensor.ShadyForecastSensor` (entity patterns) from `custom_components/shady/sensor.py` (→ task: TASK-0011-forecast-sensor-and-recalculate-button)
- `coordinator.ShadyCoordinator` (5-minute trigger) from `custom_components/shady/coordinator.py` (→ task: TASK-0013-intraday-deviation-correction)
- `diagnostics.base.DiagnosticMode`, `DiagnosticContext`,
  `DiagnosticSlotSample`, `DiagnosticResult`, `DiagnosticFitResult` from
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-diagnostic-mode-base-architecture):
  - `DiagnosticSlotSample` — frozen dataclass: `slot_of_day: int`,
    `predicted: Mapping[str, float]`, `actual: float | None`,
    `pool: Mapping[str, list[tuple[float, float]]] | None = None`.
  - `DiagnosticContext` — frozen dataclass: `samples: Sequence[DiagnosticSlotSample]`.
  - `DiagnosticResult` — frozen dataclass: `state: str`, `attributes: dict[str, Any]`.
  - `DiagnosticFitResult` — frozen dataclass: `predictions: Mapping[str, float]`.
  - `DiagnosticMode` — `abc.ABC`, `key: ClassVar[str]`;
    `compute(self, context: DiagnosticContext) -> DiagnosticResult`
    (abstract, required); `extra_fit(self, context: DiagnosticContext) ->
    DiagnosticFitResult | None` (optional, default `None`). Note:
    `extra_fit`'s parameter is `DiagnosticContext` — ADR-004's own sketch
    named it `DiagnosticFitContext`, a typo corrected during TASK-0015a
    (see `tasks/INDEX.md`'s 2026-08-31 refinement-log entry).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
