"""Diagnostics switch for Shady."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

from .const import DOMAIN
from .coordinator import ShadyCoordinator

__all__ = ["ShadyDiagnosticsSwitch"]


class _CoordinatorSwitchBase(SwitchEntity):  # type: ignore[misc]
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


class ShadyDiagnosticsSwitch(_CoordinatorSwitchBase):  # type: ignore[misc]
    """Toggle diagnostics fitting and reporting."""

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, f"{entry.title} Diagnostics", f"{entry.entry_id}-diagnostics")

    @property
    def is_on(self) -> bool:
        return bool(self._coordinator.diagnostics_enabled)

    async def async_turn_on(self, **kwargs: object) -> None:
        self._coordinator.set_diagnostics_enabled(True)
        await self._coordinator.async_refresh_diagnostics()

    async def async_turn_off(self, **kwargs: object) -> None:
        self._coordinator.set_diagnostics_enabled(False)
        await self._coordinator.async_refresh_diagnostics()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Callable[[list[SwitchEntity]], None]
) -> None:
    """Add Shady diagnostics switches."""

    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShadyDiagnosticsSwitch(coordinator, entry)])
