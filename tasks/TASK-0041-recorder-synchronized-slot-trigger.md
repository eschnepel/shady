# Task: Recorder-Synchronized Slot Trigger (Replace the 5-Minute Wall-Clock Tick With the Recorder's Statistics Event)

- **Status:** review
- **Related ADRs:** \[ADR-006 §1a (Amendment 2026-10-07), ADR-004 §2i (and §2g,
  §4), ADR-007a §4 (Amendment 2026-10-07)\]
- **Dependencies:** [TASK-0037-patch-5-no-freeze-of-unsettled-tail]

## Goal

Everything Shady does per slot — advance the followed diagnosed slot (ADR-004
§2g), each string's intraday correction (ADR-006 §1a), the diagnostics refresh
(ADR-004 §2/§4) — runs off one `async_track_time_interval(..., 5 minutes)` tick
whose phase is wherever Home Assistant happened to start. Shady's actual input
is the recorder's short-term statistics, which are compiled at `second=10` after
every 5-minute mark. A tick whose phase falls within that delay reads the newest
complete slot before it exists, so the followed diagnostic result computes
without "selected actual" and without accuracy, and — because the result is
cached until the next tick — shows that gap for the whole 5 minutes, on every
tick, for the rest of the run (reported 2026-10-07; both a followed and a pinned
CSV export lacked PV for all of today's pool rows; see
`TASK-0037-patch-5-no-freeze-of-unsettled-tail` for the cache half of the root
cause).

Replace the interval with the recorder's own signal: Home Assistant fires
`EVENT_RECORDER_5MIN_STATISTICS_GENERATED` (`homeassistant.const`) once per
compile, from inside the compile (read from HA core's recorder source; it is
fired just before the session commits and carries no payload). Per event, run
one **slot job**: probe until the newest complete slot is readable, then run the
former tick body exactly once. Only the with-PV compute is ever published.

**Stays on its own clock (unchanged):** midnight recalibration (00:01:00,
already after the 00:00:10 compile), energy reset (00:00:00), the Forecast.Solar
hourly polls, all state-change listeners.

## Decisions Ledger (as of 2026-10-08, for the implementing session)

**Decided by the human (in chat, 2026-10-07/08):**

- The whole 5-minute slot trigger (followed-slot advance, per-string intraday
  correction, diagnostics) moves from the wall-clock interval to
  `EVENT_RECORDER_5MIN_STATISTICS_GENERATED`.
