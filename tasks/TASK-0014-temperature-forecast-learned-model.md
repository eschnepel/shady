# Task: Temperature-Forecast Learned Model

- **Status:** done
- **Related ADRs:** [ADR-003c §1, ADR-003c §2, ADR-003c §3, ADR-003c §4, ADR-003c §5, ADR-003c §6, ADR-003c §7]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0006-cache-batched-regression-pool-accessor, TASK-0004-temperature-source-provider, TASK-0007-yield-corrections, TASK-0010-coordinator-recalibration-recompute-push, TASK-0005-patch-4-recency-weight, TASK-0005-patch-5-optional-magnitude-weight]

## Goal
Implement the cell/ambient-tier per-slot temperature forecasting model:
one learned model per 5-minute slot (same 288-slot grid, same rolling
window), reusing `regression/`'s fitting mechanics only (no
`magnitude_weight_i`, no ADR-011 smoothing/exclusion), trained against a
second instance of `providers/temperature.py` (TASK-0004's class,
reused as-is, pointed at the dedicated weather-forecast-entity config
field) as predictor and the tier's own sensor as target. Feeds
`yield_correction.py`'s reverse transform (TASK-0007) with a real
target-slot temperature forecast. Requires no new coordinator listener
code — TASK-0010's generic `forward()`-push loop already picks this
predictor up automatically once it overrides `forward()`.

**Readiness-time note (added after `TASK-0005-patch-4`, ADR-001 §4a):**
`regression.base.build_pool` — this task's shared fitting mechanics —
now also requires a `recency_decay_max` argument (ADR-001 §4a's
day-recency weighting). Whether this second, temperature-predicting fit
should reuse the same `self._recency_decay_max` the yield fit uses, or
its own value (e.g. `0.0`, since a learned *temperature* model has no a
priori reason to expect the same seasonal-regime-shift behavior a
shading pattern does), is this task's own decision to make at
implementation time — this note only flags that the call site now needs
*some* value, not which one. Whichever is chosen, state it explicitly
in this task's own Delivered Artifacts.

## Acceptance Criteria
- Given historical predictor/target pairs for a slot, When the model
  fits using the shared `regression/` strategies (TASK-0005), Then
  `magnitude_weight_i` downweighting is **not** applied (ADR-003c §2 —
  temperature has no near-zero degeneracy).
- Given the weather-forecast-entity config field is set, When
  `forward()` is called on the second `providers/temperature.py`
  instance, Then it returns a non-`None` series without any new
  provider-specific coordinator code (TASK-0010's generic loop handles
  it).
- Given the cell tier, When `predicted_temp` is produced, Then it is used
  directly as `target_cell_temperature` with no ambient→cell uplift
  applied on top (category-error guard, ADR-003c §4).
- Given the ambient tier, When `predicted_temp` is produced, Then it
  passes through the existing ambient→cell uplift formula (TASK-0007)
  unchanged, exactly as a live reading would have.
- Given no weather-forecast entity is configured (or a string on the
  cell/ambient tier has none available), When derating is evaluated,
  Then both the forward and reverse transforms are skipped entirely for
  that string — not degraded to a naive fallback (ADR-003c §5).
- Given the predictor and target series, When read, Then both go through
  `cache.py`'s existing `get_time_range`/`get_regression_pools`
  accessors with no `cache.py` changes required (ADR-003c §6).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/coordinator.py` (extended — instantiates the
  second `providers/temperature.py` instance and the per-slot temperature
  fit, calling into `regression/` a second time)
- `tests/test_coordinator_temperature_forecast.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0005, TASK-0006, TASK-0004, TASK-0007,
     TASK-0010. -->
