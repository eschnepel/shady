# Task: Wire `Cache.trim()` Into the Recalibration Trigger (ADR-007a §1)

- **Status:** done
- **Related ADRs:** \[ADR-007a §1 (trimming), ADR-007a §6 (pinned floor),
  ADR-002 §1 (recalibration trigger), ADR-008 §2 (training pools)\]
- **Dependencies:** [TASK-0042-cache-internal-threading-lock]

> **Accepted 2026-10-11** by the human (grill of `TASK-0045`, G1): `review` →
> `done`.

> **Gate:** discovered by the Lead Agent during `TASK-0042` (2026-10-09), not
> requested by the human. Do not start until the human has approved this task.
> **Approved** by the human in chat, 2026-10-10 ("Work on Task 43").

## Goal

ADR-007a §1 says `coordinator.py` calls `cache.trim()` "exactly once, at the
ADR-002 §1 recalibration trigger (midnight or button)". **No production code
calls it** (only tests do) and no earlier task ever scheduled it. Consequence:
every sensor's series list, offset map and shadow array only ever grow (about
288 entries per sensor per day), the configured `window_days` retention floor is
never enforced, and §6's pinned-reference retention floor is exercised only by
tests. The growth is small per day but unbounded for a long-running install.

## Pitfall for the implementer (found by the Lead while reading the arithmetic)

`trim()`'s default floor is `index_for(reference) - window_days * 288 + 1`. At
the recalibration (`_handle_midnight` at 00:01) `index_for(now)` is today's
first slot, so the floor is **one slot after** the first slot of the oldest
training day (`get_regression_pools`'
`window_start_day_index = today_start - window_days * 288`). A naive
`trim(reference=now)` would silently drop slot 0 of the oldest training day and
turn it into `NaN` in the next training pool. The change must therefore pick the
reference so that **nothing `get_regression_pools` or `get_pinned_slot_pool` can
read is discarded**, and prove it.

## Acceptance Criteria

- Given a recalibration (`_handle_midnight` or the button) has run, then
  `cache.trim(...)` was called exactly once for it, never from the slot job
  (ADR-006 §1a) or a baseline update (ADR-002 §2).
- Given a cache with `window_days` full days of history, when the recalibration
  trims, then `get_regression_pools(...)` returns exactly the same arrays before
  and after the trim (no training slot lost, including slot 0 of the oldest
  day); this test fails if the naive `reference=now` is used.
- Given a pinned reference older than the live window, when the recalibration
  trims, then the pin's own window is still fully readable (ADR-007a §6).
- Given a series list for each sensor, when many days pass with a recalibration
  each day, then its length stays bounded by about `window_days * 288` plus the
  forecast horizon instead of growing.
