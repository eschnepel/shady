# Task: Cache-Owned Threading Lock for Loop-Thread Readers (Former TASK-0041 D4)

- **Status:** done
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

- **Refreshed from TASK-0037-patch-5's Delivered Artifacts (2026-10-08):**
  `Cache.__init__(self, window_days: int, fetch_fn: FetchFn, local_tz: _tzinfo = UTC, clock: Callable[[], datetime] | None = None)`,
  module constant `SETTLE_GRACE`, and `Cache._settled_end` from
  `custom_components/shady/cache.py` (→ task:
  TASK-0037-patch-5-no-freeze-of-unsettled-tail, `done` 2026-10-08; the
  coordinator already passes `clock=lambda: self._now()`).

- **From TASK-0041's Delivered Artifacts (2026-10-08, informational — not a
  dependency):** `ShadyCoordinator.async_run_cache_job(fn, *args)` in
  `custom_components/shady/coordinator.py` serializes every *executor-thread*
  cache job on a loop-held `asyncio.Lock` (kept until the thread has finished).
  It does **not** cover loop-thread readers (`sensor.py` reads), which is this
  task's remit; `Cache` still never sees that lock. Slot-job probes call
  `Cache.get_time_range` from that executor path.

## Delivered Artifacts

- `custom_components/shady/cache.py` →
  - private `Cache._lock: threading.RLock` (created in `__init__`), never
    exposed
  - module-private decorator `_locked` (PEP 695 generic) applied to
    `Cache.validated_range`, `_ensure_sensor`, `_write`, `_read`, `push`,
    `invalidate`, `trim`
  - `Cache._validate_range(...)` — same signature; decides the missing head/tail
    spans under the lock, then fetches with it released
  - `Cache._fetch_and_store(self, sensor_id: str, start: int, end: int) -> None`
    — same signature; `fetch_fn` and the settled-end computation run **outside**
    the lock; it then re-reads the current validated range and writes only
    indexes that are still unvalidated (stale data never overwrites newer data),
    widening `validated` from the current state (never shrinks)
  - new `Cache._is_validated(current, index) -> bool` (static, private)
  - read phases of `get_time_range`, `get_pinned_slot_pool` and the gather step
    of `get_regression_pools` run under the lock
  - Public signatures, return types and single-thread behavior are unchanged
- `custom_components/shady/coordinator.py` → docstring of `async_run_cache_job`
  only (no longer claims `Cache` is not thread-safe; names the cache's own
  lock).
- Tests (`tests/test_cache_core.py`): `_GatedList`,
  `_pause_writer_mid_mutation`, `_call_on_thread`, class `TestThreadingContract`
  (6 tests): prepend reproducer, trim reproducer, single-slot `_read`,
  lock-not-held-across-`fetch_fn`, stale-overlapping- fetch-never-overwrites,
  `cache.py` imports no Home Assistant / coordinator.
- `adr/007a-cache-storage-and-accessor-design.md` → §4 Amendment 2026-10-09
  (threading contract) written before the code; header pointer;
  `tasks/adr-summary.md` paragraph added.
- External dependencies added: none (`threading`/`functools` are standard
  library).
- **Reproducer result (before any fix):** the hazard is real, so the task is not
  closed as "not reproducible". With a real `list` subclass pausing a writer
  between the list mutation and the `_list_offset` update (no mocks, no sleeps
  for synchronization): a prepend made slot 100 read `None` instead of `1.0`; a
  trim made slot 102 return slot 104's value `5.0`; a stale overlapping fetch
  overwrote the newer one. All three fail on the unlocked code and pass with the
  lock.
- **Test-strength checks:** mutation "hold the lock across `fetch_fn`" is caught
  by `test_a_reader_is_not_blocked_while_another_thread_is_inside_fetch_fn`;
  mutation "drop the lock from `_read`" is caught by
  `test_a_single_slot_read_is_guarded_on_its_own`; the six tests passed in 25
  consecutive runs.
- Verification: `pytest` 870 passed (864 + 6 new); `mypy` clean (71 files);
  `ruff check` / `ruff format --check` clean (212 files); `mdformat --check`
  clean on edited `.md`; coverage `cache.py` 97 % → 97 % (12 → 12 uncovered
  lines, all pre-existing).
- **Finding, out of scope (new `TASK-0043`):** `Cache.trim()` is never called by
  any production code, although ADR-007a §1 says the coordinator calls it once
  at the recalibration trigger; no earlier task scheduled it. The reproducer
  exercises `trim` directly. `TASK-0043` also records the off-by-one pitfall of
  wiring it naively.
