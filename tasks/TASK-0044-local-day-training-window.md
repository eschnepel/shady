# Task: Training Window on Local Day Boundaries, Slots Stay UTC-Clock (ADR-008 §2)

- **Status:** done
- **Related ADRs:** \[ADR-008 §2 (training pools), ADR-007a §1 (trim floor),
  ADR-007a §6 (pinned floor), ADR-002 §1 (recalibration trigger)\]
- **Dependencies:** [TASK-0043-wire-cache-trim-into-recalibration]

> **Accepted 2026-10-11** by the human (grill of `TASK-0045`, G1): `review` →
> `done`, **superseded in part by `TASK-0045c`**. Still standing: the UTC-clock
> slot index and the smoothing-radius window extension. Replaced: the local
> midnight-to-midnight days (23/25-hour DST days) give way to exact 24-hour days
> counted back from the reference day.

> **Gate:** requested by the human in chat, 2026-10-10 ("All should be in local
> time ... which includes the training window"); the slot semantics were decided
> by the human the same day: **"UTC-clock slots with local day boundaries"**.
> `TASK-0043` is still in `review` (not accepted); this task builds on its
> single training-window definition (`Cache._training_window_start_index`).

## Goal

`Cache.get_regression_pools` anchors its window on `now`'s calendar fields _read
as UTC_ (`datetime(now.year, now.month, now.day, tzinfo=UTC)`), so the training
window is `window_days` **UTC** days even though everything user-facing is local
(ADR-005 §3, TASK-0039). Make the window `window_days` complete **local** days
ending at local midnight today, derived from `reference` as an _instant_
(`reference.astimezone(local_tz).date()`), so a UTC `now` (the button) and a
local `now` (the midnight trigger) for the same instant give the same window.

**What does not change (the human's decision):** a model slot `s` is still the
**UTC clock** slot `s` (`index % 288`). The fitted models, the forward fill,
`_predict_day_slots`, the backfill, the provider push and
`target_cell_temperature_for_slot` all stay as they are; solar-time stability
across a DST change is the reason (a UTC-indexed model does not mix solar times
when the clock changes). Only which days the pool is made of changes.

## Acceptance Criteria

- Given a configured local timezone, when `get_regression_pools(reference)` is
  built, then column `i` of each block is one complete local day (oldest first),
  and row `s` of it is the sample at **UTC-clock slot `s`** within that local
  day: absolute index `L_i + ((s - L_i mod 288) mod 288)` where `L_i` is the
  absolute index of that day's local midnight. Verified with a fetch function
  returning the slot's own UTC slot-of-day, so the pool is constant down every
  row, in UTC, Berlin, New York and Auckland.
- Given the same instant expressed in UTC or in the local timezone, then the
  pools are identical (no dependence on `reference`'s own tzinfo).
- Given the window, then it starts at local midnight of `today - window_days`
  and ends at local midnight today (never reads today).
- Given the timezone is UTC, then every result is identical to before this task
  (all existing tests unchanged).
- Given a DST day inside the window (23 or 25 local hours), then a UTC slot that
  does not occur in that local day reads `NaN` (23 h), and only the first 288
  slots of a 25 h day are used; no slot is ever read twice, and neighbors never
  reach outside the window.
- Given `trim(reference)` at any time of day in any timezone, then the floor is
  the same local-day boundary the pool starts at, nothing the pool reads is
  discarded, and no re-fetch is needed.
- Given the recalibration at local midnight (`now` in local time) or the button
  (`now` in UTC), then the same window is trained and trimmed.
- Given a smoothing radius `r`, then the pool validates the window widened by
  `r` slots at each end (its neighbor cells are real values wherever the source
  has them, independent of cache history) and `trim` keeps those `r` slots, so
  no recalibration has to re-fetch them.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` (`_training_window_start_index`,
  `get_regression_pools`, `trim` docstring, pin floor)
- `tests/test_cache_regression_pools.py`,
  `tests/test_coordinator_recalibration_trim.py`
- `adr/008-numpy-backend-and-cache-array-accessor.md` (§2 amendment),
  `adr/007a-cache-storage-and-accessor-design.md`, `tasks/adr-summary.md`

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected)

## Consumed Interfaces

- `Cache._training_window_start_index(reference)`, `Cache.trim(reference)`,
  `Cache.get_regression_pools(sensor_ids, smoothing_radius, reference)` from
  `custom_components/shady/cache.py` (→ task:
  TASK-0043-wire-cache-trim-into-recalibration)
- `Cache._local_date(moment)`, `Cache._local_midnight(day)` from
  `custom_components/shady/cache.py` (→ task: TASK-0039)

## Delivered Artifacts

Status is `review`: **not yet accepted by the human.** Depends on `TASK-0043`,
itself still in `review`.

- `custom_components/shady/cache.py` →
  - new `Cache._training_day_starts(self, reference: datetime) -> list[int]` —
    `[L_0, ..., L_window_days]`: absolute index of local midnight of each of the
    window's days, plus local midnight today as the exclusive end; today is
    `self._local_date(reference)` (the instant's local date).
  - `Cache._training_window_start_index(self, reference: datetime) -> int` —
    signature unchanged; now local midnight of
    `local_date(reference) - window_days` (was: `reference`'s calendar fields
    read as UTC). `trim` and `get_regression_pools` both use it.
  - `Cache.get_regression_pools(sensor_ids, smoothing_radius, reference=None)` —
    signature, shape `(288, window_days * (2*radius+1))` and column layout
    unchanged. Rows stay UTC-clock slots; columns are now complete local days:
    row `s` of local day `i` is `L_i + ((s - L_i) mod 288)`; cells for a UTC
    slot a 23-hour DST day lacks are `NaN`; a 25-hour day uses its first 288
    slots.
  - `Cache.trim(reference=None)` — signature unchanged; floor =
    `_training_window_start_index(reference)`; the pin floor is now
    `index_for(local midnight of (pinned_reference - window_days))`.
  - `Cache._window_length()` still exists (used by the validation path); no
    longer used for the window.
- **Not changed (the decision):** `coordinator.py` (fit, forward fill,
  `_predict_day_slots`, backfill, provider push,
  `target_cell_temperature_for_slot`), the fitted models, the diagnostics. UTC
  installs behave exactly as before (every pre-existing test passes unchanged
  except those that pinned the old floor, restated in `TASK-0043`).
- Tests → `tests/test_cache_regression_pools.py`: new
  `TestTrainingWindowIsLocalDaysWithUtcClockSlots` and the trim guard extended
  over UTC, Berlin, New York and Auckland (+ Kolkata for the window);
  `tests/test_coordinator_recalibration_trim.py`: window helper now local,
  `TestModelSlotsStayUtcClockWithLocalDayBoundaries` (the real coordinator fetch
  path builds, in Berlin, New York and Auckland, exactly the UTC install's
  pool), button (UTC `now`) vs midnight (local `now`) train the same window.
- `adr/008-numpy-backend-and-cache-array-accessor.md` → §2 Amendment 2026-10-10
  (**Decided by: human**); `adr/007a-...md` §1 amendment reworded;
  `tasks/adr-summary.md` → rolling-window bullet.
- External dependencies added: none; `tasks/DEPENDENCIES.md` unchanged.
- **Test-strength checks (mutations, each caught):** `today` from the UTC date
  of the instant (8 failures) or from `reference`'s own tzinfo date (4); rows on
  the local clock instead of the UTC-clock slot (4 in the cache tests, plus the
  end-to-end coordinator test); no DST `slot_exists` mask (1); window one local
  day late (81); trim floor on the old UTC-day definition (33); trim ignoring
  the pin (1). The new tests were first run against the pre-change code (15
  failing; the slot-semantics and UTC-regression guards pass there by design).
- **Smoothing neighbors (added 2026-10-10 at the human's request; same task, not
  yet accepted):** neighbor cells just outside the window used to read whatever
  the shadow array held there (documented as `NaN`, true only for a freshly
  filled cache), so fitted edge values differed between a restart and steady
  state. `Cache.get_regression_pools` now validates the window **widened by
  `smoothing_radius` slots at each end**, and
  `Cache.trim(reference=None, smoothing_radius=0)` keeps those slots (floor =
  `_training_window_start_index(reference) - smoothing_radius`);
  `ShadyCoordinator._trim_cache` passes `self._smoothing_radius`. Effects,
  verified: the pool is identical for an empty and a pre-filled cache; the
  validated range is exactly the extended window; a not-yet-settled tail
  (today's first slots at 00:01) stays `NaN` and unvalidated so the next read
  asks again (ADR-007a §4 settled-end rule); without the radius `trim` would
  force a head re-fetch every recalibration (test). Measured steady-state series
  size is now `window_days x 288 + 2 x smoothing_radius` (580 for window 2,
  radius 2; the pushed forecast 1154). Fitted values change only for those edge
  cells, near local midnight where the weighting suppresses them. One existing
  test pinned the old `NaN`-edge design (`TestDayBoundaryWraparound`) and was
  restated. ADR-008 §2 (Decided by: human) and ADR-007a §1 amended.
- **Open finding, not changed (diagnostics):** the human accepts a different
  integer slot index for the diagnostics as long as the *timestamp* is
  equivalent. Measured (index-valued fetch, Europe/Berlin): in a window without
  a DST change the diagnostics' pool and the model's pool contain identical
  timestamps for the same instant. In a window that contains a DST change they
  do not: `get_pinned_slot_pool` places every day at
  `oldest day's local midnight + day_offset x 288 + slot_of_day`, so on the
  pinned day itself local slot 120 reads 11:00 local after a spring-forward
  (10:00 expected), one hour from the diagnosed timestamp, while the model's
  UTC-slot row is correct. Not introduced by this task (TASK-0039 / TASK-0015b
  behaviour), affects roughly `window_days` days after each clock change. A fix
  would anchor the day placement on the pinned day. No task created.
- **Verification (after the smoothing change):** `pytest` 996 passed; `mypy`,
  `ruff`, `mdformat` clean. Mutations all caught: trim ignoring the radius (35
  failures), coordinator not passing it (3), pool validating the window only
  (44), extending the tail only (44) or the head only (11), trim keeping twice
  the radius (1).
