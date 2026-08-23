# Task: Forecast Adjustment

- **Status:** done
- **Related ADRs:** [ADR-001 §2, ADR-003a §1a, ADR-003b §1b, ADR-006 §1b]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0007-yield-corrections]

## Goal
Implement `forecast_adjust.py`: given a baseline series and a slot→model
lookup, apply the fitted per-slot model, call back into
`yield_correction.py`'s reverse transform (when configured), and apply
the final output clamp — `[0, FC]`, or `[0, min(FC, inverter_limit)]`
when a clipping limit is configured — exactly once, as the *last* step.
This module has no opinion on *when* it's called or how far the input
series reaches (that's `coordinator.py`'s concern, TASK-0010).

**Note for future tasks:** ADR-006 §1b establishes the canonical
clamp-ordering rule (temperature reverse-transform → intraday correction
→ clamp, last). Intraday correction does not exist yet at this task's
time of implementation (see TASK-0013) — implement the clamp as the
final step after the reverse transform for now; TASK-0013 will need to
extend this module to insert its correction ahead of the clamp (flagged
in TASK-0013 as a shared-file dependency on this task).

## Acceptance Criteria
- Given a fitted model and a raw baseline series with no clipping/
  derating configured, When adjustment runs, Then the output is
  `predict(fc)` clamped to `[0, FC]` per slot.
- Given a string with an inverter limit configured, When adjustment runs
  and a prediction would exceed that limit, Then the output is clamped
  to `min(FC, inverter_limit)`, not just `FC` (ADR-003a §1a).
- Given a string with temperature derating configured, When adjustment
  runs, Then `yield_correction.py`'s reverse transform is applied *before*
  the final clamp, using the target slot's own expected temperature
  (ADR-003b §1b).
- Given both an inverter limit and temperature derating configured, When
  adjustment runs, Then the ordering is: reverse transform, then the
  clamp, exactly once, last (ADR-006 §1b's canonical statement).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/forecast_adjust.py`
- `tests/test_forecast_adjust.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- Zero-mocking test suite (ADR-000 §6).

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0005 and TASK-0007. -->
- `regression.base.FittedModel` Protocol from
  `custom_components/shady/regression/base.py` (→ task:
  TASK-0005-regression-fitting-pipeline,
  TASK-0005-patch-2-unclamped-predict) —
  `predict_unclamped(fc: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]`
  is the entry point this task calls: returns `(raw_adjusted,
  confidence)`, **before** the `[0, FC]` clamp, with the cold-start
  passthrough fallback already applied. `predict()` itself (the clamped
  wrapper) is *not* used here — this task owns the one final clamp
  itself, per ADR-006 §1b's canonical ordering, and calling the already-
  clamped `predict()` here would clamp before the reverse-transform runs
  (exactly the bug `TASK-0005-patch-2` exists to prevent).
- `yield_correction.apply_derate_to_prediction` from
  `custom_components/shady/yield_correction.py` (→ task:
  TASK-0007-yield-corrections, TASK-0007-patch-1-ndarray-typing) —
  `apply_derate_to_prediction(predicted_at_reference: float | NDArray[np.float64], target_cell_temperature: float | NDArray[np.float64] | None, coefficient_per_c: float | None, *, provider_already_corrects: bool = False) -> float | NDArray[np.float64]`.
  The reverse temperature-derating transform (ADR-003b §1b), applied to
  `predict_unclamped`'s raw output. No-op (returns its input unchanged)
  when `coefficient_per_c` or `target_cell_temperature` is `None`, or
  `provider_already_corrects` is set — this task does not need to
  re-implement any of those conditions itself, just pass its own
  per-string configuration through.
- ADR-000 §4 Amendment (`NDArray[np.float64]` typing convention, never a
  bare `np.ndarray`) applies to every new symbol this task delivers.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/forecast_adjust.py` →
  - `adjust_forecast(model: FittedModel, fc: NDArray[np.float64], target_cell_temperature: float | NDArray[np.float64] | None, coefficient_per_c: float | None, inverter_limit: float | None = None, *, provider_already_corrects: bool = False) -> tuple[NDArray[np.float64], NDArray[np.float64]]`
    — the full pipeline: `model.predict_unclamped(fc)` →
    `yield_correction.apply_derate_to_prediction` → `clamp_output`, in
    that order (ADR-006 §1b). Returns `(adjusted_forecast, confidence)`.
    Calls `predict_unclamped`, never `predict` — verified by a test
    whose stub `predict()` raises if called.
  - `clamp_output(adjusted: float | NDArray[np.float64], fc: NDArray[np.float64], inverter_limit: float | None = None) -> NDArray[np.float64]`
    — the one final clamp: `[0, FC]`, or `[0, min(FC, inverter_limit)]`
    when `inverter_limit` is given (ADR-003a §1a). A standalone function,
    not a reuse of `regression/base.py`'s `clamp_to_forecast` (which has
    no `inverter_limit` concept).
- `tests/test_forecast_adjust.py` → 12 zero-mocking tests (6 classes),
  one class per acceptance criterion plus two extra classes
  (`TestUsesPredictUnclampedNotPredict`, `TestClampOutputDirectly`)
  verifying the `predict_unclamped`-not-`predict` contract and
  `clamp_output`'s boundary behavior directly. Uses a hand-written
  `_StubModel` dataclass implementing `FittedModel`'s protocol (real
  object, not `Mock` — ADR-000 §6).
  `TestCombinedOrderingReverseTransformThenClamp` demonstrates the
  ordering fix concretely: a prediction below `inverter_limit`
  *pre*-transform that a cold-temperature reverse-transform pushes
  *above* it — the correct (transform-then-clamp) result and the wrong
  (clamp-then-transform) result are numerically different, and the test
  asserts against both to prove the implementation picked the right one.
- External dependencies added: none.
- **Note carried into TASK-0013** (already in this task's own spec):
  intraday correction doesn't exist yet; the clamp is the final step
  after the reverse-transform for now. TASK-0013 will need to extend
  this module to insert its own correction ahead of the clamp — a
  shared-file dependency on this task, already flagged in TASK-0013.
- **Post-delivery update (`TASK-0005-patch-3`, 2026-08-23):** the
  `_StubModel`/`_AssertingStub` test doubles in
  `tests/test_forecast_adjust.py` now inherit `regression.base.FittedModel`
  directly (it became a concrete `ABC` base class in that patch, rather
  than a `Protocol`). No assertion in this file changed — see
  `TASK-0005-patch-3`'s own Delivered Artifacts for the exact diff.
- CI gate: `mypy --strict` (0 issues, 26 files), `ruff check` + `ruff
  format --check` (clean), `pytest` — full suite 128/128 (116
  pre-existing + 12 new).
