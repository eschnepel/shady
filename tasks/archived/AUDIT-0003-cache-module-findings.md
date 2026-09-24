# Findings: AUDIT-0003 — Cache Module

**Auditor:** Lead Agent (inline, single-pass) **Date:** 2026-09-06 **Verdict:**
One confirmed FAIL (fitted-model cache is not in `cache.py`, contradicting
ADR-007 §1 and ADR-007a §5's explicit text). Every other criterion PASSes,
several very precisely.

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | `cache.py` owns all retained state; pure, no `hass` (§1) | **FAIL (partial)** | See dedicated finding below — the fitted-model cache does not live here. Purity itself is confirmed: `grep -n "hass\|homeassistant" custom_components/shady/cache.py` returns zero matches; `Cache.__init__` (`cache.py:170`) takes only `window_days`/`fetch_fn`. |
| 2 | `coordinator.py` shrunk to orchestration-only; no fit/predict/business logic leaked into `cache.py` (§2) | PASS | `cache.py` contains no `regression/`, `yield_correction.py`, or `forecast_adjust.py` imports (`grep -n "^from \.\|^import"` at the top of the file shows only `numpy`/stdlib); confirmed storage-and-accessor-only content throughout. |
| 3 | Three genuine states for stored values (§1) | PASS | `_write`/`_read` (`cache.py:243-284`) store/retrieve `float \| None \| str` directly, no collapsing. `_shape` (`cache.py:132`) and `_shadow_value` (`cache.py:147`) both explicitly branch on all three states. |
| 4 | Real validated-range tracking, actually used (§2) | PASS | `_validated: dict[str, tuple[int, int\|None]]` (referenced throughout `_validate_range`/`push`/`invalidate`/`trim`) is read before every accessor call (`get_time_range:481-482`, `get_regression_pools:579`, `get_pinned_slot_pool:687-688`) — not merely stored and ignored. |
| 5 | Push vs. invalidate: different code paths, different effects (§3) | PASS | `push` (`cache.py:335-356`) sets `to_index=None` and never triggers a fetch; `invalidate` (`cache.py:358-382`) writes `None` and either deletes or shrinks the validated range, forcing a future re-fetch. Genuinely different downstream behavior, not two names for the same operation. |
| 6 | Injected fetch function; validation catches up correctly (§4) | PASS | `FetchFn = Callable[[str, datetime, datetime], list[...]]` injected via `__init__` (`cache.py:170`), never imported directly. `_validate_range` (`cache.py:306-331`) correctly branches: no data → fetch the whole window (`:314-318`); `to_index=None` (push-based) → never re-queried (`:322-325`); partial → fetch only the missing head/tail (`:327-331`). |
| 7 | Accessor methods match documented signatures/semantics, respect three-state/validated-range (§5) | PASS | `get_time_range` (`:459-503`) validates before reading, both `group_by` shapes present. All three accessors route reads through `_read`/`_shape`, never bypass to raw storage. |
| 8 | Pinned reference: single, cache-wide scalar, one write path (§6) | PASS | `_pinned_reference: date \| None` is a single instance attribute; `pin_reference`/`clear_reference` (`cache.py:600-610`) are its only two mutators — no per-sensor or per-string variant found anywhere in the file. |
| 9 | Batched regression-pool accessor returns real `numpy`-backed batch, full sweep in one call (ADR-008 §2) | PASS | `get_regression_pools` (`cache.py:505-596`) builds the entire `(288, window_days×(2r+1))` array via one vectorized broadcast/gather (`:570-594`) — no per-slot Python loop; `_validate_range` is called once per sensor for the whole window (`:579`), not per slot. |
| 10 | Three-accessor split matches documentation exactly (ADR-008 §3) | PASS | Exactly `get_time_range`, `get_pinned_slot_pool`, `get_regression_pools` exist, each with the exact shape ADR-008 §3 assigns it — no fourth generically-parameterized accessor and no leftover accessor from before the split. |

### FAIL — Fitted-model cache is not in `cache.py` (ADR-007 §1, ADR-007a §5)

ADR-007 §1 explicitly lists the five caches `cache.py` "holds," the first being
"Per-string, per-slot fitted-model cache (ADR-002 §1)." ADR-007a §5 is even more
explicit about *where*: "The model cache (fitted model objects per
string/slot)... stay[s] as simple `dict[key, value]` structures **elsewhere in
`cache.py`**, without the index/validation machinery above."

The shipped code does not do this.
`grep -n "model" custom_components/ shady/cache.py` returns no cache-storage
matches at all (only three docstring mentions of an unrelated word). The actual
fitted-model cache lives in **`coordinator.py`**:

```
coordinator.py:461:  self._models: dict[int, FittedModel] = {}
coordinator.py:470:  self._temperature_models: dict[int, FittedModel] = {}
```

constructed directly in `coordinator.py`'s setup, alongside (not inside)
`self.cache = Cache(...)` (`coordinator.py:452`). `cache.py`'s own module
docstring (`cache.py:1-54`) is consistent with this: it explicitly enumerates
what the module owns (three-state store, energy totals,
pinned-reference/`get_pinned_slot_pool`, `IntradayState`/`IntradayBasis` ramp
state) and **never mentions a model cache** — meaning this isn't an accidental
omission from the docstring while the code secretly complies; the code and its
own documentation agree with each other, and both disagree with
ADR-007/ADR-007a.

