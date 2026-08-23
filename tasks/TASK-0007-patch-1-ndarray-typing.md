# Task: Patch — Retrofit `NDArray[np.float64]` Typing onto `yield_correction.py`

- **Status:** done
- **Related ADRs:** [ADR-000 §4 Amendment (2026-08-22)]
- **Dependencies:** [TASK-0007-yield-corrections]

## Goal
Scenario C patch (Phase 6): TASK-0007 is `done` and not reopened. This
task retrofits ADR-000 §4's newly-amended numpy-typing convention —
`numpy.typing.NDArray[np.float64]`, never a bare `np.ndarray` — onto
every `np.ndarray`-typed signature already delivered by TASK-0007
(`yield_correction.py`). Type-annotation-only change: no runtime
behavior changes, no test assertions change.

## Acceptance Criteria
- Given `yield_correction.py`, When grepped for `np.ndarray`, Then zero
  bare occurrences remain in type position — every one is
  `NDArray[np.float64]` (the `float | np.ndarray` unions become
  `float | NDArray[np.float64]`).
- Given the existing `tests/test_yield_correction.py` suite (22 tests,
  unchanged), When run against the patched module, Then all still pass
  unmodified — this is a typing-only change.
- Given `mypy --strict`, When run against the patched file, Then it
  reports zero issues (same bar TASK-0007 already cleared, now with the
  more precise type).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/yield_correction.py`

## Definition of Done
- Tests green (unmodified `tests/test_yield_correction.py`) · docs
  updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected — `numpy.typing` ships with `numpy`, already declared)

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0007. -->
- Every symbol TASK-0007 delivered in
  `custom_components/shady/yield_correction.py` (→ task:
  TASK-0007-yield-corrections) — this patch changes their type
  annotations only; names/signatures' shapes are unchanged.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/yield_correction.py` — every `np.ndarray`
  type annotation replaced with `numpy.typing.NDArray[np.float64]`
  (`from numpy.typing import NDArray` added to imports); every
  `float | np.ndarray` union is now `float | NDArray[np.float64]`. All
  symbol names and signatures' shapes are unchanged from TASK-0007's
  original delivery — see TASK-0007's own Delivered Artifacts block for
  the full symbol list, still accurate as-is (only its `np.ndarray`
  mentions are now `NDArray[np.float64]`).
- External dependencies added: none (`numpy.typing` ships with `numpy`,
  already declared).
- CI gate: `mypy --strict` (0 issues, 23 files), `ruff check` + `ruff
  format --check` (clean), `pytest` — `tests/test_yield_correction.py`'s
  22 tests pass unmodified; full suite 106/106.
