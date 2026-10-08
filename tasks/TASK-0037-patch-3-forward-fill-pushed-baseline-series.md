# Task: `_push_provider_series` Never Forward-Filled a Coarser-Than-5-Minute `forward()` Series (Diagnostic "selected" Series Only Ever Appeared On The Hour)

- **Status:** done
- **Related ADRs:** [ADR-012 §4 (Amendment 2026-09-23), ADR-009 §1a]
- **Dependencies:**
  [TASK-0037-patch-2-allow-historical-backfill-for-get-time-range]

## Goal

Fourth downstream follow-up (human, live in chat, sharing a self-diagnosed
finding after `TASK-0037-patch-2`): "the diagnostic sensors contain the selected
series only if the evaluated slot is the first slot of the hour (matches minute
0)".

Root-caused by direct reproduction against the real coordinator:
`_push_provider_series` (ADR-012 §4) built its push `dict` as a plain
`{Cache.index_for(ts): value for ts, value in series}` — a 1:1 timestamp match
against `provider.forward()`'s own raw series. For a coarser-than-5-minute
source (`forecast_solar`/`weather_sunshine`/`weather_cloud` — always hourly,
ADR-009 §1a), that only ever writes the one exact slot each raw sample lands on;
every other 5-minute slot in that sample's span was never written at all and
stayed permanently `None` (`to_index=None` once pushed, so `_validate_range`
never re-queries it later). `_recompute_string`'s own sibling read of the
identical `forward()` series already solves this exact problem via
`_forward_fill_by_day` — `_push_provider_series` never got the same treatment.

Confirmed directly (not just by reading): pushed a synthetic hourly `forward()`
series through the real, unmodified `_push_provider_series` and read the cache
back at every 5-minute offset — `None` everywhere except the two hour marks
bracketing the range, reproducing the report exactly.

## Acceptance Criteria

- Given `_push_provider_series` pushes a `forward()` series whose raw samples
  are spaced more than one 5-minute slot apart, when the cache is read at any
  slot between two consecutive samples, then it returns the earlier sample's
  value (held forward), not `None`.
- Given two consecutive raw samples with different values, when the cache is
  read at the exact index of the later sample, then it returns the later
  sample's own value — the forward-fill steps at the next sample's own
  timestamp, it does not interpolate between them.
- Given `provider.forward()` returns samples already at native 5-minute
  resolution (the common case today — `sensor_dict`/`sensor_list` shapes), then
  behavior is unchanged: every slot already had its own sample, so
  forward-filling it is a no-op.
- Given a diagnosed slot pinned to a non-hour-aligned time, against a baseline
  whose only source of truth is the pushed series (a future pin, or any
  `weather_sunshine`/`weather_cloud`/unresolved-`forecast_solar` baseline even
  for an already-elapsed slot), then `"selected {method}"` now appears in
  `series` — the reported symptom.
- The full test suite passes, including new coverage that fails against the
  pre-fix `_push_provider_series` and passes against the fix.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` — `_push_provider_series`
- `tests/test_coordinator.py`, `tests/test_diagnostics_compare_regressions.py` —
  new coverage
- `adr/012-provider-architecture.md` — §4 amended

## Definition of Done

- Tests green (full suite: 653 passed) · `tasks/adr-summary.md` §4's push-loop
  description updated to match · ADR-012 §4 amended · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- `mypy --config-file mypy.ini custom_components/ tests/`/`ruff check`/
  `ruff format --check`/`mdformat --check` clean on every edited file
- No new external dependencies

## Consumed Interfaces

- `_forward_fill_by_day(series, start, end) -> dict[date, dict[int, float]]`
  (`custom_components/shady/coordinator.py`, module-level) — the existing helper
  this task reuses rather than reimplementing, unchanged itself (→ ADR-009 §1a,
  `_recompute_string`'s own caller)
- `_tomorrow_end(now) -> datetime` (`custom_components/shady/coordinator.py`,
  module-level) — the same horizon bound `_recompute_string` already uses (→
  ADR-002 §3)
- `Cache.index_for(timestamp) -> int` (`custom_components/shady/cache.py`) —
  unchanged, already in use at this call site

## Delivered Artifacts

- `custom_components/shady/coordinator.py` — `_push_provider_series` now runs
  `provider.forward(now)`'s series through
  `_forward_fill_by_day(series, now, _tomorrow_end(now))` before flattening it
  into the `values: dict[int, float]` passed to `cache.push(...)`, reusing the
  existing helper and horizon rather than adding new ones. No new
  functions/classes/constants exported.
- `tests/test_coordinator.py` — new `TestGenericPushForwardFillsCoarserGrid`:
  `test_hourly_forward_series_fills_every_5_minute_slot` (an hourly `forward()`
  series fills every 5-minute slot in between, and the second hour's own sample
  still lands where expected) and
  `test_forward_fill_stops_at_the_next_raw_sample_not_the_value` (a value change
  between two samples steps at the second sample's own timestamp, not
  interpolated). Neither `provider.forward = lambda ...` reassignment carries a
  `# type: ignore[method-assign]` — `provider` traces back to this file's
  dynamically-`_load`ed `BaselineProvider`, typed `Any`, so mypy never raises
  `method-assign` there in the first place; a first pass added the comment
  anyway (habit from the same assignment against a properly-typed `Provider` in
  production code, where it genuinely is needed) and
  `warn_unused_ignores = True` (the project default everywhere except the
  handful of HA-subclassing production modules `mypy.ini` lists) correctly
  flagged it as dead — caught by running
  `mypy --config-file mypy.ini custom_components/ tests/` (the actual project
  invocation) rather than the single-file check this task's own first pass used,
  fixed the same session.
