"""Baseline forecast discovery and provider plumbing."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Literal

from .base import ProviderBase
from .normalize import SeriesKind, normalize_series

WeatherLabel = Literal["sunshine_duration", "cloud_coverage"]

__all__ = [
    "ForecastCandidate",
    "ShadyBaselineForecastProvider",
    "discover_candidates",
    "rank_candidates",
    "score_candidate",
]


@dataclass(frozen=True)
class ForecastCandidate:
    entity_id: str
    attribute: str
    source_kind: SeriesKind
    score: float
    label: str
    invert_cloud_coverage: bool = False


def _iter_entities(source: Any) -> list[Any]:
    if hasattr(source, "states") and hasattr(source.states, "async_all"):
        return list(source.states.async_all())
    if hasattr(source, "states") and isinstance(source.states, list):
        return list(source.states)
    if isinstance(source, list):
        return source
    raise TypeError("discover_candidates expects a hass-like object or entity list")


def _series_value_keys(value: Any) -> tuple[str, ...]:
    if isinstance(value, dict):
        return tuple(k for k in value.keys() if isinstance(k, str))
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return tuple(k for k in value[0].keys() if isinstance(k, str))
    return ()


def _looks_like_timestamp_mapping(value: Any) -> bool:
    if not isinstance(value, dict) or not value:
        return False
    try:
        for key in value.keys():
            _ = datetime.fromisoformat(str(key).replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def _looks_like_timed_series_list(value: Any) -> bool:
    if not isinstance(value, list) or not value or not isinstance(value[0], dict):
        return False
    keys = _series_value_keys(value)
    if any(key in {"sunshine_duration", "cloud_coverage"} for key in keys):
        return True
    if not any(key in {"datetime", "start", "period_start", "time", "timestamp"} for key in keys):
        return False
    if not any(key in {"wh", "pv_estimate", "power", "value", "energy"} for key in keys):
        return False
    return True


def score_candidate(entity_id: str, attribute: str, value: Any) -> float:
    score = 0.0
    lowered = f"{entity_id} {attribute}".lower()
    for token, bonus in (
        ("forecast", 10.0),
        ("pv", 8.0),
        ("sunshine", 8.0),
        ("cloud", 8.0),
        ("power", 4.0),
        ("energy", 4.0),
        ("value", 2.0),
    ):
        if token in lowered:
            score += bonus

    keys = _series_value_keys(value)
    if any(key in {"datetime", "start", "period_start", "time", "timestamp"} for key in keys):
        score += 10.0
    if any(key in {"wh", "pv_estimate", "power", "value", "energy"} for key in keys):
        score += 10.0
    if "sunshine_duration" in keys:
        score += 12.0
    if "cloud_coverage" in keys:
        score += 12.0
    return score


def discover_candidates(source: Any) -> list[ForecastCandidate]:
    candidates: list[ForecastCandidate] = []
    for entity in _iter_entities(source):
        entity_id = getattr(entity, "entity_id", "")
        if not entity_id:
            continue
        domain = entity_id.split(".", 1)[0]
        attributes = getattr(entity, "attributes", {}) or {}
        if not isinstance(attributes, dict):
            continue

        for attribute, value in attributes.items():
            if domain == "sensor":
                if _looks_like_timestamp_mapping(value):
                    source_kind = "sensor-mapping"
                    label = attribute
                elif _looks_like_timed_series_list(value):
                    source_kind = "sensor-list"
                    label = attribute
                else:
                    continue
                candidates.append(
                    ForecastCandidate(
                        entity_id=entity_id,
                        attribute=attribute,
                        source_kind=source_kind,
                        score=score_candidate(entity_id, attribute, value),
                        label=label,
                    )
                )
            elif domain == "weather":
                if attribute != "forecast" or not _looks_like_timed_series_list(value):
                    continue
                keys = _series_value_keys(value)
                if "sunshine_duration" in keys:
                    candidates.append(
                        ForecastCandidate(
                            entity_id=entity_id,
                            attribute=attribute,
                            source_kind="weather-sunshine",
                            score=score_candidate(entity_id, attribute, value),
                            label="sunshine duration",
                        )
                    )
                if "cloud_coverage" in keys:
                    candidates.append(
                        ForecastCandidate(
                            entity_id=entity_id,
                            attribute=attribute,
                            source_kind="weather-cloud",
                            score=score_candidate(entity_id, attribute, value),
                            label="cloud coverage (inverted)",
                            invert_cloud_coverage=True,
                        )
                    )
    return rank_candidates(candidates)


def rank_candidates(candidates: list[ForecastCandidate]) -> list[ForecastCandidate]:
    return sorted(candidates, key=lambda candidate: (-candidate.score, candidate.label, candidate.entity_id))


def _series_in_range(
    series: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
) -> list[tuple[datetime, float]]:
    return [(timestamp, value) for timestamp, value in series if start <= timestamp <= end]


class ShadyBaselineForecastProvider(ProviderBase):
    """Concrete provider for discovered baseline forecast series."""

    def __init__(
        self,
        entity_id: str,
        attribute: str,
        source_kind: SeriesKind = "sensor-mapping",
        *,
        series_source: Callable[[str, str], Any] | None = None,
    ) -> None:
        self.entity_id = entity_id
        self.attribute = attribute
        self.source_kind = source_kind
        self._series_source = series_source

    def identify(self) -> str:
        return self.entity_id

    def _raw_series(self, start: datetime, end: datetime) -> Any:
        if self._series_source is not None:
            return self._series_source(self.entity_id, self.attribute)
        raise RuntimeError("ShadyBaselineForecastProvider requires a series_source callable")

    def _normalized_series(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        raw = self._raw_series(start, end)
        series = normalize_series(raw, source_kind=self.source_kind)
        return _series_in_range(series, start, end)

    def fetch(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        return self._normalized_series(start, end)

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None:
        series = self._normalized_series(now, datetime.max)
        return series if series else None
