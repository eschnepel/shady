# Findings: AUDIT-0010 — Config Flow & Translations

**Auditor:** Lead Agent (inline, single-pass)
**Date:** 2026-09-06
**Verdict: 1 FAIL** — `config_flow.py`'s `baseline_manual_shape` field
(added by `TASK-0009-patch-1`) is real, required, user-facing, and
correctly implemented and translated, but was never added to ADR-010's
own field list or amendment history, contradicting ADR-010's own stated
Con ("this document has to be kept in sync whenever a future ADR adds
or changes a field") and the project's own Scenario-C/amendment
discipline. Every other Audit Criterion **PASS**es, including a fully
type-checked (not just "plausible") contract between the manual-shape
selector and `providers/normalize.py`'s `BaselineShape` Literal. **2
Test-Coverage GAPs**: no test proves `en.json`/`de.json` have identical
key **sets** independent of the schema-key check, and no test proves
the manual-shape selector's stored output is actually valid input to
`providers/normalize.py`'s parser — coverage stops at "the config flow
accepts and stores the selection." All 19 tests across both Scope Test
Files re-run live: **19/19 passed** (required installing `voluptuous`
into the sandbox — already declared as a dev dependency in
`pyproject.toml` / `tasks/DEPENDENCIES.md`, not a new dependency).

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
|---|---|---|---|
| 1 | [ADR-010] Step structure and field set match the ADR exactly; every documented field exists; no undocumented field added without an ADR amendment | **FAIL** on the undocumented-field half; PASS on everything else | All four steps (`settings`, `add_string`, `add_string_advanced`, `add_another`) exist with exactly the field counts and step-transition logic ADR-010 documents — verified field-by-field: `settings` has all 16 of ADR-010's own bulleted global fields (`config_flow.py:143-219`) plus the "manual entity + attribute path entry" sub-fields the ADR's baseline bullet itself names (`baseline_manual_entity_id`/`baseline_manual_attribute`); `add_string` has exactly the 4 ADR-documented fields (`:326-339`); `add_string_advanced` has exactly the 4 ADR-documented fields (`:405-425`); `add_another` has the 1 ADR-documented field (`:512`). **However**, `_settings_schema` also defines `baseline_manual_shape` (`:156-159`) — a real, `vol.Required`-equivalent field (technically `vol.Optional` with a default, but always rendered and always consulted for manual entries per `_normalize_settings:242-246`) added by `TASK-0009-patch-1` (`tasks/TASK-0009-patch-1-manual-baseline-shape.md`, `Status: done`). This field does not appear anywhere in ADR-010's "settings" bullet list, and ADR-010's own amendment history (`2026-08-14`, `2026-08-18`, `2026-08-20`, `2026-08-25`) has no entry documenting it — the `2026-08-25` amendment documents `recency_decay_max` (added by the sibling patch, `TASK-0009-patch-2`) but nothing was ever added for the shape selector. `TASK-0009-patch-1`'s own Definition of Done claims "no open ADR conflicts" without an ADR-010 amendment ever being written. This is a genuine documentation-sync gap, not a behavioral bug — the field itself is correctly implemented, tested, and translated (see Criteria 4 and Test-Coverage below) — but it directly contradicts ADR-010's own Consequences section, which names exactly this risk as its stated cost of being "the single place every other ADR's config-flow fields converge." |
| 2 | [ADR-001 §1] Regression-method selection exposed as a config-flow field, `wls2` pre-selected default | PASS | `CONF_REGRESSION_METHOD` (`config_flow.py:166-169`) uses `vol.In(REGRESSION_METHODS)` with `default=DEFAULT_REGRESSION_METHOD`; `const.py:16-17` defines `REGRESSION_METHODS = ("linear", "kernel", "wls2", "wls3")` and `DEFAULT_REGRESSION_METHOD = "wls2"`, matching ADR-001 §2's own table and its explicit "`wls2` (default)" designation and stated curvature/extrapolation rationale (§2, `001-empirical-shading-model.md:163,178-215`). Also confirmed: no latitude/longitude/elevation field exists anywhere in any of the three rendered step schemas (§1's own "no location field anywhere in the config flow" claim, cross-checked directly against the schema functions, not just against ADR-010's matching note). |
| 3 | [ADR-001 §4a] `recency_decay_max` exists with a sensible default/bounds; `CONF_RECENCY_DECAY_MAX` is the single source of truth shared with `coordinator.py` | PASS | `config_flow.py:178-181`: `vol.All(vol.Coerce(float), vol.Range(min=0, max=1))`, `default=DEFAULT_RECENCY_DECAY_MAX` (`const.py:71` = `0.5`) — matches §4a's "default `0.5` (50%)" and its `[0, 1)`-ish stated range ("`0` disables... values approaching `1.0`..."); `max=1` inclusive is a reasonable, non-contradicted boundary choice since the ADR never explicitly forbids exactly `1.0`. Single-source-of-truth cross-checked directly against `coordinator.py` (not just AUDIT-0005's prior write-up, though it corroborates): `coordinator.py:139` imports the same `CONF_RECENCY_DECAY_MAX` from `const.py`, `:361` reads `data[CONF_RECENCY_DECAY_MAX]` into `self._recency_decay_max`, threaded to both fit call sites (`:781`, `:840`) — one constant, one import path, no shadow/duplicate definition anywhere in either file. |
| 4 | [ADR-009 §3] Manual baseline entry offers the `_BASELINE_SHAPES` selector; each shape option is contractually matched to `providers/normalize.py`, not just plausible | PASS | `config_flow.py:75-80` defines `_BASELINE_SHAPES: tuple[BaselineShape, ...] = ("sensor_dict", "sensor_list", "weather_sunshine", "weather_cloud")`, and — critically — `BaselineShape` itself is *imported* directly from `providers/normalize.py` (`config_flow.py:70`, `from .providers.normalize import BaselineShape`), not redefined independently; `providers/normalize.py:36` defines `BaselineShape = Literal["sensor_dict", "sensor_list", "weather_sunshine", "weather_cloud"]` — the exact same four values in the exact same order. Because `_BASELINE_SHAPES` is typed as `tuple[BaselineShape, ...]`, `mypy --strict` would reject any drift (a renamed/added/removed literal on either side) as a type error, not just a runtime surprise — a genuinely type-checked contract, stronger than "independently plausible." (ADR-009 §3 itself does not mention a shape selector at all — that requirement comes from `providers/normalize.py`'s own parsing needs, correctly surfaced by `TASK-0009-patch-1`; see Criterion 1's FAIL for the resulting ADR-010 documentation gap this created.) |
| 5 | [ADR-003c §3, cross-ref] Temperature-forecast predictor source is a dedicated, explicit field, not reused from the ADR-003b §1a temperature-source field | PASS | Two distinct `const.py` constants exist and are used independently throughout: `CONF_DEFAULT_TEMPERATURE_SOURCE` (`config_flow.py:186-189`, ADR-003b §1a's field) and `CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY` (`:193-196`, ADR-003c §3's field) — separate schema keys, separate `_normalize_settings`/`_settings_defaults_from_entry_data` handling (`:258-264`, `:302-306`), no code path where one is derived from or substituted for the other. Matches §3's explicit rejection of "reused... whenever it happened to be `weather.*` domain" (`003c-temperature-forecast-via-learned-model.md:109-119`) and its "Global, not per-string... Optional; leave empty to disable" requirements — the field is `vol.Optional` (`:193`), matching "leave empty to disable this mechanism," and lives in the global `settings` step only, never in `add_string`/`add_string_advanced`. |

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | `test_config_flow.py` covers all 7 original test classes across all documented steps; both patch-added classes (`TestManualBaselineShape`, `TestRecencyDecayMax`) still exist and are exercised | COVERED | 9 classes present: the 7 original (`TestSettingsStepDefaults`, `TestBaselineDropdownDiscovery`, `TestAddStringSkipsAdvanced`, `TestBaselineOverrideImpliesTemperatureAware`, `TestRatedCapacitySkipsDerating`, `TestNoLatLongElevationField`, `TestOptionsFlowEditsAndChangesSettings`) plus `TestManualBaselineShape` (2 tests, patch-1) and `TestRecencyDecayMax` (4 tests, patch-2) — exactly matching each patch's own Delivered Artifacts claim of one dedicated class each. Total test count: 14 (8 original + 2 + 4), reconciling exactly with `TASK-0009-patch-1`'s own recorded "138/138 (128 pre-TASK-0009 + 8 TASK-0009 + 2 this patch)" gate note. |
| 2 | A test asserting a *fresh* flow actually pre-selects `wls2`, not just that it's an available option | COVERED | `TestSettingsStepDefaults::test_documented_defaults_are_stored` (`test_config_flow.py:252-265`) drives `_finish_minimal_flow`, which extracts the settings step's *own rendered schema defaults* via `_defaults_from_schema(settings_form["data_schema"])` (`:190`, reading `vol.Schema`'s actual `default=` callables — not a hardcoded literal) and submits them unmodified, then asserts `data["regression_method"] == "wls2"` and `data["temperature_regression_method"] == "wls2"` (`:256,261`). Because the submitted value comes from introspecting the schema's own default rather than being asserted independently, this genuinely proves the pre-selection, not merely availability. |
| 3 | `test_translations.py`'s schema-key-vs-label check covers **every** current schema key, including both patches' fields, not just the original TASK-0009 set | COVERED, and structurally future-proof | `test_every_schema_key_has_a_translation_label` (`test_translations.py:177-194`) does not use a hardcoded field list at all — `_SETTINGS_KEYS`/`_ADD_STRING_KEYS`/`_ADD_STRING_ADVANCED_KEYS` (`:144-148`) are computed by calling the real `_settings_schema([], {})`/`_add_string_schema([], {})`/`_add_string_advanced_schema({})` functions and reading back `.schema.keys()` at test-collection time — so `recency_decay_max` and `baseline_manual_shape` are automatically included today, and any future field addition would be automatically included too, with no test-file edit required. Confirmed live: `recency_decay_max` and `baseline_manual_shape` both have non-empty labels in both `en.json` and `de.json`. |
| 4 | A test proving `en.json`/`de.json` have identical key **sets** | **GAP** | No test in `test_translations.py` compares the two files' key sets against each other directly. `test_every_schema_key_has_a_translation_label` checks, independently per language, that every *real config-flow schema key* has a label — if a schema key's label were missing from one language, that would be caught (a passing proxy for today's actual state) — but a key added to `en.json` that is *not* tied to a real schema field (e.g. a leftover, a typo'd duplicate, or a future non-schema string like an error message) would not be checked against `de.json` at all, in either direction, since the test only iterates over schema-derived keys, never over the JSON files' own key sets. Manually diffing the two files during this audit (`json.load` + recursive flatten + set difference) confirms they are identical today (74 keys each, no divergence) — so this is a real gap in the test suite's own guarantee, not a live bug. |
| 5 | A test for the manual-baseline-shape selector's stored output being valid input to `providers/normalize.py`, not just "the config flow accepts the selection" | **GAP** | `TestManualBaselineShape`'s two tests (`test_config_flow.py:412-444`) both stop at asserting the flow *stores* the chosen shape correctly (`final["data"]["baseline_shape"] == "sensor_list"`, `:438`; and the discovered-candidate-wins case, `:443-444`) — neither test calls `providers/normalize.py::normalize_candidate_series(shape, raw)` with a matching synthetic payload to confirm the selection round-trips through the actual parser. Criterion 4 above establishes the *type-level* contract is sound (both sides import the same `Literal`), but no test exercises the *runtime* parsing contract for the manual-entry path specifically — coverage genuinely stops at "the config flow accepts and stores the selection," exactly as this criterion's own alternate phrasing anticipates. |

## Live re-execution

```
$ python3 -m pytest tests/test_config_flow.py tests/test_translations.py -q
19 passed, 1 warning in 0.07s
```

Required installing `voluptuous` into the sandbox first (`pip install
voluptuous --break-system-packages`) — already declared in
`pyproject.toml`'s dev dependency group and in `tasks/DEPENDENCIES.md`
as "already declared... do not re-add as a runtime dependency," so this
was a sandbox-setup step, not a new dependency introduced by this audit.

Also independently re-verified with a small script (not part of the
test suite): `en.json` and `de.json`, flattened, have exactly 74 keys
each with zero set difference in either direction — corroborating
Test-Coverage Criterion 4's "no live bug, but no dedicated test either"
finding.

## Candidate Follow-Ups (not created — proposed only)

1. **Audit Criterion 1's FAIL:** add an ADR-010 amendment entry (dated
   at `TASK-0009-patch-1`'s original completion, or dated today per this
   audit's own discovery — the human's call) documenting
   `baseline_manual_shape` as a "settings" step field, mirroring the
   existing `2026-08-25` `recency_decay_max` amendment's format. This is
   a documentation-only fix — no code changes needed, since the field
   itself is correctly implemented, tested, and translated. Per Phase
   0's amendment procedure, `tasks/adr-summary.md` should be checked
   for accuracy afterward too (a quick check during this audit found no
   existing adr-summary.md reference to this field either way, so no
   separate summary fix is needed beyond the ADR-010 amendment itself).
2. **Test-Coverage Criterion 4's GAP:** add a small, direct
   `en.json`-vs-`de.json` key-set-equality test to `test_translations.py`
   (a simple recursive-flatten-and-compare, similar to the one used
   ad hoc during this audit) — independent of and complementary to the
   existing schema-key check, closing the "extra/unrelated key" blind
   spot.
3. **Test-Coverage Criterion 5's GAP:** add one test to
   `TestManualBaselineShape` that feeds a synthetic payload matching
   each of the 4 `_BASELINE_SHAPES` values through
   `providers/normalize.py::normalize_candidate_series` using the exact
   `(entity_id, attribute, shape)` triple the config flow just produced,
   confirming the full pipeline, not just storage.

## Delivered Artifacts (for the task file)
- `tasks/AUDIT-0010-config-flow-translations-findings.md` (this file)
