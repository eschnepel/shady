"""Tests for `coordinator.py` (ADR-002, ADR-012 §4).

`coordinator.py` is HA-facing (real, non-`TYPE_CHECKING` imports of
`homeassistant.core`, `homeassistant.helpers.event`, and
`homeassistant.components.recorder.statistics`) — outside ADR-000 §6's
zero-mocking pure tier, same as `config_flow.py` (TASK-0009). This file
extends that task's hand-written `homeassistant` stub convention
(`tasks/INDEX.md`'s refinement log) with the additional surface this
module touches: `async_track_time_change`/`async_track_state_change_event`
and `statistics_during_period` — all real (non-`Mock`) stand-ins, not
mocks, registered directly in `sys.modules` before file-path-loading the
module under test.
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


# -- hand-written `homeassistant` stub (real stand-in, not a mock) ----------


def _callback(func: Any) -> Any:
    return func


class FakeState:
    def __init__(self, entity_id: str, attributes: dict[str, Any] | None = None) -> None:
        self.entity_id = entity_id
        self.state = "unknown"
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

    def set(self, entity_id: str, attributes: dict[str, Any] | None = None) -> None:
        """Set/update an entity's state and fire any registered
        state-change listeners — a real (non-mock) stand-in for a live
        HA state-changed event, sufficient for what `coordinator.py`'s
        listeners actually read (they re-derive everything from current
        state, never from the fired event's payload)."""
        self._states[entity_id] = FakeState(entity_id, attributes)
        for listener in self._listeners.get(entity_id, []):
            listener(None)


class FakeHomeAssistant:
    def __init__(self) -> None:
        self.states = FakeStates()
        self.statistics: dict[str, dict[datetime, float]] = {}
        self._pending_tasks: list[asyncio.Task[Any]] = []

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)

    def async_create_task(self, coro: Any) -> Any:
        task = asyncio.ensure_future(coro)
        self._pending_tasks.append(task)
        return task

    async def drain(self) -> None:
        """Test-only: let every `async_create_task`-scheduled coroutine
        (recompute, midnight-triggered refit) actually run to completion
        before assertions — mirrors pumping HA's own event loop."""
        while self._pending_tasks:
            pending = self._pending_tasks
            self._pending_tasks = []
            await asyncio.gather(*pending)


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers_event = ModuleType("homeassistant.helpers.event")
    ha_components = ModuleType("homeassistant.components")
    ha_recorder = ModuleType("homeassistant.components.recorder")
    ha_recorder_statistics = ModuleType("homeassistant.components.recorder.statistics")

    ha_core.callback = _callback  # type: ignore[attr-defined]

    class FakeConfigEntry:
        def __init__(self, entry_id: str, data: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.data = data

    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]

    def async_track_time_change(
        hass: Any, action: Any, *, hour: int, minute: int, second: int
    ) -> Any:
        # Never auto-fires in tests — `_handle_midnight` is exercised
        # directly, which is a real (non-mocked) call into the exact
        # same handler this registration would eventually invoke.
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

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.helpers = ha_helpers  # type: ignore[attr-defined]
    ha_helpers.event = ha_helpers_event  # type: ignore[attr-defined]
    ha.components = ha_components  # type: ignore[attr-defined]
    ha_components.recorder = ha_recorder  # type: ignore[attr-defined]
    ha_recorder.statistics = ha_recorder_statistics  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.event"] = ha_helpers_event
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.recorder"] = ha_recorder
    sys.modules["homeassistant.components.recorder.statistics"] = ha_recorder_statistics


_install_ha_stub()

# `coordinator.py` does `from .regression import kernel, linear, wls2,
# wls3` (package-level, not `from .regression.kernel import ...`) —
# resolving that requires the top-level `shady` package itself to be a
# real (if empty) entry in `sys.modules`, not just its submodules
# individually; `providers.*`/`regression.*`'s own direct
# `from .x.y import z`-style imports never needed this, since Python's
# import machinery short-circuits on an exact dotted-name cache hit
# before ever falling back to package-attribute + recursive-import
# resolution — a fallback only `from .regression import <submodule>`
# actually triggers.
_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []  # mark as a package, matching a real `shady/`
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
_load("cache.py", "shady.cache")
_const_mod = _load("const.py", "shady.const")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = sys.modules["shady.cache"].Cache
CONF_STRINGS = _const_mod.CONF_STRINGS

