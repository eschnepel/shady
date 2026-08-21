from __future__ import annotations

import asyncio
from types import SimpleNamespace

from ._module_loader import load_module


shady_init = load_module("shady", "__init__.py")


class _FakeCoordinator:
    def __init__(self, hass, cache, config, baseline_providers, temperature_providers=None) -> None:
        self.hass = hass
        self.cache = cache
        self.config = config
        self.baseline_providers = baseline_providers
        self.temperature_providers = temperature_providers
        self.setup_calls = 0
        self.shutdown_calls = 0

    async def async_setup(self) -> None:
        self.setup_calls += 1

    async def async_shutdown(self) -> None:
        self.shutdown_calls += 1


def test_async_setup_entry_stores_coordinator_and_forwards_platforms(monkeypatch):
    forwarded: list[tuple[str, ...]] = []
    hass = SimpleNamespace(
        data={},
        states=SimpleNamespace(async_all=lambda: []),
        config_entries=SimpleNamespace(
            async_forward_entry_setups=lambda entry, platforms: forwarded.append(tuple(platforms))
            or asyncio.sleep(0),
            async_unload_platforms=lambda entry, platforms: asyncio.sleep(0),
        ),
    )
    entry = SimpleNamespace(
        entry_id="entry-1",
        title="Shady",
        data={
            shady_init.CONF_WINDOW_DAYS: 28,
            shady_init.CONF_TEMPERATURE_SOURCE_ENTITY_ID: "weather.home",
            shady_init.CONF_STRINGS: [
                {
                    "id": "string-1",
                    "name": "Roof",
                    "baseline_entity_id": "weather.home",
                    "baseline_attribute": "forecast",
                    "actual_yield_entity_id": "sensor.actual",
                }
            ],
        },
    )

    monkeypatch.setattr(shady_init, "ShadyCoordinator", _FakeCoordinator)

    result = asyncio.run(shady_init.async_setup_entry(hass, entry))

    assert result is True
    assert forwarded == [("button", "sensor", "switch")]
    assert hass.data[shady_init.DOMAIN][entry.entry_id].setup_calls == 1
    assert "weather.home" in hass.data[shady_init.DOMAIN][entry.entry_id].temperature_providers


def test_async_unload_entry_removes_coordinator(monkeypatch):
    hass = SimpleNamespace(
        data={shady_init.DOMAIN: {}},
        config_entries=SimpleNamespace(
            async_forward_entry_setups=lambda entry, platforms: asyncio.sleep(0),
            async_unload_platforms=lambda entry, platforms: asyncio.sleep(0),
        ),
    )
    entry = SimpleNamespace(entry_id="entry-1", title="Shady", data={})
    coordinator = _FakeCoordinator(hass, None, {}, {})
    hass.data[shady_init.DOMAIN][entry.entry_id] = coordinator

    async def _unload(entry_obj, platforms):
        return True

    hass.config_entries.async_unload_platforms = _unload

    result = asyncio.run(shady_init.async_unload_entry(hass, entry))

    assert result is True
    assert entry.entry_id not in hass.data[shady_init.DOMAIN]
    assert coordinator.shutdown_calls == 1
