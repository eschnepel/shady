"""Tests for `coordinator.py`'s ADR-003c cell/ambient-tier temperature-
forecast learned model wiring (`TASK-0014`): the three-tier resolution
(`_resolve_temperature_entity`), the predictor's generic `forward()`-
push registration (ADR-012 §4, no new listener code), the per-tier
`target_cell_temperature` computation (`cell`: no uplift; `ambient`:
the existing uplift, unchanged; `weather`: unchanged since the original
delivery), ADR-003c §5's "no predictor, no correction — skip both sides
entirely" rule, and `build_pool`'s `apply_magnitude_weight=False` reuse
(`TASK-0005-patch-5`) at this module's own new call site.

Reuses `test_coordinator.py`'s exact hand-written `homeassistant` stub
and fixture conventions (`ShadyCoordinator`/`_make_entry`/`_run`/
`hass_pushed_values`) rather than re-declaring them — mirrors
`test_coordinator_intraday.py`'s own import style (importing the module
installs the stub exactly once).

Deliberately does **not** re-test `regression/`'s fitting math (already
`tests/test_regression.py`'s job, including `TestOptionalMagnitudeWeight`
for the `apply_magnitude_weight=False` formula itself), `Temperature
Provider`'s own `fetch()`/`forward()` mechanics (`tests/
test_providers_temperature.py`), or `uplift_ambient_to_cell`/
`derate_actual_to_reference`'s formulas (`tests/test_yield_correction.py`)
— only the coordinator-level wiring connecting them (ADR-000 §6's
testing philosophy: one place tests each concern).

Most tests below call `coordinator._resolve_temperature_entity`/
`_fit_temperature_string`/`_predict_target_slot_temperature`/`_apply_
training_corrections` directly rather than driving a full `async_refit`
— precedent already established by `test_coordinator.py`'s own direct
`coordinator._recompute_string(...)` calls — since this sidesteps
needing to know `BaselineProvider`'s own Wh->W conversion just to
hand-verify an unrelated formula's wiring; `TestNoPredictorSkipsBoth
SidesEndToEnd` is the one true end-to-end (`async_refit`-driven) test,
and deliberately only compares two runs against each other (not against
a hand-computed absolute number) for the same reason.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from tests import test_coordinator as tc

Cache = tc.Cache
_NOW = tc._NOW
_YESTERDAY = tc._YESTERDAY
_BASELINE_ENTITY = tc._BASELINE_ENTITY
_ACTUAL_YIELD_ENTITY = tc._ACTUAL_YIELD_ENTITY
_make_entry = tc._make_entry
_run = tc._run
FakeHomeAssistant = tc.FakeHomeAssistant
hass_pushed_values = tc.hass_pushed_values
_synthetic_wh_period = tc._synthetic_wh_period
_seed_actual_yield_statistics = tc._seed_actual_yield_statistics
ShadyCoordinator = tc.ShadyCoordinator

_coordinator_mod = sys.modules["shady.coordinator"]
_yield_correction_mod = sys.modules["shady.yield_correction"]
_providers_temperature_mod = sys.modules["shady.providers.temperature"]
_regression_base_mod = sys.modules["shady.regression.base"]
_cache_mod = sys.modules["shady.cache"]

_TemperatureResolution = _coordinator_mod._TemperatureResolution
uplift_ambient_to_cell = _yield_correction_mod.uplift_ambient_to_cell
derate_actual_to_reference = _yield_correction_mod.derate_actual_to_reference
TemperatureProvider = _providers_temperature_mod.TemperatureProvider
FittedModel = _regression_base_mod.FittedModel
SLOTS_PER_DAY = _cache_mod.SLOTS_PER_DAY

_PREDICTOR_ENTITY = "weather.forecast_home"
_CELL_SENSOR_ENTITY = "sensor.string_a_cell_temp"
_AMBIENT_SENSOR_ENTITY = "sensor.property_ambient_temp"
_DAY_START = datetime(2026, 6, 15, tzinfo=UTC)


def _string(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "Test String",
        "baseline_entity_id": None,
        "baseline_attribute": None,
        "baseline_shape": None,
        "temperature_aware": False,
        "actual_yield_entity_id": _ACTUAL_YIELD_ENTITY,
        "converter_limit_w": None,
        "temperature_source_entity_id": None,
        "temperature_coefficient_pct_per_c": -0.4,
        "rated_dc_capacity_wp": None,
    }
    base.update(overrides)
    return base


def _make_coordinator(entry: Any, hass: Any | None = None) -> tuple[Any, Any]:
    hass = hass if hass is not None else FakeHomeAssistant()
    coordinator = ShadyCoordinator(hass, entry)
    coordinator._now = lambda: _NOW
    return coordinator, hass


def _weather_forecast_state(
    temps_by_slot: dict[int, float], current: float = 10.0, day_start: datetime = _DAY_START
) -> dict[str, Any]:
    """A `weather.*` `forecast` attribute with one entry per `slot ->
    temperature`, timestamped on `day_start`'s 5-minute grid."""
    forecast = [
        {"datetime": (day_start + timedelta(minutes=5 * slot)).isoformat(), "temperature": temp}
        for slot, temp in temps_by_slot.items()
    ]
    return {"temperature": current, "forecast": forecast}


