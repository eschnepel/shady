"""`sensor.py` — `ShadyForecastSensor`, one per configured string
(ADR-002 §3, ADR-002 §5, TASK-0011).

Thin HA glue only (ADR-000 §3): every value is read directly from
`coordinator.cache` via `Cache.get_time_range` — no correction,
aggregation, or other business-logic math of its own. That math already
happened in `coordinator.py` (ADR-002 §2/§3) by the time anything lands
in the cache under `coordinator.forecast_sensor_id(string_index)`.

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
from homeassistant.const import UnitOfPower

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
    """Add one `ShadyForecastSensor` per configured string.

    Reads the already-constructed `ShadyCoordinator` out of
    `hass.data[DOMAIN][entry.entry_id]` — built by `__init__.py`
    (`TASK-0016`), not by this function.
    """
    coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ShadyForecastSensor(coordinator, entry, string_index, string_name)
        for string_index, string_name in coordinator.strings()
    )


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
