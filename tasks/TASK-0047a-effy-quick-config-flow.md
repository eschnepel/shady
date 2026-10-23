# Task: Effy Quick Config in the Config Flow — Pick the Recalculated-From Sensor, Hide the Options It Replaces

- **Status:** todo (Gate 2 approved by the human on 2026-10-21; the design was
  settled in the `grill-with-docs` session of 2026-10-20, recorded in the
  accepted ADR-016 and ADR-017)
- **Related ADRs:** \[ADR-016 §1–3 and §7, ADR-017 §9 (both Accepted 2026-10-21
  — the decisions this task implements), ADR-010 (config flow shape, edited in
  place), ADR-001 §3/§4, ADR-002 §1a; Effy's ADR-021
  (`github.com/eschnepel/effy`,
  `adr/021-config-attributes-on-recalculated-from.md`, Accepted 2026-10-18) —
  the published contract this task reads, not an ADR of this repository\]
- **Dependencies:** [TASK-0045a-wording-alignment] (it renames wording inside
  ADR-010 and `config_flow.py` comments; starting after it avoids a text
  conflict)

> Split from `TASK-0047-effy-quick-config` (superseded, kept for history). This
> task delivers the **flow half** with snapshot semantics: the values are read
> when the Effy step is submitted. Following the sensor at runtime (trigger,
> live config, Repairs issues) is `TASK-0047b-effy-mode-runtime`. Gate 2 is
> approved.

## Goal

A person who also runs Effy picks one entity, the recalculated-from sensor,
instead of re-entering what Effy already knows. Shady reads two things from its
attributes and hides the two options they replace while it is picked (the config
entry is then in **Effy mode**, see GLOSSARY.md):

| Replaced option | Hidden form field | Filled from |
| -- | -- | -- |
| the strings (`CONF_STRINGS` keys, ADR-010 step `strings`) | the multi-select entity selector | the `entity_id` of every `sensors` entry with `series: effective`, `role: pv`, `direction: input` |
| the training window (`CONF_WINDOW_DAYS`, ADR-010 step `regression_tuning`) | the `window_days` number field | `max_history_days`, copied unchanged |

Everything else stays: baseline, per-string settings (hub and edit pages), the
other regression settings, the advanced page. Leaving the new field empty gives
exactly today's flow.

## Decisions that shape this task (grill 2026-10-20, ADR-016)

- Opt-in per entry, nothing pre-selected; key `effy_entity_id` in `entry.data`.
- All PV inputs, no subset; only `schema_version == 1`; the window is copied
  unchanged (no minus one).
- The step exists only where an `effy`-platform entity exists or one is stored.
- The new first step `effy` uses
  `selector.EntitySelector(domain="sensor", integration="effy")`; Shady imports
  nothing from Effy.
- Hidden means not asked and not shown, **not** not stored: the derived values
  go into `entry.data` under today's keys and shapes.
- The `regression_tuning` page shows, read-only, which training window was taken
  from Effy.
- This task is snapshot only; keeping up with Effy at runtime is `TASK-0047b`.
- Terms: "Effy mode", "recalculated-from sensor", "string"; never "following"
  for the sensor (GLOSSARY.md, already updated).

## Acceptance Criteria

- **AC 1 — Optional, off by default.** Given the Effy step is submitted empty
  (or not shown), when the flow completes, then `entry.data` equals what today's
  flow produces for the same inputs (the existing `test_config_flow.py` cases
  pass unchanged) and `CONF_EFFY_ENTITY_ID` is absent. Given no entity of the
  `effy` platform exists and none is stored, then the step is skipped without a
  form.

- **AC 2 — Validation.** Given a picked entity, when the step is submitted, then
  exactly one outcome applies, decided by the entity's state and attributes
  only:

  - `effy_not_ready`: the entity is missing, `unavailable` or `unknown`, or it
    carries `schema_version` but no `sensors` list (Effy has not written yet;
    ADR-021 reads an absent `sensors` as "not ready").
  - `effy_not_the_recalculated_from_sensor`: a valid state but no
    `schema_version` attribute (any other Effy entity).
  - `effy_unsupported_schema`: `schema_version` other than `1`.
  - `effy_malformed`: a wrong shape or type (`max_history_days` as `"28"`, `0`
    or `True`; `sensors` not a list of mappings).
  - `effy_no_pv_inputs`: no entry that is `series: effective`, `role: pv` and
    `direction: input`.
  - Otherwise it is accepted. A failing case re-shows the step with that one
    form error. Each case has a test.

