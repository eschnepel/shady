# Task: Patch — `DiagnosticMode` Output Generalized to a Sensor List

- **Status:** done
- **Related ADRs:** [ADR-004 §5 (Amendment 2026-09-02, second same day), ADR-013 §1, ADR-012 §1]
- **Dependencies:** [TASK-0015a-patch-3-diagnostic-mode-multi-string-bundling]

## Goal
Second same-day Scenario C patch — this time on the already-`done`
`TASK-0015a-patch-3`: replace `DiagnosticResult`/`DiagnosticFitResult`'s
string-index keying with a flat, self-identifying shape, so a mode that
isn't scoped to "one entry per configured string" at all (ADR-013's
sketched `compare_providers_daily`/`compare_regressions_daily`) can still
produce a well-formed result without any further change to
`diagnostics/base.py`.

Discovered immediately after `TASK-0015a-patch-3` was merged, while
reviewing that same-day decision against ADR-013 (written specifically to
validate this base class against needs beyond `CompareRegressionsMode`):
`compare_providers_daily` compares candidate providers, not strings, and
`compare_regressions_daily` produces a single whole-day series, not one
entry per string either. String-index keying would have silently broken
ADR-013's own central claim the moment either sketched mode was built.

## Acceptance Criteria
- Given `DiagnosticMode.compute`/`DiagnosticMode.extra_fit`, When their
  signatures are inspected, Then both remain exactly as
  `TASK-0015a-patch-2`/`TASK-0015a-patch-3` left them —
  `compute(self) -> DiagnosticResult`,
  `extra_fit(self) -> DiagnosticFitResult | None` — no parameter is
  reintroduced.
- Given a new `DiagnosticSensorResult` dataclass (replacing
  `DiagnosticStringResult`), When it is inspected, Then it has exactly
  six fields: `sensor_id: str` (required), `state: str` (required),
  `attributes: dict[str, Any]` (required), `name: str | None = None`,
  `unit: str | None = None`, `device_class: str | None = None`.
- Given `diagnostics/base.py` after this patch, When its exports are
  listed, Then `DiagnosticStringResult` no longer exists (renamed, not
  kept alongside the new class).
- Given `DiagnosticResult` after this patch, When it is inspected, Then
  it has exactly one field, `sensors: Sequence[DiagnosticSensorResult]`
  — not `by_string`.
- Given `DiagnosticFitResult` after this patch, When it is inspected,
  Then it has exactly one field,
  `by_sensor: Mapping[str, Mapping[str, float]]` — keyed by `sensor_id`
  (a `str`), not string index (an `int`).
- Given a dummy `DiagnosticMode` subclass whose `compute()` returns a
  `DiagnosticResult` with three `DiagnosticSensorResult` entries using
  three different kinds of `sensor_id` (a string-index-derived id, a
  provider-name id, and a fixed whole-array sentinel id — demonstrating
  the generalization is real, not just renamed), When the returned value
  is inspected, Then all three entries are present in `result.sensors`
  unchanged, each reachable by its own `sensor_id`.
- Given a dummy `DiagnosticMode` subclass whose `compute()` returns a
  `DiagnosticSensorResult` using only the three required fields (`name`/
  `unit`/`device_class` omitted), When the returned value is inspected,
  Then all three optional fields are `None`.
- Given `tests/test_diagnostics_base.py`'s existing tests (from
  `TASK-0015a-patch-3`), When they are revised for the new shape, Then
  every construction of `DiagnosticResult(by_string=...)`/
  `DiagnosticStringResult(...)`/`DiagnosticFitResult(by_string=...)` is
  updated to the new `sensors`/`DiagnosticSensorResult`/`by_sensor`
  shape, and every other assertion (constructor requiredness,
  coordinator reachability, cadence-getter requiredness/values,
  no-parameter signatures) is otherwise unchanged.
