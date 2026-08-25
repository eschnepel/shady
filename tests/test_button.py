"""Tests for `button.py`'s `ShadyRecalculateButton` (ADR-002 §1/§5,
TASK-0011).

`button.py` is HA-facing (real, non-`TYPE_CHECKING` import of
`homeassistant.components.button`) — outside ADR-000 §6's zero-mocking
pure tier. This file extends `test_coordinator.py`'s hand-written
`homeassistant` stub convention with the additional surface `button.py`
touches: `homeassistant.components.button.ButtonEntity` — a real
(non-`Mock`) stand-in, registered directly in `sys.modules` before
file-path-loading the module under test. Fully self-contained, per that
same established convention.
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


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


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
        self._states[entity_id] = FakeState(entity_id, attributes)
        for listener in self._listeners.get(entity_id, []):
            listener(None)


class FakeHomeAssistant:
    def __init__(self) -> None:
        self.states = FakeStates()
        self.statistics: dict[str, dict[datetime, float]] = {}
        self.data: dict[str, Any] = {}
        self._pending_tasks: list[asyncio.Task[Any]] = []

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)

    def async_create_task(self, coro: Any) -> Any:
        task = asyncio.ensure_future(coro)
        self._pending_tasks.append(task)
        return task


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers_event = ModuleType("homeassistant.helpers.event")
    ha_components = ModuleType("homeassistant.components")
    ha_recorder = ModuleType("homeassistant.components.recorder")
    ha_recorder_statistics = ModuleType("homeassistant.components.recorder.statistics")
    ha_components_button = ModuleType("homeassistant.components.button")

    ha_core.callback = _callback  # type: ignore[attr-defined]

    class FakeConfigEntry:
        def __init__(self, entry_id: str, data: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.data = data

    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]

    def async_track_time_change(
        hass: Any, action: Any, *, hour: int, minute: int, second: int
    ) -> Any:
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

    # -- `homeassistant.components.button` (this file's own addition) --

    class ButtonEntity:
        """Real (non-Mock) stand-in for the slice `button.py` actually
        uses: nothing beyond being a plain base class carrying
        `_attr_*` attributes and an overridable `async_press`."""

    ha_components_button.ButtonEntity = ButtonEntity  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.helpers = ha_helpers  # type: ignore[attr-defined]
    ha_helpers.event = ha_helpers_event  # type: ignore[attr-defined]
    ha.components = ha_components  # type: ignore[attr-defined]
    ha_components.recorder = ha_recorder  # type: ignore[attr-defined]
    ha_recorder.statistics = ha_recorder_statistics  # type: ignore[attr-defined]
    ha_components.button = ha_components_button  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.event"] = ha_helpers_event
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.recorder"] = ha_recorder
    sys.modules["homeassistant.components.recorder.statistics"] = ha_recorder_statistics
    sys.modules["homeassistant.components.button"] = ha_components_button


_install_ha_stub()

_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []
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
_button_mod = _load("button.py", "shady.button")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = sys.modules["shady.cache"].Cache
CONF_STRINGS = _const_mod.CONF_STRINGS
DOMAIN = _const_mod.DOMAIN
async_setup_entry = _button_mod.async_setup_entry
ShadyRecalculateButton = _button_mod.ShadyRecalculateButton

# -- shared test fixture (mirrors test_coordinator.py's own) ---------------

_NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 6, 14, tzinfo=UTC)
_BASELINE_ENTITY = "sensor.forecast_solar_estimate"
_ACTUAL_YIELD_ENTITY = "sensor.string_a_yield"


def _synthetic_wh_period(start: datetime, end: datetime) -> dict[str, float]:
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
    coordinator._now = lambda: _NOW
    return coordinator, hass


class _FakeAddEntities:
    def __init__(self) -> None:
        self.added: list[Any] = []

    def __call__(self, entities: Any) -> None:
        self.added.extend(entities)


class TestAsyncSetupEntry:
    """Given `button.py`'s `async_setup_entry` runs for a config entry,
    When entities are added, Then exactly one `ShadyRecalculateButton`
    is added (one per config entry, not per string)."""

    def test_exactly_one_button_per_entry(self) -> None:
        coordinator, hass = _make_coordinator()
        entry = coordinator.entry
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        add_entities = _FakeAddEntities()

        _run(async_setup_entry(hass, entry, add_entities))

        assert len(add_entities.added) == 1
        assert isinstance(add_entities.added[0], ShadyRecalculateButton)

    def test_multiple_configured_strings_still_yield_one_button(self) -> None:
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
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        add_entities = _FakeAddEntities()

        _run(async_setup_entry(hass, entry, add_entities))

        assert len(add_entities.added) == 1


class TestRecalculateButtonPress:
    """Given `ShadyRecalculateButton.async_press()` is called, When
    pressed, Then it triggers the exact same refit code path as the
    midnight schedule (TASK-0010), and any exception during refit is
    logged and swallowed, not raised (ADR-000 §8)."""

    def test_press_triggers_a_real_refit(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator._models == {}
        button = ShadyRecalculateButton(coordinator, coordinator.entry)

        _run(button.async_press())

        assert coordinator._models  # the same `_refit_sync` path TASK-0010 tests directly

    def test_press_swallows_a_refit_exception(self) -> None:
        coordinator, _hass = _make_coordinator()

        async def _boom(now: datetime | None = None) -> None:
            raise RuntimeError("synthetic refit failure")

        coordinator.async_refit = _boom  # type: ignore[method-assign]
        button = ShadyRecalculateButton(coordinator, coordinator.entry)

        _run(button.async_press())  # must not raise

    def test_unique_id_is_entry_scoped(self) -> None:
        coordinator, _hass = _make_coordinator()
        button = ShadyRecalculateButton(coordinator, coordinator.entry)

        assert coordinator.entry.entry_id in button._attr_unique_id
