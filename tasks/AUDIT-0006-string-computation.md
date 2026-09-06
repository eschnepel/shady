# Audit Task: String Computation Module

- **Status:** todo
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** [ADR-014 §1, ADR-014 §2, ADR-014 §3, ADR-014 §4, ADR-014 §5, ADR-014 §6, ADR-000 §3, ADR-000 §5, ADR-000 §6]
- **Dependencies:** [] (TASK-0017 is `done`)
- **Origin:** TASK-0017-string-computation-module — a mid-project
  refactor (ADR-014 was "discovered while scoping TASK-0015b", per
  `adr/INDEX.md`) that relocated logic **out of** `coordinator.py` and
  **out of** duplicated code in `diagnostics/`. This module exists
  specifically to eliminate duplication — the audit's main question is
  whether that duplication actually stayed eliminated.

## Goal
Verify `string_computation.py` genuinely holds the single, shared
implementation of per-string fit/predict logic that ADR-014 §2 claims
moved here "verbatim in behavior" from `coordinator.py`, that
`coordinator.py` and `diagnostics/compare_regressions.py` both call this
module rather than each keeping their own copy, and that the module
itself stays pure per ADR-014 §1.

## Scope — Source Files
- `custom_components/shady/string_computation.py`

## Scope — Test Files
- `tests/test_string_computation.py`

## Out of Scope
- `coordinator.py`'s own logic and call sites (covered by AUDIT-0005) —
  this audit checks the shared module itself, and flags (but does not
  verify in depth) whether `coordinator.py`'s calls look consistent.
- `diagnostics/compare_regressions.py`'s consumption (covered by
  AUDIT-0008) — same relationship as above, in the other direction.

## Audit Criteria
- [ADR-014 §1] Is the module responsibility genuinely string-shaped and
  slot-count-agnostic — does it work on an arbitrary slot count with no
  hardcoded 288 (24h × 12 slots/h) or similar constant baked in?
- [ADR-014 §1] Is the module pure — no `homeassistant.*` import, no
  `hass` parameter, matching the "no new `hass`-mocking" quality this
  ADR claims for the relocation?
- [ADR-014 §2] For the logic that "moves here, verbatim in behavior,
  from `coordinator.py`" — is it actually verbatim (same algorithm,
  same edge-case handling), or did the relocation introduce any
  behavioral change (intentional or not) that isn't documented as an
  amendment?
- [ADR-014 §3] Do `fit_string_model` and `predict_string_forecast`
  exist with the documented responsibilities, and do they compose the
  underlying `regression/`, `yield_correction.py`, and
  `forecast_adjust.py` calls directly (per the module-boundary doc's
  note that this module "also reads regression/, forecast_adjust.py,
  yield_correction.py directly") rather than going through
  `coordinator.py` as an intermediary?
- [ADR-014 §4] Does `coordinator.py`'s role, as observed from this
  module's call sites, actually look "narrower" — i.e. does
  `coordinator.py` call into `fit_string_model`/`predict_string_forecast`
  rather than reimplementing any part of them locally?
- [ADR-014 §5] Does `diagnostics/compare_regressions.py` depend on this
  module directly (the new `diagnostics --> string_computation` edge
  replacing the old `diagnostics --> regression` edge) — confirm there
  is no leftover direct `diagnostics/` → `regression/` import that
  should have been removed by this relocation.
- [ADR-014 §6] Does the actual code structure support the ADR's own
  stated rationale for *not* inlining this a third time or putting it in
  `coordinator.py` — i.e., is there genuinely only one implementation of
  this logic in the whole codebase, not three?

## Test-Coverage Criteria
- Is there a test that would fail if `coordinator.py` reintroduced a
  local copy of `fit_string_model`'s logic instead of calling this
  module (a duplication regression, not just a correctness regression)?
- Is there a test proving `fit_string_model`/`predict_string_forecast`
  behave identically to what `coordinator.py` did *before* TASK-0017 —
  i.e. does `tests/test_coordinator.py` (updated by TASK-0017 per its
  Delivered Artifacts) still assert the same observable outcomes it did
  pre-refactor, proving the "verbatim in behavior" claim (ADR-014 §2)
  empirically rather than just by inspection?
- Do the 14 tests (per TASK-0017's Delivered Artifacts) still map
  one-to-one onto this module's public functions, or has the module
  grown public surface since TASK-0017 landed that has no corresponding
  test class?
- Is there a test exercising a non-default slot count (ADR-014 §1's
  slot-count-agnostic claim), or does every test implicitly assume the
  project's actual 5-minute/288-slot grid?

## Consumed Context (attached to the auditor)
- `tasks/adr-summary.md`
- `adr/014-string-computation-module.md` (full text)
- `adr/000-coding-standards.md` §§3, 5, 6
- All files listed under Scope above
- `tasks/TASK-0017-*.md` (Delivered Artifacts block, and its list of
  which other test files it touched, as a cross-check list only)
- `tasks/DEPENDENCIES.md`

## Definition of Done
- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering
  test named, or GAP explained.
- Findings written to `tasks/AUDIT-0006-string-computation-findings.md`.
- No code changes made.

## Delivered Artifacts
<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->
