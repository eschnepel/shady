# Task: Historical Backfill Silently Skipped for an Already-Push-Marked Baseline (Permanent Cold-Start Passthrough, Take 2)

- **Status:** done
- **Related ADRs:** \[ADR-007a §2 (unchanged, referenced — the "actively pushed,
  never (re-)queried" contract this task's fix must not weaken for any other
  caller), ADR-012 §2a (unchanged, referenced — the historical-backfill behavior
  this task restores), ADR-008 §2 (unchanged, referenced —
  `get_regression_pools`'s own batched-fetch contract)\]
- **Dependencies:** \[TASK-0034-baseline-recorder-backed-history,
  TASK-0034-patch-1\]

## Goal

Real-world bug report, live-debugged directly in chat (no source document —
root-caused from a fresh clone of the `initialcode` branch plus temporary
diagnostic logging deployed to the user's own running instance): every
configured string's forecast sensor showed the identical, raw, un-corrected
Forecast.Solar value — the exact symptom `TASK-0034` itself was written to fix,
now recurring despite `TASK-0034`/`TASK-0034-patch-1` both already being `done`
and the recorder genuinely holding 60 days of real history for the resolved
`history_entity_id` companion sensor.

Root cause — a different bug than either prior `TASK-0034` round, in the cache
layer itself, not in resolution or recorder eligibility: `baseline_entity_id` is
used as the cache key for two things that were never meant to collide.
`_push_provider_series` pushes that entity's live, forward-looking `forward()`
series on every poll (this is normal, pre-existing, ADR-012 §4 behavior, and
happens on every startup before any refit ever runs). `Cache.push` marks any
sensor it touches `_validated[sensor_id] = (from_index, None)` — `to_index=None`
meaning "actively pushed by Shady, always current, never (re-)queried" (ADR-007a
§2), a guarantee written for sensors Shady owns end-to-end (its own computed
output series) with no external source to ever backfill from.
`get_regression_pools` (`TASK-0034`'s own historical-training entry point) calls
the *same* `_validate_range` for the *same* key — but `_validate_range`'s
`to_index is None` branch returned immediately, **before even checking whether
the requested range's start was still below `from_index`.** Once the live push
has run even once (which it always has, by the time any refit fires), the entire
historical-backfill fetch `TASK-0034` added never executes at all — not because
the data isn't there, not because resolution failed, but because a pre-existing,
unrelated "actively pushed" short-circuit (older than `TASK-0034`, written for a
different kind of sensor) swallows the request first. Every downstream check
(recorder retention, statistics eligibility, `history_entity_id` resolution,
distinct per-string actual-yield sensors) came back clean during diagnosis
precisely because none of those were actually broken.

Confirmed live against the reporting user's own instance, via a temporary
diagnostic log: before the fix, `get_regression_pools`'s baseline pool was
`(288, 84)` with **0** non-`NaN` cells (`whole-pool non-NaN FC=0 PV=23791`)
despite `sensor.power_production_now` genuinely holding real recorder history;
after the fix, the same pool showed `whole-pool non-NaN FC=23915 PV=23791` —
matching the actual-yield side's own coverage almost exactly.

## Acceptance Criteria

- Given a sensor Shady has already pushed to (`to_index=None`), when a caller
  invokes `_validate_range` with its default `allow_historical_backfill=False`
  (every existing call site except one — see below), then it is never
  (re-)queried at all, exactly as before this task —
  `TestPushGuardAndPushOnly Sensor` (`tests/test_cache_core.py`) already pins
  this and must keep passing unmodified.
- Given the same push-marked sensor, when `get_regression_pools` calls
  `_validate_range` with `allow_historical_backfill=True` and the requested
  historical window's start is still below the sensor's currently-validated
  `from_index`, then the missing historical head **is** fetched via the normal
  `_fetch_and_store` path — regardless of `to_index` being `None`.
- Given that same historical backfill fetch completes, when a *future* index
  already covered by the original push is read afterward through the normal
  (`allow_historical_backfill=False`) path, then it still returns the pushed
  value, not something re-fetched over it — the `to_index=None` "future is
  always current" guarantee must survive being merged with a historical
  backfill, not be silently downgraded to a real `to_index` boundary.
- Given the opt-in backfill has already run once for a sensor (its historical
  head is now covered), when `get_regression_pools` is called again for the same
  window, then no second fetch happens — ordinary "already validated" behavior,
  unchanged.
- Given any other existing caller of `_validate_range` (`get_time_range`,
  `get_pinned_slot_pool`) — none of which pass `allow_historical_backfill` —
  then their behavior is byte-for-byte unchanged; the parameter defaults to
  `False` specifically so no other call site needs to change.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `_validate_range` gains
  `allow_historical_backfill: bool = False`; `_fetch_and_store`'s `_validated`
  merge logic; `get_regression_pools`'s own `_validate_range` call site.
- `tests/test_cache_core.py`, `tests/test_cache_regression_pools.py` — new
  tests.

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none — this
  task touches only `cache.py`'s own existing internals)

## Consumed Interfaces

- `cache.py`'s `Cache._validated`, `Cache._validate_range`,
  `Cache._fetch_and_store`, `Cache.push`, `Cache.get_regression_pools` — all
  pre-existing (`TASK-0034`/ADR-007a/ADR-008 §2's own delivered contract). This
  task is a same-file, Lead-Agent-inline fix (no sub-agents available in this
  environment, same convention every prior task in this cycle's Refinement Log
  already documents) with full-file context, not a minimal cross-task interface
  handoff.
- `providers/discovery.py`'s `resolve_forecast_solar_history_entity`,
  `BaselineProvider.history_entity_id()` — from `TASK-0034`/
  `TASK-0034-patch-1`'s Delivered Artifacts; confirmed working correctly during
  diagnosis (not touched by this fix).

## Delivered Artifacts

- `custom_components/shady/cache.py`:
  - `Cache._validate_range(self, sensor_id, start, end, *, allow_historical_backfill: bool = False) -> None`
    — new keyword-only parameter. When `True` and the sensor is push-marked
    (`to_index is None`), the missing historical head (`start < from_index`) is
    still fetched before returning; the "future never re-queried" return remains
    unconditional. Default `False` preserves the exact original behavior for
    every pre-existing call site.
  - `Cache._fetch_and_store` — merge fix: `to_index is None` in the pre-existing
    `_validated` entry is now preserved as `None` after a fetch
    (`new_to = to_index if to_index is None else max(to_index, end)`), instead
    of being widened to the just-fetched `end`. This branch was unreachable
    before `allow_historical_backfill` existed (the old `_validate_range` never
    called `_fetch_and_store` for a `to_index=None` sensor at all); making it
    reachable without this companion fix would have silently downgraded a
    push-based sensor to a normal validated-range sensor the first time a
    historical backfill ran, risking a later live read re-fetching and
    overwriting an already-pushed future value.
  - `Cache.get_regression_pools` — its own `_validate_range` call now passes
    `allow_historical_backfill=True`; no other call site (`get_time_range`,
    `get_pinned_slot_pool`) changed.
- `tests/test_cache_core.py`: new `TestValidateRangeHistoricalBackfillOptIn`
  class (3 tests) — default (`False`) still never queries a push-marked sensor;
  opt-in fetches the missing historical head exactly once and leaves the
  already-pushed future value intact; opt-in is a no-op once the head is already
  covered (no duplicate fetch).
- `tests/test_cache_regression_pools.py`: new
  `TestGetRegressionPoolsBackfillsAPushMarkedBaseline` class (2 tests) — the
  historical pool is fully populated (no `NaN`) for a baseline that was already
  push-marked before `get_regression_pools` ever ran; a live read of the pushed
  future slot afterward still returns the pushed value, not a re-fetched one.
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged.

**Verification (fresh, full run):** `pytest` — 635 passed (630 baseline + 5 new:
3 in `test_cache_core.py`, 2 in `test_cache_regression_pools.py`);
`mypy --config-file mypy.ini custom_components/ tests/` — clean, 59 files;
`ruff check .` — clean; `ruff format --check .` — clean, 178 files;
`mdformat --check` — clean on this file. Fix additionally confirmed live against
the reporting user's own running instance (see Goal) before this task file was
written — pool coverage went from `0/24192` non-`NaN` to `23915/24192`, matching
the actual-yield side's own coverage.
