# Handover 0001: Diagnostic "selected actual" Missing → Cache Freeze + Recorder-Synchronized Slot Trigger

**Written:** 2026-10-08 · **Phase reached:** Gate 2 (task set drafted, **no code
written**) · **Base:** branch `initialcode`, HEAD `6940b71` plus *uncommitted*
documentation changes (see "State of the working tree").

A fresh Lead Agent session should read this file first, then the files under
"Read in this order". Nothing here replaces the ADRs or the task files; it says
where to start and what is and is not settled.

## 1. The problem and its root cause

**Report (human, Shady):** in the `compare_regressions` diagnostic chart the
"selected actual" entry (and every accuracy value) is missing while the
follow-latest-slot toggle is on.

**Evidence supplied by the human** (copies in the bundle's
`handover-evidence/`):

- A followed export and a pinned export of the same slot (13:50Z, local 15:50,
  `diagnosed_index` 711814): byte-identical except `is_pinned`; both have no
  `pv_selected`, no accuracy, and **all seven of today's training-pool rows
  (offsets -3 to +3) have blank `pv_raw`**, including three slots that ended
  13-23 minutes before the export. Yesterday's rows are intact.
- A post-reboot pinned export (13:40Z, `diagnosed_index` 711812): all of today's
  rows have PV (27.97 / 29.13 / 29.33 / **29.50** / 30.78 / 29.45 / 21.10 W) and
  accuracy appears (linear 0.397, kernel 0.610, **wls2 0.829**, wls3 0.802).
- A screenshot: "Effy" is the measured PV (about 27-30 W at 15:50); Shady's
  forecast was about 54 W at the same time.
- Intraday correction was **off** on that system.

**Root cause (reproduced against the real `Cache`, see
`handover-evidence/tick_phase_simulation.py`):**

1. The recorder compiles each slot's 5-minute statistic about 10 s after the
   slot boundary. Shady's 5-minute `async_track_time_interval` tick is not
   clock-aligned; its phase is wherever HA started.
1. A tick landing within that delay reads the just-ended slot too early;
   `fetch_fn` returns `None` for it.
1. `Cache._fetch_and_store` widens `validated` over the whole fetched span,
   including trailing `None`s, and `_validate_range` never re-queries a
   validated index. The `None` is frozen for the rest of the run, and since the
   tick phase is constant, every later slot freezes the same way.
1. The diagnostic result is computed once per tick and cached until the next
   one, so even with the cache fixed a bad phase would still show the newest
   slot without its actual.

Simulation result: tick at +40 s → all slots present; tick at +3 s → all `None`;
intraday correction on (window through `now`) → all `None`. After a restart the
phase changes, which is why the reboot "fixed" it.

## 2. The fix, as three tasks (ship in this order)

| Order | Task | What | Status |
| -- | -- | -- | -- |
| 1 | `TASK-0037-patch-5-no-freeze-of-unsettled-tail` | Cache: a trailing `None` from a slot that ended < `SETTLE_GRACE` (10 min) ago, or has not ended, is not validated; `Cache` gets an injectable `clock`. | `review` (awaiting Gate 2) |
| 2 | `TASK-0041-recorder-synchronized-slot-trigger` | Replace the 5-minute wall-clock tick with `EVENT_RECORDER_5MIN_STATISTICS_GENERATED`; slot job with bounded probe retry; `async_run_cache_job` lock method; interval kept as watchdog. | `review` (awaiting Gate 2) |
| 3 | `TASK-0042-cache-internal-threading-lock` | `threading.RLock` inside `Cache` for loop-thread readers, never held across `fetch_fn`. Reproducer first; may close as "not reproducible". | `review` (awaiting Gate 2) |

ADR amendments are **already written** (before any code, per the Phase 0
procedure): ADR-007a §4 (and pointers in §1/header), ADR-006 §1a, ADR-004 §2i.
`TASK-0042`'s ADR-007a threading-contract amendment is deliberately **not**
written; the Lead writes it after Gate 2 approval. `tasks/adr-summary.md` is
updated for everything written so far.

## 3. Decisions: what is settled and what is not

**Settled by the human:**

- Option C (cache-level fix) rather than lagging the followed slot or aligning
  the tick; the clock-based `SETTLE_GRACE` stays (an event-based "settled" would
  reintroduce the freeze when a read lands before the commit).
- The whole slot trigger (followed-slot advance, per-string intraday correction,
  diagnostics) moves to the recorder event. No fixed pause; only the with-PV
  compute is published; bounded probe retry only as a safety net.
- `ShadyCoordinator.async_run_cache_job(fn, *args)` is a **method**; the raw
  `asyncio.Lock` is not exposed and never reaches `Cache`. It must also cover
  `http_export.py`'s `mode.export_csv` dispatch.
- Cache-internal threading is its own task (`TASK-0042`).

**Still open - confirm with the human in one message before any code:**

