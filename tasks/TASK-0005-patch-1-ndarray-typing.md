# Task: Patch — Retrofit `NDArray[np.float64]` Typing onto `regression/`

- **Status:** done
- **Related ADRs:** [ADR-000 §4 Amendment (2026-08-22)]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline]

## Goal
Scenario C patch (Phase 6): TASK-0005 is `done` and not reopened. This
task retrofits ADR-000 §4's newly-amended numpy-typing convention —
`numpy.typing.NDArray[np.float64]`, never a bare `np.ndarray` — onto
every `np.ndarray`-typed signature/attribute already delivered by
TASK-0005 (`regression/base.py`, `linear.py`, `wls2.py`, `wls3.py`,
`kernel.py`). Type-annotation-only change: no runtime behavior changes,
no test assertions change.

## Acceptance Criteria
- Given `regression/base.py`, `linear.py`, `wls2.py`, `wls3.py`,
  `kernel.py`, When grepped for `np.ndarray`, Then zero bare occurrences
  remain in type position (parameter types, return types, `@dataclass`
  attributes) — every one is `NDArray[np.float64]`.
- Given the existing `tests/test_regression.py` suite (16 tests, unchanged),
  When run against the patched module, Then all still pass unmodified —
  this is a typing-only change.
- Given `mypy --strict`, When run against the patched files, Then it
  reports zero issues (same bar TASK-0005 already cleared, now with the
  more precise type).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/regression/base.py`
- `custom_components/shady/regression/linear.py`
- `custom_components/shady/regression/wls2.py`
- `custom_components/shady/regression/wls3.py`
- `custom_components/shady/regression/kernel.py`

## Definition of Done
- Tests green (unmodified `tests/test_regression.py`) · docs updated ·
  no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected — `numpy.typing` ships with `numpy`, already declared)

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0005. -->
- Every symbol TASK-0005 delivered in `custom_components/shady/regression/*.py`
  (→ task: TASK-0005-regression-fitting-pipeline) — this patch changes
  their type annotations only; names/signatures' shapes are unchanged.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/regression/base.py`, `linear.py`, `wls2.py`,
  `wls3.py`, `kernel.py` — every `np.ndarray` type annotation replaced
  with `numpy.typing.NDArray[np.float64]` (`from numpy.typing import
  NDArray` added to each file's imports). All symbol names, signatures'
  *shapes*, and runtime behavior are unchanged from TASK-0005's original
  delivery — see TASK-0005's own Delivered Artifacts block for the full
  symbol list, still accurate as-is.
- **One real typing fix beyond the mechanical substitution:**
  `regression/base.py`'s two private helpers, `_magnitude_weight` and
  `_median_ratio`, take a `valid_mask` parameter that is genuinely
  boolean (`~np.isnan(...) & ~np.isnan(...)`), not `float64` — a blanket
  `np.ndarray` → `NDArray[np.float64]` substitution would have mistyped
  it. Both are now `valid_mask: NDArray[np.bool_]`. `mypy --strict`
  caught this immediately (`Unsupported operand types for &` /
  `incompatible type` on the two call sites) — exactly the kind of
  error bare `np.ndarray` typing was masking, and the concrete
  motivation for this patch beyond stylistic consistency.
- External dependencies added: none (`numpy.typing` ships with `numpy`,
  already declared).
- CI gate: `mypy --strict` (0 issues, 23 files), `ruff check` + `ruff
  format --check` (clean), `pytest` — `tests/test_regression.py`'s 16
  tests pass unmodified; full suite 106/106.
