# Task: Config Flow

- **Status:** done
- **Related ADRs:** [ADR-010, ADR-001 §1]
- **Dependencies:** [TASK-0003-baseline-forecast-discovery]

## Goal
Implement `config_flow.py`: `ShadyConfigFlow`'s `settings` →
`add_string` → `add_string_advanced` → `add_another` step sequence with
every field ADR-010 specifies (defaults included), plus
`ShadyOptionsFlow` mirroring it for post-setup editing. No code in this
project imports `config_flow.py`'s classes downstream — it is a leaf
module in the dependency graph, so it can be developed in parallel with
most other tasks once its one real dependency (discovery scoring) is
done.

## Acceptance Criteria
- Given the `settings` step, When submitted with defaults, Then the
  resulting config-entry data contains exactly ADR-010's documented
  global fields at their documented defaults (`window_days=28`,
  `regression_method="wls2"`, `smoothing_radius=1`,
  `neighbor_fitting_cutoff=0.25`, `clipping_threshold=0.98`,
  `max_uplift_c=25`, `temperature_regression_method="wls2"`,
  `intraday_correction_mode="off"`, `intraday_correction_cutoff=0.10`,
  `window_slots=24`, `ramp_slots=12`).
- Given the global baseline-candidate dropdown, When rendered, Then it is
  populated by calling TASK-0003's discovery/scoring function, ranked,
  with a "None of these" manual entity+attribute fallback always present
  (ADR-009 §3).
- Given `add_string` with "Configure advanced corrections?" left off,
  When submitted, Then the flow proceeds directly to `add_another`,
  skipping `add_string_advanced` entirely.
