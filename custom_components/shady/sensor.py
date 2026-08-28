"""`sensor.py` — `ShadyForecastSensor`, one per configured string
(ADR-002 §3, ADR-002 §5, TASK-0011); plus the six config-entry-level
aggregate sensors (ADR-005, TASK-0012): `ShadyPvSumSensor`,
`ShadyFcSumSensor`, `ShadyFcDaySumSensor`, `ShadyFcRemainingTodaySensor`,
`ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor`.

Thin HA glue only (ADR-000 §3): every value is read directly from
`coordinator.py` — either a plain coordinator method call
(`pv_sum()`/`fc_sum()`/`fc_day_array()`/`fc_day_energy_total()`/
`fc_remaining_energy()`, all poll-friendly) or, for the two
restart-persisted integral totals, `coordinator.cache.energy_total(...)`
directly. No correction, aggregation, or other business-logic math of
its own — that math already happened in `coordinator.py`/`aggregation.py`
by the time anything lands here.

Platform-level `async_setup_entry` only (this task's corrected scope —
see `tasks/TASK-0011-forecast-sensor-and-recalculate-button.md`'s Goal):
`custom_components/shady/__init__.py`'s integration-level setup, which
actually builds `hass.data[DOMAIN][entry.entry_id]` and forwards this
platform, is `TASK-0016`'s.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfEnergy, UnitOfPower

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShadyCoordinator

_ONE_DAY = timedelta(days=1)
_LAST_SLOT_OF_DAY = timedelta(hours=23, minutes=55)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add one `ShadyForecastSensor` per configured string, plus the six
    config-entry-level aggregate sensors (ADR-005, one of each per entry).

    Reads the already-constructed `ShadyCoordinator` out of
    `hass.data[DOMAIN][entry.entry_id]` — built by `__init__.py`
    (`TASK-0016`), not by this function.
    """
    coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list[SensorEntity] = [
        ShadyForecastSensor(coordinator, entry, string_index, string_name)
        for string_index, string_name in coordinator.strings()
    ]
    entities.extend(
        [
            ShadyPvSumSensor(coordinator, entry),
            ShadyFcSumSensor(coordinator, entry),
            ShadyFcDaySumSensor(coordinator, entry),
            ShadyFcRemainingTodaySensor(coordinator, entry),
            ShadyPvEnergyIntegralSensor(coordinator, entry),
            ShadyFcEnergyIntegralSensor(coordinator, entry),
        ]
    )
    async_add_entities(entities)


class ShadyForecastSensor(SensorEntity):  # type: ignore[misc]
    """The corrected forecast for one string, today (remaining) +
    tomorrow (ADR-002 §3's horizon).

    `native_value` is the current slot's corrected value; `today`/
    `tomorrow` attributes expose the full 288-slot arrays for charting
    (docs/architecture.mmd's `FCSensor` node: "slot array, per string").
    Both are read straight through `coordinator.cache.get_time_range` —
    a slot with nothing pushed yet (or already invalidated) simply shows
    as `None`, exactly what is actually cached, never synthesized.
    """

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    # No push mechanism from `coordinator.py` to this entity (ADR-002's
    # coordinator is a bespoke `hass`-driven scheduler/listener set, not
    # `homeassistant.helpers.update_coordinator.DataUpdateCoordinator`,
    # so there is no `CoordinatorEntity` to subscribe through) — this
    # task's own scope decision (see Delivered Artifacts) is to poll
    # instead, HA's default (`should_poll=True`) when left unset.

    def __init__(
        self,
        coordinator: ShadyCoordinator,
        entry: ConfigEntry,
        string_index: int,
        string_name: str,
    ) -> None:
        self._coordinator = coordinator
        self._sensor_id = coordinator.forecast_sensor_id(string_index)
        self._attr_unique_id = self._sensor_id
        self._attr_name = f"{string_name} Forecast"
        # Injectable clock (a plain callable, not a `Mock`) — mirrors
        # `coordinator.py`'s own `_now` convention; tests substitute a
        # fixed value the same way `cache.py`'s `reference` parameter
        # and `coordinator._now` are used elsewhere for determinism.
        self._now: Callable[[], datetime] = lambda: datetime.now(UTC)

    def _today_start(self, now: datetime) -> datetime:
        return datetime(now.year, now.month, now.day, tzinfo=UTC)

    @property
    def native_value(self) -> float | None:
        now = self._now()
        values = self._coordinator.cache.get_time_range(
            [self._sensor_id], now, now, on_invalid="raw"
        )[self._sensor_id]
        value = values[0]
        return value if isinstance(value, float) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        now = self._now()
        today_start = self._today_start(now)
        tomorrow_start = today_start + _ONE_DAY

        def _day_array(day_start: datetime) -> list[float | None]:
            raw = self._coordinator.cache.get_time_range(
                [self._sensor_id],
                day_start,
                day_start + _LAST_SLOT_OF_DAY,
                on_invalid="raw",
            )[self._sensor_id]
            return [value if isinstance(value, float) else None for value in raw]

        return {
            "today": _day_array(today_start),
            "tomorrow": _day_array(tomorrow_start),
        }


