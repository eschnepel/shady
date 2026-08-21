"""Optional per-string yield corrections."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

__all__ = [
    "apply_temperature_derating",
    "estimate_cell_temperature_from_ambient",
    "exclude_clipped_samples",
    "reverse_temperature_derating",
]


def exclude_clipped_samples(
    samples: Sequence[Sequence[float]] | np.ndarray,
    inverter_limit: float | None,
    *,
    clipping_threshold: float = 0.98,
    actual_index: int = 1,
) -> np.ndarray:
    array = np.asarray(samples, dtype=float)
    if inverter_limit is None:
        return array
    if array.ndim != 2:
        raise ValueError("samples must be a 2-D array of rows")
    if actual_index >= array.shape[1]:
        raise ValueError("actual_index is out of range for the provided samples")
    ceiling = clipping_threshold * inverter_limit
    return array[array[:, actual_index] < ceiling]


def apply_temperature_derating(
    actual_raw: float | np.ndarray,
    cell_temperature: float | np.ndarray | None,
    coefficient_per_c: float | None,
    *,
    provider_already_corrects: bool = False,
) -> float | np.ndarray:
    if provider_already_corrects or coefficient_per_c is None or cell_temperature is None:
        return actual_raw
    actual = np.asarray(actual_raw, dtype=float)
    temperature = np.asarray(cell_temperature, dtype=float)
    factor = 1.0 + coefficient_per_c * (temperature - 25.0)
    return actual / factor


def reverse_temperature_derating(
    predicted_at_25c: float | np.ndarray,
    target_cell_temperature: float | np.ndarray | None,
    coefficient_per_c: float | None,
    *,
    provider_already_corrects: bool = False,
) -> float | np.ndarray:
    if provider_already_corrects or coefficient_per_c is None or target_cell_temperature is None:
        return predicted_at_25c
    predicted = np.asarray(predicted_at_25c, dtype=float)
    temperature = np.asarray(target_cell_temperature, dtype=float)
    factor = 1.0 + coefficient_per_c * (temperature - 25.0)
    return predicted * factor


def estimate_cell_temperature_from_ambient(
    ambient_temperature: float | np.ndarray,
    baseline_forecast: float | np.ndarray,
    baseline_rated_capacity: float | None,
    *,
    max_uplift_c: float = 25.0,
) -> float | np.ndarray:
    if baseline_rated_capacity is None or baseline_rated_capacity <= 0:
        return ambient_temperature
    ambient = np.asarray(ambient_temperature, dtype=float)
    baseline = np.clip(np.asarray(baseline_forecast, dtype=float), 0.0, baseline_rated_capacity)
    uplift = max_uplift_c * (baseline / baseline_rated_capacity)
    return ambient + uplift
