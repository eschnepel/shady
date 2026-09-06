# Audit Task: Diagnostics Package

- **Status:** todo
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** [ADR-004 §1, ADR-004 §2, ADR-004 §2a, ADR-004 §2b, ADR-004 §3, ADR-004 §4, ADR-004 §5, ADR-012 §1, ADR-013 §1, ADR-013 §2, ADR-014 §5, ADR-000 §3, ADR-000 §6]
- **Dependencies:** [] (TASK-0015a-diagnostic-mode-base-architecture +
  4 patches, TASK-0015b are `done`; TASK-0015a-patch-1 is `superseded`)
- **Origin:** ADR-004 has been amended **five times** (2026-08-30,
  09-01, 09-02 ×2, 09-03) and its implementation went through
  TASK-0015a's base architecture, four patches (one — patch-1 —
  superseded rather than completed), and TASK-0015b's full select/
  scatter-sensor build. This is the single most-amended ADR and the
  most patch-churned implementation surface in the project — highest
  priority audit target.

## Goal
Verify `diagnostics/base.py` and `diagnostics/compare_regressions.py`
match ADR-004's **current** (post all five amendments) decision — not an
earlier version — and specifically confirm that `TASK-0015a-patch-1`'s
supersession didn't leave a half-applied change behind, and that
`DiagnosticMode`'s loss of its "zero-mocking purity guarantee" (noted in
`tasks/adr-summary.md` §2 as of the 2026-09-01 amendment) was a
deliberate, fully-executed architectural change rather than an
inconsistent one.

## Scope — Source Files
- `custom_components/shady/diagnostics/__init__.py`
- `custom_components/shady/diagnostics/base.py`
- `custom_components/shady/diagnostics/compare_regressions.py`

## Scope — Test Files
- `tests/test_diagnostics_base.py`
- `tests/test_diagnostics_compare_regressions.py`

## Out of Scope
- `select.py`'s exposure of the diagnostic-mode picker and `sensor.py`'s
  scatter/accuracy sensors (covered by AUDIT-0009) — this audit checks
  the `DiagnosticMode` machinery itself, not its HA-facing surface.
- `coordinator.py`'s per-instance mode registry and the construction-
  time reference it passes into each `DiagnosticMode` (covered by
  AUDIT-0005) — this audit checks the receiving side in
  `diagnostics/base.py`.
- `string_computation.py` itself (covered by AUDIT-0006) — this audit
  checks that diagnostics calls it correctly, not its internals.

## Audit Criteria
- [ADR-004 §1, as amended 2026-08-30] Is diagnostics genuinely surfaced
  via a select dropdown with a `DiagnosticMode` base class, with **no**
  leftover boolean-switch implementation from before the amendment
  (check for a stray `switch.py` diagnostic entity or dead code)?
