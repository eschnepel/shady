"""Tests for `sensor.py`'s six config-entry-level aggregate sensors
(ADR-005, TASK-0012): `ShadyPvSumSensor`, `ShadyFcSumSensor`,
`ShadyFcDaySumSensor`, `ShadyFcRemainingTodaySensor`,
`ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor`.

Own independent `homeassistant` stub, per the same established
convention as `test_button.py`/`test_sensor_forecast.py` — fully
self-contained, not sharing `sys.modules` state with any other test
file. `ShadyForecastSensor` itself (the per-string sensor) is
`test_sensor_forecast.py`'s job; this file only covers the six
aggregates `async_setup_entry` adds alongside it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _set_state(
    hass: Any,
    entity_id: str,
    attributes: dict[str, Any] | None = None,
    state: float | str | None = None,
) -> None:
    """`FakeStates.set` inside a running event loop — necessary for
    `_ACTUAL_YIELD_ENTITY`, since `_handle_actual_yield_update`
    (ADR-005 §5) is a synchronous `@callback` that calls
    `hass.async_create_task`, which needs a running loop to attach to;
    a bare `hass.states.set(...)` outside of `_run`/`asyncio.run` has
    none (matches `test_coordinator.py`'s own copy of this helper)."""

    async def _drive() -> None:
        hass.states.set(entity_id, attributes, state)
        await hass.drain()

    _run(_drive())


# -- hand-written `homeassistant` stub (real stand-in, not a mock) ----------


def _callback(func: Any) -> Any:
    return func


class FakeState:
    def __init__(
        self,
        entity_id: str,
        attributes: dict[str, Any] | None = None,
        state: str = "unknown",
    ) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    def __init__(self) -> None:
        self._states: dict[str, FakeState] = {}
        self._listeners: dict[str, list[Any]] = {}

    def get(self, entity_id: str) -> FakeState | None:
        return self._states.get(entity_id)

    def async_all(self, domain: str | None = None) -> list[FakeState]:
        values = list(self._states.values())
        if domain is None:
            return values
        return [s for s in values if s.entity_id.startswith(f"{domain}.")]

    def set(
        self,
        entity_id: str,
        attributes: dict[str, Any] | None = None,
        state: float | str | None = None,
    ) -> None:
        resolved_state = "unknown" if state is None else str(state)
        self._states[entity_id] = FakeState(entity_id, attributes, resolved_state)
        for listener in self._listeners.get(entity_id, []):
            listener(None)


class FakeStore:
    """Real (non-`Mock`) stand-in for `homeassistant.helpers.storage
    .Store` — backed by `hass.store_data`, matching every other test
    file's copy of this stub."""

    def __init__(self, hass: Any, version: int, key: str) -> None:
        self._hass = hass
        self._version = version
        self._key = key

    async def async_load(self) -> Any:
        return self._hass.store_data.get(self._key)

    async def async_save(self, data: Any) -> None:
        self._hass.store_data[self._key] = data


class FakeHomeAssistant:
    def __init__(self) -> None:
        self.states = FakeStates()
        self.statistics: dict[str, dict[datetime, float]] = {}
        self.data: dict[str, Any] = {}
        self._pending_tasks: list[asyncio.Task[Any]] = []
        self.store_data: dict[str, Any] = {}

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)

    def async_create_task(self, coro: Any) -> Any:
        task = asyncio.ensure_future(coro)
        self._pending_tasks.append(task)
        return task

    async def drain(self) -> None:
        while self._pending_tasks:
            pending = self._pending_tasks
            self._pending_tasks = []
            await asyncio.gather(*pending)


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_const = ModuleType("homeassistant.const")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers_event = ModuleType("homeassistant.helpers.event")
    ha_helpers_storage = ModuleType("homeassistant.helpers.storage")
    ha_components = ModuleType("homeassistant.components")
    ha_recorder = ModuleType("homeassistant.components.recorder")
    ha_recorder_statistics = ModuleType("homeassistant.components.recorder.statistics")
    ha_components_sensor = ModuleType("homeassistant.components.sensor")

    ha_core.callback = _callback  # type: ignore[attr-defined]

    class FakeConfigEntry:
        def __init__(self, entry_id: str, data: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.data = data

    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]

    def async_track_time_change(
        hass: Any, action: Any, *, hour: int, minute: int, second: int
    ) -> Any:
        return lambda: None

    def async_track_time_interval(hass: Any, action: Any, interval: Any) -> Any:
        # Same non-auto-firing convention as `async_track_time_change`
        # above (TASK-0013) -- tests that need the intraday tick call
        # `_handle_intraday_tick` directly.
        return lambda: None

    def async_track_state_change_event(hass: Any, entity_ids: list[str], action: Any) -> Any:
        for entity_id in entity_ids:
            hass.states._listeners.setdefault(entity_id, []).append(action)

        def _unsub() -> None:
            for entity_id in entity_ids:
                listeners = hass.states._listeners.get(entity_id, [])
                if action in listeners:
                    listeners.remove(action)

        return _unsub

    ha_helpers_event.async_track_time_change = async_track_time_change  # type: ignore[attr-defined]
    ha_helpers_event.async_track_time_interval = async_track_time_interval  # type: ignore[attr-defined]
    ha_helpers_event.async_track_state_change_event = (  # type: ignore[attr-defined]
        async_track_state_change_event
    )

    def statistics_during_period(
        hass: Any,
        start_time: datetime,
        end_time: datetime | None,
        statistic_ids: set[str] | None,
        period: str,
        units: Any,
        types: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for entity_id in statistic_ids or set():
            by_start = hass.statistics.get(entity_id, {})
            rows = [
                {"start": start, "mean": mean}
                for start, mean in sorted(by_start.items())
                if start >= start_time and (end_time is None or start < end_time)
            ]
            result[entity_id] = rows
        return result

    ha_recorder_statistics.statistics_during_period = statistics_during_period  # type: ignore[attr-defined]

    # -- `homeassistant.components.sensor` --

    class SensorEntity:
        """Real (non-Mock) stand-in — nothing beyond a plain base class
        carrying `_attr_*` attributes; every aggregate sensor overrides
        every relevant property itself (ADR-000 §3's thin-glue rule)."""

    class SensorDeviceClass:
        POWER = "power"
        ENERGY = "energy"

    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL = "total"
        TOTAL_INCREASING = "total_increasing"

    ha_components_sensor.SensorEntity = SensorEntity  # type: ignore[attr-defined]
    ha_components_sensor.SensorDeviceClass = SensorDeviceClass  # type: ignore[attr-defined]
    ha_components_sensor.SensorStateClass = SensorStateClass  # type: ignore[attr-defined]

    class UnitOfPower:
        WATT = "W"

    class UnitOfEnergy:
        WATT_HOUR = "Wh"

    ha_const.UnitOfPower = UnitOfPower  # type: ignore[attr-defined]
    ha_const.UnitOfEnergy = UnitOfEnergy  # type: ignore[attr-defined]

    ha_helpers_storage.Store = FakeStore  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.const = ha_const  # type: ignore[attr-defined]
    ha.helpers = ha_helpers  # type: ignore[attr-defined]
    ha_helpers.event = ha_helpers_event  # type: ignore[attr-defined]
    ha_helpers.storage = ha_helpers_storage  # type: ignore[attr-defined]
    ha.components = ha_components  # type: ignore[attr-defined]
    ha_components.recorder = ha_recorder  # type: ignore[attr-defined]
    ha_recorder.statistics = ha_recorder_statistics  # type: ignore[attr-defined]
    ha_components.sensor = ha_components_sensor  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.event"] = ha_helpers_event
    sys.modules["homeassistant.helpers.storage"] = ha_helpers_storage
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.recorder"] = ha_recorder
    sys.modules["homeassistant.components.recorder.statistics"] = ha_recorder_statistics
    sys.modules["homeassistant.components.sensor"] = ha_components_sensor


_install_ha_stub()

# Same `shady` top-level package trick every other HA-facing test file
# established — required for coordinator.py's `from .regression import
# kernel, linear, wls2, wls3` package-level import to resolve.
_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []
sys.modules["shady"] = _shady_pkg

_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_load("providers/discovery.py", "shady.providers.discovery")
_load("providers/temperature.py", "shady.providers.temperature")
_load("regression/__init__.py", "shady.regression")
_load("regression/base.py", "shady.regression.base")
_load("regression/linear.py", "shady.regression.linear")
_load("regression/kernel.py", "shady.regression.kernel")
_load("regression/wls2.py", "shady.regression.wls2")
_load("regression/wls3.py", "shady.regression.wls3")
_load("yield_correction.py", "shady.yield_correction")
_load("forecast_adjust.py", "shady.forecast_adjust")
_load("aggregation.py", "shady.aggregation")
_load("cache.py", "shady.cache")
_load("string_computation.py", "shady.string_computation")
_load("diagnostics/__init__.py", "shady.diagnostics")
_load("diagnostics/base.py", "shady.diagnostics.base")
_load("diagnostics/compare_regressions.py", "shady.diagnostics.compare_regressions")
_const_mod = _load("const.py", "shady.const")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")
_sensor_mod = _load("sensor.py", "shady.sensor")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = sys.modules["shady.cache"].Cache
CONF_STRINGS = _const_mod.CONF_STRINGS
DOMAIN = _const_mod.DOMAIN
ShadyPvSumSensor = _sensor_mod.ShadyPvSumSensor
ShadyFcSumSensor = _sensor_mod.ShadyFcSumSensor
ShadyFcDaySumSensor = _sensor_mod.ShadyFcDaySumSensor
ShadyFcRemainingTodaySensor = _sensor_mod.ShadyFcRemainingTodaySensor
ShadyPvEnergyIntegralSensor = _sensor_mod.ShadyPvEnergyIntegralSensor
ShadyFcEnergyIntegralSensor = _sensor_mod.ShadyFcEnergyIntegralSensor

_ha_components_sensor = sys.modules["homeassistant.components.sensor"]
SensorDeviceClass = _ha_components_sensor.SensorDeviceClass
SensorStateClass = _ha_components_sensor.SensorStateClass
_ha_const = sys.modules["homeassistant.const"]
UnitOfPower = _ha_const.UnitOfPower
UnitOfEnergy = _ha_const.UnitOfEnergy

# -- shared test fixture (mirrors test_coordinator.py's own) ---------------

_NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 6, 14, tzinfo=UTC)
_BASELINE_ENTITY = "sensor.forecast_solar_estimate"
_ACTUAL_YIELD_ENTITY = "sensor.string_a_yield"


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
        CONF_STRINGS: [
            {
                "name": "Dach Süd",
                "baseline_entity_id": None,
                "baseline_attribute": None,
                "baseline_shape": None,
                "actual_yield_entity_id": _ACTUAL_YIELD_ENTITY,
                "converter_limit_w": None,
                "temperature_source_entity_id": None,
                "temperature_coefficient_pct_per_c": -0.4,
                "rated_dc_capacity_wp": None,
            }
        ],
    }
    data.update(overrides)
    config_entries_mod = sys.modules["homeassistant.config_entries"]
    return config_entries_mod.ConfigEntry("test_entry", data)


