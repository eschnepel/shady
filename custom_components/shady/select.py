"""`select.py` — `ShadyDiagnosticModeSelect`, one per config entry
(ADR-004 §1, TASK-0015b): gates every diagnostic sensor and their extra
per-string fitting cost.

Thin HA glue only (ADR-000 §3): the select itself holds no diagnostic
logic — it reads `const.py`'s `DIAGNOSTIC_MODES` for its option list and
delegates the actual selection to `coordinator.py`'s `active_diagnostic_
mode()`/`set_active_diagnostic_mode()`. Default `"off"` (ADR-004 §1) —
every diagnostic sensor reports `state: "disabled"` and the coordinator
performs no extra fitting until this is changed.

A `select`, not a `switch` (ADR-004's 2026-08-30 amendment,
`TASK-0015`'s original scope) — there is no `switch.py` anywhere in this
project; a second diagnostic mode (ADR-013's sketched future modes)
needs no new entity type, only a new `const.py` option and
`coordinator.py` registry entry.

Platform-level `async_setup_entry` only (ADR-000 §3, matching `sensor.py`/
`button.py`'s own established scope note): `custom_components/shady/
__init__.py`'s integration-level setup, which actually builds
`hass.data[DOMAIN][entry.entry_id]` and forwards this platform, is
`TASK-0016`'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.components.select import SelectEntity

from .const import DIAGNOSTIC_MODES, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import ShadyCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Add the one `ShadyDiagnosticModeSelect` for this config entry.

    Reads the already-constructed `ShadyCoordinator` out of
    `hass.data[DOMAIN][entry.entry_id]` — built by `__init__.py`
    (`TASK-0016`), not by this function.
    """
    coordinator: ShadyCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ShadyDiagnosticModeSelect(coordinator, entry)])


class ShadyDiagnosticModeSelect(SelectEntity):  # type: ignore[misc]
    """One diagnostic-mode select per config entry (ADR-004 §1) —
    `const.py`'s `DIAGNOSTIC_MODES` is the entire option list, so a
    second mode (ADR-013) needs no change here."""

    _attr_name = "Diagnostic Mode"

    def __init__(self, coordinator: ShadyCoordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{DOMAIN}_diagnostic_mode_{entry.entry_id}"
        self._attr_options = list(DIAGNOSTIC_MODES)

    @property
    def current_option(self) -> str:
        return self._coordinator.active_diagnostic_mode()

    async def async_select_option(self, option: str) -> None:
        self._coordinator.set_active_diagnostic_mode(option)
