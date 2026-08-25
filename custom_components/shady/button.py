"""`button.py` — `ShadyRecalculateButton`, one per config entry
(ADR-002 §1/§5, TASK-0011): a manual trigger for the exact same refit
routine the midnight schedule calls (`ShadyCoordinator.async_refit`).

Thin HA glue only (ADR-000 §3): the button itself does no fitting — it
delegates entirely to `coordinator.py`. Any exception during refit is
logged and swallowed, never raised (ADR-000 §8 — a background failure,
not a request/response cycle with a caller to propagate to).

Platform-level `async_setup_entry` only (this task's corrected scope —
see `tasks/TASK-0011-forecast-sensor-and-recalculate-button.md`'s Goal):
`custom_components/shady/__init__.py`'s integration-level setup, which
actually builds `hass.data[DOMAIN][entry.entry_id]` and forwards this
platform, is `TASK-0016`'s.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.button import ButtonEntity

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShadyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the one `ShadyRecalculateButton` for this config entry.

    Reads the already-constructed `ShadyCoordinator` out of
    `hass.data[DOMAIN][entry.entry_id]` — built by `__init__.py`
    (`TASK-0016`), not by this function.
    """
    coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShadyRecalculateButton(coordinator, entry)])


class ShadyRecalculateButton(ButtonEntity):  # type: ignore[misc]
    """One diagnostic button per config entry — manually triggers a
    full recalibration (ADR-002 §1/§5), the same code path the midnight
    schedule uses (`ShadyCoordinator.async_refit`)."""

    _attr_name = "Recalculate"

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_recalculate_{entry.entry_id}"

    async def async_press(self) -> None:
        try:
            await self._coordinator.async_refit()
        except Exception:  # deliberately broad — ADR-000 §8, logged and swallowed
            _LOGGER.exception("Shady manual recalculation failed for %s", self._attr_unique_id)