- **AC 3 — Derivation.** Given a valid payload, then the strings are the
  matching `entity_id`s in list order with a duplicate dropped, and the window
  is `max_history_days`; `smoothed`, `derived_power` and `standby_power` series
  and every `role: bms` entry are never strings. Given a string that already has
  settings (reconfigure), those stay; a string no longer listed loses them; a
  new one gets the defaults (the ADR-010 rule, unchanged).

- **AC 4 — Strings option hidden.** Given an Effy entity is stored, the linear
  flow is `effy` → `baseline` → `string_settings_hub` → `regression_tuning` →
  `advanced_optional`; `strings` is never shown. In the reconfigure menu the
  "Strings" entry skips the selector and opens `string_settings_hub` (the only
  way to reach per-string settings there). Given no Effy entity, `strings` is as
  today.

- **AC 5 — Training window hidden.** Given an Effy entity is stored, the schema
  of `regression_tuning` has no `window_days` field, its stored value is
  `max_history_days`, and the page description says read-only which window was
  taken from Effy (a `description_placeholders` entry, one key per language).
  Every other field is unchanged. Given none, the page is as today.

- **AC 6 — Entry shape.** `entry.data` gains the optional key
  `CONF_EFFY_ENTITY_ID` (`"effy_entity_id"`). `CONF_STRINGS` and
  `CONF_WINDOW_DAYS` keep their key names and value shapes. A test builds the
  same coordinator from a manual entry and from an Effy-derived entry with equal
  strings and window and asserts equal behavior at the `_StringConfig` level.

- **AC 7 — Reconfigure.** The menu gains "Effy" (shown where AC 1's rule
  allows), pre-filled with the stored entity. Submitting it re-reads the sensor
  (AC 2/3) and replaces the derived strings and window — this is also where a
  string that Effy no longer lists is removed. Given the field is cleared, then
  `CONF_EFFY_ENTITY_ID` is removed, the `strings` selector and the `window_days`
  field reappear pre-filled with the last derived values, and later manual edits
  behave as today. "Save & Finish" never reads the sensor.

- **AC 8 — No coordinator change.** `coordinator.py`, `cache.py` and the entity
  modules are unchanged (verified by the diff).

- **AC 9 — Contract parsing is pure.** A pure module (no `homeassistant` import,
  ADR-000 §6 zero-mocking) maps `(state, attributes)` to a result (strings,
  window days) or one cause of AC 2; `TASK-0047b` reuses it unchanged. Unit
  tests cover every case of AC 2/3, an extra unknown key (ignored, per ADR-021's
  additive rule) and a duplicate `entity_id`, and run against one verbatim JSON
  fixture of an Effy schema-1 payload (`tests/fixtures/`, copied from ADR-021's
  example; source ADR and date in a comment).

- **AC 10 — Translations and docs.** `en.json` and `de.json` carry the new step
  (title, description, field label, data description), the five errors, the menu
  label and the read-only window line; `test_translations.py` passes with its
  existing shape check. README Configuration section describes the option and
  names Effy's `max_history_days` and the PV effective sensors; the Effy
  section's "valid, ready-made input" sentence points to it. ADR-010 is edited
  **in place** (lean-ADR policy, no `Amendment` block): the new step, the new
  field, the hiding rule, the snapshot semantics. `tasks/adr-summary.md` §6/§7
  updated.

- **AC 11 — README retention rule (valid with and without Effy mode).** The
  README Requirements section is corrected and extended: the limit for the
  5-minute statistics Shady trains on is the configured `purge_keep_days`, not a
  fixed 10 days separate from it (the current sentence is wrong; Effy's README
  and code, which reads the live value, are right; ADR-017 §9). It states the
  two numbers for a training window of *N* days: **minimum** `purge_keep_days` =
  *N* + 1, **optimal** 2 × *N*, with the reason (the newest refit reads the *N*
  whole days before today plus today's running day; a refit or pinned
  diagnostics for the oldest day still inside the window needs *N* days before
  that day), and names the default window of 28 days (29 / 56). In Effy mode *N*
  is Effy's `max_history_days`. Docs only: no code reads `purge_keep_days`.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/const.py` — `CONF_EFFY_ENTITY_ID`, the supported
  `schema_version`, the attribute and series names read from Effy's contract.