def _make_coordinator() -> tuple[Any, FakeHomeAssistant, Any]:
    hass = FakeHomeAssistant()
    hass.states.set(_BASELINE_ENTITY, {"wh_period": {}})
    hass.states.set(_ACTUAL_YIELD_ENTITY, {})
    entry = _make_entry()
    coordinator = ShadyCoordinator(hass, entry)
    coordinator._now = lambda: _NOW
    return coordinator, hass, entry


def _push_forecast(coordinator: Any, string_index: int, timestamp: datetime, value: float) -> None:
    """Test-only helper: writes one slot directly into a
    `ShadyForecastSensor` cache key — `Cache.push`'s real signature
    takes an index->value dict and a `not_before_index` floor, not a
    single `(timestamp, value)` pair."""
    index = Cache.index_for(timestamp)
    coordinator.cache.push(coordinator.forecast_sensor_id(string_index), {index: value}, index)


class TestSensorDeviceAndStateClasses:
    """ADR-005's own device/state-class table: §1/§2 → POWER/WATT/
    MEASUREMENT; §3/§4 → ENERGY/Wh/TOTAL; §5/§6 → ENERGY/Wh/
    TOTAL_INCREASING."""

    def test_pv_sum_is_power_measurement(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyPvSumSensor(coordinator, entry)
        assert sensor._attr_device_class == SensorDeviceClass.POWER
        assert sensor._attr_native_unit_of_measurement == UnitOfPower.WATT
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT

    def test_fc_sum_is_power_measurement(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyFcSumSensor(coordinator, entry)
        assert sensor._attr_device_class == SensorDeviceClass.POWER
        assert sensor._attr_native_unit_of_measurement == UnitOfPower.WATT
        assert sensor._attr_state_class == SensorStateClass.MEASUREMENT

    def test_fc_day_sum_is_energy_total(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyFcDaySumSensor(coordinator, entry)
        assert sensor._attr_device_class == SensorDeviceClass.ENERGY
        assert sensor._attr_native_unit_of_measurement == UnitOfEnergy.WATT_HOUR
        assert sensor._attr_state_class == SensorStateClass.TOTAL

    def test_fc_remaining_today_is_energy_total(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyFcRemainingTodaySensor(coordinator, entry)
        assert sensor._attr_device_class == SensorDeviceClass.ENERGY
        assert sensor._attr_native_unit_of_measurement == UnitOfEnergy.WATT_HOUR
        assert sensor._attr_state_class == SensorStateClass.TOTAL

    def test_pv_energy_integral_is_energy_total_increasing(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyPvEnergyIntegralSensor(coordinator, entry)
        assert sensor._attr_device_class == SensorDeviceClass.ENERGY
        assert sensor._attr_native_unit_of_measurement == UnitOfEnergy.WATT_HOUR
        assert sensor._attr_state_class == SensorStateClass.TOTAL_INCREASING

    def test_fc_energy_integral_is_energy_total_increasing(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyFcEnergyIntegralSensor(coordinator, entry)
        assert sensor._attr_device_class == SensorDeviceClass.ENERGY
        assert sensor._attr_native_unit_of_measurement == UnitOfEnergy.WATT_HOUR
        assert sensor._attr_state_class == SensorStateClass.TOTAL_INCREASING


class TestUniqueIds:
    """Every aggregate sensor's unique_id is entry-scoped (one per
    config entry, unlike `ShadyForecastSensor`'s per-string id)."""

    def test_unique_ids_are_distinct_and_entry_scoped(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensors = [
            ShadyPvSumSensor(coordinator, entry),
            ShadyFcSumSensor(coordinator, entry),
            ShadyFcDaySumSensor(coordinator, entry),
            ShadyFcRemainingTodaySensor(coordinator, entry),
            ShadyPvEnergyIntegralSensor(coordinator, entry),
            ShadyFcEnergyIntegralSensor(coordinator, entry),
        ]
        unique_ids = [s._attr_unique_id for s in sensors]

        assert len(set(unique_ids)) == 6  # all distinct
        assert all(entry.entry_id in uid for uid in unique_ids)
        assert all(uid.startswith(DOMAIN) for uid in unique_ids)


class TestPvSumSensorValue:
    """`ShadyPvSumSensor.native_value` — zero math of its own, reads
    `coordinator.pv_sum()` directly on every access."""

    def test_matches_coordinator_pv_sum_directly(self) -> None:
        coordinator, hass, entry = _make_coordinator()
        _set_state(hass, _ACTUAL_YIELD_ENTITY, state=321.5)
        sensor = ShadyPvSumSensor(coordinator, entry)

        assert sensor.native_value == coordinator.pv_sum() == 321.5

    def test_none_when_coordinator_pv_sum_is_none(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyPvSumSensor(coordinator, entry)

        assert sensor.native_value is None


class TestFcSumSensorValue:
    """`ShadyFcSumSensor.native_value` — reads `coordinator.fc_sum(now)`
    at the sensor's own clock, directly."""

    def test_matches_coordinator_fc_sum_directly(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        _push_forecast(coordinator, 0, _NOW, 456.0)
        sensor = ShadyFcSumSensor(coordinator, entry)
        sensor._now = lambda: _NOW

        assert sensor.native_value == coordinator.fc_sum(_NOW) == 456.0

    def test_none_when_slot_unpushed(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        sensor = ShadyFcSumSensor(coordinator, entry)
        sensor._now = lambda: _NOW

        assert sensor.native_value is None


class TestFcDaySumSensorValue:
    """`ShadyFcDaySumSensor` — state is `fc_day_energy_total`;
    `extra_state_attributes` exposes `fc_day_array`'s own two arrays,
    ISO-formatted for JSON-serializability."""

    def test_native_value_matches_coordinator_directly(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        _push_forecast(coordinator, 0, today_start, 600.0)
        sensor = ShadyFcDaySumSensor(coordinator, entry)
        sensor._now = lambda: _NOW

        assert sensor.native_value == coordinator.fc_day_energy_total(_NOW)
        assert sensor.native_value == 600.0 * 5 / 60

    def test_attributes_are_288_slot_arrays_matching_fc_day_array(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        slot = today_start + timedelta(hours=8)
        _push_forecast(coordinator, 0, slot, 250.0)
        sensor = ShadyFcDaySumSensor(coordinator, entry)
        sensor._now = lambda: _NOW

        attrs = sensor.extra_state_attributes
        expected_timestamps, expected_values = coordinator.fc_day_array(_NOW)

        assert set(attrs) == {"slot_timestamps", "slot_values"}
        assert len(attrs["slot_timestamps"]) == 288
        assert len(attrs["slot_values"]) == 288
        assert attrs["slot_timestamps"] == [ts.isoformat() for ts in expected_timestamps]
        assert attrs["slot_values"] == expected_values
        slot_index = int((slot - today_start) / timedelta(minutes=5))
        assert attrs["slot_values"][slot_index] == 250.0


class TestFcRemainingTodaySensorValue:
    """`ShadyFcRemainingTodaySensor` — pure post-processing of the same
    array `ShadyFcDaySumSensor` builds; excludes past slots."""

    def test_matches_coordinator_fc_remaining_energy_directly(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        past_slot = today_start + timedelta(hours=1)
        future_slot = today_start + timedelta(hours=12)
        _push_forecast(coordinator, 0, past_slot, 1000.0)
        _push_forecast(coordinator, 0, future_slot, 600.0)
        sensor = ShadyFcRemainingTodaySensor(coordinator, entry)
        sensor._now = lambda: _NOW

        assert sensor.native_value == coordinator.fc_remaining_energy(_NOW)
        assert sensor.native_value == 600.0 * 5 / 60


class TestEnergyIntegralSensorValues:
    """`ShadyPvEnergyIntegralSensor`/`ShadyFcEnergyIntegralSensor` —
    read `coordinator.cache.energy_total(...)` directly, zero math of
    their own; advancing the total is `coordinator.py`'s job
    (`_accumulate_energy`), not this sensor's."""

    def test_pv_energy_integral_matches_cache_directly(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        coordinator.cache.set_energy_total("pv", 1234.5)
        sensor = ShadyPvEnergyIntegralSensor(coordinator, entry)

        assert sensor.native_value == coordinator.cache.energy_total("pv") == 1234.5

    def test_fc_energy_integral_matches_cache_directly(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        coordinator.cache.set_energy_total("fc", 987.6)
        sensor = ShadyFcEnergyIntegralSensor(coordinator, entry)

        assert sensor.native_value == coordinator.cache.energy_total("fc") == 987.6

    def test_integrals_reflect_real_accumulation_not_just_manual_set(self) -> None:
        coordinator, _hass, entry = _make_coordinator()
        coordinator._accumulate_energy("pv", _NOW, 600.0)
        coordinator._accumulate_energy("pv", _NOW + timedelta(minutes=5), 600.0)
        sensor = ShadyPvEnergyIntegralSensor(coordinator, entry)

        assert sensor.native_value == 50.0  # 600W for 5 minutes = 50 Wh
