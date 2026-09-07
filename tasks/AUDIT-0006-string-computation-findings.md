# Findings: AUDIT-0006 — String Computation Module

**Auditor:** Lead Agent (inline, single-pass)
**Date:** 2026-09-06
**Verdict:** Mostly PASS, well-tested (all 14 tests re-run live during
this audit, 14/14 green). **One genuine FAIL**: the module's own
docstring makes a factually false claim about who calls
`predict_string_forecast` — it says `coordinator.py`'s no-intraday-
correction path uses it; `coordinator.py` never calls
`predict_string_forecast` at all. This sharpens (and is the same
underlying fact as) AUDIT-0005's finding B, but is more directly
actionable here since it's a defect in the audited file itself, not
just the ADR text. One coverage GAP (duplication-regression is
untestable at the unit level, same class of gap as AUDIT-0005's #4).

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
|---|---|---|---|
| 1 | Slot-count-agnostic — no hardcoded 288 or similar | PASS | `grep -n "288\|SLOTS_PER_DAY"  string_computation.py` returns nothing; every function signature takes `Mapping[int, NDArray]`/plain `NDArray` with no dimension assumption. `TestFitStringModel.test_single_slot_pool_n_slots_1` and `TestPredictStringForecast.test_single_slot_prediction` (`test_string_computation.py:297-305,336-346`) exercise `n_slots=1` directly and pass, empirically confirming the claim, not just by inspection. |
| 2 | Pure — no `homeassistant.*`/`cache.py` import | PASS | Imports (`string_computation.py:53-56`): `.forecast_adjust`, `.regression`/`.regression.base`, `.yield_correction` only. `TestModulePurity.test_no_cache_or_homeassistant_import` (`:79-87`) asserts this from the source text directly and passes. |
| 3 | `apply_training_corrections`/`REGRESSION_STRATEGIES` moved verbatim in behavior (§2) | PASS | `TestApplyTrainingCorrections`'s six tests (`:104-266`) each independently reconstruct the expected result via direct `exclude_clipped`/`derate_actual_to_reference`/`uplift_ambient_to_cell` calls (the same primitives the function composes) and assert exact array equality across the no-temperature, `cell`, `ambient`-with-uplift, `ambient`-without-capacity, `provider_already_corrects`, and multi-offset cases — genuine differential proofs, not smoke tests. `TestModulePurity.test_registry_has_all_four_methods` (`:89-94`) confirms `REGRESSION_STRATEGIES` still maps all four `const.py` method names to the correct modules by identity (`is`, not just equality). |
| 4 | `fit_string_model`/`predict_string_forecast` exist with documented responsibilities, compose `regression/`/`forecast_adjust.py`/`yield_correction.py` directly (§3) | **PARTIAL — see FAIL below for the specific inaccuracy** | Both functions do compose the underlying modules directly (`build_pool`+`strategy.fit()` for the former, `forecast_adjust.adjust_forecast` for the latter) — confirmed via `TestFitStringModel.test_matches_direct_build_pool_and_fit` (all 4 methods) and `TestPredictStringForecast`'s two differential tests (`:274-333`), all re-run live during this audit and passing. The module-boundary half of this criterion is satisfied. |
| 5 | `coordinator.py`'s role looks "narrower" — calls into `fit_string_model`/`predict_string_forecast` rather than reimplementing locally (§4 cross-ref) | **FAIL, for `predict_string_forecast` specifically** | `grep -n "string_computation\." coordinator.py` shows exactly two call sites, both to `apply_training_corrections`/`fit_string_model` (`coordinator.py:763,776,831`) — genuinely narrower for those. **`predict_string_forecast` has zero call sites in `coordinator.py`.** `coordinator.py`'s `_predict_day_basis`/`_clamp_basis` (confirmed in AUDIT-0005) still call `forecast_adjust.reverse_transformed_forecast`/`clamp_output` directly for **both** the intraday-on and intraday-off paths — this is a real architectural constraint (ADR-006 §1b's correction must sit between transform and clamp) and is not itself a bug. **But `string_computation.py`'s own module docstring (`:34-42`) explicitly and incorrectly claims otherwise**: *"`predict_string_forecast` is a thin wrapper... `coordinator.py`'s own... 'no intraday correction' path... [doesn't need confidence]... `coordinator.py`'s intraday-ON path still calls `forecast_adjust.reverse_transformed_forecast`/`clamp_output` directly..."* and, even more explicitly, `predict_string_forecast`'s own function docstring (`:187-198`): *"Used by `coordinator.py`'s no-intraday-correction path and by `diagnostics/compare_regressions.py`... alike."* This is false — `coordinator.py`'s off-path (`_clamp_basis`) also calls `clamp_output` directly, never `predict_string_forecast`. `grep -rn "predict_string_forecast"` across the whole codebase confirms the only real caller is `diagnostics/compare_regressions.py:396`. |
| 6 | `diagnostics/compare_regressions.py` depends on this module directly, no leftover `diagnostics → regression` import (§5) | PASS | `diagnostics/compare_regressions.py:50-53`'s import block shows `from .. import string_computation` and no import of `..regression`/`..regression.base` anywhere in the file — the edge described in ADR-014 §5's updated module diagram is the only one present. (Deep verification of *how* `diagnostics/` uses it is AUDIT-0008's job, per this task's own Out-of-Scope note — this is a shallow import-list check only, as the criterion asks.) |
| 7 | Genuinely one implementation, not three (§6) | PASS, with the one caveat above | `apply_training_corrections`/`fit_string_model` are each called from exactly two places (`coordinator.py`, `diagnostics/compare_regressions.py`) with no third, independent copy found anywhere via `grep -rn "def apply_training_corrections\|def fit_string_model\|def predict_string_forecast"` (each defined exactly once, in `string_computation.py`). The `predict_string_forecast` finding above is not a case of a *third* implementation appearing — `coordinator.py` composes the same two underlying calls (`reverse_transformed_forecast`+`clamp_output`) `predict_string_forecast` itself wraps, not a re-derived version — so ADR-014 §6's actual "drift risk" concern (three independently-maintained copies of the *logic*) has not materialized; only the module's own description of *who calls what* is inaccurate. |

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | A test would fail if `coordinator.py` reintroduced a local copy of `fit_string_model`'s logic instead of calling this module | **GAP** | No test in either `test_string_computation.py` or `test_coordinator.py` inspects `coordinator.py`'s source/call-graph to confirm it delegates rather than reimplements — every existing test only checks *output* correctness. A hypothetical regression that reintroduced a correctness-preserving local copy of `fit_string_model`'s three-line sequence directly inside `coordinator.py` (exactly the ADR-014 §6 "drift risk" scenario) would pass every existing test undetected, since the numeric outputs would still match. Same class of gap as AUDIT-0005's Test-Coverage Gap #4 — an absence-of-a-second-implementation property is not naturally unit-testable; static grep (as done in Audit Criteria 5/7 above) is the practical substitute. |
| 2 | `fit_string_model`/`predict_string_forecast` proven identical to pre-TASK-0017 `coordinator.py` behavior, empirically | COVERED, confirmed by live re-execution | `tests/test_coordinator.py`, `tests/test_coordinator_intraday.py`, and `tests/test_coordinator_temperature_forecast.py` are documented (TASK-0017 Delivered Artifacts) as passing unmodified after the refactor — this audit did not re-run those three files (they require the real `homeassistant` package, not installed in this sandbox), but **did** independently install `pytest` and re-run `tests/test_string_computation.py` live: **14/14 passed**, confirming the differential proofs against the underlying `regression/`/`forecast_adjust.py`/`yield_correction.py` primitives (Audit Criteria 3/4 above) hold today, not merely at TASK-0017's original landing. |
| 3 | 14 tests still map one-to-one onto public functions, no ungrown surface | COVERED, with one bookkeeping nit | `grep -c "def test_"` confirms exactly 14 test functions today — unchanged since TASK-0017. `string_computation.py`'s public surface is unchanged too (`REGRESSION_STRATEGIES`, `apply_training_corrections`, `fit_string_model`, `predict_string_forecast` — four names, matching `__all__`-equivalent expectations, no fifth function added since). Minor nit: TASK-0017's own Delivered Artifacts block claims "14 tests across **5** classes"; the file actually has **4** classes (`TestModulePurity`, `TestApplyTrainingCorrections`, `TestFitStringModel`, `TestPredictStringForecast`). Cosmetic task-file bookkeeping error, not a code or coverage issue — noted for completeness only. |
| 4 | A test exercises a non-default slot count, not just the 288-slot grid | COVERED | `TestFitStringModel.test_single_slot_pool_n_slots_1` and `TestPredictStringForecast.test_single_slot_prediction` both use `n_slots=1` explicitly and assert shape `(1,)` — the exact shape `diagnostics/`'s real single-diagnosed-slot caller uses (ADR-004 §4), not merely a synthetic edge case. |

## Candidate Follow-Ups (not created — proposed only)

1. **Documentation fix, low risk, high value:** correct
   `string_computation.py`'s module docstring (`:34-42`) and
   `predict_string_forecast`'s own docstring (`:187-198`) — remove the
   false claim that `coordinator.py`'s no-intraday-correction path uses
   `predict_string_forecast`. The accurate statement (already correctly
   captured in `coordinator.py`'s own comments and in TASK-0017's
   Acceptance Criteria) is that **both** of `coordinator.py`'s paths
   (intraday on and off) call `reverse_transformed_forecast`/
   `clamp_output` directly, and only `diagnostics/compare_regressions.py`
   actually calls `predict_string_forecast`. This is a same-file
   docstring correction — no behavior change, no test change needed.
2. **Same underlying fact as AUDIT-0005's candidate follow-up #2:**
   if/when ADR-014 §4 is amended (per that audit's recommendation) to
   carve out `_predict_day_basis`/`_clamp_basis`'s exception, the same
   amendment pass should note that `predict_string_forecast` today has
   exactly one real caller (`diagnostics/`), not two — this findings
   file and AUDIT-0005's are describing the same gap from two ends of
   the same call graph and should be resolved together.
3. **Optional, low priority:** a lightweight static check (e.g. a test
   that parses `coordinator.py`'s source and asserts no
   `_apply_training_corrections`-shaped private method exists, or a
   `ruff`/code-review convention) would close Test-Coverage Gap #1 —
   not urgent, same reasoning as AUDIT-0005's analogous follow-up #4.

## Delivered Artifacts (for the task file)
- `tasks/AUDIT-0006-string-computation-findings.md` (this file)