- No fixed pause; only a bounded probe retry (the event fires before the
  compile's commit). Only the with-PV compute is ever published.
- The coordinator exposes `async_run_cache_job(fn, *args)` (a method), not the
  lock; `Cache` never sees the lock.
- Loop-thread readers of the cache are a separate task (`TASK-0042`).

**Open — confirm in one message before any code (Gate 2):**

- **D2** intraday window end (recommended: D2-b, end both windows at the last
  complete slot) — below.
- **D3** keep the interval as a 6-minute watchdog (recommended: keep).
- Parameters `PROBE_INTERVAL` 1 s, `MAX_PROBES` 5, `WATCHDOG` 6 min
  (recommended: accept).
- Gate 2 approval of `TASK-0037-patch-5`, this task and `TASK-0042` as written.

## Acceptance Criteria

Trigger and lifecycle:

- Given the coordinator is set up, then it subscribes with
  `hass.bus.async_listen(EVENT_RECORDER_5MIN_STATISTICS_GENERATED, ...)`, keeps
  the returned unsubscribe in `_unsub`, and `shutdown()` removes it and cancels
  any in-flight slot job.
- Given an event, then the handler is a `@callback` that only schedules a task
  on the loop — no recorder access, no blocking work, no `time.sleep` anywhere.
- Given the former interval registration, then it remains as a **watchdog**
  (D3): its handler starts a slot job only if none was started for `WATCHDOG` (6
  minutes); in normal operation it never starts one.

Slot job:

- Given a slot job, then it runs the probe on the recorder executor and, while
  the newest complete slot is still missing for a string that is "pending",
  waits `PROBE_INTERVAL` (1 s) with `await asyncio.sleep` (never inside an
  executor job) and probes again, at most `MAX_PROBES` (5) times.
- Given a string is "pending" iff its slot before the newest complete one has a
  value and the newest complete one does not, then a string with no data at all
  never delays the job (one two-slot read per string decides it).
- Given the probe succeeds or `MAX_PROBES` is reached, then the job runs the
  former tick body once, in this order: followed-slot advance (still first,
  still independent of whether any mode is active), each string's intraday
  advance, diagnostics refresh (`extra_fit` per `fit_cadence()`, `compute` per
  `compute_cadence()`), publishing `_diagnostic_result_cache` only when the
  compute completes (readers keep the previous result until then).
- Given two triggers for the same slot index (a duplicate event, or the watchdog
  right after an event), then the body runs once.
- Given a new event arrives while an earlier slot job is still probing, then the
  earlier job is cancelled and never runs its body after the newer one started.

Serialization (replaces the unverified "single-worker executor" assumption):

- Given every cache-touching `get_instance(hass).async_add_executor_job`
  dispatch — in `coordinator.py` (startup backfill, `async_refit`, the slot job,
  `_async_recompute_diagnostic_result`) **and in `http_export.py`**
  (`mode.export_csv`, which reaches the cache through `_gather_pool`) — then
  each goes through one public coordinator **method**,
  `ShadyCoordinator.async_run_cache_job(fn, *args)`, that holds a single
  `asyncio.Lock` on the loop around the dispatch to the recorder executor, so
  two such jobs never run concurrently; a test dispatches two jobs at once and
  asserts no overlap. The raw lock is deliberately **not** exposed as a property
  (a method cannot be held across other awaits or forgotten by a caller), and it
  is never handed to `Cache` (sync methods cannot await it, and `cache.py` stays
  free of coordinator imports, ADR-007a §2). Loop-thread readers of the cache
  are out of scope here: see `TASK-0042`.
- Given the module docstring's claim that the recorder executor has a single
  worker, then it is corrected: HA's `MAX_DB_EXECUTOR_WORKERS = POOL_SIZE - 1`
  with `POOL_SIZE = 5`, hence the lock.

Regression and end-to-end (coordinator tier, existing harness):

- Given the tick-phase simulation, a recorder that compiles each slot 10 s after
  its boundary and an event fired at that moment with the commit visible a few
  hundred milliseconds later, when the diagnostic mode is on and following, then
  the published result contains "selected actual" and accuracy for the newest
  complete slot — also when the first probe loses the race. Must fail against
  the pre-change interval-driven code.
- Given no event ever fires (simulated), when `WATCHDOG` elapses, then the slot
  job runs and the diagnostics advance.
- Given a pinned future or in-progress slot, then each slot job still refreshes
  its prediction, and a just-elapsed pinned slot gains its actual and accuracy
  on the first job after it exists.
- Given intraday correction is on, then `_advance_intraday_string` runs once per
  slot job with the same inputs it had per tick (modulo D2).
- Given the tick-driven bodies' existing tests (`_intraday_tick_sync` and
  friends), then they are unchanged and green — only registration and
  orchestration move.

## Open Decisions (resolve at Gate 2)

**D2 — intraday window end (pre-existing bias, found while reading the code; by
code reading only, not measured on a live system — the reporter's intraday
correction is off).** `_intraday_energy_window` reads
`get_time_range(..., start, now)` with `end` inclusive, so the window contains
`now`'s own in-progress slot. Its PV is always `None` (contributes zero: a
`None` slot is excluded from `day_energy_total_wh`), but its forecast value is
present. `ratio_string = pv_window / fc_window` is therefore low by roughly
`fc(in-progress slot) / fc_window`, about `1 / (window_slots + 1)` — around 4 %
at the default `window_slots=24` — independently of tick phase, and the
effective factor is clamped to `1 ± intraday_correction_cutoff` (default 0.10),
so the bias moves forecasts at all times while intraday correction is active.

