# Audit Task: Coordinator (Round 2)

- **Status:** review
- **Group:** `custom_components/shady/coordinator.py`
- **Related ADRs:** [ADR-002, ADR-007, ADR-014 §4, ADR-000 §3]
- **Source Tasks:** \[TASK-0009-coordinator-refresh-cycle,
  TASK-0009-patch-1-listener-dedup, TASK-0021-fitted-model-cache-location,
  TASK-0023-entity-layer-cache-access-boundary,
  TASK-0027-module-diagram-and-docstring-accuracy\]

## Scope

Re-audits round 1's `AUDIT-0005-coordinator` (2 ADR-text-staleness items, 1
acknowledged-not-scheduled coverage gap) against the current checkout.
`coordinator.py` changed materially in this remediation round (net +69/-69 per
`git diff --stat f7fcef8 HEAD` from `TASK-0021`'s model-cache relocation and
`TASK-0023`'s read-only `cache` property) — this is a genuine re-audit of
changed logic, not just a staleness re-check, plus the primary write-up for a
new diagram finding.

## Findings — Code Logic vs. ADRs

- **Round-1 item 1 — single merged listener (RESOLVED).** `AUDIT-0005` found
  ADR-002 §5's Consequences text still described two separate config-entry
  update listeners where the code had already been consolidated into one.
  `TASK-0009-patch-1`'s fix is confirmed still in place:
  `adr/002-coordinator- update-strategy.md` now describes a single merged
  listener (grep for "listener" in the file shows the consolidated wording, no
  remaining reference to two registrations). **PASS.**
- **Round-1 item 2 — ADR-014 §4 overclaim (RESOLVED).** `AUDIT-0005` found
  ADR-014 §4 implying `_predict_day_basis`/`_clamp_basis` would be fully
  replaced by `string_computation.py`'s new orchestration functions, when they
  are actually kept as intentional exceptions with unchanged signatures and
  callers. `adr/014-string-computation-module.md:137-157` now explicitly
  documents this: *"`_fit_string`, `_fit_temperature_string`,
  `_predict_day_basis`, and `_clamp_basis` all keep their existing signatures
  and existing callers unchanged"* and separately calls out
  `_predict_day_basis`/`_clamp_basis` as "the two exceptions." Cross-checked
  against `string_computation.py`'s own docstring (fixed by `TASK-0027`,
  re-confirmed below) — consistent. **PASS.**
- **NEW FINDING — ADR-000 §3's diagram has a false `cache --> aggregation` edge
  and is missing the real `coordinator --> aggregation` edge.**
  `adr/000-coding-standards.md:112` draws `cache --> aggregation`. This does not
  correspond to any real import: `cache.py` imports only `.regression.base`
  (confirmed via `grep`); `aggregation.py` has zero internal imports in either
  direction (confirmed: no `from .`/`import .` lines in the file at all).
  Neither module imports the other. Meanwhile the diagram has **no edge at all**
  for the relationship that actually exists: `coordinator.py:118` does
  `from .aggregation import (...)` — a genuine, direct dependency that is simply
  absent from the diagram. The most likely explanation is a transcription slip
  during `TASK-0027`'s edit pass (which correctly added the real
  `coordinator --> cache` and `init --> coordinator` edges but appears to have
  written `cache` instead of `coordinator` for the aggregation edge) — noted
  here as context, not as an accusation requiring further investigation; the fix
  is the same either way. **Proposed fix (single reasonable path):** replace the
  `cache --> aggregation` edge with `coordinator --> aggregation`.
- No other deviations found in `coordinator.py`'s refresh-cycle orchestration,
  per-string parallel fit/predict dispatch, or debounce/backoff logic — all
  match round 1's confirmed reading, re-spot-checked.

## Findings — Test Coverage vs. ADRs

- **Round-1 item — acknowledged-not-scheduled gap (unchanged).** Round 1 noted a
  theoretical second enumeration path for detecting duplicate string
  configuration was untested, and explicitly judged a dedicated regression test
  impractical relative to its value (per
  `tasks/archived/AUDIT-REMEDIATION-INDEX.md`'s own acknowledged-items list). No
  change in risk profile since; still acknowledged, not re-opened here.
- **NEW FINDING — `invalidate_models()`'s call-site behavior is untested at the
  coordinator level.** `TASK-0021` made `_refit_sync` (`coordinator.py:733`)
  call `self.cache.invalidate_models()` unconditionally, once, before the
  per-string fit loop — an intentional **behavior change** (the task's own text:
  *"not just a pure relocation... a string whose fit has been persistently
  failing... previously served a stale... prediction from the last successful
  fit; will now correctly have no model"*). The storage-layer contract for
  `invalidate_models()` itself is well covered (`tests/test_cache_core.py:438`,
  `TestFittedModelCacheInvalidation`), but
  `grep -n "invalidate_models" tests/test_coordinator.py` returns **zero
  matches** — no coordinator-level test establishes a previously-valid model via
  a successful fit, then drives a subsequent fit failure for that same string,
  and asserts the model is actually gone afterward (not merely still-absent,
  which is all the nearest existing test,
  `test_no_recompute_attempted_when_fitting_fails`, actually checks — that
  test's coordinator never has a model to begin with, since its fixture has no
  baseline provider configured at all, so it cannot distinguish "never set" from
  "was valid, then correctly cleared"). This is a genuine coverage gap for a
  genuine behavior change, not a documentation nit: a future regression that
  removed or misplaced the `invalidate_models()` call (e.g. moved it inside a
  per-string conditional, or dropped it) would not be caught by the existing
  suite.

## Open Questions

None. The diagram edge has exactly one reasonable fix; the coverage gap has
exactly one reasonable fix (add the missing test).

## Definition of Done (for Phase 8)

- `adr/000-coding-standards.md`'s §3 diagram replaces the
  `cache --> aggregation` edge with `coordinator --> aggregation`
- A new coordinator-level test establishes a valid model for a string (via a
  successful `_refit_sync` with a working baseline provider), then triggers a
  second `_refit_sync` where that string's provider is made to fail, and asserts
  `coordinator.cache.get_model(...)` returns `None` afterward — added to
  `tests/test_coordinator.py`
- Full test suite still green
- No new ADR conflicts introduced
- `Delivered Artifacts` block below completed and accurate

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8. -->
