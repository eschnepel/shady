"""Tests for `coordinator.py`'s weather-forecast-subscription push
(ADR-012 §4a) and Forecast.Solar polling push (ADR-012 §4b), neither
of which any other test file exercises: `test_coordinator.py`'s own
hand-written `homeassistant` stub deliberately never provides
`homeassistant.components.weather` (its own module docstring notes
this), so `coordinator.py`'s `try: from homeassistant.components.
weather.const import DATA_COMPONENT` always takes its `except
ImportError` fallback there, and `_register_weather_forecast_
subscriptions` always returns immediately via its own `WEATHER_DATA_
COMPONENT is None` guard.

Reuses `test_coordinator.py`'s already-loaded `shady.*` module chain
entirely (`from tests import test_coordinator as tc`, matching
`test_coordinator_intraday.py`/`test_coordinator_temperature_forecast
.py`'s own established reuse convention) rather than re-`_load`-ing
`providers/`/`regression/`/etc fresh — those files' own `sys.modules[
"shady.xxx"]` captures assume nothing re-registers those same dotted
names in between, so a second, independent reload here (this file's
own name sorts between `test_coordinator.py` and `test_coordinator_
temperature_forecast.py`) would otherwise leave whichever of those
files imports last holding a `FittedModel`/`_TemperatureResolution`
class object that `tc`'s own already-constructed `ShadyCoordinator`
instances don't actually subclass/return — an `isinstance()`/equality
mismatch, not an import error, so it would surface as confusing
downstream assertion failures rather than at the point of the actual
mistake. Only `coordinator.py` itself is reloaded a second time here
(under a private module name, `shady._coordinator_weather_push_test`,
never `shady.coordinator`), since this file's entire point is a second
load where the `homeassistant.components.weather.const` import
succeeds — everything that second load's own top-level code pulls in
via `from .regression import ...`/etc still resolves to `tc`'s own
already-registered, stable `shady.*` submodules.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

from tests import test_coordinator as tc
from tests.support import _load, _run
from tests.support_ha import FakeHomeAssistant

# `homeassistant.components.weather.const.DATA_COMPONENT` — the one
# stub `test_coordinator.py`'s own shared convention deliberately never
# provides (see this module's own docstring). A plain, unique
# `object()` is enough: real HA's own `HassKey` is just an opaque
# hashable token too, and `hass.data.get(...)` only ever needs
# identity/hash equality, never any real behavior. Extends `tc`'s
# already-installed stub tree in place (mirroring `test_button.py`'s
# own `_install_button_stub()` convention) rather than calling
# `_install_ha_stub()` again, which would otherwise replace `tc`'s own
# `homeassistant.config_entries`/etc with a functionally-identical but
# distinct set of stub objects.
_WEATHER_DATA_COMPONENT_KEY = object()
_ha_components = sys.modules["homeassistant.components"]
_ha_weather = ModuleType("homeassistant.components.weather")
_ha_weather_const = ModuleType("homeassistant.components.weather.const")
_ha_weather_const.DATA_COMPONENT = _WEATHER_DATA_COMPONENT_KEY  # type: ignore[attr-defined]
_ha_weather.const = _ha_weather_const  # type: ignore[attr-defined]
_ha_components.weather = _ha_weather  # type: ignore[attr-defined]
sys.modules["homeassistant.components.weather"] = _ha_weather
sys.modules["homeassistant.components.weather.const"] = _ha_weather_const

# A second, independent `coordinator.py` load, under a private module
# name (see module docstring) — every other `from .xxx import ...` it
# does resolves against `tc`'s own already-registered `shady.*`
# submodules, untouched here.
_discovery_mod = sys.modules["shady.providers.discovery"]
_coordinator_mod = _load("coordinator.py", "shady._coordinator_weather_push_test")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
BaselineProvider = _discovery_mod.BaselineProvider

# The import succeeded (this file's whole reason for being) — sanity-
# checked once, up front, so a future accidental regression back to
# the `except ImportError` fallback fails loudly and immediately,
# rather than as a confusing "why did every test below suddenly start
# no-op-ing" mystery.
assert _coordinator_mod.WEATHER_DATA_COMPONENT is _WEATHER_DATA_COMPONENT_KEY

# Reused straight from `tc` (identical fixture shape; only the
# `ShadyCoordinator` class this file constructs against differs) —
# this import's whole purpose, beyond running `tc`'s own module-level
# `shady.*` load first, is these names plus `_make_entry`/
# `_synthetic_wh_period` below.
_NOW = tc._NOW
_YESTERDAY = tc._YESTERDAY
_BASELINE_ENTITY = tc._BASELINE_ENTITY
_ACTUAL_YIELD_ENTITY = tc._ACTUAL_YIELD_ENTITY
_synthetic_wh_period = tc._synthetic_wh_period
_make_entry = tc._make_entry

# `ServiceResponseCache`'s expiry constant/key helper (ADR-007 §1a,
# `TASK-0036`) — fetched off the already-registered `shady.cache`
# module (loaded once via `tc`'s own module chain) rather than
# re-imported, matching this file's own "everything but `coordinator
# .py` itself resolves against `tc`'s already-registered `shady.*`
# submodules" convention.
_cache_mod = sys.modules["shady.cache"]
_SERVICE_RESPONSE_MAX_AGE = _cache_mod.SERVICE_RESPONSE_MAX_AGE


async def _construct_coordinator(hass: FakeHomeAssistant, entry: Any) -> Any:
    """Construction itself can schedule an immediate `hass.async_create_
    task(...)` call (a Forecast.Solar poll, or — once found — a weather
    forecast subscription's initial `async_update_listeners`), so it
    needs a running loop already, like every other `async_create_task`
    call site in this module."""
    coordinator = ShadyCoordinator(hass, entry)
    await hass.drain()
    return coordinator


class _FakeWeatherEntity:
    """Real (non-`Mock`) stand-in for the slice of a `WeatherEntity`
    `_register_weather_forecast_subscriptions`/`_make_forecast_listener`
    actually touch: `async_subscribe_forecast` (records the listener,
    returns an unsub) and `async_update_listeners` (records the
    requested forecast types)."""

    def __init__(self) -> None:
        self.subscribed_forecast_types: list[str] = []
        self.listeners: list[Any] = []
        self.unsubscribed = False
        self.update_calls: list[set[str]] = []

    def async_subscribe_forecast(self, forecast_type: str, listener: Any) -> Any:
        self.subscribed_forecast_types.append(forecast_type)
        self.listeners.append(listener)

        def _unsub() -> None:
            self.unsubscribed = True

        return _unsub

    async def async_update_listeners(self, types: set[str]) -> None:
        self.update_calls.append(set(types))


class _FakeWeatherComponent:
    """Real (non-`Mock`) stand-in for `hass.data[WEATHER_DATA_COMPONENT]`
    — just `get_entity(entity_id)`, the one method
    `_register_weather_forecast_subscriptions` calls on it."""

    def __init__(self, entities: dict[str, _FakeWeatherEntity] | None = None) -> None:
        self._entities = entities or {}

    def get_entity(self, entity_id: str) -> _FakeWeatherEntity | None:
        return self._entities.get(entity_id)


class TestWeatherForecastSubscriptionRegistrationGuards:
    """`_register_weather_forecast_subscriptions` (ADR-012 §4a) is a
    no-op — no exception — for every one of its defensive "nothing to
    subscribe yet" branches, each exercised independently."""

    def test_hass_without_a_data_attribute_is_a_no_op(self) -> None:
        # A `hass` genuinely lacking `.data` at all (this method's own
        # docstring: "the coordinator test suite's `FakeHomeAssistant`
        # stand-ins... predate this method") — `getattr(..., "data",
        # None)` must fall back to `None` rather than raising.
        entry = _make_entry()
        hass = FakeHomeAssistant()
        del hass.data

        coordinator = _run(_construct_coordinator(hass, entry))
        assert coordinator is not None  # construction itself must not raise

    def test_hass_data_present_but_no_weather_component_registered(self) -> None:
        # The default/normal case for every config entry that isn't a
        # `weather.*`-sourced baseline: `hass.data` exists (a plain
        # dict, per `FakeHomeAssistant`) but never gained the
        # `WEATHER_DATA_COMPONENT` key at all.
        entry = _make_entry()
        hass = FakeHomeAssistant()
        hass.states.set(
            _BASELINE_ENTITY,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW)},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})

        coordinator = _run(_construct_coordinator(hass, entry))
        assert coordinator is not None

    def test_sensor_shaped_baseline_and_temperature_provider_are_both_skipped(self) -> None:
        # A `weather_component` *is* present, but every registered
        # provider is skipped: the default global baseline is
        # `sensor_dict`-shaped (`forecast_type is None`), and the
        # weather-tier temperature predictor isn't a `BaselineProvider`
        # at all.
        entry = _make_entry(default_temperature_source="weather.home")
        hass = FakeHomeAssistant()
        hass.states.set(
            _BASELINE_ENTITY,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW)},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set("weather.home", {"temperature": 20.0, "forecast": []})
        hass.data[_WEATHER_DATA_COMPONENT_KEY] = _FakeWeatherComponent()  # type: ignore[index]

        coordinator = _run(_construct_coordinator(hass, entry))

        baseline_provider = coordinator._entity_providers[_BASELINE_ENTITY]
        temperature_provider = coordinator._entity_providers["weather.home"]
        assert isinstance(baseline_provider, BaselineProvider)
        assert baseline_provider.forecast_type is None  # sensor_dict -> continue at forecast_type
        assert not isinstance(temperature_provider, BaselineProvider)  # continue at isinstance


