# Task: Intraday Correction Window Ends at the Last Complete Slot (TASK-0041 D2-b)

- **Status:** todo
- **Related ADRs:** \[ADR-006 §1a (window definition; Amendment 2026-10-07),
  ADR-006 §3 (`window_slots`), ADR-007a §4/§5 (`get_time_range`)\]
- **Dependencies:** [TASK-0041-recorder-synchronized-slot-trigger]

> **Gate: do not start until the human has confirmed D2-b in chat** after
> testing the finished `TASK-0041` on the live system (Gate 2 outcome,
> 2026-10-08: "I will decide based on tests with the live system"). On
> confirmation the Lead Agent first wires the ADR-006 §1a amendment (below) into
> the ADR text, records the decision in the Decisions block, and presents the
> task for approval; only then does a worker start. If the human decides to
> **keep** `end=now` (D2-a), set this task `done` with "withdrawn — D2-a
> confirmed" in Delivered Artifacts and amend ADR-006 §1a to state that
> `end=now` is intended, so the question does not resurface.

## Goal

ADR-006 §1a defines the trailing window as
`get_time_range(..., start=now-window_slots*5m, end=now)` with `end` inclusive.
At every slot job `now` lies inside the **in-progress** slot, so that slot is
part of the window although it is not complete. Its forecast value is present
(Shady pushed it), but its actual yield is always `None` — the recorder has no
statistic for it yet — and `day_energy_total_wh` sums a `None` slot as zero. The
effect, found **by code reading only and not measured on a live system**:

`ratio_string = pv_energy_window / fc_energy_window` is low by about
`fc(in-progress slot) / fc_window`, i.e. roughly `1 / (window_slots + 1)` —
about 4 % at the default `window_slots = 24` — **even when the forecast is
exactly right**, at every slot job, independent of trigger phase. With `ramping`
or `blending` correction active this feeds a persistent downward bias into the
corrected forecast; `intraday_correction_cutoff` (default 0.10) clamps the
factor to `1 ± 0.10`, so the bias is bounded but real.

Change both window sums to cover exactly the last `window_slots` **complete**
slots: PV and forecast over the same slots, neither containing the in-progress
slot. This is also the slot `TASK-0041`'s probe waits for, so after that task
the newest complete slot's PV is reliably present when the window is read.

## How the human can decide (live-system check, no code needed)

With `intraday_correction_mode` on (`ramping` or `blending`), on a steady clear
day where actual PV tracks the forecast closely, read a string's
`intraday_ratio` attribute (ADR-006 §4, `intraday_attributes`) after a few slot
jobs. If the bias exists as described, the ratio sits near
`window_slots / (window_slots + 1)` (≈ 0.96 at the default) rather than near 1.0
while the forecast is demonstrably right. Near 1.0 → keep D2-a and withdraw this
task; persistently ≈ 0.96 → confirm D2-b.

## Proposed ADR-006 §1a amendment (draft, to be written into the ADR on the human's confirmation)

Replace "`end=now`" in the window definition by the end of the **last complete
slot** before `now` (`Cache.timestamp_for(Cache.index_for(now) - 1)`), keep
`start = max(reset_at, now - window_slots * 5m)` (which, with `now` anywhere
inside its slot, makes the window exactly `window_slots` slots when not bounded
by a reset), and note that a reset inside the in-progress slot gives an empty
window (`ratio_string = 1`, ADR-006 §1b unchanged). Remove the sentence claiming
"the window's edge lags behind by more than one slot" as an argument for
polling, which no longer matches the slot trigger. Record: *Reason* — the
in-progress slot carries a forecast but never a PV value; *Decision* — end at
the last complete slot; *Decided by* — human, after live-system tests.

## Acceptance Criteria

- Given `window_slots = N` and the slot job's `now` anywhere in slot `n`, when
  `_intraday_energy_window` is read for a string whose last reset is older than
  `N` slots, then it covers slots `n - N .. n - 1` — exactly `N` complete slots
  — and neither the forecast nor the PV of slot `n` contributes.
