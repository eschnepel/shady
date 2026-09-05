"""Tests for `select.py`'s `ShadyDiagnosticModeSelect` (ADR-004 §1,
TASK-0015b).

`select.py` is HA-facing (real, non-`TYPE_CHECKING` import of
`homeassistant.components.select.SelectEntity`) — outside ADR-000 §6's
zero-mocking pure tier, but its own logic is thin enough (read
`const.py`'s option list; delegate `current_option`/
`async_select_option` straight to two coordinator methods) that it
needs neither the full `FakeHomeAssistant` recorder-stub convention
(`test_coordinator.py`) nor a real `ShadyCoordinator` — a hand-written
`-> Any`-typed stand-in exposing only the two methods `select.py` ever
calls, the same "fake object standing in for a strictly-typed
dependency" pattern `test_diagnostics_base.py`'s own `_stub_coordinator()`
already establishes, is enough to exercise every acceptance criterion.
Fully self-contained: registers its own minimal `homeassistant.
components.select` stub before file-path-loading `select.py`,
independent of any other test file's `sys.modules` state.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# -- minimal `homeassistant.components.select` stand-in ---------------------


class _FakeSelectEntity:
    """Real (non-`Mock`) stand-in for HA's `SelectEntity` — `select.py`
    only relies on it being an inheritable base class; no HA runtime
    behaviour (state writes, entity registry, ...) is exercised here."""


_select_module = ModuleType("homeassistant.components.select")
_select_module.SelectEntity = _FakeSelectEntity  # type: ignore[attr-defined]
sys.modules["homeassistant"] = ModuleType("homeassistant")
sys.modules["homeassistant.components"] = ModuleType("homeassistant.components")
sys.modules["homeassistant.components.select"] = _select_module

_const_mod = _load("const.py", "shady.const")
select = _load("select.py", "shady.select")


def _stub_coordinator(initial_mode: str = "off") -> Any:
    """A hand-written stand-in exposing only what `select.py` calls —
    `active_diagnostic_mode()`/`set_active_diagnostic_mode()` — nothing
    else `ShadyCoordinator` provides. `-> Any` so `mypy` doesn't demand
    a real `ShadyCoordinator` here, mirroring
    `test_diagnostics_base.py`'s own `_stub_coordinator()`."""

    class _StubCoordinator:
        def __init__(self) -> None:
            self._mode = initial_mode

        def active_diagnostic_mode(self) -> str:
            return self._mode

        def set_active_diagnostic_mode(self, mode: str) -> None:
            self._mode = mode

    return _StubCoordinator()


def _make_entry(entry_id: str = "entry123") -> Any:
    class _Entry:
        pass

    entry = _Entry()
    entry.entry_id = entry_id  # type: ignore[attr-defined]
    return entry


class TestOptionsListMatchesConstDiagnosticModes:
    """Given `const.py`'s `DIAGNOSTIC_MODES`, When
    `ShadyDiagnosticModeSelect` is constructed, Then its `options` list
    is exactly that tuple — adding a future mode (ADR-013) needs no
    change here, only a new `const.py` entry + registry entry."""

    def test_options_match_diagnostic_modes(self) -> None:
        entity = select.ShadyDiagnosticModeSelect(_stub_coordinator(), _make_entry())
        assert entity._attr_options == list(_const_mod.DIAGNOSTIC_MODES)
        assert entity._attr_options == ["off", "compare_regressions"]


class TestCurrentOptionDelegatesToCoordinator:
    """Given a coordinator with some active diagnostic mode key, When
    `current_option` is read, Then it returns exactly that key, read
    fresh from `coordinator.active_diagnostic_mode()` each time — no
    caching of its own (ADR-004 §1)."""

    def test_reflects_off_by_default(self) -> None:
        entity = select.ShadyDiagnosticModeSelect(_stub_coordinator("off"), _make_entry())
        assert entity.current_option == "off"

    def test_reflects_a_selected_mode(self) -> None:
        entity = select.ShadyDiagnosticModeSelect(
            _stub_coordinator("compare_regressions"), _make_entry()
        )
        assert entity.current_option == "compare_regressions"

    def test_reflects_a_change_made_after_construction(self) -> None:
        coordinator = _stub_coordinator("off")
        entity = select.ShadyDiagnosticModeSelect(coordinator, _make_entry())
        coordinator.set_active_diagnostic_mode("compare_regressions")
        assert entity.current_option == "compare_regressions"


class TestAsyncSelectOptionDelegatesToCoordinator:
    """Given `async_select_option(option)`, When called, Then it forwards
    `option` verbatim to `coordinator.set_active_diagnostic_mode` — no
    validation, no business logic of its own (ADR-000 §3 thin-glue)."""

    def test_forwards_the_chosen_option(self) -> None:
        coordinator = _stub_coordinator("off")
        entity = select.ShadyDiagnosticModeSelect(coordinator, _make_entry())
        _run(entity.async_select_option("compare_regressions"))
        assert coordinator.active_diagnostic_mode() == "compare_regressions"

    def test_forwards_a_switch_back_to_off(self) -> None:
        coordinator = _stub_coordinator("compare_regressions")
        entity = select.ShadyDiagnosticModeSelect(coordinator, _make_entry())
        _run(entity.async_select_option("off"))
        assert coordinator.active_diagnostic_mode() == "off"


class TestUniqueIdIncludesEntry:
    """Given two config entries, When each gets its own
    `ShadyDiagnosticModeSelect`, Then their `unique_id`s differ (one
    select per config entry, ADR-004 §1)."""

    def test_unique_id_is_entry_scoped(self) -> None:
        entity_a = select.ShadyDiagnosticModeSelect(_stub_coordinator(), _make_entry("aaa"))
        entity_b = select.ShadyDiagnosticModeSelect(_stub_coordinator(), _make_entry("bbb"))
        assert entity_a._attr_unique_id != entity_b._attr_unique_id
        assert "aaa" in entity_a._attr_unique_id
        assert "bbb" in entity_b._attr_unique_id


class TestAsyncSetupEntryAddsOneSelect:
    """Given `hass.data[DOMAIN][entry.entry_id]` already holds a
    coordinator, When `select.py`'s `async_setup_entry` runs, Then
    exactly one `ShadyDiagnosticModeSelect` is added."""

    def test_adds_exactly_one_entity(self) -> None:
        coordinator = _stub_coordinator()
        entry = _make_entry()

        class _Hass:
            def __init__(self) -> None:
                self.data: dict[str, Any] = {}

        hass = _Hass()
        hass.data.setdefault(_const_mod.DOMAIN, {})[entry.entry_id] = coordinator

        added: list[Any] = []

        def _add_entities(entities: list[Any]) -> None:
            added.extend(entities)

        _run(select.async_setup_entry(hass, entry, _add_entities))

        assert len(added) == 1
        assert isinstance(added[0], select.ShadyDiagnosticModeSelect)
