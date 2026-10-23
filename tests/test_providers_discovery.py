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

import sys
from datetime import UTC, datetime
from types import ModuleType
from typing import TYPE_CHECKING, Any

from tests.support import _load, _run


class FakeEntityRegistryEntry:
    """A real (non-Mock) stand-in for one `homeassistant.helpers.
    entity_registry.RegistryEntry` — just the four attributes
    `resolve_forecast_solar_history_entity` (ADR-009 §1c Amendment,
    `TASK-0034`) reads. `entity_id` deliberately carries no
    config-entry-scoping prefix or suffix by default (`sensor.
    power_production_now`, confirmed against a live deployment), matching
    Forecast.Solar's own real-world behavior and the reason this
    resolution matches on `translation_key`, never a guessed `entity_id`/
    `unique_id` composition."""

    def __init__(
        self,
        entity_id: str,
        config_entry_id: str,
        translation_key: str | None = "power_production_now",
        domain: str = "sensor",
    ) -> None:
        self.entity_id = entity_id
        self.config_entry_id = config_entry_id
        self.translation_key = translation_key
        self.domain = domain


class FakeEntityRegistry:
    """A real (non-Mock) stand-in for `homeassistant.helpers.
    entity_registry.EntityRegistry` — holds entries queried through the
    module-level `async_entries_for_config_entry(registry, config_entry_id)`
    below, the one function `resolve_forecast_solar_history_entity`
    (ADR-009 §1c Amendment) calls."""

    def __init__(self, entries: list[FakeEntityRegistryEntry] | None = None) -> None:
        self.entries = list(entries or [])


def _install_fake_entity_registry_module() -> None:
    """Register a hand-written `homeassistant.helpers.entity_registry`
    stand-in into `sys.modules` before `providers/discovery.py` is
    loaded below, so its guarded `try: from homeassistant.helpers import
    entity_registry ...` (ADR-009 §1c Amendment) exercises the real
    resolution logic in this test file, not only its `_entity_registry
    is None` fallback branch. Mirrors `tests/support_ha.py`'s own
    `_install_ha_stub()` pattern for other `homeassistant.helpers.*`
    submodules (`device_registry`, `storage`, …), scoped to just this one
    file rather than the shared file, since no other test file needs
    real entity-registry resolution logic exercised (`tests/test_
    coordinator.py`/`tests/test_config_flow.py` only need this module to
    *load*, which the guarded import's `except ImportError` fallback
    already handles without any stub at all).
    """
    ha_module = sys.modules.setdefault("homeassistant", ModuleType("homeassistant"))
    ha_helpers = sys.modules.get("homeassistant.helpers")
    if ha_helpers is None:
        ha_helpers = ModuleType("homeassistant.helpers")
        sys.modules["homeassistant.helpers"] = ha_helpers
        ha_module.helpers = ha_helpers  # type: ignore[attr-defined]
    ha_entity_registry = ModuleType("homeassistant.helpers.entity_registry")

    def _async_get(hass: Any) -> FakeEntityRegistry | None:
        return getattr(hass, "entity_registry", None)

    def _async_entries_for_config_entry(
        registry: FakeEntityRegistry, config_entry_id: str
    ) -> list[FakeEntityRegistryEntry]:
        return [entry for entry in registry.entries if entry.config_entry_id == config_entry_id]

    ha_entity_registry.async_get = _async_get  # type: ignore[attr-defined]
    ha_entity_registry.async_entries_for_config_entry = _async_entries_for_config_entry  # type: ignore[attr-defined]
    sys.modules["homeassistant.helpers.entity_registry"] = ha_entity_registry
    ha_helpers.entity_registry = ha_entity_registry  # type: ignore[attr-defined]


_install_fake_entity_registry_module()

_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_load("regression/base.py", "shady.regression.base")
_load("const.py", "shady.const")
_load("cache.py", "shady.cache")
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


