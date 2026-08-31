# Task: `string_computation.py` — Shared Per-String Fit/Predict Module

- **Status:** done
- **Related ADRs:** [ADR-014, ADR-000 §3/§5/§6 (amended 2026-08-31)]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0007-yield-corrections, TASK-0008-forecast-adjustment, TASK-0010-coordinator-recalibration-recompute-push, TASK-0013-intraday-deviation-correction, TASK-0014-temperature-forecast-learned-model]

## Goal
Extract the pure per-string fit/predict computation currently embedded
as private `coordinator.py` methods into a new pure module,
`string_computation.py` (ADR-014): the `REGRESSION_STRATEGIES` registry
and `apply_training_corrections` (moved, no behavior change), plus two
new functions, `fit_string_model` and `predict_string_forecast`, that
each factor out a pattern currently inlined twice in `coordinator.py`.
This is a **prerequisite discovered mid-implementation** (Scenario B)
while scoping `TASK-0015b-diagnostics-select-and-scatter-sensors`:
`CompareRegressionsMode.extra_fit()` needs this exact computation, and
`DiagnosticMode`'s "no `cache.py`, no `homeassistant.*`" purity rule
means it cannot reach into `coordinator.py`'s instance methods to reuse
it. See `tasks/INDEX.md`'s refinement log for the full discovery
context and ADR-014 for the complete design rationale.