# -- _resolve_temperature_entity (ADR-003b §1/§1a) --------------------------


class TestResolveTemperatureEntity:
    """The full three-tier resolution — same override/global-default
    precedence as before `TASK-0014`, now additionally distinguishing
    `cell` (per-string override, `sensor.*`) from `ambient` (global
    default, `sensor.*`) and enforcing ADR-003c §5's "no predictor, no
    correction" rule for both."""

    def test_weather_domain_default_resolves_to_weather_tier(self) -> None:
        entry = _make_entry(
            default_temperature_source="weather.home",
            strings=[_string()],
        )
        coordinator, _hass = _make_coordinator(entry)
        resolution = coordinator._resolve_temperature_entity(coordinator._strings[0])
        assert resolution == _TemperatureResolution("weather.home", "weather")

    def test_weather_domain_per_string_override_also_resolves_to_weather_tier(self) -> None:
        entry = _make_entry(
            default_temperature_source=None,
            strings=[_string(temperature_source_entity_id="weather.balcony")],
        )
        coordinator, _hass = _make_coordinator(entry)
        resolution = coordinator._resolve_temperature_entity(coordinator._strings[0])
        assert resolution == _TemperatureResolution("weather.balcony", "weather")

    def test_per_string_sensor_override_resolves_to_cell_tier(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source="sensor.ambient_wrong_one",
            strings=[_string(temperature_source_entity_id=_CELL_SENSOR_ENTITY)],
        )
        coordinator, _hass = _make_coordinator(entry)
        resolution = coordinator._resolve_temperature_entity(coordinator._strings[0])
        # The per-string override wins precedence over the global
        # default, exactly as before TASK-0014 — and resolves `cell`,
        # not `ambient`, purely because of that scope.
        assert resolution == _TemperatureResolution(_CELL_SENSOR_ENTITY, "cell")

    def test_global_default_sensor_resolves_to_ambient_tier(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source=_AMBIENT_SENSOR_ENTITY,
            strings=[_string()],
        )
        coordinator, _hass = _make_coordinator(entry)
        resolution = coordinator._resolve_temperature_entity(coordinator._strings[0])
        assert resolution == _TemperatureResolution(_AMBIENT_SENSOR_ENTITY, "ambient")

    def test_sensor_tier_with_no_predictor_configured_resolves_to_none(self) -> None:
        # ADR-003c §5: an otherwise-valid cell/ambient resolution, but no
        # weather_forecast_temperature_entity to forecast it with -> both
        # forward and reverse must be skipped, exactly as if unset.
        entry = _make_entry(
            weather_forecast_temperature_entity=None,
            default_temperature_source=_AMBIENT_SENSOR_ENTITY,
            strings=[_string()],
        )
        coordinator, _hass = _make_coordinator(entry)
        assert coordinator._resolve_temperature_entity(coordinator._strings[0]) is None

    def test_per_string_sensor_override_with_no_predictor_also_resolves_to_none(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=None,
            strings=[_string(temperature_source_entity_id=_CELL_SENSOR_ENTITY)],
        )
        coordinator, _hass = _make_coordinator(entry)
        assert coordinator._resolve_temperature_entity(coordinator._strings[0]) is None

    def test_temperature_source_none_sentinel_resolves_to_none(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source=_AMBIENT_SENSOR_ENTITY,
            strings=[_string(temperature_source_entity_id="none")],
        )
        coordinator, _hass = _make_coordinator(entry)
        # The per-string sentinel explicitly disables derating for this
        # string, superseding the global default entirely (unchanged
        # semantics from before TASK-0014).
        assert coordinator._resolve_temperature_entity(coordinator._strings[0]) is None

    def test_unset_source_resolves_to_none(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source=None,
            strings=[_string()],
        )
        coordinator, _hass = _make_coordinator(entry)
        assert coordinator._resolve_temperature_entity(coordinator._strings[0]) is None


