# Audit Task: Coordinator

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** \[ADR-002 §1, ADR-002 §1a, ADR-002 §2, ADR-002 §3, ADR-002
  §4, ADR-002 §5, ADR-012 §4, ADR-000 §5, ADR-001 §4a, ADR-003c §1, ADR-003c §2,
  ADR-003c §3, ADR-003c §4, ADR-003c §5, ADR-003c §6, ADR-003c §7, ADR-006 §1a,
  ADR-006 §1b, ADR-006 §4\]
- **Dependencies:** [] (TASK-0010 + 3 patches, TASK-0014, TASK-0017, TASK-0015b
  extended this file; all `done`)
- **Origin:** `coordinator.py` is the single largest file in the project (92K)
  and has the longest extension history of any module: TASK-0010 (base) + 3
  patches, then extended in place by TASK-0013 (intraday), TASK-0014
  (temperature-forecast learned model), TASK-0015b (diagnostics wiring), and
  refactored by TASK-0017 (logic relocated out to `string_computation.py`).
  Highest drift-risk file in the project for this audit pass.

## Goal

Verify `coordinator.py` still matches ADR-002's recalibration-vs-recompute split
after six rounds of extension/refactor, that ADR-014's relocation (TASK-0017)
actually left `coordinator.py` in the "narrower role" ADR-014 §4 describes
rather than silently regaining fit/predict logic on a later patch, and that the
temperature-forecast learned model (ADR-003c, which lives almost entirely in
this file) is correctly gated.

## Scope — Source Files

- `custom_components/shady/coordinator.py`

## Scope — Test Files

- `tests/test_coordinator.py`
- `tests/test_coordinator_intraday.py`
- `tests/test_coordinator_temperature_forecast.py`

## Out of Scope

- The actual fit/predict math now living in `string_computation.py` (covered by
  AUDIT-0006) — this audit only checks that `coordinator.py` *calls* it
  correctly and doesn't duplicate it.
- `cache.py`'s accessor implementations (covered by AUDIT-0003) — this audit
  only checks call sites.
- `diagnostics/base.py`'s construction-time coordinator reference (covered by
  AUDIT-0008) — this audit only checks the registration/ push side in
  `coordinator.py`.

## Audit Criteria

- [ADR-002 §1] Does model recalibration actually trigger at local midnight
  **and** on manual button press, both paths converging on the same
  recalibration code, not two divergent implementations?
- [ADR-002 §1a] Does the startup-ordering guard genuinely handle the documented
  case (a config entry's entities may not exist yet) — is there a real
  guard/wait mechanism, not just a `try/except` that swallows the symptom?
- [ADR-002 §2] Does forecast recompute fire on model update **and** on every
  baseline update, as two distinct trigger paths both landing on one recompute
  function — and per TASK-0010-patch-1, does recalibration completion itself now
  also trigger a recompute (was this a gap the patch closed, and does it still
  hold)?
- [ADR-002 §3] Does the forecast horizon genuinely cover today (remaining slots
  only, not the whole day retroactively) plus tomorrow (full day), matching
  exactly what §3 specifies?
- [ADR-002 §4 / ADR-012 §4 cross-ref] Is "retaining raw baseline FC via push"
  implemented as this document's specific instance of ADR-012 §4's generic push
  policy — same push mechanism, not a second one reinvented here?
- [ADR-002 §5] Does the actual module-responsibility split (what
  `coordinator.py` does vs. what it delegates) match what §5 documents as of
  ADR-014's later relocation — i.e. is §5 itself now stale relative to
  TASK-0017's refactor, and if so does `coordinator.py` match ADR-014 §4's
  newer, narrower description instead?
- [ADR-000 §5] Does `ShadyCoordinator.strings()` (TASK-0010-patch-2) return the
  documented `list[tuple[int, str]]` shape, and is it the **only** public
  string-enumeration surface (no second, divergent enumeration method added by a
  later task)?
- [ADR-001 §4a, cross-ref] Is `recency_decay_max` (TASK-0010-patch-3) actually
  threaded from config through to the `recency_weight_i` call in
  `regression/base.py` — a real value flow, not a parameter that's accepted but
  never read?
- [ADR-003c §1] Is the learned temperature-forecast model scoped to exactly the
  cell and ambient tiers, with the third (weather) tier explicitly bypassing the
  learned model per §1?
- [ADR-003c §2] Is there one learned model per 5-minute-of-day slot, on the same
  grid ADR-001 §3a defines — not a coarser or finer grid?
- [ADR-003c §3] Is the predictor source read from the documented dedicated,
  explicit config-flow field (not inferred/guessed from other config)?
- [ADR-003c §4] Is the prediction actually applied where §4 specifies, and does
  `_predict_target_slot_temperature`'s per-tier dispatch match the documented
  per-tier behavior (weather unchanged, cell no-uplift, ambient uplifted)?
- [ADR-003c §5] When no predictor is configured, does **both** the forward
  (training) and reverse (prediction) transform degrade together to "no
  temperature source at all" — genuinely identical code path, not two
  separately-coded no-op branches that could drift apart?
- [ADR-003c §6] Does the learned model reuse existing cache/pool machinery (no
  new storage concept introduced in `coordinator.py` itself for this feature)?
- [ADR-003c §7] Is the predictor push (registering the temperature predictor to
  receive live updates) genuinely automatic/generic per ADR-012 §4's policy,
  requiring no new per-predictor registration code?
- [ADR-006 §1a / §1b, cross-ref] Does the intraday correction factor's rolling
  window and ramp actually live in `aggregation.py`'s pure functions (per
  AUDIT-0007) with `coordinator.py` only orchestrating calls to them — no
  duplicate ramp/window math inlined here?