## Acceptance Criteria
- Given `string_computation.py`, When imported, Then it has no
  `cache.py` import and no `homeassistant.*` import anywhere (ADR-000
  §3's pure tier).
- Given `apply_training_corrections`, When called with the same
  `fc_by_offset`/`pv_by_offset`/`temperature_by_offset`/config-flag
  arguments `coordinator.py`'s own `_apply_training_corrections`
  previously computed from, Then it returns byte-identical results —
  a pure relocation, not a rewrite.
- Given `fit_string_model(fc_by_offset, corrected_pv_by_offset,
  smoothing_radius, neighbor_fitting_cutoff, recency_decay_max, method,
  apply_magnitude_weight=...)`, When called for each of `const.py`'s
  four `REGRESSION_METHODS`, Then it returns the same `FittedModel`
  each corresponding `regression/<method>.fit(build_pool(...))` call
  would have produced directly.
- Given `predict_string_forecast(model, fc, target_cell_temperature,
  coefficient_per_c, provider_already_corrects, inverter_limit)`, When
  called, Then it returns exactly
  `clamp_output(reverse_transformed_forecast(model, fc,
  target_cell_temperature, coefficient_per_c,
  provider_already_corrects=provider_already_corrects)[0], fc,
  inverter_limit)` — the same two-step sequence in the same order, now
  behind one call that cannot be chained in the wrong order.
- Given either function above, When called with `fc`/pool arrays shaped
  for a single slot (`n_slots=1`) instead of a full day (288), Then it
  behaves identically in kind — no code path assumes a specific
  `n_slots` (ADR-014 §1's slot-count-agnostic requirement, exercised
  here for the first time by a non-`coordinator.py` shape, ahead of
  `TASK-0015b`'s real single-slot caller).
- Given `coordinator.py` after refactoring, When `_fit_string`/
  `_fit_temperature_string` run, Then they produce the exact same
  outputs as before this task (no behavior change) by delegating to
  `string_computation.apply_training_corrections`/`fit_string_model`
  internally, and `_apply_training_corrections` no longer exists as a
  `coordinator.py` method. `_predict_day_basis`/`_clamp_basis` are
  **not** required to change call shape — they already call
  `forecast_adjust.py` directly with no duplication to remove (exactly
  one caller needs their particular split-then-multi-day-clamp shape,
  since intraday correction, ADR-006 §1b, must sit between the two
  steps); `string_computation.predict_string_forecast`'s combined
  fit-and-clamp shape exists for `diagnostics/`'s benefit (§4/§5),
  which always wants one already-clamped, single-slot value with no
  correction step to insert in between.
- Given the existing `tests/test_coordinator.py`,
  `tests/test_coordinator_intraday.py`, and
  `tests/test_coordinator_temperature_forecast.py` suites, When run
  against the refactored `coordinator.py`, Then all pass unmodified —
  confirms the refactor is behavior-preserving (neither file is a
  Consumed Interface anywhere else, so this is ordinary same-module
  refactoring, not a Scenario C interface break).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/string_computation.py` (new)
- `custom_components/shady/coordinator.py` (extended/shrunk — delegates
  to the new module; `_apply_training_corrections` removed;
  `_REGRESSION_STRATEGIES` removed in favor of the new module's
  exported `REGRESSION_STRATEGIES`)
- `tests/test_string_computation.py` (new, zero-mocking)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- Full existing suite (309 tests as of `TASK-0015a`, plus this task's
  own new tests) passes with zero regressions.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0005, TASK-0007, TASK-0008, TASK-0010,
     TASK-0013, TASK-0014. -->
- `regression.base.build_pool`, `regression.base.FittedModel`,
  `regression.{linear,kernel,wls2,wls3}.fit` from
  `custom_components/shady/regression/` (→ task: TASK-0005 and its
  patches)
- `yield_correction.exclude_clipped`, `yield_correction
  .derate_actual_to_reference`, `yield_correction
  .uplift_ambient_to_cell` from `custom_components/shady/yield_correction.py`
  (→ task: TASK-0007 and its patch)
- `forecast_adjust.reverse_transformed_forecast`,
  `forecast_adjust.clamp_output` from
  `custom_components/shady/forecast_adjust.py` (→ task: TASK-0008)
- `coordinator.py`'s private `_apply_training_corrections`,
  `_fit_string`, `_fit_temperature_string`, `_predict_day_basis`,
  `_clamp_basis`, `_REGRESSION_STRATEGIES` (the logic being relocated
  out of) from `custom_components/shady/coordinator.py` (→ tasks:
  TASK-0010, TASK-0013, TASK-0014) — private, not a Delivered-Artifacts-
  declared interface; referenced here only so this task's worker knows
  exactly which existing code it is extracting from and must keep
  behavior-identical to.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/string_computation.py` (new, pure — no
  `cache.py`/`homeassistant.*` import, confirmed by
  `TestModulePurity.test_no_cache_or_homeassistant_import`):
  - `REGRESSION_STRATEGIES: dict[str, Any]` — `{"linear": linear,
    "kernel": kernel, "wls2": wls2, "wls3": wls3}`, exported (moved from
    `coordinator.py`'s private `_REGRESSION_STRATEGIES`, now removed).
  - `apply_training_corrections(fc_by_offset, pv_by_offset,
    temperature_by_offset, temperature_tier, *, converter_limit_w,
    clipping_threshold, coefficient_per_c, provider_already_corrects,
    rated_dc_capacity_wp, max_uplift_c) -> dict[int, NDArray[np.float64]]`
    — de-methodized relocation of `coordinator.py`'s private
    `_apply_training_corrections` (now removed as a method entirely; no
    call sites remain).
  - `fit_string_model(fc_by_offset, corrected_pv_by_offset,
    smoothing_radius, neighbor_fitting_cutoff, recency_decay_max,
    method: str, *, apply_magnitude_weight: bool = True) -> FittedModel`
    — new; wraps `regression.base.build_pool` + `REGRESSION_STRATEGIES[method]
    .fit(pool)`.
  - `predict_string_forecast(model, fc, target_cell_temperature,
    coefficient_per_c, provider_already_corrects, inverter_limit) ->
    NDArray[np.float64]` — new; thin wrapper over
    `forecast_adjust.adjust_forecast`, returns only the adjusted array
    (drops the confidence return value).
- `custom_components/shady/coordinator.py` (refactored, behavior-
  identical):
  - `_apply_training_corrections` method **removed**.
  - Module-level `_REGRESSION_STRATEGIES` dict **removed**.
  - `_fit_string`/`_fit_temperature_string` now call
    `string_computation.apply_training_corrections`/`fit_string_model`
    directly; imports updated (`from . import string_computation`
    added; `regression`, `build_pool`, `derate_actual_to_reference`,
    `exclude_clipped` imports dropped — `FittedModel` and
    `uplift_ambient_to_cell` retained, still used elsewhere for type
    annotations/the intraday-basis path respectively).
  - `_predict_day_basis`/`_clamp_basis` **unchanged** — still call
    `forecast_adjust.reverse_transformed_forecast`/`clamp_output`
    directly (the one caller needing the split-then-multi-day-clamp
    shape for intraday correction to insert into, ADR-006 §1b; no
    duplication to remove there per this task's own acceptance
    criteria).
- `tests/test_string_computation.py` (new, zero-mocking) → 14 tests
  across 5 classes (`TestModulePurity`, `TestApplyTrainingCorrections`,
  `TestFitStringModel`, `TestPredictStringForecast`), covering every
  acceptance criterion above including the two explicit `n_slots=1`
  smoke tests.
- `tests/test_coordinator.py`, `tests/test_button.py`,
  `tests/test_sensor_aggregates.py`, `tests/test_sensor_forecast.py`
  (harness-only change) → added
  `_load("string_computation.py", "shady.string_computation")` right
  after each file's existing `_load("cache.py", ...)` line, so
  `coordinator.py`'s new `from . import string_computation` relative
  import resolves against `sys.modules` the same way its other
  relative imports already do.
- `tests/test_coordinator_temperature_forecast.py` (updated, not just
  harness) → `TestApplyTrainingCorrectionsTierDispatch`'s four tests
  previously called `coordinator._apply_training_corrections(string,
  ...)` directly; updated to call
  `string_computation.apply_training_corrections(...)` with the same
  values translated into the new function's explicit parameters — this
  was **not** anticipated when this task was scoped (Consumed
  Interfaces review only checked Delivered/Consumed Interfaces
  declarations, which correctly showed no other task's Delivered
  Artifacts referenced this private method — but missed that a sibling
  task's *test file* called it directly). Flagged here explicitly since
  it's a deviation from this task's own "no other test file calls these
  privates directly" acceptance-criterion assumption; the fix was
  narrow (four call-site translations, no behavior/assertion changes)
  and the resulting suite still asserts byte-identical outputs.
- External dependencies added: none.
- Gates: `ruff format`, `ruff check`, `mypy --config-file mypy.ini
  --strict`, `pytest` all pass with zero errors. Full suite 332/332
  (318 pre-existing + 14 new). `mypy` clean on 45 source files.
  `ruff format --check` still shows only the one pre-existing,
  documented, unrelated `tests/test_regression.py` drift (2026-08-26
  refinement-log entry) — untouched by this task.
