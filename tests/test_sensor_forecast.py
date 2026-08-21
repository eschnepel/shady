from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable

from ._module_loader import load_module


sensor_module = load_module("shady.sensor", "sensor.py")


@dataclass
class _FakeCoordinator:
    series: list[tuple[datetime, float]]

    def __post_init__(self) -> None:
        self.listeners: list[Callable[[], None]] = []

    def get_forecast_series(self, string_id: str):
        return list(self.series)

    def get_forecast_value(self, string_id: str):
        return self.series[0][1] if self.series else None

    def get_intraday_snapshot(self, string_id: str):
        return {}

    def async_add_listener(self, listener):
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)


def test_forecast_sensor_reads_series_from_coordinator():
    timestamp = datetime(2026, 8, 21, 12, 0)
    coordinator = _FakeCoordinator([(timestamp, 42.0)])
    sensor = sensor_module.ShadyForecastSensor(
        coordinator,
        {
            "id": "string-1",
            "name": "Roof",
        },
    )

    assert sensor.native_value == 42.0
    assert sensor.available is True
    assert sensor.extra_state_attributes == {
        "forecast_timestamps": [timestamp.isoformat()],
        "forecast_values": [42.0],
        "intraday_ratio": None,
        "intraday_state": "off",
        "intraday_ramp_weight": 0.0,
        "values_raw": [],
        "intraday_blend_active": False,
    }


def test_forecast_sensor_registers_listener_and_writes_state(monkeypatch):
    coordinator = _FakeCoordinator([])
    sensor = sensor_module.ShadyForecastSensor(coordinator, {"id": "string-1", "name": "Roof"})
    writes: list[bool] = []
    monkeypatch.setattr(sensor, "async_write_ha_state", lambda: writes.append(True))

    asyncio.run(sensor.async_added_to_hass())
    coordinator.listeners[0]()

    assert writes == [True]