- [ADR-006 §4] Is the intraday correction applied per string, per future slot,
  exactly as §4 specifies (not per-aggregate, not for past/already-elapsed
  slots)?

## Test-Coverage Criteria

- Is there a test that would fail if `_refit_sync` stopped calling recompute
  after recalibration (ADR-002 §2 / TASK-0010-patch-1's own regression target)?
- Is there a test for the startup-ordering guard (ADR-002 §1a) that actually
  simulates entities-not-yet-existing, or does coverage only exercise the
  already-initialized case?
- Is there an end-to-end test proving the unconfigured-predictor case (ADR-003c
  §5) is **byte-identical** to no-temperature-source-at-all for both directions
  together (per TASK-0014's own stated test intent) — confirm this specific test
  still exists and still asserts equality, not just "doesn't crash"?
- Is there a test proving `strings()` (ADR-000 §5) is not shadowed or duplicated
  by a second enumeration path added in TASK-0014/0015b/0017?
- Is there a differential test for `apply_magnitude_weight` actually being wired
  through from `coordinator.py`/`string_computation.py` into
  `regression/base.py` (per TASK-0014's Delivered Artifacts, "a broken True-mode
  fit would produce a detectably different, wrong prediction") — confirm this
  test still exists and still fails under a deliberately broken wiring, i.e.
  re-verify its differential design rather than just its current pass/fail
  status.
- Given the ADR-002 §5 vs. ADR-014 §4 tension noted above: is there any test
  whose name or docstring still asserts the *pre-TASK-0017*
  module-responsibility split, which would now be testing a stale description
  rather than current behavior?

## Consumed Context (attached to the auditor)

- `tasks/adr-summary.md`
- `adr/002-coordinator-update-strategy.md` (full text)
- `adr/012-provider-architecture.md` §4 (cross-ref only)
- `adr/000-coding-standards.md` §5
- `adr/001-empirical-shading-model.md` §4a (cross-ref only)
- `adr/003c-temperature-forecast-via-learned-model.md` (full text)
- `adr/006-intraday-deviation-correction.md` §§1a, 1b, 4 (cross-ref only)
- `adr/014-string-computation-module.md` §4 (for the ADR-002 §5 vs. ADR-014 §4
  staleness check above)
- All files listed under Scope above
- `tasks/TASK-0010-*.md` (all four files), `tasks/TASK-0013-*.md`,
  `tasks/TASK-0014-*.md`, `tasks/TASK-0015b-*.md`, `tasks/TASK-0017-*.md` —
  Delivered Artifacts blocks only
- `tasks/DEPENDENCIES.md`

## Definition of Done

- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering test
  named, or GAP explained.
- Findings written to `tasks/AUDIT-0005-coordinator-findings.md`, including an
  explicit note on whether ADR-002 §5 needs an amendment to reflect ADR-014 §4's
  later, narrower description (flag for human decision — do not amend the ADR
  yourself).
- No code changes made.

## Delivered Artifacts

<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->

- `tasks/AUDIT-0005-coordinator-findings.md` — full findings: 17/17 Audit
  Criteria PASS or PASS-with-noted-nuance (one PARTIAL folded into the
  ADR-staleness discussion), 6 Test-Coverage Criteria (5 COVERED, 1 GAP). No
  behavioral FAIL. Two ADR-text-staleness items flagged for human decision
  (ADR-002 §5's "two registrations" Con no longer matches the code's single
  merged listener; ADR-014 §4's "all four methods delegate to
  `string_computation.py`" overclaims for `_predict_day_basis`/`_clamp_basis`,
  whose exception is already justified in TASK-0017's own Acceptance Criteria
  but not reflected in the ADR text itself). No code changes made.
