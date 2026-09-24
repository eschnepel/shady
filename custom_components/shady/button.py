"""`button.py` — `ShadyRecalculateButton`, one per config entry
(ADR-002 §1/§5, TASK-0011): a manual trigger for the exact same refit
routine the midnight schedule calls (`ShadyCoordinator.async_refit`).
Also `ShadyClearDiagnosticSlotButton`, one per config entry (ADR-004
§2f): clears `datetime.py`'s `ShadyDiagnosticSlotDateTime` pin, since
the `datetime` domain itself has no "clear to unknown" affordance in
its own frontend (see `datetime.py`'s module docstring) — this button
is that pin's only clear path.

Thin HA glue only (ADR-000 §3): neither button holds business logic of
its own — both delegate entirely to `coordinator.py`. Any exception
during `ShadyRecalculateButton`'s refit is logged and swallowed, never
raised (ADR-000 §8 — a background failure, not a request/response cycle
with a caller to propagate to); `ShadyClearDiagnosticSlotButton`'s
`clear_diagnostic_slot()` call cannot itself fail (no timestamp to
validate, unlike a pin), so it needs no such guard.

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
from .device import device_info

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShadyCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add this config entry's buttons: `ShadyRecalculateButton` and
    `ShadyClearDiagnosticSlotButton`.

    Reads the already-constructed `ShadyCoordinator` out of
    `hass.data[DOMAIN][entry.entry_id]` — built by `__init__.py`
    (`TASK-0016`), not by this function.
    """
    coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            ShadyRecalculateButton(coordinator, entry),
            ShadyClearDiagnosticSlotButton(coordinator, entry),
        ]
    )


class ShadyRecalculateButton(ButtonEntity):  # type: ignore[misc]
    """One diagnostic button per config entry — manually triggers a
    full recalibration (ADR-002 §1/§5), the same code path the midnight
    schedule uses (`ShadyCoordinator.async_refit`)."""

    _attr_name = "Recalculate"

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_recalculate_{entry.entry_id}"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        try:
            await self._coordinator.async_refit()
        except Exception:  # deliberately broad — ADR-000 §8, logged and swallowed
            _LOGGER.exception("Shady manual recalculation failed for %s", self._attr_unique_id)


class ShadyClearDiagnosticSlotButton(ButtonEntity):  # type: ignore[misc]
    """One button per config entry (ADR-004 §2f) — clears `datetime.py`'s
    `ShadyDiagnosticSlotDateTime` pin, returning every diagnostic sensor
    to auto-tracking the last complete slot. The only clear path for
    that pin (see `datetime.py`'s module docstring for why the
    `datetime` domain itself cannot offer one)."""

    _attr_name = "Clear Diagnostic Slot"

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_clear_diagnostic_slot_{entry.entry_id}"
        self._attr_device_info = device_info(entry)

    async def async_press(self) -> None:
        self._coordinator.clear_diagnostic_slot()
