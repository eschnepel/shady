"""Zero-mocking tests for `providers/base.py` (ADR-012 §1/§1a, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

import pytest

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_base_mod = _load("providers/base.py", "shady.providers.base")

# TYPE_CHECKING-only static import mirroring the runtime file-path load
# above (ADR-000 §6) — gives mypy a real type for `Provider` so the
# subclasses below type-check normally, without reintroducing the package
# import (and therefore `homeassistant.*`) the file-path load avoids.
if TYPE_CHECKING:
    from shady.providers.base import Provider as Provider  # noqa: PLC0414
else:
    Provider = _base_mod.Provider


class DummyProviderMinimal(Provider):
    """A minimal provider that only implements the required `fetch()`."""

    def fetch(self, start: datetime, end: datetime) -> list[float | None | str]:
        return [1.0, None, "unavailable"]


class TestProviderBaseClassDefaults:
    """Given a dummy subclass that only implements fetch(), the base
    class's identify()/forward() defaults apply (ADR-012 §1)."""

    def test_minimal_subclass_instantiates(self) -> None:
        provider = DummyProviderMinimal()
        assert provider.fetch(
            datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)
        ) == [
            1.0,
            None,
            "unavailable",
        ]

    def test_identify_defaults_to_none(self) -> None:
        provider = DummyProviderMinimal()
        assert provider.identify() is None

    def test_forward_defaults_to_none(self) -> None:
        provider = DummyProviderMinimal()
        assert provider.forward(datetime(2026, 1, 1, tzinfo=UTC)) is None


class TestProviderRequiresFetch:
    """Given a dummy subclass that omits fetch() entirely, instantiation
    fails — fetch is required, no default (ADR-012 §1)."""

    def test_missing_fetch_fails_instantiation(self) -> None:
        class DummyProviderNoFetch(Provider):
            """Deliberately omits fetch()."""

        with pytest.raises(TypeError):
            DummyProviderNoFetch()  # type: ignore[abstract]


class TestMapStateValue:
    """Given a range of raw hass.states-shaped inputs, the mapping helper
    returns exactly one of cache.py's three storage states (ADR-007a §1).
    """

    def test_numeric_state_maps_to_float(self) -> None:
        assert _base_mod.map_state_value(123.4) == 123.4
        assert isinstance(_base_mod.map_state_value(123.4), float)

    def test_numeric_int_state_maps_to_float(self) -> None:
        result = _base_mod.map_state_value(7)
        assert result == 7.0
        assert isinstance(result, float)

    def test_numeric_string_state_maps_to_float(self) -> None:
        result = _base_mod.map_state_value("42.5")
        assert result == 42.5
        assert isinstance(result, float)

    def test_unknown_state_maps_to_none(self) -> None:
        assert _base_mod.map_state_value("unknown") is None

    def test_unavailable_state_maps_to_str(self) -> None:
        result = _base_mod.map_state_value("unavailable")
        assert result == "unavailable"
        assert isinstance(result, str)

    def test_absent_attribute_maps_to_none(self) -> None:
        assert _base_mod.map_state_value(None) is None


class TestAssembleSeries:
    """Given already-resolved timestamp/value pairs (dict shape and
    list-of-dicts shape), the assembly helper returns the canonical
    list[tuple[datetime, float]] shape (ADR-009 §2)."""

    def test_dict_shape(self) -> None:
        ts1 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        ts2 = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
        pairs = {ts1: 100.0, ts2: 110.5}

        result = _base_mod.assemble_series(pairs)

        assert result == [(ts1, 100.0), (ts2, 110.5)]

    def test_list_of_dicts_shape_default_keys(self) -> None:
        ts1 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        ts2 = datetime(2026, 1, 1, 10, 5, tzinfo=UTC)
        pairs = [
            {"datetime": ts1, "value": 100.0},
            {"datetime": ts2, "value": 110.5},
        ]

        result = _base_mod.assemble_series(pairs)

        assert result == [(ts1, 100.0), (ts2, 110.5)]

    def test_list_of_dicts_shape_custom_keys(self) -> None:
        ts1 = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        pairs = [{"ts": ts1, "val": "99.0"}]

        result = _base_mod.assemble_series(pairs, datetime_key="ts", value_key="val")

        assert result == [(ts1, 99.0)]

    def test_empty_dict_shape(self) -> None:
        assert _base_mod.assemble_series({}) == []

    def test_empty_list_shape(self) -> None:
        assert _base_mod.assemble_series([]) == []
