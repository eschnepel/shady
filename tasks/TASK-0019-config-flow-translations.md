# Task: Config-Flow Translations — Replace Placeholder en/de Content

- **Status:** done
- **Related ADRs:** [ADR-010, ADR-000]
- **Dependencies:** [TASK-0009-config-flow, TASK-0009-patch-1-manual-baseline-shape, TASK-0009-patch-2-recency-decay-config-field]

## Goal
`custom_components/shady/translations/en.json` and `de.json` still carry
their original Phase-0 placeholder content — `"data": {}` for both the
`config.step` and `options.step` sections, and a description literally
reading "Placeholder – config flow fields to be defined per ADR-001 §6"
— even though `config_flow.py` has long since been fully implemented
with four real steps (`settings`, `add_string`, `add_string_advanced`,
`add_another`) and roughly two dozen real fields between them (ADR-010).
The GitHub release pipeline copies `en.json` verbatim into the shipped
`strings.json`, so every install today shows this placeholder text and
no field labels at all in the actual config-flow UI. This task replaces
it with real step titles, descriptions, and per-field `data` labels, in
both English and German, matching the field set `config_flow.py` (both
`ShadyConfigFlow` and `ShadyOptionsFlow`, which reuse the same four step
IDs) actually defines today.

## Acceptance Criteria
- Given `config_flow.py`'s `_settings_schema`, `_add_string_schema`,
  `_add_string_advanced_schema`, and the inline `add_another` schema,
  When their `vol.Required`/`vol.Optional` keys are compared against
  `translations/en.json`'s `config.step.<step_id>.data` and
  `options.step.<step_id>.data` entries, Then every key present in a
  schema has a corresponding, non-empty label in both places that reuse
  that step id (the `settings`/`add_string`/`add_string_advanced` steps
  are shared, byte-for-byte step ids, between `config.step` and
  `options.step`; `add_another`'s single `"add_another"` field the same).
  Write this as an actual test (see Definition of Done) — a manual
  cross-check is not durable against future field additions.
- Given the same comparison against `translations/de.json`, When run,
  Then it holds there too — both languages, not just English.
- Given each of the four `config.step.*`/`options.step.*` entries, When
  read, Then each has a real, non-placeholder `title` and `description`
  (no literal "Placeholder" or "to be defined" wording remaining
  anywhere in either file).
- Given `config_flow.py`'s own docstrings/comments (e.g. `_settings_schema`'s
  "ADR-010, global fields, in the document's own field order",
  `_add_string_advanced_schema`'s note on which of its four fields
  actually applies being resolved downstream rather than hidden), When
  writing field descriptions, Then this task does not invent behavior
  beyond what ADR-010 and the field's own default/validator already
  establish (e.g. don't imply `add_string_advanced` fields are
  conditionally shown — they aren't, per that same docstring).
- Given `config_flow.py` currently never passes `errors=` to any
  `async_show_form` call (no `vol.Invalid`-driven error path exists in
  the code today), When this task is done, Then `config.error`/
  `config.abort`/`options.error` sections are left as they are (`{}`) —
  this task does not invent error-key translations for a validation-UX
  that does not exist yet in the code (that would be a separate,
  code-level task, not a translation-content one).
- Given `ruff format --check .` (JSON files aren't ruff's concern, but
  the new test file is), `mypy --config-file mypy.ini custom_components/
  tests/`, and the full test suite, When run after this task, Then all
  three stay clean/green (52+1 source files clean; 414+N tests green,
  N being however many this task's new test file adds).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/translations/en.json`
- `custom_components/shady/translations/de.json`
- `tests/test_translations.py` (new — the schema-vs-translation-keys
  consistency check described above; can import `config_flow.py`'s
  schema-building functions directly rather than needing a full
  `homeassistant` stub, if a real `voluptuous` import is enough for
  them — check what `config_flow.py` itself imports from
  `homeassistant.*` before deciding whether a stub is needed at all)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `config_flow.py`'s `_settings_schema(candidates, defaults)`,
  `_add_string_schema(candidates, defaults)`,
  `_add_string_advanced_schema(defaults)` (→ task: TASK-0009-config-flow,
  TASK-0009-patch-1-manual-baseline-shape,
  TASK-0009-patch-2-recency-decay-config-field) — the exact field keys
  this task's translations and consistency test must cover. Each
  accepts an empty/placeholder `candidates`/`defaults` argument fine for
  the purpose of reading back `vol.Schema(...).schema.keys()`.
- `const.py`'s `CONF_*` constants (pre-existing) — the literal string
  values several of the above schema keys resolve to.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/translations/en.json` → rewritten. `config
  .step`/`options.step` now have four real steps each — `settings`
  (19 fields), `add_string` (4 fields), `add_string_advanced`
  (4 fields), `add_another` (1 field) — every key copied verbatim from
  `config_flow.py`'s own `vol.Required`/`vol.Optional` schema keys
  (`_settings_schema`, `_add_string_schema`,
  `_add_string_advanced_schema`, plus the inline `"add_another"` key),
  each with a real, non-placeholder label; every step has a real,
  non-placeholder `title`/`description`. `config.error`/`config.abort`/
  `options.error` deliberately left as `{}` (see task Goal/Acceptance
  Criteria — no `errors=` path exists in the code yet). `entity.sensor`
  section untouched (`{}`, out of this task's scope).
- `custom_components/shady/translations/de.json` → same structure,
  German field labels/step titles/descriptions, same key set, same
  `error`/`abort` sections left empty.
- `tests/test_translations.py` (new) → 5 tests: schema-key-vs-label
  cross-check (both languages, both `config`/`options` sections, all
  four steps — the durable, future-proof consistency check this task's
  Acceptance Criteria require), no-placeholder-wording check, real-
  title/description check, `error`/`abort` sections still empty check,
  and a check that no wording implies `add_string_advanced`'s fields
  are conditionally shown (they aren't, per that schema function's own
  docstring). Loads `config_flow.py` via the same hand-written,
  real-non-Mock `homeassistant` stub-and-file-path-load convention
  `test_config_flow.py` already established, duplicated (not imported)
  per this project's per-file self-contained-harness convention.
  **Cross-file note for future maintainers, spelled out in this file's
  own module docstring too:** five other test files (`test_button.py`,
  `test_coordinator.py`, `test_init.py`, `test_sensor_aggregates.py`,
  `test_sensor_forecast.py`) each install their own
  `homeassistant.config_entries` stub, then re-fetch
  `sys.modules["homeassistant.config_entries"].ConfigEntry`
  *dynamically at test-run time* inside their own `_make_entry`
  helpers — since pytest collects every file's module-level code before
  running any test, whichever such stub is collected *last*
  (alphabetically, this new file, now) is the one all five actually get
  at run time. This file's `_ConfigEntry` therefore intentionally
  matches their shared `(entry_id, data)` two-positional-argument shape
  byte-for-byte, even though this file's own tests never construct one
  — an earlier draft used a zero-argument stub instead and broke all
  five of those files' `TypeError: _ConfigEntry() takes no arguments`,
  with the failures surfacing entirely inside unrelated-looking test
  files. Caught by running the full suite (not just this file in
  isolation) before considering the task done; re-verified stable
  under both forward and reverse file-collection order.
- No new external dependency — `tasks/DEPENDENCIES.md` unchanged.
- Verification: full suite 414 → 419/419 (5 new, all pre-existing
  still green, confirmed stable under both normal and reverse
  alphabetical file-collection order); `mypy --config-file mypy.ini
  custom_components/ tests/` clean on 53 source files; `ruff check .`
  clean repo-wide; `ruff format --check .` shows only the same two
  pre-existing, already-documented drift files as before this task
  (`tests/test_regression.py`, `adr/004-diagnostics-select-and-scatter
  -sensor.md`'s embedded code block) — neither touched here, and this
  task's own new file formats clean. `git diff --stat`/`git status`
  confirm only the two translation files were modified and
  `tests/test_translations.py` added — no `.py` source file under
  `custom_components/` touched.
