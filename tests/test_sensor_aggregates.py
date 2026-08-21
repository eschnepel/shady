from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable

from ._module_loader import load_module


sensor_module = load_module("shady.sensor", "sensor.py")


@dataclass
class _FakeCache:
    totals: dict[str, float]

    def get_integral_total(self, key: str) -> float:
        return self.totals[key]


class _FakeCoordinator:
    def __init__(self) -> None:
        self.aggregate_snapshot = {
            "pv_sum": 1200.0,
            "fc_sum": 1100.0,
            "fc_day_timestamps": [datetime(2026, 8, 21, 0, 0), datetime(2026, 8, 21, 0, 5)],
            "fc_day_values": [10.0, 20.0],
            "fc_day_energy": 1.25,
            "fc_remaining_today": 0.75,
            "pv_energy": 6.5,
            "fc_energy": 6.25,
        }
        self.cache = _FakeCache({"pv_energy": 6.5, "fc_energy": 6.25})
        self._listeners: list[Callable[[], None]] = []
        self.forecasts = {"string-1": [(datetime(2026, 8, 21, 12, 0), 42.0)]}
        self.intraday_snapshots = {"string-1": {"intraday_ratio": 1.05, "intraday_state": "ramping"}}

    def async_add_listener(self, listener):
        self._listeners.append(listener)

        def _remove():
            self._listeners.remove(listener)

        return _remove

    def get_forecast_series(self, string_id: str):
        return self.forecasts[string_id]

    def get_aggregate_value(self, key: str):
        return self.aggregate_snapshot[key]

    def get_intraday_snapshot(self, string_id: str):
        return self.intraday_snapshots[string_id]


def test_aggregate_sensors_read_from_coordinator():
    coordinator = _FakeCoordinator()
    entry = type("Entry", (), {"entry_id": "entry-1", "title": "Shady", "data": {"strings": [{"id": "string-1", "name": "Roof"}]}})()

    pv_sum = sensor_module.ShadyPvSumSensor(coordinator, entry)
    fc_sum = sensor_module.ShadyFcSumSensor(coordinator, entry)
    fc_day = sensor_module.ShadyFcDaySumSensor(coordinator, entry)
    fc_remaining = sensor_module.ShadyFcRemainingTodaySensor(coordinator, entry)
    pv_energy = sensor_module.ShadyPvEnergyIntegralSensor(coordinator, entry)
    fc_energy = sensor_module.ShadyFcEnergyIntegralSensor(coordinator, entry)

    assert pv_sum.native_value == 1200.0
    assert fc_sum.native_value == 1100.0
    assert fc_day.native_value == 1.25
    assert fc_day.extra_state_attributes["slot_values"] == [10.0, 20.0]
    assert fc_remaining.native_value == 0.75
    assert pv_energy.native_value == 6.5
    assert fc_energy.native_value == 6.25


def test_aggregate_sensors_notify_on_coordinator_update(monkeypatch):
    coordinator = _FakeCoordinator()
    entry = type("Entry", (), {"entry_id": "entry-1", "title": "Shady", "data": {"strings": [{"id": "string-1", "name": "Roof"}]}})()
    sensor = sensor_module.ShadyPvSumSensor(coordinator, entry)
    writes: list[bool] = []
    monkeypatch.setattr(sensor, "async_write_ha_state", lambda: writes.append(True))

    asyncio.run(sensor.async_added_to_hass())
    coordinator._listeners[0]()  # noqa: SLF001

    assert writes == [True]


def test_forecast_sensor_exposes_intraday_attributes():
    coordinator = _FakeCoordinator()
    entry = type("Entry", (), {"entry_id": "entry-1", "title": "Shady", "data": {"strings": [{"id": "string-1", "name": "Roof"}]}})()
    sensor = sensor_module.ShadyForecastSensor(coordinator, {"id": "string-1", "name": "Roof"})

    attrs = sensor.extra_state_attributes

    assert attrs["intraday_ratio"] == 1.05
    assert attrs["intraday_state"] == "ramping"
