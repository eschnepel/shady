# Task: A `None` in the Freshest Slots Was Frozen as "Validated" (Diagnostic "selected actual" Missing for a Whole Run)

- **Status:** review
- **Related ADRs:** [ADR-007a §4 (Amendment 2026-10-07), ADR-007a §1/§6]
- **Dependencies:** \[TASK-0037-pinned-slot-pool-not-yet-elapsed-freeze,
  TASK-0037-patch-4-follow-latest-diagnostic-slot-toggle\]

## Goal

Human report (2026-10-07): in the `compare_regressions` diagnostic chart the
"selected actual" entry (and with it every `accuracy` percentage) is missing
while the follow-latest-slot toggle is on. The human then exported the same
diagnosed slot twice, followed and pinned, and uploaded both CSVs plus a
screenshot; the two exports are byte-identical except for `is_pinned`, and both
have `pv_selected` blank. After an HA restart the entry appeared and the
accuracy values were correct (e.g. `wls2` accuracy 0.83 against a measured 29.5
W). Intraday correction was off.

Root cause, established by reading the exports and reproducing against the real
`Cache` class (a day of simulated 5-minute ticks, 06:30-13:58 UTC):

- All seven of today's slot-pool rows (offsets -3 to +3) had no PV, including
  three slots that ended 13-23 minutes before the export, while yesterday's rows
  were intact. So the cache held `None` for every slot since the run started —
  not just for the newest one.
- `Cache._fetch_and_store` widens `validated` over the whole fetched span even
  when `fetch_fn` returned `None` for its trailing slots, and `_validate_range`
  never re-queries a validated index. The recorder compiles a slot's 5-minute
  statistic ~10-15 s after the slot ends; the coordinator's 5-minute tick is not
  aligned to the wall clock. A tick phase within that delay of a boundary makes
  every tick read the just-ended slot too early, freeze it, and (the phase being
  constant until restart) every slot after it too. Simulation: tick at +40 s →
  all slots present; tick at +3 s → all `None`.
- The same freeze is reachable through `_intraday_energy_window` (validates
  through `now`'s own in-progress slot every tick; simulated with intraday on →
  all `None`) and, by code reading, through `get_pinned_slot_pool`'s pinned
  branch (`index_for(now)` inclusive). Hence a cache-level fix, not a per-caller
  one.

This is the same family as `TASK-0037` (permanent freeze of a slot fetched too
early), but `TASK-0037` capped one caller and left the invariant itself
violated; it also cannot help a slot that *has* ended but is not compiled yet.

## Acceptance Criteria

Cache (zero-mocking, `tests/test_cache_core.py`, fake `fetch_fn` + injected
`clock`):

- Given a fetch for a slot that ended 3 s before the injected clock and
  `fetch_fn` returns `None` for it, when the same slot is read again after
  `fetch_fn` can serve it (clock +30 s), then the real value is returned — the
  slot was re-fetched, not frozen.
- Given the same slot but the clock is 11 minutes (beyond `SETTLE_GRACE`) past
  its end and `fetch_fn` returns `None`, then it is validated: two reads call
  `fetch_fn` once for it.
- Given a slot that has not ended yet (in progress), when a range through it is
  read twice, then the second read re-fetches only the unsettled tail, not the
  whole range, and the slot is never marked validated.
- Given `fetch_fn` returns `None` for a slot *followed by* a real value (an
  interior gap), then the gap is validated immediately (not re-queried).
- Given `fetch_fn` returns a `str` (e.g. `"unavailable"`) for the newest slot,
  then it is validated immediately, however recent.
- Given a sensor with `to_index=None` (pushed), then behavior is unchanged
  (existing `TestPushGuardAndPushOnlySensor` untouched and green).
- Given a fetch whose trailing slots are all settled, then `validated` and the
  number of `fetch_fn` calls are exactly what they were before this task (no
  existing cache test changes).
- Given the first fetch for a sensor (`current is None`, whole-window fetch)
  whose trailing slots are unsettled `None`s, then `validated` ends at the last
  settled slot, including the degenerate empty case (`to_index == start - 1`);
  `trim()`, `invalidate()` and the `validated_range` accessor handle it.

