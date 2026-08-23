# Task: Patch — Expose `predict_unclamped()` (Unclamped Prediction Step)

- **Status:** done
- **Related ADRs:** [ADR-006 §1b, ADR-001 §2, ADR-003b §1b]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline]

## Goal
Scenario C patch (Phase 6): TASK-0005 is `done` and not reopened.
Discovered while implementing TASK-0008: every strategy's `predict()`
applies the `[0, FC]` clamp **unconditionally, internally** — a design
decision TASK-0005 made without ADR-006 in its context package (it was
never in TASK-0005's Related ADRs). ADR-006 §1b's canonical ordering
requires the temperature reverse-transform (ADR-003b §1b) to run
**before** the one true final output clamp, on the model's raw,
unclamped value — but `predict()` as delivered clamps first, so there is
no unclamped value left for `forecast_adjust.py` (TASK-0008) to
reverse-transform correctly (clamping first can zero out or cap a value
the reverse-transform then can't recover — see INDEX.md's refinement log
entry for a worked example).

This task introduces the missing intermediate processing step: a new
`predict_unclamped()` method, sitting between each strategy's raw model
evaluation (including the existing cold-start passthrough, which is
retained — it is a business-logic fallback, not the ADR-006 §1b clamp)
and the `[0, FC]` clamp. `predict()` becomes a thin wrapper —
`clamp_to_forecast(*predict_unclamped(fc))` — so its own behavior,
signature, and every existing test assertion about it are unchanged.

## Acceptance Criteria
- Given each of the four strategies' `FittedModel.predict_unclamped(fc)`,
  When called, Then it returns `(raw_adjusted, confidence)` — the same
  value `predict()` used to compute internally right before its
  `clamp_to_forecast` call, now returned directly, unclamped (ADR-006
  §1b).
- Given `predict_unclamped(fc)` on a slot with confidence <= 0
  (cold-start), When called, Then it still returns `fc` unmodified (the
  existing passthrough fallback runs inside `predict_unclamped`, not
  only inside `predict`) — this is a business-logic default, not the
  ADR-006 §1b clamp, and is preserved exactly.
- Given `predict(fc) == (clamp_to_forecast(*predict_unclamped(fc)[:1], fc), predict_unclamped(fc)[1])`
  for all four strategies, When compared directly, Then they are
  numerically identical — `predict()`'s own contract and every existing
  `tests/test_regression.py` assertion about it are unaffected by this
  refactor.
- Given the existing `tests/test_regression.py` suite (16 tests,
  unmodified), When run against the patched modules, Then all still
  pass — this task changes internal structure, not `predict()`'s
  observable behavior.
- Given `mypy --strict`, When run against the patched files, Then it
  reports zero issues.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/regression/base.py` (the `FittedModel`
  Protocol gains `predict_unclamped`)
- `custom_components/shady/regression/linear.py`
- `custom_components/shady/regression/wls2.py`
- `custom_components/shady/regression/wls3.py`
- `custom_components/shady/regression/kernel.py`

## Definition of Done
- Tests green (unmodified `tests/test_regression.py`) · docs updated ·
  no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0005. -->
- Every symbol TASK-0005 delivered in
  `custom_components/shady/regression/*.py` (→ task:
  TASK-0005-regression-fitting-pipeline) — `clamp_to_forecast`,
  `passthrough_where_no_confidence`, `evaluate_polynomial`,
  `fit_weighted_polynomial`, `SamplePool`, `FittedModel` Protocol, and
  each strategy's `<Name>FittedModel` dataclass + `fit()`. This patch
  adds `predict_unclamped` alongside them; every other name/signature is
  unchanged.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/regression/base.py` → `FittedModel` Protocol
  gains `predict_unclamped(self, fc: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]`
  alongside the existing `predict`. `clamp_to_forecast` and
  `passthrough_where_no_confidence` are unchanged (still exported, still
  used — now by `predict_unclamped` instead of `predict` directly).
- `custom_components/shady/regression/linear.py` → `LinearFittedModel.predict_unclamped`
  added; `predict` is now `clamp_to_forecast(*predict_unclamped(fc)), confidence` —
  a thin wrapper, behaviorally identical to before.
- `custom_components/shady/regression/wls2.py` → `Wls2FittedModel.predict_unclamped`
  added, `predict` refactored identically.
- `custom_components/shady/regression/wls3.py` → `Wls3FittedModel.predict_unclamped`
  added, `predict` refactored identically.
- `custom_components/shady/regression/kernel.py` → `KernelFittedModel.predict_unclamped`
  added (the locally-weighted-average computation, including its own
  per-query cold-start fallback `np.where(total_weight > 0, weighted_average, fc)`,
  moved here verbatim); `predict` refactored identically.
- External dependencies added: none.
- **Behavior guarantee:** `predict()`'s signature, return values, and
  every existing `tests/test_regression.py` assertion about it are
  unchanged — verified by re-running that 16-test suite unmodified.
- CI gate: `mypy --strict` (0 issues, 24 files), `ruff check` + `ruff
  format --check` (clean), `pytest` — `tests/test_regression.py`'s 16
  tests pass unmodified; full suite 116/116.