# -- predictor provider registration (ADR-003c §3/§7, ADR-012 §4) ----------


class TestPredictorProviderRegisteredGenerically:
    """The dedicated weather-forecast-temperature predictor is a normal
    `TemperatureProvider` (`tier="weather"`), registered once, globally,
    at construction — TASK-0010's existing generic `forward()`-push
    loop (ADR-012 §4) then picks it up automatically, with no new
    coordinator listener code (this task's own Consumed Interfaces
    note)."""

    def test_predictor_registered_as_a_weather_tier_temperature_provider(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY, strings=[_string()]
        )
        coordinator, _hass = _make_coordinator(entry)
        provider = coordinator._entity_providers.get(_PREDICTOR_ENTITY)
        assert isinstance(provider, TemperatureProvider)
        assert provider._tier == "weather"

    def test_predictor_gets_a_state_change_listener_with_no_new_listener_code(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY, strings=[_string()]
        )
        _coordinator, hass = _make_coordinator(entry)
        # `_register_provider_listeners` (ADR-012 §4) is fully generic —
        # this alone proves it picked the predictor up, since no
        # TASK-0014-specific registration code exists.
        assert _PREDICTOR_ENTITY in hass.states._listeners
        assert len(hass.states._listeners[_PREDICTOR_ENTITY]) == 1

    def test_predictor_forward_returns_a_non_none_series_from_its_forecast_attribute(self) -> None:
        # Acceptance criterion, stated directly: given the config field
        # is set and the entity has a forecast attribute, forward()
        # itself (unchanged from TASK-0004) returns a real series — the
        # mechanism this task leans on for "no new coordinator code"
        # actually produces data, not just registers without crashing.
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY, strings=[_string()]
        )
        coordinator, hass = _make_coordinator(entry)
        hass.states.set(_PREDICTOR_ENTITY, _weather_forecast_state({10: 12.5, 20: 13.0}))
        provider = coordinator._entity_providers[_PREDICTOR_ENTITY]
        assert isinstance(provider, TemperatureProvider)
        series = provider.forward(_DAY_START)
        assert series is not None
        assert len(series) == 2
        values = {timestamp: value for timestamp, value in series}
        assert values[_DAY_START + timedelta(minutes=50)] == 12.5
        assert values[_DAY_START + timedelta(minutes=100)] == 13.0

    def test_not_registered_at_all_when_unconfigured(self) -> None:
        entry = _make_entry(weather_forecast_temperature_entity=None, strings=[_string()])
        coordinator, _hass = _make_coordinator(entry)
        assert _PREDICTOR_ENTITY not in coordinator._entity_providers

    def test_same_entity_id_as_a_string_source_is_registered_only_once(self) -> None:
        # The predictor and a string's own weather-tier source happening
        # to be the same entity_id is a legal (if unusual) config —
        # `_ensure_temperature_provider`'s existing idempotency guard
        # (`if entity_id in self._entity_providers: return`) must still
        # hold, exactly as it already does for the baseline-provider
        # case this task didn't touch.
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source=_PREDICTOR_ENTITY,
            strings=[_string()],
        )
        coordinator, _hass = _make_coordinator(entry)
        assert list(coordinator._entity_providers).count(_PREDICTOR_ENTITY) == 1


