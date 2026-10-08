# Task: Diagnostic Slot/Calendar-Day Math Silently `UTC`-Anchored Instead of HA's Configured Local Timezone (Pinned Slot Off By The Local `UTC` Offset)

- **Status:** done
- **Related ADRs:** \[ADR-004 §2a/§2g (unchanged, referenced — the
  `diagnosed_slot()`/pin concept whose `slot_of_day` this fixes), ADR-007a §6
  (unchanged, referenced — `get_pinned_slot_pool`'s own window anchor, reused
  as-is via its `reference` parameter), ADR-005 §5/§6 (unchanged, referenced —
  this ADR's own text already said "HA's local timezone"; the code did not
  actually do that until this task), ADR-002 §3 (unchanged, referenced — the
  forecast/pin horizon's "remainder of today")\]
- **Dependencies:** \[TASK-0015b-diagnostics-select-and-scatter-sensors,
  TASK-0037-pinned-slot-pool-not-yet-elapsed-freeze\]

## Goal

Bug report (human, MEST/CEST — `UTC+2`): the pinned diagnostic slot's own entry
only appeared in the diagnostic dashboard's scatter/comparison series once the
pin was moved two hours earlier than the time actually meant.

Root cause: every "which calendar day / what time of day is this" question
`coordinator.py`/`cache.py` asked was silently answered in `UTC`, never in Home
Assistant's actually-configured local timezone (`hass.config.time_zone`) — while
the absolute-instant slot-index arithmetic (`Cache.EPOCH`-anchored
`index_for`/`timestamp_for`) was, and remains, entirely correct regardless of
timezone. Two different `UTC`-relative framings of "today" then disagreed with
each other: `ShadyCoordinator.diagnosed_slot()`'s `slot_of_day` was
`index % SLOTS_PER_DAY` (slots since the nearest `UTC` midnight), while
`cache.get_pinned_slot_pool`'s window anchor was a plain `.date()` extraction
from a `UTC`-aware timestamp. A slot picked at a real local wall-clock time
therefore resolved to the wrong absolute slot — the diagnosed entry and its own
historical pool disagreed by exactly the local `UTC` offset (two hours, for
`UTC+2`). The same `UTC`-relative framing also affected `_tomorrow_end`'s
forecast/pin horizon, `fc_day_array`'s "today" (`ShadyFcDaySumSensor`'s own
genuine time-series dashboard export), the energy-integral midnight reset
(ADR-005 §5/§6's own text already said "HA's local timezone" — the code simply
didn't), `_apply_intraday_reset`'s same-day-basis check, and the CSV export's
training-window start date.

Deliberately **not** touched: the internal shading/temperature-model fitting
pipeline (`get_regression_pools`, `_predict_day_slots`, `_forward_fill_by_day`)
stays on its existing, self-consistent `UTC`-internal framing — it trains and
predicts using the same convention throughout, so it already produces
numerically correct real-world forecasts regardless of local timezone; changing
it would risk a train/predict mismatch for no accuracy benefit.

## Acceptance Criteria

- Given `ShadyCoordinator.__init__`, when `hass.config.time_zone` is a real IANA
  zone name, then it is resolved once, up front, into a real `tzinfo`
  (`zoneinfo.ZoneInfo`) and stored — falling back to `UTC` (this module's own
  prior, implicit behavior) if it is ever missing or unrecognized, never failing
  setup entirely over it (ADR-000 §8).
- Given `cache.py`'s `Cache`, when constructed, then it accepts an optional
  `local_tz` (defaulting to `UTC`, so every existing caller/test is unaffected
  unless it opts in) and uses it for every "which calendar date is this"
  question the pinned-diagnostic-reference machinery asks
  (`get_pinned_slot_pool`'s window anchor, `trim()`'s pinned floor) — never the
  arbitrary tzinfo a caller's own `now`/`reference` happens to carry.
- Given `ShadyCoordinator.diagnosed_slot()`, when it reports `slot_of_day`, then
  it is the diagnosed slot's position since *local* midnight (HA's configured
  timezone), not `index % SLOTS_PER_DAY` (`UTC` midnight) — agreeing with
  `get_pinned_slot_pool`'s own local-midnight-anchored window so the two resolve
  to the same absolute slot.
- Given `pin_diagnostic_slot`/`set_follow_latest_diagnostic_slot`, when either
  stores `cache.pinned_reference`, then it stores the pinned slot's *local*
  calendar date, not its `UTC` one.
- Given `_tomorrow_end` (ADR-002 §3's forecast/pin horizon), `fc_day_array`
  (ADR-005 §3's "today"), `_maybe_reset_energy_totals` (ADR-005 §5/§6's midnight
  reset), and `_apply_intraday_reset`'s same-day-basis check, then each resolves
  "today"/"local midnight" in HA's configured local timezone, not `UTC`'s.
- Given `diagnostics/compare_regressions.py`'s CSV export window-start-date
  resolution, then it resolves both "today" and the pinned date via the
  coordinator's own `local_date`, matching `get_pinned_slot_pool`'s anchor
  exactly.
- A new
  `ShadyCoordinator.local_date(moment) -> date`/`local_day_start(day) -> datetime`
  accessor pair is added (mirroring `now()`'s own public-read pattern) and added
  to `ShadyCoordinatorLike`'s Protocol, so a `DiagnosticMode` can resolve the
  same local calendar date without reaching into a `_`-prefixed coordinator
  attribute (ADR-000 §3).
- The full test suite passes; new coverage (`tests/test_local_timezone.py`,
  additions to `tests/test_cache_pinned_slot_pool.py`) proves the fix against a
  real `Europe/Berlin` (`UTC+2`, CEST) scenario, including the near-local-
  midnight boundary case where the local and `UTC` calendar dates disagree.
- `mypy`/`ruff check`/`ruff format --check` clean on every edited/created file.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` — `__init__`'s local-timezone
  resolution, `_tomorrow_end`, `diagnosed_slot`, `pin_diagnostic_slot`,
  `set_follow_latest_diagnostic_slot`, `fc_day_array`,
  `_maybe_reset_energy_totals`, `_async_persist_energy_state`,
  `_apply_intraday_reset`, `_push_provider_series`, new `local_date`/
  `local_day_start`
- `custom_components/shady/cache.py` — `Cache.__init__`'s new `local_tz`
  parameter, new `_local_date`/`_local_midnight`, `trim`, `get_pinned_slot_pool`
- `custom_components/shady/coordinator_like.py` — `ShadyCoordinatorLike`
  Protocol gains `local_date`
- `custom_components/shady/diagnostics/compare_regressions.py` —
  `_export_window_start_date`
- `tests/support_ha.py` — `FakeHomeAssistant.config.time_zone`
- `tests/test_cache_pinned_slot_pool.py`,
  `tests/diagnostics/test_compare_regressions.py` — fixture/stub updates
- `tests/test_local_timezone.py` — new

## Definition of Done

- Tests green (full suite: 782 passed) · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- `mypy`/`ruff check`/`ruff format --check` clean on every edited/created file
- No new external dependencies (`zoneinfo` is part of the Python standard
  library)

## Consumed Interfaces

- `Cache.index_for`/`Cache.timestamp_for` (`custom_components/shady/cache.py`) —
  unchanged; this task only changes which `tzinfo` a *calendar date* question is
  resolved against, never the absolute-instant slot-index arithmetic itself (→
  ADR-007a §1)
- `Cache.get_pinned_slot_pool`'s own `reference` parameter (→
  TASK-0037-pinned-slot-pool-not-yet-elapsed-freeze) — unchanged signature,
  reused as-is
- `ShadyCoordinator.now()`/`diagnosed_slot()`/`diagnostic_slot_timestamp()` (→
  ADR-004 §2a/§2g, TASK-0015b) — signatures unchanged

## Delivered Artifacts

- `custom_components/shady/coordinator.py` — `__init__` resolves
  `hass.config.time_zone` via `zoneinfo.ZoneInfo` into `self._local_tz` up front
  (falling back to `UTC` on `ZoneInfoNotFoundError`/`AttributeError`/
  `ValueError`), passed to `Cache(...)`'s new `local_tz` keyword; new public
  `local_date(moment) -> date`/`local_day_start(day) -> datetime`;
  `_tomorrow_end` now derives "today" from whatever tzinfo its own `now`
  argument carries (every real caller now passes one already converted to
  `self._local_tz`); `diagnosed_slot()`'s `slot_of_day` now counted from local
  midnight; `pin_diagnostic_slot`/`set_follow_latest_diagnostic_slot` store
  `cache.pinned_reference` via `local_date`; `fc_day_array`'s `today_start` via
  `local_day_start(local_date(...))`; `_maybe_reset_energy_totals`/
  `_async_persist_energy_state` compare/store local dates;
  `_apply_intraday_reset`'s same-day-basis check uses `local_date` on both
  sides; `_push_provider_series`/`_recompute_string` pass a local-timezone-
  converted `now` into `_tomorrow_end`.
- `custom_components/shady/cache.py` — `Cache.__init__` gained
  `local_tz: tzinfo = UTC`; new
  `_local_date(moment) -> date`/`_local_midnight(day) -> datetime`; `trim()`'s
  pinned floor and `get_pinned_slot_pool`'s `today`/`_day_start_index` both
  resolve via these instead of a bare `.date()`/`tzinfo=UTC` construction.
- `custom_components/shady/coordinator_like.py` — `ShadyCoordinatorLike`
  Protocol gained `local_date(moment: datetime) -> date`.
- `custom_components/shady/diagnostics/compare_regressions.py` —
  `_export_window_start_date` resolves both "today" and the pinned date via
  `self._coordinator.local_date(...)`.
- `tests/support_ha.py` — `FakeHomeAssistant.config` (a `SimpleNamespace` with
  `time_zone="UTC"`, matching this fake's own prior implicit behavior) added;
  `_install_sensor_stub()` gained `homeassistant.components.http.auth` (needed
  by an unrelated, concurrently-landed change already present in the working
  tree — left in place, not re-attributed to this task).
- `tests/test_cache_pinned_slot_pool.py` — new
  `TestGetPinnedSlotPoolUsesTheConfiguredLocalTimezone` (3 tests): a
  `Europe/Berlin` pinned window anchors on the local calendar date, a
  near-local-midnight reference resolves the correct local date even though it
  disagrees with `UTC`'s, and the `UTC` default stays unchanged from prior
  behavior.
- `tests/diagnostics/test_compare_regressions.py` — `_ReplayCoordinator` gained
  a `local_date` method (`moment.date()`, `UTC` doubling as "local" in a
  tzinfo-free CSV replay) so `_export_window_start_date` resolves against it.
- `tests/test_local_timezone.py` — new: `TestLocalTimezoneResolution` (3),
  `TestDiagnosedSlotIsLocalTimeOfDay` (3),
  `TestForecastHorizonIsLocalCalendarDay` (2),
  `TestFcDayArrayIsLocalCalendarDay` (1), `TestEnergyResetIsLocalMidnight` (2) —
  11 tests total, all against a real `Europe/Berlin` (`UTC+2`, CEST) coordinator
  built via `test_coordinator.py`'s own harness.
- No external dependencies added (`zoneinfo` ships with the Python standard
  library, already relied on nowhere else in this project before this task).
- No ADR amended — ADR-005 §5/§6's own text already specified "HA's local
  timezone" for the energy-integral reset; this task is a bug fix bringing the
  implementation in line with already-documented intent, not a new architecture
  decision. ADR-004's `DiagnosedSlot.slot_of_day` docstring ("index's 0-287
  time-of-day component") is now slightly imprecise (it no longer describes a
  derivation from `index` alone) but was left unamended — a
  documentation-accuracy follow-up, not in scope for this bug-fix task.
