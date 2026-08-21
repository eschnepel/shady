# Task: Regression Fitting Pipeline

- **Status:** todo
- **Related ADRs:** [ADR-001 §2, ADR-001 §2a, ADR-001 §3, ADR-001 §3a, ADR-011 §1, ADR-011 §2, ADR-011 §3, ADR-008 §1]
- **Dependencies:** []

## Goal
Implement the `regression/` package: the shared `base.py` protocol
(`fit(samples) -> FittedModel`, `predict(fc) -> (adjusted_forecast,
confidence)`), sample weighting (`magnitude_weight_i`, `time_weight_i`),
neighbor-regime exclusion/rescale, and all four pluggable strategies
(`linear`, `kernel`, `wls2`, `wls3`) — operating on already-assembled,
padded `numpy` pool arrays (batched per ADR-008 §1, never naive
per-slot). No `cache.py` coupling — pools are passed in.

## Acceptance Criteria
- Given a shared scenario fixture with a hard shading edge crossing
  mid-window, When each of the four strategies fits and predicts on it,
  Then every strategy's output satisfies `0 <= predicted <= FC` for
  every sample (ADR-000 §6 invariant).
- Given a scenario with samples at or above a clipping-style ceiling,
  When `wls2`/`wls3` predict at an out-of-training-range `FC`, Then the
  output still respects the same clamp invariant (extrapolation safety,
  ADR-001 §2).
- Given a pool with near-zero-`FC` samples (sunrise/sunset), When weights
  are computed, Then `magnitude_weight_i` smoothly approaches (but is
  only exactly `0` at) `FC_i == 0` — continuous, not a hard cutoff
  (ADR-001 §2).
- Given a center slot and a neighbor slot whose median `PV/FC` ratio
  deviates beyond `neighbor_fitting_cutoff` (default 0.25), When the pool
  is built, Then that neighbor's entire series is hard-excluded
  (`time_weight_i` forced to 0), not merely downweighted (ADR-011 §2).
- Given `neighbor_fitting_cutoff = -1%` (the rescale sentinel), When the
  same deviating neighbor is processed, Then it is rescaled to the center
  slot's median and retained, not excluded (ADR-011 §3).
- Given confidence is computed for the same pool across all four
  strategies, When compared, Then confidence is identical regardless of
  which strategy produced the point estimate (ADR-001 §2 — confidence is
  method-independent, pool-weight-sum only).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/regression/__init__.py`
- `custom_components/shady/regression/base.py`
- `custom_components/shady/regression/linear.py`
- `custom_components/shady/regression/kernel.py`
- `custom_components/shady/regression/wls2.py`
- `custom_components/shady/regression/wls3.py`
- `tests/test_regression_*.py` (shared scenario fixtures across all four)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- `numpy>=1.26.0` used per ADR-008 §1 (already declared in
  `manifest.json`/`pyproject.toml` — confirm, don't re-add)
- Zero-mocking test suite (ADR-000 §6), shared scenario fixtures reused
  across all four strategies rather than bespoke data per strategy.

## Consumed Interfaces
<!-- None — this task has no dependencies. -->

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
