# Task: Scheduled Recalibration at 04:00 Local, Followed-Slot Reference for Every Trigger

- **Status:** review (awaiting Gate 2 approval)
- **Related ADRs:** \[ADR-002 §1, §3; ADR-006 (the "00:01" sentence ~l.169);
  ADR-007a (~l.144); ADR-008 (~l.243)\]
- **Dependencies:** [TASK-0045a-wording-alignment]

> Part of the split of `TASK-0045-apply-glossary-terminology` (decision record
> for the grill of 2026-10-11; the decisions below are copied from it, so this
> file is self-contained). **Must land before or together with `TASK-0045c`**:
> under the closing-midnight reference day a 00:01 run on the fall-back date
> would read an hour that has not happened yet (25 Oct 2026 is the first real
> test). Until `TASK-0045c` is released, the current `TASK-0044` code handles
> the 25-hour day at 00:01, so this task is safe to ship on its own.

## Goal

Move the scheduled **recalibration** from 00:01 local to **04:00 local**, daily,
identical on DST and non-DST dates, and give **every** recalibration trigger
(timer, button, startup safety net) the same reference: the **followed slot**.

## Decisions (human — inputs, do not re-ask)

- **G3 — 04:00 local, daily.** Safely after every clock change (EU switch at
  02:00/03:00 local, US at 02:00). At 04:00 the followed slot (03:55) is always
  _today_, so the reference day is today and the training window lies fully in
  the past; the "let the recorder settle 23:55" rationale of ADR-002 §1 goes
  away. The model stays one night old for the first four hours of the day (PV ≈
  0). The **energy reset at 00:00** and the **recorder slot trigger** are
  independent and unchanged. `_handle_midnight` is renamed (name in the
  glossary's language, e.g. a scheduled-recalibration handler).
- **G4 — One reference for every trigger.** The recalibration reference is the
  **followed slot** (= the last completed slot) for the timer, the button and
  the startup safety net. Consequence, accepted: a button/startup recalibration
  between 00:00 and 00:05 trains a window one day short until the next 04:00
  run; it never reads the future. ADR-002 §1's "only recorder data up to and
  including yesterday" becomes "the training window before the reference day".
- **G9 — Horizon invariant.** ADR-002 §3's calendar horizon (remainder of today
  \+ all of tomorrow, as far as the baseline provider reaches) **stays**. Add the
  invariant to its text: _the horizon always reaches at least the next scheduled
  recalibration_ (true at every time of day, because 04:00 < 24:00 of tomorrow).
  Recompute (ADR-002 §2) runs after each baseline update (3–5 per day; the raw
  solar and weather forecasts cover two days) and applies the current model.
- **Startup safety net** (ADR-002 §1): "no model yet, or last successful fit
  more than 24 h old" stays as is. Verify it still behaves with a 04:00 schedule
  (a restart at 05:00 after a fit at 04:00 yesterday refits; a restart at 03:00
  does not).
- **G14 — Lean ADRs.** Edit the main text in place; no `Amendment` blocks;
  stable section numbers. The "00:01" wording in ADR-006, ADR-007a and ADR-008
  is reworded in place (no amendment).

## Evidence

- ADR-002 §1: `async_track_time_change(hass, ..., hour=0, minute=1, second=0)`,
  "one minute past midnight"; `coordinator.py` ~l.1163 registers
  `_handle_midnight` with `hour=0, minute=1, second=0`; ~l.1984 documents that
  the energy reset (`hour=0, minute=0`) deliberately does not reuse it.
- Measured (zoneinfo, 2026, every slot of every local date): with the closing
  midnight as reference-day anchor, a recalibration reference inside the first
  hour of a 25-hour date has a window that reaches into the future — 12 slots
  per year in Europe/Berlin and America/New_York, 6 at Australia/Lord_Howe, 0 in
  UTC. A 04:00 run is never in that hour.

## Acceptance Criteria

- Given the coordinator is set up, then the scheduled recalibration is
  registered for 04:00:00 local and nothing is registered for 00:01; the energy
  reset is still registered for 00:00:00 (existing test unchanged).
- Given a fake clock at 04:00 local on 29 Mar 2026 and on 25 Oct 2026
  (Europe/Berlin) and on an ordinary date, when the scheduled handler runs, then
  its reference is the followed slot 03:55 of that date, the training window
  ends at or before that date's reference-day start, and it reads nothing from
  the future.
- Given a button press or a startup safety-net fit at 14:37 and at 00:03 local,
  then the reference is the followed slot (14:30 slot; yesterday 23:55) and
  nothing reads the future.
- Given Home Assistant starts at 05:00 with the last fit at 04:00 yesterday,
  then the safety net refits; given it starts at 03:00, then it does not.
- Given a recompute at any time of day, then the horizon reaches at least the
  next scheduled recalibration (test at 03:55 and at 04:05).
- Given the timezone is UTC and no DST, then fitted models are unchanged and all
  pre-existing tests pass unless they pinned the 00:01 schedule (restate those,
  do not delete them). New tests fail against the old code.
- Given the ADRs, then ADR-002 §1/§3 describe 04:00, the training window before
  the reference day and the horizon invariant in the main text; "00:01" no
  longer appears in ADR-002/006/007a/008 except in quoted history.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` — the scheduled-recalibration
  registration and `_handle_midnight` (~l.1163–1190), `async_refit` /
  `_refit_sync` reference derivation, the startup safety net
- `tests/test_coordinator_recalibration_trim.py`
  (`_make_setup(window_days, time_zone, smoothing_radius)` harness), other
  coordinator recalibration tests
- `adr/002-coordinator-update-strategy.md` (§1, §3), `adr/006`, `adr/007a`,
  `adr/008` (one-sentence rewordings), `tasks/adr-summary.md`

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate (new handler name included)
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none)

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation. -->

- `ShadyCoordinator.async_refit`, `_refit_sync`, `_handle_midnight`,
  `_trim_cache` from `custom_components/shady/coordinator.py` (→ tasks:
  TASK-0043, TASK-0044, TASK-0041)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
