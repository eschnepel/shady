# Task: `series` Entries Reshaped for Direct `apexcharts-card` Use

- **Status:** done
- **Related ADRs:** [ADR-004 §2/§2b/§5 (Amendment 2026-09-21)]
- **Dependencies:** [TASK-0015b-diagnostics-select-and-scatter-sensors]

## Goal

Direct human request, this session: `ShadyDiagnosticsSensor`'s `series`
attribute (ADR-004 §2) was shaped as `{"name": ..., "data": [[x, y], ...]}` —
"pre-shaped for direct use as an ApexCharts scatter chart `series` option," per
the original design. That assumption held for the raw ApexCharts JS library, but
the popular Home Assistant Lovelace card most people actually pair this with,
`apexcharts-card`, does not take a raw ApexCharts `series` array — each of its
own `series` list entries instead needs its own `entity`/`name`/
`data_generator` fields, `data_generator` being a JS-code string returning the
point array. The human confirmed, live against a running instance, that
`{"entity": ..., "name": ..., "data_generator": "return [[x, y], ...]"}` is
exactly what `apexcharts-card` expects and renders correctly — so each `series`
entry the sensor emits is reshaped to that contract directly, replacing
`data`/no-`entity` entirely (human's explicit choice — a single format the
attribute emits, not two shapes for two audiences, since the whole point of this
attribute is dashboard consumption in the first place).

## Acceptance Criteria

- Given the diagnostic mode is active and a string has a configured baseline,
  when `ShadyDiagnosticsSensor.extra_state_attributes` is read, then every entry
  of its `series` list has exactly the keys `entity`, `name`, `data_generator` —
  no `data` key anywhere in `series`.
- Given the same, then every entry's `entity` value is that sensor's own
  `entity_id` (self-reference, matching `apexcharts-card`'s per-series-block
  contract) and `name` is unchanged from today's naming (`"-1"`/`"0"`/`"1"`/…,
  `"selected {method} ({accuracy}%)"`, `"selected {method}"`,
  `"selected actual"`).
- Given the same, then each entry's `data_generator` is the exact string
  `"return " + json.dumps(points)`, where `points` is the same
  `[[FC_i, PV_i], ...]` (or single-point `[[FC_selected, predicted]]`) data the
  old `data` key used to carry — same values, same point count, same NaN-pair
  exclusion, same omission rules (§2's "selected actual" entirely absent for a
  future-pinned slot with no `PV_selected` yet) — only the container around
  those points changes.
- Given the `sensor_id="sum"` entity (§2b), then the same three-key shape
  applies identically — it shares `_pool_series`/`_append_selected_series` with
  the per-string entries, so no separate code path is needed or written.
- Given the diagnostic mode is off or a `sensor_id` is otherwise unavailable
  (`state` is `"disabled"`/`"unavailable"`), then `extra_state_attributes`
  remains `{}` exactly as before — nothing about this task changes that path.
- The `accuracy` attribute is untouched: same key, same shape, same values —
  this task only reshapes `series` entries.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/diagnostics/compare_regressions.py` — `_pool_series`,
  `_append_selected_series` (name/data\* build, `data` -> `data_generator`)
- `custom_components/shady/sensor.py` —
  `ShadyDiagnosticsSensor.extra_state_attributes` (injects `entity` —
  `diagnostics/` has no way to know its own future `entity_id`, so this one key
  is added at the point that does)
- `tests/test_diagnostics_compare_regressions.py`,
  `tests/test_sensor_diagnostics.py` — updated assertions

## Definition of Done

- Tests green (full suite) · `tasks/adr-summary.md` updated · ADR-004 amended
  before implementation (Phase 0) · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- No new external dependencies (`json` is stdlib)

## Consumed Interfaces

- `DiagnosticSensorResult` (`custom_components/shady/diagnostics/base.py`) —
  unchanged; `attributes: dict[str, Any]` is opaque to `base.py`, so no edit
  needed there (→ task: TASK-0015b-diagnostics-select-and-scatter-sensors)
- `ShadyDiagnosticsSensor` (`custom_components/shady/sensor.py`) — the
  `extra_state_attributes` property this task edits in place (→ task:
  TASK-0015b-diagnostics-select-and-scatter-sensors)

## Delivered Artifacts

- `custom_components/shady/diagnostics/compare_regressions.py` — new module
  function `_data_generator(points: list[list[float]]) -> str`
  (`"return " + json.dumps(points)`); `_pool_series` and
  `_append_selected_series` now emit `{"name": ..., "data_generator": ...}` (no
  `data` key) per `series` entry; `import json` added.
- `custom_components/shady/sensor.py` —
  `ShadyDiagnosticsSensor.extra_state_attributes` now rebuilds each `series`
  entry as
  `{"entity": self.entity_id, "name": entry["name"], "data_generator": entry["data_generator"]}`
  before returning; `accuracy` and every other attribute key pass through
  unchanged.
- No external dependencies added.
