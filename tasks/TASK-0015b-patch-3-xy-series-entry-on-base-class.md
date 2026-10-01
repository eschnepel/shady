# Task: `_xy_series_entry` Moved to `DiagnosticMode` — Shared by Every Diagnostic Mode, Not Just `CompareRegressionsMode`

- **Status:** done
- **Related ADRs:** [ADR-004 §2d/§5 (Amendment 2026-09-21)]
- **Dependencies:** [TASK-0015b-patch-2-plotly-graph-xy-series-format]

## Goal

Direct human follow-up, same day as `TASK-0015b-patch-2`: `_xy_series_entry` —
the function building one `custom:plotly-graph` trace entry for a `series`
attribute — was introduced as a private module-level function in
`compare_regressions.py`, `CompareRegressionsMode`'s own module. But ADR-004
§2/§5 has always described `series`'s shape as a property of `DiagnosticMode`
output in general, not anything `CompareRegressionsMode`-specific — ADR-013
already sketches future modes (`compare_providers_daily`, a whole-day snapshot
mode) that would need the exact same shape for the exact same reason. Left where
it was, a second mode would either reimplement it (risking drift from the first)
or reach across modules into `compare_regressions.py` for a function with
nothing `CompareRegressionsMode`- specific about it. This task moves it onto
`DiagnosticMode` itself (`diagnostics/base.py`) as an inherited `@staticmethod`,
so every concrete mode gets it automatically, with no cross-module reach and no
reimplementation risk.

## Acceptance Criteria

- Given any concrete `DiagnosticMode` subclass, when it calls
  `self._xy_series_entry(name, points)`, then it returns the identical
  `{"entity": "", "name": ..., "type": "scatter", "mode": "markers", "x": ..., "y": ...}`
  shape `TASK-0015b-patch-2` delivered — same keys, same values, same behavior.
  This is a pure relocation: no observable output changes for
  `CompareRegressionsMode` or anything consuming its `series` attribute.
- Given `compare_regressions.py`, then it no longer defines `_xy_series_entry`
  itself — `_pool_series`/`_append_selected_series` call
  `self._xy_series_entry(...)` (the inherited method) instead of a bare
  module-level function call.
- Given `diagnostics/base.py`, then `_xy_series_entry` is a `@staticmethod` on
  `DiagnosticMode` — not an abstract method (every mode gets the same
  implementation; nothing for a subclass to override) and not an instance method
  (no `self`-held state it needs).
- The full test suite passes unchanged in behavior — only import paths for the
  helper move, no test assertions about the *shape* it produces change.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/diagnostics/base.py` —
  `DiagnosticMode. _xy_series_entry` (new)
- `custom_components/shady/diagnostics/compare_regressions.py` — removed
  module-level `_xy_series_entry`; call sites updated
- `tests/test_diagnostics_compare_regressions.py` — updated import path for the
  reused production helper

## Definition of Done

- Tests green (full suite) · `tasks/adr-summary.md` updated · ADR-004 amended
  before implementation (Phase 0) · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- No new external dependencies

## Consumed Interfaces

- `DiagnosticMode` (`custom_components/shady/diagnostics/base.py`) — the base
  class this task adds a method to (→ task:
  TASK-0015b-diagnostics-select-and-scatter-sensors)
- `CompareRegressionsMode._pool_series`/`_append_selected_series`
  (`custom_components/shady/diagnostics/compare_regressions.py`) — the two call
  sites this task updates (→ task:
  TASK-0015b-patch-2-plotly-graph-xy-series-format)

## Delivered Artifacts

- `custom_components/shady/diagnostics/base.py` — new
  `DiagnosticMode. _xy_series_entry(name: str, points: list[list[float]]) -> dict[str, Any]`
  (`@staticmethod`), identical shape/behavior to `TASK-0015b-patch-2`'s
  module-level version.
- `custom_components/shady/diagnostics/compare_regressions.py` — removed
  module-level `_xy_series_entry`; `_pool_series`/`_append_selected_series` now
  call `self._xy_series_entry(...)`.
- No external dependencies added.
