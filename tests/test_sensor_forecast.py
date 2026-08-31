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
    .Store` — backed by `hass.store_data` (see `FakeHomeAssistant`),
    matching `test_coordinator.py`'s own copy of this stub."""

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

    # -- `homeassistant.components.sensor` (this file's own addition) ---

    class SensorEntity:
        """Real (non-Mock) stand-in for the slice `sensor.py` actually
        uses: nothing beyond being a plain base class carrying
        `_attr_*` class/instance attributes — HA's own property
        descriptors (`native_value` etc. falling back to `_attr_*`) are
        not needed here since `ShadyForecastSensor` overrides every
        relevant property itself."""

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

# Same `shady` top-level package trick `test_coordinator.py` established
# (see its own comment) — required for coordinator.py's `from .regression
# import kernel, linear, wls2, wls3` package-level import to resolve.
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
_const_mod = _load("const.py", "shady.const")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")
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
    config-entry-level aggregate sensors (ADR-005, TASK-0012)."""

    def test_one_sensor_per_configured_string_plus_six_aggregates(self) -> None:
        coordinator, hass, entry = _make_ready_coordinator()
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        add_entities = _FakeAddEntities()

        _run(async_setup_entry(hass, entry, add_entities))

        assert len(add_entities.added) == 7
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
