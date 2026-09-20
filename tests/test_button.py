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

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

from tests.support import _load, _run
from tests.support_ha import FakeHomeAssistant, _install_ha_stub


def _install_button_stub() -> None:
    """Extends the shared core stub with `homeassistant.components
    .button` (`ButtonEntity`) — this file's own addition, the only
    consumer of it."""
    ha_components = sys.modules["homeassistant.components"]
    ha_components_button = ModuleType("homeassistant.components.button")

    class ButtonEntity:
        """Real (non-Mock) stand-in for the slice `button.py` actually
        uses: nothing beyond being a plain base class carrying
        `_attr_*` attributes and an overridable `async_press`."""

    ha_components_button.ButtonEntity = ButtonEntity  # type: ignore[attr-defined]
    ha_components.button = ha_components_button  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.button"] = ha_components_button


_install_ha_stub()
_install_button_stub()

_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []
sys.modules["shady"] = _shady_pkg

_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_load("regression/base.py", "shady.regression.base")
_const_mod = _load("const.py", "shady.const")
_load("cache.py", "shady.cache")
_load("providers/discovery.py", "shady.providers.discovery")
_load("providers/temperature.py", "shady.providers.temperature")
_load("regression/__init__.py", "shady.regression")
_load("regression/linear.py", "shady.regression.linear")
_load("regression/kernel.py", "shady.regression.kernel")
_load("regression/wls2.py", "shady.regression.wls2")
_load("regression/wls3.py", "shady.regression.wls3")
_load("yield_correction.py", "shady.yield_correction")
_load("forecast_adjust.py", "shady.forecast_adjust")
_load("aggregation.py", "shady.aggregation")
_load("string_computation.py", "shady.string_computation")
_load("diagnostics/__init__.py", "shady.diagnostics")
_load("diagnostics/base.py", "shady.diagnostics.base")
_load("diagnostics/compare_regressions.py", "shady.diagnostics.compare_regressions")
_load("coordinator_like.py", "shady.coordinator_like")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")
_load("device.py", "shady.device")
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
        "recency_decay_max": 0.5,
        "clipping_threshold": 0.98,
        "default_temperature_source": None,
        "max_uplift_c": 25,
        "weather_forecast_temperature_entity": None,
        "temperature_regression_method": "wls2",
        "intraday_correction_mode": "off",
        "intraday_correction_cutoff": 0.10,
        "window_slots": 24,
        "ramp_slots": 12,
        CONF_STRINGS: {
            _ACTUAL_YIELD_ENTITY: {
                "name": "Dach Süd",
                "baseline_entity_id": None,
                "baseline_attribute": None,
                "baseline_shape": None,
                "converter_limit_w": None,
                "temperature_source_entity_id": None,
                "temperature_coefficient_pct_per_c": -0.4,
                "rated_dc_capacity_wp": None,
            }
        },
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
                CONF_STRINGS: {
                    _ACTUAL_YIELD_ENTITY: {
                        "name": "Dach Süd",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    },
                    second_yield_entity: {
                        "name": "Dach Nord",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    },
                }
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
        assert coordinator.cache.get_model("shading", 0) is None
        button = ShadyRecalculateButton(coordinator, coordinator.entry)

        _run(button.async_press())

        # the same `_refit_sync` path TASK-0010 tests directly
        assert coordinator.cache.get_model("shading", 0) is not None

    def test_press_swallows_a_refit_exception(self) -> None:
        coordinator, _hass = _make_coordinator()

        async def _boom(now: datetime | None = None) -> None:
            raise RuntimeError("synthetic refit failure")

        coordinator.async_refit = _boom
        button = ShadyRecalculateButton(coordinator, coordinator.entry)

        _run(button.async_press())  # must not raise

    def test_unique_id_is_entry_scoped(self) -> None:
        coordinator, _hass = _make_coordinator()
        button = ShadyRecalculateButton(coordinator, coordinator.entry)

        assert coordinator.entry.entry_id in button._attr_unique_id