class FakeServices:
    """A real (non-Mock) stand-in for `hass.services` — just enough of
    `weather.get_forecasts` for `_scan_weather_domain` (ADR-009
    Amendment) and `forecast_solar.get_forecast` for
    `_scan_forecast_solar_domain` (same amendment, "Forecast.Solar
    polling sourcing"). Defaults to looking each sampled weather
    entity's forecast payload straight back up from its own state's
    `forecast` attribute (the same payload the pre-2024.4 fixtures
    already carried), but `weather_overrides`/`weather_raises`/
    `forecast_solar_responses`/`forecast_solar_raises` let a test
    exercise the malformed-response/service-failure branches directly,
    a real coroutine raising or returning an odd shape rather than a
    `Mock(side_effect=...)`."""

    def __init__(self, states: FakeStates) -> None:
        self._states = states
        # entity_id -> raw `weather.get_forecasts` response, bypassing
        # the state-attribute-derived default entirely.
        self.weather_overrides: dict[str, object] = {}
        # entity_ids for which `weather.get_forecasts` raises instead of
        # returning (ADR-000 §8's "a misbehaving integration must not
        # abort discovery").
        self.weather_raises: set[str] = set()
        # config_entry_id -> raw `forecast_solar.get_forecast` response.
        self.forecast_solar_responses: dict[str, object] = {}
        # config_entry_ids for which `forecast_solar.get_forecast` raises.
        self.forecast_solar_raises: set[str] = set()

    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, object] | None = None,
        *,
        target: dict[str, object] | None = None,
        blocking: bool = False,
        return_response: bool = False,
    ) -> object:
        if domain == "weather" and service == "get_forecasts":
            entity_id = (target or {}).get("entity_id")
            if entity_id in self.weather_raises:
                raise RuntimeError("synthetic weather.get_forecasts failure")
            if entity_id in self.weather_overrides:
                return self.weather_overrides[entity_id]
            state = self._states.get(entity_id) if isinstance(entity_id, str) else None
            forecast = state.attributes.get("forecast") if state is not None else None
            if forecast is None:
                return {}
            return {entity_id: {"forecast": forecast}}
        if domain == "forecast_solar" and service == "get_forecast":
            config_entry_id = (service_data or {}).get("config_entry")
            if config_entry_id in self.forecast_solar_raises:
                raise RuntimeError("synthetic forecast_solar.get_forecast failure")
            if not isinstance(config_entry_id, str):
                return None
            return self.forecast_solar_responses.get(config_entry_id)
        return {}


class _FakeLoadedConfigEntry:
    """A real (non-Mock) stand-in for the one attribute
    `_scan_forecast_solar_domain` reads off a loaded config entry."""

    def __init__(self, entry_id: str) -> None:
        self.entry_id = entry_id


class FakeConfigEntries:
    """A real (non-Mock) stand-in for `hass.config_entries` — just
    `async_loaded_entries(domain)`, the one method
    `_scan_forecast_solar_domain` calls."""

    def __init__(self) -> None:
        self._loaded: dict[str, list[str]] = {}

    def add_loaded_entry(self, domain: str, entry_id: str) -> None:
        self._loaded.setdefault(domain, []).append(entry_id)

    def async_loaded_entries(self, domain: str) -> list[_FakeLoadedConfigEntry]:
        return [_FakeLoadedConfigEntry(entry_id) for entry_id in self._loaded.get(domain, [])]


