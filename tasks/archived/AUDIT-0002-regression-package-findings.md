# Findings: AUDIT-0002 — Regression Package

**Auditor:** Lead Agent (inline, single-pass) **Date:** 2026-09-06 **Verdict:**
PASS overall. No FAILs. Two genuine test-coverage GAPs within this package's own
test file (one with incidental coverage elsewhere); one self-correction to this
audit task's own criterion wording.

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | Pluggable, globally-selected method; `wls2` default (§2) | PASS | Four independent strategy modules (`linear.py`, `wls2.py`, `wls3.py`, `kernel.py`), each exposing a module-level `fit(pool) -> FittedModel`, share `regression/base.py`'s `FittedModel`/`SamplePool`. Default-ness itself is a config-flow concern (verified in AUDIT-0010), not visible in this package — no `linear.py`-vs-`wls2.py` asymmetry in this package suggests one is privileged over another at this layer, consistent with "chosen once by the user," not hardcoded here. |
| 2 | Daily-total goodness-of-fit, not per-slot (§2a) | N/A to this package | `regression/` only produces per-slot `confidence`; the daily-total-weighted aggregation ADR-002 §3/ADR-001 §2a describes is a `coordinator.py`/entity-layer concern. Correctly out of this package's scope — cross-ref AUDIT-0005/AUDIT-0009. |
| 3 | One model per string (§3) | N/A to this package | `regression/` is per-string-agnostic by construction — it fits whatever pool it's handed, once per call. Cardinality (one call per string) is `coordinator.py`'s responsibility (AUDIT-0005). |
| 4 | One model per 5-min slot, on the 288-slot grid (§3a) | PASS (structurally) | `build_pool`/`fit_weighted_polynomial`/`evaluate_polynomial` are all slot-count-agnostic — operate on whatever `n_slots` the caller's arrays have (`base.py:238-301`, `:304-330`). The actual 288-slot grid is imposed by the caller (`cache.py`/`coordinator.py`, AUDIT-0003/0005), not hardcoded here — matches the ADR's intent that this is a caller-supplied shape, and confirms this package makes no slot-count assumption that could silently diverge from 288 elsewhere. |
| 5 | `recency_weight_i` applied in `build_pool` (§4a) | PASS | `base.py:242` `recency_weight = _recency_weight(...)`; formula at `base.py:166-185` (`day_age_i = (window_days-1) - day_position_i`, `1 - (day_age/(window_days-1))*recency_decay_max`) matches ADR-001 §4a exactly, including the `window_days<=1` degenerate case (`base.py:181-182`). Actually multiplied into `combined_weight` at `base.py:290`, not merely computed and discarded. |
| 6 | Smoothing widens training *data*, not output (§1) | PASS | `build_pool` takes `fc_by_offset`/`pv_by_offset` keyed by neighbor offset and concatenates them into one pool (`base.py:238-298`) before any strategy's `fit()` runs — confirmed data-level, not a post-fit smoothing pass (no smoothing/averaging code found anywhere after `fit_weighted_polynomial`/`evaluate_polynomial`). |
| 7 | `time_weight_i` formula and hard cutoff (§1) | PASS | `base.py:258` `time_weight = 1.0 - abs(offset) / (smoothing_radius + 1)`, matches ADR-011 §1 exactly; offsets iterate only `range(-smoothing_radius, smoothing_radius+1)` (`base.py:238`) — no sample outside that range enters the pool at all, matching the "hard cutoff" claim. |
| 8 | Neighbor hard exclusion, not down-weight (§2) | PASS | `base.py:280-287`: `excluded = deviation > neighbor_fitting_cutoff`; `magnitude_weight = np.where(excluded[:,None], 0.0, magnitude_weight)` — weight forced to exactly `0.0`, not reduced, matching "hard exclusion... not a further reduction of the existing linear weight." |
| 9 | Rescale alternative (§3) is config-gated, not silently replacing §2 | PASS | `base.py:268` `if neighbor_fitting_cutoff == RESCALE_SENTINEL:` gates the rescale path on the exact `-0.01` sentinel (`base.py:38`); the ordinary path (any other `neighbor_fitting_cutoff` value) always takes the exclusion branch (`base.py:279` `else:`). §2 remains the default/normal behavior; §3 only activates on the explicit sentinel. |
| 10 | `numpy`-vectorized `fit()`/`predict()` for all four strategies (ADR-008 §1) | PASS | `fit_weighted_polynomial` (`base.py:304-330`) does one batched `np.linalg.solve` call for the whole slot sweep — shared by `linear`/`wls2`/`wls3`. `kernel.KernelFittedModel.predict_unclamped` (`kernel.py:67-83`) is a single vectorized `np.exp`/`np.einsum`-free but fully array-broadcast computation over all slots at once — no Python-level per-slot loop found in any of the four strategy files (`grep -n "for .* in range" regression/*.py` returns nothing in `linear.py`/`wls2.py`/`wls3.py`/`kernel.py`). |
| 11 | `NDArray[np.float64]` typing, zero bare `np.ndarray` (ADR-000 §4 Amendment) | PASS | `grep -rn "np\.ndarray\b" custom_components/shady/regression/*.py` returns **zero** matches — every array-valued signature/attribute across all six files (`base.py`, `linear.py`, `wls2.py`, `wls3.py`, `kernel.py`, `__init__.py`) uses `NDArray[np.float64]`. |
| 12 | `magnitude_weight_i` optionality defaults to preserving old behavior (ADR-003c §2 cross-ref) | PASS, **with a correction to this audit task's own wording** | `base.py:195` `apply_magnitude_weight: bool = True` — the default is `True` (apply magnitude weighting, i.e. today's ADR-001 §2 behavior), **not** "disabled" as this audit task's own criterion mis-stated it. "No-op" here correctly means "no behavior change for pre-existing callers who don't pass the new parameter," which is exactly what the default being `True` achieves — not that the feature itself defaults to off. Confirmed byte-identical via `tests/test_regression.py:259-280` `test_true_default_reproduces_pre_patch_output_unmodified`. |
| 13 | `predict_unclamped()` on all four `FittedModel`s via consolidated base class, identical semantics (ADR-006 §1b cross-ref) | PASS | `FittedModel.predict()` (`base.py:102-109`) is implemented **once** on the base class and calls the abstract `predict_unclamped()`; all four strategies implement only `predict_unclamped` (`linear.py:29-34`, `wls2.py`, `wls3.py`, `kernel.py:67-83`), confirming the consolidation TASK-0005-patch-3 claims. Cold-start passthrough (`passthrough_where_no_confidence`) is called identically inside each of the three polynomial strategies' `predict_unclamped` and inline in `kernel.py:81`'s equivalent `np.where` — same fallback semantics, no divergence found. |

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | Differential test: `recency_weight_i` actually changes the fit | COVERED | `tests/test_regression.py:403-406` `test_confidence_reflects_recency_weight_contribution` asserts `decayed.confidence < undecayed.confidence` — a genuine differential comparison, not just "parameter accepted." |
| 2 | `magnitude_weight_i` default is a true no-op | COVERED | `test_true_default_reproduces_pre_patch_output_unmodified` (`test_regression.py:259-280`) asserts `np.array_equal` between default and explicit-`True` calls — byte-identical, not merely "doesn't crash." |
| 3 | Neighbor-exclusion boundary test would catch a regression to down-weight | COVERED | `TestNeighborHardExclusion.test_deviating_neighbor_is_fully_excluded` (`test_regression.py:412` area) — needs to assert exact `0.0` weight, not just "reduced"; confirmed by reading the test body (uses `neighbor_fitting_cutoff` below the fixture's deviation and asserts zero contribution). |
| 4 | `NDArray[np.float64]` typing enforcement | GAP, **by design — not a pytest concern** | Correctly flagged in this task's own criteria as enforced by `mypy --strict` (a CI gate, ADR-000 §1), not by pytest. Cross-referenced to AUDIT-0012, which checks whether the CI pipeline itself would actually catch a regression here (e.g. a stray `warn_unused_ignores` suppression). |
| 5 | `predict_unclamped()` regression to clamped output, for any of the four strategies | **GAP within this package's own test file** | `grep -n "predict_unclamped" tests/test_regression.py` returns **zero matches** — `test_regression.py` never calls `predict_unclamped()` directly on any of the four real strategies; every test in this file goes through `predict()` or `build_pool()`. There **is** incidental coverage elsewhere — `tests/test_coordinator_temperature_forecast.py:354` calls a real `model.predict_unclamped(query)` — but that's a different audit group's test file (AUDIT-0005), testing it in service of a different scenario (the temperature-forecast learned model), not as a `regression/`-package-level guarantee. If `coordinator_temperature_forecast`'s test were ever removed or narrowed, `test_regression.py` alone would not catch a strategy silently clamping inside `predict_unclamped`. |
| 6 | Nine documented test classes, from TASK-0005's Delivered Artifacts, unmodified in name/intent | PASS (expanded, not shrunk) | Current file has **16** test classes (`grep -c "^class "` → 16), all with intent-describing docstrings referencing specific ADR sections (§1/§2/§2a/§3/§4a/ADR-011 §1/§2/§3/ADR-008 §1) — consistent with the five patches each adding, not replacing, coverage. No evidence of a renamed/merged class masking which ADR clause it protects. |

## Candidate Follow-Ups (not created — proposed only)

1. **Recommended, moderate priority:** add a direct
   `predict_unclamped()`-vs-`predict()` differential test to
   `test_regression.py` itself (e.g. a fixture where the unclamped prediction
   would exceed `FC` or go negative, asserting `predict_unclamped` preserves
   that while `predict` clamps it) — closes Test-Coverage Gap #5 without relying
   on a different audit group's test file for a `regression/`-package-level
   guarantee.
1. **Correction, no action needed:** this audit task's own Audit Criterion #12
   wording ("default to a no-op (disabled)") should be read as "default
   preserves pre-existing behavior," not "defaults to off" — noting this so a
   future re-run of this audit task doesn't trip on the same imprecise phrasing.

## Delivered Artifacts (for the task file)

- `tasks/AUDIT-0002-regression-package-findings.md` (this file)
