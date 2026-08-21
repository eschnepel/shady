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
- `regression.base.FittedModel` / `.predict(fc)` from `custom_components/shady/regression/base.py` (→ task: TASK-0005-regression-fitting-pipeline)
- `yield_correction.<reverse_transform_function>` from `custom_components/shady/yield_correction.py` (→ task: TASK-0007-yield-corrections)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/forecast_adjust.py` → functions `adjust_forecast()`, `apply_forecast_adjustment()`
