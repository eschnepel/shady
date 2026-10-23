# Task: `series` Entries Reshaped Again — `custom:plotly-graph` x/y Arrays, Not `apexcharts-card`

- **Status:** done
- **Related ADRs:** [ADR-004 §2/§2c/§2d/§5 (Amendment 2026-09-21)]
- **Dependencies:** [TASK-0015b-patch-1-apexcharts-card-series-format]

## Goal

Direct human follow-up, same day as `TASK-0015b-patch-1`: `apexcharts-card`
turns out not to accept a numeric x-axis at all — the very axis type this
scatter chart needs (FC on x, PV on y), so patch-1's shape, while faithfully
implemented, cannot actually render what ADR-004 §2 needs anywhere. The human
found `custom:plotly-graph` does support it, and confirmed a concrete shape live
against a running instance:
`{"entity": "", "name": ..., "type": "scatter", "mode": "markers", "x": [...], "y": [...]}`
— points as two parallel flat arrays, not `[[x, y], ...]` pairs, and no
`data_generator` templating at all (`plotly-graph` takes `x`/`y` literally).
`entity` is a *constant* empty string this time, not a self-reference — data is
supplied directly, so nothing needs to be looked up from any entity's own
attributes, and per the human's validated example `entity` is present but blank
regardless.

## Acceptance Criteria

- Given the diagnostic mode is active and a string has a configured baseline,
  when `ShadyDiagnosticsSensor.extra_state_attributes` is read, then every entry
  of its `series` list has exactly the keys `entity`, `name`, `type`, `mode`,
  `x`, `y` — no `data_generator` key (patch-1's shape) and no `data` key (the
  original shape) anywhere in `series`.
- Given the same, then every entry's `entity` is the literal empty string `""`,
  `type` is `"scatter"`, `mode` is `"markers"` — constant across every entry,
  every sensor.
- Given the same, then `x`/`y` are the same `[FC_i, PV_i]` points patch-1's
  `data`/`data_generator` used to carry, split into two parallel flat arrays
  (`x[i]`, `y[i]` is the `i`-th point) — same values, same point count, same
  NaN-pair exclusion, same omission rules (§2's "selected actual" entirely
  absent for a future-pinned slot with no `PV_selected` yet).
- Given the `sensor_id="sum"` entity (§2b), then the same shape applies
  identically — shared code path, no separate branch.
- Given the diagnostic mode is off or unavailable, `extra_state_attributes`
  remains `{}` exactly as before.
- The `accuracy` attribute is untouched — same key, same shape, same values.
- Because `entity` is now a constant baked into `diagnostics/`'s own output
  rather than something depending on the entity's runtime `entity_id`,
  `sensor.py` needs **no reshaping step at all** — `extra_state_attributes`
  reverts to a plain pass-through of `result.attributes`, undoing patch-1's
  `entity`-injection addition there.
- ADR-004 §2's canonical dashboard example is the human-provided
  `custom:plotly-graph` card template (`entities:` templated from
  `state_attr("...", "series") | string`), and documents — explicitly, not just
  by example — that the `"y"` key must stay quoted in any hand-written YAML
  rendering of this shape: YAML 1.1 resolves bare `y`/`n`/`yes`/`no` to
  booleans, so an unquoted `y:` becomes the boolean key `True`, not the string
  `"y"` `plotly-graph` expects. (This is a documentation-only concern — Python's
  own `dict`/`str()` round-trip always quotes string keys — but the ADR's own
  `apexcharts-card`-era markdown tooling (`mdformat`) silently stripped exactly
  this quoting from a `yaml`-tagged fence once already; the fix is fencing that
  example as `yml` instead, not just re-adding the quotes.)

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/diagnostics/compare_regressions.py` — `_pool_series`,
  `_append_selected_series` (drop `_data_generator`, add `_xy_series_entry`)
- `custom_components/shady/sensor.py` —
  `ShadyDiagnosticsSensor.extra_state_attributes` (revert to pass-through)
- `tests/test_diagnostics_compare_regressions.py`,
  `tests/test_sensor_diagnostics.py` — updated assertions

## Definition of Done

- Tests green (full suite) · `tasks/adr-summary.md` updated · ADR-004 amended
  before implementation (Phase 0) · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- No new external dependencies

## Consumed Interfaces

- `DiagnosticSensorResult` (`custom_components/shady/diagnostics/base.py`) —
  unchanged; opaque `attributes: dict[str, Any]` (→ task:
  TASK-0015b-diagnostics-select-and-scatter-sensors)
- `ShadyDiagnosticsSensor.extra_state_attributes`
  (`custom_components/shady/sensor.py`) — the entity-injection logic
  `TASK-0015b-patch-1` added, which this task removes (→ task:
  TASK-0015b-patch-1-apexcharts-card-series-format)

## Delivered Artifacts

- `custom_components/shady/diagnostics/compare_regressions.py` — removed
  `_data_generator`; new
  `_xy_series_entry(name: str, points: list[list[float]]) -> dict[str, Any]`
  returning
  `{"entity": "", "name": name, "type": "scatter", "mode": "markers", "x": [...], "y": [...]}`;
  `_pool_series`/`_append_selected_series` now build entries via this helper.
- `custom_components/shady/sensor.py` —
  `ShadyDiagnosticsSensor. extra_state_attributes` reverted to
  `return result.attributes` (no reshaping; patch-1's `entity`-injection block
  removed).
- No external dependencies added.
