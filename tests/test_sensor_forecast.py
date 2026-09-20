"""Tests for `sensor.py`'s `ShadyForecastSensor` (ADR-002 §3/§5,
TASK-0011).

`sensor.py` is HA-facing (real, non-`TYPE_CHECKING` imports of
`homeassistant.components.sensor`/`homeassistant.const`) — outside
ADR-000 §6's zero-mocking pure tier. This file extends `test_coordinator
.py`'s hand-written `homeassistant` stub convention with the additional
surface `sensor.py` touches: `homeassistant.components.sensor`'s
`SensorEntity`/`SensorDeviceClass`/`SensorStateClass` and
`homeassistant.const.UnitOfPower` — real (non-`Mock`) stand-ins,
registered directly in `sys.modules` before file-path-loading the
module under test. Fully self-contained (this task's own fixtures,
independent of any other test file's `sys.modules` state), per that
same established convention.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

from tests.support import _load, _run
from tests.support_ha import FakeHomeAssistant, _install_ha_stub, _install_sensor_stub

_install_ha_stub()
_install_sensor_stub()

# Same `shady` top-level package trick `test_coordinator.py` established
# (see its own comment) — required for coordinator.py's `from .regression
# import kernel, linear, wls2, wls3` package-level import to resolve.
_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []
sys.modules["shady"] = _shady_pkg

_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_load("regression/base.py", "shady.regression.base")
_const_mod = _load("const.py", "shady.const")
_load("cache.py", "shady.cache")
_load("providers/discovery.py", "shady.providers.discovery")
_load("providers/temperature.py", "shady.providers.temperature")
_load("regression/__init__.py", "shady.regression")
_load("regression/linear.py", "shady.regression.linear")
_load("regression/kernel.py", "shady.regression.kernel")
_load("regression/wls2.py", "shady.regression.wls2")
_load("regression/wls3.py", "shady.regression.wls3")
_load("yield_correction.py", "shady.yield_correction")
_load("forecast_adjust.py", "shady.forecast_adjust")
_load("aggregation.py", "shady.aggregation")
_load("string_computation.py", "shady.string_computation")
_load("diagnostics/__init__.py", "shady.diagnostics")
_load("diagnostics/base.py", "shady.diagnostics.base")
_load("diagnostics/compare_regressions.py", "shady.diagnostics.compare_regressions")
_load("coordinator_like.py", "shady.coordinator_like")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")
_load("device.py", "shady.device")
_sensor_mod = _load("sensor.py", "shady.sensor")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = sys.modules["shady.cache"].Cache
CONF_STRINGS = _const_mod.CONF_STRINGS
DOMAIN = _const_mod.DOMAIN
async_setup_entry = _sensor_mod.async_setup_entry
ShadyForecastSensor = _sensor_mod.ShadyForecastSensor
ShadyPvSumSensor = _sensor_mod.ShadyPvSumSensor
ShadyFcSumSensor = _sensor_mod.ShadyFcSumSensor
ShadyFcDaySumSensor = _sensor_mod.ShadyFcDaySumSensor
ShadyFcRemainingTodaySensor = _sensor_mod.ShadyFcRemainingTodaySensor
ShadyPvEnergyIntegralSensor = _sensor_mod.ShadyPvEnergyIntegralSensor
ShadyFcEnergyIntegralSensor = _sensor_mod.ShadyFcEnergyIntegralSensor

# -- shared test fixture (mirrors test_coordinator.py's own) ---------------

_NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 6, 14, tzinfo=UTC)
_BASELINE_ENTITY = "sensor.forecast_solar_estimate"
_ACTUAL_YIELD_ENTITY = "sensor.string_a_yield"


def _synthetic_wh_period(start: datetime, end: datetime) -> dict[str, float]:
    out: dict[str, float] = {}
    step = timedelta(minutes=5)
    current = start
    while current < end:
        out[current.isoformat()] = 500.0 if 6 <= current.hour < 18 else 0.0
        current += step
    return out


def _seed_actual_yield_statistics(hass: FakeHomeAssistant, start: datetime, end: datetime) -> None:
    by_start: dict[datetime, float] = {}
    step = timedelta(minutes=5)
    current = start
    while current < end:
        by_start[current] = 400.0 if 6 <= current.hour < 18 else 0.0
        current += step
    hass.statistics[_ACTUAL_YIELD_ENTITY] = by_start


def _make_entry(**overrides: Any) -> Any:
    data: dict[str, Any] = {
        "baseline_entity_id": _BASELINE_ENTITY,
        "baseline_attribute": "wh_period",
        "baseline_shape": "sensor_dict",
        "temperature_aware": False,
        "window_days": 1,
        "regression_method": "wls2",
        "smoothing_radius": 0,
        "neighbor_fitting_cutoff": 0.25,
        "recency_decay_max": 0.5,
        "clipping_threshold": 0.98,
        "default_temperature_source": None,
        "max_uplift_c": 25,
        "weather_forecast_temperature_entity": None,
        "temperature_regression_method": "wls2",
        "intraday_correction_mode": "off",
        "intraday_correction_cutoff": 0.10,
        "window_slots": 24,
        "ramp_slots": 12,
        CONF_STRINGS: {
            _ACTUAL_YIELD_ENTITY: {
                "name": "Dach Süd",
                "baseline_entity_id": None,
                "baseline_attribute": None,
                "baseline_shape": None,
                "converter_limit_w": None,
                "temperature_source_entity_id": None,
                "temperature_coefficient_pct_per_c": -0.4,
                "rated_dc_capacity_wp": None,
            }
        },
    }
    data.update(overrides)
    config_entries_mod = sys.modules["homeassistant.config_entries"]
    return config_entries_mod.ConfigEntry("test_entry", data)


def _make_ready_coordinator() -> tuple[Any, FakeHomeAssistant, Any]:
    """A coordinator that has already fit + pushed an initial forecast
    (mirrors what `TASK-0016`'s real `__init__.py` will do via
    `async_startup`, but calling `async_refit` directly here — this
    task does not depend on `TASK-0016`)."""
    hass = FakeHomeAssistant()
    hass.states.set(
        _BASELINE_ENTITY,
        {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
    )
    hass.states.set(_ACTUAL_YIELD_ENTITY, {})
    _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
    entry = _make_entry()
    coordinator = ShadyCoordinator(hass, entry)
    coordinator._now = lambda: _NOW
    _run(coordinator.async_refit(_NOW))
    return coordinator, hass, entry


class _FakeAddEntities:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def __call__(self, entities: Any) -> None:
        self.added.extend(entities)


class TestAsyncSetupEntry:
    """Given `hass.data[DOMAIN][entry.entry_id]` already holds a
    `ShadyCoordinator` for a config entry with one configured string,
    When `sensor.py`'s `async_setup_entry` runs, Then one
    `ShadyForecastSensor` per configured string is added, plus the six
    config-entry-level aggregate sensors (ADR-005, TASK-0012), plus —
    as of `TASK-0015b` — one `ShadyDiagnosticsSensor` per `(sensor_id,
    name)` pair `coordinator.diagnostic_sensor_ids()` declares (ADR-004
    §2/§2b, §5 fifth Amendment): `CompareRegressionsMode` declares one
    id per configured string plus one `"sum"` id, so 1 forecast + 6
    aggregates + 1 diagnostics + 1 diagnostics-sum = 9 for this
    fixture's single configured string."""

    def test_one_sensor_per_configured_string_plus_six_aggregates(self) -> None:
        coordinator, hass, entry = _make_ready_coordinator()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        add_entities = _FakeAddEntities()

        _run(async_setup_entry(hass, entry, add_entities))

        assert len(add_entities.added) == 9
        forecast_sensors = [e for e in add_entities.added if isinstance(e, ShadyForecastSensor)]
        assert len(forecast_sensors) == 1
        aggregate_types = {
            ShadyPvSumSensor,
            ShadyFcSumSensor,
            ShadyFcDaySumSensor,
            ShadyFcRemainingTodaySensor,
            ShadyPvEnergyIntegralSensor,
            ShadyFcEnergyIntegralSensor,
        }
        aggregate_sensors = [e for e in add_entities.added if type(e) in aggregate_types]
        assert len(aggregate_sensors) == 6
        assert {type(e) for e in aggregate_sensors} == aggregate_types


