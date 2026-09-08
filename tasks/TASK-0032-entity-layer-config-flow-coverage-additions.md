# Task: Entity-Layer & Config-Flow Test-Coverage Additions

- **Status:** done
- **Related ADRs:** [ADR-004, ADR-009, ADR-010]
- **Dependencies:** [TASK-0015b-diagnostics-select-and-scatter-sensors, TASK-0019-config-flow-translations, TASK-0009-patch-1-manual-baseline-shape]

## Goal
Two audits (`AUDIT-0009`, `AUDIT-0010`) each found small, additive
test-coverage gaps in the entity/config-flow layer:

1. **No test asserts entity `unique_id` distinctness with a real
   ≥2-string fixture** in the entity layer's own test files.
   `test_sensor_diagnostics.py`'s `_CountingDiagnosticMode` fixture
   already constructs two `ShadyDiagnosticsSensor` instances from two
   ids (`"0"`, `"1"`), but no test asserts
   `sensor_0._attr_unique_id != sensor_1._attr_unique_id` — the
   underlying guarantee is real and tested elsewhere (at the
   `sensor_ids()`-producer level in `test_diagnostics_compare_
   regressions.py`), but nothing in the entity layer's own tests
   exercises it directly.
2. **No test compares `en.json`/`de.json`'s key sets directly.**
   `test_every_schema_key_has_a_translation_label` checks, per language,
   that every real config-flow schema key has a label — but a key added
   to one language file that isn't tied to a real schema field (a
   leftover, a typo'd duplicate, a future non-schema string) would not
   be caught in either direction, since the existing test only iterates
   schema-derived keys, never the JSON files' own key sets.
3. **No test proves the manual-baseline-shape selector's stored output
   is valid input to `providers/normalize.py`'s actual parser** — both
   `TestManualBaselineShape` tests stop at asserting the flow *stores*
   the chosen shape correctly; neither calls
   `normalize_candidate_series(shape, raw)` with a matching synthetic
   payload to confirm the selection round-trips through the real parser.

## Known Decisions
- All three additions are pure, additive tests — no production code
  changes anywhere in this task.
- Item 1 should reuse the existing two-string fixture already present in
  `test_sensor_diagnostics.py` rather than building a new one.
- Item 2 should mirror `test_translations.py`'s own existing
  introspection style (load both JSON files, flatten keys, compare sets)
  — the same manual check the audit itself performed ad hoc.

## Open Questions for Execution
- None expected for items 1 and 2. **Item 3 has one small scope
  question:** should the new round-trip test cover all four
  `_BASELINE_SHAPES` values (`sensor_dict`, `sensor_list`,
  `weather_sunshine`, `weather_cloud`), or just the shape(s) already
  exercised by `TestManualBaselineShape`'s existing two tests? The audit's
  own recommendation says "each of the 4 `_BASELINE_SHAPES` values" —
  default to all four unless the worker finds a reason one is
  impractical to synthesize a payload for, in which case note which one
  and why here before skipping it.
- **Note on TASK-0022 interaction:** if `TASK-0022` (sunshine-duration
  rescaling) lands Option B (adding a rescale step) before this task
  runs, the `weather_sunshine` round-trip test added here should
  exercise the *post-rescale* behavior, not the pre-rescale one this
  task file was written against. Check `TASK-0022`'s own status/
  Delivered Artifacts before writing that specific sub-case.

**Resolved — 2026-09-08:** `TASK-0022` is still `todo` (checked
`tasks/INDEX.md` before writing item 3), so the pre-rescale
`weather_sunshine` behavior this task file was written against is the
correct one to test here — no adjustment needed. Item 3's scope
question resolved to the default: all four `_BASELINE_SHAPES` values
covered, one synthetic payload each; none were impractical to
synthesize.

## Acceptance Criteria
- Given `tests/test_sensor_diagnostics.py`, When run after this task,
  Then it contains a new test asserting `unique_id` distinctness across
  its existing two-string `_CountingDiagnosticMode` fixture.
- Given `tests/test_translations.py`, When run after this task, Then it
  contains a new test directly comparing `en.json`'s and `de.json`'s
  flattened key sets for equality, independent of and complementary to
  the existing schema-key check.
