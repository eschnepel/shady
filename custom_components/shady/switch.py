"""`switch.py` — `ShadyFollowDiagnosticSlotSwitch`, one per config entry
(ADR-004 §2g, `TASK-0037-patch-4`): toggles the diagnosed slot (every
diagnostic sensor, ADR-004 §2) between **following** the newest
complete 5-minute slot (on, the default) and staying **pinned** to one
chosen slot (off).

Replaces `button.py`'s short-lived `ShadyClearDiagnosticSlotButton`
(ADR-004 §2f): a stateless one-shot action could not show whether the
slot was currently pinned or following, whereas this switch's own state
*is* that fact. It is `datetime.py`'s `ShadyDiagnosticSlotDateTime`'s
companion — that entity shows (and, when set, pins) the slot itself;
this one only says whether the coordinator keeps moving it.

- **On:** `coordinator.set_follow_latest_diagnostic_slot(True)` — the
  slot jumps to the newest complete one immediately, then is set again on
  every 5-minute tick.
- **Off:** `coordinator.set_follow_latest_diagnostic_slot(False)` — pins
  the slot exactly as `ShadyDiagnosticSlotDateTime` currently shows it;
  switching off never moves anything.
- Setting `ShadyDiagnosticSlotDateTime` to a chosen timestamp pins too,
  so this switch then reads off (at its next poll — like every entity in
  this integration it uses Home Assistant's default polling; there is no
  coordinator-to-entity push mechanism, `sensor.py`'s own scope note).

Thin HA glue only (ADR-000 §3): no business logic lives here — reading
and changing the pinned/following state are `coordinator.py`'s own
methods. Neither call can itself fail (no timestamp to validate, unlike
a pin), so no error handling is needed here.

Platform-level `async_setup_entry` only (matching `sensor.py`/
`select.py`/`button.py`/`datetime.py`'s own established scope note):
`custom_components/shady/__init__.py`'s integration-level setup, which
actually builds `hass.data[DOMAIN][entry.entry_id]` and forwards this
platform, is `TASK-0016`'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.switch import SwitchEntity

from .const import DOMAIN
from .device import device_info

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShadyCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the one `ShadyFollowDiagnosticSlotSwitch` for this config entry.

    Reads the already-constructed `ShadyCoordinator` out of
    `hass.data[DOMAIN][entry.entry_id]` — built by `__init__.py`
    (`TASK-0016`), not by this function.
    """
    coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShadyFollowDiagnosticSlotSwitch(coordinator, entry)])


class ShadyFollowDiagnosticSlotSwitch(SwitchEntity):  # type: ignore[misc]
    """One auto-follow toggle per config entry (ADR-004 §2g) — there is
    exactly one diagnosed-slot state config-entry-wide, not one per
    diagnostic sensor, so this entity is not itself entity-targeted at
    any sensor either. `on` ⇔ the diagnosed slot follows the newest
    complete slot; `off` ⇔ it is pinned."""

    _attr_name = "Follow Latest Diagnostic Slot"

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_follow_diagnostic_slot_{entry.entry_id}"
        self._attr_device_info = device_info(entry)

    @property
    def is_on(self) -> bool:
        return self._coordinator.is_following_latest_diagnostic_slot()

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._coordinator.set_follow_latest_diagnostic_slot(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._coordinator.set_follow_latest_diagnostic_slot(False)