- **D2-a:** leave it (no forecast-output change in this task).
- **D2-b (recommended):** end both windows at the last complete slot (`now - 1`
  slot) so PV and forecast cover the same complete slots. Changes forecast
  output and needs an ADR-006 §1a amendment (the window definition `end=now`).

**D3 — watchdog.** Keep the interval as a 6-minute watchdog (default, about 15
lines; protects against the event alone going missing while the recorder still
works, e.g. a failing compile or a future HA change) or drop it (the recorder is
a practical requirement anyway, since actual yield is read from it).

Parameters `PROBE_INTERVAL` (1 s), `MAX_PROBES` (5), `WATCHDOG` (6 min) are Lead
Agent defaults, to be confirmed or changed at Gate 2.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` — `_register_intraday_schedule`
  (becomes event subscription plus watchdog), `_handle_intraday_tick` /
  `_async_intraday_tick` (become the slot job), `shutdown`,
  `async_run_cache_job` and every `async_add_executor_job` dispatch, module
  docstring correction.
- `custom_components/shady/http_export.py` — route its `export_csv` dispatch
  through the same helper.
- `tests/test_coordinator.py` — new classes for event wiring, probe/retry,
  dedupe, supersede, watchdog, lock, end-to-end phase replay.
- ADR text already amended (ADR-006 §1a, ADR-004 §2i, ADR-007a §4); D2-b would
  add an ADR-006 §1a amendment line.
- Wording sweep: every "5-minute tick/poll" mention in `coordinator.py`
  docstrings/comments and in ADR-002/004/005/006 means the slot trigger now.

## Definition of Done

- Tests green; each new test shown to fail against the pre-change code where the
  behavior is new, then shown to pass.
- `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` clean across the whole tree; `mdformat --check` clean
  on every edited `.md` file.
- Coverage of `coordinator.py` measured before and after; no drop.
- ADR-006 §1a and ADR-004 §2i Amendments present (done at task creation) and
  consistent with what was built; `tasks/adr-summary.md` accurate.
- `tasks/INDEX.md` log row single-line, no bare pipe inside code spans in table
  cells.
- No new external dependency (the event constant comes from `homeassistant`
  itself); `tasks/DEPENDENCIES.md` unchanged.
- `Delivered Artifacts` block completed and accurate.

## Consumed Interfaces

<!-- Read from the current code on `initialcode`; refresh from the dependency
     task's Delivered Artifacts (patch-5) before this starts. -->

- `ShadyCoordinator._register_intraday_schedule(self) -> None`,
  `_handle_intraday_tick(self, now: datetime) -> None` (`@callback`),
  `async _async_intraday_tick(self, now: datetime) -> None`,
  `_intraday_tick_sync(self, now: datetime) -> None` from
  `custom_components/shady/coordinator.py` (→ task:
  TASK-0037-patch-4-follow-latest-diagnostic-slot-toggle)
- `ShadyCoordinator._advance_followed_diagnostic_slot(self, now: datetime) -> None`,
  `_diagnostics_tick_sync(self, now: datetime) -> None`,
  `_advance_intraday_string(self, string, now: datetime) -> None`,
  `_intraday_energy_window(self, string, start: datetime, now: datetime) -> tuple[float, float]`,
  `diagnostic_result(self)`,
  `async _async_recompute_diagnostic_result(self) -> None`
- `ShadyCoordinator.shutdown(self) -> None` and
  `self._unsub: list[Callable[[], None]]`
- `ShadyCoordinator.async_refit(self, now: datetime | None = None)` and the
  `_backfill_elapsed_today_slots` executor dispatch
- `cache.Cache.get_time_range(...)`, `Cache.index_for(...)`,
  `Cache.timestamp_for(...)`, and `Cache.__init__(..., clock=...)` from
  `custom_components/shady/cache.py` (→ task:
  TASK-0037-patch-5-no-freeze-of-unsettled-tail)
- `homeassistant.const.EVENT_RECORDER_5MIN_STATISTICS_GENERATED`,
  `hass.bus.async_listen`

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