class FakeHomeAssistant:
    """A real (non-Mock) stand-in for `homeassistant.core.HomeAssistant`,
    holding the `.states`/`.services` attributes both provider modules
    touch (`.services` since ADR-009 Amendment's `weather.get_forecasts`
    /`forecast_solar.get_forecast` sourcing). `.config_entries` is left
    unset unless a test opts in via `add_forecast_solar_entry` — mirrors
    `_scan_forecast_solar_domain`'s own `getattr(hass, "config_entries",
    None)` defensive fallback (ADR-000 §8) for a `hass` that doesn't
    model config entries at all. `.entity_registry` (ADR-009 §1c
    Amendment, `TASK-0034`) is likewise left unset unless a test passes
    one in — mirrors `_install_fake_entity_registry_module`'s own
    `async_get`, which reads exactly this attribute, defaulting to
    `None` (registry unavailable) the same way. `.data` (`TASK-0036`,
    the service-response cache's `hass.data`-held singleton) follows the
    same opt-in convention: unset by default, so every test predating
    the cache keeps exercising `async_get_service_response_cache`'s own
    "no `.data` at all" fallback unchanged; a test exercising the cache
    itself passes `data={}`."""

    def __init__(
        self,
        states: list[FakeState],
        entity_registry: FakeEntityRegistry | None = None,
        data: dict[str, object] | None = None,
    ) -> None:
        self.states = FakeStates(states)
        self.services = FakeServices(self.states)
        if entity_registry is not None:
            self.entity_registry = entity_registry
        if data is not None:
            self.data = data

    def add_forecast_solar_entry(self, entry_id: str) -> None:
        if not hasattr(self, "config_entries"):
            self.config_entries = FakeConfigEntries()
        self.config_entries.add_loaded_entry("forecast_solar", entry_id)


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
        # `supported_features=2` (`WeatherEntityFeature.FORECAST_HOURLY`,
        # ADR-009 Amendment) — `_scan_weather_domain` skips any entity
        # lacking this, since `weather.get_forecasts` would just error.
        "supported_features": 2,
        "forecast": [
            {"datetime": "2026-01-01T10:00:00+00:00", "sunshine_duration": 900.0},
            {"datetime": "2026-01-01T11:00:00+00:00", "sunshine_duration": 1200.0},
        ],
    },
)
_WEATHER_CLOUD = FakeState(
    "weather.openweathermap",
    {
        "supported_features": 2,
        "forecast": [
            {"datetime": "2026-01-01T10:00:00+00:00", "cloud_coverage": 40.0},
        ],
    },
)


class TestDiscoverSensorShapes:
    """Given a sensor.* entity exposing a {timestamp: number}-shaped
    attribute and one exposing a list-of-dicts shape, both are recognized
    and scored as candidates (ADR-009 §1)."""

    def test_dict_shaped_sensor_recognized(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert len(candidates) == 1
        assert candidates[0].entity_id == "sensor.forecast_solar_estimate"
        assert candidates[0].attribute == "wh_period"
        assert candidates[0].shape == "sensor_dict"

    def test_list_shaped_sensor_recognized(self) -> None:
        hass = FakeHomeAssistant([_SOLCAST_LIKE])
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert len(candidates) == 1
        assert candidates[0].entity_id == "sensor.solcast_pv_forecast"
        assert candidates[0].attribute == "detailedForecast"
        assert candidates[0].shape == "sensor_list"

    def test_both_shapes_recognized_together(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE, _SOLCAST_LIKE])
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        shapes = {c.shape for c in candidates}
        assert shapes == {"sensor_dict", "sensor_list"}
        assert len(candidates) == 2


class TestDiscoverWeatherShapes:
    """Given a weather.* entity exposing sunshine_duration and another
    exposing cloud_coverage, both are recognized, the cloud-coverage one
    is inverted, and both are labeled distinctly (ADR-009 §1/§3)."""

    def test_sunshine_and_cloud_both_recognized_and_labeled_distinctly(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE, _WEATHER_CLOUD])
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
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
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []

    def test_mixed_entities_only_real_candidates_surfaced(self) -> None:
        hass = FakeHomeAssistant([_NO_FORECAST_SHAPE, _FORECAST_SOLAR_LIKE])
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
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


