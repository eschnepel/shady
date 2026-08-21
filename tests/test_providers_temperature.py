from __future__ import annotations

from datetime import datetime

from ._module_loader import load_module


temperature = load_module("shady.providers.temperature", "providers/temperature.py")


def test_sensor_tier_fetches_history_and_has_no_forward_series():
    start = datetime(2026, 8, 21, 12, 0)
    raw = {start.isoformat(): 30, start.replace(minute=5).isoformat(): 31}

    provider = temperature.ShadyTemperatureProvider(
        "sensor.module_temp",
        "module",
        series_source=lambda entity_id, attribute: raw,
    )

    assert provider.identify() == "sensor.module_temp"
    assert provider.fetch(start, start.replace(minute=10)) == [
        (start, 30.0),
        (start.replace(minute=5), 31.0),
    ]
    assert provider.forward(start) is None


def test_weather_tier_uses_forecast_for_fetch_and_forward():
    start = datetime(2026, 8, 21, 12, 0)
    raw = [
        {"datetime": start.isoformat(), "value": 20},
        {"datetime": start.replace(minute=5).isoformat(), "value": 21},
    ]

    provider = temperature.ShadyTemperatureProvider(
        "weather.openweather",
        "weather",
        series_source=lambda entity_id, attribute: raw,
    )

    assert provider.fetch(start, start.replace(minute=10)) == [
        (start, 20.0),
        (start.replace(minute=5), 21.0),
    ]
    assert provider.forward(start) == [
        (start, 20.0),
        (start.replace(minute=5), 21.0),
    ]