# -- _fit_temperature_string (ADR-003c §2) -----------------------------------


class TestFitTemperatureString:
    def test_weather_tier_needs_no_learned_model(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source="weather.home",
            strings=[_string()],
        )
        coordinator, _hass = _make_coordinator(entry)
        assert coordinator._fit_temperature_string(coordinator._strings[0], _NOW) is None

    def test_unresolved_source_needs_no_learned_model(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=None,
            default_temperature_source=_AMBIENT_SENSOR_ENTITY,
            strings=[_string()],
        )
        coordinator, _hass = _make_coordinator(entry)
        assert coordinator._fit_temperature_string(coordinator._strings[0], _NOW) is None

    def test_cell_tier_produces_a_fitted_model(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            strings=[_string(temperature_source_entity_id=_CELL_SENSOR_ENTITY)],
        )
        coordinator, _hass = _make_coordinator(entry)
        model = coordinator._fit_temperature_string(coordinator._strings[0], _NOW)
        assert isinstance(model, FittedModel)

    def test_apply_magnitude_weight_false_is_actually_wired(self) -> None:
        # A clean, entirely-negative-valued (sub-freezing) predictor
        # training set with an exact linear target relationship
        # (target = predictor - 10). If `apply_magnitude_weight=True`
        # were mistakenly used instead of TASK-0005-patch-5's `False`,
        # `_magnitude_weight`'s row_max would be <= 0 for this slot's
        # entire row (every predictor value negative), zeroing out every
        # sample's weight -> zero confidence -> predict_unclamped's
        # cold-start passthrough (returns the *query* value unmodified).
        # With apply_magnitude_weight=False correctly wired, the model
        # instead genuinely fits the linear relationship and predicts
        # close to query - 10 for a query inside the training range.
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            window_days=5,
            strings=[_string(temperature_source_entity_id=_CELL_SENSOR_ENTITY)],
        )
        coordinator, _hass = _make_coordinator(entry)
        slot = 100
        predictor_values = [-10.0, -8.0, -6.0, -4.0, -2.0]
        target_values = [value - 10.0 for value in predictor_values]

        reference = _NOW
        for day_offset, (predictor_value, target_value) in enumerate(
            zip(predictor_values, target_values, strict=True)
        ):
            day = reference - timedelta(days=5 - day_offset)
            day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
            index = Cache.index_for(day_start) + slot
            coordinator.cache.push(_PREDICTOR_ENTITY, {index: predictor_value}, index)
            coordinator.cache.push(_CELL_SENSOR_ENTITY, {index: target_value}, index)

        model = coordinator._fit_temperature_string(coordinator._strings[0], reference)
        assert model is not None

        query = np.full(SLOTS_PER_DAY, np.nan, dtype=np.float64)
        query[slot] = -3.0
        predicted, confidence = model.predict_unclamped(query)

        assert confidence[slot] > 0.0
        # A broken (True-mode) fit would instead predict exactly -3.0
        # (unmodified passthrough) — well outside this tolerance.
        assert abs(predicted[slot] - (-3.0 - 10.0)) < 1.0


# -- _predict_target_slot_temperature (ADR-003b §1b, ADR-003c §4) ----------


