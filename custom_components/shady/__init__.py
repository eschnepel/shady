"""Shady – Shading-Adjusted PV Forecast integration.

Placeholder skeleton for the brainstorming phase. The actual coordinator/
platform wiring follows once the core logic (providers/,
yield_correction.py, regression/, forecast_adjust.py, aggregation.py,
cache.py) is implemented per ADR-000 §3.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shady from a config entry. TODO: wire up the coordinator."""
    hass.data.setdefault(DOMAIN, {})
    # TODO: instantiate ShadyCoordinator and store it in hass.data,
    # once coordinator.py exists (see ADR-000 §3).
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
