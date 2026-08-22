"""Tests for `providers/temperature.py` against a real `hass` fixture
(ADR-000 §6's exception — see `tests/test_providers_discovery.py` for the
shared rationale and fixture shape; duplicated here per that file's own
Delivered Artifacts note rather than introducing a cross-test-file import).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load("providers/base.py", "shady.providers.base")
_temperature_mod = _load("providers/temperature.py", "shady.providers.temperature")

if TYPE_CHECKING:
    from shady.providers.temperature import (
        TemperatureProvider as TemperatureProvider,  # noqa: PLC0414
    )
else:
    TemperatureProvider = _temperature_mod.TemperatureProvider


class FakeState:
    """A real (non-Mock) stand-in for `homeassistant.core.State`."""

    def __init__(self, entity_id: str, state: str, attributes: dict[str, object]) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes


class FakeStates:
    """A real (non-Mock) stand-in for `homeassistant.core.StateMachine`,
    implementing only `get(entity_id)` (this module never calls
    `async_all`, unlike `providers/discovery.py`)."""

    def __init__(self, states: list[FakeState]) -> None:
        self._states = states

    def get(self, entity_id: str) -> FakeState | None:
        for state in self._states:
            if state.entity_id == entity_id:
                return state
        return None


class FakeHomeAssistant:
    """A real (non-Mock) stand-in for `homeassistant.core.HomeAssistant`."""

    def __init__(self, states: list[FakeState]) -> None:
        self.states = FakeStates(states)


_MODULE_SENSOR = FakeState("sensor.string_a_cell_temp", "42.3", {"device_class": "temperature"})
_AMBIENT_SENSOR = FakeState("sensor.garden_ambient_temp", "18.0", {"device_class": "temperature"})
_WEATHER_ENTITY = FakeState(
    "weather.dwd",
    "sunny",
    {
        "temperature": 12.5,
        "forecast": [
            {"datetime": "2026-01-01T10:00:00+00:00", "temperature": 15.0, "condition": "sunny"},
            {"datetime": "2026-01-01T10:05:00+00:00", "temperature": 15.4, "condition": "sunny"},
        ],
    },
)


class TestSensorTierFetch:
    """Given a config-selected sensor.* entity with device_class:
    temperature (module/cell or ambient tier), When fetch() is called for
    a past range, Then it returns that sensor's own reading with no
    discovery/scoring step (ADR-003b §1a)."""

    def test_module_sensor_reading_fills_every_slot(self) -> None:
        hass = FakeHomeAssistant([_MODULE_SENSOR])
        provider = TemperatureProvider(hass, "sensor.string_a_cell_temp", "sensor")
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [42.3, 42.3]

    def test_ambient_sensor_tier_uses_same_mechanism(self) -> None:
        """Module/cell and ambient are the same fetch mechanism here —
        the uplift formula distinguishing them lives in
        yield_correction.py, not this provider (ADR-003b §1a)."""
        hass = FakeHomeAssistant([_AMBIENT_SENSOR])
        provider = TemperatureProvider(hass, "sensor.garden_ambient_temp", "sensor")
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
        assert provider.fetch(start, end) == [18.0]

    def test_unresolvable_entity_returns_all_none(self) -> None:
        hass = FakeHomeAssistant([])
        provider = TemperatureProvider(hass, "sensor.missing", "sensor")
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [None, None]


class TestWeatherTierFetch:
    """Given a config-selected weather.* entity (weather-integration
    tier), When fetch() is called, Then it uses the entity's forecast
    attribute for the prediction-time case, falling back to the current
    condition reading elsewhere (ADR-003b §1a/§1b)."""

    def test_matching_forecast_slot_uses_forecast_value(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_ENTITY])
        provider = TemperatureProvider(hass, "weather.dwd", "weather")
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [15.0, 15.4]

    def test_slot_without_forecast_entry_falls_back_to_current_condition(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_ENTITY])
        provider = TemperatureProvider(hass, "weather.dwd", "weather")
        start = datetime(2026, 1, 1, 9, 55, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
        assert provider.fetch(start, end) == [12.5, 15.0]

    def test_unresolvable_entity_returns_all_none(self) -> None:
        hass = FakeHomeAssistant([])
        provider = TemperatureProvider(hass, "weather.missing", "weather")
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [None, None]


class TestForwardByTier:
    """Given a sensor.*-tier instance, forward(now) returns None (no
    forecasting concept, ADR-003c Context). Given a weather.*-tier
    instance, forward(now) returns a genuinely forward-looking series."""

    def test_sensor_tier_forward_is_none(self) -> None:
        hass = FakeHomeAssistant([_MODULE_SENSOR])
        provider = TemperatureProvider(hass, "sensor.string_a_cell_temp", "sensor")
        assert provider.forward(datetime(2026, 1, 1, 10, 0, tzinfo=UTC)) is None

    def test_weather_tier_forward_is_forward_looking(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_ENTITY])
        provider = TemperatureProvider(hass, "weather.dwd", "weather")
        forwarded = provider.forward(datetime(2026, 1, 1, 10, 0, tzinfo=UTC))
        assert forwarded == [
            (datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 15.0),
            (datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 15.4),
        ]

    def test_weather_tier_forward_filters_to_now_or_later(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_ENTITY])
        provider = TemperatureProvider(hass, "weather.dwd", "weather")
        forwarded = provider.forward(datetime(2026, 1, 1, 10, 5, tzinfo=UTC))
        assert forwarded == [(datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 15.4)]

    def test_weather_tier_forward_unresolvable_entity_is_none(self) -> None:
        hass = FakeHomeAssistant([])
        provider = TemperatureProvider(hass, "weather.missing", "weather")
        assert provider.forward(datetime(2026, 1, 1, 10, 0, tzinfo=UTC)) is None


class TestIdentifyByTier:
    """Given identify() is called on any tier, When resolved, Then it
    returns exactly the config-flow-selected entity with no ranking
    step (ADR-003b §1a: "a plain entity selector is sufficient")."""

    def test_sensor_tier_identifies_with_no_attribute(self) -> None:
        hass = FakeHomeAssistant([_MODULE_SENSOR])
        provider = TemperatureProvider(hass, "sensor.string_a_cell_temp", "sensor")
        assert provider.identify() == _temperature_mod.EntityRef("sensor.string_a_cell_temp", None)

    def test_weather_tier_identifies_with_temperature_attribute(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_ENTITY])
        provider = TemperatureProvider(hass, "weather.dwd", "weather")
        assert provider.identify() == _temperature_mod.EntityRef("weather.dwd", "temperature")