class TestWeatherForecastSubscriptionRegistrationSuccess:
    """`_register_weather_forecast_subscriptions` (ADR-012 §4a): given a
    `weather_sunshine`/`weather_cloud`-shaped baseline provider and a
    `weather_component` that actually resolves its entity, subscribes
    to it and requests an immediate first value — and the listener it
    hands `async_subscribe_forecast` is `_make_forecast_listener`'s own
    `_handle`, which pushes whatever forecast it's given straight into
    that provider (ADR-012 §4a's "push, then maybe recompute" tail)."""

    @staticmethod
    def _make_entry_and_hass(entity: _FakeWeatherEntity | None) -> tuple[Any, FakeHomeAssistant]:
        entry = _make_entry(
            baseline_entity_id="weather.dwd",
            baseline_attribute="sunshine_duration",
            baseline_shape="weather_sunshine",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        entities = {"weather.dwd": entity} if entity is not None else {}
        hass.data[_WEATHER_DATA_COMPONENT_KEY] = _FakeWeatherComponent(entities)  # type: ignore[index]
        return entry, hass

    def test_entity_not_found_on_the_weather_component_is_skipped(self) -> None:
        entry, hass = self._make_entry_and_hass(entity=None)
        coordinator = _run(_construct_coordinator(hass, entry))
        assert coordinator is not None  # no exception; nothing to assert further

    def test_entity_found_subscribes_and_requests_an_immediate_update(self) -> None:
        entity = _FakeWeatherEntity()
        entry, hass = self._make_entry_and_hass(entity=entity)

        coordinator = _run(_construct_coordinator(hass, entry))

        assert entity.subscribed_forecast_types == ["hourly"]
        assert len(entity.listeners) == 1
        assert entity.update_calls == [{"hourly"}]
        assert coordinator is not None

    def test_forecast_listener_pushes_the_live_forecast_into_the_provider(self) -> None:
        entity = _FakeWeatherEntity()
        entry, hass = self._make_entry_and_hass(entity=entity)
        coordinator = _run(_construct_coordinator(hass, entry))
        provider = coordinator._entity_providers["weather.dwd"]
        assert isinstance(provider, BaselineProvider)
        assert provider._latest_forecast is None  # nothing pushed yet

        raw_forecast = [
            {"datetime": "2026-06-15T10:00:00+00:00", "sunshine_duration": 900.0},
            {"datetime": "2026-06-15T10:05:00+00:00", "sunshine_duration": 1200.0},
        ]
        listener = entity.listeners[0]

        async def _fire_listener() -> None:
            listener(raw_forecast)
            await hass.drain()

        _run(_fire_listener())

        assert provider._latest_forecast == raw_forecast
        # `_handle_provider_update` actually pushed the normalized
        # series into the cache under this same entity_id.
        pushed = coordinator.cache.get_time_range(
            ["weather.dwd"],
            datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
            datetime(2026, 6, 15, 10, 10, tzinfo=UTC),
            on_invalid="raw",
        )["weather.dwd"]
        assert pushed == [900.0, 1200.0, None]


class _FakeForecastSolarServices:
    """Real (non-`Mock`) stand-in for `hass.services` covering just
    `forecast_solar.get_forecast` — `support_ha.py`'s own `FakeServices`
    is registration-based (`async_register`/`has_service`) and doesn't
    accept the `blocking`/`return_response` kwargs `_poll_forecast_solar`
    passes, so this file uses its own minimal stand-in instead, matching
    `tests/test_providers_discovery.py`'s own `FakeServices` convention
    for the identical service."""

    def __init__(self) -> None:
        self.responses: dict[str, Any] = {}
        self.raises: set[str] = set()
        self.calls: list[str] = []

    async def async_call(
        self,
        domain: str,
        service: str,
        service_data: dict[str, Any] | None = None,
        *,
        blocking: bool = False,
        return_response: bool = False,
    ) -> Any:
        assert domain == "forecast_solar"
        assert service == "get_forecast"
        config_entry_id = (service_data or {}).get("config_entry")
        assert isinstance(config_entry_id, str)
        self.calls.append(config_entry_id)
        if config_entry_id in self.raises:
            raise RuntimeError("synthetic forecast_solar.get_forecast failure")
        return self.responses.get(config_entry_id)


class TestForecastSolarPoll:
    """`_register_forecast_solar_polls`/`_make_forecast_solar_poll`/
    `_poll_forecast_solar` (ADR-012 §4b) — the one push path with no
    subscription API at all, only a genuine hourly poll."""

    @staticmethod
    def _make_entry_and_hass() -> tuple[Any, FakeHomeAssistant]:
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.services = _FakeForecastSolarServices()  # type: ignore[assignment]
        return entry, hass

    def test_construction_schedules_an_immediate_poll(self) -> None:
        entry, hass = self._make_entry_and_hass()
        hass.services.responses["fs_entry_1"] = {  # type: ignore[attr-defined]
            "wh_period": {"2026-06-15T10:00:00+00:00": 500.0}
        }

        coordinator = _run(_construct_coordinator(hass, entry))

        assert hass.services.calls == ["fs_entry_1"]  # type: ignore[attr-defined]
        provider = coordinator._entity_providers["fs_entry_1"]
        assert isinstance(provider, BaselineProvider)
        assert provider._latest_forecast == {"wh_period": {"2026-06-15T10:00:00+00:00": 500.0}}

    def test_timer_fire_triggers_another_poll(self) -> None:
        entry, hass = self._make_entry_and_hass()
        hass.services.responses["fs_entry_1"] = {"wh_period": {}}  # type: ignore[attr-defined]
        coordinator = _run(_construct_coordinator(hass, entry))
        assert hass.services.calls == ["fs_entry_1"]  # type: ignore[attr-defined]

        poll_callback = coordinator._make_forecast_solar_poll("fs_entry_1")

        async def _fire_timer() -> None:
            poll_callback(_NOW)
            await hass.drain()

        _run(_fire_timer())

        assert hass.services.calls == ["fs_entry_1", "fs_entry_1"]  # type: ignore[attr-defined]

    def test_poll_for_an_unregistered_entity_is_a_no_op(self) -> None:
        entry, hass = self._make_entry_and_hass()
        hass.services.responses["fs_entry_1"] = {"wh_period": {}}  # type: ignore[attr-defined]
        coordinator = _run(_construct_coordinator(hass, entry))

        _run(coordinator._poll_forecast_solar("sensor.not_a_registered_provider"))

        # Unchanged: the poll for an unregistered entity never calls
        # the service at all.
        assert hass.services.calls == ["fs_entry_1"]  # type: ignore[attr-defined]

    def test_service_call_failure_is_swallowed(self) -> None:
        entry, hass = self._make_entry_and_hass()
        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]

        coordinator = _run(_construct_coordinator(hass, entry))

        provider = coordinator._entity_providers["fs_entry_1"]
        assert isinstance(provider, BaselineProvider)
        assert provider._latest_forecast is None  # never updated; the failure was swallowed

    def test_successful_poll_pushes_the_forecast_into_the_cache(self) -> None:
        entry, hass = self._make_entry_and_hass()
        hass.services.responses["fs_entry_1"] = {  # type: ignore[attr-defined]
            "wh_period": {
                "2026-06-15T10:00:00+00:00": 500.0,
                "2026-06-15T10:05:00+00:00": 520.0,
            }
        }

        coordinator = _run(_construct_coordinator(hass, entry))

        pushed = coordinator.cache.get_time_range(
            ["fs_entry_1"],
            datetime(2026, 6, 15, 10, 0, tzinfo=UTC),
            datetime(2026, 6, 15, 10, 10, tzinfo=UTC),
            on_invalid="raw",
        )["fs_entry_1"]
        assert pushed == [500.0, 520.0, None]


