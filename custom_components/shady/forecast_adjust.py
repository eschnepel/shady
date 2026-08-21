"""Apply fitted per-slot models and final clamps to baseline forecasts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Protocol, overload

from .aggregation import crossfade
from .yield_correction import reverse_temperature_derating

__all__ = ["adjust_forecast", "apply_forecast_adjustment"]


class _Predictor(Protocol):
    def predict(self, forecast: float) -> tuple[float, float]:
        ...


def _slot_of_day(moment: datetime) -> int:
    return (moment.hour * 60 + moment.minute) // 5


def _lookup_model(
    models: Mapping[int, _Predictor] | Sequence[_Predictor],
    slot: int,
) -> _Predictor | None:
    if isinstance(models, Mapping):
        return models.get(slot)
    if 0 <= slot < len(models):
        return models[slot]
    return None


def _clamp(value: float, forecast: float, inverter_limit: float | None) -> float:
    upper_bound = forecast if inverter_limit is None else min(forecast, inverter_limit)
    return min(max(value, 0.0), upper_bound)


def adjust_forecast(
    baseline_series: Sequence[tuple[datetime, float]],
    models: Mapping[int, _Predictor] | Sequence[_Predictor],
    *,
    inverter_limit: float | None = None,
    coefficient_per_c: float | None = None,
    target_temperatures: Mapping[datetime, float] | None = None,
    intraday_factors: Mapping[datetime, float] | None = None,
    intraday_old_predictions: Mapping[datetime, float] | None = None,
    intraday_blend_weights: Mapping[datetime, float] | None = None,
    clamp_output: bool = True,
    return_raw: bool = False,
) -> list[tuple[datetime, float]] | tuple[list[tuple[datetime, float]], list[tuple[datetime, float]]]:
    adjusted: list[tuple[datetime, float]] = []
    raw_adjusted: list[tuple[datetime, float]] = []
    for timestamp, forecast in baseline_series:
        slot = _slot_of_day(timestamp)
        model = _lookup_model(models, slot)
        predicted = forecast
        if model is not None:
            predicted, _ = model.predict(forecast)

        target_temperature = None
        if target_temperatures is not None:
            target_temperature = target_temperatures.get(timestamp)
        if coefficient_per_c is not None and target_temperature is not None:
            predicted = float(
                reverse_temperature_derating(
                    predicted,
                    target_temperature,
                    coefficient_per_c,
                )
            )

        if intraday_factors is not None and timestamp in intraday_factors:
            predicted = float(predicted) * float(intraday_factors[timestamp])
        if intraday_old_predictions is not None and intraday_blend_weights is not None:
            old_prediction = intraday_old_predictions.get(timestamp)
            blend_weight = intraday_blend_weights.get(timestamp)
            if old_prediction is not None and blend_weight is not None:
                predicted = crossfade(float(old_prediction), float(predicted), float(blend_weight))

        raw_value = float(predicted)
        raw_adjusted.append((timestamp, raw_value))
        adjusted_value = _clamp(raw_value, forecast, inverter_limit) if clamp_output else raw_value
        adjusted.append((timestamp, adjusted_value))

    if return_raw:
        return adjusted, raw_adjusted
    return adjusted


apply_forecast_adjustment = adjust_forecast
