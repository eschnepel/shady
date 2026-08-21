"""Shared provider base class and pure helper functions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from datetime import datetime
from numbers import Real
from typing import Any, TypeAlias

EntityRef: TypeAlias = str
ThreeStateValue: TypeAlias = float | None | str

__all__ = [
    "EntityRef",
    "ProviderBase",
    "ThreeStateValue",
    "assemble_series_tuples",
    "state_to_three_state_value",
]


class ProviderBase(ABC):
    """Common provider contract for pull and push series sources."""

    @abstractmethod
    def fetch(self, start: datetime, end: datetime) -> list[ThreeStateValue]:
        """Return the provider series for the requested range."""

    def identify(self) -> EntityRef | None:
        """Return the resolved entity reference, if one exists."""

        return None

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None:
        """Return the provider's live forward-looking series, if any."""

        return None


def _coerce_three_state_value(value: object) -> ThreeStateValue:
    if value is None:
        return None
    if isinstance(value, Real) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"unknown", "unavailable"}:
            return lowered
        try:
            return float(value)
        except ValueError:
            return value
    return value if isinstance(value, str) else str(value)


def state_to_three_state_value(
    state_or_value: object | None,
    attribute: str | None = None,
) -> ThreeStateValue:
    """Translate a Home Assistant-style state or attribute to cache storage."""

    if state_or_value is None:
        return None

    value: object | None = state_or_value
    if attribute is not None:
        attributes = getattr(state_or_value, "attributes", None)
        if not isinstance(attributes, Mapping) or attribute not in attributes:
            return None
        value = attributes[attribute]
    elif hasattr(state_or_value, "state"):
        value = getattr(state_or_value, "state")

    return _coerce_three_state_value(value)


def assemble_series_tuples(
    resolved_series: Mapping[datetime, float]
    | Sequence[Mapping[str, object]]
    | Sequence[tuple[datetime, float]],
    *,
    timestamp_keys: tuple[str, ...] = ("datetime", "timestamp", "time"),
    value_keys: tuple[str, ...] = ("value", "state"),
) -> list[tuple[datetime, float]]:
    """Normalize several resolved series shapes into canonical tuples."""

    items: list[tuple[datetime, float]] = []
    if isinstance(resolved_series, Mapping):
        for timestamp, value in resolved_series.items():
            items.append((timestamp, float(value)))
        return items

    for entry in resolved_series:
        if isinstance(entry, tuple) and len(entry) == 2 and isinstance(entry[0], datetime):
            items.append((entry[0], float(entry[1])))
            continue

        if isinstance(entry, Mapping):
            timestamp: datetime | None = None
            for key in timestamp_keys:
                if key in entry:
                    raw_timestamp = entry[key]
                    if isinstance(raw_timestamp, datetime):
                        timestamp = raw_timestamp
                    break
            if timestamp is None:
                raise ValueError("resolved series entry is missing a datetime timestamp")

            value: object | None = None
            for key in value_keys:
                if key in entry:
                    value = entry[key]
                    break
            if value is None:
                raise ValueError("resolved series entry is missing a numeric value")
            items.append((timestamp, float(value)))
            continue

        raise TypeError("resolved series must contain mappings or (datetime, float) pairs")

    items.sort(key=lambda item: item[0])
    return items