class TestBaselineCandidateForecastType:
    """Given a `BaselineCandidate`, its `forecast_type` is `"hourly"` for
    either `weather.*` shape (the one granularity ADR-009 Amendment ever
    subscribes to) and `None` for every other shape — `sensor_dict`/
    `sensor_list` have nothing to subscribe to, and `forecast_solar`
    polls a service instead (ADR-009 Amendment, "Forecast.Solar polling
    sourcing")."""

    def test_weather_shaped_candidate_reports_hourly(self) -> None:
        candidate = _discovery_mod._build_candidate(
            "weather.dwd", "sunshine_duration", "weather_sunshine"
        )
        assert candidate.forecast_type == "hourly"

    def test_sensor_shaped_candidate_reports_none(self) -> None:
        candidate = _discovery_mod._build_candidate(
            "sensor.forecast_solar_estimate", "wh_period", "sensor_dict"
        )
        assert candidate.forecast_type is None

    def test_forecast_solar_candidate_reports_none(self) -> None:
        candidate = _discovery_mod._build_forecast_solar_candidate("entry123")
        assert candidate.forecast_type is None
        assert candidate.entity_id == "entry123"
        assert candidate.shape == "forecast_solar"
        assert candidate.score == _discovery_mod._FORECAST_SOLAR_SCORE


class TestWeatherEntryKeysHelper:
    """Given `_weather_entry_keys`' three "not actually a forecast list"
    guards (ADR-009 §1), each returns `None` rather than raising, so
    `_scan_weather_domain` can uniformly treat any of them as "skip this
    entity" (TASK note: these guards are Solcast's `resolve_list_series`
    equivalent, kept separate since `weather.get_forecasts`' response
    shape is sampled, not attribute-read)."""

    def test_string_value_is_not_a_forecast_list(self) -> None:
        assert _discovery_mod._weather_entry_keys("not a list") is None

    def test_empty_list_has_no_keys(self) -> None:
        assert _discovery_mod._weather_entry_keys([]) is None

    def test_non_sequence_value_is_not_a_forecast_list(self) -> None:
        assert _discovery_mod._weather_entry_keys({"not": "a list"}) is None

    def test_first_entry_not_a_mapping(self) -> None:
        assert _discovery_mod._weather_entry_keys(["not a dict"]) is None

    def test_well_formed_list_returns_lowercased_keys(self) -> None:
        raw = [{"Datetime": "2026-01-01T10:00:00+00:00", "Sunshine_Duration": 900.0}]
        assert _discovery_mod._weather_entry_keys(raw) == {"datetime", "sunshine_duration"}


class TestWeatherDomainScanEdgeCases:
    """Given `_scan_weather_domain`/`_sample_weather_forecast`'s
    ADR-000 §8 defensive branches (a service call failure, an entity
    lacking hourly support, or a malformed/empty response), none of
    them raise or surface a spurious candidate."""

    def test_entity_without_hourly_support_is_skipped(self) -> None:
        no_hourly_support = FakeState(
            "weather.no_hourly",
            {
                "supported_features": 0,
                "forecast": [
                    {"datetime": "2026-01-01T10:00:00+00:00", "sunshine_duration": 900.0},
                ],
            },
        )
        hass = FakeHomeAssistant([no_hourly_support])
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []

    def test_service_call_failure_is_swallowed(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE])
        hass.services.weather_raises.add("weather.dwd")
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []

    def test_empty_response_yields_no_candidate(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE])
        hass.services.weather_overrides["weather.dwd"] = {}
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []

    def test_response_entry_not_a_mapping_yields_no_candidate(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE])
        hass.services.weather_overrides["weather.dwd"] = {"weather.dwd": "not a mapping"}
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []

    def test_malformed_forecast_shape_yields_no_candidate(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE])
        hass.services.weather_overrides["weather.dwd"] = {"weather.dwd": {"forecast": ["oops"]}}
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []


