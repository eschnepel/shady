# Audit Task: Regression Package (Round 2)

- **Status:** review
- **Group:** `custom_components/shady/regression/*.py` (`base.py`, `kernel.py`,
  `linear.py`, `wls2.py`, `wls3.py`)
- **Related ADRs:** [ADR-001 §2/§2a/§3/§3a, ADR-008 §1, ADR-011, ADR-000 §3/§4]
- **Source Tasks:** \[TASK-0005-regression-fitting-pipeline,
  TASK-0005-patch-1-ndarray-typing, TASK-0005-patch-2-unclamped-predict,
  TASK-0005-patch-3-consolidate-predict, TASK-0005-patch-4-recency-weight,
  TASK-0005-patch-5-optional-magnitude-weight,
  TASK-0030-regression-correction-coverage-additions\]

## Scope

Re-audits round 1's `AUDIT-0002-regression-package` finding. `regression/*.py`
itself has zero byte changes since round 1 (confirmed via
`git diff --stat f7fcef8 HEAD`). This pass confirms the one coverage gap round 1
found is closed, and separately traces this package's role in an ADR-000 §3
diagram discrepancy whose primary write-up belongs to a different group.

## Findings — Code Logic vs. ADRs

- No deviations found in `regression/*.py` itself. `FittedModel`'s shared base
  (`predict`/`predict_unclamped`), the four pluggable strategies
  (`kernel`/`linear`/`wls2`/`wls3`), `build_pool`'s slot-partitioned pool
  construction (ADR-001 §3a) with `recency_weight_i`/optional
  `magnitude_weight_i` (ADR-011), and the unified confidence definition (ADR-001
  §2) all match round 1's confirmed reading — re-spot-checked, unchanged.
- **Cross-reference, primary write-up in
  `AUDIT-0016-yield-forecast- corrections`:** ADR-000 §3's module-dependency
  diagram draws an edge `regression --> yield_correction`, implying
  `regression/*.py` imports `yield_correction.py`. This is false — a repo-wide
  `grep -n "^from \."` / `"^import \."` across all five `regression/*.py` files
  shows none of them import anything outside the `regression/` package itself
  (only `.base` imports within the package). The regression package has no
  coupling to `yield_correction.py` at all, direct or otherwise; the actual
  caller that prepares training data through both `regression/` and
  `yield_correction.py` is `string_computation.py`
  (`string_computation.py:54-56`, importing both `regression` and
  `.yield_correction`). See `AUDIT-0016` for the full finding and proposed fix —
  not repeated here to avoid duplicating the same finding under two groups, per
  this round's own stated cross-referencing convention.

## Findings — Test Coverage vs. ADRs

- **Round-1 item — `predict_unclamped()` direct coverage (RESOLVED).**
  `AUDIT-0002` found no test in `tests/test_regression.py` called
  `predict_unclamped()` directly on a real strategy. `TASK-0030` added it —
  confirmed present: `tests/test_regression.py:571-616`
  (`# -- AUDIT-0002/TASK-0030 item 1: predict_unclamped() called directly --`),
  asserting `predict_unclamped` returns the model's real raw value distinct from
  the clamped `predict()` result, parametrized across all four strategies.
  **PASS.**
- `tests/test_regression.py` re-run live as part of the full suite this session
  — passing (445/445 total, see `tasks/AUDIT-INDEX.md`).

## Open Questions

None.

## Definition of Done (for Phase 8)

- N/A — the one active finding in this group (the
  `regression --> yield_correction` diagram edge) is tracked and fixed under
  `AUDIT-0016`, not here, to avoid a duplicate fix touching the same diagram
  text from two audit tasks.

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8 — not applicable, no independent fix
     scheduled under this task; see AUDIT-0016. -->
