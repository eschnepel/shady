# Task: Patch — Manual Baseline Entry Needs a Shape Selector

- **Status:** done
- **Related ADRs:** [ADR-009 §3, ADR-010]
- **Dependencies:** [TASK-0009-config-flow]

## Goal
`TASK-0009`'s "settings" step lets a user bypass discovery entirely via
"None of these (enter manually)" (ADR-009 §3), storing a manually-typed
`baseline_entity_id`/`baseline_attribute` with `baseline_shape=None`.
`providers.discovery.BaselineProvider` (TASK-0003) requires a real
`BaselineShape` (`"sensor_dict"|"sensor_list"|"weather_sunshine"|
"weather_cloud"`) to parse that attribute at all — `shape=None` cannot
construct a working provider. Discovered while gathering TASK-0010's
Consumed Interfaces (Scenario C: a `done` task's delivered interface
turned out insufficient) — `TASK-0009` stays `done` and unreopened; this
adds the missing field instead.

## Acceptance Criteria
- Given the `settings` step's baseline dropdown set to "None of these
  (enter manually)", When the form is rendered, Then a required shape
  selector (the same four `BaselineShape` values) is shown, defaulting
  to `"sensor_dict"`.
- Given the `settings` step submitted with manual entry and a chosen
  shape, When the flow completes, Then the stored `baseline_shape` is
  exactly that choice (not `None`).
- Given the `settings` step submitted with a *discovered* candidate
  (not manual entry), When the flow completes, Then the manual shape
  field's value is ignored entirely — the candidate's own shape is
  used, exactly as before this patch.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/config_flow.py` (`_settings_schema`,
  `_normalize_settings`, `_settings_defaults_from_entry_data`)
- `tests/test_config_flow.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
- `providers.normalize.BaselineShape` (the four-value `Literal`) from
  `custom_components/shady/providers/normalize.py` (→ task:
  TASK-0003-baseline-forecast-discovery) — already consumed by
  TASK-0009; not re-derived here.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/config_flow.py` → added `_BASELINE_SHAPES`
  (tuple of the four `BaselineShape` values) and `_DEFAULT_MANUAL_SHAPE`
  ("sensor_dict"); `_settings_schema` gained a `baseline_manual_shape`
  field (`vol.In(_BASELINE_SHAPES)`, default `"sensor_dict"`);
  `_normalize_settings` now stores that choice as `CONF_BASELINE_SHAPE`
  for manual entries (only when a non-empty entity_id was actually
  typed — an empty manual entry still stores `baseline_shape=None`,
  unchanged); `_settings_defaults_from_entry_data` round-trips it for
  the options flow.
- `tests/test_config_flow.py` → `TestManualBaselineShape` (2 tests):
  field presence + correct storage for a manual entry, and confirms a
  *discovered* candidate's own shape still wins (manual field ignored)
  when one is selected instead.
- No external dependencies added.
- Gates: `ruff check`/`ruff format --check`/`mypy --strict` all clean;
  full suite 138/138 (128 pre-TASK-0009 + 8 TASK-0009 + 2 this patch).