class TestForecastSolarDomainScan:
    """Given `_scan_forecast_solar_domain`/`_sample_forecast_solar`
    (ADR-009 Amendment, "Forecast.Solar polling sourcing"): a loaded
    config entry with a usable `get_forecast` response yields one
    `forecast_solar`-shaped candidate keyed by that entry's own
    `entry_id`; a service failure or an unusable response yields none,
    without raising (ADR-000 §8)."""

    def test_loaded_entry_with_valid_response_yields_one_candidate(self) -> None:
        hass = FakeHomeAssistant([])
        hass.add_forecast_solar_entry("fs_entry_1")
        hass.services.forecast_solar_responses["fs_entry_1"] = {
            "wh_period": {"2026-01-01T10:00:00+00:00": 500.0}
        }
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.entity_id == "fs_entry_1"
        assert candidate.shape == "forecast_solar"
        assert candidate.score == _discovery_mod._FORECAST_SOLAR_SCORE

    def test_service_failure_yields_no_candidate(self) -> None:
        hass = FakeHomeAssistant([])
        hass.add_forecast_solar_entry("fs_entry_1")
        hass.services.forecast_solar_raises.add("fs_entry_1")
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []

    def test_unusable_response_yields_no_candidate(self) -> None:
        hass = FakeHomeAssistant([])
        hass.add_forecast_solar_entry("fs_entry_1")
        hass.services.forecast_solar_responses["fs_entry_1"] = {"watts": {}}
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert candidates == []


class TestServiceResponseCacheFallback:
    """`_sample_weather_forecast`/`_sample_forecast_solar` routed
    through the shared `ServiceResponseCache` (ADR-007 §1a, ADR-009 §4
    Amendment, `TASK-0036`) — a transient failure at discovery time no
    longer drops an otherwise-valid candidate. Uses `FakeHomeAssistant(
    data={})` throughout: without an explicit `.data` mapping (every
    other test in this file), `async_get_service_response_cache` returns
    `None` and every call below degrades to exactly today's "no
    fallback" behavior — covered by `test_a_cold_failing_sample_still_
    returns_none`/`TestWeatherDomainScanEdgeCases`/
    `TestForecastSolarDomainScan` above, all still passing unmodified."""

    def test_weather_sample_falls_back_to_the_last_good_response(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE], data={})
        first = _run(_discovery_mod._sample_weather_forecast(hass, "weather.dwd"))
        hass.services.weather_raises.add("weather.dwd")

        second = _run(_discovery_mod._sample_weather_forecast(hass, "weather.dwd"))

        assert first == [
            {"datetime": "2026-01-01T10:00:00+00:00", "sunshine_duration": 900.0},
            {"datetime": "2026-01-01T11:00:00+00:00", "sunshine_duration": 1200.0},
        ]
        assert second == first

    def test_weather_sample_is_remembered_per_entity(self) -> None:
        """Two weather entities must not share one remembered response
        — the entity travels in `target=`, not `service_data`."""
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE, _WEATHER_CLOUD], data={})
        _run(_discovery_mod._sample_weather_forecast(hass, "weather.dwd"))
        hass.services.weather_raises.add("weather.openweathermap")

        result = _run(_discovery_mod._sample_weather_forecast(hass, "weather.openweathermap"))

        assert result is None

    def test_forecast_solar_sample_falls_back_to_the_last_good_response(self) -> None:
        hass = FakeHomeAssistant([], data={})
        hass.services.forecast_solar_responses["fs_entry_1"] = {
            "wh_period": {"2026-01-01T10:00:00+00:00": 500.0}
        }
        first = _run(_discovery_mod._sample_forecast_solar(hass, "fs_entry_1"))
        hass.services.forecast_solar_raises.add("fs_entry_1")

        second = _run(_discovery_mod._sample_forecast_solar(hass, "fs_entry_1"))

        assert first == {"wh_period": {"2026-01-01T10:00:00+00:00": 500.0}}
        assert second == first

    def test_a_cold_failing_sample_still_returns_none(self) -> None:
        hass = FakeHomeAssistant([_WEATHER_SUNSHINE], data={})
        hass.services.weather_raises.add("weather.dwd")
        hass.services.forecast_solar_raises.add("fs_entry_1")

        assert _run(_discovery_mod._sample_weather_forecast(hass, "weather.dwd")) is None
        assert _run(_discovery_mod._sample_forecast_solar(hass, "fs_entry_1")) is None

    def test_end_to_end_discovery_recovers_a_candidate_after_a_transient_failure(self) -> None:
        """The full `discover_baseline_candidates` path, not just the
        private sampler — a second discovery run (e.g. a user reopening
        the config flow) still finds the Forecast.Solar candidate even
        though its service call fails this time."""
        hass = FakeHomeAssistant([], data={})
        hass.add_forecast_solar_entry("fs_entry_1")
        hass.services.forecast_solar_responses["fs_entry_1"] = {
            "wh_period": {"2026-01-01T10:00:00+00:00": 500.0}
        }
        first_run = _run(_discovery_mod.discover_baseline_candidates(hass))
        hass.services.forecast_solar_raises.add("fs_entry_1")

        second_run = _run(_discovery_mod.discover_baseline_candidates(hass))

        assert len(first_run) == 1
        assert len(second_run) == 1
        assert second_run[0].entity_id == "fs_entry_1"


