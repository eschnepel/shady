# Task: Optional Yield Corrections (Clipping + Temperature Derating)

- **Status:** todo
- **Related ADRs:** [ADR-003a §1, ADR-003a §1a, ADR-003a §2, ADR-003b §1, ADR-003b §1a, ADR-003b §1b, ADR-003b §1c]
- **Dependencies:** []

## Goal
Implement `yield_correction.py`: inverter clipping-exclusion
(training-time sample exclusion, no output-clamp logic — that lives in
`forecast_adjust.py`, TASK-0008), and temperature-derating forward
(25°C normalization) + reverse transforms, the ambient→cell uplift
formula, and the provider-already-corrects skip flag. Pure functions of
numbers in, numbers out — `cell_temperature` values are supplied by the
caller; this task does not need a live temperature provider to test its
own unit tests.

## Acceptance Criteria
- Given a historical sample whose actual yield is at or above
  `clipping_threshold` (default 0.98) of a configured inverter limit,
  When training data is prepared, Then that sample is excluded entirely
  (not downweighted) from the returned training set (ADR-003a §1).
- Given no inverter limit configured for a string, When clipping
  exclusion runs, Then it is a no-op (input series returned unchanged,
  ADR-003a §2).
- Given a raw actual-yield sample and a cell temperature, When the
  forward transform runs, Then `actual_corrected = actual_raw / (1 +
  coefficient_per_c * (cell_temperature - 25))` exactly (ADR-003b §1).
- Given a 25°C-equivalent prediction and a target-slot temperature, When
  the reverse transform runs, Then it is the exact algebraic inverse of
  the forward transform (round-trip test: forward then reverse recovers
  the original value within floating-point tolerance).
- Given ambient/weather-tier inputs at `baseline_forecast_i = 0` and at
  `baseline_forecast_i = baseline_rated_capacity`, When the uplift
  formula runs, Then it yields `0` uplift and the full `max_uplift_c`
  respectively (ADR-003b §1a boundary conditions).
- Given the provider-already-corrects flag is `true`, When forward/reverse
  are invoked, Then both are skipped entirely (input returned unchanged),
  not just one side (ADR-003b §1c).
- Given no temperature coefficient/source configured for a string, When
  derating runs, Then it is a no-op, matching the same "no-op when not
  configured" pattern as clipping (ADR-003b §2).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/yield_correction.py`
- `tests/test_yield_correction.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- Zero-mocking test suite (ADR-000 §6): no HA imports.

## Consumed Interfaces
<!-- None — this task has no dependencies. -->

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