class TestPredictTargetSlotTemperature:
    def test_weather_tier_unchanged_uses_native_forecast_with_uplift(self) -> None:
        entry = _make_entry(
            default_temperature_source="weather.home",
            max_uplift_c=25,
            strings=[_string(rated_dc_capacity_wp=2000.0)],
        )
        coordinator, hass = _make_coordinator(entry)
        hass.states.set("weather.home", _weather_forecast_state({0: 5.0, 200: 15.0}))
        string = coordinator._strings[0]
        resolution = coordinator._resolve_temperature_entity(string)
        assert resolution is not None and resolution.tier == "weather"

        fc_array = np.full(SLOTS_PER_DAY, np.nan, dtype=np.float64)
        fc_array[0] = 0.0
        fc_array[200] = 1000.0

        result = coordinator._predict_target_slot_temperature(
            string, resolution, fc_array, _DAY_START
        )
        assert result is not None
        expected_ambient = np.array(
            [
                (5.0 if slot == 0 else (15.0 if slot == 200 else np.nan))
                for slot in range(SLOTS_PER_DAY)
            ],
            dtype=np.float64,
        )
        expected = uplift_ambient_to_cell(expected_ambient, fc_array, 2000.0, 25.0)
        assert np.allclose(result[0], expected[0])
        assert np.allclose(result[200], expected[200])

    def test_weather_tier_none_without_rated_capacity(self) -> None:
        entry = _make_entry(default_temperature_source="weather.home", strings=[_string()])
        coordinator, hass = _make_coordinator(entry)
        hass.states.set("weather.home", _weather_forecast_state({0: 5.0}))
        string = coordinator._strings[0]
        resolution = coordinator._resolve_temperature_entity(string)
        assert resolution is not None
        fc_array = np.full(SLOTS_PER_DAY, 0.0, dtype=np.float64)
        assert (
            coordinator._predict_target_slot_temperature(string, resolution, fc_array, _DAY_START)
            is None
        )

    def test_cell_tier_uses_predicted_temp_directly_no_uplift(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            max_uplift_c=25,
            strings=[
                _string(
                    temperature_source_entity_id=_CELL_SENSOR_ENTITY, rated_dc_capacity_wp=2000.0
                )
            ],
        )
        coordinator, hass = _make_coordinator(entry)
        # The cell sensor itself never gets a live state -> guaranteed
        # cold-start (zero confidence, guaranteed passthrough) fit, so
        # predicted_temp is known exactly: the predictor's own forecast
        # value, unmodified.
        hass.states.set(_PREDICTOR_ENTITY, _weather_forecast_state({50: 8.0, 150: 30.0}))
        string = coordinator._strings[0]
        model = coordinator._fit_temperature_string(string, _NOW)
        assert model is not None
        coordinator._temperature_models[string.index] = model

        resolution = coordinator._resolve_temperature_entity(string)
        assert resolution is not None and resolution.tier == "cell"
        fc_array = np.full(SLOTS_PER_DAY, 1000.0, dtype=np.float64)

        result = coordinator._predict_target_slot_temperature(
            string, resolution, fc_array, _DAY_START
        )
        assert result is not None
        # No uplift: the raw predictor forecast values pass straight
        # through, unlike a very different value uplift would have
        # produced for the same fc/rated_dc_capacity_wp/max_uplift_c.
        assert np.isclose(result[50], 8.0)
        assert np.isclose(result[150], 30.0)

    def test_ambient_tier_applies_the_same_uplift_a_live_reading_would(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source=_AMBIENT_SENSOR_ENTITY,
            max_uplift_c=25,
            strings=[_string(rated_dc_capacity_wp=2000.0)],
        )
        coordinator, hass = _make_coordinator(entry)
        # Same cold-start-guarantee trick: the ambient sensor never gets
        # a live state, so predicted_temp is exactly the predictor's own
        # forecast value.
        hass.states.set(_PREDICTOR_ENTITY, _weather_forecast_state({50: 8.0, 150: 30.0}))
        string = coordinator._strings[0]
        model = coordinator._fit_temperature_string(string, _NOW)
        assert model is not None
        coordinator._temperature_models[string.index] = model

        resolution = coordinator._resolve_temperature_entity(string)
        assert resolution is not None and resolution.tier == "ambient"
        fc_array = np.full(SLOTS_PER_DAY, np.nan, dtype=np.float64)
        fc_array[50] = 0.0
        fc_array[150] = 1000.0

        result = coordinator._predict_target_slot_temperature(
            string, resolution, fc_array, _DAY_START
        )
        assert result is not None
        expected_50 = uplift_ambient_to_cell(8.0, 0.0, 2000.0, 25.0)
        expected_150 = uplift_ambient_to_cell(30.0, 1000.0, 2000.0, 25.0)
        assert np.isclose(result[50], expected_50)
        assert np.isclose(result[150], expected_150)
        # And this must differ from the un-uplifted cell-tier behavior
        # the previous test already confirmed for the exact same
        # predicted_temp/fc values (fc[150]=1000 gives a nonzero uplift).
        assert not np.isclose(result[150], 30.0)

    def test_ambient_tier_none_without_rated_capacity(self) -> None:
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            default_temperature_source=_AMBIENT_SENSOR_ENTITY,
            strings=[_string()],
        )
        coordinator, hass = _make_coordinator(entry)
        hass.states.set(_PREDICTOR_ENTITY, _weather_forecast_state({0: 8.0}))
        string = coordinator._strings[0]
        model = coordinator._fit_temperature_string(string, _NOW)
        assert model is not None
        coordinator._temperature_models[string.index] = model
        resolution = coordinator._resolve_temperature_entity(string)
        assert resolution is not None
        fc_array = np.full(SLOTS_PER_DAY, 0.0, dtype=np.float64)
        assert (
            coordinator._predict_target_slot_temperature(string, resolution, fc_array, _DAY_START)
            is None
        )

    def test_cell_tier_none_when_no_model_fitted_yet(self) -> None:
        # Defensive fallback (ADR-000 §8): a resolvable cell/ambient
        # string whose temperature model has, for whatever reason, never
        # been fit yet -> graceful skip, not a KeyError.
        entry = _make_entry(
            weather_forecast_temperature_entity=_PREDICTOR_ENTITY,
            strings=[_string(temperature_source_entity_id=_CELL_SENSOR_ENTITY)],
        )
        coordinator, _hass = _make_coordinator(entry)
        string = coordinator._strings[0]
        resolution = coordinator._resolve_temperature_entity(string)
        assert resolution is not None
        assert string.index not in coordinator._temperature_models
        fc_array = np.full(SLOTS_PER_DAY, 0.0, dtype=np.float64)
        assert (
            coordinator._predict_target_slot_temperature(string, resolution, fc_array, _DAY_START)
            is None
        )