class TestForecastSolarHistoryEntityResolution:
    """Given a `forecast_solar` config entry, `_resolve_forecast_solar_
    history_entity`/`_scan_forecast_solar_domain` resolve that entry's
    own companion `power_production_now` sensor via the entity
    registry's own `(config_entry_id, domain, translation_key)` index
    (ADR-009 §1c Amendment, `TASK-0034`) — never by string-matching/
    guessing an `entity_id`, and never by composing a guessed
    `unique_id` either: the real `entity_id` carries no config-entry
    prefix/suffix at all (`sensor.power_production_now`, confirmed
    against a live deployment) — and degrade to `None` (never raising)
    whenever no registry entry is available (ADR-000 §8)."""

    def test_resolves_via_translation_key_within_the_config_entry(self) -> None:
        registry = FakeEntityRegistry(
            [FakeEntityRegistryEntry("sensor.power_production_now", "fs_entry_1")]
        )
        hass = FakeHomeAssistant([], entity_registry=registry)
        resolved = _discovery_mod.resolve_forecast_solar_history_entity(hass, "fs_entry_1")
        assert resolved == "sensor.power_production_now"

    def test_no_matching_entry_resolves_to_none(self) -> None:
        registry = FakeEntityRegistry([])
        hass = FakeHomeAssistant([], entity_registry=registry)
        resolved = _discovery_mod.resolve_forecast_solar_history_entity(hass, "fs_entry_1")
        assert resolved is None

    def test_registry_unavailable_resolves_to_none(self) -> None:
        hass = FakeHomeAssistant([])  # no `.entity_registry` attribute at all
        resolved = _discovery_mod.resolve_forecast_solar_history_entity(hass, "fs_entry_1")
        assert resolved is None

    def test_wrong_domain_entry_is_not_matched(self) -> None:
        registry = FakeEntityRegistry(
            [
                FakeEntityRegistryEntry(
                    "binary_sensor.power_production_now", "fs_entry_1", domain="binary_sensor"
                )
            ]
        )
        hass = FakeHomeAssistant([], entity_registry=registry)
        resolved = _discovery_mod.resolve_forecast_solar_history_entity(hass, "fs_entry_1")
        assert resolved is None

    def test_wrong_translation_key_is_not_matched(self) -> None:
        """A `sensor` domain entry on the right config entry, but for a
        different Forecast.Solar sensor entirely (e.g. "energy production
        today") — proves the match is on `translation_key`, not merely on
        "any sensor belonging to this config entry"."""
        registry = FakeEntityRegistry(
            [
                FakeEntityRegistryEntry(
                    "sensor.energy_production_today",
                    "fs_entry_1",
                    translation_key="energy_production_today",
                )
            ]
        )
        hass = FakeHomeAssistant([], entity_registry=registry)
        resolved = _discovery_mod.resolve_forecast_solar_history_entity(hass, "fs_entry_1")
        assert resolved is None

    def test_wrong_config_entry_id_is_not_matched(self) -> None:
        registry = FakeEntityRegistry(
            [FakeEntityRegistryEntry("sensor.power_production_now", "fs_entry_OTHER")]
        )
        hass = FakeHomeAssistant([], entity_registry=registry)
        resolved = _discovery_mod.resolve_forecast_solar_history_entity(hass, "fs_entry_1")
        assert resolved is None

    def test_renamed_entity_id_still_resolves(self) -> None:
        """A user is free to rename `entity_id` freely — the registry
        lookup keys on `config_entry_id`/`translation_key`, neither of
        which a rename touches."""
        registry = FakeEntityRegistry(
            [FakeEntityRegistryEntry("sensor.my_renamed_pv_sensor", "fs_entry_1")]
        )
        hass = FakeHomeAssistant([], entity_registry=registry)
        resolved = _discovery_mod.resolve_forecast_solar_history_entity(hass, "fs_entry_1")
        assert resolved == "sensor.my_renamed_pv_sensor"

    def test_build_forecast_solar_candidate_carries_history_entity_id(self) -> None:
        candidate = _discovery_mod._build_forecast_solar_candidate(
            "fs_entry_1", "sensor.power_production_now"
        )
        assert candidate.history_entity_id == "sensor.power_production_now"
        assert candidate.shape == "forecast_solar"

    def test_scan_forecast_solar_domain_wires_history_entity_id_through(self) -> None:
        registry = FakeEntityRegistry(
            [FakeEntityRegistryEntry("sensor.power_production_now", "fs_entry_1")]
        )
        hass = FakeHomeAssistant([], entity_registry=registry)
        hass.add_forecast_solar_entry("fs_entry_1")
        hass.services.forecast_solar_responses["fs_entry_1"] = {
            "wh_period": {"2026-01-01T10:00:00+00:00": 500.0}
        }
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert len(candidates) == 1
        assert candidates[0].history_entity_id == "sensor.power_production_now"

    def test_scan_forecast_solar_domain_no_registry_entry_leaves_history_entity_id_none(
        self,
    ) -> None:
        hass = FakeHomeAssistant([])  # no `.entity_registry` at all
        hass.add_forecast_solar_entry("fs_entry_1")
        hass.services.forecast_solar_responses["fs_entry_1"] = {
            "wh_period": {"2026-01-01T10:00:00+00:00": 500.0}
        }
        candidates = _run(_discovery_mod.discover_baseline_candidates(hass))
        assert len(candidates) == 1
        assert candidates[0].history_entity_id is None


