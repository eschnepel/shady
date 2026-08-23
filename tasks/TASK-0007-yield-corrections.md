# Task: Optional Yield Corrections (Clipping + Temperature Derating)

- **Status:** done
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
- `custom_components/shady/yield_correction.py` →
  - `DEFAULT_CLIPPING_THRESHOLD: float` (module constant, `0.98`, ADR-003a §1)
  - `REFERENCE_TEMPERATURE_C: float` (module constant, `25.0`, ADR-003b §1)
  - `DEFAULT_MAX_UPLIFT_C: float` (module constant, `25.0`, ADR-003b §1a)
  - `exclude_clipped(actual_yield: np.ndarray, inverter_limit: float | None, clipping_threshold: float = DEFAULT_CLIPPING_THRESHOLD) -> np.ndarray`
    — ADR-003a §1/§2; marks excluded samples `NaN` (same "invalid" sentinel
    `regression/base.py`'s `build_pool` treats as zero weight); no-op
    (returns the same object) when `inverter_limit is None`.
  - `uplift_ambient_to_cell(ambient_temperature: float | np.ndarray, baseline_forecast: float | np.ndarray, baseline_rated_capacity: float, max_uplift_c: float = DEFAULT_MAX_UPLIFT_C) -> float | np.ndarray`
    — ADR-003b §1a.
  - `derate_actual_to_reference(actual_raw: float | np.ndarray, cell_temperature: float | np.ndarray | None, coefficient_per_c: float | None, *, provider_already_corrects: bool = False) -> float | np.ndarray`
    — ADR-003b §1 forward transform; no-op when `provider_already_corrects`,
    or `coefficient_per_c is None`, or `cell_temperature is None`.
  - `apply_derate_to_prediction(predicted_at_reference: float | np.ndarray, target_cell_temperature: float | np.ndarray | None, coefficient_per_c: float | None, *, provider_already_corrects: bool = False) -> float | np.ndarray`
    — ADR-003b §1b reverse transform (exact algebraic inverse of
    `derate_actual_to_reference`); same no-op conditions.
- `tests/test_yield_correction.py` → 22 zero-mocking tests, one class per
  acceptance criterion (`TestExcludeClipped`, `TestExcludeClippedNoOp`,
  `TestDerateActualToReference`, `TestReverseTransformRoundTrip`,
  `TestUpliftAmbientToCell`, `TestProviderAlreadyCorrectsFlag`,
  `TestDeratingNoOpWhenNotConfigured`).
- External dependencies added: none (`numpy` already declared, no
  `tasks/DEPENDENCIES.md` change needed).
- **Caller contract (not enforced by the module, documented in its
  docstring):** apply `exclude_clipped` before `derate_actual_to_reference`
  when preparing training data — the clipping threshold is a raw physical
  inverter limit, evaluated against the un-normalized actual-yield value.
- CI gate: `mypy --strict` (0 issues, 23 files), `ruff check` + `ruff
  format --check` (clean), `pytest` (106 passed, 22 new + 84 pre-existing).