# -- _apply_training_corrections (ADR-003a §1/§2, ADR-003b §1/§1a) ---------


class TestApplyTrainingCorrectionsTierDispatch:
    """Direct, hand-computed coverage of the training-side tier
    dispatch — `cell` uses its own reading as-is (never calling
    `uplift_ambient_to_cell`, and therefore never gated on
    `rated_dc_capacity_wp`); `ambient` (like `weather`, unchanged)
    always passes through it first, and *is* gated on that field."""

    @staticmethod
    def _fixture(rated_dc_capacity_wp: float | None) -> tuple[Any, Any]:
        entry = _make_entry(strings=[_string(rated_dc_capacity_wp=rated_dc_capacity_wp)])
        coordinator, _hass = _make_coordinator(entry)
        return coordinator, coordinator._strings[0]

    def test_cell_tier_uses_reading_directly_ungated_on_rated_capacity(self) -> None:
        coordinator, string = self._fixture(rated_dc_capacity_wp=None)
        fc_by_offset = {0: np.array([[1000.0]])}
        pv_by_offset = {0: np.array([[500.0]])}
        temperature_by_offset = {0: np.array([[35.0]])}

        corrected = coordinator._apply_training_corrections(
            string, fc_by_offset, pv_by_offset, temperature_by_offset, "cell"
        )
        coefficient_per_c = string.temperature_coefficient_pct_per_c / 100.0
        expected = derate_actual_to_reference(
            pv_by_offset[0], temperature_by_offset[0], coefficient_per_c
        )
        assert np.allclose(corrected[0], expected)

    def test_ambient_tier_applies_uplift_first(self) -> None:
        coordinator, string = self._fixture(rated_dc_capacity_wp=2000.0)
        fc_by_offset = {0: np.array([[1000.0]])}
        pv_by_offset = {0: np.array([[500.0]])}
        temperature_by_offset = {0: np.array([[35.0]])}

        corrected = coordinator._apply_training_corrections(
            string, fc_by_offset, pv_by_offset, temperature_by_offset, "ambient"
        )
        coefficient_per_c = string.temperature_coefficient_pct_per_c / 100.0
        uplifted = uplift_ambient_to_cell(
            temperature_by_offset[0], fc_by_offset[0], 2000.0, coordinator._max_uplift_c
        )
        expected = derate_actual_to_reference(pv_by_offset[0], uplifted, coefficient_per_c)
        assert np.allclose(corrected[0], expected)
        # And this must differ from the cell-tier (no-uplift) result for
        # the exact same raw inputs — the concrete behavioral distinction
        # the two acceptance criteria describe.
        cell_equivalent = derate_actual_to_reference(
            pv_by_offset[0], temperature_by_offset[0], coefficient_per_c
        )
        assert not np.allclose(corrected[0], cell_equivalent)

    def test_ambient_tier_skipped_entirely_without_rated_capacity(self) -> None:
        # Gated on rated_dc_capacity_wp, unlike cell -- absent, so no
        # correction at all (not degraded to some naive value).
        coordinator, string = self._fixture(rated_dc_capacity_wp=None)
        fc_by_offset = {0: np.array([[1000.0]])}
        pv_by_offset = {0: np.array([[500.0]])}
        temperature_by_offset = {0: np.array([[35.0]])}

        corrected = coordinator._apply_training_corrections(
            string, fc_by_offset, pv_by_offset, temperature_by_offset, "ambient"
        )
        assert np.allclose(corrected[0], pv_by_offset[0])

    def test_no_tier_resolved_means_no_correction(self) -> None:
        coordinator, string = self._fixture(rated_dc_capacity_wp=2000.0)
        fc_by_offset = {0: np.array([[1000.0]])}
        pv_by_offset = {0: np.array([[500.0]])}

        corrected = coordinator._apply_training_corrections(
            string, fc_by_offset, pv_by_offset, None, None
        )
        assert np.allclose(corrected[0], pv_by_offset[0])