class TestForecastSolarPollServiceResponseCache:
    """The service-response-cache fallback layered onto `_poll_forecast_
    solar` above (ADR-007 §1a, ADR-012 §4b, `TASK-0036`) — a failing or
    unusable poll now reuses the last usable forecast instead of going
    silent for a full hour or overwriting a good forecast with nothing."""

    @staticmethod
    def _make_entry_and_hass() -> tuple[Any, FakeHomeAssistant]:
        return TestForecastSolarPoll._make_entry_and_hass()

    def test_a_failing_poll_reuses_the_previous_forecast(self) -> None:
        entry, hass = self._make_entry_and_hass()
        hass.services.responses["fs_entry_1"] = {  # type: ignore[attr-defined]
            "wh_period": {"2026-06-15T10:00:00+00:00": 500.0}
        }
        coordinator = _run(_construct_coordinator(hass, entry))
        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]

        _run(coordinator._poll_forecast_solar("fs_entry_1"))

        provider = coordinator._entity_providers["fs_entry_1"]
        assert isinstance(provider, BaselineProvider)
        assert provider._latest_forecast == {"wh_period": {"2026-06-15T10:00:00+00:00": 500.0}}

    def test_a_wh_period_less_response_reuses_the_previous_forecast(self) -> None:
        """The existing "returned no usable wh_period data" warning
        branch now falls back instead of pushing the empty response
        into the provider."""
        entry, hass = self._make_entry_and_hass()
        hass.services.responses["fs_entry_1"] = {  # type: ignore[attr-defined]
            "wh_period": {"2026-06-15T10:00:00+00:00": 500.0}
        }
        coordinator = _run(_construct_coordinator(hass, entry))
        hass.services.responses["fs_entry_1"] = {"watts": {}}  # type: ignore[attr-defined]

        _run(coordinator._poll_forecast_solar("fs_entry_1"))

        provider = coordinator._entity_providers["fs_entry_1"]
        assert provider._latest_forecast == {"wh_period": {"2026-06-15T10:00:00+00:00": 500.0}}

    def test_a_cold_failing_poll_is_still_swallowed(self) -> None:
        """Unchanged from before this amendment: nothing remembered,
        nothing pushed, no exception escapes — the cache sits in this
        path now, but changes nothing about the cold case."""
        entry, hass = self._make_entry_and_hass()
        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]

        coordinator = _run(_construct_coordinator(hass, entry))

        provider = coordinator._entity_providers["fs_entry_1"]
        assert provider._latest_forecast is None

    def test_a_remembered_forecast_older_than_12_hours_is_not_used(self) -> None:
        """Isolates "was this recalled" from "was this ever pushed":
        the good response is remembered directly via the cache (never
        through a poll, which would also set `_latest_forecast` itself)
        so the provider's `_latest_forecast` staying `None` after the
        expired poll can only mean the stale entry was correctly
        excluded from recall, not merely left untouched from an
        earlier successful push."""
        entry, hass = self._make_entry_and_hass()
        coordinator = _run(_construct_coordinator(hass, entry))
        key = _cache_mod.service_call_key(
            "forecast_solar", "get_forecast", {"config_entry": "fs_entry_1"}
        )

        async def _good() -> Any:
            return {"wh_period": {"2026-06-15T10:00:00+00:00": 500.0}}

        _run(coordinator._service_response_cache.async_call(key, _good, now=_NOW))

        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]
        coordinator._now = lambda: _NOW + _SERVICE_RESPONSE_MAX_AGE + timedelta(seconds=1)
        _run(coordinator._poll_forecast_solar("fs_entry_1"))

        provider = coordinator._entity_providers["fs_entry_1"]
        # Aged out — behaves as a genuinely cold failure, not a recall.
        assert provider._latest_forecast is None

    def test_the_poll_result_survives_a_restart(self) -> None:
        """End-to-end of the persisted half: a first coordinator polls
        successfully; a second one, constructed over the same `hass`
        (same on-disk store, fresh `hass.data`) with the service now
        failing, still starts up with a usable baseline."""
        entry, hass = self._make_entry_and_hass()
        hass.services.responses["fs_entry_1"] = {  # type: ignore[attr-defined]
            "wh_period": {"2026-06-15T10:00:00+00:00": 500.0}
        }
        _run(_construct_coordinator(hass, entry))

        hass.data.clear()
        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]
        restarted = _run(_construct_coordinator(hass, entry))

        provider = restarted._entity_providers["fs_entry_1"]
        assert provider._latest_forecast == {"wh_period": {"2026-06-15T10:00:00+00:00": 500.0}}

    def test_a_persisted_forecast_older_than_12_hours_is_not_used_after_a_restart(self) -> None:
        entry, hass = self._make_entry_and_hass()
        coordinator = _run(_construct_coordinator(hass, entry))
        key = _cache_mod.service_call_key(
            "forecast_solar", "get_forecast", {"config_entry": "fs_entry_1"}
        )

        async def _good() -> Any:
            return {"wh_period": {"2026-06-15T10:00:00+00:00": 500.0}}

        # Remember (and persist) a response at `_NOW`, bypassing the poll
        # itself — isolates "was this recalled from disk" from "was this
        # ever pushed by this coordinator instance".
        _run(coordinator._service_response_cache.async_call(key, _good, now=_NOW))

        hass.data.clear()
        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]
        restarted = _run(_construct_coordinator(hass, entry))
        restarted._now = lambda: _NOW + _SERVICE_RESPONSE_MAX_AGE + timedelta(seconds=1)

        _run(restarted._poll_forecast_solar("fs_entry_1"))

        provider = restarted._entity_providers["fs_entry_1"]
        assert provider._latest_forecast is None


