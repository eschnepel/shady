# Findings: AUDIT-0005 — Coordinator

**Auditor:** Lead Agent (inline, single-pass)
**Date:** 2026-09-06
**Verdict:** Mostly PASS, well-tested. **Two real ADR-text-vs-code
discrepancies found** (both documentation staleness, not behavioral
bugs) — ADR-002 §5's "two registrations" Con is now false (code merges
push+recompute into one listener, and a test explicitly pins that), and
ADR-014 §4's blanket "all four methods delegate everything else to
`string_computation.py`" overclaims for `_predict_day_basis`/
`_clamp_basis`, which TASK-0017's own Acceptance Criteria explicitly
and correctly exempted for a real architectural reason (intraday
correction must sit between transform and clamp) that the ADR text
itself never states. One coverage GAP (absence-of-a-second-enumeration-
path is not runtime-tested). No behavioral FAILs.

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
|---|---|---|---|
| 1 | Recalibration triggers at midnight **and** button, one shared code path (§1) | PASS | `_register_schedule`/`_handle_midnight` (`coordinator.py:687-694`) calls `hass.async_create_task(self.async_refit(now))`; `button.py`'s `ShadyRecalculateButton.async_press` (confirmed via `tasks/TASK-0011-*.md` Delivered Artifacts) calls the same `async_refit`. `TestRefitSharedCodePath.test_button_and_midnight_produce_the_same_fit` (`test_coordinator.py:419-435`) asserts byte-identical fitted coefficients from both trigger paths, not just "both call something." |
| 2 | Startup-ordering guard: coordinator's own contribution (§1a) | PASS (for coordinator.py's scope) | `missing_required_entities()` (`coordinator.py:653-665`) checks exactly the documented required set — per-string `actual_yield_entity_id` and resolved `baseline_entity_id` (override-or-global) — and explicitly excludes optional correction-tier entities, matching §1a's "which entities are required" text verbatim. The actual guard/wait mechanism (`ConfigEntryNotReady`/`async_at_started`/`async_schedule_reload`) is, per §1a's own text, `__init__.py`'s job, not `coordinator.py`'s — correctly out of this file's scope (AUDIT-0011). |
| 3 | Recompute fires on model update **and** every baseline update; recalibration completion also triggers recompute (patch-1) | PASS | `_refit_sync` (`coordinator.py:713-737`) calls `self._recompute_string(string, now)` immediately after a successful fit, for both the shading and temperature models — exactly `TASK-0010-patch-1`'s Delivered Artifacts ("`_refit_sync` now calls `self._recompute_string(string, now)` immediately after a string's model is (re)fit"). `_make_listener`'s `_handle` (`coordinator.py:1779-1792`) separately triggers `_async_recompute` on every baseline-entity state-change event. Two genuinely distinct trigger paths converging on `_recompute_string`. |
| 4 | Forecast horizon: today (remaining) + tomorrow, no past-slot recompute (§3) | PASS | `_tomorrow_end` (`coordinator.py:203-207`) computes the exclusive end as `today_start + 2 days`; `_recompute_string`'s `series = [(ts, value) for ts, value in raw_series if now <= ts < horizon_end]` (`:1319`) excludes past timestamps at the provider-series level, and `_predict_day_basis`'s `if index < now_index: continue` (`:1397-1398`) excludes them a second time at the per-slot level. `TestRecomputeHorizon.test_only_remainder_of_today_and_tomorrow_pushed` (`test_coordinator.py:587-599`) asserts both the lower bound (`index >= now_index + 1`) and upper bound (`index < Cache.index_for(horizon_end)`) directly. |
| 5 | Raw baseline `FC` push is ADR-012 §4's generic instance, not reinvented (§4 cross-ref) | PASS | `_register_provider_listeners`/`_push_provider_series` (`coordinator.py:1769-1806`) is the one generic loop: skips a provider whose `forward` is un-overridden (`type(provider).forward is Provider.forward`), otherwise registers one listener whose body calls `provider.forward(now)`, converts to `Cache`'s index scheme, and `push(sensor_id, values, not_before_index)` — identical for baseline and (§7 below) temperature-predictor providers, no baseline-specific branch anywhere in this function. |
| 6 | Module-responsibility split matches ADR-014 §4's newer description, not stale ADR-002 §5 (§5 cross-ref) | **PARTIAL — see "ADR staleness" section below** | `_fit_string`/`_fit_temperature_string` (`:739-843`) genuinely delegate to `string_computation.apply_training_corrections`/`fit_string_model` — matches ADR-014 §4. `_predict_day_basis`/`_clamp_basis` (`:1352-1403`, `:1472-1485`) still call `forecast_adjust.reverse_transformed_forecast`/`clamp_output` **directly**, never through `string_computation.predict_string_forecast` — this is deliberate and justified (TASK-0017's own Acceptance Criteria explains why: intraday correction must sit between transform and clamp, and `predict_string_forecast`'s combined shape can't accommodate that), but it means ADR-014 §4's literal text ("all four... delegate everything else to `string_computation.py`") is not what was built for two of the four. See below for the separate, additional ADR-002 §5 finding. |
| 7 | `strings()` returns documented `list[tuple[int, str]]`, sole public enumeration surface (ADR-000 §5) | PASS | `coordinator.py:865-872` returns exactly `[(string.index, string.name) for string in self._strings]`, type-annotated `list[tuple[int, str]]`. `grep -rn "\.strings()"` across `custom_components/shady/` shows every consumer (`sensor.py`, `diagnostics/compare_regressions.py`, two internal call sites) goes through this one method — no second enumeration path found anywhere in the codebase. |
| 8 | `recency_decay_max` genuinely threaded through to `regression/base.py` (ADR-001 §4a cross-ref) | PASS | `self._recency_decay_max: float = data[CONF_RECENCY_DECAY_MAX]` (`:361`) is read into the coordinator, then passed as a positional argument to `string_computation.fit_string_model` at **both** call sites — the shading fit (`:781`) and the temperature fit (`:840`) — which TASK-0014's own documented decision (quoted in `_fit_temperature_string`'s docstring, `:809-818`) confirms is intentional: both fits share the one global value rather than each having its own. |
| 9 | ADR-003c §1: weather tier bypasses the learned model entirely | PASS | `_predict_target_slot_temperature`'s `if resolution.tier == "weather":` branch (`:1436-1448`) reads `provider.fetch()` directly and never touches `self._temperature_models`/`temperature_model.predict_unclamped(...)` — that call only appears in the `else` branch (`:1450-1460`), reached only for `cell`/`ambient`. `_fit_temperature_string` itself also returns `None` immediately for `resolution.tier == "weather"` (`:820-822`), so no model is ever fitted for that tier in the first place. |
| 10 | ADR-003c §2: one model per 5-minute slot, same grid as ADR-001, reusing `regression/` mechanics only | PASS | `_fit_temperature_string` (`:785-843`) calls the exact same `string_computation.fit_string_model` the shading fit uses, over the same `SLOTS_PER_DAY`-shaped pools from `cache.get_regression_pools`, with no separate grid or slot-count constant introduced. `apply_magnitude_weight=False` (`:842`) and `smoothing_radius=0` (`:838`) are the two documented, deliberate opt-outs (§2's "not reused" bullets) — confirmed present, not silently defaulting to the shading model's `True`/`self._smoothing_radius`. |
| 11 | ADR-003c §3: predictor sourced from a dedicated, explicit global config field | PASS | `self._weather_forecast_temperature_entity_id: str | None = data.get(CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY)` (`:391-393`) is read once, independently of the baseline provider's own entity — `_fit_temperature_string` asserts it directly (`:823,825`) rather than deriving it from `_resolve_temperature_entity`'s baseline-adjacent logic. |
| 12 | ADR-003c §4: per-tier prediction dispatch matches spec (weather unchanged, cell no-uplift, ambient uplifted) | PASS | `_predict_target_slot_temperature` (`:1405-1470`): `weather` branch applies `uplift_ambient_to_cell` to a native forecast (pre-existing, unchanged path per the docstring); `cell` branch (`:1462-1463`) returns `predicted_temp` directly, no uplift call; `ambient` branch (falls through to `:1465-1470`) applies the identical `uplift_ambient_to_cell` call the weather/live-ambient path would use, gated on `rated_dc_capacity_wp`. |
| 13 | ADR-003c §5: no-predictor case skips forward **and** reverse together, one code path | PASS | `_resolve_temperature_entity` (out of this audit's line range but confirmed via `TestResolveTemperatureEntity` in `test_coordinator_temperature_forecast.py`) is the single gate both `_fit_string`'s training-time correction (`resolution` used to decide whether to pass `temperature_by_offset`, `:757-761`) and `_predict_day_basis`'s prediction-time correction (`:1379-1382`) go through — one `None`-or-not decision point, not two independently-coded checks. Proven end-to-end, not just by inspection — see Test-Coverage Criterion 3 below. |
| 14 | ADR-003c §6: no new cache/storage concept for the learned model | PASS | `_fit_temperature_string` reads through `self.cache.get_regression_pools(...)` (`:827`) — the exact same accessor `_fit_string` already uses for the shading model, just with a different `sensor_ids` list. No new `Cache` method, no new persisted structure. |
| 15 | ADR-003c §7: predictor push is automatic via the generic loop, no per-predictor registration code | PASS | The predictor is registered as an ordinary `TemperatureProvider` in `__init__` (`:419-432`, tier `"weather"`) purely so `_register_provider_listeners`'s generic `forward`-override check (criterion 5 above) picks it up — no predictor-specific branch anywhere in the push-loop code itself. `TestPredictorProviderRegisteredGenerically.test_predictor_gets_a_state_change_listener_with_no_new_listener_code` (`test_coordinator_temperature_forecast.py:234`) names this property directly. |
| 16 | ADR-006 §1a/§1b: ramp/window math lives in `aggregation.py`, coordinator only orchestrates (§1a/§1b cross-ref) | PASS | `coordinator.py`'s intraday functions (`_apply_intraday_reset`, `_compute_intraday_output`, `_advance_intraday_string`, `:1489-1649`) call `crossfade`, `ramp_weight`, `intraday_correction_factor` — all imported from `.aggregation` (`:118-126`) — for every formula in ADR-006 §1a/§1b (ramp weight, effective factor, crossfade blend). No inline reimplementation of any of these formulas found in `coordinator.py`. |
| 17 | ADR-006 §4: intraday correction applied per string, per future slot, past slots untouched | PASS | `_recompute_string`'s per-string loop (`_intraday_tick_sync`, `:1677-1680`, and `_recompute_string` itself operating on one `string` at a time) combined with `_predict_day_basis`'s already-established `index < now_index: continue` guard (criterion 4) means intraday correction is layered on top of a basis that already excludes past slots — `_apply_intraday_reset`/`_compute_intraday_output` never receive past-slot indices to begin with. |

### ADR staleness: two findings, not one

The task explicitly asked whether ADR-002 §5 needs an amendment to
reflect ADR-014 §4. Investigating that surfaced **two** separate,
independently-evidenced staleness issues, not one:

**A. ADR-002 §5 (and its own Consequences section) describes two
listener registrations; the code has one.** ADR-002 §5 states
recompute listeners run "independently of" the push loop, and ADR-002's
Consequences section is explicit: *"§4's push... is a second,
independent listener on the same baseline entity §2 already listens to
for recompute — **two registrations on one entity rather than one
callback doing both**."* The actual code (`_register_provider_
listeners`, `coordinator.py:1769-1777`) registers **exactly one**
`async_track_state_change_event` per entity, whose single handler
(`_make_listener`'s `_handle`, `:1784-1791`) does both the push
(`_push_provider_series`) and, conditionally, the recompute dispatch —
literally "one callback doing both," the opposite of what the Con
describes. This is not a guess: `TestGenericProviderPushLoop.
test_one_listener_per_forward_overriding_provider`
(`test_coordinator.py:624-638`) explicitly asserts
`len(hass.states._listeners[_BASELINE_ENTITY]) == 1`, so this is
deliberately built and tested this way, not an accidental merge. ADR-002
§5's body text and its Con both describe an implementation that was
apparently simplified after this text was written, and neither was
updated to match.

**B. ADR-014 §4's "all four... delegate everything else to
`string_computation.py`" overclaims for two of the four methods, and
the ADR itself never records the reason.** `_fit_string`/`_fit_
temperature_string` do delegate as described. `_predict_day_basis`/
`_clamp_basis` do not — they call `forecast_adjust.py`'s functions
directly, with no `string_computation.py` involvement at all for these
two call sites (`predict_string_forecast` exists and is genuinely used,
but only by `diagnostics/compare_regressions.py:396`, never by
`coordinator.py`). Critically, this is not an unnoticed regression: TASK-
0017's own Acceptance Criteria section states outright that "`_predict_
day_basis`/`_clamp_basis` are **not** required to change call shape...
exactly one caller needs their particular split-then-multi-day-clamp
shape, since intraday correction, ADR-006 §1b, must sit between the two
steps" — a real, sound architectural reason (`predict_string_forecast`'s
combined transform+clamp shape is structurally incompatible with
inserting ADR-006 §1b's correction step in between). The task file
correctly documents and justifies the exception; **ADR-014 §4 itself
does not** — its Decision text still reads as an unconditional claim
about all four methods.

**Recommendation for the human:** both are ADR-text amendments, not
code changes — the code's actual behavior in both cases is
deliberate, tested, and (for B) already justified in a task file the
ADR text just doesn't reflect. Candidate amendments:
- ADR-002 §5 / Consequences: replace "two registrations... rather than
  one callback doing both" with a description of the actual single
  merged listener.
- ADR-014 §4: add the `_predict_day_basis`/`_clamp_basis` exception
  and its intraday-ordering rationale, matching what TASK-0017's
  Acceptance Criteria already says.

Neither finding is a FAIL against a criterion this audit was scoped to
check for behavioral correctness — both describe correct, tested
behavior; the ADR prose is what has drifted.

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | A test would fail if `_refit_sync` stopped calling recompute after recalibration | COVERED | `TestRefitTriggersRecompute.test_refit_pushes_a_forecast_without_any_baseline_update` (`test_coordinator.py:507-515`) asserts pushed values exist after `async_refit` alone, with **no** baseline update fired — this would fail immediately if the `_recompute_string` call were removed from `_refit_sync`. |
| 2 | A test simulates entities-not-yet-existing for the startup-ordering guard, not only the already-initialized case | COVERED, for coordinator.py's own scope; the guard/wait mechanism itself is untested *here* by design | `TestMissingRequiredEntities.test_reports_missing_actual_yield_and_baseline` (`:480-485`) constructs a `FakeHomeAssistant` with neither required entity set, proving `missing_required_entities()` correctly reports both when genuinely absent — not just the trivially-true "both present" case. The `ConfigEntryNotReady`/`async_at_started` retry mechanism itself is `__init__.py`'s responsibility (per §1a's own text) and is out of this audit's Scope — that coverage belongs to `tests/test_init.py`, AUDIT-0011. |
| 3 | End-to-end test proves the unconfigured-predictor case is byte-identical to no-temperature-source-at-all for both directions together | COVERED, still valid | `TestNoPredictorSkipsBothSidesEndToEnd.test_matches_a_control_run_with_no_temperature_source_at_all` (`test_coordinator_temperature_forecast.py:676-684`) runs a full `async_refit` end-to-end for both configurations and asserts dict equality of the pushed forecast values, plus a non-vacuousness check (`len(...) > 0`) ruling out both sides accidentally being empty. |
| 4 | A test proves `strings()` is not shadowed/duplicated by a second enumeration path | **GAP** | `TestStringEnumeration` (`test_coordinator.py:669-`) only exercises `strings()`'s own return value/ordering — it does not, and structurally cannot easily, prove the *absence* of a second enumeration path added elsewhere (e.g. a future `sensor.py` change that iterates `coordinator._strings` directly instead of calling `strings()`). A regression of this specific kind (a second, divergent enumeration surface appearing) would not be caught by any existing test. Confirmed by static inspection instead (Audit Criterion 7) that no such second path exists today. |
| 5 | A differential test proves `apply_magnitude_weight` is genuinely wired through, not merely accepted | COVERED, still valid, still a genuine differential design | `TestFitTemperatureString.test_apply_magnitude_weight_false_is_actually_wired` (`test_coordinator_temperature_forecast.py:317-359`) constructs an all-negative predictor training set specifically engineered so that the wrong (`True`) mode would zero every sample's weight and fall back to cold-start passthrough (predicting the query value unmodified); the test asserts the model instead predicts close to the true linear relationship — a real differential proof, not an output-shape check. |
| 6 | Any test whose name/docstring still asserts the pre-TASK-0017 module-responsibility split | None found | `grep -n "responsib\|owns\|delegat\|string_computation"` across all three coordinator test files found no test describing a stale pre-split responsibility boundary; the one reference to `string_computation` (`test_coordinator_temperature_forecast.py:29`) correctly cites `TASK-0017`/ADR-014 by name and describes current behavior. |

## Candidate Follow-Ups (not created — proposed only)

1. **ADR amendment, not code:** update ADR-002 §5 and its Consequences
   section to describe the actual single merged provider listener
   (push + conditional recompute in one callback), replacing the "two
   registrations" Con — see "ADR staleness" finding A above. Flagged
   for human decision, not resolved here per this audit's own charter.
2. **ADR amendment, not code:** extend ADR-014 §4 to explicitly carve
   out `_predict_day_basis`/`_clamp_basis` and state the intraday-
   ordering reason `TASK-0017`'s own Acceptance Criteria already gives
   — see finding B above. Flagged for human decision.
3. **Low priority, optional:** the top-of-file module docstring's
   Intraday paragraph (`coordinator.py:75-78`) still says
   `_register_intraday_schedule`'s poll is "only registered when
   `intraday_correction_mode` is not `off`" — this was true pre-ADR-004
   but the constructor's own inline comment (`:525-537`) correctly
   describes the current always-registered-but-no-op-when-off behavior.
   A same-file internal inconsistency, not an ADR conformance issue;
   worth a one-line docstring fix whenever this file is next touched,
   no urgency.
4. **Low priority, optional:** consider a lightweight guard (a code-
   review convention, or a test asserting `sensor.py`/`diagnostics/*`
   never reference `_strings`/`_StringConfig` directly) to close
   Test-Coverage Gap #4 — a static check would suffice; a runtime test
   is not the natural tool for an absence-of-a-path property.

## Delivered Artifacts (for the task file)
- `tasks/AUDIT-0005-coordinator-findings.md` (this file)