class TestForecastSensorValue:
    """Given a real, freshly-refit coordinator with seeded fake
    recorder/provider data, When the sensor's state/attributes are
    inspected, Then it exposes a plausible corrected value read
    straight from `coordinator.cache` — no computation of its own
    (ADR-000 §3)."""

    def test_native_value_matches_cache_directly(self) -> None:
        coordinator, _hass, _entry = _make_ready_coordinator()
        string_index, string_name = coordinator.strings()[0]
        sensor = ShadyForecastSensor(coordinator, _entry, string_index, string_name)
        # The exact `_NOW` slot is itself frozen by the refit that just
        # ran against it (`not_before_index = index_for(now) + 1`,
        # TASK-0010-patch-1) — legitimately `None` right at that instant,
        # same as any other already-elapsed-or-elapsing slot. Query a
        # few minutes later, matching a realistic poll shortly after a
        # recompute, where the very next slot has a real pushed value.
        query_time = _NOW + timedelta(minutes=5)
        sensor._now = lambda: query_time

        expected = coordinator.cache.get_time_range(
            [coordinator.forecast_sensor_id(string_index)], query_time, query_time, on_invalid="raw"
        )[coordinator.forecast_sensor_id(string_index)][0]

        assert sensor.native_value == expected
        assert isinstance(sensor.native_value, float)
        assert sensor.native_value > 0.0  # 10:05, daytime, sunny synthetic fixture

    def test_the_exact_recompute_instant_is_frozen_not_synthesized(self) -> None:
        # Documents the `not_before_index` freeze (TASK-0010-patch-1):
        # the sensor never invents a value for a frozen slot — it
        # reports exactly what `coordinator.cache` holds, `None` here.
        coordinator, _hass, _entry = _make_ready_coordinator()
        string_index, string_name = coordinator.strings()[0]
        sensor = ShadyForecastSensor(coordinator, _entry, string_index, string_name)
        sensor._now = lambda: _NOW

        assert sensor.native_value is None

    def test_today_and_tomorrow_attributes_are_288_slot_arrays_from_cache(self) -> None:
        coordinator, _hass, _entry = _make_ready_coordinator()
        string_index, string_name = coordinator.strings()[0]
        sensor = ShadyForecastSensor(coordinator, _entry, string_index, string_name)
        sensor._now = lambda: _NOW

        attrs = sensor.extra_state_attributes

        assert set(attrs) == {
            "today",
            "tomorrow",
            "values_raw",
            "intraday_ratio",
            "intraday_state",
            "intraday_ramp_weight",
            "intraday_blend_active",
        }
        assert len(attrs["today"]) == 288
        assert len(attrs["tomorrow"]) == 288
        # Some daytime slots already pushed by the refit-triggered recompute.
        assert any(v is not None and v > 0.0 for v in attrs["today"])
        assert any(v is not None and v > 0.0 for v in attrs["tomorrow"])

    def test_unique_id_is_the_exact_cache_sensor_id(self) -> None:
        coordinator, _hass, _entry = _make_ready_coordinator()
        string_index, string_name = coordinator.strings()[0]
        sensor = ShadyForecastSensor(coordinator, _entry, string_index, string_name)

        assert sensor._attr_unique_id == coordinator.forecast_sensor_id(string_index)

    def test_no_forecast_yet_reports_none_not_an_invented_value(self) -> None:
        # A coordinator that has never been refit at all: nothing pushed.
        hass = FakeHomeAssistant()
        hass.states.set(
            _BASELINE_ENTITY,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        entry = _make_entry()
        coordinator = ShadyCoordinator(hass, entry)
        string_index, string_name = coordinator.strings()[0]
        sensor = ShadyForecastSensor(coordinator, entry, string_index, string_name)
        sensor._now = lambda: _NOW

        assert sensor.native_value is None
        assert all(v is None for v in sensor.extra_state_attributes["today"])
