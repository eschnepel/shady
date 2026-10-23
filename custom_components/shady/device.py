"""`device.py` — the single `device_info()` helper every entity
platform (`sensor.py`, `button.py`, `select.py`) calls to attach its
entities to one shared Home Assistant device per config entry, rather
than each platform building its own `DeviceInfo` (mirrors this
project's established one-helper-per-concern module split — see
`forecast_adjust.py`/`yield_correction.py`/`string_computation.py`).
Every entity across every platform for the same config entry passes
the identical `entry` through to this one function, so Home Assistant
groups them under a single device entry — previously nothing did,
which is why no Shady device ever appeared on Home Assistant's own
Settings -> Devices & Services -> Devices page; every entity existed,
config-entry-scoped, but device-less.

`entry_type=DeviceEntryType.SERVICE`, not `None` (the default for a
physical product): this "device" is Shady's own computed forecast for
one config entry, not a piece of hardware — the same reasoning any
other computation-only integration uses for its one virtual device.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry


def device_info(entry: ConfigEntry) -> DeviceInfo:
    """One `DeviceInfo`, identified by `entry.entry_id` alone (ADR-000
    §3's "no config entry ever spans more than one device" scope — a
    second config entry, e.g. a second PV installation, gets its own,
    separate device). `name` follows the config entry's own title
    (whatever the user set/accepted during the config flow), matching
    how the entry itself already appears in the UI elsewhere.
    """
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Shady",
        model="Shading-Adjusted PV Forecast",
        entry_type=DeviceEntryType.SERVICE,
    )