class TestBaselineProviderPushSourcedShapes:
    """Given a `weather_sunshine`/`weather_cloud`/`forecast_solar`
    `BaselineProvider` instance (ADR-009 Amendment's "forecast
    subscription/polling sourcing"), it reads `_latest_forecast` (set
    only by `update_live_forecast()`, called by `coordinator.py`) rather
    than any `hass.states` attribute — `None` until the first push, the
    just-pushed value after."""

    def test_shape_and_forecast_type_for_weather_sunshine(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "weather.dwd", "sunshine_duration", "weather_sunshine")
        assert provider.shape == "weather_sunshine"
        assert provider.forecast_type == "hourly"

    def test_forecast_type_is_none_for_forecast_solar(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "fs_entry_1", "wh_period", "forecast_solar")
        assert provider.forecast_type is None

    def test_before_any_push_fetch_and_forward_see_no_data(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "weather.dwd", "sunshine_duration", "weather_sunshine")
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [None, None]
        assert provider.forward(datetime(2026, 1, 1, 10, 0, tzinfo=UTC)) is None

    def test_after_a_push_fetch_and_forward_reflect_it(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "weather.dwd", "sunshine_duration", "weather_sunshine")
        provider.update_live_forecast(
            [
                {"datetime": "2026-01-01T10:00:00+00:00", "sunshine_duration": 900.0},
                {"datetime": "2026-01-01T10:05:00+00:00", "sunshine_duration": 1200.0},
            ]
        )
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [900.0, 1200.0]
        assert provider.forward(datetime(2026, 1, 1, 10, 0, tzinfo=UTC)) == [
            (datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 900.0),
            (datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 1200.0),
        ]

    def test_forecast_solar_shaped_provider_reads_pushed_wh_period(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "fs_entry_1", "wh_period", "forecast_solar")
        provider.update_live_forecast(
            {
                "wh_period": {
                    "2026-01-01T10:00:00+00:00": 500.0,
                    "2026-01-01T10:05:00+00:00": 520.0,
                }
            }
        )
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 10, tzinfo=UTC)
        assert provider.fetch(start, end) == [500.0, 520.0]


