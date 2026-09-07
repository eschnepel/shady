# Audit Task: Aggregation Module

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** [ADR-005 §1, ADR-005 §2, ADR-005 §3, ADR-005 §4, ADR-005 §5, ADR-005 §6, ADR-006 §1, ADR-006 §1a, ADR-006 §1b, ADR-006 §2, ADR-006 §3, ADR-006 §4, ADR-006 §5]
- **Dependencies:** [] (TASK-0012, TASK-0013 are `done`)
- **Origin:** TASK-0012-aggregate-sensors (new module) extended in
  place by TASK-0013-intraday-deviation-correction (added the three
  intraday pure functions to the same file)

## Goal
`aggregation.py` holds two conceptually distinct decisions — ADR-005's
cross-string sums/integrals and ADR-006's intraday ramp/crossfade math —
that happen to share a file because both are pure, `hass`-free
computation. Verify each decision independently, and verify the two
haven't blurred into each other now that they're co-located.

## Scope — Source Files
- `custom_components/shady/aggregation.py`

## Scope — Test Files
- `tests/test_aggregation.py`
- `tests/test_aggregation_intraday.py`

## Out of Scope
- `sensor.py`'s exposure of aggregate/intraday values as HA entities
  (covered by AUDIT-0009).
- `coordinator.py`'s orchestration of *when* these functions get called
  (covered by AUDIT-0005) — this audit only checks the functions
  themselves.
- `cache.py`'s `IntradayState`/`IntradayBasis` storage (covered by
  AUDIT-0003) — this audit only checks the pure functions that consume/
  produce those shapes.

## Audit Criteria
- [ADR-005 §1] Does `ShadyPvSumSensor`'s underlying aggregation function
  sum current actual yield across exactly the configured strings, with
  no double-counting and no silent exclusion of a configured string?
- [ADR-005 §2] Does the corrected-forecast sum function sum the
  *corrected* forecast (post `forecast_adjust.py`), not the raw
  baseline FC?
- [ADR-005 §3] Does the whole-day sum genuinely integrate/sum across the
  full day (not just remaining slots — contrast with §4), matching the
  distinction the ADR draws between §3 and §4?
- [ADR-005 §4] Does the "remaining today" function genuinely restrict to
  not-yet-elapsed slots, and does its boundary (the current slot) match
  what §4 specifies (inclusive/exclusive of the current partial slot)?
- [ADR-005 §5] Does the actual-energy daily integral reset at midnight —
  is there a real reset mechanism, not just "the number happens to be
  small at 00:05 because little energy has accumulated"?
- [ADR-005 §6] Same reset-at-midnight check for the corrected-forecast
  energy integral, independently of §5 (confirm both reset via the same
  mechanism, not two different ones that could drift).
- [ADR-006 §1] Is the three-state config switch (off/ramping/blending)
  actually read by this module (or does this module stay agnostic and
  the switch lives entirely in `coordinator.py`/config — confirm which,
  since the module-boundary doc places "Application" in `coordinator.py`
  but the pure ramp math here)?
- [ADR-006 §1a] Does `ramp_weight(active_slots_since_reset, ramp_slots)`
  implement the documented rolling-window ramp starting from the first
  active slot, with the exact boundary behavior (weight at slot 0,
  weight once `ramp_slots` is reached) the ADR specifies?
- [ADR-006 §1b] Do `intraday_correction_factor` and `crossfade` together
  implement "ramping resets, blending crossfades" as two genuinely
  different transition behaviors on a provider update — not the same
  code path with a cosmetic flag?
- [ADR-006 §2] Does `intraday_correction_cutoff` act as a pure magnitude
  clamp (bounds the correction factor's absolute size) rather than a
  directional/sign-based clamp?
- [ADR-006 §3] Cross-ref only — confirm the two config-flow timespans
  (rolling window, ramp/blend duration) are consumed as **inputs** to
  these functions (parameters), not hardcoded constants inside
  `aggregation.py` itself.
- [ADR-006 §4] Does `crossfade`/`intraday_correction_factor` apply per
  string, per future slot — i.e. do these functions operate on a single
  string's data with no cross-string aggregation logic accidentally
  mixed in from the ADR-005 half of this file?
- [ADR-006 §5] Cross-ref only — confirm the module placement itself
  (these three functions living in `aggregation.py` rather than
  `coordinator.py` or a new file) matches what §5 documents.

## Test-Coverage Criteria
- Is there a test for each of the six ADR-005 sensor functions that
  would fail if a configured string were silently dropped from the sum
  (not just a two-string happy-path test)?
- Is there a midnight-boundary test for both daily-integral resets
  (ADR-005 §5/§6) at the exact reset instant, not just "well after
  midnight" and "well before midnight"?
- Is there a test proving `ramp_weight` at `active_slots_since_reset =
  0` and at `= ramp_slots` hits the documented boundary values exactly
  (ADR-006 §1a), not just monotonicity in between?
- Is there a test proving ramping's reset behavior and blending's
  crossfade behavior (ADR-006 §1b) are asserted as genuinely different
  outcomes from the same provider-update scenario, run through both
  modes?
- Is there a test for `intraday_correction_cutoff` (ADR-006 §2) at
  values on both sides of the clamp for both a positive and a negative
  correction factor, confirming it's magnitude-based?
- Per TASK-0013's own stated test intent ("Blending's freeze/crossfade
  and convergence-to-Ramping's-steady-state"): is there still a test
  proving blending *converges* to ramping's steady state over time, not
  just that both modes independently produce plausible output?

## Consumed Context (attached to the auditor)
- `tasks/adr-summary.md`
- `adr/005-aggregate-sum-and-integral-sensors.md` (full text)
- `adr/006-intraday-deviation-correction.md` (full text)
- All files listed under Scope above
- `tasks/TASK-0012-*.md`, `tasks/TASK-0013-*.md`
- `tasks/DEPENDENCIES.md`

## Definition of Done
- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering
  test named, or GAP explained.
- Findings written to `tasks/AUDIT-0007-aggregation-findings.md`.
- No code changes made.

## Delivered Artifacts
<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->
- `tasks/AUDIT-0007-aggregation-findings.md` — full findings: 13/13
  Audit Criteria PASS, plus one additional FAIL found outside the
  enumerated checklist (both ADR-005's module diagram and ADR-000 §3's
  canonical module graph claim an `aggregation --> forecast_adjust`
  edge that does not exist — `aggregation.py` has zero non-stdlib
  imports; confirmed via grep). 6 Test-Coverage Criteria (5 COVERED, 1
  GAP: Ramping vs. Blending divergence mid-ramp is never asserted,
  only their convergence at `w=1`). Both test files re-installed
  pytest and re-run live: 19/19 passed. No code changes made.
