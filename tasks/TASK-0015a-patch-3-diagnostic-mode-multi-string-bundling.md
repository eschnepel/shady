# Task: Patch — `DiagnosticMode` Output Bundles Every String Per Call

- **Status:** done
- **Related ADRs:** [ADR-004 §5 (Amendment 2026-09-02), ADR-012 §1]
- **Dependencies:** [TASK-0015a-patch-2-diagnostic-mode-coordinator-access]

## Goal
Scenario C patch on the already-`done` `TASK-0015a-patch-2`: keep
`compute()`/`extra_fit()` zero-argument (unchanged from the 2026-09-01
amendment), but restructure their output dataclasses,
`DiagnosticResult`/`DiagnosticFitResult`, so a single call covers **every
configured string in one shot** rather than one string per call.

Discovered while assembling `TASK-0015b`'s Consumed Interfaces, before
any of its code existed: `coordinator.py`'s `_diagnostic_modes` holds one
shared `DiagnosticMode` instance per mode name (matching
`string_computation.py`'s `REGRESSION_STRATEGIES` lookup in shape, per
the 2026-09-01 amendment), but §2 needs one `ShadyDiagnosticsSensor` per
configured string, each with its own series/accuracy — and a
zero-argument `compute()`/`extra_fit()` on a single shared instance has
no way to know which string a given call is for. Three resolutions were
presented to the human (per-(mode, string) instances; bundle-by-string in
one call; reintroduce a `string_index` parameter); the human chose
bundle-by-string. See ADR-004 §5's third Amendment (2026-09-02) for the
full rationale, including the accepted N-strings-worth-of-recompute-per-
sensor-read cost trade-off.

## Acceptance Criteria
- Given `DiagnosticMode.compute`/`DiagnosticMode.extra_fit`, When their
  signatures are inspected, Then both remain exactly as
  `TASK-0015a-patch-2` left them — `compute(self) -> DiagnosticResult`,
  `extra_fit(self) -> DiagnosticFitResult | None` — no parameter is
  reintroduced.
- Given a new `DiagnosticStringResult` dataclass, When it is inspected,
  Then it has exactly `state: str` and `attributes: dict[str, Any]` —
  the same two fields `DiagnosticResult` held directly before this patch.
- Given `DiagnosticResult` after this patch, When it is inspected, Then
  it has exactly one field, `by_string: Mapping[int, DiagnosticStringResult]`
  — no `state`/`attributes` fields of its own.
- Given `DiagnosticFitResult` after this patch, When it is inspected,
  Then it has exactly one field, `by_string: Mapping[int, Mapping[str, float]]`
  — the inner `Mapping[str, float]` keyed by compared-source name
  (method or provider name), same as `TASK-0015a-patch-2`'s
  `predictions` field, now nested one level deeper under each string's
  key instead of being the dataclass's own top-level field.
- Given a dummy `DiagnosticMode` subclass whose `compute()` returns a
  `DiagnosticResult` bundling two strings' worth of
  `DiagnosticStringResult`, When the returned value is inspected, Then
  each string's `state`/`attributes` is reachable via
  `result.by_string[<index>]` unchanged from what the subclass produced.
- Given a dummy `DiagnosticMode` subclass whose `extra_fit()` returns a
  `DiagnosticFitResult` bundling two strings' worth of predictions, When
  the returned value is inspected, Then each string's inner
  `Mapping[str, float]` is reachable via `result.by_string[<index>]`
  unchanged from what the subclass produced.
- Given `diagnostics/base.py` after this patch, When its exports are
  listed, Then `DiagnosticStringResult` is newly exported alongside the
  restructured `DiagnosticResult`/`DiagnosticFitResult`; `DiagnosticMode`,
  `DiagnosticCadence`, `key: ClassVar[str]`, both cadence getters, and
  the constructor are all unchanged from `TASK-0015a-patch-2`.