class TestBaselineProviderHistoryEntityId:
    """Given a `BaselineProvider` constructed with/without a
    `history_entity_id` (ADR-009 §1c Amendment, `TASK-0034`),
    `.history_entity_id()` — the generic, optional `Provider` base-class
    method it overrides (ADR-012 §1/§2a Amendment) — reports it back
    exactly; the default (no fifth constructor argument) stays `None`,
    matching the base class's own default for every provider that
    doesn't override it with anything (ADR-012 §1)."""

    def test_default_is_none(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "fs_entry_1", "wh_period", "forecast_solar")
        assert provider.history_entity_id() is None

    def test_resolved_value_is_reported_back(self) -> None:
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(
            hass,
            "fs_entry_1",
            "wh_period",
            "forecast_solar",
            "sensor.power_production_now",
        )
        assert provider.history_entity_id() == "sensor.power_production_now"

    def test_fetch_and_forward_unaffected_by_history_entity_id(self) -> None:
        """ADR-012 §2a's own explicit claim: `history_entity_id()` never
        changes `fetch()`/`forward()`'s own behavior — only
        `coordinator.py`'s `_fetch_fn` dispatch reads it."""
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(
            hass,
            "fs_entry_1",
            "wh_period",
            "forecast_solar",
            "sensor.power_production_now",
        )
        provider.update_live_forecast({"wh_period": {"2026-01-01T10:00:00+00:00": 500.0}})
        start = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        end = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
        assert provider.fetch(start, end) == [500.0]

    def test_set_history_entity_id_updates_a_none_default(self) -> None:
        """`set_history_entity_id` (`TASK-0034-patch-1`) — the one
        post-construction mutation this field ever undergoes, used by
        `coordinator.py`'s startup self-heal retry when a discovery-time
        resolution that returned `None` succeeds on a later retry."""
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(hass, "fs_entry_1", "wh_period", "forecast_solar")
        assert provider.history_entity_id() is None

        provider.set_history_entity_id("sensor.power_production_now")

        assert provider.history_entity_id() == "sensor.power_production_now"

    def test_set_history_entity_id_can_replace_an_already_resolved_value(self) -> None:
        """Not restricted to the `None` → resolved direction only — the
        setter itself is a plain assignment; it is
        `coordinator.py`'s own `provider.history_entity_id() is not
        None: continue` guard, not this method, that keeps an
        already-resolved provider from ever being retried in practice."""
        hass = FakeHomeAssistant([])
        provider = BaselineProvider(
            hass, "fs_entry_1", "wh_period", "forecast_solar", "sensor.power_production_now"
        )

        provider.set_history_entity_id("sensor.power_production_now_renamed")

        assert provider.history_entity_id() == "sensor.power_production_now_renamed"