- **D2** (TASK-0041): end the intraday PV/forecast windows at the last complete
  slot (recommended) or leave them. Pre-existing bias, **found by code reading
  only, not measured**: `_intraday_energy_window` reads through `now` inclusive,
  so the in-progress slot's forecast is counted but its PV (always `None`,
  summed as zero) is not; `ratio_string` is low by about
  `1 / (window_slots + 1)` (about 4 % at the default 24), clamped by the ±10 %
  cutoff.
- **D3**: keep the 6-minute watchdog (recommended) or drop it.
- Parameters `PROBE_INTERVAL` 1 s, `MAX_PROBES` 5, `WATCHDOG` 6 min.
- Gate 2 approval of all three tasks as written.

## 4. Facts about Home Assistant to re-verify against the pinned version

Read from HA core's `dev` branch on 2026-10-07/08; `hacs.json` pins HA 2026.3 as
the minimum. Re-check these against 2026.3 before relying on them:

- `recorder/core.py`:
  `async_track_utc_time_change(..., minute=range(0, 60, 5), second=10)` queues
  `StatisticsTask(start, True)` for the live compile; the startup catch-up
  (`_schedule_compile_missing_statistics`) does **not** fire events.
- `recorder/statistics.py`: `_compile_statistics` fires
  `EVENT_RECORDER_5MIN_STATISTICS_GENERATED` (a constant in
  `homeassistant.const`) **inside** the compile's session, i.e. before the
  commit; the event has no payload.
- `Recorder.async_block_till_done()` returns immediately when the queue is empty
  and the event session has no pending writes, so it is **not** a barrier for
  the running statistics task (do not use it).
- `MAX_DB_EXECUTOR_WORKERS = POOL_SIZE - 1` and `recorder/pool.py` has
  `POOL_SIZE = 5`: the recorder executor is **not** single-worker. The module
  docstring in `coordinator.py` claims otherwise and must be corrected
  (`TASK-0041`). `MutexPool` applies only to in-memory SQLite.

## 5. Already known, out of scope

- `tasks/INDEX.md`: a 2026-10-04 refinement-log row for `TASK-0015b-patch-4`
  sits after the Audit Groups section at end of file, merged into that
  paragraph's last line (same failure mode as the 2026-10-03 entry). Not
  touched.
- Forecast quality (observation, unverified cause): wls2 predicted 53.8 W for
  the 15:50 slot (wls3 63.7 W) against about 29.5 W actual; comparable days in
  the pool (FC 373-526 W) gave 26-32 W. Likely polynomial extrapolation at the
  edge of the training data (today's FC 412 W exceeds most training points).
  Candidate for a later audit, not part of these tasks.

## 6. Working-tree state and environment

- **Nothing is committed.** Changed/new files (documentation only, no code, no
  tests): `adr/004-...md`, `adr/006-...md`, `adr/007a-...md`,
  `tasks/adr-summary.md`, `tasks/INDEX.md`, and new
  `tasks/TASK-0037-patch-5-...md`, `tasks/TASK-0041-...md`,
  `tasks/TASK-0042-...md`, this file. The bundle contains `shady.zip` (full tree
  with `.git`; unzip and work there) and `handover-docs.patch` (same changes,
  `git apply` on a clean `initialcode` checkout at `6940b71`). A plain clone of
  GitHub will **not** contain these changes unless they are committed and
  pushed.
- Baseline: `tests/test_cache_core.py` + `tests/test_cache_pinned_slot_pool.py`
  pass (49 tests) with only `pytest`, `pytest-asyncio` and `numpy`. The
  coordinator tier needs Home Assistant (the repo's `uv` dev group); that suite
  was **not** run in this session.
- Formatting: `.mdformat.toml` (wrap 80, plugins `mdformat-gfm`,
  `mdformat-config`, `mdformat-ruff`). Run `mdformat` on every edited `.md` and
  `mdformat --check` before finishing. INDEX table rows must be single physical
  lines with no bare pipe inside code spans.
- The Definition of Done in each task requires whole-tree
  `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .`.

## 7. Read in this order

1. `tasks/adr-summary.md` (esp. the cache and "Slot trigger" paragraphs).
1. ADR-007a §4 Amendment 2026-10-07; ADR-006 §1a Amendment 2026-10-07; ADR-004
   §2i.
1. `tasks/TASK-0037-patch-5-...md`, then `TASK-0041-...md` (read its Decisions
   Ledger first), then `TASK-0042-...md`.
1. `tasks/INDEX.md` refinement log, the two 2026-10-07 rows.
1. `handover-evidence/tick_phase_simulation.py` (throwaway evidence script; uses
   `tests.support._load`; run from the repo root; do not commit it, but its
   structure is the basis for the regression tests).

**Next actions for the new Lead:** (1) get the human's answers to the open items
in section 3; (2) record any ADR-006 §1a window amendment if D2-b is chosen; (3)
mark the tasks `todo` at Gate 2; (4) run Phases 3-4 (worker, reviewer) for
`TASK-0037-patch-5` first and fill `TASK-0041`'s Consumed Interfaces from its
Delivered Artifacts before starting it.
