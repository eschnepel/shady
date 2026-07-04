"""Shady – Shading-Adjusted PV Forecast integration.

Platzhalter-Skeleton für die Brainstorming-Phase. Die eigentliche
Coordinator-/Platform-Verdrahtung folgt, sobald die Kernlogik
(sun_geometry.py, horizon_profile.py, shading.py, forecast_adjust.py)
gemäß ADR-000 §3 entworfen ist.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shady from a config entry. TODO: Coordinator einhängen."""
    hass.data.setdefault(DOMAIN, {})
    # TODO: ShadyCoordinator instanzieren und in hass.data ablegen,
    # sobald coordinator.py existiert (siehe ADR-000 §3).
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
