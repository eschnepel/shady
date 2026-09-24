"""`datetime.py` — `ShadyDiagnosticSlotDateTime`, one per config entry
(ADR-004 §2a/§2f): pins the diagnosed slot (every diagnostic sensor,
ADR-004 §2) to the 5-minute slot containing a chosen timestamp, instead
of auto-tracking the last complete slot.

Supersedes the original `shady.select_diagnostic_slot` service (ADR-004
§2a as first written) with a native `datetime` entity — a Lovelace-
pickable input instead of a Developer Tools -> Actions call, matching
this project's existing thin-entity-glue platforms (`select.py`,
`button.py`) rather than a bespoke service for what is, underneath,
just one more piece of per-config-entry state. `native_value` reads
`coordinator.py`'s `pinned_diagnostic_slot()` (`None` while auto-
tracking); `async_set_value` pins it via `pin_diagnostic_slot()`,
raising `HomeAssistantError` if the chosen timestamp falls beyond the
available forecast horizon (ADR-004 §2a) — the same rejection
`pin_diagnostic_slot()` itself already signals via its `bool` return,
just surfaced as an entity-service error here instead of a
`ServiceValidationError`.

Clearing the pin (going back to auto-tracking) is deliberately **not**
done through this entity: Home Assistant's own `datetime` domain has no
"clear to unknown" affordance anywhere in its frontend (its more-info
dialog always constructs a new value from the entity's current one, and
never offers to unset it) — seen directly in the frontend's own
`more-info-datetime` dialog, which always feeds a concrete `Date`
back to `datetime.set_value`. `button.py`'s companion
`ShadyClearDiagnosticSlotButton` (ADR-004 §2f) is the clear
mechanism instead, mirroring how `ShadyRecalculateButton` already
covers a different single-purpose trigger via the same platform.

Thin HA glue only (ADR-000 §3): no business logic lives here — pinning/
clearing/reading the pin are all `coordinator.py`'s own methods.

Platform-level `async_setup_entry` only (matching `sensor.py`/
`select.py`/`button.py`'s own established scope note): `custom_
components/shady/__init__.py`'s integration-level setup, which actually
builds `hass.data[DOMAIN][entry.entry_id]` and forwards this platform,
is `TASK-0016`'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.datetime import DateTimeEntity
from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .device import device_info

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShadyCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the one `ShadyDiagnosticSlotDateTime` for this config entry.

    Reads the already-constructed `ShadyCoordinator` out of
    `hass.data[DOMAIN][entry.entry_id]` — built by `__init__.py`
    (`TASK-0016`), not by this function.
    """
    coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShadyDiagnosticSlotDateTime(coordinator, entry)])


class ShadyDiagnosticSlotDateTime(DateTimeEntity):  # type: ignore[misc]
    """One diagnostic-slot pin per config entry (ADR-004 §2a/§2f) —
    there is exactly one diagnosed-slot state config-entry-wide, not
    one per diagnostic sensor, so this entity is not itself entity-
    targeted at any sensor either."""

    _attr_name = "Diagnostic Slot"

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_diagnostic_slot_{entry.entry_id}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> datetime | None:
        return self._coordinator.pinned_diagnostic_slot()

    async def async_set_value(self, value: datetime) -> None:
        if not self._coordinator.pin_diagnostic_slot(value):
            raise HomeAssistantError(
                f"{value.isoformat()} is beyond the available forecast horizon"
            )
