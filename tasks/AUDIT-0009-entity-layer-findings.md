# Findings: AUDIT-0009 — HA Entity Layer (sensor / button / select)

**Auditor:** Lead Agent (inline, single-pass)
**Date:** 2026-09-06
**Verdict:** No behavioral FAIL — every entity reads/formats/exposes
exactly what `coordinator.py`/`aggregation.py`/`diagnostics/` already
computed, nothing is recomputed locally, and the switch→select rename
(ADR-004's 2026-08-30 amendment) left zero residue anywhere in this
layer. **1 PARTIAL** on the ADR-000 §3 module-boundary sub-question:
two of `sensor.py`'s nine entity classes read `coordinator.cache`
directly (bypassing the coordinator-method convention the other seven
follow), an explicit, task-time-reviewed decision (TASK-0011's own
Consumed Interfaces block authorizes it) that is nonetheless not
reflected anywhere in ADR-000 §3's own module-dependency diagram or its
"`coordinator.py` [is] the only module that imports `cache.py`" claim.
**1 coverage GAP**: no test in this audit's Scope Test Files constructs
a ≥2-string fixture and asserts two entities' `unique_id`s differ — the
underlying `sensor_id` distinctness is already guaranteed upstream and
tested elsewhere (AUDIT-0008's territory), but nothing in *this* layer's
own tests exercises it. All 40 tests across the five Scope Test Files
re-run live during this audit: **40/40 passed**, no `homeassistant`
package required (hand-written stubs throughout).

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
|---|---|---|---|
| 1 | [ADR-000 §3] No business logic beyond thin read/format/expose | PASS, business-logic sub-check; **PARTIAL**, module-boundary sub-check | Grepped all three files for arithmetic operators (`+`/`*`/`/`): the only hits are `today_start + _ONE_DAY` and `day_start + _LAST_SLOT_OF_DAY` (`sensor.py:143,149`) — pure window-boundary construction, not forecast/correction math. Every `native_value`/`extra_state_attributes` body is a direct coordinator/aggregation read (`coordinator.pv_sum()`, `.fc_sum()`, `.fc_day_array()`, `.fc_day_energy_total()`, `.fc_remaining_energy()`, `.diagnostic_result()`, `.active_diagnostic_mode()`) with only `isoformat()`/`None`-coalescing formatting on top — matches the docstring's own claim (`sensor.py:15-22`). **However**, `ShadyForecastSensor.native_value`/`.extra_state_attributes` (`sensor.py:131-167`) and `ShadyPvEnergyIntegralSensor`/`ShadyFcEnergyIntegralSensor.native_value` (`sensor.py:279-302`) call `self._coordinator.cache.get_time_range(...)`/`.energy_total(...)` directly — reaching two hops past "coordinator" into `cache.py`'s own public API — while the other seven sensor classes go through a dedicated coordinator method (`pv_sum()`, `fc_sum()`, etc.) that itself wraps the equivalent cache read. ADR-000 §3's module diagram draws only `entity_glue --> coordinator` (no `entity_glue --> cache` edge), and `coordinator.py`'s own module docstring (`coordinator.py:1`) states it is *"the only module that imports `cache.py`"*. `sensor.py` never `import`s `cache.py` (confirmed via `grep -rn "import.*cache" *.py`), so the literal import-statement claim holds — but three of nine sensor classes still depend directly on `cache.py`'s public method signatures via `coordinator.cache`, which the diagram doesn't show and which is inconsistent with the other seven classes' own convention within the same file. |
| 2 | [ADR-002 §3] Forecast sensor exposes the documented today(remaining)+tomorrow horizon | PASS | `ShadyForecastSensor.extra_state_attributes` (`sensor.py:140-167`) builds `today`/`tomorrow` via `cache.get_time_range` over the full calendar-day boundary each, matching §3's "remainder of today... and all of tomorrow" plus its own "not recomputed does not mean not retained" clause (already-past slots stay populated because `coordinator.py` pushes on compute, never queries them back) — confirmed against ADR-002 §3's text directly, not just `adr-summary.md`. `native_value` separately exposes just the current-slot value, the conventional single-state-value HA pattern; the full horizon lives in the attributes, which is where §3 itself expects a "chart-friendly" full array (cross-referencing ADR-005's parallel `slot_timestamps`/`slot_values` pattern). No mismatch between what the sensor exposes and what §3 specifies. |
| 3 | [ADR-002 §5] Button calls the exact coordinator entry point, no duplicate path | PASS | `ShadyRecalculateButton.async_press` (`button.py:60-64`) calls `self._coordinator.async_refit()` and nothing else — no local recompute, no second code path. `tests/test_button.py::TestRecalculateButtonPress::test_press_triggers_a_real_refit` proves this isn't just a name match: it asserts `coordinator._models` (empty before) is populated after a real `async_press()` call, i.e. the actual `_refit_sync` path ran. `test_press_swallows_a_refit_exception` monkeypatches `coordinator.async_refit` itself (not some internal helper) and confirms the button still calls through that exact attribute and swallows the exception — a genuine "no parallel path" proof, since replacing that one attribute is sufficient to change the button's entire behavior. |
| 4 | [ADR-004 §1, amended 2026-08-30] `select.py`, not `switch.py`; default "off" | PASS | `find custom_components -iname "*switch*"` → no results anywhere in the repo. `select.py`'s own docstring (`select.py:12-16`) explicitly documents the absence. `ShadyDiagnosticModeSelect` has no `_attr_current_option` default set in `__init__` — `current_option` is a property delegating live to `coordinator.active_diagnostic_mode()` (`select.py:66-68`), and `coordinator.py`'s own `_active_diagnostic_mode` field defaults to `"off"` (confirmed via `grep -n "DIAGNOSTIC_MODES" const.py`: `("off", "compare_regressions")`, `"off"` listed first per the amendment). `tests/test_select.py::TestCurrentOptionDelegatesToCoordinator::test_reflects_off_by_default` confirms this directly. |
| 5 | [ADR-004 §2] One scatter-series sensor per configured string, non-colliding unique-IDs | PASS | `coordinator.diagnostic_sensor_ids()` (`coordinator.py:996-1011`) returns one `(sensor_id, name)` pair per configured string plus one `"sum"` pair (§2b), `sensor_id` literally being `str(string_index)` per string (confirmed in AUDIT-0008's finding #2 on the same underlying method, `CompareRegressionsMode.sensor_ids()`) — collision-proof by construction, since string indices are themselves unique. `ShadyDiagnosticsSensor.__init__` (`sensor.py:336-346`) builds `_attr_unique_id = f"{DOMAIN}_diagnostics_{sensor_id}_{entry.entry_id}"`, a direct format of that already-unique id — no independent id-assignment logic in `sensor.py` that could itself introduce a collision. |
| 6 | [ADR-004 §2a] Manual-slot-selection surface, if entity-exposed, matches §2a | PASS — **correctly implemented outside this audit's Scope Source Files** | `grep -n "select_diagnostic_slot\|pin_diagnostic_slot\|pinned_reference" sensor.py button.py select.py` → zero matches. §2a's mechanism is a service (`shady.select_diagnostic_slot`), not an entity — its handler and `pin_diagnostic_slot` live in `coordinator.py`/`__init__.py` (already independently confirmed by AUDIT-0008's Criterion 3, which the same grep pattern corroborates here from the entity-layer side: none of this layer's three files implement or duplicate any part of the pin mechanism). Correctly out of scope, same shallow-cross-check pattern AUDIT-0006/0007/0008 used for adjacent-but-out-of-deep-scope behavior. |
| 7 | [ADR-004 §2b, amended 2026-09-03] Summed-diagnostics entity matches the *revised* behavior | PASS | §2b's final (2026-09-03) text: the sum entry is *"the same `ShadyDiagnosticsSensor` class... not a dedicated `ShadyDiagnosticsSumSensor` class"* with `series`/`accuracy` built inside `CompareRegressionsMode.compute()` itself from raw per-string pool data, not assembled client-side in `sensor.py`. Code matches exactly: `sensor.py` has exactly one diagnostics sensor class, `ShadyDiagnosticsSensor` (`sensor.py:305-369`, confirmed via `grep -c "class Shady.*Diagnostic" sensor.py` → 1), with no per-sum-vs-per-string branching inside it at all — `_result()` (`sensor.py:348-355`) does a flat linear scan of `result.sensors` by `sensor_id` regardless of whether that id is a string index or `"sum"`. The class's own docstring (`sensor.py:305-322`) explicitly narrates this history ("as of the fifth Amendment... free to produce several distinct aggregate entities... without `sensor.py` needing a new subclass per kind"), matching the ADR's revised text rather than a stale pre-2026-09-03 description. |
| 8 | [ADR-005 §1–§6] Six aggregate sensors exist with exactly the stated responsibilities, each backed by `aggregation.py`, no inline aggregate math | PASS | All six classes present (`ShadyPvSumSensor`, `ShadyFcSumSensor`, `ShadyFcDaySumSensor`, `ShadyFcRemainingTodaySensor`, `ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor`, `sensor.py:170-303`), device_class/unit/state_class combinations matching ADR-005's own per-section descriptions exactly (POWER/W/MEASUREMENT for §1/§2; ENERGY/Wh/TOTAL for §3/§4; ENERGY/Wh/TOTAL_INCREASING for §5/§6) — cross-checked line-by-line against `tests/test_sensor_aggregates.py::TestSensorDeviceAndStateClasses`, whose own docstring cites "ADR-005's own device/state-class table" and whose six tests match the ADR text precisely. None of the six classes performs its own summation/integration — each is a one-line delegation to a `coordinator.py` method (`pv_sum`/`fc_sum`/`fc_day_energy_total`/`fc_remaining_energy`) which in turn calls `aggregation.py` (confirmed in ADR-005's own Module section, not re-verified here since `aggregation.py` itself is AUDIT-0007's territory). |
| 9 | [ADR-006 §4, cross-ref] Forecast sensor exposes all four documented intraday attributes, plus `values_raw` — not a subset | PASS | `ShadyForecastSensor.extra_state_attributes` (`sensor.py:154-167`) always includes `values_raw` (built locally from `raw_forecast_sensor_id`) and merges in `coordinator.intraday_attributes(string_index)`'s four keys (`intraday_ratio`, `intraday_state`, `intraday_ramp_weight`, `intraday_blend_active` — `coordinator.py:1742-1765`) unconditionally via `dict.update`, so all five ADR-006 §4 keys are always present together, never a subset — even when the mode is `"off"` (`intraday_state` still mirrors the configured mode per that method's own docstring, `coordinator.py:1747-1748`, and the other three degrade to `None`/`False` rather than disappearing). `tests/test_sensor_forecast.py::TestForecastSensorValue::test_today_and_tomorrow_attributes_are_288_slot_arrays_from_cache` asserts the exact attribute-key set (`{"today", "tomorrow", "values_raw", "intraday_ratio", "intraday_state", "intraday_ramp_weight", "intraday_blend_active"}`) as one assertion, not four separate ones — directly matching this criterion's own "confirm all four are present, not a subset" wording. |
| 10 | [ADR-013 §1, cross-ref, Proposed] No entity exposes the not-yet-scheduled whole-day comparison modes | PASS | `grep -rn -i "wholeday\|whole_day\|compare_providers_daily\|compare_regressions_daily"` across `sensor.py`/`button.py`/`select.py` → zero matches. `select.py`'s options list is a direct, unmodified copy of `const.py`'s `DIAGNOSTIC_MODES = ("off", "compare_regressions")` — no third option exists anywhere in this layer. Matches ADR-013's own `Status: Proposed`. |
| 11 | Rename residue: no leftover `switch`-named identifier/string/docstring reference | PASS | `grep -rn -i "switch"` across all three source files and all five Scope Test Files finds exactly two hits, both non-residue: `select.py`'s own docstring explicitly explaining the absence of `switch.py` (`select.py:12-13`, matches AUDIT-0008's identical finding #1 for `diagnostics/`), and `tests/test_select.py::test_forwards_a_switch_back_to_off` — an ordinary English verb ("switch back to off"), not a reference to the deleted entity type. Zero identifiers, string literals, or unique-id patterns reference the old `switch` domain. |

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | A test would fail if `sensor.py`/`button.py`/`select.py` started computing a value itself instead of reading it from upstream | COVERED, with one caveat | `test_button.py`'s `test_press_triggers_a_real_refit`/`test_press_swallows_a_refit_exception` and `test_select.py`'s `TestCurrentOptionDelegatesToCoordinator`/`TestAsyncSelectOptionDelegatesToCoordinator` use genuine delegate/spy patterns (real state mutation on a stub, or monkeypatched method) that would catch this class of regression cleanly. `test_sensor_diagnostics.py`'s `_CountingDiagnosticMode` spy is the strongest instance — proves zero extra `compute()` calls across ten reads. `test_sensor_forecast.py::test_native_value_matches_cache_directly` is comparatively weaker: it computes its own "expected" value via the *same* `coordinator.cache.get_time_range` call the sensor itself makes, rather than mocking the upstream source and asserting the sensor returns exactly that mocked value (the Task's own suggested pattern) — a genuine independent-computation regression would very likely still produce a numerically different value against this fixture's synthetic data (so the test would probably still fail), but it is not the same category of proof as a true call-count/mock-substitution test, and is worth noting as the one instance in this file that falls short of the others' rigor. |
| 2 | A test for each of the six ADR-005 aggregate sensors asserting `unique_id`/`device_class`/`unit_of_measurement` per ADR conventions | COVERED | `test_sensor_aggregates.py::TestSensorDeviceAndStateClasses` (6 tests, one per sensor) and `TestUniqueIds::test_unique_ids_are_distinct_and_entry_scoped` (asserts all 6 unique, entry-scoped, `DOMAIN`-prefixed) together cover every sensor × every metadata field named in this criterion. |
| 3 | A test proving all four intraday attributes are present on the forecast sensor simultaneously | COVERED | See Audit Criterion 9 above — `test_today_and_tomorrow_attributes_are_288_slot_arrays_from_cache` asserts the full attribute-key set as one `set(...) ==` comparison, not four isolated single-key assertions, directly satisfying "simultaneously, not just... individually... across different tests." |
| 4 | A test asserting entity uniqueness across ≥2 configured strings for the per-string scatter sensor | **GAP** | Searched all five Scope Test Files for `unique_id` assertions involving a ≥2-string fixture: `test_sensor_forecast.py::test_unique_id_is_the_exact_cache_sensor_id` and `test_sensor_aggregates.py::TestUniqueIds` both use single-string or entry-level (not per-string) fixtures; `test_sensor_diagnostics.py`'s `_CountingDiagnosticMode.sensor_ids()` does return two ids (`"0"`, `"1"`) and constructs two `ShadyDiagnosticsSensor` instances from them, but no test in that file asserts `sensor_0._attr_unique_id != sensor_1._attr_unique_id` — the two-string setup is used only to test the "declared but missing from compute output" path (Audit Criterion 5 context), not id-collision-freedom. The underlying guarantee (`sensor_id = str(string_index)`, hence collision-proof) is real and independently tested at the `sensor_ids()`-producer level in `tests/test_diagnostics_compare_regressions.py` (AUDIT-0008's own territory, per that audit's finding #2's `test_one_id_per_string_plus_sum`) — so this is a low-risk gap in practice, not an unverified claim — but nothing in *this* layer's own test files exercises entity-level `unique_id` distinctness with a real multi-string fixture, which is what this criterion specifically asks for. |
| 5 | `tests/test_select.py` covers the full option set, not just default/off | COVERED, for the current option set | `TestOptionsListMatchesConstDiagnosticModes::test_options_match_diagnostic_modes` asserts `entity._attr_options == ["off", "compare_regressions"]` (both currently-defined modes). `TestAsyncSelectOptionDelegatesToCoordinator` separately exercises selecting `"compare_regressions"` (`test_forwards_the_chosen_option`) and switching back to `"off"` (`test_forwards_a_switch_back_to_off`) — both of today's two modes are exercised, not only the default. Since `const.py` currently defines only these two modes (ADR-013's further modes are `Proposed`, not implemented), "full option set" is fully covered as of today's codebase; this will need a new case whenever a second non-off mode is actually added. |

