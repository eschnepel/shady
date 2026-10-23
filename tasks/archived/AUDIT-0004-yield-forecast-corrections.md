# Audit Task: Yield & Forecast Corrections

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** \[ADR-003a §1, ADR-003a §1a, ADR-003a §2, ADR-003b §1,
  ADR-003b §1a, ADR-003b §1b, ADR-003b §1c, ADR-003b §2, ADR-001 §2, ADR-006
  §1b\]
- **Dependencies:** [] (TASK-0007 + patch-1, TASK-0008 are `done`)
- **Origin:** TASK-0007-yield-corrections + TASK-0007-patch-1-ndarray- typing
  (clipping + temperature derating), TASK-0008-forecast- adjustment
  (`forecast_adjust.py`, which calls back into `yield_correction.py` — the
  module boundary doc calls this out as a deliberate reverse edge)

## Goal

`yield_correction.py` and `forecast_adjust.py` are grouped together because the
architecture doc documents a reverse dependency edge between them
(`forecast_adjust.py → yield_correction.py`, not the other direction the overall
chain would suggest). Verify both the forward (training-time) and reverse
(prediction-time) transforms are actually inverses of each other where ADR-003b
requires it, and that clipping exclusion (ADR-003a) and temperature derating
(ADR-003b) each remain fully optional/no-op when unconfigured.

## Scope — Source Files

- `custom_components/shady/yield_correction.py`
- `custom_components/shady/forecast_adjust.py`

## Scope — Test Files

- `tests/test_yield_correction.py`
- `tests/test_forecast_adjust.py`

## Out of Scope

- `providers/temperature.py`'s sourcing of the temperature signal (covered by
  AUDIT-0001).
- `regression/`'s `predict()`/`predict_unclamped()` that `forecast_adjust.py`
  calls (covered by AUDIT-0002).
- Intraday's use of `reverse_transformed_forecast` (covered by AUDIT-0007 for
  the intraday math itself; this audit only checks that the function it calls
  behaves as ADR-003b/ADR-006 §1b describe).

## Audit Criteria

- [ADR-003a §1] Is clipping/inverter-limit handling implemented as **exclusion**
  (drop the affected training points) rather than down-weighting or clamping the
  training input?
- [ADR-003a §1a] Does the same inverter limit that governs training exclusion
  also bound the corrected *output*, as a distinct, separate application of the
  limit (not accidentally the same code path doing double duty in a way that
  conflates the two)?
- [ADR-003a §2] Does clipping exclusion live entirely inside
  `yield_correction.py`'s pre-processing layer, with no clipping logic leaking
  into `forecast_adjust.py` or `regression/`?
- [ADR-003b §1] Is temperature correction applied **before** the PV/FC ratio is
  formed (i.e. corrects the raw yield value pre-fit), not applied inside the
  regression model itself?
- [ADR-003b §1a] Does the temperature-source hierarchy get consumed here exactly
  as `providers/temperature.py` exposes it, with no duplicate/parallel sourcing
  logic in this module?
- [ADR-003b §1b] Does `forecast_adjust.py` genuinely **reverse** the same
  normalization `yield_correction.py` applies at training time — i.e. is there a
  real mathematical inverse relationship (same coefficient, opposite direction),
  not two independently-tuned transforms that happen to look similar?
- [ADR-003b §1c] Is there a documented condition under which a baseline provider
  does **not** need this correction at all, and does the code actually skip the
  correction (not merely apply a no-op multiplier of 1.0) when that condition
  holds?
- [ADR-003b §2] Does this pre-processing layer sit **below** `regression/` in
  the dependency chain (i.e. `regression/` never imports from
  `yield_correction.py`, only the reverse)?
- [ADR-001 §2, cross-ref] Does `forecast_adjust.py` treat the regression method
  as opaque (calls `predict()`/`predict_unclamped()` uniformly regardless of
  which of the four strategies is configured), with no strategy-specific
  branching that would violate ADR-001 §2's pluggability?
- [ADR-006 §1b, cross-ref] Does `reverse_transformed_forecast` (the unclamped,
  not-yet-intraday-corrected step) have the exact documented signature and
  return both series (values and something else, per TASK-0013's Delivered
  Artifacts) needed by the intraday layer, without itself performing intraday
  correction?

## Test-Coverage Criteria

- Is there a test proving clipping exclusion (ADR-003a §1) actually removes
  points from the training pool — a count/identity check, not just an
  output-value check that could pass under down-weighting too?
- Is there a test asserting the inverter-limit output clamp (ADR-003a §1a) is a
  **separate** assertion from the training-exclusion test, proving both apply
  independently?
- Is there a differential test proving `yield_correction.py`'s forward transform
  and `forecast_adjust.py`'s reverse transform are true inverses (apply forward
  then reverse, or vice versa, and assert round-trip equality within tolerance)
  for ADR-003b §1b — or does coverage only exercise each direction in isolation?
- Is there a test for the "baseline provider doesn't need correction" condition
  (ADR-003b §1c) that asserts the correction is skipped entirely (e.g. via a
  spy/call-count), not just that output equals input by coincidence?
- Is there a test that would fail if `forecast_adjust.py` started branching on
  regression strategy (ADR-001 §2 cross-ref) — e.g. run the same scenario across
  all four strategies and assert the call pattern into `regression/` is
  identical?

## Consumed Context (attached to the auditor)

- `tasks/adr-summary.md`
- `adr/003a-inverter-clipping-exclusion.md` (full text)
- `adr/003b-temperature-derating-correction.md` (full text)
- `adr/001-empirical-shading-model.md` §2 (cross-ref only)
- `adr/006-intraday-deviation-correction.md` §1b (cross-ref only)
- All files listed under Scope above
- `tasks/TASK-0007-*.md`, `tasks/TASK-0008-*.md`
- `tasks/DEPENDENCIES.md`

## Definition of Done

- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering test
  named, or GAP explained.
- Findings written to `tasks/AUDIT-0004-yield-forecast-corrections-findings.md`.
- No code changes made.

## Delivered Artifacts

- `tasks/AUDIT-0004-yield-forecast-corrections-findings.md` → 10/10 Audit
  Criteria PASS. Test-Coverage: 4/5 COVERED (two exceeding the original bar with
  spy/differential-ordering tests), 1 minor GAP (no test parametrizes
  forecast_adjust over all four real regression strategies — relies on
  hand-built stubs). No code changes made.