- `regression.base.build_pool(fc_by_offset, pv_by_offset, smoothing_radius, neighbor_fitting_cutoff, recency_decay_max, *, apply_magnitude_weight=True) -> SamplePool` and `regression.base.FittedModel.predict_unclamped(fc) -> (NDArray, NDArray)` from `custom_components/shady/regression/base.py` (→ task: TASK-0005-regression-fitting-pipeline; `apply_magnitude_weight` → task: TASK-0005-patch-5-optional-magnitude-weight); `_REGRESSION_STRATEGIES: dict[str, RegressionStrategy]` mapping in `coordinator.py` itself (unchanged, pre-existing)
- `cache.Cache.get_regression_pools(sensor_ids, smoothing_radius, reference=None) -> dict[str, NDArray]` and `cache.Cache.push(sensor_id, values, not_before_index)` from `custom_components/shady/cache.py` (→ task: TASK-0006-cache-batched-regression-pool-accessor)
- `providers.temperature.TemperatureProvider(hass, entity_id, tier)` (tier: `Literal["sensor", "weather"]`) and its `fetch(start, end) -> list[float | None]` / `forward(now) -> list[tuple[int, float]] | None` from `custom_components/shady/providers/temperature.py` (→ task: TASK-0004-temperature-source-provider)
- `yield_correction.uplift_ambient_to_cell(ambient, baseline_forecast, baseline_rated_capacity, max_uplift_c)` and `yield_correction.derate_actual_to_reference(actual, cell_temperature, coefficient_per_c, *, provider_already_corrects=False)` from `custom_components/shady/yield_correction.py` (→ task: TASK-0007-yield-corrections); `forecast_adjust.reverse_transformed_forecast(model, fc, target_cell_temperature, coefficient_per_c, *, provider_already_corrects=False)` (unchanged call site, same task)
- `coordinator.ShadyCoordinator`'s generic `forward()`-push loop (`_register_provider_listeners`, ADR-012 §4) and its existing `self._entity_providers: dict[str, Provider]` registry from `custom_components/shady/coordinator.py` (→ task: TASK-0010-coordinator-recalibration-recompute-push) — this task registers into that same registry, adding no new listener-registration code
- `const.CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY = "weather_forecast_temperature_entity"` and `const.CONF_TEMPERATURE_REGRESSION_METHOD = "temperature_regression_method"` from `custom_components/shady/const.py` — already part of `config_flow.py`'s original settings-step schema (Optional/Required respectively, present in every `ConfigEntry.data` since the original delivery, confirmed present in all four `_make_entry` test fixtures already)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/coordinator.py` →
  - `_TemperatureResolution` — new frozen dataclass, `(entity_id: str, tier: Literal["weather", "cell", "ambient"])`.
  - `ShadyCoordinator._resolve_temperature_entity(self, string: _StringConfig) -> _TemperatureResolution | None` — replaces (renames, extends) the previous, weather-only `_resolve_weather_temperature_entity`; every prior call site updated. Implements ADR-003b §1/§1a's full three-tier resolution and ADR-003c §5's "no predictor configured → skip both sides" rule.
  - `ShadyCoordinator._ensure_temperature_provider(self, entity_id: str, tier: TemperatureTier) -> None` — signature extended with an explicit `tier` (previously hardcoded `"weather"`); every prior call site updated. `TemperatureTier` imported from `.providers.temperature`.
  - `ShadyCoordinator._fit_temperature_string(self, string: _StringConfig, now: datetime) -> FittedModel | None` — new. Fits the ADR-003c §2 per-slot model for a `cell`/`ambient`-tier string (`None` for `weather` tier or an unresolved source); predictor = the global `weather_forecast_temperature_entity`, target = the string's own already-resolved temperature entity; `smoothing_radius=0`, `apply_magnitude_weight=False` (`TASK-0005-patch-5`); `recency_decay_max` reuses `self._recency_decay_max` (documented decision, no new config field); regression method from `self._temperature_regression_method`.
  - `ShadyCoordinator._predict_target_slot_temperature(self, string, resolution, fc_array, day_start) -> NDArray[np.float64] | None` — new, extracted from `_predict_day_basis`. Dispatches by tier: `weather` unchanged (native forecast + uplift, gated on `rated_dc_capacity_wp`); `cell`/`ambient` feed the predictor's own forecast through the string's fitted temperature model (`predict_unclamped`, cold-start passthrough when no model/confidence yet); `cell` returns the model's output directly (no uplift, ungated on `rated_dc_capacity_wp`); `ambient` passes it through `uplift_ambient_to_cell` (gated on `rated_dc_capacity_wp`, same as `weather`).
  - `ShadyCoordinator._apply_training_corrections(self, string, fc_by_offset, pv_by_offset, temperature_by_offset, temperature_tier: Literal["weather", "cell", "ambient"] | None) -> dict[int, NDArray[np.float64]]` — signature extended with `temperature_tier` (previously 4 params, unconditionally uplift-based); every prior call site (`_fit_string`) updated. `cell` uses the reading directly, ungated on `rated_dc_capacity_wp`; `weather`/`ambient` uplift first, gated on it (unchanged for `weather`).
  - `ShadyCoordinator.__init__` → new instance attributes `self._weather_forecast_temperature_entity_id: str | None`, `self._temperature_regression_method: str`, `self._temperature_models: dict[int, FittedModel]` (keyed by `string.index`, same convention as `self._models`). The global predictor provider is registered once, unconditionally, alongside the existing global baseline-provider registration.
  - `ShadyCoordinator._refit_sync` → now also fits and stores each string's temperature model (inside the same `if model is not None:` block that already stores the shading model and triggers `_recompute_string`).
  - No `cache.py`, `providers/temperature.py`, `yield_correction.py`, or `forecast_adjust.py` changes — confirmed via `git diff --stat` against the pre-TASK-0014 commit, touching only `coordinator.py` (plus the separate `TASK-0005-patch-5` commit's `regression/base.py`).
- `tests/test_coordinator_temperature_forecast.py` → new file, 28 tests across 7 classes (`TestResolveTemperatureEntity`, `TestPredictorProviderRegisteredGenerically`, `TestFitTemperatureString`, `TestPredictTargetSlotTemperature`, `TestApplyTrainingCorrectionsTierDispatch`, `TestNoPredictorSkipsBothSidesEndToEnd`), covering: the three-tier resolution and its ADR-003c §5 gate; the predictor's automatic, no-new-code provider/listener registration, including a direct `forward()` call proving it returns a real, non-`None` series from a forecast attribute; `_fit_temperature_string`'s tier gating and a decisive differential proof that `apply_magnitude_weight=False` is actually wired (a broken `True`-mode fit would produce a detectably different, wrong prediction on an all-negative training row); `_predict_target_slot_temperature`'s per-tier dispatch (`weather` unchanged, `cell` no-uplift, `ambient` uplifted, both `rated_dc_capacity_wp`-gated correctly, defensive no-model fallback); `_apply_training_corrections`'s tier dispatch with hand-verified expected values via the real `uplift_ambient_to_cell`/`derate_actual_to_reference` functions; and one true end-to-end (`async_refit`-driven) test proving the unconfigured-predictor case is byte-identical to "no temperature source at all" for both the forward (training) and reverse (prediction) transforms together, not a degraded fallback.
- Full suite: 309/309 passing (278 pre-existing + `TASK-0005-patch-5`'s 3 + this task's 28). `mypy --strict` clean on `custom_components/` + `tests/` (40 files). `ruff check` clean; `ruff format --check` clean on every file this task touched (the one pre-existing, unrelated `tests/test_regression.py` nit logged 2026-08-29 in `tasks/INDEX.md` remains untouched and out of scope). `git diff --stat` against the pre-TASK-0014 commit confirms only `coordinator.py` changed in this task's own commit (no `cache.py`, `providers/temperature.py`, or `yield_correction.py` diff) — Acceptance Criterion 6 (ADR-003c §6).
- External dependencies added: none.