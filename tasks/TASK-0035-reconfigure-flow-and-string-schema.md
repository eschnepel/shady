# Task: Config Flow Redesign — Paged Global Settings, Multi-Select Strings, Per-String Settings Loop, Reconfigure-Flow Migration

- **Status:** done
- **Related ADRs:** \[ADR-010 (rewritten in place, 2026-09-18, to present this
  task's reshape as the single current Decision — no longer a same-task
  amendment layered on an earlier, superseded sketch), ADR-002 §1a (unchanged,
  referenced — `entry.data`-only reads), ADR-000 §8 (unchanged, referenced),
  ADR-003a/ADR-003b/ADR-003c/ADR-006/ADR-009/ADR-011/ADR-001 §4a (unchanged —
  every field this task relocates keeps the exact meaning and default those ADRs
  already gave it; only its page/step changes)\]
- **Dependencies:** [] (none — independent of `TASK-0034`/`TASK-0034-patch-1`;
  touches `config_flow.py` only, which neither of those touched)

## Goal

Real-world bug report, same session as `TASK-0034-patch-1`: a user attempted a
reconfiguration and the changed configuration did not get written. Root cause
(confirmed against Home Assistant's own documentation, not guessed):
`ShadyOptionsFlow`'s final step returns
`self.async_create_entry(title="", data={...})` — in Home Assistant this writes
to `entry.options`, never `entry.data`, and `coordinator.py` reads exclusively
from `entry.data` (ADR-002 §1a). No reconfiguration has ever actually taken
effect, since initial release — not a race, a standing bug.

Human's explicit choice, given the shipped flow was going to be touched either
way: don't just patch the persistence bug — reshape the whole flow while in
there. What shipped today asks for a string's *entire* configuration (name,
baseline override, actual-yield entity, advanced corrections) in one cramped,
repeated `add_string`/`add_string_advanced`/`add_another` loop, before a person
has even seen their own strings laid out together, and crams every global
setting (baseline *and* every regression/temperature/intraday knob) into one
single first step. The reshape (full design: ADR-010's amendment): global
settings split across three pages (`baseline`, `regression_tuning`,
`advanced_optional`); strings defined by one multi-select entity field (pattern
borrowed from Effy's own multi-sensor fields — `github.com/eschnepel/effy` —
adapted, since Effy has no per-item settings concept at all) instead of a
repeated add-one-at-a-time loop; each string's own settings reached via a
hub-and-loop rather than crammed into that same repeated loop; reconfigure moves
off `ShadyOptionsFlow` onto `ConfigFlow.async_step_reconfigure`, linear for
first setup, menu-driven (`async_show_menu`, jump straight to the one section
that needs changing) for reconfigure.

## Acceptance Criteria

**Linear first-setup flow (`async_step_user`)**

- Given a fresh setup, when it proceeds, then the step order is exactly
  `baseline` → `strings` → (`string_settings_hub`/`string_settings_edit` loop,
  skipped entirely if `strings` selected zero entities) → `regression_tuning` →
  `advanced_optional` → `self.async_create_entry(title="Shady", data=...)`.
- Given the `strings` step, when its schema is built, then it is exactly one
  `selector.EntitySelector` field (`domain="sensor"`,
  `device_class=["power", "energy"]`, `multiple=True`) — no other field on this
  step, and no separate per-string "add" step exists anywhere.
- Given at least one entity was picked in `strings`, when `string_settings_hub`
  is entered, then it presents a choice of every picked entity_id (label: that
  string's name if already set this session, else the entity_id itself) plus a
  "Done" option; picking an entity_id enters `string_settings_edit` for that
  entity_id and returns to this same hub afterward; picking "Done" proceeds to
  `regression_tuning`.
- Given `string_settings_edit` for a specific entity_id, when its schema is
  built, then it contains exactly: optional name (default `""`), optional
  baseline candidate override (same dropdown as the global default, plus a
  distinct "use the global default" sentinel — not the global step's own "None
  of these" sentinel), optional temperature-source override, optional
  converter/inverter AC power limit, temperature coefficient (default −0.4),
  optional rated DC capacity — with no "configure advanced corrections?" gate of
  any kind; every field is always shown.
- Given an entity was picked in `strings`, given `string_settings_edit` was used
  to configure it, when that same entity is later removed from `strings` (same
  session, before the flow's final step), then `string_settings_hub` no longer
  offers it, and its settings are absent from the flow's eventual result
  entirely — not retained for a possible later re-add within the same session.
- Given `regression_tuning`, when its schema is built, then it contains exactly:
  `window_days` (default 28), `regression_method` (default `wls2`),
  `smoothing_radius` (default 1), `neighbor_fitting_cutoff` (default 25%),
  `recency_decay_max` (default 50%), `clipping_threshold` (default 98%) — the
  `baseline`/`temperature_aware` pair and every `advanced_optional` field
  (below) are absent from this step.
- Given `advanced_optional`, when its schema is built, then it contains exactly:
  default temperature source, `max_uplift_c` (default 25), weather forecast
  temperature entity, `temperature_regression_method` (default `wls2`),
  `intraday_correction_mode` (default off), `intraday_correction_cutoff`
  (default 10%), intraday window slots (default 24), intraday ramp slots
  (default 12).

**Menu-driven reconfigure (`async_step_reconfigure`)**

- Given a person opens reconfigure on an existing entry, when the flow starts,
  then it shows an `async_show_menu` with exactly the options "Baseline,"
  "Strings," "Regression Tuning," "Advanced & Optional Settings," and "Save &
  Finish" — not the linear sequence above.
- Given any one menu option other than "Save & Finish" is chosen, when its step
  (or, for "Strings," its `strings` → hub/loop sequence) is submitted, then the
  flow returns to this same top-level menu — never proceeds onward to another
  section linearly.
- Given any step reached from the menu, when it is shown, then every field is
  pre-filled from the existing config entry's current data — global settings,
  and (for "Strings") the currently-configured entity_ids and each one's
  existing per-string settings, exactly as `ShadyOptionsFlow` already did, not
  regressed by this migration.
- Given "Save & Finish" is chosen, when the flow completes, then it calls
  `self.async_update_reload_and_abort(self._get_reconfigure_entry(), data_updates=...)`
  with the accumulated changes from whichever sections were actually visited —
  `entry.data` reflects every changed value, the integration reloads with the
  new configuration in effect, and no data is lost for a section the person
  never opened (`data_updates=`'s merge semantics, not a full `data=` replace).
- Given the reconfigure flow is abandoned before "Save & Finish" (closed,
  cancelled), when this happens, then the existing config entry is completely
  untouched — including any string removed mid-session per the discard rule
  above, which was never persisted regardless.

**Cross-cutting**

- Given `ShadyOptionsFlow` is removed, when `ShadyConfigFlow` is inspected, then
  `async_get_options_flow` is removed too — not left pointing at a deleted class
  — and nothing in `hass.config_entries.flow` machinery expects an options-flow
  handler for this integration's entries any longer.
- Given this integration defines no `unique_id` scheme (one relevant config
  entry per physical installation, no external account to mismatch), when
  `async_step_reconfigure` is implemented, then it does **not** call
  `async_set_unique_id`/`_abort_if_unique_id_mismatch` — there is no identity
  here for a mismatch to protect against, and adding that pairing anyway would
  be a false safety check.
- Given the migration, when `strings.json`/`translations/en.json` (whichever
  this project uses — confirm at implementation time) are checked, then the
  `reconfigure_successful` abort reason this flow now produces has a translated
  string present — HA's own documented requirement for
  `async_update_reload_and_abort`, not optional polish.
- Given no migration path is implemented for the old `CONF_STRINGS`
  list-of-dicts shape (deliberate — see ADR-010's amendment; exactly one
  installation exists as of this task), when this task ships, then
  `coordinator.py`'s own reading of `CONF_STRINGS` is updated to match whatever
  the new shape turns out to be (per-string settings keyed by `entity_id` rather
  than a list of dicts each carrying their own `actual_yield_entity_id`) — this
  task's own Delivered Artifacts must record the exact new `entry.data` shape
  precisely, since `coordinator.py`'s `_resolve_string`/`_StringConfig`
  construction is a direct consumer of it and needs updating in lock-step, not
  left reading the old shape.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/config_flow.py` — substantial rewrite:
  `ShadyOptionsFlow` removed entirely; `ShadyConfigFlow` gains
  `async_step_reconfigure` plus new step methods `async_step_baseline`,
  `async_step_strings`, `async_step_string_settings_hub`,
  `async_step_string_settings_edit`, `async_step_regression_tuning`,
  `async_step_advanced_optional`; a
  `self._reconfigure_entry: ConfigEntry | None` (or equivalent) distinguishing
  linear-vs-menu dispatch; a `self._editing_entity_id: str | None` (or
  equivalent) tracking which string `string_settings_edit` currently targets —
  the pattern `homeassistant.helpers.schema_config_entry_flow` itself documents
  for this exact "sub-item being edited" need.
- `custom_components/shady/const.py` — new/renamed `CONF_*` constants for the
  new per-string-settings-keyed-by-entity_id shape; `CONF_STRING_NAME` becomes
  `vol.Optional`.
- `custom_components/shady/coordinator.py` — `_resolve_string`/`_StringConfig`
  construction updated to read the new `entry.data` shape.
- `custom_components/shady/strings.json` / `translations/en.json` — new step
  titles/descriptions for six step methods (was three), the reconfigure menu's
  option labels, and the `reconfigure_successful` abort reason.
- `tests/test_config_flow.py` — substantial rewrite: existing `ShadyOptionsFlow`
  tests rewritten against the menu-driven `async_step_reconfigure`; existing
  `add_string`/`add_string_advanced`/ `add_another` tests rewritten against
  `strings`/`string_settings_hub`/ `string_settings_edit`; new tests for the
  discard-on-removal rule and the menu's return-to-menu-not-onward behavior.
- `tests/test_coordinator.py` — `_make_entry`'s `strings=[...]` fixture shape
  (used extensively — see `TASK-0034-patch-1`'s own tests, for one) needs
  updating to match whatever the new `entry.data` shape turns out to be; a
  non-trivial, cross-cutting change to confirm carefully before starting, not a
  footnote.

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate — in particular, the exact
  new `entry.data` shape for strings (field names, nesting), since multiple
  other files' tests depend on constructing it correctly
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected — `selector.EntitySelector`, `async_show_menu`, and
  `async_update_reload_and_abort` are all core Home Assistant, already the same
  category as e.g. `homeassistant.helpers.entity_registry` used elsewhere in
  this project)

## Consumed Interfaces

<!-- No dependency tasks, so this stays empty per the template's own
     instruction ("leave empty if none"); everything this task touches
     (`config_flow.py`'s current schema/step functions, `coordinator.py`'s
     `_resolve_string`) is pre-existing code being modified in place, not a
     cross-task handoff. -->

## Delivered Artifacts

- `custom_components/shady/config_flow.py` — full rewrite. `ShadyConfigFlow`
  (unchanged base class/domain) gains `async_step_baseline`,
  `async_step_strings`, `async_step_string_settings_hub`,
  `async_step_string_settings_edit`, `async_step_regression_tuning`,
  `async_step_advanced_optional`, `async_step_reconfigure`, `async_step_finish`;
  `async_step_user` now delegates straight to `async_step_baseline`.
  `ShadyOptionsFlow` and `async_get_options_flow` are removed outright — no stub
  left behind. Flow state: `self._data: dict[str, Any]` (every global field,
  flat, keyed by the same `CONF_*` constants `entry.data` itself uses — seeded
  from `dict(reconfigure_entry.data)` minus `CONF_STRINGS` on reconfigure, empty
  on first setup), `self._strings: dict[str, dict[str, Any]]` (same pattern for
  per-string settings), `self._editing_entity_id: str | None`,
  `self._reconfigure_entry: ConfigEntry | None`,
  `self._candidates: list[BaselineCandidate]`. Schema-building functions
  (module-level, not methods): `_baseline_schema`, `_strings_schema`,
  `_hub_schema`, `_string_settings_edit_schema`, `_regression_tuning_schema`,
  `_advanced_optional_schema` — each paired with a `_normalize_*`/`_build_*`
  (submission → canonical dict) and a `_*_defaults` (canonical dict → form
  defaults) function. Helpers: `_candidate_choices`/`_resolve_candidate_choice`/
  `_find_candidate_choice` (baseline dropdown, reused for both the global step
  and the per-string override), `_optional_float`/`_blank_if_none` (optional
  numeric field round-trip), `_default_string_settings`, `_hub_choices`.
- `custom_components/shady/const.py` — removed `CONF_STRING_ACTUAL_YIELD_ENTITY`
  and `CONF_STRING_CONFIGURE_ADVANCED`. Added
  `STRING_SETTINGS_HUB_DONE = "__done__"` (the hub dropdown's "Done" sentinel).
  `CONF_STRING_NAME` is now `vol.Optional` (default `""`) wherever it's used in
  `config_flow.py`. Every other `CONF_*` constant (global and per-string) is
  unchanged in name, meaning, and default.
- **`entry.data` shape** (the exact shape downstream code/tests must match):
  every global field from `baseline`/`regression_tuning`/`advanced_optional` is
  stored flat, keyed by its own `CONF_*` constant, exactly as before this task
  (only which step collects it changed). `CONF_STRINGS`
  (`entry.data["strings"]`) is now `dict[str, dict[str, Any]]` keyed by each
  string's own `entity_id` — **not** a list. Each value dict has exactly these
  keys: `name` (`str`, default `""`), `baseline_entity_id` (`str | None`),
  `baseline_attribute` (`str | None`), `baseline_shape` (`str | None`),
  `baseline_history_entity_id` (`str | None` — ADR-009 §1c Amendment/ADR-012 §2a
  Amendment carry-through), `temperature_aware` (`bool`), `converter_limit_w`
  (`float | None`), `temperature_source_entity_id` (`str | None`),
  `temperature_coefficient_pct_per_c` (`float`, default `-0.4`),
  `rated_dc_capacity_wp` (`float | None`). No `actual_yield_entity_id` field
  anywhere inside this dict — the `entity_id` key it's stored under *is* that
  value.
- `custom_components/shady/coordinator.py` —
  `_resolve_string(index, entity_id, raw)` (new `entity_id` parameter — no
  longer reads `raw[CONF_STRING_ACTUAL_YIELD_ENTITY]`, uses the passed-in dict
  key instead; `name` now `raw.get(CONF_STRING_NAME, "")`, not
  `raw[CONF_STRING_NAME]`). `ShadyCoordinator.__init__`'s `self._strings`
  construction now iterates `data.get(CONF_STRINGS, {}).items()` instead of
  `enumerate(... , [])`. `_resolve_stale_forecast_solar_history_entities`
  (`TASK-0034-patch-1`)'s rebuild-on-resolve logic updated for the dict shape
  (`new_strings: dict[str, dict[str, Any]] | None`, iterates `.values()`,
  reassigns `new_data[CONF_STRINGS] = new_strings` as a dict). No other
  production file touches `CONF_STRINGS` (confirmed by full-codebase grep before
  starting) — `sensor.py`/`button.py`/`select.py`/`diagnostics/*` needed zero
  changes, fully isolated by the `_StringConfig` dataclass, which keeps its own
  `actual_yield_entity_id` attribute name unchanged.
- `custom_components/shady/translations/en.json` /
  `custom_components/shady/translations/de.json` — full rewrite: `config.step`
  now has `baseline`, `strings`, `string_settings_hub`, `string_settings_edit`,
  `regression_tuning`, `advanced_optional` (each with `title`/`description`/
  `data` labels for every real schema field), and `reconfigure` (a menu step —
  `title`/`description`/`menu_options` for `baseline`/`strings`/
  `regression_tuning`/`advanced_optional`/`finish`, no `data` block). The
  `options` top-level section is removed entirely. `config.abort` now has one
  key, `reconfigure_successful`, translated in both languages. `config.error`
  stays `{}` (no validation-error UX exists).
- `README.md` — Configuration section rewritten to describe the five-step linear
  flow and the menu-driven Reconfigure entry point.
- `tasks/adr-summary.md` — §6 (`ShadyConfigFlow` bullet) and §7 (Config flow
  shape) updated to drop the "not yet implemented / `Status: todo`" framing now
  that this is the shipped design.
- `tests/test_config_flow.py` — full rewrite, 42 tests. Extends the file's own
  hand-written `homeassistant` stub with `_get_reconfigure_entry`,
  `async_update_reload_and_abort`, `async_show_menu`, a
  `FakeConfigEntriesManager`
  (`async_get_entry`/`async_update_entry`/`async_loaded_entries`), and a real
  `_EntitySelector`/`_entity_selector_config` stand-in for
  `homeassistant.helpers.selector`. Covers every Acceptance Criterion above:
  linear step order, exact schema field sets per step, discard-on-removal
  (including same-session re-add), reconfigure menu options/prefill/return-to-
  menu/save-and-finish/abandon-leaves-entry-untouched, `ShadyOptionsFlow`
  removal, no-`unique_id`-calls, no-lat-long-fields,
  baseline-override-implies-temperature-aware, `baseline_history_entity_id`
  carry-through (global and per-string), manual baseline shape, empty
  rated-capacity → `None`, `recency_decay_max` round-trip.
- `tests/test_translations.py` — full rewrite, 7 tests, against the new step set
  and the `reconfigure` menu step; `options`-section assumption removed;
  `config.abort` now asserted to contain exactly `reconfigure_successful` with a
  real label (previously asserted empty).
- `tests/test_coordinator.py`, `tests/test_coordinator_temperature_forecast.py`,
  `tests/test_button.py`, `tests/test_init.py`,
  `tests/test_sensor_aggregates.py`, `tests/test_sensor_forecast.py` — every
  literal `CONF_STRINGS`/`strings=` fixture construction converted from a list
  of dicts (each carrying its own `actual_yield_entity_id`) to a dict keyed by
  that same entity_id, matching the new `entry.data` shape.
- External dependencies added: none. `tasks/DEPENDENCIES.md` unchanged —
  `homeassistant.helpers.selector` (`EntitySelector`/`EntitySelectorConfig`),
  `async_show_menu`, `_get_reconfigure_entry`, and
  `async_update_reload_and_abort` all ship with the `homeassistant` package
  itself, same category as `aiohttp`/`homeassistant.helpers.device_registry`
  already used elsewhere in this project.