- Given `add_string_advanced` with a baseline candidate override set for
  that string, When the flow completes, Then that string is
  automatically treated as temperature-aware, with no separate flag
  asked (ADR-003b §1c / ADR-010's `add_string` note).
- Given `add_string_advanced`'s "Rated DC capacity" field left empty for
  a string on the ambient/weather temperature tier, When the flow
  completes, Then the stored config reflects "skip derating for this
  string" per the skip-both-sides rule (ADR-003c §5 / ADR-010).
- Given the completed flow, When rendered against ADR-001 §1's decision,
  Then no latitude/longitude/elevation field is presented anywhere.
- Given `ShadyOptionsFlow`, When invoked on an existing config entry,
  Then it can add/edit strings and change any global setting, following
  the same step shape as initial setup.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/config_flow.py`
- `tests/test_config_flow.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0003. -->
- `providers.discovery.discover_baseline_candidates(hass) -> list[BaselineCandidate]` from `custom_components/shady/providers/discovery.py` (→ task: TASK-0003-baseline-forecast-discovery)
- `providers.discovery.BaselineCandidate` (frozen dataclass: `entity_id: str`, `attribute: str`, `shape: BaselineShape`, `score: float`, `label: str`) from `custom_components/shady/providers/discovery.py` (→ task: TASK-0003-baseline-forecast-discovery)
- `providers.normalize.BaselineShape` (the `Literal["sensor_dict","sensor_list","weather_sunshine","weather_cloud"]` type alias) from `custom_components/shady/providers/normalize.py` (→ task: TASK-0003-baseline-forecast-discovery)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/const.py` → rewritten from its placeholder;
  exports every `CONF_*` config-entry data key ADR-010 specifies (global
  `settings` fields + per-string `strings`-list fields), plus
  `REGRESSION_METHODS`, `INTRADAY_CORRECTION_MODES`, their `DEFAULT_*`
  constants, `CONF_STRINGS` (the list-of-strings key, name assigned by
  the Lead Agent — ADR-010 never names it), and three sentinels:
  `BASELINE_CANDIDATE_MANUAL`, `BASELINE_CANDIDATE_NONE`,
  `TEMPERATURE_SOURCE_NONE`.
- `custom_components/shady/config_flow.py` → `class ShadyConfigFlow
  (config_entries.ConfigFlow, domain=DOMAIN)`: `async_step_user`
  (delegates to `async_step_settings`), `async_step_settings`,
  `async_step_add_string`, `async_step_add_string_advanced`,
  `async_step_add_another`, `async_get_options_flow`. `class
  ShadyOptionsFlow(config_entries.OptionsFlow)`: `async_step_init`
  (delegates to `async_step_settings`) plus the same four step methods,
  pre-filled from `self.config_entry.data`, walking existing strings one
  at a time for re-confirmation/editing before allowing new ones via the
  trailing `add_another` loop. Shared module-level helpers (used by both
  classes — a mixin base class was considered and rejected; see the
  module docstring for why): `_candidate_choices`,
  `_resolve_candidate_choice`, `_optional_float`, `_settings_schema`,
  `_normalize_settings`, `_settings_defaults_from_entry_data`,
  `_add_string_schema`, `_string_defaults`, `_build_current_string`,
  `_add_string_advanced_schema`, `_apply_advanced`.
- `tests/test_config_flow.py` → 8 tests (7 test classes) covering all 7
  acceptance criteria, driven through a hand-written, real (non-`Mock`)
  `homeassistant` stub registered in `sys.modules` (see below) plus the
  existing `FakeHomeAssistant`/`FakeState`/`FakeStates` pattern
  (duplicated here per this project's established convention of
  duplicating small hass fixtures per test file rather than
  cross-importing — see `test_providers_temperature.py`'s own note).
- **Testing-infrastructure decision, flagged for TASK-0010/0011/0015
  (all remaining HA-facing modules):** `config_flow.py` is outside
  ADR-000 §6's zero-mocking pure tier — it genuinely subclasses
  `homeassistant.config_entries.ConfigFlow`/`OptionsFlow` at runtime, not
  just under `TYPE_CHECKING`. No ADR specifies how HA-facing modules
  (`config_flow.py`/`sensor.py`/`coordinator.py`/`switch.py`/`button.py`)
  should be tested locally, and the project declares no `homeassistant`
  dev dependency (a full install is a large, unrelated dependency this
  project's own `pyproject.toml` deliberately excludes — HA is supplied
  by the host runtime, per `manifest.json`). This task's `_install_ha_stub()`
  in `tests/test_config_flow.py` — a small, hand-written, real (non-`Mock`)
  stand-in for exactly the `homeassistant.core`/`config_entries`/
  `data_entry_flow` surface actually touched, registered directly into
  `sys.modules` before the module-under-test is file-path-loaded — is a
  direct extension of the same "real stand-in, not a mock" philosophy
  `FakeHomeAssistant`/`FakeState` already establish for
  `providers/discovery.py`/`providers/temperature.py`. Each subsequent
  HA-facing task should build its own small stub the same way (matching
  the project's stated preference for per-file duplication over
  cross-test-file imports), not attempt a full `homeassistant` install.
- `custom_components/shady/translations/en.json` /
  `translations/de.json` — **not updated in this task**; left at their
  placeholder `"data": {}` content. Populating every new field's label
  is real work with no functional test coverage possible (translation
  content isn't asserted anywhere) and no downstream task consumes it;
  flagged here rather than silently skipped so a later polish pass (or
  the human) can pick it up.
- External dependencies added: `voluptuous` — already declared (dev
  dependency group, `pyproject.toml`) before this task; now actually
  installed in this sandbox and genuinely imported at runtime by
  `config_flow.py` (previously declared but unused). No new entry
  needed in `tasks/DEPENDENCIES.md`.
- Gates: `ruff check` — zero errors on all 3 new/changed files (plus a
  harmless import-sort auto-fix applied to `config_flow.py`'s own import
  block). `mypy --config-file mypy.ini` — zero issues, 28 source files
  total. Two targeted suppressions per ADR-000 §2, both on the exact
  flagged line: `class ShadyConfigFlow(config_entries.ConfigFlow,
  domain=DOMAIN):  # type: ignore[misc, call-arg]` (mypy treats the
  unresolved `ConfigFlow` base's `__init_subclass__` as `object`'s,
  which doesn't accept `domain=`) and `@callback  # type:
  ignore[untyped-decorator]` on `async_get_options_flow`. `pytest` —
  full suite 136 tests, all pass (128 pre-existing + 8 new).
  `ruff format --check`: `config_flow.py`/`const.py`/
  `test_config_flow.py` all report "already formatted" after one
  `ruff format` pass; the two pre-existing `normalize.py`/
  `temperature.py` reformatting diffs this run also surfaces are the
  already-documented TASK-0003 sandbox `ruff format` bug (untouched by
  this task).