class TestForecastSolarRefreshOnRefit:
    """`async_refit`'s own `_refresh_forecast_solar_providers` call — an
    *awaited* Forecast.Solar poll ahead of every fit/recompute, added to
    close the exact startup-ordering race a real user hit: the
    construction-time immediate poll (`_register_forecast_solar_polls`)
    failed because the Forecast.Solar config entry wasn't loaded yet,
    and pressing the manual Recalculate button afterwards did nothing to
    recover, since `async_refit` never re-polled it — only the next
    scheduled hourly poll would have. `async_refit` (button, midnight
    schedule) and `async_startup`'s own "recent fit, skip refit" branch
    both now retry first."""

    def test_refit_recovers_from_a_missed_construction_time_poll(self) -> None:
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.services = _FakeForecastSolarServices()  # type: ignore[assignment]
        # Simulate the exact race report: the config entry isn't loaded
        # yet at construction time, so the immediate poll fails.
        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]
        tc._seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))

        coordinator = _run(_construct_coordinator(hass, entry))
        provider = coordinator._entity_providers["fs_entry_1"]
        assert provider._latest_forecast is None  # construction-time poll failed

        # The config entry has since finished loading — a Recalculate
        # press (or the midnight schedule) should now succeed.
        hass.services.raises.discard("fs_entry_1")  # type: ignore[attr-defined]
        hass.services.responses["fs_entry_1"] = {  # type: ignore[attr-defined]
            "wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))
        }

        _run(coordinator.async_refit(_NOW))

        assert provider._latest_forecast is not None
        pushed = tc.hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert pushed  # the recompute actually produced something now

    def test_async_startup_skip_branch_still_refreshes(self) -> None:
        """`async_startup`'s "recent fit, skip refit" branch (a fit
        already exists, <24h old) doesn't call `async_refit` at all —
        it must still retry a missed Forecast.Solar poll on its own."""
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.services = _FakeForecastSolarServices()  # type: ignore[assignment]
        hass.services.raises.add("fs_entry_1")  # type: ignore[attr-defined]
        tc._seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))

        coordinator = _run(_construct_coordinator(hass, entry))
        coordinator._now = lambda: _NOW
        coordinator._last_fit_at = _NOW  # pretend a fit just happened

        provider = coordinator._entity_providers["fs_entry_1"]
        assert provider._latest_forecast is None

        hass.services.raises.discard("fs_entry_1")  # type: ignore[attr-defined]
        hass.services.responses["fs_entry_1"] = {  # type: ignore[attr-defined]
            "wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))
        }

        _run(coordinator.async_startup(_NOW))

        assert provider._latest_forecast is not None
