"""Tests for `datetime.py`'s `ShadyDiagnosticSlotDateTime` (ADR-004
§2a/§2f).

`datetime.py` is HA-facing (real, non-`TYPE_CHECKING` imports of
`homeassistant.components.datetime` and `homeassistant.exceptions`) —
outside ADR-000 §6's zero-mocking pure tier. This file extends
`test_coordinator.py`'s hand-written `homeassistant` stub convention
with the additional surface `datetime.py` touches:
`homeassistant.components.datetime.DateTimeEntity` and
`homeassistant.exceptions.HomeAssistantError` — real (non-`Mock`)
stand-ins, registered directly in `sys.modules` before file-path-loading
the module under test. Fully self-contained, per that same established
convention.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

from tests.support import _load, _run
from tests.support_ha import FakeHomeAssistant, _install_ha_stub


def _install_datetime_stub() -> None:
    """Extends the shared core stub with `homeassistant.components
    .datetime` (`DateTimeEntity`) and `homeassistant.exceptions`
    (`HomeAssistantError`) — this file's own additions, the only
    consumer of either."""
    ha = sys.modules["homeassistant"]
    ha_components = sys.modules["homeassistant.components"]
    ha_components_datetime = ModuleType("homeassistant.components.datetime")
    ha_exceptions = ModuleType("homeassistant.exceptions")

    class DateTimeEntity:
        """Real (non-Mock) stand-in for the slice `datetime.py` actually
        uses: a plain base class carrying `_attr_*` attributes, an
        overridable `native_value` property, and an overridable
        `async_set_value` — mirrors real HA's own `DateTimeEntity`
        contract (`homeassistant/components/datetime/__init__.py`),
        not the full entity machinery."""

    class HomeAssistantError(Exception):
        pass

    ha_components_datetime.DateTimeEntity = DateTimeEntity  # type: ignore[attr-defined]
    ha_exceptions.HomeAssistantError = HomeAssistantError  # type: ignore[attr-defined]
    ha_components.datetime = ha_components_datetime  # type: ignore[attr-defined]
    ha.exceptions = ha_exceptions  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.datetime"] = ha_components_datetime
    sys.modules["homeassistant.exceptions"] = ha_exceptions


_install_ha_stub()
_install_datetime_stub()

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
_datetime_mod = _load("datetime.py", "shady.datetime")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = sys.modules["shady.cache"].Cache
CONF_STRINGS = _const_mod.CONF_STRINGS
DOMAIN = _const_mod.DOMAIN
async_setup_entry = _datetime_mod.async_setup_entry
ShadyDiagnosticSlotDateTime = _datetime_mod.ShadyDiagnosticSlotDateTime

HomeAssistantError = sys.modules["homeassistant.exceptions"].HomeAssistantError

# -- shared test fixture (mirrors test_button.py's own) ---------------------

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
    """Given `datetime.py`'s `async_setup_entry` runs for a config
    entry, When entities are added, Then exactly one
    `ShadyDiagnosticSlotDateTime` is added (one per config entry, not
    per string)."""

    def test_exactly_one_entity_per_entry(self) -> None:
        coordinator, hass = _make_coordinator()
        entry = coordinator.entry
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
        add_entities = _FakeAddEntities()

        _run(async_setup_entry(hass, entry, add_entities))

        assert len(add_entities.added) == 1
        assert isinstance(add_entities.added[0], ShadyDiagnosticSlotDateTime)


class TestNativeValue:
    """Given a config entry's diagnosed-slot pin state (ADR-004 §2a),
    When `native_value` is read, Then it reflects `coordinator.py`'s
    `pinned_diagnostic_slot()` exactly — `None` while auto-tracking, the
    pinned slot's own start timestamp otherwise."""

    def test_auto_tracking_reports_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        entity = ShadyDiagnosticSlotDateTime(coordinator, coordinator.entry)

        assert entity.native_value is None

    def test_pinned_slot_reports_its_start_timestamp(self) -> None:
        coordinator, _hass = _make_coordinator()
        target = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)
        coordinator.pin_diagnostic_slot(target, now=_NOW)
        entity = ShadyDiagnosticSlotDateTime(coordinator, coordinator.entry)

        assert entity.native_value == Cache.timestamp_for(Cache.index_for(target))


class TestAsyncSetValue:
    """Given `async_set_value` is called (ADR-004 §2a), When the chosen
    timestamp is within the forecast horizon, Then it pins the
    diagnosed slot; when it falls beyond that horizon, Then it raises
    `HomeAssistantError` and leaves the pin untouched, mirroring the
    original service's own validation (the same `bool` return from
    `coordinator.pin_diagnostic_slot()` either way)."""

    def test_pins_a_valid_in_horizon_timestamp(self) -> None:
        coordinator, _hass = _make_coordinator()
        entity = ShadyDiagnosticSlotDateTime(coordinator, coordinator.entry)
        target = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)

        _run(entity.async_set_value(target))

        assert coordinator._pinned_slot_index == Cache.index_for(target)

    def test_raises_home_assistant_error_beyond_horizon(self) -> None:
        coordinator, _hass = _make_coordinator()
        entity = ShadyDiagnosticSlotDateTime(coordinator, coordinator.entry)
        far_future = datetime(2026, 7, 1, tzinfo=UTC)

        raised = False
        try:
            _run(entity.async_set_value(far_future))
        except HomeAssistantError:
            raised = True

        assert raised
        # Rejected -- no state change.
        assert coordinator._pinned_slot_index is None


class TestUniqueId:
    def test_unique_id_is_entry_scoped(self) -> None:
        coordinator, _hass = _make_coordinator()
        entity = ShadyDiagnosticSlotDateTime(coordinator, coordinator.entry)

        assert coordinator.entry.entry_id in entity._attr_unique_id
