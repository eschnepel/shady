# Findings: AUDIT-0007 — Aggregation Module

**Auditor:** Lead Agent (inline, single-pass)
**Date:** 2026-09-06
**Verdict:** PASS on every behavioral criterion — the two decisions
(ADR-005 sums/integrals, ADR-006 intraday math) genuinely have not
blurred together, confirmed by both code inspection and a live test
run (19/19 passed). **One genuine FAIL, module-graph documentation**:
both ADR-005's local module diagram and ADR-000 §3's canonical module
graph claim an `aggregation --> forecast_adjust` edge that does not
exist in the code — `aggregation.py` has zero imports beyond the
standard library. One real Test-Coverage GAP (Ramping vs. Blending
divergence mid-ramp is never asserted, only their convergence at
`w=1`).

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
|---|---|---|---|
| 1 | §1: `ShadyPvSumSensor`'s sum covers every configured string, no double-count/silent drop | PASS | `sum_values` (`aggregation.py:49-61`) is a plain, generic `sum()` over whatever iterable of `float \| None` it's handed — no per-string filtering, ordering, or length assumption of its own, so there is no code path inside this function that could double-count or silently drop a member of the list it's given. (Whether `coordinator.py` actually hands it every configured string's value is that module's concern, correctly out of this audit's Scope per the Out-of-Scope note.) |
| 2 | §2: the FC-sum function sums the *corrected* forecast, not raw baseline FC | PASS | `sum_values` is type-agnostic about what its inputs represent — it has no way to distinguish "corrected" from "raw" values, so correctness here is entirely a question of what `coordinator.py` passes in. `coordinator.py`'s own comment (`coordinator.py:641`, cited already in AUDIT-0005) states directly: `aggregation.sum_values is only ever handed already-[adjusted values]`, i.e. `coordinator.py` performs the correction (via `string_computation.py`/`forecast_adjust.py`) before calling into `aggregation.py`, never the reverse. This is also the reason `aggregation.py` has no dependency on `forecast_adjust.py` at all — see the FAIL below. |
| 3 | §3: whole-day sum genuinely covers all 288 slots including past ones, distinct from §4 | PASS | `day_energy_total_wh` (`:70-76`) takes no `now`/timestamp argument at all and sums every slot in whatever `slot_values` iterable it receives unconditionally — structurally incapable of excluding past slots, unlike `remaining_energy_wh` which explicitly filters by `timestamp >= now`. The two functions are cleanly distinct, not a shared implementation with a flag. |
| 4 | §4: "remaining today" restricts to not-yet-elapsed slots, boundary matches the ADR's `>=` | PASS | `remaining_energy_wh` (`:79-92`) filters with `timestamp >= now` — the exact operator ADR-005 §4 specifies ("slots ... still in the future relative to 'now' — i.e. ... where `slot_timestamps[i] >= now`"), not `>` — the slot exactly at `now` is included, matching the ADR's own boundary choice precisely, not just "roughly the right half." |
| 5 | §5: actual-energy daily integral has a real reset mechanism, not just "small numbers early in the day" | PASS, for this module's actual (narrow) share of the guarantee | Per ADR-005's own Implementation notes, the stateful running total and the reset trigger both live outside `aggregation.py` (`cache.py`/`coordinator.py` — correctly excluded from this audit's Scope, covered by AUDIT-0003). This module's only obligation toward reset correctness is `trapezoidal_energy_increment`'s documented `previous=None -> 0.0` behavior, which is exactly what lets a reset "take" (a fresh integral starts contributing nothing until a second sample exists) — confirmed present (`:115-116`) and tested (`test_no_previous_sample_contributes_zero`). |
| 6 | §6: same reset check for the FC-energy integral, confirm one shared mechanism, not two that could drift | PASS | `trapezoidal_energy_increment` is the one function both `ShadyPvEnergyIntegralSensor` and `ShadyFcEnergyIntegralSensor` call (per ADR-005 §6: "the same integral treatment as §5") — there is only one implementation in `aggregation.py`, not two independently-written copies, so there is no aggregation-layer mechanism that could drift between the two sensors. |
| 7 | ADR-006 §1: does this module read the ramping/blending switch, or stay agnostic? | PASS — stays fully agnostic | `grep -in "mode\|ramping\|blending"  aggregation.py` finds nothing — no function in the intraday section takes a mode parameter or branches on one. `ramp_weight`/`intraday_correction_factor` are called identically regardless of mode; `crossfade` is simply not called at all under Ramping. The switch itself lives in `coordinator.py` (`self._intraday_correction_mode`, confirmed in AUDIT-0005) — matching the module-boundary doc's placement of "Application" in `coordinator.py`, "the pure ramp math" here. |
| 8 | ADR-006 §1a: `ramp_weight`'s boundary behavior exact | PASS | `ramp_weight` (`:128-145`): `active_slots_since_reset <= 0` returns exactly `0.0` (not a near-zero linear value); `active_slots_since_reset == ramp_slots` returns exactly `1.0` via `min(1.0, ramp_slots/ramp_slots)`; linear in between. Boundary values verified as exact equalities in tests, not approximate (`test_zero_at_reset`, `test_exactly_one_at_ramp_slots`), re-run live during this audit and passing. |
| 9 | ADR-006 §1b: `intraday_correction_factor`+`crossfade` are genuinely two different transition behaviors, not one path with a flag | PASS | Structurally two separate functions with disjoint signatures — `intraday_correction_factor` never takes an "old" value and knows nothing of blending; `crossfade` is the only function that combines an old and a new prediction. Per the module docstring (`:169-171`), Ramping calls `intraday_correction_factor` **once**, Blending calls it **twice** (once per side) and *additionally* calls `crossfade` — genuinely more/different work under Blending, not a branch inside a shared function. |
| 10 | ADR-006 §2: `intraday_correction_cutoff` is a magnitude clamp, not directional | PASS | `clamped_ratio = min(1.0 + cutoff, max(1.0 - cutoff, ratio))` (`:176-178`) — the same `cutoff` value bounds both the upper (`1+cutoff`) and lower (`1-cutoff`) side symmetrically around neutral (`1.0`); there is no separate "over-performance cutoff" vs. "under-performance cutoff" parameter. `test_ratio_clamped_to_upper_cutoff_before_ramping`/`test_ratio_clamped_to_lower_cutoff_before_ramping` both use the identical `cutoff=0.3` for opposite-direction ratios (2.0 and 0.1), confirming symmetric magnitude behavior empirically, not just by reading the formula. |
| 11 | ADR-006 §3 cross-ref: the two timespans are parameters, not hardcoded | PASS | `ramp_slots` (`ramp_weight`'s second argument) and `intraday_correction_cutoff` (`intraday_correction_factor`'s fourth argument) are both plain function parameters with no default value and no module-level constant standing in for either anywhere in the file. |
| 12 | ADR-006 §4: `crossfade`/`intraday_correction_factor` operate per string, no cross-string logic mixed in | PASS | Both functions' full signatures are scalar `float` in, scalar `float` out (`intraday_correction_factor(float, float, float, float) -> float`; `crossfade(float, float, float) -> float`) — no list/array/dict-of-strings parameter anywhere, so there is no way for cross-string aggregation logic to have leaked in even accidentally; the two "halves" of this file operate on structurally incompatible input shapes (the ADR-005 half takes iterables/sequences of per-slot or per-string values, the ADR-006 half takes bare scalars), which is itself evidence they haven't blurred together. |
| 13 | ADR-006 §5 cross-ref: module placement matches (functions live in `aggregation.py`, not `coordinator.py` or a new file) | PASS | All three functions (`ramp_weight`, `intraday_correction_factor`, `crossfade`) are defined in `aggregation.py` under the `# -- ADR-006 §1a/§1b/§2/§5` section header (`:125-198`) exactly as ADR-006 §5 specifies — "no new module needed." |

### Additional finding, outside the enumerated criteria: stale module-dependency edge

Neither ADR-005's local module diagram nor this audit's checklist
explicitly asked about `aggregation.py`'s own *imports*, but verifying
Criterion 2 (does the FC-sum use corrected values) required checking
whether `aggregation.py` calls `forecast_adjust.py` itself, and it
does not — at all:

```
$ grep -n "forecast_adjust\|^from\|^import" custom_components/shady/aggregation.py
39:from __future__ import annotations
41:from collections.abc import Iterable, Sequence
42:from datetime import datetime
```

**Both** ADR-005's own module diagram (`adr/005-...md:169`,
`aggregation --> forecast_adjust`) **and** ADR-000 §3's canonical,
"current" module graph (`adr/000-...md:162`, the same edge) claim this
dependency exists. It does not, and — per Criterion 2's evidence above
— it structurally *shouldn't*: the correction step happens in
`coordinator.py` before values ever reach `aggregation.py`'s purely
numeric `sum_values`/`day_energy_total_wh`/`remaining_energy_wh`. This
reads as a leftover from an earlier design (plausibly pre-dating
ADR-014's `string_computation.py` split, when it may once have seemed
natural for the aggregation layer to call the correction step
directly) that was never removed from either diagram when the actual
call chain settled into its current, correction-happens-upstream
shape. This is a documentation defect in two ADRs, not a code defect —
flagged as **FAIL** against diagram accuracy, with a recommendation
below.

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | A test per ADR-005 sensor function that would fail if a configured string were silently dropped | COVERED | Every `TestSumValues`/`TestDayEnergyTotalWh` test uses distinguishable, non-degenerate values (e.g. `[100.0, 200.0, 50.0]`, or four `600.0`s where dropping even one identical value still changes the total from 200 to 150) — any silent drop of an element changes the asserted result, so these are genuine drop-detecting tests, not merely happy-path totals. |
| 2 | A midnight-boundary test for both integral resets, at the exact reset instant | COVERED, for this module's actual (narrow) scope | The full reset-at-midnight mechanism is `cache.py`'s responsibility (AUDIT-0003), correctly out of this file's scope. This file's only reset-adjacent contribution — `trapezoidal_energy_increment(None, current) == 0.0` — is directly tested (`test_no_previous_sample_contributes_zero`), which is the exact instant a reset "takes." |
| 3 | A test proving `ramp_weight` hits the exact boundary values at `0` and at `ramp_slots` | COVERED | `test_zero_at_reset` (`agg_mod.ramp_weight(0, 12) == 0.0`) and `test_exactly_one_at_ramp_slots` (`agg_mod.ramp_weight(12, 12) == 1.0`) assert exact equality at both named boundaries, distinct from `test_linear_partway_through_the_ramp`'s interior-monotonicity check. |
| 4 | Ramping's and Blending's outcomes asserted as genuinely different from the same provider-update scenario, not just both independently plausible | **GAP** | `TestBlendingConvergesToRampingSteadyState` proves the two modes **converge** to the identical value once `w_blend` reaches `1` — a real and valuable regression guard, but it is the one point in the ramp where the two modes are *supposed* to agree, not where they differ. No test in this file computes both modes' outputs at a **partial** ramp weight (e.g. `w=0.3`, immediately after a provider update) and asserts they diverge — which they structurally must: Ramping's `new_value * intraday_correction_factor(..., ramp_weight=0.3, ...)` ignores any prior value entirely, while Blending's `crossfade(old_prediction, new_prediction, 0.3)` is still mostly `old_prediction`. A regression that accidentally made `coordinator.py` call `crossfade` even under Ramping mode (or vice-versa) would not be caught by any test in this file — only the converged endpoint is guarded. |
| 5 | A test for `intraday_correction_cutoff` at both clamp directions, for both a positive and negative correction, confirming magnitude-based behavior | COVERED | `test_ratio_clamped_to_upper_cutoff_before_ramping` (ratio 2.0 -> clamped to 1.3) and `test_ratio_clamped_to_lower_cutoff_before_ramping` (ratio 0.1 -> clamped to 0.7) use the identical `cutoff=0.3` for opposite-direction raw ratios, directly demonstrating symmetric, magnitude-based clamping rather than two independently-tunable directional bounds. |
| 6 | A test proving Blending *converges* to Ramping's steady state, per TASK-0013's stated intent | COVERED | `TestBlendingConvergesToRampingSteadyState.test_converged_crossfade_matches_plain_ramping_multiply` (`test_aggregation_intraday.py:140-152`) computes both sides independently (Ramping: `new_value * effective_factor`; Blending: `crossfade(old*old_factor, new*effective_factor, ramp_weight(12,12))`) and asserts exact equality — still present, still passing, still a genuine two-sided computation rather than a tautology. |

