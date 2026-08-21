from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._module_loader import load_module


base = load_module("shady.providers.base", "providers/base.py")


@dataclass
class _FakeState:
    state: object
    attributes: dict[str, object]


class _DummyProvider(base.ProviderBase):
    def fetch(self, start: datetime, end: datetime) -> list[float | None | str]:
        return [1.0]


def test_provider_base_defaults():
    provider = _DummyProvider()
    assert provider.identify() is None
    assert provider.forward(datetime(2026, 8, 21, 12, 0)) is None


def test_state_to_three_state_value_handles_common_ha_shapes():
    assert base.state_to_three_state_value(_FakeState("12.5", {})) == 12.5
    assert base.state_to_three_state_value(_FakeState("unknown", {})) == "unknown"
    assert base.state_to_three_state_value(_FakeState("unavailable", {})) == "unavailable"
    assert base.state_to_three_state_value(_FakeState("12.5", {}), "missing") is None


def test_assemble_series_tuples_supports_dicts_and_dict_like_rows():
    start = datetime(2026, 8, 21, 10, 0)
    series = {
        start: 1.0,
        start.replace(minute=5): 2.0,
    }
    rows = [
        {"datetime": start, "value": 1.0},
        {"datetime": start.replace(minute=5), "value": 2.0},
    ]

    assert base.assemble_series_tuples(series) == [(start, 1.0), (start.replace(minute=5), 2.0)]
    assert base.assemble_series_tuples(rows) == [(start, 1.0), (start.replace(minute=5), 2.0)]
