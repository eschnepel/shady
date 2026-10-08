# Task: Diagnostic Chart Marker Styling — One-Decimal Values, Weight-Sized Points, Stroke for Excluded Neighbors, Cross for Selected

- **Status:** done
- **Related ADRs:** \[ADR-004 §2/§2d/§2e/§2h/§5 (Amendment 2026-10-04), ADR-011
  §2/§3, ADR-001 §2/§4a\]
- **Dependencies:** [TASK-0015b-patch-3-xy-series-entry-on-base-class]

## Goal

Direct human request: every trace of the diagnostic scatter chart is currently
drawn identically, so the chart cannot show how much each training point counts
in the fit, which neighbor series ADR-011 §2 excluded, or which points are the
diagnosed slot's predictions. Add a `marker` to every `series` entry (ADR-004
§2h) and round the plotted values: at most one decimal; slot-pool point size
following the fit weight (weight `1` → size `4`, integer sizes); ADR-011
§2-excluded neighbor series drawn as a stroke; `selected ...` series drawn as a
cross.

## Acceptance Criteria

- Given any `series` entry, when it is built, then its `x` and `y` values are
  rounded to one decimal place (a `-0.0` result is normalised to `0.0`), and its
  keys are exactly `entity`, `name`, `type`, `mode`, `x`, `y`, `marker`.
- Given a slot-pool series, then `marker.symbol` is `"circle"` and `marker.size`
  is a list with one integer per plotted point, equal to
  `max(1, round(4 × weight))` where `weight` is `build_pool`'s combined weight
  for that point (`WeightBreakdown.combined_weight`) — so weight `1.0` → size
  `4`.
- Given a neighbor offset that `build_pool` excluded (ADR-011 §2,
  `neighbor_excluded`), then its series uses `marker.symbol == "line-ns"`, and
  its `marker.size` is computed from the weight the point would have had without
  the exclusion (`magnitude × time × recency × valid`), not from the zeroed
  combined weight — so no stroke is size `0`.
- Given a neighbor offset that is not excluded (including every offset when
  `neighbor_fitting_cutoff` is the rescale sentinel, ADR-011 §3, and offset
  `0`), then its symbol is `"circle"` and its sizes equal the combined weight
  formula above.
- Given any `selected {method}` or `selected actual` series, then
  `marker == {"symbol": "x"}` (no `size`), and its single point's `x`/`y` are
  rounded to one decimal like every other series.
- Given the `sensor_id="sum"` entity (§2b), then the identical rules apply, with
  weights and exclusion evaluated on the pointwise-summed pool (shared code
  path, no separate branch).
- Given the diagnostic mode is off or unavailable, `extra_state_attributes`
  remains `{}` exactly as before; `accuracy` is untouched — same key, same
  shape, full-precision values; the CSV export (ADR-015) is untouched — full
  precision.
- `sensor.py` still performs no reshaping at all — `series` passes through
  unchanged.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/diagnostics/base.py` —
  `DiagnosticMode._xy_series_entry` (rounding, `symbol`/`sizes` parameters,
  `marker` key)
- `custom_components/shady/diagnostics/compare_regressions.py` — `_pool_series`
  (weights/exclusion from `build_pool`), `_append_selected_series` (cross),
  sizing helper and symbol constants
- `tests/diagnostics/test_base.py`,
  `tests/diagnostics/test_compare_regressions.py`,
  `tests/test_sensor_diagnostics.py` — updated and new assertions

## Definition of Done

- Tests green (full suite), `mypy`, `ruff` and `mdformat --check` clean ·
  `tasks/adr-summary.md` updated · ADR-004 amended before implementation (Phase
  0\) · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- No new external dependencies

## Consumed Interfaces

- `DiagnosticMode._xy_series_entry(name, points)`
  (`custom_components/shady/diagnostics/base.py`) — the entry builder this task
  extends (→ task: TASK-0015b-patch-3-xy-series-entry-on-base-class)
- `CompareRegressionsMode._pool_series` / `_append_selected_series`
  (`custom_components/shady/diagnostics/compare_regressions.py`) — the two call
  sites this task updates (→ task:
  TASK-0015b-patch-3-xy-series-entry-on-base-class)
- `build_pool(..., return_weight_breakdown=True)` and `WeightBreakdown`
  (`custom_components/shady/regression/base.py`) — read-only; already imported
  by `compare_regressions.py` for the CSV export (→ task:
  TASK-0038-diagnostic-slot-raw-data-csv-export)

## Delivered Artifacts

- `custom_components/shady/diagnostics/base.py` — new module constant
  `SERIES_VALUE_DIGITS = 1`; new private `_round_value(value: float) -> float`
  (`round(value, SERIES_VALUE_DIGITS) + 0.0`, normalising `-0.0`);
  `DiagnosticMode._xy_series_entry(name: str, points: list[list[float]], *, symbol: str = "circle", sizes: Sequence[int] | None = None) -> dict[str, Any]`
  (`@staticmethod`) now returns
  `{"entity": "", "name": name, "type": "scatter", "mode": "markers", "x": [...], "y": [...], "marker": {"symbol": symbol[, "size": [...]]}}`
  with `x`/`y` rounded; `sizes` must match `points` one-to-one (assertion).
- `custom_components/shady/diagnostics/compare_regressions.py` — new module
  constants `_SYMBOL_POOL = "circle"`, `_SYMBOL_EXCLUDED_NEIGHBOR = "line-ns"`,
  `_SYMBOL_SELECTED = "x"`, `_WEIGHT_UNIT_SIZE = 4`, `_MIN_MARKER_SIZE = 1`; new
  `_marker_size(weight: float) -> int`;
  `CompareRegressionsMode._pool_series(settings, pool)` now runs
  `build_pool(..., return_weight_breakdown=True)` on the pool it is given (a
  string's, or the summed pool for `"sum"`) and emits per-point sizes plus
  `line-ns` for `neighbor_excluded` offsets;
  `CompareRegressionsMode._append_selected_series` passes
  `symbol=_SYMBOL_SELECTED` for every `selected ...` entry. No signature changes
  beyond the above; `export_csv`, `accuracy`, and `sensor.py` untouched.
- Tests: `tests/diagnostics/test_base.py` (+8, `TestXySeriesEntry`),
  `tests/diagnostics/test_compare_regressions.py` (+21: `_marker_size`
  parametrized, `TestPoolSeriesMarkerSizes`,
  `TestExcludedNeighborSeriesIsAStroke`, `TestSelectedSeriesAreCrosses`; 3
  existing exact-shape assertions rebuilt with hand-derived sizes),
  `tests/test_sensor_diagnostics.py` (fixture carries `marker`).
- No external dependencies added.
