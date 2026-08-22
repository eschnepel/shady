"""Tests for `providers/discovery.py` against a real `hass` fixture
(ADR-000 §6's exception for `providers/discovery.py`/`providers/temperature.py`
— both read `hass.states` directly by design, ADR-009 §4/ADR-012 §5).

`FakeHomeAssistant`/`FakeState` below are concrete, real Python objects
implementing exactly the small subset of the `homeassistant.core`
`HomeAssistant`/`State` surface these modules touch
(`hass.states.async_all(domain)`, `hass.states.get(entity_id)`,
`state.entity_id`/`state.attributes`) — not `unittest.mock.Mock()`
instances. This keeps the test environment `pytest`-only (no
`pytest-homeassistant-custom-component`, no real `homeassistant` package
needed), matching ADR-000 §6's stated rationale for file-path-loaded
tests, while still exercising real code paths against a real object
graph rather than an attribute-stubbing mock.
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
_load("providers/normalize.py", "shady.providers.normalize")
_discovery_mod = _load("providers/discovery.py", "shady.providers.discovery")

if TYPE_CHECKING:
    from shady.providers.discovery import BaselineProvider as BaselineProvider  # noqa: PLC0414
else:
    BaselineProvider = _discovery_mod.BaselineProvider


class FakeState:
    """A real (non-Mock) stand-in for `homeassistant.core.State`, holding
    exactly the two attributes `providers/discovery.py` reads."""

    def __init__(self, entity_id: str, attributes: dict[str, object]) -> None:
        self.entity_id = entity_id
        self.state = "unknown"
        self.attributes = attributes


class FakeStates:
    """A real (non-Mock) stand-in for `homeassistant.core.StateMachine`,
    implementing only `async_all(domain)` and `get(entity_id)`."""

    def __init__(self, states: list[FakeState]) -> None:
        self._states = states

    def async_all(self, domain: str | None = None) -> list[FakeState]:
        if domain is None:
            return list(self._states)
        return [s for s in self._states if s.entity_id.startswith(f"{domain}.")]

    def get(self, entity_id: str) -> FakeState | None:
        for state in self._states:
            if state.entity_id == entity_id:
                return state
        return None


class FakeHomeAssistant:
    """A real (non-Mock) stand-in for `homeassistant.core.HomeAssistant`,
    holding only the `.states` attribute both provider modules touch."""

    def __init__(self, states: list[FakeState]) -> None:
        self.states = FakeStates(states)


_FORECAST_SOLAR_LIKE = FakeState(
    "sensor.forecast_solar_estimate",
    {
        "wh_period": {
            "2026-01-01T10:00:00+00:00": 500.0,
            "2026-01-01T10:05:00+00:00": 520.0,
        }
    },
)
_SOLCAST_LIKE = FakeState(
    "sensor.solcast_pv_forecast",
    {
        "detailedForecast": [
            {"period_start": "2026-01-01T10:00:00+00:00", "pv_estimate": 1.2},
            {"period_start": "2026-01-01T10:30:00+00:00", "pv_estimate": 1.5},
        ]
    },
)
_NO_FORECAST_SHAPE = FakeState(
    "sensor.random_thing",
    {"friendly_name": "Random Thing", "unit_of_measurement": "kg"},
)
_WEATHER_SUNSHINE = FakeState(
    "weather.dwd",
    {
        "forecast": [
            {"datetime": "2026-01-01T10:00:00+00:00", "sunshine_duration": 900.0},
            {"datetime": "2026-01-01T11:00:00+00:00", "sunshine_duration": 1200.0},
        ]
    },
)
_WEATHER_CLOUD = FakeState(
    "weather.openweathermap",
    {
        "forecast": [
            {"datetime": "2026-01-01T10:00:00+00:00", "cloud_coverage": 40.0},
        ]
    },
)


class TestDiscoverSensorShapes:
    """Given a sensor.* entity exposing a {timestamp: number}-shaped
    attribute and one exposing a list-of-dicts shape, both are recognized
    and scored as candidates (ADR-009 §1)."""

    def test_dict_shaped_sensor_recognized(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        candidates = _discovery_mod.discover_baseline_candidates(hass)
        assert len(candidates) == 1
        assert candidates[0].entity_id == "sensor.forecast_solar_estimate"
        assert candidates[0].attribute == "wh_period"
        assert candidates[0].shape == "sensor_dict"

    def test_list_shaped_sensor_recognized(self) -> None:
        hass = FakeHomeAssistant([_SOLCAST_LIKE])
        candidates = _discovery_mod.discover_baseline_candidates(hass)
        assert len(candidates) == 1
        assert candidates[0].entity_id == "sensor.solcast_pv_forecast"
        assert candidates[0].attribute == "detailedForecast"
        assert candidates[0].shape == "sensor_list"

    def test_both_shapes_recognized_together(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE, _SOLCAST_LIKE])
        candidates = _discovery_mod.discover_baseline_candidates(hass)
        shapes = {c.shape for c in candidates}
        assert shapes == {"sensor_dict", "sensor_list"}
        assert len(candidates) == 2


class TestDiscoverWeatherShapes:
    """Given a weather.* entity exposing sunshine_duration and another
    exposing cloud_coverage, both are recognized, the cloud-coverage one
    is inverted, and both are labeled distinctly (ADR-009 §1/§3)."""

    def test_sunshine_and_cloud_both_recognized_and_labeled_distinctly(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE, _WEATHER_CLOUD])
        candidates = _discovery_mod.discover_baseline_candidates(hass)
        assert len(candidates) == 2

        by_entity = {c.entity_id: c for c in candidates}
        sunshine_candidate = by_entity["weather.dwd"]
        cloud_candidate = by_entity["weather.openweathermap"]

        assert sunshine_candidate.shape == "weather_sunshine"
        assert sunshine_candidate.label == "sunshine duration"
        assert cloud_candidate.shape == "weather_cloud"
        assert cloud_candidate.label == "cloud coverage (inverted)"
        assert sunshine_candidate.label != cloud_candidate.label

    def test_cloud_coverage_is_actually_inverted_when_normalized(self) -> None:
        raw = _WEATHER_CLOUD.attributes["forecast"]
        series = _discovery_mod.normalize_candidate_series("weather_cloud", raw)
        assert series == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 60.0)]


class TestNoFalsePositives:
    """Given an entity with none of the recognized attribute shapes, it
    is not surfaced as a candidate (ADR-009 §1)."""

    def test_unrelated_attributes_not_surfaced(self) -> None:
        hass = FakeHomeAssistant([_NO_FORECAST_SHAPE])
        candidates = _discovery_mod.discover_baseline_candidates(hass)
        assert candidates == []

    def test_mixed_entities_only_real_candidates_surfaced(self) -> None:
        hass = FakeHomeAssistant([_NO_FORECAST_SHAPE, _FORECAST_SOLAR_LIKE])
        candidates = _discovery_mod.discover_baseline_candidates(hass)
        assert len(candidates) == 1
        assert candidates[0].entity_id == "sensor.forecast_solar_estimate"


class TestBaselineProviderSharedMapping:
    """Given the base class's fetch()/forward() contract (TASK-0001),
    this provider's fetch() (past range) and forward() (live forward
    range) both go through the same canonical-series mapping function
    (ADR-012 §1)."""

    def test_fetch_and_forward_agree_on_underlying_values(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        provider = BaselineProvider(
            hass, "sensor.forecast_solar_estimate", "wh_period", "sensor_dict"
        )

        assert provider.identify() == _discovery_mod.EntityRef(
            "sensor.forecast_solar_estimate", "wh_period"
        )

        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        fetched = provider.fetch(start, end)
        assert fetched == [500.0, 520.0]

        forwarded = provider.forward(datetime(2026, 1, 1, 10, 0, tzinfo=UTC))
        assert forwarded == [
            (datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 500.0),
            (datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 520.0),
        ]

    def test_forward_filters_to_now_or_later(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        provider = BaselineProvider(
            hass, "sensor.forecast_solar_estimate", "wh_period", "sensor_dict"
        )
        forwarded = provider.forward(datetime(2026, 1, 1, 10, 5, tzinfo=UTC))
        assert forwarded == [(datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 520.0)]

    def test_fetch_returns_none_for_slots_with_no_data(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        provider = BaselineProvider(
            hass, "sensor.forecast_solar_estimate", "wh_period", "sensor_dict"
        )
        start = datetime(2026, 1, 1, 9, 55, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
        fetched = provider.fetch(start, end)
        assert fetched == [None, 500.0]

    def test_unresolvable_entity_fetch_returns_all_none(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "sensor.missing", "wh_period", "sensor_dict")
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [None, None]

    def test_unresolvable_entity_forward_returns_none(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "sensor.missing", "wh_period", "sensor_dict")
        assert provider.forward(datetime(2026, 1, 1, 10, 0, tzinfo=UTC)) is None
