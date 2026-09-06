# Audit Task: Regression Package

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** [ADR-001 §2, ADR-001 §2a, ADR-001 §3, ADR-001 §3a, ADR-001 §4a, ADR-011 §1, ADR-011 §2, ADR-011 §3, ADR-008 §1, ADR-000 §4 Amendment (2026-08-22), ADR-003c §2, ADR-006 §1b]
- **Dependencies:** [] (TASK-0005 and its five patches are `done`)
- **Origin:** TASK-0005-regression-fitting-pipeline + TASK-0005-patch-1
  through TASK-0005-patch-5 (five patches against one package —
  highest patch-count of any module in the project; prime drift-risk
  candidate for this audit)

## Goal
`regression/` was extended five separate times after its initial build
(typing retrofit, unclamped predict, predict consolidation, recency
weight, optional magnitude weight). Verify the accumulated result still
matches ADR-001's regression-method decision and ADR-011's temporal
smoothing/exclusion decision as a whole, not just patch-by-patch, and
that no earlier patch's behavior was silently undone by a later one.

## Scope — Source Files
- `custom_components/shady/regression/__init__.py`
- `custom_components/shady/regression/base.py`
- `custom_components/shady/regression/linear.py`
- `custom_components/shady/regression/wls2.py`
- `custom_components/shady/regression/wls3.py`
- `custom_components/shady/regression/kernel.py`

## Scope — Test Files
- `tests/test_regression.py`

## Out of Scope
- `forecast_adjust.py`'s use of `predict()`/`predict_unclamped()`
  (covered by AUDIT-0004).
- `string_computation.py`'s call sites into this package (covered by
  AUDIT-0006).

## Audit Criteria
- [ADR-001 §2] Is the regression method a pluggable, globally-selected
  strategy — one config value selecting among `linear`/`wls2`/`wls3`/
  `kernel` — rather than a per-string or hardcoded choice?
- [ADR-001 §2] Is `wls2` actually the default, per the ADR's stated
  rationale (captures diffuse/direct-light curvature without `wls3`'s
  extrapolation risk)?
- [ADR-001 §2a] Does "good" fit quality get evaluated against the daily
  total, not individual slots, anywhere this package exposes a
  goodness-of-fit or diagnostic value?
- [ADR-001 §3] Is there one model per configured string (not one global
  model, not one per inverter)?
- [ADR-001 §3a] Is the slot partitioning exactly one model per
  5-minute-of-day slot, on the stated 00:00…23:55 grid?
- [ADR-001 §4a] Does `build_pool` apply `recency_weight_i` (TASK-0005-
  patch-4) using the documented weighting formula/shape, and is it
  actually threaded into the fit rather than computed and discarded?
- [ADR-011 §1] Does the smoothing implementation widen each slot's
  *training data* (wider window of days/neighbor slots feeding the fit),
  not the output (no post-hoc smoothing of predictions)?
- [ADR-011 §2] Is a whole neighbor series excluded at a shading boundary
  per the documented condition, not partially down-weighted (that's §3,
  a documented alternative — confirm which one shipped)?
- [ADR-011 §3] If `neighbor_fitting_cutoff = -1%` rescale-instead-of-
  exclude is present, confirm it's genuinely an alternative path
  (config-gated) and not silently replacing §2's exclusion as the only
  behavior.
- [ADR-008 §1] Is the batching genuinely `numpy`-vectorized across the
  full slot sweep for **both** `fit()` and `predict()`, for all four
  strategies — not just `linear`/`wls2`, and not a Python-level loop
  dressed up with numpy types?
- [ADR-000 §4 Amendment] Is every `numpy.ndarray`-valued type annotated
  `numpy.typing.NDArray[np.float64]`, with zero bare `np.ndarray`
  annotations remaining anywhere in this package (the amendment that
  TASK-0005-patch-1 retrofitted)?
- [ADR-003c §2, cross-ref] Does `build_pool`'s optional
  `magnitude_weight_i` (TASK-0005-patch-5) default to a no-op (disabled)
  when the caller doesn't opt in, so ADR-001's core behavior is
  unaffected for callers that predate ADR-003c?
- [ADR-006 §1b, cross-ref] Does `predict_unclamped()` (TASK-0005-patch-2)
  exist on every one of the four `FittedModel` implementations via the
  consolidated base class (TASK-0005-patch-3), with identical semantics
  across strategies (same clamping omitted, nothing else different)?

## Test-Coverage Criteria
- Is there a test proving `recency_weight_i` (ADR-001 §4a) actually
  changes the fit result versus an unweighted pool — a differential
  test, not just "the parameter can be passed"?
- Is there a test proving `magnitude_weight_i`'s default is a true no-op
  (byte-identical result to not passing it at all), not merely "doesn't
  crash when omitted"?
- Is there a test for the neighbor-exclusion boundary condition (ADR-011
  §2) that would fail if the exclusion silently became a down-weight?
- Is there a test asserting `NDArray[np.float64]` typing itself (mypy
  --strict is a CI gate per ADR-000 §1, not a pytest assertion) — note
  whether this criterion is properly a test-coverage gap by design
  (enforced by tooling, not pytest) and cross-reference AUDIT-0012.
- Is there a test that would fail if `predict_unclamped()` on any one of
  the four strategies silently regressed to clamped output?
- Do all nine documented test classes (per TASK-0005's Delivered
  Artifacts: 16 zero-mocking tests, 9 classes) still exist unmodified in
  name/intent, or did a later patch quietly rename/merge them in a way
  that could mask which ADR clause each protects?

## Consumed Context (attached to the auditor)
- `tasks/adr-summary.md`
- `adr/001-empirical-shading-model.md` §§2, 2a, 3, 3a, 4a (full text)
- `adr/011-temporal-smoothing-and-neighbor-exclusion.md` (full text)
- `adr/008-numpy-backend-and-cache-array-accessor.md` §1
- `adr/000-coding-standards.md` §4 + its 2026-08-22 Amendment
- `adr/003c-temperature-forecast-via-learned-model.md` §2 (cross-ref only)
- `adr/006-intraday-deviation-correction.md` §1b (cross-ref only)
- All files listed under Scope above
- `tasks/TASK-0005-*.md` (all six files) for what each patch claims to
  have changed, as a diff-history reference — not as ground truth
- `tasks/DEPENDENCIES.md`

## Definition of Done
- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering
  test named, or GAP explained.
- Findings written to `tasks/AUDIT-0002-regression-package-findings.md`.
- No code changes made.

## Delivered Artifacts
- `tasks/AUDIT-0002-regression-package-findings.md` → 13/13 Audit
  Criteria PASS (or correctly N/A to this package), including one
  self-correction to this task's own Criterion #12 wording. 4 of 6
  Test-Coverage Criteria COVERED; 1 GAP by design (mypy typing,
  cross-ref AUDIT-0012); 1 genuine GAP (`predict_unclamped()` untested
  directly within `test_regression.py`, though incidentally exercised
  in a different audit group's test file). No code changes made.