class ShadyPvSumSensor(SensorEntity):  # type: ignore[misc]
    """ADR-005 §1: current actual yield, summed across every configured
    string. Zero math of its own — reads `coordinator.pv_sum()` on every
    poll, which itself is a plain state-tracking aggregate independent
    of the coordinator's fit/recompute cycle."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_pv_sum_{entry.entry_id}"
        self._attr_name = "PV Sum"

    @property
    def native_value(self) -> float | None:
        return self._coordinator.pv_sum()


class ShadyFcSumSensor(SensorEntity):  # type: ignore[misc]
    """ADR-005 §2: current-slot corrected forecast, summed across every
    configured string. Reads `coordinator.fc_sum(now)` on every poll —
    updates whenever the underlying per-string forecasts do, simply by
    virtue of being read fresh from `coordinator.cache` each time."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_fc_sum_{entry.entry_id}"
        self._attr_name = "Forecast Sum"
        self._now: Callable[[], datetime] = lambda: datetime.now(UTC)

    @property
    def native_value(self) -> float | None:
        return self._coordinator.fc_sum(self._now())


class ShadyFcDaySumSensor(SensorEntity):  # type: ignore[misc]
    """ADR-005 §3: corrected forecast, summed across every configured
    string, for every one of today's 288 slots. State is the implied
    daily energy total (Wh); `slot_timestamps`/`slot_values` expose the
    full arrays for charting, mirroring `ShadyForecastSensor`'s own
    `today`/`tomorrow` attribute convention."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_fc_day_sum_{entry.entry_id}"
        self._attr_name = "Forecast Day Total"
        self._now: Callable[[], datetime] = lambda: datetime.now(UTC)

    @property
    def native_value(self) -> float:
        return self._coordinator.fc_day_energy_total(self._now())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        slot_timestamps, slot_values = self._coordinator.fc_day_array(self._now())
        return {
            "slot_timestamps": [timestamp.isoformat() for timestamp in slot_timestamps],
            "slot_values": slot_values,
        }


class ShadyFcRemainingTodaySensor(SensorEntity):  # type: ignore[misc]
    """ADR-005 §4: expected remaining energy today — pure post-processing
    of `ShadyFcDaySumSensor`'s own array, restricted to slots at/after
    "now"; no correction logic or data-retention mechanism of its own."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_fc_remaining_today_{entry.entry_id}"
        self._attr_name = "Forecast Remaining Today"
        self._now: Callable[[], datetime] = lambda: datetime.now(UTC)

    @property
    def native_value(self) -> float:
        return self._coordinator.fc_remaining_energy(self._now())


class ShadyPvEnergyIntegralSensor(SensorEntity):  # type: ignore[misc]
    """ADR-005 §5: running Riemann-sum integral of `ShadyPvSumSensor`'s
    power over time, since midnight — restart-persisted (ADR-007 §1),
    unlike every other sensor in this design. Reads `coordinator.cache
    .energy_total("pv")` directly; `coordinator.py`'s
    `_accumulate_energy` is what actually advances this total, on every
    actual-yield state change."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_pv_energy_integral_{entry.entry_id}"
        self._attr_name = "PV Energy Today"

    @property
    def native_value(self) -> float:
        return self._coordinator.cache.energy_total("pv")


class ShadyFcEnergyIntegralSensor(SensorEntity):  # type: ignore[misc]
    """ADR-005 §6: the same integral treatment as
    `ShadyPvEnergyIntegralSensor`, but accumulating `ShadyFcSumSensor`'s
    corrected-forecast power instead — directly comparable against §5's
    actual figure at any point in the day. Advanced by `coordinator.py`'s
    `_accumulate_energy` on every recompute trigger (recalibration or a
    baseline-provider update), not on a fixed poll."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_fc_energy_integral_{entry.entry_id}"
        self._attr_name = "Forecast Energy Today"

    @property
    def native_value(self) -> float:
        return self._coordinator.cache.energy_total("fc")
