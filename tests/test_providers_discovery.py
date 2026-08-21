from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._module_loader import load_module


discovery = load_module("shady.providers.discovery", "providers/discovery.py")


@dataclass
class _Entity:
    entity_id: str
    state: str
    attributes: dict[str, object]


class _States:
    def __init__(self, entities: list[_Entity]) -> None:
        self._entities = entities

    def async_all(self) -> list[_Entity]:
        return list(self._entities)

    def get(self, entity_id: str) -> _Entity | None:
        for entity in self._entities:
            if entity.entity_id == entity_id:
                return entity
        return None


class _Hass:
    def __init__(self, entities: list[_Entity]) -> None:
        self.states = _States(entities)


def test_discovery_scores_sensor_and_weather_candidates():
    start = datetime(2026, 8, 21, 12, 0)
    entities = [
        _Entity(
            "sensor.forecast_solar",
            "ok",
            {"wh_period": {start.isoformat(): 10, start.replace(minute=5).isoformat(): 20}},
        ),
        _Entity(
            "sensor.solcast",
            "ok",
            {"detailedForecast": [{"start": start.isoformat(), "pv_estimate": 1.2}]},
        ),
        _Entity(
            "weather.sunny",
            "ok",
            {"forecast": [{"datetime": start.isoformat(), "sunshine_duration": 15}]},
        ),
        _Entity(
            "weather.cloudy",
            "ok",
            {"forecast": [{"datetime": start.isoformat(), "cloud_coverage": 25}]},
        ),
        _Entity("sensor.irrelevant", "ok", {"value": 1}),
    ]

    candidates = discovery.discover_candidates(_Hass(entities))

    assert any(candidate.entity_id == "sensor.forecast_solar" for candidate in candidates)
    assert any(candidate.entity_id == "sensor.solcast" for candidate in candidates)
    assert any(candidate.label == "sunshine duration" for candidate in candidates)
    assert any(candidate.label == "cloud coverage (inverted)" for candidate in candidates)
    assert all(candidate.entity_id != "sensor.irrelevant" for candidate in candidates)
    assert candidates == discovery.rank_candidates(candidates)


def test_baseline_provider_uses_shared_normalization_for_fetch_and_forward():
    start = datetime(2026, 8, 21, 12, 0)
    raw = {start.isoformat(): 10, start.replace(minute=5).isoformat(): 20}

    provider = discovery.ShadyBaselineForecastProvider(
        "sensor.forecast_solar",
        "wh_period",
        series_source=lambda entity_id, attribute: raw,
    )

    assert provider.identify() == "sensor.forecast_solar"
    assert provider.fetch(start, start.replace(minute=10)) == [
        (start, 10.0),
        (start.replace(minute=5), 20.0),
    ]
    assert provider.forward(start) == [
        (start, 10.0),
        (start.replace(minute=5), 20.0),
    ]
