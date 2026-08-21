"""Normalization helpers for baseline and temperature series."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from numbers import Real
from typing import Literal, TypeAlias

SeriesKind: TypeAlias = Literal["sensor-mapping", "sensor-list", "weather-sunshine", "weather-cloud"]

TIMESTAMP_KEYS = ("datetime", "start", "period_start", "time", "timestamp")
VALUE_KEYS = ("wh", "pv_estimate", "power", "value", "energy", "sunshine_duration", "cloud_coverage")

__all__ = [
    "SeriesKind",
    "TIMESTAMP_KEYS",
    "VALUE_KEYS",
    "canonical_series",
    "normalize_series",
    "parse_timestamp",
]


def parse_timestamp(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    raise TypeError("timestamp values must be datetimes or ISO-8601 strings")


def _coerce_float(value: object) -> float:
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise TypeError("series values must be numeric")


def _extract_from_mapping(raw: Mapping[object, object]) -> list[tuple[datetime, float]]:
    series: list[tuple[datetime, float]] = []
    for timestamp, value in raw.items():
        series.append((parse_timestamp(timestamp), _coerce_float(value)))
    series.sort(key=lambda item: item[0])
    return series


def _extract_from_sequence(
    raw: Sequence[Mapping[str, object]] | Sequence[tuple[datetime, float]],
    *,
    timestamp_keys: tuple[str, ...] = TIMESTAMP_KEYS,
    value_keys: tuple[str, ...] = VALUE_KEYS,
) -> list[tuple[datetime, float]]:
    if len(raw) == 0:
        return []
    first = raw[0]
    if isinstance(first, tuple) and len(first) == 2:
        series = [(parse_timestamp(timestamp), _coerce_float(value)) for timestamp, value in raw]  # type: ignore[misc]
        series.sort(key=lambda item: item[0])
        return series

    series: list[tuple[datetime, float]] = []
    for entry in raw:
        timestamp: datetime | None = None
        for key in timestamp_keys:
            if key in entry:
                timestamp = parse_timestamp(entry[key])
                break
        if timestamp is None:
            raise ValueError("series entry is missing a timestamp key")

        value: object | None = None
        for key in value_keys:
            if key in entry:
                value = entry[key]
                break
        if value is None:
            raise ValueError("series entry is missing a numeric value key")
        series.append((timestamp, _coerce_float(value)))

    series.sort(key=lambda item: item[0])
    return series


def normalize_series(
    raw: Mapping[object, object] | Sequence[Mapping[str, object]] | Sequence[tuple[datetime, float]],
    *,
    source_kind: SeriesKind = "sensor-mapping",
    invert_cloud_coverage: bool = False,
) -> list[tuple[datetime, float]]:
    """Convert recognized forecast shapes into the canonical series."""

    if isinstance(raw, Mapping):
        series = _extract_from_mapping(raw)
    else:
        series = _extract_from_sequence(raw)

    if source_kind == "weather-cloud" or invert_cloud_coverage:
        series = [
            (timestamp, 100.0 - value if value > 1.0 else 1.0 - value)
            for timestamp, value in series
        ]
    return series


canonical_series = normalize_series
