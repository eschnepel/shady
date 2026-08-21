"""Forecast and aggregate sensors for Shady."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfPower
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .const import CONF_NAME, CONF_STRINGS, DOMAIN
from .coordinator import ShadyCoordinator

__all__ = [
    "ShadyForecastSensor",
    "ShadyFcDaySumSensor",
    "ShadyFcEnergyIntegralSensor",
    "ShadyFcRemainingTodaySensor",
    "ShadyFcSumSensor",
    "ShadyDiagnosticsSensor",
    "ShadyDiagnosticsSumSensor",
    "ShadyPvEnergyIntegralSensor",
    "ShadyPvSumSensor",
]


class _CoordinatorSensorBase(SensorEntity):  # type: ignore[misc]
    def __init__(self, coordinator: ShadyCoordinator, name: str, unique_id: str) -> None:
        self._coordinator = coordinator
        self._remove_listener: CALLBACK_TYPE | None = None
        self._attr_name = name
        self._attr_unique_id = unique_id

    async def async_added_to_hass(self) -> None:
        self._remove_listener = self._coordinator.async_add_listener(self._handle_coordinator_update)

    async def async_will_remove_from_hass(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None

    @callback
    def _handle_coordinator_update(self) -> None:
        self.async_write_ha_state()


class ShadyForecastSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    """Thin per-string forecast sensor."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ShadyCoordinator, string_data: dict[str, Any]) -> None:
        self._string_data = dict(string_data)
        super().__init__(
            coordinator,
            f"{self._string_data.get(CONF_NAME, 'Shady')} Forecast",
            f"{self._string_data.get('id')}-forecast",
        )

    @property
    def available(self) -> bool:
        return bool(self._coordinator.get_forecast_series(str(self._string_data["id"])))

    @property
    def native_value(self) -> float | None:
        series = self._coordinator.get_forecast_series(str(self._string_data["id"]))
        if not series:
            return None
        return float(series[0][1])

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        series = self._coordinator.get_forecast_series(str(self._string_data["id"]))
        intraday = self._coordinator.get_intraday_snapshot(str(self._string_data["id"]))
        return {
            "forecast_timestamps": [timestamp.isoformat() for timestamp, _ in series],
            "forecast_values": [value for _, value in series],
            "intraday_ratio": intraday.get("intraday_ratio"),
            "intraday_state": intraday.get("intraday_state", "off"),
            "intraday_ramp_weight": intraday.get("intraday_ramp_weight", 0.0),
            "values_raw": intraday.get("values_raw", []),
            "intraday_blend_active": intraday.get("intraday_blend_active", False),
        }


class ShadyDiagnosticsSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    """Per-string diagnostics sensor."""

    def __init__(self, coordinator: ShadyCoordinator, string_data: dict[str, Any]) -> None:
        self._string_data = dict(string_data)
        super().__init__(
            coordinator,
            f"{self._string_data.get(CONF_NAME, 'Shady')} Diagnostics",
            f"{self._string_data.get('id')}-diagnostics",
        )

    @property
    def native_value(self) -> str:
        snapshot = self._coordinator.get_diagnostic_snapshot(str(self._string_data["id"]))
        return str(snapshot.get("state", "disabled"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self._coordinator.get_diagnostic_snapshot(str(self._string_data["id"]))
        if snapshot.get("state") == "disabled":
            return {}
        return {key: value for key, value in snapshot.items() if key != "state"}


class ShadyDiagnosticsSumSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    """Entry-level diagnostics aggregate sensor."""

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} Diagnostics Sum", f"{entry.entry_id}-diagnostics-sum")

    @property
    def native_value(self) -> str:
        snapshot = self._coordinator.get_diagnostic_sum_snapshot()
        return str(snapshot.get("state", "disabled"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        snapshot = self._coordinator.get_diagnostic_sum_snapshot()
        if snapshot.get("state") == "disabled":
            return {}
        return {key: value for key, value in snapshot.items() if key != "state"}


class ShadyPvSumSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} PV Sum", f"{entry.entry_id}-pv-sum")

    @property
    def native_value(self) -> float:
        value = self._coordinator.get_aggregate_value("pv_sum")
        return float(value or 0.0)


class ShadyFcSumSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} FC Sum", f"{entry.entry_id}-fc-sum")

    @property
    def native_value(self) -> float:
        value = self._coordinator.get_aggregate_value("fc_sum")
        return float(value or 0.0)


class ShadyFcDaySumSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} FC Day Sum", f"{entry.entry_id}-fc-day-sum")

    @property
    def native_value(self) -> float:
        value = self._coordinator.get_aggregate_value("fc_day_energy")
        return float(value or 0.0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "slot_timestamps": [
                timestamp.isoformat() for timestamp in self._coordinator.get_aggregate_value("fc_day_timestamps") or []
            ],
            "slot_values": list(self._coordinator.get_aggregate_value("fc_day_values") or []),
        }


class ShadyFcRemainingTodaySensor(_CoordinatorSensorBase):  # type: ignore[misc]
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} FC Remaining Today", f"{entry.entry_id}-fc-remaining")

    @property
    def native_value(self) -> float:
        value = self._coordinator.get_aggregate_value("fc_remaining_today")
        return float(value or 0.0)


class ShadyPvEnergyIntegralSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} PV Energy Today", f"{entry.entry_id}-pv-energy")

    @property
    def native_value(self) -> float:
        return self._coordinator.cache.get_integral_total("pv_energy")


class ShadyFcEnergyIntegralSensor(_CoordinatorSensorBase):  # type: ignore[misc]
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} FC Energy Today", f"{entry.entry_id}-fc-energy")

    @property
    def native_value(self) -> float:
        return self._coordinator.cache.get_integral_total("fc_energy")


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Callable[[list[SensorEntity]], None]
) -> None:
    """Add Shady sensors."""

    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = []
    for string_data in entry.data.get(CONF_STRINGS, []):
        entities.append(ShadyForecastSensor(coordinator, string_data))
        entities.append(ShadyDiagnosticsSensor(coordinator, string_data))
    entities.extend(
        [
            ShadyPvSumSensor(coordinator, entry),
            ShadyFcSumSensor(coordinator, entry),
            ShadyFcDaySumSensor(coordinator, entry),
            ShadyFcRemainingTodaySensor(coordinator, entry),
            ShadyDiagnosticsSumSensor(coordinator, entry),
            ShadyPvEnergyIntegralSensor(coordinator, entry),
            ShadyFcEnergyIntegralSensor(coordinator, entry),
        ]
    )
    async_add_entities(entities)