# -- end-to-end: no predictor configured skips both sides (ADR-003c §5) ----


class TestNoPredictorSkipsBothSidesEndToEnd:
    """Given a `sensor.*`-domain temperature source with no global
    weather-forecast predictor configured, When a full refit+recompute
    runs, Then the pushed forecast is byte-identical to a control run
    with no temperature source configured at all — ADR-003c §5's "not
    degraded to a naive fallback" requirement, proven end-to-end rather
    than only at the unit level above."""

    @staticmethod
    def _pushed_values(**string_overrides: Any) -> dict[int, float]:
        entry = _make_entry(
            weather_forecast_temperature_entity=None,
            default_temperature_source=_AMBIENT_SENSOR_ENTITY,
            strings=[_string(rated_dc_capacity_wp=2000.0, **string_overrides)],
        )
        hass = FakeHomeAssistant()
        hass.states.set(
            _BASELINE_ENTITY,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=1))},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
        # Deliberately no state at all for _AMBIENT_SENSOR_ENTITY —
        # unconfigured-predictor is the point of this test, not a
        # missing-entity edge case.
        coordinator, _hass = _make_coordinator(entry, hass)
        _run(coordinator.async_refit(_NOW))
        return hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))

    def test_matches_a_control_run_with_no_temperature_source_at_all(self) -> None:
        with_unresolvable_ambient = self._pushed_values()
        without_any_source = self._pushed_values(
            temperature_source_entity_id="none",
        )
        assert with_unresolvable_ambient == without_any_source
        # And it must be a genuinely non-trivial result (not both
        # accidentally empty), or this equality would be vacuous.
        assert len(with_unresolvable_ambient) > 0