## Live re-execution

```
$ python3 -m pytest tests/test_sensor_forecast.py tests/test_sensor_aggregates.py \
    tests/test_sensor_diagnostics.py tests/test_button.py tests/test_select.py -q
40 passed, 1 warning in 0.49s
```

No `homeassistant` package install was required — all five files register
their own hand-written stub modules in `sys.modules` before file-path-loading
the module under test, confirmed by inspection and by this successful run
in a sandbox that does not have the real package installed.

## Candidate Follow-Ups (not created — proposed only)

1. **ADR-000 §3 module-boundary question (Audit Criterion 1's PARTIAL):**
   three of `sensor.py`'s nine entity classes (`ShadyForecastSensor`,
   `ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor`) call
   `self._coordinator.cache.<method>(...)` directly rather than through a
   dedicated `coordinator.py` wrapper method, unlike the other six/seven
   classes in the same file. This was an explicit, task-time-reviewed
   decision (TASK-0011's Consumed Interfaces block names `self.cache:
   Cache — exposed directly` as an authorized dependency), not an
   unreviewed oversight — but it is not reflected in ADR-000 §3's module
   diagram (`entity_glue --> coordinator` only) or its "coordinator.py
   [is] the only module that imports cache.py" text, and is internally
   inconsistent with `sensor.py`'s own predominant convention. Candidate
   follow-ups for the human to choose between: (a) amend ADR-000 §3's
   diagram/text to note this narrow, reviewed exception, or (b) a small
   Scenario-C-style patch task adding two thin `coordinator.py` wrapper
   methods (e.g. `forecast_series(sensor_id, start, end)`,
   `energy_total(kind)`) so all nine sensor classes follow one uniform
   access pattern. Not fixed inline per this audit's own read-only
   mandate.
2. **Test-Coverage Criterion 4's GAP:** add one test to
   `test_sensor_diagnostics.py` (which already has a two-string
   `_CountingDiagnosticMode` fixture on hand) asserting
   `sensor_0._attr_unique_id != sensor_1._attr_unique_id` — a small,
   low-risk addition given the existing fixture, not a new harness.
3. **Test-Coverage Criterion 1's caveat:** consider strengthening
   `test_native_value_matches_cache_directly` to mock/substitute
   `coordinator.cache.get_time_range` with a spy and assert the sensor's
   returned value equals exactly the spy's return, rather than
   recomputing the same call independently — would make this test's
   proof-strength match the rest of the suite's (spy-based) convention.
   Minor; not a real regression risk found, just a coverage-quality note.

## Delivered Artifacts (for the task file)
- `tasks/AUDIT-0009-entity-layer-findings.md` (this file)
