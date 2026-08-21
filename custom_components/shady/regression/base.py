"""Shared regression helpers and fitted model implementations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from collections.abc import Iterable, Sequence

import numpy as np

__all__ = [
    "KernelRegressionModel",
    "PolynomialRegressionModel",
    "RegressionModel",
    "build_training_pool",
    "magnitude_weight",
    "time_weight",
]


def _scalar_or_array(source: object, value: np.ndarray) -> float | np.ndarray:
    if np.ndim(source) == 0:
        return float(np.asarray(value).reshape(()))
    return value


def magnitude_weight(forecast: float | np.ndarray) -> float | np.ndarray:
    forecast_array = np.clip(np.asarray(forecast, dtype=float), 0.0, None)
    weight = np.where(forecast_array == 0.0, 0.0, 1.0 - np.exp(-forecast_array / 1000.0))
    return _scalar_or_array(forecast, weight)


def time_weight(distance: int, smoothing_radius: int) -> float:
    if smoothing_radius < 0:
        raise ValueError("smoothing_radius must be non-negative")
    if distance > smoothing_radius:
        return 0.0
    return 1.0 - distance / (smoothing_radius + 1.0)


def _pool_to_arrays(pool: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    array = np.asarray(pool, dtype=float)
    if array.ndim == 2:
        array = array[np.newaxis, ...]
    if array.ndim != 3:
        raise ValueError("pool must be a 2-D or 3-D numpy array")
    forecast = array[..., 0]
    actual = array[..., 1]
    if array.shape[-1] >= 3:
        base_weight = array[..., 2]
    else:
        base_weight = np.ones_like(forecast)
    return forecast, actual, base_weight


def _prepare_single_pool(pool: np.ndarray) -> np.ndarray:
    array = np.asarray(pool, dtype=float)
    if array.ndim != 2 or array.shape[1] < 2:
        raise ValueError("training pool rows must contain forecast and actual values")
    forecast = array[:, 0]
    actual = array[:, 1]
    if array.shape[1] >= 3:
        base_weight = array[:, 2]
    else:
        base_weight = np.ones_like(forecast)
    return np.column_stack((forecast, actual, base_weight))


def build_training_pool(
    center_samples: np.ndarray,
    neighbor_samples: Sequence[np.ndarray] = (),
    *,
    smoothing_radius: int = 1,
    neighbor_fitting_cutoff: float = 0.25,
) -> np.ndarray:
    """Build a weighted pool from one center series and optional neighbors."""

    if smoothing_radius < 0:
        raise ValueError("smoothing_radius must be non-negative")

    def series_median_ratio(samples: np.ndarray) -> float:
        array = np.asarray(samples, dtype=float)
        if array.ndim != 2 or array.shape[1] < 2:
            raise ValueError("each series must contain forecast and actual columns")
        forecast = array[:, 0]
        actual = array[:, 1]
        valid = forecast > 0
        if not np.any(valid):
            return 0.0
        ratios = actual[valid] / forecast[valid]
        return float(np.median(ratios))

    center = np.asarray(center_samples, dtype=float)
    if center.ndim != 2 or center.shape[1] < 2:
        raise ValueError("center_samples must contain forecast and actual columns")

    center_median = series_median_ratio(center)
    pools: list[np.ndarray] = []
    series_list = [center, *neighbor_samples]

    for distance, series in enumerate(series_list):
        if distance > smoothing_radius:
            continue
        array = np.asarray(series, dtype=float)
        if array.ndim != 2 or array.shape[1] < 2:
            raise ValueError("each series must contain forecast and actual columns")
        forecast = array[:, 0]
        actual = array[:, 1]
        if array.shape[1] >= 3:
            base_weight = array[:, 2]
        else:
            base_weight = np.ones_like(forecast)

        adjusted_actual = actual
        if distance > 0:
            neighbor_median = series_median_ratio(array)
            if neighbor_fitting_cutoff < 0:
                if neighbor_median > 0 and center_median > 0:
                    adjusted_actual = actual * (center_median / neighbor_median)
            else:
                deviation = 0.0
                if center_median > 0:
                    deviation = abs(neighbor_median - center_median) / center_median
                if deviation > neighbor_fitting_cutoff:
                    base_weight = np.zeros_like(base_weight)

        weights = np.asarray(magnitude_weight(forecast), dtype=float) * time_weight(distance, smoothing_radius)
        weights = weights * base_weight
        pools.append(np.column_stack((forecast, adjusted_actual, weights)))

    if not pools:
        return np.zeros((0, 3), dtype=float)
    return np.vstack(pools)


class RegressionModel(ABC):
    """Common prediction contract for fitted models."""

    @abstractmethod
    def predict(self, forecast: float | np.ndarray) -> tuple[float | np.ndarray, float | np.ndarray]:
        """Predict corrected output and confidence for a given forecast."""


@dataclass
class PolynomialRegressionModel(RegressionModel):
    coefficients: np.ndarray
    confidence: np.ndarray

    def predict(self, forecast: float | np.ndarray) -> tuple[float | np.ndarray, float | np.ndarray]:
        forecast_array = np.asarray(forecast, dtype=float)
        coeffs = np.asarray(self.coefficients, dtype=float)
        if coeffs.ndim == 1:
            prediction = np.polynomial.polynomial.polyval(forecast_array, coeffs)
            prediction = np.clip(prediction, 0.0, forecast_array)
            return _scalar_or_array(forecast, prediction), _scalar_or_array(forecast, np.asarray(self.confidence, dtype=float))

        fc_array = forecast_array
        if fc_array.ndim == 0:
            fc_array = np.full(coeffs.shape[0], float(fc_array), dtype=float)
        if fc_array.ndim != 1 or fc_array.shape[0] != coeffs.shape[0]:
            raise ValueError("batched forecast must match the fitted batch size")
        prediction = np.array(
            [np.polynomial.polynomial.polyval(fc, coeff_row) for fc, coeff_row in zip(fc_array, coeffs)],
            dtype=float,
        )
        prediction = np.clip(prediction, 0.0, fc_array)
        confidence = np.asarray(self.confidence, dtype=float)
        return prediction, confidence


@dataclass
class KernelRegressionModel(RegressionModel):
    forecast_samples: np.ndarray
    actual_samples: np.ndarray
    weights: np.ndarray
    confidence: np.ndarray
    bandwidth: np.ndarray

    def predict(self, forecast: float | np.ndarray) -> tuple[float | np.ndarray, float | np.ndarray]:
        forecast_array = np.asarray(forecast, dtype=float)
        forecasts = np.asarray(self.forecast_samples, dtype=float)
        actuals = np.asarray(self.actual_samples, dtype=float)
        weights = np.asarray(self.weights, dtype=float)
        bandwidth = np.asarray(self.bandwidth, dtype=float)

        if forecasts.ndim == 1:
            local_weights = weights / (1.0 + np.abs(forecasts - forecast_array) / bandwidth)
            denominator = float(np.sum(local_weights))
            prediction = 0.0 if denominator == 0.0 else float(np.sum(local_weights * actuals) / denominator)
            prediction = float(np.clip(prediction, 0.0, float(forecast_array)))
            confidence = float(self.confidence)
            return prediction, confidence

        if forecast_array.ndim == 0:
            forecast_array = np.full(forecasts.shape[0], float(forecast_array), dtype=float)
        if forecast_array.ndim != 1 or forecast_array.shape[0] != forecasts.shape[0]:
            raise ValueError("batched forecast must match the fitted batch size")

        predictions = np.empty(forecasts.shape[0], dtype=float)
        for index, (series_forecasts, series_actuals, series_weights, series_bandwidth, query) in enumerate(
            zip(forecasts, actuals, weights, bandwidth, forecast_array)
        ):
            local_weights = series_weights / (1.0 + np.abs(series_forecasts - query) / series_bandwidth)
            denominator = float(np.sum(local_weights))
            value = 0.0 if denominator == 0.0 else float(np.sum(local_weights * series_actuals) / denominator)
            predictions[index] = float(np.clip(value, 0.0, float(query)))
        return predictions, np.asarray(self.confidence, dtype=float)


def _fit_weighted_polynomial(pool: np.ndarray, degree: int) -> PolynomialRegressionModel:
    forecast, actual, weight = _pool_to_arrays(pool)
    batch_size = forecast.shape[0]
    coefficients = np.zeros((batch_size, degree + 1), dtype=float)
    confidence = np.sum(weight, axis=1)

    for batch_index in range(batch_size):
        batch_forecast = forecast[batch_index]
        batch_actual = actual[batch_index]
        batch_weight = weight[batch_index]
        mask = batch_weight > 0
        if not np.any(mask):
            continue
        effective_degree = min(degree, int(np.count_nonzero(mask)) - 1)
        design = np.vander(batch_forecast[mask], N=effective_degree + 1, increasing=True)
        scaled_design = design * np.sqrt(batch_weight[mask])[:, np.newaxis]
        scaled_target = batch_actual[mask] * np.sqrt(batch_weight[mask])
        solution, *_ = np.linalg.lstsq(scaled_design, scaled_target, rcond=None)
        coefficients[batch_index, : effective_degree + 1] = solution

    if batch_size == 1:
        return PolynomialRegressionModel(coefficients[0], confidence[0])
    return PolynomialRegressionModel(coefficients, confidence)


def _fit_kernel(pool: np.ndarray) -> KernelRegressionModel:
    forecast, actual, weight = _pool_to_arrays(pool)
    bandwidth = np.ptp(forecast, axis=1)
    bandwidth = np.where(bandwidth <= 0.0, 1.0, bandwidth)
    confidence = np.sum(weight, axis=1)
    if forecast.shape[0] == 1:
        return KernelRegressionModel(forecast[0], actual[0], weight[0], confidence[0], bandwidth[0])
    return KernelRegressionModel(forecast, actual, weight, confidence, bandwidth)
