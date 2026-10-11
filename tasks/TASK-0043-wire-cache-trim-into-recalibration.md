# Task: Wire `Cache.trim()` Into the Recalibration Trigger (ADR-007a §1)

- **Status:** todo
- **Related ADRs:** \[ADR-007a §1 (trimming), ADR-007a §6 (pinned floor),
  ADR-002 §1 (recalibration trigger), ADR-008 §2 (training pools)\]
- **Dependencies:** [TASK-0042-cache-internal-threading-lock]

> **Gate:** discovered by the Lead Agent during `TASK-0042` (2026-10-09), not
> requested by the human. Do not start until the human has approved this task.

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

<!-- Filled by the Worker AFTER implementation. -->