- Given PV seeded to equal the string's already-corrected forecast in every
  complete slot (and, as in production, absent for slot `n`), then
  `ratio_string == 1.0` exactly (was `N / (N + 1)`). **This test must fail
  against the pre-change code** (ratio 0.96 at `N = 24`).
- Given a reset inside slot `n` (`reset_at` in the in-progress slot), then the
  window is empty: `(0.0, 0.0)`, `ratio_string = 1.0`, `effective_factor = 1`.
  Given a reset in an earlier slot `m < n`, then the window starts at slot `m`.
- Given the slot job runs at an arbitrary phase (event at second 10, or the
  watchdog mid-slot), then the window is identical for every `now` inside the
  same slot (index-based, not time-of-day-based).
- Given the `_intraday_energy_window(string, _NOW, _NOW) == (0.0, 0.0)` guard
  test (`tests/test_coordinator.py`), then it still passes unchanged.
- Given the event/commit-lag harness of
  `tests/test_coordinator_slot_trigger.py`, when the newest complete slot's
  statistic commits only after the first probe, then the window's
  `pv_energy_window` includes that slot's PV (the probe guarantee reaches the
  correction, not just the diagnostics).
- Given `_apply_intraday_reset`, the clamp order (ADR-006 §1b), the ramp-weight
  accounting (`active_slots_since_reset`, which still counts the in-progress
  slot when its forecast is nonzero) and the re-push start (`now_index + 1`),
  then they are unchanged. (The ramp-accounting question is deliberately **not**
  reopened here; if the human wants it aligned, that is a separate decision.)
- Given the existing intraday tests (`tests/test_coordinator_intraday.py`), then
  any whose expected values assumed `end=now` are updated, each change listed in
  Delivered Artifacts with the reason; no test is loosened to a weaker
  assertion.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` — `_intraday_energy_window` (end of
  the read, empty-window guard, docstring); a comment in
  `_advance_intraday_string`.
- `adr/006-intraday-deviation-correction.md` — §1a amendment (written by the
  Lead on confirmation, before code).
- `tests/test_coordinator_intraday.py`,
  `tests/test_coordinator_slot_trigger.py`, possibly
  `tests/test_coordinator.py`.
- `tasks/adr-summary.md` — the window-end sentence.

## Definition of Done

- Tests green; each new test shown to fail against the pre-change code where the
  behavior is new, then shown to pass.
- `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` clean across the whole tree; `mdformat --check` clean
  on every edited `.md` file.
- Coverage of `coordinator.py` measured before and after; no drop.
- ADR-006 §1a amended before code, consistent with what was built;
  `tasks/adr-summary.md` accurate.
- `tasks/INDEX.md` log row single-line, no bare pipe inside code spans in table
  cells.
- No new external dependency; `tasks/DEPENDENCIES.md` unchanged.
- `Delivered Artifacts` block completed and accurate.

## Consumed Interfaces

<!-- From TASK-0041's Delivered Artifacts (done 2026-10-08); read from the code. -->

- `ShadyCoordinator._intraday_energy_window(self, string: _StringConfig, start: datetime, now: datetime) -> tuple[float, float]`,
  `_advance_intraday_string(self, string: _StringConfig, now: datetime) -> None`,
  `_intraday_tick_sync(self, now: datetime) -> None` from
  `custom_components/shady/coordinator.py` (unchanged by TASK-0041; the slot job
  `_async_slot_job` now calls the latter, once per slot, under
  `async_run_cache_job`)
- `Cache.get_time_range(sensor_ids, start, end, on_invalid=...)`,
  `Cache.index_for(...)`, `Cache.timestamp_for(...)` from
  `custom_components/shady/cache.py`
- Test harness: `_make_setup`, `_Recorder`, `_Clock`, `_EVENT` in
  `tests/test_coordinator_slot_trigger.py`;
  `_reseed_pv_to_match_pushed_forecast` in `tests/test_coordinator_intraday.py`

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
