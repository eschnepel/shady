# Task: A Push-Sourced (`forecast_solar`-Shaped) Baseline's Already-Elapsed History Was Never Fetched At All (Diagnostic "selected" Series/Accuracy Still Missing After `TASK-0037-patch-1`)

- **Status:** done
- **Related ADRs:** [ADR-007a §4 (Amendment 2026-09-22)]
- **Dependencies:**
  [TASK-0037-patch-1-ridge-regularization-and-exception-isolation]

## Goal

Third downstream follow-up (human, live in chat, sharing their deployed
`compare_regressions.py` after `TASK-0037-patch-1`): the "selected" series still
did not appear, and — the key new hint — `accuracy` was an empty `{}` too. That
combination (no `"selected ..."` entries at all, not even `"selected actual"`,
and empty `accuracy`) only happens when `_append_selected_series`'s
`fc_selected is None` early return fires — `FC_selected` itself was still
unresolvable, not a downstream fitting problem.

Root-caused by re-reading `cache.py`'s own `_validate_range` contract (ADR-012
§2a): `allow_historical_backfill` — the opt-in that lets a push-sourced,
`forecast_solar`-shaped baseline's real external history actually be fetched
(otherwise a sensor Shady pushes to is "never (re-)queried, full stop") — was,
until now, exclusive to `get_regression_pools` (ADR-008 §2). Neither
`get_time_range` (which `diagnostics/compare_regressions.py`'s `_selected_value`
and `coordinator.py`'s `target_cell_temperature_for_slot` both call to read a
single already-elapsed slot) nor `get_pinned_slot_pool` (ADR-007a §6,
`TASK-0037`'s own subject) ever passed it. Since `get_regression_pools`'s own
window never reaches "today" (it stops at yesterday, by design), a push-sourced
baseline's **already-elapsed history for today** was therefore never fetched by
*any* caller in the entire codebase — permanently `None` for the diagnosed slot,
not because of a timing race (`TASK-0037` fixed that one) and not because of a
fitting exception (`TASK-0037-patch-1` fixed that one), but because nothing ever
asked for it.

## Acceptance Criteria

- Given `get_time_range` is called for a sensor Shady actively pushes to
  (`to_index=None`) with `allow_historical_backfill=True`, when that sensor's
  requested range falls before its currently-known earliest validated index,
  then it is fetched for real — not left `None` forever.
- Given the same call without `allow_historical_backfill` (the default), then
  behavior is byte-for-byte unchanged — a push-only sensor
  (`forecast_sensor_id`) is still never (re-)queried, full stop.
- Given `diagnostics/compare_regressions.py`'s `_selected_value` and
  `coordinator.py`'s `target_cell_temperature_for_slot`, both now pass
  `allow_historical_backfill=True` — the same opt-in `get_regression_pools`
  already used, for the identical reason (a possibly push-sourced baseline
  needing real calendar history).
- Given `get_pinned_slot_pool`'s own internal `_validate_range` call, it now
  always passes `allow_historical_backfill=True` — that accessor has exactly one
  purpose (diagnostic history for a possibly push-sourced baseline) and exactly
  one caller, so there is nothing to default `False` for.
- The full test suite passes, including new coverage proving `get_time_range`
  itself (not just `_validate_range` directly, already covered) threads the flag
  through, and that `_selected_value` passes it.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `get_time_range` (all overloads +
  implementation), `get_pinned_slot_pool`
- `custom_components/shady/diagnostics/compare_regressions.py` —
  `_selected_value`
- `custom_components/shady/coordinator.py` — `target_cell_temperature_for_slot`
- `tests/test_cache_core.py`, `tests/test_diagnostics_compare_regressions.py` —
  new coverage
- `adr/007a-cache-storage-and-accessor-design.md` — §4 amended

## Definition of Done

- Tests green (full suite: 648 passed) · `tasks/adr-summary.md` unaffected (no
  summarized signature drifted enough to need an update beyond §4's own ADR
  text) · ADR-007a §4 amended · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- `mypy`/`ruff check`/`ruff format --check` clean on every edited file
- No new external dependencies

## Consumed Interfaces

- `Cache._validate_range` (`custom_components/shady/cache.py`) — the
  `allow_historical_backfill` parameter this task threads one layer further out,
  unchanged itself (→ ADR-012 §2a)

## Delivered Artifacts

- `custom_components/shady/cache.py` — `get_time_range` (all three overloads +
  implementation) gained a keyword-only
  `allow_historical_backfill: bool = False`, threaded into its own
  `_validate_range` call; `get_pinned_slot_pool`'s internal `_validate_range`
  call now always passes `allow_historical_backfill=True`.
- `custom_components/shady/diagnostics/compare_regressions.py` —
  `_selected_value`'s `get_time_range` call now passes
  `allow_historical_backfill=True`.
- `custom_components/shady/coordinator.py` —
  `target_cell_temperature_for_slot`'s `get_time_range` call now passes
  `allow_historical_backfill=True`.
- `tests/test_cache_core.py` — new
  `TestGetTimeRangeThreadsAllowHistoricalBackfill`: confirms the default still
  never queries a push-marked sensor, and that opting in resolves an
  already-elapsed slot for real.
- `tests/test_diagnostics_compare_regressions.py` — new
  `TestSelectedValuePassesAllowHistoricalBackfill`: confirms `_selected_value`
  passes the flag through to `cache.get_time_range`.
- `adr/007a-cache-storage-and-accessor-design.md` — §4 amended with the
  generalized `allow_historical_backfill` rationale; header "Last updated" note
  extended.
- No external dependencies added.
