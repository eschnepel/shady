from __future__ import annotations

import asyncio
from dataclasses import dataclass

from ._module_loader import load_module


button_module = load_module("shady.button", "button.py")


@dataclass
class _FakeCoordinator:
    calls: int = 0
    fail: bool = False

    async def async_refit(self) -> None:
        self.calls += 1
        if self.fail:
            raise RuntimeError("boom")


def test_button_triggers_shared_refit_path():
    coordinator = _FakeCoordinator()
    button = button_module.ShadyRecalculateButton(coordinator, type("Entry", (), {"entry_id": "entry-1", "title": "Shady"})())

    asyncio.run(button.async_press())

    assert coordinator.calls == 1


def test_button_swallows_refit_exceptions():
    coordinator = _FakeCoordinator(fail=True)
    button = button_module.ShadyRecalculateButton(coordinator, type("Entry", (), {"entry_id": "entry-1", "title": "Shady"})())

    asyncio.run(button.async_press())

    assert coordinator.calls == 1