- Given the trim runs, then it runs as part of the existing recalibration
  executor job (under `async_run_cache_job`), not on the event loop.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` (`_refit_sync`, or the call site that
  `_handle_midnight` and the button share)
- `tests/test_coordinator.py` and/or `tests/test_cache_core.py`
- `tasks/adr-summary.md`, ADR-007a §1 if the reference choice needs recording

## Definition of Done

- Tests green; each new behavioral test shown to fail against the pre-change
  code.
- `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` clean across the whole tree; `mdformat --check` clean
  on every edited `.md`.
- Coverage of `coordinator.py` and `cache.py` measured before and after; no
  drop.
- No open ADR conflicts; `Delivered Artifacts` block completed and accurate.
- Any new external dependency recorded in `tasks/DEPENDENCIES.md` (none
  expected).

## Consumed Interfaces

- `Cache.trim(self, reference: datetime | None = None) -> None` from
  `custom_components/shady/cache.py` (→ task:
  TASK-0042-cache-internal-threading-lock; now takes the cache's own lock for
  its whole body)
- `ShadyCoordinator._refit_sync(self, now: datetime) -> None`,
  `_handle_midnight`, `async_run_cache_job` from
  `custom_components/shady/coordinator.py` (→ task:
  TASK-0041-recorder-synchronized-slot-trigger)

## Delivered Artifacts

Reworked 2026-10-10 after the human pointed out that nothing justifies trimming
part of a training day (the first version compensated for `trim`'s rolling floor
with a shifted reference in the coordinator; the root cause is now fixed in
`Cache`). Status is `review`: **not yet accepted by the human.**

- `custom_components/shady/cache.py` →
  - new `Cache._training_window_start_index(self, reference: datetime) -> int` —
    absolute index of slot 0 of the oldest day of the training window for
    `reference`; the one definition of that boundary. As delivered here it
    anchored on `reference`'s calendar fields read as UTC; `TASK-0044` made it
    whole *local* days (this record is otherwise unchanged).
  - `Cache.trim(self, reference: datetime | None = None, smoothing_radius: int = 0) -> None`
    — `smoothing_radius` added by `TASK-0044` (default 0, so earlier callers are
    unchanged); the floor is now `_training_window_start_index(reference)`
    (whole-day, ADR-007a §1's `today - window_days`) instead of the rolling
    `index_for(reference) - window_days x 288 + 1`; the pin floor is
    `index_for(local midnight of the pin) - window_days x 288` (was `... + 1`).
  - `Cache.get_regression_pools(...)` — signature and results unchanged; it now
    reads its window start from `_training_window_start_index` (same value as
    before, one definition instead of two).
- `custom_components/shady/coordinator.py` →
  - `ShadyCoordinator._refit_sync(self, now: datetime) -> None` — unchanged
    signature; its last statement is `self._trim_cache(now)`, after
    `_accumulate_fc_energy(now)`. The only `.trim(` call in production, so it
    runs inside the existing `async_run_cache_job`, once per recalibration
    (button and `_handle_midnight` share it).
  - new `ShadyCoordinator._trim_cache(self, now: datetime) -> None` — calls
    `self.cache.trim(reference=now, smoothing_radius=self._smoothing_radius)`
    (radius added by `TASK-0044`); contained in `try`/`except Exception` and
    logged.
  - No public signature changes; no new imports.
- Tests →
  - `tests/test_coordinator_recalibration_trim.py` (new, 17 tests): once per
    recalibration (button, midnight, twice, never from the slot job /
    diagnostics tick / baseline update, single AST call site), inside
    `_refit_sync`, a raising trim is contained, the coordinator passes `now`,
    the training pool (UTC, Berlin, New York evening, mid-day) and the pinned
    pools (explicit pin; auto-tracking UTC / Auckland / New York) survive the
    trim with zero re-fetches, bounded size over ten days.
  - `tests/test_cache_regression_pools.py` — new
    `TestTrimNeverDiscardsTheTrainingPool` (17): for window 1 and 3, smoothing
    radius 0 and 2, at 00:00 / 00:01 / 14:37 / 23:55, the pool is identical and
    needs no re-fetch; the floor is exactly the oldest training day's slot 0.
  - `tests/test_cache_core.py` — **two existing tests restated** because they
    pinned the rolling floor: `TestTrimAdvancesOffsetWithoutOffByOne`
    (TASK-0002; same intent, whole-day semantics; plus two new tests: the floor
    does not move within a day, and advances by exactly 288 per day) and
    `TestThreadingContract::test_reader_never_sees_a_trim_halfway_through`
    (TASK-0042; same scenario shape, built around a day boundary).
- `adr/007a-cache-storage-and-accessor-design.md` → §1 Amendment 2026-10-10
  ("the trim floor is a whole-day boundary...") plus header pointer;
  `tasks/adr-summary.md` → "Trim floor" paragraph.
- External dependencies added: none; `tasks/DEPENDENCIES.md` unchanged.
- **Behavior change to be aware of:** series now stop growing. Steady state
  (measured, `window_days=2`): pulled training inputs 576 entries
  (`window_days x 288`), Shady's pushed forecast series 1152
  (`(window_days + 2) x 288`); before, +288 per day each, unbounded.
- **Verification:** `pytest` 906 passed (870 + 36); `mypy` clean (72 files);
  `ruff check` / `ruff format --check` clean (214 files); `mdformat --check`
  clean on the edited `.md` files; coverage unchanged (`coordinator.py` 99 %, 13
  uncovered lines; `cache.py` 97 %, 12 uncovered lines; all pre-existing).
- **Test-strength checks (mutations, each caught):** old rolling floor `+ 1` (23
  failures); rolling floor without `+ 1`, not day-aligned (13); training window
  start one day too early (3) or one slot too late (6); trim ignoring the pin
  (1); coordinator passing a shifted reference (2) or none (8). The new
  behavioral tests were also run against the pre-change code first (failing). (A
  first run of the mutation script silently applied nothing; it was caught from
  its error output and rerun.)
- **Local-time training window:** resolved by the human's decision (UTC-clock
  slots with local day boundaries) and delivered as
  `TASK-0044-local-day-training-window`, which builds on this task's single
  window definition. The prediction side did not need to change.
