# Task: Optional Effy Quick Config — Pick `sensor.effy_recalculated_from` to Fill the Strings and the Training Window

- **Status:** superseded — split into `TASK-0047a-effy-quick-config-flow` and
  `TASK-0047b-effy-mode-runtime` after the `grill-with-docs` session of
  2026-10-20; the slug is not reused. Kept for history: the decisions D1–D5
  below are the pre-grill proposal (D1 became live following in `TASK-0047b`,
  the rest were accepted); the settled design is in the draft ADR-016.
- **Related ADRs:** \[ADR-010 (config flow shape; the field list and the new
  step), ADR-001 §3/§4 (one model per string; the training window), ADR-002 §1a
  (the coordinator reads `entry.data` only); **Effy's ADR-021**
  (`github.com/eschnepel/effy`,
  `adr/021-config-attributes-on-recalculated-from.md`, Accepted 2026-10-18) —
  the published contract this task consumes, not an ADR of this repository\]
- **Dependencies:** [TASK-0045a-wording-alignment] (soft — see D5: it renames
  wording inside ADR-010 and `config_flow.py` comments, so this task starts
  after it to avoid a text conflict; `TASK-0035`, which shaped the flow, is
  already `done`)

> Requested by the human in chat on 2026-10-19: "add an optional quick config
> option to pick the effy recalculated from sensor. All referenced options which
> can be replaced should be hidden in the config flow if picked." No code is
> written until Gate 2 approves this file and D1–D5 are answered.

## Goal

A person who also runs Effy can pick one entity, Effy's
`sensor.effy_recalculated_from`, instead of re-entering what Effy already knows.
Effy publishes, as attributes of that sensor (its ADR-021): `sensors` (every
Effy sensor with `series`, `role`, `direction` and `source_entity_id`),
`max_history_days` and `schema_version`. Shady reads two things from it and
**hides the two config-flow options they replace** while the sensor is picked:

| Replaced option | Hidden form field | Filled from |
| -- | -- | -- |
| the strings (`CONF_STRINGS` keys, ADR-010 step `strings`) | the multi-select entity selector | every entry of `sensors` with `series: effective`, `role: pv`, `direction: input` — its `entity_id` is the string |
| the training window in days (`CONF_WINDOW_DAYS`, ADR-010 step `regression_tuning`) | the `window_days` number field | `max_history_days` |

Everything else stays as it is: baseline, per-string settings
(`string_settings_hub`/`string_settings_edit`: name, baseline override,
temperature, converter limit, …), the other regression settings, and the
advanced page. Leaving the new field empty gives exactly today's flow.

## Decisions (Lead Agent proposal — D1–D5 are open and need the human)

Defaults are what the Acceptance Criteria below assume. Changing one changes the
named criteria, noted in each line.

- **D1 — Snapshot, not live.** The flow reads the sensor when the new step is
  submitted and copies the result into `entry.data` in today's shape
  (`CONF_STRINGS` keys, `CONF_WINDOW_DAYS`), plus the picked entity ID. The
  coordinator, `cache.py`, and every entity stay untouched (ADR-002 §1a). Effy
  changes later (a new PV input, other history days) reach Shady only when the
  person re-submits the Effy step in the reconfigure menu. *Alternative:*
  resolve at every setup or by listening to the sensor (the use ADR-021 names
  for consumers) — a runtime coupling that needs a new ADR, a coordinator change
  and a reload-on-change rule, so it is a separate task if wanted. Changing D1
  voids AC 3, 7, 8 and the "No coordinator change" line.
