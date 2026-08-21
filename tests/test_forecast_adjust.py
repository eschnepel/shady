from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ._module_loader import load_module


forecast_adjust = load_module("shady.forecast_adjust", "forecast_adjust.py")


@dataclass
class _FakeModel:
    value: float

    def predict(self, forecast: float) -> tuple[float, float]:
        return self.value, 0.9


def test_adjust_forecast_clamps_to_fc_without_temperature_or_limits():
    timestamp = datetime(2026, 8, 21, 12, 0)
    adjusted = forecast_adjust.adjust_forecast([(timestamp, 100.0)], {144: _FakeModel(150.0)})

    assert adjusted == [(timestamp, 100.0)]


def test_adjust_forecast_applies_reverse_transform_before_final_clamp():
    timestamp = datetime(2026, 8, 21, 12, 0)
    adjusted = forecast_adjust.adjust_forecast(
        [(timestamp, 100.0)],
        {144: _FakeModel(60.0)},
        coefficient_per_c=0.1,
        target_temperatures={timestamp: 35.0},
    )

    assert adjusted == [(timestamp, 100.0)]


def test_adjust_forecast_uses_inverter_limit_as_tighter_clamp():
    timestamp = datetime(2026, 8, 21, 12, 0)
    adjusted = forecast_adjust.adjust_forecast(
        [(timestamp, 100.0)],
        {144: _FakeModel(95.0)},
        inverter_limit=80.0,
    )

    assert adjusted == [(timestamp, 80.0)]


def test_adjust_forecast_applies_intraday_factor_and_blend():
    timestamp = datetime(2026, 8, 21, 12, 0)
    adjusted = forecast_adjust.adjust_forecast(
        [(timestamp, 100.0)],
        {144: _FakeModel(60.0)},
        intraday_factors={timestamp: 1.1},
        intraday_old_predictions={timestamp: 40.0},
        intraday_blend_weights={timestamp: 0.5},
    )

    assert adjusted == [(timestamp, 53.0)]
