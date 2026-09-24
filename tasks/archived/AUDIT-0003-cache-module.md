# Audit Task: Cache Module

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** \[ADR-007 §1, ADR-007 §2, ADR-007 §3, ADR-007a §1, ADR-007a
  §2, ADR-007a §3, ADR-007a §4, ADR-007a §5, ADR-007a §6, ADR-008 §2, ADR-008
  §3\]
- **Dependencies:** [] (TASK-0002 and TASK-0006 are `done`; TASK-0012,
  TASK-0013, TASK-0015b extended this file further)
- **Origin:** TASK-0002-cache-core-time-series-store,
  TASK-0006-cache-batched-regression-pool-accessor, and in-place extensions from
  TASK-0012, TASK-0013, TASK-0015b (`cache.py` is the single largest file in the
  project at 40K — extended by five separate tasks without ever being split)

## Goal

Verify `cache.py` still matches ADR-007's "owns all retained state, stays pure"
split and ADR-007a's storage/accessor design after five rounds of in-place
extension (regression pools, aggregate sensors, intraday state, diagnostics
pinned-slot pool), and that it has not silently regained orchestration logic
that ADR-007 §2 assigns to `coordinator.py`.

## Scope — Source Files

- `custom_components/shady/cache.py`

## Scope — Test Files

- `tests/test_cache_core.py`
- `tests/test_cache_pinned_slot_pool.py`
- `tests/test_cache_regression_pools.py`

## Out of Scope

- `coordinator.py`'s call sites into `cache.py` (covered by AUDIT-0005).
- The regression-pool accessor's *consumers* in `regression/` (covered by
  AUDIT-0002) — this audit only checks the accessor itself.

## Audit Criteria

- [ADR-007 §1] Does `cache.py` own all retained state (no module-level mutable
  state left behind in `coordinator.py` that should have moved here), and does
  it stay pure — no `homeassistant.*` imports, no `hass` parameter anywhere in
  this file?
- [ADR-007 §2] Has `coordinator.py` actually shrunk to orchestration-only as
  claimed, i.e. does `cache.py` contain zero fit/predict/business logic that
  belongs in `regression/`, `string_computation.py`, or `aggregation.py` — only
  storage and accessors?
- [ADR-007a §1] Is time-series storage index-addressable, and does every stored
  value genuinely support the three documented states (present /
  absent-not-yet-fetched / invalidated), not just two?
- [ADR-007a §2] Is there real validated-range tracking — i.e. can the cache
  distinguish "never fetched this range" from "fetched and empty" — and is that
  distinction actually used by any accessor, not just stored and ignored?
- [ADR-007a §3] Are writes split into the two documented mechanisms (push by
  Shady itself, invalidate by any caller), with genuinely different code paths
  and different effects on the validated range?
- [ADR-007a §4] Does initialization take an injected fetch function
  (dependency-injected, not hardcoded to one HA API call), and does validation
  actually catch up correctly when that function is called — i.e. does a fetch
  response widen the validated range as documented?
- [ADR-007a §5] Do all the accessor methods documented in this section exist
  with the documented signatures, and does each one respect the
  validated-range/three-state semantics from §1/§2 (no accessor bypassing them
  by reading raw storage directly)?
- [ADR-007a §6] Is the pinned diagnostic reference date genuinely a single,
  cache-wide value (not per-string, not per-caller), and is there exactly one
  write path for it?
- [ADR-008 §2] Does the batched regression-pool accessor return a real
  `numpy`-backed batch (not a Python list of per-slot arrays assembled by the
  caller), covering the *full* sweep in one call?
- [ADR-008 §3] Does the three-way accessor split described in this section (how
  `cache.py`'s accessors now divide responsibility) match what's actually
  exposed — i.e. are there exactly the documented accessor categories, with no
  leftover accessor from before the split still doing the old job in parallel?

## Test-Coverage Criteria

- Is there a test that would fail if the three-state value semantics (ADR-007a
  §1) collapsed to two states (e.g. "invalidated" silently behaving identically
  to "not yet fetched")?
- Is there a test for the validated-range boundary (ADR-007a §2) at exactly its
  edges (first/last index), not only well inside a fetched range?
- Is there a test proving `invalidate` and `push` (ADR-007a §3) have observably
  different effects on subsequent reads, not just that both can be called
  without error?
- Is there a test that injects a custom fetch function (ADR-007a §4) and asserts
  the validated range widens exactly as documented, including a
  partial-fetch-response case?
- Is there a test for the pinned diagnostic reference date (ADR-007a §6) that
  would fail if a second write silently created a second value instead of
  overwriting the one cache-wide value?
- Is there a test proving the batched regression-pool accessor (ADR-008 §2)
  returns results identical to calling the equivalent per-slot accessor in a
  loop — a differential correctness test, not just a shape/type check?
- Given `cache.py` was extended in place by TASK-0012/0013/0015b for
  aggregate/intraday/diagnostic state: do `tests/test_cache_core.py` and
  `tests/test_cache_regression_pools.py` still pass unmodified, or did a later
  extension require changing an earlier test's expected behavior (a signal worth
  flagging even if tests currently pass)?

## Consumed Context (attached to the auditor)

- `tasks/adr-summary.md`
- `adr/007-coordinator-cache-split.md` (full text)
- `adr/007a-cache-storage-and-accessor-design.md` (full text)
- `adr/008-numpy-backend-and-cache-array-accessor.md` §§2, 3
- All files listed under Scope above
- `tasks/TASK-0002-*.md`, `tasks/TASK-0006-*.md`, `tasks/TASK-0012-*.md`,
  `tasks/TASK-0013-*.md`, `tasks/TASK-0015b-*.md` — Delivered Artifacts blocks
  only, as a reference for which extension added which accessor
- `tasks/DEPENDENCIES.md`

## Definition of Done

- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering test
  named, or GAP explained.
- Findings written to `tasks/AUDIT-0003-cache-module-findings.md`.
- No code changes made.

## Delivered Artifacts

- `tasks/AUDIT-0003-cache-module-findings.md` → **1 confirmed FAIL**: the
  per-string/per-slot fitted-model cache lives in `coordinator.py`
  (`self._models`, `self._temperature_models`), not in `cache.py` as ADR-007 §1
  and ADR-007a §5 explicitly require — flagged for human decision (amend ADRs
  vs. relocate code), not resolved here. 9/10 other Audit Criteria PASS.
  Test-Coverage: 7 COVERED, 1 PARTIAL (no direct batched-vs-single-slot
  differential test), 1 N/A note. No code changes made.
