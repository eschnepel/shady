"""Temperature source provider."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Callable, Literal

from .base import ProviderBase
from .normalize import normalize_series

TemperatureTier = Literal["module", "ambient", "weather"]

__all__ = ["ShadyTemperatureProvider", "TemperatureTier"]


def _series_in_range(
    series: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, float]]:
    return [(timestamp, value) for timestamp, value in series if start <= timestamp <= end]


class ShadyTemperatureProvider(ProviderBase):
    """Resolve and normalize the selected temperature source."""

    def __init__(
        self,
        entity_id: str,
        tier: TemperatureTier = "module",
        *,
        series_source: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.tier = tier
        self._series_source = series_source

    def identify(self) -> str:
        return self.entity_id

    def _raw_series(self) -> Any:
        if self._series_source is None:
            raise RuntimeError("ShadyTemperatureProvider requires a series_source callable")
        return self._series_source(self.entity_id, "forecast" if self.tier == "weather" else "state")

    def _normalized_series(self) -> list[tuple[datetime, float]]:
        raw = self._raw_series()
        if self.tier == "weather":
            return normalize_series(raw, source_kind="weather-sunshine")
        return normalize_series(raw, source_kind="sensor-list")

    def fetch(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        return _series_in_range(self._normalized_series(), start, end)

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None:
        if self.tier != "weather":
            return None
        return _series_in_range(self._normalized_series(), now, datetime.max)