Coordinator / end-to-end:

- Given a replay of the tick-phase simulation (ticks every 5 minutes from an
  early-morning start, `fetch_fn` simulating the recorder's compile delay, using
  the real `get_pinned_slot_pool` and `get_time_range` calls the coordinator
  makes), when the tick phase is +3 s and +40 s, then in both cases every
  elapsed slot of today reads its real value after the run. Must fail against
  the pre-fix `cache.py` for +3 s.
- Given intraday correction on (`_intraday_energy_window` through `now`), then
  the slot that was in progress at one tick holds its real value at the next
  tick.
- Given `Cache` is constructed by the coordinator, then it receives the
  coordinator's own injectable `now` as `clock` (so coordinator tests that
  already inject a fake clock see consistent behavior).

## Scope boundary (former Open Decision D1, resolved 2026-10-07)

This task stops the *permanent* freeze; it deliberately does not try to make a
tick display a value the recorder does not have yet at that instant (the tick
computes once and the result is cached until the next tick, so with a bad phase
the chart would still lack "selected actual" for the newest slot). The human
resolved that by changing what triggers the tick rather than by lagging the
followed slot or adding a timer: the 5-minute interval is replaced by the
recorder's own `EVENT_RECORDER_5MIN_STATISTICS_GENERATED` — see
`TASK-0041-recorder-synchronized-slot-trigger` (ADR-006 §1a and ADR-004 §2i
Amendments). Both tasks together fix the reported symptom; this one is also
independently valuable (it removes the same freeze for the intraday window and
the pinned branch). Ship order: this task first, then `TASK-0041`.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `SETTLE_GRACE` constant, `clock`
  constructor parameter, settling-tail rule in `_fetch_and_store`.
- `custom_components/shady/coordinator.py` — pass `clock` into `Cache(...)`
  (around the `Cache(self._window_days, self._fetch_fn, local_tz=...)` call) —
  nothing else.
- `tests/test_cache_core.py` (new class for the settling rule),
  `tests/test_coordinator.py` (tick-phase replay, clock pass-through).

## Definition of Done

- Tests green; each new cache/replay test shown to fail against the pre-fix code
  before being shown to pass against the fix.
- `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` clean across the whole tree (not only edited files),
  `mdformat --check` clean on every edited `.md` file.
- Coverage of `cache.py` and `coordinator.py` measured before and after; no
  drop.
- ADR-007a §4 Amendment present (done at task creation); `tasks/adr-summary.md`
  accurate.
- `tasks/INDEX.md` log row single-line, no bare pipe inside code spans in table
  cells (a known mdformat pitfall recorded in the log).
- `Delivered Artifacts` block completed and accurate.
- No new external dependency; `tasks/DEPENDENCIES.md` unchanged.

## Consumed Interfaces

<!-- Read from the current code on `initialcode`; refresh from the dependency
     tasks' Delivered Artifacts if either changes before this starts. -->

- `cache.Cache.__init__(self, window_days: int, fetch_fn: FetchFn, local_tz: _tzinfo = UTC) -> None`
  from `custom_components/shady/cache.py` (→ task:
  TASK-0037-pinned-slot-pool-not-yet-elapsed-freeze)
- `cache.Cache._fetch_and_store(self, sensor_id: str, start: int, end: int) -> None`
  and
  `Cache._validate_range(self, sensor_id: str, start: int, end: int, *, allow_historical_backfill: bool = False) -> None`
  from `custom_components/shady/cache.py` (→ task: TASK-0037 lineage, patch-2
  added `allow_historical_backfill`)
- `Cache.index_for(...)`, `Cache.timestamp_for(...)`,
  `Cache.get_time_range(...)`, `Cache.get_pinned_slot_pool(..., *, reference)`
  from `custom_components/shady/cache.py`
- `ShadyCoordinator._advance_followed_diagnostic_slot(self, now: datetime) -> None`
  from `custom_components/shady/coordinator.py` (→ task:
  TASK-0037-patch-4-follow-latest-diagnostic-slot-toggle)
- Test loader `tests.support._load` and the existing fake-`fetch_fn` patterns in
  `tests/test_cache_core.py`

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