- **D2 — All PV inputs, no subset.** Picking Effy means every Effy PV input
  becomes a string; that is what "hide the replaced option" implies. A person
  who wants a subset leaves the field empty and picks strings by hand (still
  possible with Effy's effective sensors, as the README says today).
  *Alternative:* keep the selector visible, pre-filled with Effy's PV inputs.
  Changing D2 voids AC 4 and 5.
- **D3 — Supported contract version.** Accept `schema_version == 1` only (Effy
  raises it only for a breaking change, so additive keys never block Shady);
  anything else is an error on the step, not a silent best effort.
  *Alternative:* accept any version ≥ 1. Changing D3 voids AC 2 (version case).
- **D4 — The step shows only where it can be used.** In the linear setup and in
  the reconfigure menu the Effy step exists only if the entity registry holds at
  least one entity of the `effy` platform, or the entry already stores an Effy
  entity. People without Effy never see it. *Alternative:* always show it.
  Changing D4 voids AC 1 (last sentence) and AC 7 (menu visibility).
- **D5 — Dependency on `TASK-0045a`.** Soft ordering only (text conflict
  avoidance in ADR-010 and `config_flow.py`); drop it if the human prefers to
  run this first.

Decided here, not open (follow from the request and from the code):

- **Where the field lives.** A new first step `effy` (before `baseline`) with
  one optional field `effy_entity_id`:
  `selector.EntitySelector(domain="sensor", integration="effy")` — Shady imports
  nothing from Effy; the `integration` filter is Home Assistant's own. In the
  reconfigure menu it is an additional entry. Nothing is pre-selected: picking
  is an explicit opt-in.
- **What is validated.** Only the attributes decide (not the state, which is a
  timestamp and `unknown` on a fresh Effy install): `schema_version`, `sensors`
  and `max_history_days` must be present and well-formed. Any other Effy entity,
  or a sensor without them, is rejected on the step with a form error.
- **Hidden means not in the schema and not asked, not not stored.** The derived
  values are stored in `entry.data` under the same keys and shapes as manual
  entry, so the coordinator cannot tell the two apart.
- **No migration.** The new key is optional; an existing entry without it
  behaves exactly as before (the ADR-010 "No migration" stance is unchanged).
- **Not in scope:** following Effy changes at runtime (D1), importing Effy code,
  reading `source_entity_id`, `aggregations` or the smoothed/derived series,
  mapping Effy's BMS inputs or outputs to anything in Shady, and making Effy a
  requirement (the README's "Effy isn't required" stays true).

## Acceptance Criteria

- **AC 1 — Optional, off by default.** Given the Effy step is submitted empty
  (or not shown, D4), when the flow completes, then `entry.data` is identical to
  what today's flow produces for the same inputs (the existing
  `test_config_flow.py` cases pass unchanged), and `CONF_EFFY_ENTITY_ID` is
  absent. Given no entity of the `effy` platform exists, then the step is
  skipped without a form (D4).
- **AC 2 — Validation.** Given a picked entity, when the step is submitted, then
  it is accepted only if its state attributes hold `schema_version == 1` (D3), a
  `sensors` list, and `max_history_days` as an integer ≥ 1. Otherwise the step
  re-shows with exactly one form error: `effy_not_ready` (entity missing,
  `unavailable`, or no `sensors` attribute — ADR-021: "not ready yet"),
  `effy_unsupported_schema` (`schema_version` other than 1), `effy_no_pv_inputs`
  (the list holds no entry that is `series: effective` and `role: pv` and
  `direction: input`), or `effy_not_the_recalculated_from_sensor` (an Effy
  entity without the three attributes). Each case has a test.
- **AC 3 — Derivation.** Given a valid contract, when accepted, then the strings
  are the `entity_id`s of the matching entries, in list order, with a duplicate
  dropped, and the window is `max_history_days`; `series: smoothed`,
  `derived_power`, `standby_power` and every `role: bms` entry are never
  strings. Given a string that already has settings (reconfigure), then those
  settings stay; a string no longer listed loses them; a new one gets the
  defaults (the ADR-010 rule for the multi-select, unchanged).
- **AC 4 — Strings option hidden.** Given an Effy entity is stored, when the
  flow runs linearly, then `strings` is never shown: `effy` → `baseline` →
  `string_settings_hub` → `regression_tuning` → `advanced_optional`. In the
  reconfigure menu the "Strings" entry skips the selector and opens
  `string_settings_hub` directly (that is the only way to reach per-string
  settings there). Given no Effy entity, the `strings` step is as today.
- **AC 5 — Training window hidden.** Given an Effy entity is stored, then
  `regression_tuning`'s schema has no `window_days` field and its stored value
  is `max_history_days`; every other field of that page is unchanged. Given
  none, the page is as today.
- **AC 6 — Entry shape.** `entry.data` gains the optional key
  `CONF_EFFY_ENTITY_ID` (`"effy_entity_id"`) holding the picked entity ID.
  `CONF_STRINGS` and `CONF_WINDOW_DAYS` keep their current key names and value
  shapes. A test builds the same coordinator from a manual entry and from an
  Effy-derived entry with equal strings and window and asserts equal behavior at
  the `_StringConfig` level.
- **AC 7 — Reconfigure.** The menu gains "Effy" (visible per D4), pre-filled
  with the stored entity. Submitting it again re-reads the sensor (AC 2/3) and
  replaces the derived strings and window — the only refresh path (D1). Given
  the field is cleared, then `CONF_EFFY_ENTITY_ID` is removed, the `strings`
  selector and the `window_days` field reappear, pre-filled with the last
  derived values (nothing is lost), and later manual edits behave as today.
  "Save & Finish" never re-reads the sensor.
- **AC 8 — No coordinator change.** `coordinator.py`, `cache.py`, `sensor.py`
  and the other entity modules are unchanged (verified by the diff).
- **AC 9 — Contract parsing is pure.** A pure module (no `homeassistant` import,
  ADR-000 §6 zero-mocking) maps the attributes dict to either a result (strings,
  window days) or one of the four error keys above. Unit tests cover every case
  in AC 2/3, including: missing keys, wrong types (`max_history_days` as `"28"`,
  `0`, `True`), an entry missing `series`/`role`/`direction`, an extra unknown
  key (ignored, per ADR-021's additive rule), and a duplicate `entity_id`.
- **AC 10 — Translations and docs.** `en.json` and `de.json` carry the new step
  (title, description, field label, data description), the four errors and the
  menu label; `test_translations.py` passes with its existing shape check.
  README Configuration section describes the option and names Effy's
  `max_history_days` and the PV effective sensors; the Effy section's "valid,
  ready-made input" sentence points to it. ADR-010 is edited **in place**
  (lean-ADR policy, no `Amendment` block): new step, new field, the hiding rule,
  the snapshot semantics (D1). `tasks/adr-summary.md` §6/§7 updated to match.
  GLOSSARY.md gains one term (below).

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/const.py` — `CONF_EFFY_ENTITY_ID`, the supported
  `schema_version`, the attribute and series names used from Effy's contract.
- `custom_components/shady/effy_contract.py` (new, pure) — attribute parsing (AC
  9); `adr/000-coding-standards.md` §3 module diagram gains the node.
- `custom_components/shady/config_flow.py` — step `effy` and its schema,
  `_STEP_EFFY`, derived-values helper, conditional `strings`/`window_days`
  handling, menu entry.
- `custom_components/shady/translations/en.json`, `de.json`.
- `tests/test_effy_contract.py` (new), `tests/test_config_flow.py`,
  `tests/test_translations.py`.
- `README.md`, `adr/010-config-flow-shape.md`, `adr/INDEX.md` (only if the
  ADR-010 title line changes), `tasks/adr-summary.md`, `GLOSSARY.md`.

## Glossary (proposal)

**Effy source**: The Effy `recalculated_from` sensor a person picks in the flow;
Shady reads the strings and the history days from its attributes once, when the
step is submitted. _Avoid_: Effy link, Effy sync

## Definition of Done

- Tests green; `mypy --config-file mypy.ini custom_components/ tests/`,
  `ruff check .`, `ruff format --check .` and `mdformat --check` clean on every
  edited file — run against the whole tree, not only the edited files (the
  lesson of the 2026-09-23 log rows).
- Coverage of `config_flow.py` and the new module not lower than before.
- `Delivered Artifacts` block completed and accurate.
- No new external dependency (`tasks/DEPENDENCIES.md` unchanged: the selector's
  `integration` filter ships with Home Assistant, Shady imports nothing from
  Effy).
- No open ADR conflict; ADR-010 and `tasks/adr-summary.md` read as current
  state, not as a layered amendment.

## Evidence (read 2026-10-19, not run against a live Home Assistant)

- Effy's ADR-021 (Accepted) and `custom_components/effy/const.py`:
  `PUBLISHED_SCHEMA_VERSION = 1`; attributes `schema_version`,
  `max_history_days`, `sensors` on `sensor.effy_recalculated_from`; entry keys
  `series` (`effective`, `derived_power`, `smoothed`, `standby_power`),
  `direction`, `role` (`pv`, `bms`), `source_entity_id`, `aggregations`; the
  integration's domain is `effy`.
- Effy's effective-series sensors declare `device_class` POWER, which matches
  the `device_class: [power, energy]` filter of Shady's own `strings` selector,
  so a derived string is also a valid manual pick.
- A fresh Effy install has state `unknown` and no `sensors` attribute until its
  first closing step; after a reboot ADR-021 restores the attributes (marked
  `restored_as_of`/`restored_at`) — both cases are what AC 2 distinguishes.
- Shady's current code: `ShadyConfigFlow` keeps one evolving `self._data` and
  `self._strings`; `_strings_schema` and `_regression_tuning_schema` are plain
  schema builders; `entry.data` is the only thing the coordinator reads.

**To check by the worker (not verified here):** that
`EntitySelectorConfig(integration="effy")` filters by the entity registry
platform in the installed Home Assistant version (2026.3 per the project's
target); that an entity with `unavailable` state exposes no attributes through
`hass.states.get`; the exact `translations/*.json` keys a `menu_options` entry
and a `data_description` need in this repo's existing shape.

## Consumed Interfaces

<!-- Filled by the Lead Agent before implementation. No dependency task
     delivers a symbol this task needs; it extends the flow TASK-0035 delivered. -->

- `ShadyConfigFlow` and its step methods, `_strings_schema`,
  `_regression_tuning_schema`, `_regression_tuning_defaults`,
  `_normalize_regression_tuning`, `_default_string_settings`, `_STEP_*` from
  `custom_components/shady/config_flow.py` (→ task:
  TASK-0035-reconfigure-flow-and-string-schema, `done`)
- `CONF_STRINGS`, `CONF_WINDOW_DAYS`, `DEFAULT_WINDOW_DAYS`,
  `STRING_SETTINGS_HUB_DONE` from `custom_components/shady/const.py` (→ task:
  TASK-0035-reconfigure-flow-and-string-schema, `done`)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. Be exact. -->