- Given `tests/test_config_flow.py`'s `TestManualBaselineShape` class,
  When run after this task, Then it contains new test(s) feeding a
  synthetic payload for each covered `_BASELINE_SHAPES` value through
  `providers/normalize.py::normalize_candidate_series` using the exact
  `(entity_id, attribute, shape)` triple the config flow just produced,
  confirming the full pipeline round-trips, not just that the value is
  stored.
- Given the full test suite, When run after this task, Then all
  pre-existing tests still pass unmodified, plus the three additions.

## Estimated File / Module Footprint (hint, not a commitment)
- `tests/test_sensor_diagnostics.py`
- `tests/test_translations.py`
- `tests/test_config_flow.py`
- No production `.py` file.

## Definition of Done
- Tests green · docs updated (none needed — test-only) · no open ADR
  conflicts
- `Delivered Artifacts` block completed and accurate, listing the exact
  new test names added per file
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/sensor.py` → `ShadyDiagnosticsSensor` — (→
  task: TASK-0015b) — the class item 1's new test exercises.
- `custom_components/shady/translations/en.json`,
  `custom_components/shady/translations/de.json` — (→ task:
  TASK-0019-config-flow-translations) — the two files item 2's new test
  compares.
- `custom_components/shady/config_flow.py` → `_BASELINE_SHAPES`,
  `baseline_manual_shape` field — (→ task:
  TASK-0009-patch-1-manual-baseline-shape) — the selector item 3's new
  test round-trips.
- `custom_components/shady/providers/normalize.py` →
  `normalize_candidate_series` — (→ task:
  TASK-0003-baseline-forecast-discovery) — the parser item 3's new test
  feeds a synthetic payload through.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
- `tests/test_sensor_diagnostics.py` → new
  `TestDiagnosticsSensorUniqueIdDistinctness` class (inserted before
  `TestDiagnosticsSensorNeverCallsComputeItself`), one test:
  `test_unique_id_differs_across_two_sensor_ids` — reuses the existing
  `_make_setup()`/`_CountingDiagnosticMode` two-string fixture,
  constructs `sensor_0`/`sensor_1` the same way the existing tests do,
  asserts `_attr_unique_id` distinctness and that each contains its own
  `sensor_id`.
- `tests/test_translations.py` → new `_flatten_keys()` helper and new
  `test_en_and_de_have_identical_key_sets` test (inserted before
  `test_every_step_has_a_real_title_and_description`) — recursively
  flattens both `_TRANSLATIONS["en"]`/`["de"]` dicts into dotted-path
  key sets and asserts symmetric-difference is empty in both
  directions, independent of the existing schema-key-driven check.
- `tests/test_config_flow.py` → `_normalize_mod` now captures
  `providers/normalize.py`'s already-loaded module (previously loaded
  but discarded); new `import pytest`; new
  `test_selected_shape_round_trips_through_the_real_parser` on
  `TestManualBaselineShape`, `@pytest.mark.parametrize`d over all four
  `_BASELINE_SHAPES` values, each with a payload actually shaped like
  that source (`sensor_dict`: timestamp-keyed dict; `sensor_list`:
  list-of-dicts with `datetime`/`value`; `weather_sunshine`:
  list-of-dicts with `datetime`/`sunshine_duration`; `weather_cloud`:
  list-of-dicts with `datetime`/`cloud_coverage`, verified the inversion
  applies: `cloud_coverage=40.0` → series value `60.0`). Drives the
  manual-entry path through the real flow, then feeds the exact stored
  `(entity_id, attribute, shape)` triple's `shape` into
  `normalize_candidate_series` with the matching synthetic payload,
  asserting a non-empty canonical series. All four payloads verified
  empirically against the real `providers/normalize.py` module before
  being written into the test — none were impractical, so item 3's open
  scope question resolved to the audit's own default (all four).
- No production `.py` file touched — `git diff --stat` confirms exactly
  the three test files above, matching the Estimated Footprint.
- External dependencies added: none. `tasks/DEPENDENCIES.md` unchanged.
- Full local gate after this task: `pytest` 433/433 passed (427 + 6
  new: 1 + 1 + 4-parametrized); `mypy --config-file mypy.ini
  custom_components/ tests/` clean on 53 source files; `ruff check .`
  clean repo-wide; `ruff format --check .` shows only the one
  pre-existing, unrelated, already-documented drift file
  (`adr/004-diagnostics-select-and-scatter-sensor.md`'s embedded code
  block), untouched, out of scope — none of this task's three edited
  files needed reflowing this time.
