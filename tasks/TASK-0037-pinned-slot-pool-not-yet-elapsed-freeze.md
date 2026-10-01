# Task: `get_pinned_slot_pool` Permanently Freezing a Not-Yet-Elapsed Slot at `None` (Diagnostic "selected" Series Missing)

- **Status:** done
- **Related ADRs:** [ADR-007a §6 (Amendment 2026-09-22)]
- **Dependencies:** [TASK-0015b-diagnostics-select-and-scatter-sensors]

## Goal

Bug report (human): the diagnostic scatter sensors' `series` attribute (ADR-004
§2) reliably showed the historical per-offset training scatter (`"-1"`/`"0"`/
`"1"`, ...) but never the `"selected {method}"`/`"selected actual"` entries —
not intermittently, persistently, for any auto-tracking (not manually pinned)
diagnosed slot.

Root cause: `cache.py`'s `get_pinned_slot_pool` (ADR-007a §6) validates the
*whole* day-range spanned by its rolling window in one call per sensor —
including, while auto-tracking (or pinned to today itself), the as-yet-unlived
remainder of "today", not just whatever part of it has actually happened.
`_validate_range` (§4) widens a sensor's `to_index` permanently once a range has
been fetched, and never re-queries an index already inside a previously
validated span — even one that came back `None` only because it was queried
*before* it had actually happened yet. The very first `get_pinned_slot_pool`
call of the day therefore validated (and, for a real recorder-backed sensor,
permanently froze at `None`) every one of today's not-yet-elapsed slots for the
rest of the day. `diagnostics/compare_regressions.py`'s `_selected_value`
(`get_time_range`) reads the diagnosed slot's own baseline/actual-yield value
through that same permanently-poisoned validated range — set up moments earlier
in the same `compute()`/`extra_fit()` call by `_gather_pool`'s own
`get_pinned_slot_pool` call — so it always read back `None`, and the
`"selected ..."` series entries were dropped every time
(`_append_selected_series` returns early when `fc_selected is None`).

## Acceptance Criteria

- Given `get_pinned_slot_pool` is called auto-tracking (no pin, or a
  future-dated pin falling back to today) with a `slot_of_day` that has not yet
  elapsed as of `reference`, when it validates its window, then it does not
  validate past `reference`'s own last *complete* slot
  (`index_for(reference) - 1`) — mirroring `ShadyCoordinator.diagnosed_slot()`'s
  own auto-tracking formula.
- Given the same call is genuinely pinned (`pinned_reference` resolves, not the
  today-fallback), when it validates its window, then it validates through
  `reference` itself, inclusive — mirroring `diagnosed_slot()`'s pinned branch
  (the pinned index used directly, not `index_for(now) - 1`).
- Given a not-yet-elapsed slot was excluded from validation on an earlier call
  (so nothing was ever fetched/frozen for it), when a later call's `reference`
  has advanced past that slot, then that call fetches it for real — it is not
  permanently `None`.
- Given every existing behavior for an already-elapsed slot (any pinned-to-past
  date, or an auto-tracked slot that has genuinely elapsed), then it is
  unchanged — this is a fix to premature validation of not-yet-elapsed data
  only, not a change to the window's own resolution or shape.
- `get_pinned_slot_pool` gains an optional `reference: datetime | None = None`
  keyword-only parameter (defaulting to `datetime.now(UTC)`), the same
  testability pattern `get_regression_pools` already established — no existing
  caller (production or test) is affected unless it opts in.
- `compare_regressions.py`'s `_gather_pool` passes
  `reference=self._coordinator.now()` through, so diagnostics resolves this the
  same injectable-clock way every other diagnostics computation already does.
- The full test suite passes; `tests/test_cache_pinned_slot_pool.py` gains
  coverage proving the not-yet-elapsed-slot cap and its self-healing on a later
  call, and its own pre-existing real-wall-clock-dependent tests are made
  deterministic via the new `reference` parameter rather than left
  time-of-day-flaky against the new cap.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `get_pinned_slot_pool` (all three
  overloads + implementation)
- `custom_components/shady/diagnostics/compare_regressions.py` — `_gather_pool`
- `tests/test_cache_pinned_slot_pool.py` — new coverage + determinism fixes
- `adr/007a-cache-storage-and-accessor-design.md` — §6 amended

## Definition of Done

- Tests green (full suite: 640 passed) · `tasks/adr-summary.md` updated ·
  ADR-007a §6 amended · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- `mypy`/`ruff check`/`ruff format --check` clean on every edited file
- No new external dependencies

## Consumed Interfaces

- `Cache._validate_range`/`Cache.index_for` (`custom_components/shady/cache.py`)
  — unchanged; this task only changes what `get_pinned_slot_pool` passes as the
  validated range's upper bound (→ ADR-007a §4)
- `ShadyCoordinator.now()`/`diagnosed_slot()`
  (`custom_components/shady/coordinator.py`) — the injectable clock and the
  pinned-vs-auto-tracking split this task's cap mirrors (→ ADR-004 §5)

## Delivered Artifacts

- `custom_components/shady/cache.py` — `get_pinned_slot_pool` (all overloads +
  implementation) gained `reference: datetime | None = None`; the validated
  range's upper bound is now `min(window_end_index, last_readable_index)`, where
  `last_readable_index` is `index_for(reference)` while genuinely pinned or
  `index_for(reference) - 1` while auto-tracking.
- `custom_components/shady/diagnostics/compare_regressions.py` — `_gather_pool`
  passes `reference=self._coordinator.now()` to `get_pinned_slot_pool`.
- `tests/test_cache_pinned_slot_pool.py` — three pre-existing tests
  (`test_matches_today_anchored_window`,
  `test_pinned_to_today_itself_still_anchors_on_it`,
  `test_future_pin_matches_the_unpinned_today_anchored_result`) made
  deterministic via an explicit late-in-day `reference`; new
  `TestGetPinnedSlotPoolNeverPermanentlyFreezesANotYetElapsedSlot` proves the
  fix (a not-yet-elapsed slot is dropped now, then populated once a later call's
  `reference` has advanced past it).
- `adr/007a-cache-storage-and-accessor-design.md` — §6 amended with the bug's
  root cause and the fix's rationale; header "Last updated" bumped.
- `tasks/adr-summary.md` — `get_pinned_slot_pool`'s summarized signature/
  behavior updated to match.
- No external dependencies added.