- Given `tests/test_diagnostics_base.py`'s existing tests (from
  `TASK-0015a-patch-2`), When they are revised for the new shape, Then
  every test that constructed a bare `DiagnosticResult(state=..., attributes=...)`
  or `DiagnosticFitResult(predictions=...)` is updated to the new
  `by_string`-wrapped shape, and every other assertion (constructor
  requiredness, coordinator reachability, cadence-getter requiredness/
  values, no-parameter signatures) is otherwise unchanged.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/diagnostics/base.py` (`DiagnosticResult`/
  `DiagnosticFitResult` restructured; new `DiagnosticStringResult`;
  everything else in the file unchanged)
- `tests/test_diagnostics_base.py` (revised construction calls and
  assertions for the new output shape only — no change to the
  constructor/cadence/no-parameter tests)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0015a-patch-2. -->
- `diagnostics.base.DiagnosticMode` — exactly as `TASK-0015a-patch-2`
  delivered it (`__init__(self, coordinator: ShadyCoordinator)`,
  `key: ClassVar[str]`, `fit_cadence()`, `compute_cadence()`,
  `compute(self) -> DiagnosticResult`,
  `extra_fit(self) -> DiagnosticFitResult | None`) — unchanged by this
  patch; only the two return-type dataclasses it references are
  restructured. `diagnostics.base.DiagnosticCadence` — unchanged,
  `Literal["daily", "hourly", "slot"]`. From
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-patch-2-diagnostic-mode-coordinator-access).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/diagnostics/base.py` (restructured) →
  - `class DiagnosticStringResult` — **new**. `state: str`,
    `attributes: dict[str, Any]` — exactly `DiagnosticResult`'s
    pre-patch two fields, unchanged.
  - `class DiagnosticResult` — restructured: now exactly one field,
    `by_string: Mapping[int, DiagnosticStringResult]`. No `state`/
    `attributes` fields of its own.
  - `class DiagnosticFitResult` — restructured: now exactly one field,
    `by_string: Mapping[int, Mapping[str, float]]`. Inner mapping keyed
    by compared-source name (method or provider name), unchanged from
    the pre-patch `predictions` field's meaning.
  - `class DiagnosticMode(ABC)` — **unchanged** from `TASK-0015a-patch-2`:
    `__init__(self, coordinator: ShadyCoordinator)`,
    `key: ClassVar[str]`, `fit_cadence()`, `compute_cadence()`,
    `compute(self) -> DiagnosticResult`,
    `extra_fit(self) -> DiagnosticFitResult | None` — no parameter
    reintroduced on either method; only their referenced return-type
    dataclasses changed shape.
  - `DiagnosticCadence` — unchanged, `Literal["daily", "hourly", "slot"]`.
  - `DiagnosticContext`/`DiagnosticSlotSample` — remain deleted (not
    reintroduced by this patch).
- `tests/test_diagnostics_base.py` (revised) → 20 tests across 12
  classes (was 15/10; +5 net: one new test method added to the
  existing `TestDiagnosticContextRemoved` class for
  `DiagnosticStringResult`'s new export, plus two new classes —
  `TestDiagnosticResultShape` (3 tests) and
  `TestDiagnosticResultMultiStringBundling` (1 test)). Every construction of
  `DiagnosticResult`/`DiagnosticFitResult` throughout the file updated to
  the `by_string`-wrapped shape via a new `_single_string_result()` test
  helper (for tests that don't care about bundling itself) or explicit
  two-string bundles (for the tests that do); every other assertion
  (constructor requiredness, coordinator reachability, cadence-getter
  requiredness/values, no-parameter signatures) unchanged from
  `TASK-0015a-patch-2`. New coverage added per this task's acceptance
  criteria: `DiagnosticResult`/`DiagnosticFitResult` each have exactly
  one field (`dataclasses.fields()` introspection),
  `DiagnosticStringResult` has exactly `state`/`attributes`, a
  two-string `compute()` bundle round-trips both strings' `state`/
  `attributes` unchanged via `result.by_string[<index>]`, a two-string
  `extra_fit()` bundle round-trips both strings' prediction mappings
  unchanged the same way, and the existing coordinator-reading test
  (`TestDiagnosticModeUsesCoordinatorInCompute`) now builds its
  `DiagnosticResult` from `self._coordinator.strings()`'s two entries
  directly, bundling both in one `compute()` call instead of returning
  a flat single-string result.
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged.
- `adr/004-diagnostics-select-and-scatter-sensor.md` — third Amendment
  block added (2026-09-02), documenting the discovered gap, the three
  resolutions presented to the human, the human's choice, and the
  accepted per-read recompute cost trade-off; header `Amended` line
  updated to reference it.
- Full suite: 343/343 (338 pre-existing + 5 net new, per the test-count
  breakdown above). `mypy --strict` clean on 45 source files. `ruff
  check` clean repo-wide. `ruff format` applied to both touched Python
  files (test file needed reformatting for two now-nested dict-literal
  constructions and one import-sort fix after adding the
  `DiagnosticStringResult` `TYPE_CHECKING` import; `diagnostics/base.py`
  needed no reformatting).
- `git diff --stat` confirms only `adr/004-diagnostics-select-and-scatter-sensor.md`,
  `custom_components/shady/diagnostics/base.py`, and
  `tests/test_diagnostics_base.py` changed in this task's commit
  (plus this task's own new file).
- `TASK-0015a-patch-2-diagnostic-mode-coordinator-access` is **not**
  reopened — its `Delivered Artifacts` block is left exactly as that
  task recorded it, per Scenario C's "do not reopen" rule; this patch's
  own Delivered Artifacts block (above) is the record of what changed
  relative to it.
