# Task: Cache-Owned Threading Lock for Loop-Thread Readers (Former TASK-0041 D4)

- **Status:** review
- **Related ADRs:** [ADR-007a §4 and §5, ADR-000 §6 (zero-mocking tier)] — an
  ADR-007a amendment (a threading contract for `Cache`) is **not written yet**:
  the Lead Agent writes it, with `Decided by: human`, once the human approves
  this task at Gate 2.
- **Dependencies:** [TASK-0037-patch-5-no-freeze-of-unsettled-tail] (recommended
  to ship after `TASK-0041-recorder-synchronized-slot-trigger` too, to avoid
  editing the same functions in parallel)

## Goal

`Cache` has no locks. After `TASK-0041`, cache-touching *executor* jobs are
serialized by a coordinator-owned `asyncio.Lock` (`async_run_cache_job`). That
cannot protect against **loop-thread readers**: `sensor.py` (lines 158 and 171
at the time of writing) calls into the cache from the event loop while an
executor job may be extending the value lists, updating `validated`, or running
`trim()` (which shifts the window). An `asyncio.Lock` cannot be used there —
`Cache` methods are synchronous, a worker thread cannot await it, and a loop
thread that blocked on it would deadlock the loop — and `cache.py` must not
import the coordinator in any case (ADR-007a: pure, zero-mocking tier).

**Status of the evidence: a hazard identified by code reading, not a
demonstrated corruption.** Single list operations are atomic under the GIL; an
offset computed across a concurrent `trim()` is not. The human decided
(2026-10-07) to treat it as its own follow-up task rather than fold it into
`TASK-0041`. The first deliverable is therefore a deterministic reproducer (see
criteria); if none can be built, the Worker reports that to the Lead Agent
instead of adding a lock on faith, and the task is closed as "hazard not
reproducible; documented".

## Design (proposed, for Gate 2)

A `threading.RLock` owned by `Cache` (stdlib only), held for **in-memory state
only** and **never across `fetch_fn`**, so a loop-thread read can never block
behind a recorder query:

- Public readers and mutators take the lock for the in-memory part.
- `_validate_range` becomes double-checked: (1) under the lock, compute the
  missing range; (2) release, call `fetch_fn`; (3) re-acquire, re-compute what
  is still missing, write only that, and widen `validated` from the *current*
  state, not the pre-fetch snapshot (so a concurrent writer's wider range is
  never shrunk). Two threads may both fetch the same range; the data is
  identical and the result consistent — correctness over de-duplication.
- `TASK-0037-patch-5`'s settling-tail rule (`SETTLE_GRACE`, injected `clock`) is
  applied in step (3) and must not change.

## Acceptance Criteria

All in `tests/test_cache_core.py` (zero-mocking; threads synchronized with
`threading.Event`/`Barrier` inside a fake `fetch_fn`, no sleeps):

- Given a `fetch_fn` that blocks on an event, when thread A is inside it, then a
  reader on thread B (a pushed series and an already-validated pull series)
  returns without waiting for A — the lock is not held across `fetch_fn`.
- Given thread A paused inside `fetch_fn` for a range and thread B concurrently
  fetching an overlapping range to completion, then after A resumes the cache
  holds consistent values and `validated` covers the union (never shrinks).
- Given a reader on thread B interleaved with `trim()` on thread A at every step
  the harness can force, then B never returns a value belonging to a different
  slot than the one requested.
- Given the reproducer in the first criterion fails against the unlocked code
  (shown before the fix is applied), then it passes with the lock; if it cannot
  be made to fail, see Goal.
- Given all existing cache tests, then they are unchanged and green, and `Cache`
  still imports nothing from the coordinator or Home Assistant.
- Given `TASK-0041`'s `async_run_cache_job` is still in place, then nothing in
  this task depends on it or removes it (the two layers are complementary: the
  job lock serializes whole jobs and the coordinator's other shared state; this
  lock protects the cache's own state against loop-thread readers).

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `__init__`, `_validate_range`,
  `_fetch_and_store`, the public readers/mutators, `trim`, `invalidate`.
- `tests/test_cache_core.py` — new test class for the threading contract.
- `adr/007a-cache-storage-and-accessor-design.md` — threading-contract amendment
  (Lead Agent, after Gate 2); `tasks/adr-summary.md`.

## Definition of Done

- Tests green; the new reproducer shown failing against the pre-change code.
- `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` clean across the whole tree; `mdformat --check` clean
  on every edited `.md` file.
- Coverage of `cache.py` measured before and after; no drop.
- ADR-007a amended and `tasks/adr-summary.md` accurate before merge.
- `tasks/INDEX.md` log row single-line, no bare pipe inside code spans.
- No new external dependency (`threading` is stdlib); `tasks/DEPENDENCIES.md`
  unchanged.
- `Delivered Artifacts` block completed and accurate.

## Consumed Interfaces

<!-- Fill from TASK-0037-patch-5's Delivered Artifacts before this starts. -->

- `cache.Cache.__init__`, `Cache._fetch_and_store`, `Cache._validate_range`,
  `Cache.get_time_range`, `Cache.get_pinned_slot_pool`, `Cache.invalidate`,
  `Cache.trim`, `Cache.validated_range` from `custom_components/shady/cache.py`
  (→ task: TASK-0037-patch-5-no-freeze-of-unsettled-tail, which adds `clock` and
  the settling-tail rule)
- Loop-thread callers for context only (not edited): `sensor.py` cache reads

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
