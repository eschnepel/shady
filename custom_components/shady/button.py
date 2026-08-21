"""Manual recalculation button for Shady."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory

from .const import DOMAIN
from .coordinator import ShadyCoordinator

_LOGGER = logging.getLogger(__name__)

__all__ = ["ShadyRecalculateButton"]


class ShadyRecalculateButton(ButtonEntity):  # type: ignore[misc]
    """Trigger the coordinator's shared refit path."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._entry = entry
        self._attr_name = f"{entry.title} Recalculate"
        self._attr_unique_id = f"{entry.entry_id}-recalculate"

    async def async_press(self) -> None:
        try:
            await self._coordinator.async_refit()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Failed to recalculate Shady entry %s", self._entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: Any
) -> None:
    """Add the manual recalculation button."""

    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShadyRecalculateButton(coordinator, entry)])