This is architecturally defensible — a `FittedModel` is an object, not a
`float | None | str`/time-series value, so it never needed the index-addressable
machinery `cache.py`'s other four stores share, and keeping it directly next to
`coordinator.py`'s per-string fit/predict loop (which TASK-0017 later also
relocated to `string_computation.py`, AUDIT-0006) may well be the more coherent
design in practice. But no ADR amendment records this deviation, and ADR-007a
§5's ramp-state analogy (`IntradayState`, which correctly *did* land in
`cache.py` as a plain dict, confirming the pattern was followed for the *other*
non-time-series cache) makes the model cache's absence look like an unrecorded
scope decision rather than a documented one. Per the golden rule, this is
flagged for a human decision rather than resolved here: either (a) amend ADR-007
§1 / ADR-007a §5 to reflect that the model cache is intentionally
`coordinator.py`-owned (with rationale), or (b) treat this as a Scenario-C gap
against `TASK-0002`/`TASK-0006` to actually move `self._models`/
`self._temperature_models` into `cache.py` as ADR-007a §5 describes.

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | Three-state semantics wouldn't collapse to two undetected | COVERED | `test_cache_core.py`'s push/invalidate tests and `test_cache_regression_pools.py`'s `TestShadowArrayMirrorsThreeStateList` (`:48`) explicitly assert `None` and `str` map to distinct outcomes (`str` preserved via `on_invalid="raw"`, both become `NaN` only in the *shadow* array, which is a documented, deliberate second-purpose collapse, not the three-state list itself). |
| 2 | Validated-range boundary tested at exact edges | COVERED | `TestMissingTailOnlyRefetchesTail` (`test_cache_core.py:62`) and its head-fetch counterpart (`:93`) exercise exactly the boundary-adjacent fetch behavior, not just well-inside-range reads. |
| 3 | `invalidate`/`push` differential effect | COVERED | `TestPushGuardAndPushOnlySensor` (`:133-173`) and `TestInvalidate` (`:258-291`) are separate test classes with observably different assertions (`to_index` stays `None` after push vs. shrinks/clears after invalidate) — not merely "both can be called." |
| 4 | Injected fetch function; partial-fetch-response widening tested | COVERED | `TestNoValidDataFetchesEntireWindow` (full-window case) and `TestMissingTailOnlyRefetchesTail` (partial case) together cover both validation branches with a custom injected `fetch_fn`. |
| 5 | Pinned reference overwrite (not duplicate) tested | COVERED | `TestPinReferenceClearReferenceAndProperty.test_pin_reference_can_be_moved_to_a_new_date_directly` (`test_cache_pinned_slot_pool.py:105`) confirms a second `pin_reference` call overwrites, not stacks. |
| 6 | Batched accessor differential vs. per-slot equivalent | PARTIAL | `TestGetRegressionPoolsBatchedSingleCall` (`test_cache_regression_pools.py:131`) checks shape/dtype/single-fetch-call and `TestDayBoundaryWraparound` checks edge-slot `NaN` placement — strong structural coverage — but no test explicitly cross-checks a `get_regression_pools` cell against an equivalent single-slot `get_pinned_slot_pool` read for the same sensor/index as a true differential-correctness proof. Low-severity gap given the shared underlying shadow-array read path both accessors use. |
| 7 | Cache extended in place by TASK-0012/0013/0015b — do earlier tests still hold unmodified? | PASS (no evidence of retrofit) | `test_cache_core.py`'s energy-integral tests (TASK-0012) and `test_cache_pinned_slot_pool.py`'s tests (TASK-0015b) are additive, separate test files/classes from the original `TestNoValidDataFetchesEntireWindow`-family tests (TASK-0002) — no sign any earlier assertion had to change to accommodate a later extension. |
| 8 | (New, arising from the FAIL above) Model-cache correctness test coverage | **N/A to `cache.py` — see AUDIT-0005** | Since the model cache lives in `coordinator.py`, its own correctness testing is scoped to `tests/test_coordinator.py`, not this audit's declared test scope. Flagging here only so the human doesn't read this audit's silence on model-cache testing as an oversight. |

## Candidate Follow-Ups (not created — proposed only)

1. **Human decision needed (primary finding):** resolve the ADR-007 §1 /
   ADR-007a §5 vs. actual `coordinator.py`-resident model-cache discrepancy —
   either amend the ADRs to document the as-built location (with rationale,
   likely tied to `TASK-0017`'s later relocation of fit/predict logic to
   `string_computation.py`), or schedule a Scenario-C task to move
   `self._models`/`self._temperature_models` into `cache.py`.
1. Optional, low priority: add one differential test cross-checking
   `get_regression_pools`'s cell values against `get_pinned_slot_pool`'s
   single-slot read for the same sensor/index, to close Test-Coverage Gap #6.

## Delivered Artifacts (for the task file)

- `tasks/AUDIT-0003-cache-module-findings.md` (this file)