# -- shared test fixture -----------------------------------------------

_NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 6, 14, tzinfo=UTC)
_BASELINE_ENTITY = "sensor.forecast_solar_estimate"
_ACTUAL_YIELD_ENTITY = "sensor.string_a_yield"


def _synthetic_wh_period(start: datetime, end: datetime) -> dict[str, float]:
    """A simple, deterministic daytime-shaped series (06:00-18:00 sunny,
    else zero) covering `[start, end)` at 5-minute resolution — enough
    for a non-degenerate fit without needing real-world data."""
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
                "temperature_aware": False,
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


def _make_coordinator(entry: Any | None = None) -> tuple[Any, FakeHomeAssistant]:
    hass = FakeHomeAssistant()
    hass.states.set(
        _BASELINE_ENTITY,
        {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
    )
    hass.states.set(_ACTUAL_YIELD_ENTITY, {})
    _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
    coordinator = ShadyCoordinator(hass, entry or _make_entry())
    coordinator._now = lambda: _NOW  # deterministic clock for state-change-triggered paths
    return coordinator, hass


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


class TestRefitSharedCodePath:
    """Given a manual button press and the scheduled midnight trigger,
    When either fires, Then both call the exact same refit code path,
    using only recorder data up to and including yesterday."""

    def test_button_and_midnight_produce_the_same_fit(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        button_model = coordinator._models[0]

        coordinator2, hass2 = _make_coordinator()

        async def _drive_midnight() -> None:
            coordinator2._handle_midnight(_NOW)
            await hass2.drain()

        _run(_drive_midnight())
        midnight_model = coordinator2._models[0]

        assert (button_model.coefficients == midnight_model.coefficients).all()
        assert coordinator._last_fit_at == _NOW
        assert coordinator2._last_fit_at == _NOW

    def test_refit_only_uses_data_through_yesterday(self) -> None:
        coordinator, hass = _make_coordinator()
        # Pollute "today"'s statistics with an extreme value; if refit
        # accidentally included today's partial data the fit would be
        # visibly different from a run where today is left untouched.
        hass.statistics[_ACTUAL_YIELD_ENTITY][_NOW] = 999_999.0
        _run(coordinator.async_refit(_NOW))

        coordinator_clean, _hass_clean = _make_coordinator()
        _run(coordinator_clean.async_refit(_NOW))

        assert (
            coordinator._models[0].coefficients == coordinator_clean._models[0].coefficients
        ).all()


class TestStartupSafetyNet:
    """Given a config entry with no model fitted yet (or a last fit >24h
    old), When the coordinator's startup-fit entry point is called, Then
    a fit runs immediately, in addition to the daily schedule."""

    def test_async_startup_fits_when_no_model_yet(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator._models == {}
        _run(coordinator.async_startup(_NOW))
        assert 0 in coordinator._models
        assert coordinator._last_fit_at is not None

    def test_async_startup_skips_when_recently_fitted(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        first_fit_at = coordinator._last_fit_at
        _run(coordinator.async_startup(_NOW + timedelta(hours=1)))
        assert coordinator._last_fit_at == first_fit_at  # unchanged: no re-fit triggered


class TestMissingRequiredEntities:
    """Given a config entry's per-string actual-yield or resolved
    baseline entity does not currently exist, When
    `missing_required_entities()` is called, Then it returns those
    entity IDs (and only those — never optional correction-tier
    entities)."""

    def test_reports_missing_actual_yield_and_baseline(self) -> None:
        hass = FakeHomeAssistant()
        # Neither entity set at all: both required entities missing.
        coordinator = ShadyCoordinator(hass, _make_entry())
        missing = coordinator.missing_required_entities()
        assert set(missing) == {_BASELINE_ENTITY, _ACTUAL_YIELD_ENTITY}

    def test_none_missing_once_both_exist(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator.missing_required_entities() == []

    def test_optional_temperature_entity_never_required(self) -> None:
        entry = _make_entry(default_temperature_source="weather.home")
        hass = FakeHomeAssistant()
        hass.states.set(_BASELINE_ENTITY, {"wh_period": {}})
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        # weather.home deliberately never set — must not appear below.
        coordinator = ShadyCoordinator(hass, entry)
        assert coordinator.missing_required_entities() == []


class TestRefitTriggersRecompute:
    """Given a string's model is freshly (re)fit, When fitting succeeds,
    Then the exact same recompute path runs immediately for that string
    against whatever baseline data is currently cached (ADR-002 §2,
    trigger 1) — TASK-0010-patch-1."""

    def test_refit_pushes_a_forecast_without_any_baseline_update(self) -> None:
        coordinator, _hass = _make_coordinator()
        sensor_id = coordinator.forecast_sensor_id(0)
        assert coordinator.cache.validated_range(sensor_id) is None  # nothing pushed yet

        _run(coordinator.async_refit(_NOW))

        pushed = hass_pushed_values(coordinator, sensor_id)
        assert pushed  # recompute ran as part of refit itself, no separate trigger fired

    def test_no_recompute_attempted_when_fitting_fails(self) -> None:
        # A string with no baseline provider configured at all: `_fit_string`
        # returns None, so there must be nothing to recompute either.
        entry = _make_entry(baseline_entity_id=None, baseline_attribute=None, baseline_shape=None)
        strings = entry.data[CONF_STRINGS]
        entry.data[CONF_STRINGS] = strings
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW

        _run(coordinator.async_refit(_NOW))

        assert coordinator._models == {}
        assert coordinator.cache.validated_range(coordinator.forecast_sensor_id(0)) is None


class TestRecomputeOnBaselineUpdate:
    """Given a baseline-provider update fires mid-day, When it fires,
    Then a forecast recompute happens immediately with no debounce, but
    no recalibration is triggered by this alone."""

    def test_baseline_update_triggers_recompute_not_recalibration(self) -> None:
        coordinator, hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        fit_count_before = coordinator._last_fit_at

        async def _drive_update() -> None:
            hass.states.set(
                _BASELINE_ENTITY,
                {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
            )
            await hass.drain()

        _run(_drive_update())

        assert coordinator._last_fit_at == fit_count_before  # no recalibration
        pushed = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert pushed  # a recompute actually produced+pushed something


def hass_pushed_values(coordinator: Any, sensor_id: str) -> dict[int, float]:
    cache = coordinator.cache
    validated = cache.validated_range(sensor_id)
    assert validated is not None
    result: dict[int, float] = {}
    lst = cache._values.get(sensor_id, [])
    offset = cache._list_offset.get(sensor_id, 0)
    for position, value in enumerate(lst):
        if isinstance(value, float):
            result[offset + position] = value
    return result


class TestRecomputeHorizon:
    """Given a recompute, When it runs, Then it produces adjusted values
    only for the remainder of today plus tomorrow, and never recomputes
    already-past slots."""

    def test_only_remainder_of_today_and_tomorrow_pushed(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        coordinator._recompute_string(coordinator._strings[0], _NOW)

        sensor_id = coordinator.forecast_sensor_id(0)
        pushed = hass_pushed_values(coordinator, sensor_id)
        now_index = Cache.index_for(_NOW)
        horizon_end = _NOW.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)

        assert pushed  # something was produced
        assert all(index >= now_index + 1 for index in pushed)  # never before "now"
        assert all(index < Cache.index_for(horizon_end) for index in pushed)


class TestPushSemantics:
    """Given a `ShadyForecastSensor`-shaped output value is computed for
    a slot, When it is first computed, Then it is immediately pushed
    into `cache.py` with `to_index=None` semantics."""

    def test_pushed_value_has_to_index_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        coordinator._recompute_string(coordinator._strings[0], _NOW)
        sensor_id = coordinator.forecast_sensor_id(0)
        validated = coordinator.cache.validated_range(sensor_id)
        assert validated is not None
        assert validated[1] is None  # to_index=None: actively pushed


class TestGenericProviderPushLoop:
    """Given both the baseline provider and the temperature provider
    override `forward()`, When a config entry sets up, Then exactly one
    generic coordinator listener is registered per such provider
    instance — no provider-specific listener code exists in
    `coordinator.py`."""

    def test_one_listener_per_forward_overriding_provider(self) -> None:
        entry = _make_entry(default_temperature_source="weather.home")
        strings = entry.data[CONF_STRINGS]
        entry.data[CONF_STRINGS] = strings
        hass = FakeHomeAssistant()
        hass.states.set(_BASELINE_ENTITY, {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW)})
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set("weather.home", {"temperature": 20.0, "forecast": []})
        coordinator = ShadyCoordinator(hass, entry)

        assert _BASELINE_ENTITY in hass.states._listeners
        assert "weather.home" in hass.states._listeners
        assert len(hass.states._listeners[_BASELINE_ENTITY]) == 1
        assert len(hass.states._listeners["weather.home"]) == 1
        assert coordinator is not None  # keep reference alive for clarity


class TestGenericPushNotBeforeIndex:
    """Given a provider's `forward()` returns a series, When the listener
    fires, Then `push(sensor_id, dict[index, value])` is called with
    `not_before_index` set to "the next upcoming slot after now"."""

    def test_push_freezes_slots_before_next_upcoming(self) -> None:
        coordinator, _hass = _make_coordinator()
        # Pre-seed the raw baseline cache entry for the current slot to
        # a sentinel, so we can confirm it is left untouched by the push
        # (frozen, per `not_before_index`).
        current_index = Cache.index_for(_NOW)
        coordinator.cache.push(_BASELINE_ENTITY, {current_index: -1.0}, current_index)

        coordinator._push_provider_series(_BASELINE_ENTITY, _NOW)

        raw_now = coordinator.cache.get_time_range(
            [_BASELINE_ENTITY], _NOW, _NOW + timedelta(minutes=1), on_invalid="raw"
        )[_BASELINE_ENTITY][0]
        assert raw_now == -1.0  # current slot frozen, not overwritten

        next_slot_start = Cache.timestamp_for(current_index + 1)
        next_slot_end = next_slot_start + timedelta(minutes=1)
        raw_next = coordinator.cache.get_time_range(
            [_BASELINE_ENTITY], next_slot_start, next_slot_end, on_invalid="raw"
        )[_BASELINE_ENTITY][0]
        assert raw_next == 500.0


class TestStringEnumeration:
    """Given a config entry with N configured strings, When
    `coordinator.strings()` is called, Then it returns exactly N
    `(index, name)` pairs in `CONF_STRINGS` order, with no private
    `_StringConfig` exposed (TASK-0010-patch-2)."""

    def test_single_string_default_fixture(self) -> None:
        coordinator, _hass = _make_coordinator()

        result = coordinator.strings()

        assert result == [(0, "Dach Süd")]
        assert all(isinstance(pair, tuple) and isinstance(pair[1], str) for pair in result)

    def test_multiple_strings_preserve_config_order(self) -> None:
        second_yield_entity = "sensor.string_b_yield"
        entry = _make_entry(
            **{
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
                    },
                    {
                        "name": "Dach Nord",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "actual_yield_entity_id": second_yield_entity,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    },
                ]
            }
        )
        hass = FakeHomeAssistant()
        hass.states.set(
            _BASELINE_ENTITY,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set(second_yield_entity, {})
        _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
        coordinator = ShadyCoordinator(hass, entry)

        assert coordinator.strings() == [(0, "Dach Süd"), (1, "Dach Nord")]
