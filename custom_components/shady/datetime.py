"""`datetime.py` — `ShadyDiagnosticSlotDateTime`, one per config entry
(ADR-004 §2a/§2f/§2g): shows, and lets a person pin, the 5-minute slot
every diagnostic sensor (ADR-004 §2) is currently diagnosing.

Supersedes the original `shady.select_diagnostic_slot` service (ADR-004
§2a as first written) with a native `datetime` entity — a Lovelace-
pickable input instead of a Developer Tools -> Actions call, matching
this project's existing thin-entity-glue platforms (`select.py`,
`button.py`) rather than a bespoke service for what is, underneath,
just one more piece of per-config-entry state.

`native_value` is **always** the currently-configured diagnosed slot's
start timestamp (`coordinator.py`'s `diagnostic_slot_timestamp()`),
whether pinned or following the newest complete slot (ADR-004 §2g) —
never `None`/`unknown`. While following, the coordinator sets that
value on every 5-minute tick, so a dashboard shows the "as of" moment
of every diagnostic sensor by displaying this entity, with no template
logic of its own. `async_set_value` pins the chosen slot via
`pin_diagnostic_slot()` — which also switches following off, so the
companion `switch.py` toggle reads off from then on — raising
`HomeAssistantError` if the chosen timestamp falls beyond the available
forecast horizon (ADR-004 §2a), the same rejection
`pin_diagnostic_slot()` itself already signals via its `bool` return,
just surfaced as an entity-service error here.

Going back to following is deliberately **not** done through this
entity: Home Assistant's own `datetime` domain has no "clear to
unknown" affordance anywhere in its frontend (its more-info dialog
always constructs a new value from the entity's current one and feeds a
concrete `Date` back to `datetime.set_value` — seen directly in the
frontend's own `more-info-datetime` dialog). `switch.py`'s companion
`ShadyFollowDiagnosticSlotSwitch` (ADR-004 §2g) is that path instead.

Thin HA glue only (ADR-000 §3): no business logic lives here — pinning
and reading the slot are `coordinator.py`'s own methods.

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
    """One diagnosed-slot entity per config entry (ADR-004 §2a/§2g) —
    there is exactly one diagnosed-slot state config-entry-wide, not
    one per diagnostic sensor, so this entity is not itself entity-
    targeted at any sensor either."""

    _attr_name = "Diagnostic Slot"

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_diagnostic_slot_{entry.entry_id}"
        self._attr_device_info = device_info(entry)

    @property
    def native_value(self) -> datetime:
        return self._coordinator.diagnostic_slot_timestamp()

    async def async_set_value(self, value: datetime) -> None:
        if not self._coordinator.pin_diagnostic_slot(value):
            raise HomeAssistantError(
                f"{value.isoformat()} is beyond the available forecast horizon"
            )