- `custom_components/shady/effy_contract.py` (new, pure) — AC 9;
  `adr/000-coding-standards.md` §3 module diagram gains the node.
- `custom_components/shady/config_flow.py` — step `effy`, `_STEP_EFFY`, the
  derivation helper, conditional `strings`/`window_days` handling, menu entry.
- `custom_components/shady/translations/en.json`, `de.json`.
- `tests/test_effy_contract.py` and `tests/fixtures/` (new),
  `tests/test_config_flow.py`, `tests/test_translations.py`.
- `README.md`, `adr/010-config-flow-shape.md`, `tasks/adr-summary.md`.

## Definition of Done

- Tests green; `mypy --config-file mypy.ini custom_components/ tests/`,
  `ruff check .`, `ruff format --check .` and `mdformat --check` clean, run
  against the whole tree and not only the edited files (the lesson of the
  2026-09-23 log rows).
- Coverage of `config_flow.py` and the new module not lower than before.
- `Delivered Artifacts` block completed and accurate.
- No new external dependency (`tasks/DEPENDENCIES.md` unchanged).
- No open ADR conflict; ADR-010 and `tasks/adr-summary.md` read as current
  state.

## Evidence (read 2026-10-19/20, not run against a live Home Assistant)

- Effy's ADR-021 (Accepted) and `const.py`: `PUBLISHED_SCHEMA_VERSION = 1`;
  attributes `schema_version`, `max_history_days`, `sensors` on
  `sensor.effy_recalculated_from`; entry keys `series` (`effective`,
  `derived_power`, `smoothed`, `standby_power`), `direction`, `role` (`pv`,
  `bms`), `source_entity_id`, `aggregations`; the integration's domain is
  `effy`. Effy's `max_history_days` accepts 1–365; Shady's `window_days` accepts
  ≥ 1, so every Effy value is valid.
- Effy's effective-series sensors declare `device_class` POWER, which matches
  the `device_class: [power, energy]` filter of Shady's own `strings` selector.
- A fresh Effy install has state `unknown` and no `sensors` until its first
  closing step; after a reboot ADR-021 restores the attributes (marked
  `restored_as_of`/`restored_at`).
- Shady's current code: `ShadyConfigFlow` keeps one evolving `self._data` and
  `self._strings`; `_strings_schema` and `_regression_tuning_schema` are plain
  schema builders; `entry.data` is all the coordinator reads.

**To check by the worker (not verified here):** that
`EntitySelectorConfig(integration="effy")` filters by the entity registry
platform in the targeted Home Assistant version (2026.3); that an `unavailable`
entity exposes no attributes through `hass.states.get`; the exact
`translations/*.json` keys a `menu_options` entry, a `data_description` and a
`description_placeholders` entry need in this repo's existing shape.

## Consumed Interfaces

<!-- Filled by the Lead Agent before implementation. No dependency task delivers
     a symbol this task needs; it extends the flow TASK-0035 delivered. -->

- `ShadyConfigFlow` and its step methods, `_strings_schema`,
  `_regression_tuning_schema`, `_regression_tuning_defaults`,
  `_normalize_regression_tuning`, `_default_string_settings`, `_STEP_*` from
  `custom_components/shady/config_flow.py` (→ task:
  TASK-0035-reconfigure-flow-and-string-schema, `done`)
- `CONF_STRINGS`, `CONF_WINDOW_DAYS`, `DEFAULT_WINDOW_DAYS`,
  `STRING_SETTINGS_HUB_DONE` from `custom_components/shady/const.py` (→ task:
  TASK-0035-reconfigure-flow-and-string-schema, `done`)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. Be exact. TASK-0047b consumes this
     block: the parser's module path, result type and cause names, and the const
     names. -->