- [ADR-004 §2] Is there exactly one scatter-series sensor per configured
  PV string, with per-string identity correctly threaded through (no
  two strings accidentally sharing one sensor's data)?
- [ADR-004 §2a] Does manual slot selection via timestamp work as
  documented — does an out-of-range or malformed timestamp fail
  gracefully per whatever the ADR specifies, rather than crashing or
  silently returning a wrong slot?
- [ADR-004 §2b, as amended 2026-09-03] Does the summed-up
  diagnostics-across-all-strings sensor match the **revised** 2026-09-03
  behavior specifically — audit the amendment text, not the original
  §2b, since this section was revised.
- [ADR-004 §3, as amended 2026-09-03] Is the historical pool cached and
  refreshed at midnight/system start only — is there a test or code
  path that would reveal it accidentally refreshing every tick (a
  performance-relevant regression, not just a correctness one)?
- [ADR-004 §4] Is the extra fitting cost genuinely gated to only occur
  while `compare_regressions` is the active diagnostic mode — does
  selecting a different mode actually stop the extra computation, not
  just stop displaying its result?
- [ADR-004 §5, as amended through 2026-09-03 — the most-revised
  section] Confirm the **current** module responsibility split:
  `DiagnosticMode` has construction-time `ShadyCoordinator` access,
  `fit_cadence`/`compute_cadence` getters, and is *not* zero-mocking
  pure anymore. Does the code match this exactly, with no residual
  code path assuming the pre-2026-09-01 pure-`DiagnosticMode` contract?
- [ADR-012 §1, cross-ref] Does `DiagnosticMode`'s coordinator access
  respect the shared-base-class pattern (one access mechanism on the
  base class), rather than each concrete mode reaching into
  `coordinator.py` independently?
- [ADR-013 §1/§2, Proposed status] `ADR-013` is `Proposed`, not
  `Accepted`, and has no implementation task of its own — confirm no
  code in this package actually implements ADR-013's whole-day
  comparison modes (only that the `DiagnosticMode` base class is
  *extensible enough* to support them later, which is ADR-013's stated
  validation purpose per `adr/INDEX.md`). Flag if any whole-day-mode
  code exists prematurely.
- [ADR-014 §5, cross-ref] Does `diagnostics/compare_regressions.py`
  depend on `string_computation.py` directly, with zero remaining
  direct imports from `regression/` (the edge ADR-014 replaced)?
- [ADR-000 §3/§6] Given `DiagnosticMode` lost its zero-mocking
  guarantee: does `mypy.ini`'s per-file HA-stub suppression list
  (cross-ref AUDIT-0012) correctly account for this, and do the tests
  for this package correctly use a real `hass` fixture where the ADR
  says purity was dropped, rather than still trying to zero-mock a
  module that now needs `hass`?
- **Supersession check:** `TASK-0015a-patch-1-diagnostic-fit-inputs` is
  marked `superseded` in `tasks/INDEX.md` (2026-09-01 refinement log),
  not `done`. Confirm the functionality it was meant to deliver
  (`DiagnosticSlotSample`'s missing query-FC and fit-input fields, per
  its own Goal) was actually delivered by a **later** task (patch-2 or
  after) rather than simply dropped — i.e. that "superseded" didn't
  quietly become "abandoned."

## Test-Coverage Criteria
- Given `tests/test_diagnostics_base.py` was rewritten three times
  (9 tests → 15 → 20 → 22, per the four patch tasks' Delivered
  Artifacts): do the test **names**/class structure still map cleanly
  onto current ADR-004 §5 responsibilities, or do any test names still
  describe pre-amendment behavior (a documentation-drift signal, even
  if the assertions themselves are current)?
- Is there a test that would fail if `DiagnosticMode`'s coordinator
  reference (ADR-004 §5) were accidentally made a strong reference
  instead of the `TYPE_CHECKING`-only construction-time reference the
  architecture doc describes — or is this purely a static-typing
  distinction with no runtime-observable difference to test?
- Is there a test proving the midnight/system-start cache refresh
  (ADR-004 §3) does **not** refire mid-day, e.g. asserting a call-count
  of 1 across multiple simulated ticks within the same day?
- Is there a test asserting `compare_regressions`'s extra fitting cost
  (ADR-004 §4) is skipped when a *different* mode is selected — a
  call-count/spy assertion, not just "the sensor shows different data"?
- Is there a test proving `DiagnosticSlotSample`'s query-FC and
  fit-input fields (the subject of the superseded patch-1) exist and
  are populated, confirming the supersession check above empirically?

## Consumed Context (attached to the auditor)
- `tasks/adr-summary.md`
- `adr/004-diagnostics-select-and-scatter-sensor.md` (full text,
  **including all five Amendment blocks** — do not audit against §1–§5
  as originally written without reading each amendment)
- `adr/012-provider-architecture.md` §1 (cross-ref only)
- `adr/013-whole-day-diagnostic-modes.md` (full text — for the
  not-yet-implemented check)
- `adr/014-string-computation-module.md` §5 (cross-ref only)
- `adr/000-coding-standards.md` §§3, 6
- `adr/INDEX.md` (for ADR-013's `Proposed` status confirmation)
- All files listed under Scope above
- `tasks/TASK-0015a-*.md` (all five files, including the superseded
  patch-1), `tasks/TASK-0015b-*.md`
- `tasks/INDEX.md` refinement log entries mentioning `TASK-0015a` (for
  the supersession history)
- `tasks/DEPENDENCIES.md`

## Definition of Done
- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering
  test named, or GAP explained.
- Findings written to `tasks/AUDIT-0008-diagnostics-package-findings.md`,
  with an explicit, separate section confirming or refuting the
  supersession check (this is the single highest-value finding this
  audit can produce).
- No code changes made.

## Delivered Artifacts
<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->