## Live re-execution

Installed `pytest` and ran both test files directly during this audit
(no `homeassistant` dependency needed — both are pure, zero-mocking
modules per their own docstrings):

```
$ python3 -m pytest tests/test_aggregation.py tests/test_aggregation_intraday.py -q
...................                                                     [100%]
19 passed
```

## Note: two functions in this file fall outside this task's own checklist

`diagnostic_accuracy` and `sum_predicted` (ADR-004 §2/§2b) live in this
same file but are not mentioned anywhere in AUDIT-0007's Audit
Criteria or Test-Coverage Criteria list — the task's own Goal names
exactly two decisions to verify ("ADR-005's cross-string sums/integrals
and ADR-006's intraday ramp/crossfade math"), not three. Their tests
live in `tests/test_diagnostics_compare_regressions.py` rather than
either file in this audit's Scope. Carrying this forward as a note for
AUDIT-0008 (Diagnostics), which is better positioned to verify them in
the context of their actual caller — not treated as a gap in *this*
audit, since it was never in its checklist.

## Candidate Follow-Ups (not created — proposed only)

1. **Documentation fix, two ADRs:** remove the `aggregation -->
   forecast_adjust` edge from both ADR-005's module diagram and
   ADR-000 §3's canonical module graph, or replace it with an accurate
   description of the actual chain (`coordinator.py` corrects values
   via `string_computation.py`/`forecast_adjust.py` *before* handing
   them to `aggregation.py`'s sum functions). No code change needed —
   `aggregation.py`'s actual behavior is correct and, per Criterion 2's
   evidence, arguably *more* correct (cleaner purity boundary) than
   what the diagrams describe.
2. **Test addition, optional:** a `TestRampingVsBlendingDivergeMidRamp`
   test alongside the existing convergence test — same shape, but
   asserting `!=` at e.g. `ramp_weight=0.3` instead of `==` at `w=1` —
   would close Test-Coverage Gap #4 directly and cheaply, using data
   already set up in the existing convergence test.

## Delivered Artifacts (for the task file)
- `tasks/AUDIT-0007-aggregation-findings.md` (this file)