- Given `adr/013-whole-day-diagnostic-modes.md`, When it is reviewed
  against this patch, Then its `2026-09-02` note (added for the prior
  same-day amendment) is updated to reflect that the base class changed
  again the same day, and that neither sketched mode needs any further
  change beyond this — `compare_regressions_daily` and
  `compare_providers_daily` both fit the flat `sensor_id`-keyed shape
  without modification.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/diagnostics/base.py` (`DiagnosticResult`/
  `DiagnosticFitResult` restructured; `DiagnosticStringResult` renamed
  and extended to `DiagnosticSensorResult`; everything else in the file
  unchanged)
- `tests/test_diagnostics_base.py` (revised construction calls and
  assertions for the new output shape only)
- `adr/013-whole-day-diagnostic-modes.md` (note update only, no
  structural change to that document's own §1–§4)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0015a-patch-3. -->
- `diagnostics.base.DiagnosticMode` — exactly as `TASK-0015a-patch-2`
  delivered it, unchanged by `TASK-0015a-patch-3` and unchanged by this
  patch too (`__init__(self, coordinator: ShadyCoordinator)`,
  `key: ClassVar[str]`, `fit_cadence()`, `compute_cadence()`,
  `compute(self) -> DiagnosticResult`,
  `extra_fit(self) -> DiagnosticFitResult | None`). From
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-patch-3-diagnostic-mode-multi-string-bundling).
- `diagnostics.base.DiagnosticStringResult`/`DiagnosticResult.by_string`/
  `DiagnosticFitResult.by_string` — `TASK-0015a-patch-3`'s delivered
  shape, being replaced by this patch (not extended alongside it).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/diagnostics/base.py` (restructured) →
  - `class DiagnosticSensorResult` — **new**, replaces
    `DiagnosticStringResult` (deleted, not kept alongside it). Six
    fields: `sensor_id: str`, `state: str`, `attributes: dict[str, Any]`
    (all required), `name: str | None = None`, `unit: str | None = None`,
    `device_class: str | None = None`.
  - `class DiagnosticResult` — restructured: now exactly one field,
    `sensors: Sequence[DiagnosticSensorResult]` (was
    `by_string: Mapping[int, DiagnosticStringResult]`).
  - `class DiagnosticFitResult` — restructured: now exactly one field,
    `by_sensor: Mapping[str, Mapping[str, float]]` (was
    `by_string: Mapping[int, Mapping[str, float]]`) — outer key changed
    from string index (`int`) to `sensor_id` (`str`); inner mapping
    unchanged (compared-source name → float).
  - `class DiagnosticMode(ABC)` — **unchanged** from
    `TASK-0015a-patch-2`/`TASK-0015a-patch-3`: `__init__`,
    `key: ClassVar[str]`, `fit_cadence()`, `compute_cadence()`,
    `compute(self) -> DiagnosticResult`,
    `extra_fit(self) -> DiagnosticFitResult | None` — no parameter
    reintroduced on either method; only their referenced return-type
    dataclasses changed shape a second time today.
  - `DiagnosticCadence` — unchanged, `Literal["daily", "hourly", "slot"]`.
  - `DiagnosticContext`/`DiagnosticSlotSample` — remain deleted (not
    reintroduced by this patch).
  - New import: `Sequence` added to the existing
    `collections.abc.Mapping` import line.
- `tests/test_diagnostics_base.py` (revised) → 22 tests across 12
  classes (was 20/12 after `TASK-0015a-patch-3`; net +2 — one test
  removed/replaced by a differently-scoped one in the
  renamed-and-expanded generalization class, one new test added to
  `TestDiagnosticResultShape` for the optional-fields-default-to-`None`
  case, one new test added to `TestDiagnosticContextRemoved` for
  `DiagnosticStringResult`'s removal). Renamed
  `TestDiagnosticResultMultiStringBundling` →
  `TestDiagnosticResultSensorListGeneralization`, now asserting the
  actual generalization this patch exists for: one `compute()` call
  bundling three entries with three *differently-scoped* `sensor_id`
  kinds (a string-index-derived id, a provider-name id, and a fixed
  whole-array sentinel id), all reachable unchanged by their own
  `sensor_id` — not just "two strings" as `TASK-0015a-patch-3`'s
  equivalent test asserted. Every other construction of
  `DiagnosticResult`/`DiagnosticFitResult` throughout the file updated
  to the `sensors`/`DiagnosticSensorResult`/`by_sensor` shape via a
  renamed `_single_sensor_result()` helper (for tests that don't care
  about the flat-collection shape itself) or explicit multi-entry
  bundles (for the tests that do); every other assertion (constructor
  requiredness, coordinator reachability, cadence-getter requiredness/
  values, no-parameter signatures) unchanged from `TASK-0015a-patch-3`.
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged.
- `adr/004-diagnostics-select-and-scatter-sensor.md` — fourth Amendment
  block added (2026-09-02, second same day), documenting the discovered
  generalization gap against ADR-013, the decision, the
  `DiagnosticFitResult` symmetry extension flagged as not explicitly
  requested, and the accepted rationale; header `Amended` line updated
  to reference it.
- `adr/013-whole-day-diagnostic-modes.md` — its 2026-09-01 note extended
  with a 2026-09-02 note confirming both sketched modes
  (`compare_regressions_daily`, `compare_providers_daily`) still need no
  further `diagnostics/base.py` change under the new flat,
  `sensor_id`-keyed shape — restoring the document's own original §1/§4
  claim, which the first same-day amendment (string-index keying) would
  have broken.
- Full suite: 345/345 (343 pre-existing + 2 net new, per the test-count
  breakdown above). `mypy --strict` clean on 45 source files. `ruff
  check` clean repo-wide. `ruff format` + manual line-wrapping applied
  to `tests/test_diagnostics_base.py` (several dict-literal/call
  constructions exceeded the 100-column limit after the `sensor_id`
  field additions; `ruff format`'s own pass didn't reflow them
  automatically, so they were wrapped by hand and then reformatted).
  `diagnostics/base.py` needed no reformatting.
- `git diff --stat` confirms only `adr/004-diagnostics-select-and-scatter-sensor.md`,
  `adr/013-whole-day-diagnostic-modes.md`,
  `custom_components/shady/diagnostics/base.py`, and
  `tests/test_diagnostics_base.py` changed in this task's commit (plus
  this task's own new file).
- `TASK-0015a-patch-3-diagnostic-mode-multi-string-bundling` is **not**
  reopened — its `Delivered Artifacts` block is left exactly as that
  task recorded it, per Scenario C's "do not reopen" rule; this patch's
  own Delivered Artifacts block (above) is the record of what changed
  relative to it, the same way `TASK-0015a-patch-3` documented its own
  changes relative to `TASK-0015a-patch-2` without reopening that one
  either.
