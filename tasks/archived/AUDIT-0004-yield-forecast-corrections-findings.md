# Findings: AUDIT-0004 — Yield & Forecast Corrections

**Auditor:** Lead Agent (inline, single-pass) **Date:** 2026-09-06 **Verdict:**
PASS overall. No FAILs, no PARTIALs. Strongest-tested module pair audited so far
— several Test-Coverage Criteria exceeded what was asked for
(differential/spy-style proofs rather than output-equality checks alone).

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | Clipping = exclusion, not down-weight (§1) | PASS | `yield_correction.py:59-61` `exclude_clipped`: `excluded[excluded >= clipping_threshold * inverter_limit] = np.nan` — full `NaN` marking, no scaling factor applied anywhere in the function. |
| 2 | Inverter limit is a *second*, separate output clamp (§1a) | PASS | `forecast_adjust.py:49-65` `clamp_output`'s `upper = safe_fc if inverter_limit is None else np.minimum(safe_fc, inverter_limit)` — a distinct `min(FC, inverter_limit)` bound layered on top of the base `[0, FC]` clamp, not reusing/conflating the training-time exclusion threshold (`clipping_threshold`) at all — the output clamp uses the raw `inverter_limit`, not `clipping_threshold * inverter_limit`. |
| 3 | Clipping exclusion stays inside `yield_correction.py`'s pre-processing, no leakage elsewhere (§2) | PASS | `exclude_clipped` is the only clipping-related function in the codebase; `grep -rn "clipping_threshold\|exclude_clipped" custom_components/shady/*.py custom_components/shady/**/*.py` (excluding `yield_correction.py` and `coordinator.py`'s call site) shows no clipping logic inside `regression/` or `forecast_adjust.py` — the latter only ever handles the *output*-clamp half (§1a), correctly kept separate per ADR-003a §2's explicit "not a call back into `yield_correction.py`." |
| 4 | Temperature correction applied before the ratio is formed, not inside the model (§1) | PASS | `derate_actual_to_reference` (`yield_correction.py:94-119`) operates on the raw actual-yield value directly; `regression/`'s `build_pool` (audited in AUDIT-0002) has no temperature-awareness at all — confirms the model never sees a temperature-biased sample. |
| 5 | Temperature-source hierarchy consumed as `providers/temperature.py` exposes it, no duplicate sourcing (§1a) | PASS | `yield_correction.py`'s module docstring (`:4-7`) states `cell_temperature`/`target_cell_temperature` are "always supplied by the caller (already resolved by `providers/temperature.py`...)" — confirmed no `hass`/entity-reading code anywhere in `yield_correction.py` (`grep -n "hass\|entity_id"` returns nothing). |
| 6 | Reverse transform is the genuine algebraic inverse of forward (§1b) | PASS | `apply_derate_to_prediction` (`yield_correction.py:122-155`) is `predicted_at_reference * (1 + coefficient_per_c * (target_cell_temperature - 25))` — exactly the algebraic inverse of `derate_actual_to_reference`'s `actual_raw / (1 + coefficient_per_c * (cell_temperature - 25))`. Confirmed empirically, not just by inspection — see Test-Coverage Criterion #3 below. |
| 7 | A documented condition skips correction entirely, not a no-op multiplier (§1c) | PASS | `provider_already_corrects` (both functions, `yield_correction.py:99,117` / `127,151`) short-circuits with an early `return` of the *unmodified* input — genuinely skipped, not multiplied by `1.0`. Both forward and reverse check the exact same three conditions (`provider_already_corrects`, `coefficient_per_c is None`, `cell_temperature is None`) in lockstep, matching §1c's "skip together" rule precisely. |
| 8 | Pre-processing sits below `regression/`; no reverse import (§2) | PASS | `regression/*.py` has zero imports from `yield_correction.py` (confirmed in AUDIT-0002's file reads — no such import present); `forecast_adjust.py:46` imports `from .yield_correction import apply_derate_to_prediction` — the dependency direction only runs `forecast_adjust → yield_correction`, never the reverse. |
| 9 | `forecast_adjust.py` treats regression method as opaque, no strategy branching (ADR-001 §2 cross-ref) | PASS | `reverse_transformed_forecast` (`forecast_adjust.py:68-106`) calls only `model.predict_unclamped(fc)` — the shared abstract-base-class method (AUDIT-0002 confirmed all four strategies implement it identically) — with no `isinstance`/strategy-name branching anywhere in the file. |
| 10 | `reverse_transformed_forecast` has the documented signature, returns both series, doesn't itself intraday-correct (ADR-006 §1b cross-ref) | PASS | `forecast_adjust.py:68-75` signature returns `tuple[NDArray[np.float64], NDArray[np.float64]]` (reverse-transformed values, confidence) exactly as documented; no ramp/crossfade/intraday-related code anywhere in this function — confirmed scoped to steps 1-2 only, leaving intraday correction for `coordinator.py` to insert (AUDIT-0005/0007's scope) between this call and `clamp_output`. |

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | Clipping exclusion removes points (count/identity), not just changes output values | COVERED | `TestExcludeClipped.test_exclusion_is_not_a_downweight_but_a_full_exclusion` (`test_yield_correction.py:57-63`) asserts exact `NaN`, explicitly named to guard against a down-weight regression. |
| 2 | Inverter-limit output clamp asserted separately from training exclusion | COVERED | `TestInverterLimitClampsBelowForecast` (`test_forecast_adjust.py:109`) is a distinct test class from any clipping-exclusion test (which lives in a different file/module entirely — `yield_correction.py` doesn't know about output clamping at all), confirming the two are independently verified. |
| 3 | Differential round-trip test: forward then reverse recovers the original value | COVERED, exceeds the bar | `TestReverseTransformRoundTrip` (`test_yield_correction.py:121-161`) tests round-trip recovery for both a scalar and an array case (`test_round_trip_recovers_original_value`, `test_round_trip_recovers_original_array`), not merely each direction in isolation as the audit criterion worried might be the case. |
| 4 | "Provider already corrects" skip asserted as skip, not coincidental equality | COVERED (adequate for a pure function — no call to spy on) | `TestProviderAlreadyCorrectsFlag.test_flag_overrides_an_otherwise_fully_configured_string` (`test_yield_correction.py:236-246`) uses a fully-configured (non-degenerate) coefficient/temperature specifically so the no-op can't be mistaken for "there was nothing to correct anyway" — as strong a proof as a pure function (no intermediate call to spy on) can offer. |
| 5 | No strategy-branching regression test across all four strategies | **GAP** | No test in `test_forecast_adjust.py` runs `adjust_forecast`/`reverse_transformed_forecast` against all four real `regression/` strategies and asserts identical call-pattern behavior — the file's `_StubModel`/`_AssertingStub` fixtures (`test_forecast_adjust.py:63,222`) are hand-built fakes, not the real `linear`/`wls2`/`wls3`/`kernel` classes. The `predict_unclamped`-not-`predict` spy test (below) gives strong *indirect* assurance (any strategy-specific branching would have to reach around the uniform `predict_unclamped` call), but no test directly parametrizes over the four real strategy modules the way `test_regression.py`'s own `TestEveryStrategyHandlesTheSharedFixtures` does. |

### Additional coverage found exceeding the original audit task's own criteria

- **`TestUsesPredictUnclampedNotPredict.test_predict_is_never_called`**
  (`test_forecast_adjust.py:215-236`) is a genuine spy test — a stub model whose
  `predict()` raises `AssertionError` if called at all — directly proving
  `adjust_forecast` never touches the clamped `predict()` path. This is a
  stronger proof than this audit task originally asked for (which only asked
  whether the ordering/clamp bug this guards against was covered).
- **`TestCombinedOrderingReverseTransformThenClamp. test_ordering_matters_transform_then_clamp_not_clamp_then_transform`**
  (`test_forecast_adjust.py:177-209`) constructs a scenario where
  transform-then-clamp and clamp-then-transform produce *different* numeric
  results (700 vs. 980 vs. clamped-850) and asserts the correct one — a true
  ordering-sensitive differential test, not just "the final number looks
  plausible."

## Candidate Follow-Ups (not created — proposed only)

1. **Optional, low priority:** parametrize `TestUsesPredictUnclampedNotPredict`
   (or add a sibling test) across the four real `regression/` strategy modules,
   mirroring `test_regression.py`'s `TestEveryStrategyHandlesTheSharedFixtures`
   pattern — would close Test-Coverage Gap #5 and give this module pair the same
   real-strategy assurance `test_regression.py` has for its own package, rather
   than relying on hand-built stubs throughout.

## Delivered Artifacts (for the task file)

- `tasks/AUDIT-0004-yield-forecast-corrections-findings.md` (this file)
