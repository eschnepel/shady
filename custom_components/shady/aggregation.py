"""Pure aggregation helpers for Shady."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta

__all__ = [
    "build_day_slot_timestamps",
    "crossfade",
    "diagnostic_accuracy",
    "intraday_correction_factor",
    "ramp_weight",
    "sum_slot_rows",
    "trapezoidal_energy_increment",
    "total_energy_from_series",
]


def build_day_slot_timestamps(day_start: datetime, slot_count: int = 288) -> list[datetime]:
    """Build the 5-minute timestamps for a day."""

    return [day_start + timedelta(minutes=5 * index) for index in range(slot_count)]


def sum_slot_rows(
    slot_rows: Sequence[Mapping[str, float | int | None]],
) -> list[float]:
    """Sum a slot-aligned list of per-sensor values."""

    totals: list[float] = []
    for row in slot_rows:
        total = 0.0
        for value in row.values():
            if isinstance(value, (int, float)):
                total += float(value)
        totals.append(total)
    return totals


def ramp_weight(active_slots_since_reset: int, ramp_slots: int) -> float:
    """Return the linear ramp weight for the current slot."""

    if ramp_slots <= 0:
        return 1.0
    if active_slots_since_reset <= 0:
        return 0.0
    return min(1.0, active_slots_since_reset / float(ramp_slots))


def intraday_correction_factor(
    pv_energy_window: float,
    fc_energy_window: float,
    ramp_weight_value: float,
    intraday_correction_cutoff: float,
) -> float:
    """Return the unclamped correction factor for the current ramp weight."""

    if pv_energy_window <= 0.0 or fc_energy_window <= 0.0:
        return 1.0
    ratio_string = pv_energy_window / fc_energy_window
    lower = 1.0 - intraday_correction_cutoff
    upper = 1.0 + intraday_correction_cutoff
    clamped_ratio = min(max(ratio_string, lower), upper)
    return 1.0 + ramp_weight_value * (clamped_ratio - 1.0)


def crossfade(old_prediction: float, new_prediction: float, blend_weight: float) -> float:
    """Blend old and new predictions with a linear crossfade."""

    if blend_weight <= 0.0:
        return old_prediction
    if blend_weight >= 1.0:
        return new_prediction
    return (1.0 - blend_weight) * old_prediction + blend_weight * new_prediction


def diagnostic_accuracy(predicted: float, actual: float) -> float:
    """Return a clamped percentage accuracy for a selected diagnostic slot."""

    if actual <= 0.0:
        return 100.0 if predicted <= 0.0 else 0.0
    return max(0.0, 100.0 * (1.0 - abs(predicted - actual) / actual))


def trapezoidal_energy_increment(
    previous: tuple[datetime, float],
    current: tuple[datetime, float],
) -> float:
    """Return the Wh added between two power samples."""

    previous_timestamp, previous_power = previous
    current_timestamp, current_power = current
    duration_hours = (current_timestamp - previous_timestamp).total_seconds() / 3600.0
    if duration_hours < 0:
        raise ValueError("current sample must not precede the previous sample")
    return (previous_power + current_power) * 0.5 * duration_hours


def total_energy_from_series(series: Sequence[tuple[datetime, float]]) -> float:
    """Integrate a time-ordered power series into Wh."""

    if len(series) < 2:
        return 0.0
    total = 0.0
    for previous, current in zip(series, series[1:]):
        total += trapezoidal_energy_increment(previous, current)
    return total
