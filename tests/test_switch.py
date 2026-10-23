"""Tests for `switch.py`'s `ShadyFollowDiagnosticSlotSwitch` (ADR-004
§2g, `TASK-0037-patch-4`) — the auto-follow toggle that replaced
`button.py`'s `ShadyClearDiagnosticSlotButton` (ADR-004 §2f).

`switch.py` is HA-facing (real, non-`TYPE_CHECKING` import of
`homeassistant.components.switch`) — outside ADR-000 §6's zero-mocking
pure tier. This file extends `test_coordinator.py`'s hand-written
`homeassistant` stub convention with the one additional surface
`switch.py` touches: `homeassistant.components.switch.SwitchEntity` — a
real (non-`Mock`) stand-in, registered directly in `sys.modules` before
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


def _install_switch_stub() -> None:
    """Extends the shared core stub with `homeassistant.components
    .switch` (`SwitchEntity`) — this file's own addition, the only
    consumer of it."""
    ha_components = sys.modules["homeassistant.components"]
    ha_components_switch = ModuleType("homeassistant.components.switch")

    class SwitchEntity:
        """Real (non-Mock) stand-in for the slice `switch.py` actually
        uses: a plain base class carrying `_attr_*` attributes, an
        overridable `is_on` property, and overridable `async_turn_on`/
        `async_turn_off` — mirrors real HA's own `SwitchEntity`
        contract, not the full entity machinery."""

    ha_components_switch.SwitchEntity = SwitchEntity  # type: ignore[attr-defined]
    ha_components.switch = ha_components_switch  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.switch"] = ha_components_switch


_install_ha_stub()
_install_switch_stub()

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
_switch_mod = _load("switch.py", "shady.switch")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = sys.modules["shady.cache"].Cache
CONF_STRINGS = _const_mod.CONF_STRINGS
DOMAIN = _const_mod.DOMAIN
async_setup_entry = _switch_mod.async_setup_entry
ShadyFollowDiagnosticSlotSwitch = _switch_mod.ShadyFollowDiagnosticSlotSwitch

# -- shared test fixture (mirrors test_datetime.py's own) ---------------------

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
    """Given `switch.py`'s `async_setup_entry` runs for a config entry,
    When entities are added, Then exactly one
    `ShadyFollowDiagnosticSlotSwitch` is added (one per config entry,
    not per string)."""

    def test_exactly_one_entity_per_entry(self) -> None:
        coordinator, hass = _make_coordinator()
        entry = coordinator.entry
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        add_entities = _FakeAddEntities()

        _run(async_setup_entry(hass, entry, add_entities))

        assert len(add_entities.added) == 1
        assert isinstance(add_entities.added[0], ShadyFollowDiagnosticSlotSwitch)


class TestIsOn:
    """Given a config entry's diagnosed slot (ADR-004 §2g), When `is_on`
    is read, Then it reflects `coordinator.py`'s
    `is_following_latest_diagnostic_slot()` exactly — on by default,
    off once a slot is pinned."""

    def test_on_by_default(self) -> None:
        coordinator, _hass = _make_coordinator()
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        assert switch.is_on is True

    def test_off_once_a_slot_is_pinned_elsewhere(self) -> None:
        coordinator, _hass = _make_coordinator()
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        coordinator.pin_diagnostic_slot(datetime(2026, 6, 15, 8, 0, tzinfo=UTC), now=_NOW)

        assert switch.is_on is False


class TestTurnOff:
    """Given following is on, When the switch is turned off, Then the
    slot is pinned exactly as currently shown — nothing moves, not
    even on later ticks — and the cache's genuinely-pinned reference
    (ADR-007a §6) is set to that slot's date."""

    def test_pins_the_slot_as_currently_shown(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator.set_follow_latest_diagnostic_slot(True)
        shown = coordinator.diagnostic_slot_timestamp()
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        _run(switch.async_turn_off())
        coordinator._advance_followed_diagnostic_slot(_NOW + timedelta(hours=2))

        assert switch.is_on is False
        assert coordinator.diagnostic_slot_timestamp() == shown
        assert coordinator.diagnosed_slot().index == Cache.index_for(shown)

    def test_sets_the_cache_pinned_reference_to_the_slots_date(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator.set_follow_latest_diagnostic_slot(True)
        assert coordinator.cache.pinned_reference is None
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        _run(switch.async_turn_off())

        assert coordinator.cache.pinned_reference == coordinator.diagnostic_slot_timestamp().date()

    def test_turning_off_while_already_off_keeps_the_pin(self) -> None:
        coordinator, _hass = _make_coordinator()
        target = datetime(2026, 6, 15, 8, 0, tzinfo=UTC)
        coordinator.pin_diagnostic_slot(target, now=_NOW)
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        _run(switch.async_turn_off())

        assert coordinator.diagnostic_slot_timestamp() == Cache.timestamp_for(
            Cache.index_for(target)
        )


class TestTurnOn:
    """Given a slot is pinned, When the switch is turned on, Then the
    slot jumps to the newest complete one immediately (not one tick
    later), the cache's pinned reference is cleared (ADR-007a §6: it
    means "genuinely pinned", never "following"), and later ticks keep
    moving it."""

    def test_jumps_to_the_latest_complete_slot_immediately(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator.pin_diagnostic_slot(datetime(2026, 6, 14, 12, 0, tzinfo=UTC), now=_NOW)
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        _run(switch.async_turn_on())

        assert switch.is_on is True
        assert coordinator.diagnostic_slot_timestamp() == datetime(2026, 6, 15, 9, 55, tzinfo=UTC)

    def test_clears_the_cache_pinned_reference(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator.pin_diagnostic_slot(datetime(2026, 6, 14, 12, 0, tzinfo=UTC), now=_NOW)
        assert coordinator.cache.pinned_reference is not None
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        _run(switch.async_turn_on())

        assert coordinator.cache.pinned_reference is None

    def test_later_ticks_keep_moving_the_slot(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator.pin_diagnostic_slot(datetime(2026, 6, 14, 12, 0, tzinfo=UTC), now=_NOW)
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)
        _run(switch.async_turn_on())

        coordinator._advance_followed_diagnostic_slot(_NOW + timedelta(minutes=10))

        assert coordinator.diagnostic_slot_timestamp() == datetime(2026, 6, 15, 10, 5, tzinfo=UTC)


class TestUniqueId:
    def test_unique_id_is_entry_scoped(self) -> None:
        coordinator, _hass = _make_coordinator()
        switch = ShadyFollowDiagnosticSlotSwitch(coordinator, coordinator.entry)

        assert coordinator.entry.entry_id in switch._attr_unique_id
