from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable

from ._module_loader import load_module


sensor_module = load_module("shady.sensor", "sensor.py")
switch_module = load_module("shady.switch", "switch.py")


@dataclass
class _FakeCoordinator:
    diagnostics_enabled: bool = False

    def __post_init__(self) -> None:
        self.listeners: list[Callable[[], None]] = []
        self.diagnostics_snapshot = {
            "string-1": {"state": "disabled"},
        }
        self.diagnostics_sum_snapshot = {"state": "disabled"}

    def async_add_listener(self, listener):
        self.listeners.append(listener)

        def _remove():
            self.listeners.remove(listener)

        return _remove

    def set_diagnostics_enabled(self, enabled: bool) -> None:
        self.diagnostics_enabled = enabled

    async def async_refresh_diagnostics(self, now=None) -> None:
        if self.diagnostics_enabled:
            self.diagnostics_snapshot["string-1"] = {
                "state": "enabled",
                "diagnosed_slot": 144,
                "selected_timestamp": datetime(2026, 8, 21, 12, 0).isoformat(),
                "series": [{"name": "slot pool", "data": [{"x": 1.0, "y": 2.0}]}],
                "accuracy": {"wls2": 75.0},
            }
            self.diagnostics_sum_snapshot = {
                "state": "enabled",
                "diagnosed_slot": 144,
                "selected_timestamp": datetime(2026, 8, 21, 12, 0).isoformat(),
                "series": [{"name": "selected wls2", "data": [{"x": 0.0, "y": 2.0}]}],
                "accuracy": {"wls2": 75.0},
            }
        else:
            self.diagnostics_snapshot["string-1"] = {"state": "disabled"}
            self.diagnostics_sum_snapshot = {"state": "disabled"}

    def get_diagnostic_snapshot(self, string_id: str):
        return dict(self.diagnostics_snapshot[string_id])

    def get_diagnostic_sum_snapshot(self):
        return dict(self.diagnostics_sum_snapshot)


def test_diagnostics_sensor_hides_series_when_disabled():
    coordinator = _FakeCoordinator()
    entry = type("Entry", (), {"entry_id": "entry-1", "title": "Shady", "data": {"strings": [{"id": "string-1", "name": "Roof"}]}})()
    sensor = sensor_module.ShadyDiagnosticsSensor(coordinator, {"id": "string-1", "name": "Roof"})

    assert sensor.native_value == "disabled"
    assert sensor.extra_state_attributes == {}


def test_diagnostics_switch_and_sensor_expose_enabled_snapshot():
    coordinator = _FakeCoordinator()
    entry = type("Entry", (), {"entry_id": "entry-1", "title": "Shady"})()
    switch = switch_module.ShadyDiagnosticsSwitch(coordinator, entry)
    sensor = sensor_module.ShadyDiagnosticsSensor(coordinator, {"id": "string-1", "name": "Roof"})
    sum_sensor = sensor_module.ShadyDiagnosticsSumSensor(coordinator, entry)

    asyncio.run(switch.async_turn_on())

    assert switch.is_on is True
    assert sensor.native_value == "enabled"
    assert sensor.extra_state_attributes["series"][0]["name"] == "slot pool"
    assert sum_sensor.native_value == "enabled"
    assert sum_sensor.extra_state_attributes["accuracy"]["wls2"] == 75.0