- `tests/test_diagnostics_compare_regressions.py` — new
  `TestFuturePinnedSlotSelectedResolvesOffHourAlignment`:
  `test_selected_method_appears_for_a_quarter_past_the_hour_pin` — a future pin
  a quarter past the hour, against an hourly-only pushed baseline, now shows
  `"selected method_x"` in `series` (previously absent). Same unnecessary
  `# type: ignore[method-assign]` removed, same reason as above.
- `tests/test_coordinator.py` — top-level module-load section now captures
  `_compare_regressions_mod` (previously discarded) and sets both loaded
  modules' debug-only `_DIAGNOSTIC_LOG = True` for the whole test run (both
  assignments correctly need `# type: ignore[attr-defined]` — unlike the
  `provider.forward` reassignments above, `_coordinator_mod`/
  `_compare_regressions_mod` are properly `ModuleType`-typed, not `Any`, so mypy
  does check the attribute there). Coverage regressed slightly this session (the
  human's own observation) because the new `_push_provider_series` forward-fill,
  while itself fully covered by the three tests above, changed the file's
  statement/branch denominator; auditing every currently-missing line/branch in
  both touched production files against that regression surfaced this flag and a
  handful of genuinely untested (not merely flag-gated) branches, listed below.
  Net result: `coordinator.py` 96%→98% line coverage (845 statements, 21→13
  missing), `compare_regressions.py` 94%→98% (169 statements, 4→0 missing).
  Every one of the `_DIAGNOSTIC_LOG` call sites in both modules now executes at
  least once via the suite's existing, otherwise-unrelated invocations of
  `_fit_string`/`_diagnostics_tick_sync`/
  `extra_fit`/`compute_sensor`/`_selected_value` — none raised, so the debug
  logging itself (five call sites across both modules: wrong `%`-arg count, a
  `KeyError` on `pools[...]`, etc. were the risk) is now confirmed safe to
  actually flip on in production, which was the entire point of adding it. Two
  new test classes in this file target genuinely non-defensive gaps found in the
  same audit: `TestTargetCellTemperatureForSlotEdgeCases` gained
  `test_fc_array_stays_all_nan_when_no_baseline_resolves` (no per-string or
  global baseline configured) and
  `test_fc_array_slot_stays_nan_when_baseline_value_unavailable` (baseline
  configured but no data for the queried slot); new
  `TestHandleActualYieldUpdateWithNoYieldTotal` covers `pv_sum()` returning
  `None` (every actual-yield entity unavailable) — energy accumulation is
  skipped, not crashed.
- `tests/test_diagnostics_compare_regressions.py` — three more new test classes
  from the same audit: `TestExtraFitSkipsStringWhenSelectedValueUnresolved` (a
  string with a resolved `baseline_entity_id` whose `_selected_value` still
  can't resolve `fc_selected` — distinct from, and previously conflated with,
  the already-covered "no `baseline_entity_id` at all" skip);
  `TestAppendSelectedSeriesEmptyWhenForecastUnresolved`
  (`_append_selected_ series`'s own `fc_selected is None` early return — the
  original `TASK-0037` report's exact failure mode, confirmed still graceful
  post-patch); `TestExtraFitAcrossAllRegressionStrategies` gained a sibling
  `test_temperature_tier_predicts_without_adjustment_when_unresolved`
  (`target_cell_temperature_for_slot` returning `None` for a temperature-tier
  string — predicts without the temperature array rather than raising).
  Remaining gaps in both files after this pass are either inherent to hard-
  coding `_DIAGNOSTIC_LOG = True` for the whole suite (the flag-check's own
  "off" branch can't also be covered without a second, flag-off test run — not
  pursued, low value), one statically-unreachable guard (`extra_fit()`'s
  `if predictions:` — `REGRESSION_STRATEGIES` is a fixed non-empty constant), a
  handful of already-established per-string/per-tick `except Exception`
  isolation catches (ADR-000 §8, several already covered elsewhere), or
  genuinely deeper and unrelated to this patch — energy-reset day-boundary
  no-ops, intraday-correction empty-push, a `NaN`-output skip inside the
  reverse-transform pipeline, several sequential early-returns inside the
  startup-only backfill helper (`_backfill_elapsed_today_slots_for_string`), and
  one async Forecast.Solar service-call fallback branch — each would need its
  own dedicated, non-trivial scenario in a subsystem this patch never touches;
  left as a follow-up rather than scope-creeping this fix further.
- `adr/012-provider-architecture.md` — §4 amended with the forward-fill
  rationale and its relationship to ADR-009 §1a's identical `_recompute_string`
  handling; header "Last updated" note extended.
- `tasks/adr-summary.md` — §4's one-paragraph push-loop description updated to
  mention the forward-fill step.
- No external dependencies added.
