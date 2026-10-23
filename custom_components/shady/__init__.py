"""Shady – Shading-Adjusted PV Forecast integration.

Integration-level setup: constructs the `ShadyCoordinator`, stores it in
`hass.data[DOMAIN][entry.entry_id]`, forwards this config entry's
platforms (`sensor`/`select`/`button`/`datetime`/`switch`), registers
`http_export.py`'s one `HomeAssistantView` (ADR-015, `TASK-0038` —
guarded to run at most once per `hass`, not once per config entry, see
`_register_http_view_once` below), and restores restart-persisted
energy-integral state (ADR-005 §5/§6) — thin HA glue only (ADR-000 §3),
no business logic of its own. The diagnosed-slot pin (ADR-004
§2a/§2f/§2g) is entity-only as of `datetime.py`'s
`ShadyDiagnosticSlotDateTime`/`switch.py`'s
`ShadyFollowDiagnosticSlotSwitch` — this module registers no domain-wide
service of its own (the original `shady.select_diagnostic_slot` service
this superseded is gone, not merely deprecated).

**Startup ordering (ADR-002 §1a, the reason this module exists as a
real task rather than a trivial wire-up):** a config entry's referenced
entities (per-string actual-yield; per-string resolved baseline, if
configured) may not exist yet in `hass.states` at `async_setup_entry`
time — Home Assistant gives no ordering guarantee between custom
components' own setup. `ShadyCoordinator.missing_required_entities()`
is the check; this module only decides *when* to call it and what to do
with the result:

- `hass.is_running` already `True` (reload, or Shady sets up after HA
  finished starting): check immediately. Missing → raise
  `ConfigEntryNotReady` (HA's own backoff-retry loop handles the rest;
  no bespoke timer here). The coordinator constructed to run this one
  check is never stored or handed a platform — `missing_required_
  entities()` is itself a `ShadyCoordinator` method (ADR-002 §1a: this
  module deliberately does not re-derive per-string entity IDs a second
  time), so a real instance must exist to call it, but it is
  `shutdown()` immediately after, cancelling every listener/schedule
  its own `__init__` already registered, before being discarded — from
  the outside, nothing about this attempt outlives the failed call.
- `hass.is_running` still `False` (HA itself still starting): this is
  expected, not an error. Build `hass.data`, forward platforms, and
  restore energy state immediately regardless — Shady's own entities
  register on the normal schedule either way — but defer the
  coordinator's startup fit (ADR-002 §1) via `async_at_started`, which
  must not itself be awaited here (Shady's own setup is part of what HA
  is waiting to finish before it reports "started"). If entities are
  still missing once that deferred callback fires, log a warning and
  hand back to HA's own `ConfigEntryNotReady`/backoff path via
  `async_schedule_reload` after a short delay, rather than inventing a
  second retry mechanism.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.start import async_at_started

from .const import DOMAIN
from .coordinator import ShadyCoordinator
from .http_export import ShadyExportCsvView

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "select", "button", "datetime", "switch"]

# ADR-002 §1a, step 3: a short grace period before handing back to HA's
# own ConfigEntryNotReady/backoff path once the deferred startup fit
# still finds required entities missing after Home Assistant itself
# reports fully started — not a bespoke retry loop, just one delayed
# hand-off, rejoining the standard path via the reload's own re-run of
# this same function (which lands on the `hass.is_running` branch
# directly by then).
_MISSING_ENTITIES_RELOAD_DELAY_S: float = 30.0

# `hass.data[DOMAIN]` key for the "has `ShadyExportCsvView` already been
# registered for this `hass`" guard (ADR-015 §1/§4, `TASK-0038`) --
# distinct from every `entry.entry_id` key already stored there, since
# it tracks a `hass`-wide fact, not a per-config-entry one.
_HTTP_VIEW_REGISTERED_KEY = "_http_view_registered"


def _register_http_view_once(hass: HomeAssistant) -> None:
    """`hass.http.register_view` is HA's own view registry, keyed by
    URL pattern -- calling it twice for the same view (e.g. a second
    Shady config entry's own `async_setup_entry` run) would register a
    second, dead route behind the first. The `{config_entry_id}` URL
    segment already lets one registration serve every config entry, so
    this runs at most once per `hass`, guarded by
    `_HTTP_VIEW_REGISTERED_KEY` above rather than relying on
    `hass.http.register_view` itself being idempotent (it isn't)."""
    if hass.data[DOMAIN].get(_HTTP_VIEW_REGISTERED_KEY):
        return
    hass.http.register_view(ShadyExportCsvView())
    hass.data[DOMAIN][_HTTP_VIEW_REGISTERED_KEY] = True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shady from a config entry (ADR-002 §1/§1a/§5)."""
    hass.data.setdefault(DOMAIN, {})
    _register_http_view_once(hass)

    coordinator = ShadyCoordinator(hass, entry)

    if hass.is_running:
        missing = coordinator.missing_required_entities()
        if missing:
            # See module docstring: this instance is never retained.
            coordinator.shutdown()
            raise ConfigEntryNotReady(
                f"Shady: required entities not yet available: {', '.join(missing)}"
            )
        hass.data[DOMAIN][entry.entry_id] = coordinator
        await coordinator.async_restore_energy_state()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        await coordinator.async_startup()
        return True

    # Home Assistant is still starting (ADR-002 §1a, point 2): missing
    # entities are expected here, not an error — build hass.data and
    # forward platforms unconditionally, deferring only the startup fit.
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await coordinator.async_restore_energy_state()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def _async_handle_started(_hass: HomeAssistant) -> None:
        still_missing = coordinator.missing_required_entities()
        if still_missing:
            _LOGGER.warning(
                "Shady config entry %s still missing required entities (%s) "
                "after Home Assistant finished starting; scheduling a reload",
                entry.entry_id,
                ", ".join(still_missing),
            )
            await asyncio.sleep(_MISSING_ENTITIES_RELOAD_DELAY_S)
            hass.config_entries.async_schedule_reload(entry.entry_id)
            return
        await coordinator.async_startup()

    async_at_started(hass, _async_handle_started)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator: ShadyCoordinator | None = hass.data[DOMAIN].pop(entry.entry_id, None)
        if coordinator is not None:
            coordinator.shutdown()
    return unloaded
