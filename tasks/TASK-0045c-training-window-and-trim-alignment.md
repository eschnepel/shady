# Task: Training Window of Exact 24-Hour Days Anchored at the Reference Day; Trim Floor

- **Status:** review (awaiting Gate 2 approval)
- **Related ADRs:** [ADR-007a §1, §6; ADR-008 §2; ADR-002 §1 (reference only)]
- **Dependencies:** \[TASK-0045b-diagnostics-reference-and-pool,
  TASK-0045d-scheduled-recalibration-at-0400\]

> Part of the split of `TASK-0045-apply-glossary-terminology` (decision record
> for the grill of 2026-10-11; the decisions below are copied from it, so this
> file is self-contained). **Supersedes `TASK-0044`'s local midnight-to-midnight
> days** (23/25-hour DST days, `NaN` rows, first 288 slots of a long day); what
> `TASK-0044` decided that still stands is kept (see below).

## Goal

Train on a **training window** of exact 24-hour days measured from the
**reference day**, with one anchor and no DST special-casing, and make
`Cache.trim` keep exactly what the training pool and a pinned diagnostics pool
need — so that the model's pool and the diagnostics' pool for the same instant
are the same samples.

## Decisions (human — inputs, do not re-ask)

- **Reference day.** The 24 hours ending at the local midnight that closes the
  local date of the reference timestamp (the followed slot for every
  recalibration trigger — `TASK-0045d`). Its start is `R`. Every earlier day
  lies exactly 24 hours before the next: `D_i = R − i × 288` slots (day _i_ =
  `[D_i, D_i + 288)`, _i_ = 1 … `window_days`). The reference day itself is not
  part of the pool. No 23/25-hour days, no `NaN` rows, no unused slots.
- **Simplification (derivation).** With 24-hour strides every day start is
  congruent modulo 288, so the sample for UTC slot _s_ on day _i_ is
  `D_i + ((s − D_i) mod 288)` and `(s − D_i) mod 288` is the same for every day:
  all DST special-casing disappears.
- **Still standing from `TASK-0044`:** the fitted model's slot index stays the
  **UTC-clock slot** (`index % 288`); neighbor smoothing reads an extended
  window (`smoothing_radius` slots beyond each end of the window; `Cache.trim`
  takes the same radius).
- **First hour of a 25-hour date (G10, G4).** When the reference timestamp
  precedes the start `R` of its closing-midnight reference day (12 slots a year,
  00:00–00:55 on the fall-back date; 6 at Lord Howe), use the day
  `[R − 24 h, R)` — the 24 hours that contain the reference timestamp — as the
  reference day. The window then ends at or before the reference timestamp
  (never the future), the training is one day short until the next 04:00 run
  (accepted), and the samples equal the diagnostics' `diagnosed − i × 24 h`
  (`TASK-0045b`) for the same slot. Implement it **once**, in one helper.
- **G12 — Trim retention.** Floor = **min(training window start, pinned pool
  window start) − smoothing radius**. No extra day for the following pool (at
  00:00–04:00 its window is anchored one day _later_ than the model's, so it
  needs no older data; from 04:00 both share the reference day). Trim stays at
  the scheduled recalibration only, as `TASK-0043` wires it.
- **G11.** For 00:00–04:00 the diagnostics anchor on the followed slot while the
  model in use was fitted at the previous 04:00 — accepted and documented in the
  ADR (`TASK-0045b`).
- **G14 — Lean ADRs.** Rewrite ADR-007a §1/§6 and ADR-008 §2 **in the main
  text**; no `Amendment` blocks; stable section numbers. Delete the superseded
  `TASK-0044` text (it was collapsed into the main text by `TASK-0046`).

## Evidence

- `Cache._training_day_starts`, `_training_window_start_index` and
  `get_regression_pools` (`cache.py`) implement local midnight-to-midnight days:
  23/25-hour days, `NaN` rows for UTC slots a short day lacks, the first 288
  slots of a long day (`TASK-0044`; ADR-008 §2 and ADR-007a §1 text).
- `Cache.trim(reference, smoothing_radius)` keeps the training window start
  minus the radius plus the pin floor `min(…, pinned_reference − window_days)`.
- Pitfall: subtracting a `timedelta` from an aware `datetime` with a `ZoneInfo`
  is **wall-clock** arithmetic and ignores a clock change in between. Do the
  arithmetic on UTC instants or slot indices; convert to local only for labels
  and tests.

## Acceptance Criteria

- Given every slot of 2026 in Europe/Berlin and America/New_York as reference
  timestamp, when the model's pool for that slot is read via
  `get_regression_pools` and the diagnostics' pool via `get_pinned_slot_pool`,
  then both hold the same timestamps — including the 12 slots at the start of
  the 25-hour date, with no exception.
- Given a recalibration reference at 03:55 on 29 Mar 2026, on 25 Oct 2026
  (Europe/Berlin) and on an ordinary date, then the window is exactly
  `window_days` consecutive 24-hour days ending at `R`, with no `NaN` row from a
  day-length effect and no sample from the reference day.
- Given a reference timestamp in the first hour of a 25-hour date, then the
  window ends at or before the reference timestamp and no future index is
  requested.
- Given the same periodic fixture data in UTC and in a non-UTC timezone, then
  the training matrices are identical (the existing harness property in
  `tests/test_coordinator_recalibration_trim.py`).
- Given a recalibration followed by `trim`, in UTC and non-UTC timezones across
  both DST changes, then the next recalibration, the following pool and a pinned
  pool within the floor are served without a recorder re-fetch (counting
  recorder spy), and a pinned slot older than the training window keeps its own
  window.
- Given the timezone is UTC and no DST, then fitted models are unchanged. Tests
  that pinned the superseded local-midnight definition are **restated, not
  deleted**; new tests fail against the old code.
- Given the ADRs, then ADR-007a §1/§6 and ADR-008 §2 describe the 24-hour-day
  training window, the UTC-clock slot, the smoothing extension and the trim
  floor in the main text; `Cache._training_day_starts`' DST branches are gone.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `get_regression_pools`,
  `_training_day_starts`, `_training_window_start_index`, `trim`, and the pin
  floor (`pin_reference` / `pinned_reference` as changed by `TASK-0045b`)
- `custom_components/shady/coordinator.py` — `_refit_sync`, `_trim_cache`
- `tests/test_cache_regression_pools.py`, `tests/test_cache_core.py`,
  `tests/test_coordinator_recalibration_trim.py` (harness `_make_setup`)
- `adr/007a-cache-storage-and-accessor-design.md`,
  `adr/008-numpy-backend-and-cache-array-accessor.md`, `tasks/adr-summary.md`

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none)

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation, from the Delivered
     Artifacts of TASK-0045b and TASK-0045d. Known today (TASK-0043/0044): -->

- `Cache.get_regression_pools`, `Cache._training_day_starts`,
  `Cache._training_window_start_index`,
  `Cache.trim(reference, smoothing_radius)` from
  `custom_components/shady/cache.py` (→ tasks: TASK-0043, TASK-0044)
- `Cache.get_pinned_slot_pool`, `Cache.pin_reference`, `Cache.pinned_reference`
  as delivered by TASK-0045b
- `ShadyCoordinator._refit_sync`, `_trim_cache`, and the followed-slot reference
  as delivered by TASK-0045d

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
