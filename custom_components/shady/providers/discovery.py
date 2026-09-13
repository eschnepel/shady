"""Baseline (unshaded) forecast discovery, scoring, and provider (ADR-009).

Scans `sensor.*`/`weather.*` entities for forecast-shaped attributes,
scores candidates, and exposes `BaselineProvider` — the concrete
`Provider` (ADR-012 §1) that wraps a config-flow-confirmed candidate.
Reads `hass.states` only, per ADR-009 §4/ADR-012 §5's module boundary —
no writes, no reaching into another integration's internals.

`homeassistant.core.HomeAssistant`/`State` are imported only under
`TYPE_CHECKING` (with `from __future__ import annotations` making every
annotation lazy) so this module has no runtime dependency on the
`homeassistant` package, matching ADR-000 §6's "pytest only" testing
philosophy for the two real-hass-fixture exception modules.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .base import EntityRef, Provider, map_state_value
from .normalize import (
    CLOUD_COVERAGE_KEYS,
    SUNSHINE_DURATION_KEY,
    BaselineShape,
    normalize_candidate_series,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# Same 5-minute slot convention `cache.py`'s `FetchFn` and
# `providers/base.py`'s `Provider.fetch` calling convention both already
# establish (ADR-007a §4) — duplicated here, not imported, since
# `providers/` sits upstream of `cache.py` in the module dependency
# direction (ADR-000 §3) and must not import it.
_SLOT_DURATION = timedelta(minutes=5)

# Attribute-name keywords that raise a candidate's score (ADR-009 §3).
_SENSOR_KEYWORDS: tuple[str, ...] = ("forecast", "pv")
_SUNSHINE_KEYWORDS: tuple[str, ...] = ("sunshine", "forecast")
_CLOUD_KEYWORDS: tuple[str, ...] = ("cloud", "forecast")

# Distinct, user-facing labels per shape (ADR-009 §3: "a candidate matched
# on cloud_coverage is labeled distinctly... e.g. 'cloud coverage
# (inverted)' vs. 'sunshine duration'").
_LABELS: dict[BaselineShape, str] = {
    "sensor_dict": "forecast sensor (timestamp map)",
    "sensor_list": "forecast sensor (list)",
    "weather_sunshine": "sunshine duration",
    "weather_cloud": "cloud coverage (inverted)",
}


@dataclass(frozen=True)
class BaselineCandidate:
    """A scored, not-yet-confirmed baseline candidate (ADR-009 §3). The
    config flow (ADR-010) presents these ranked by `score`; the user
    confirms one (or falls back to manual entity+attribute entry) before
    a `BaselineProvider` is ever instantiated.
    """

    entity_id: str
    attribute: str
    shape: BaselineShape
    score: float
    label: str


def _keyword_bonus(attribute: str, keywords: Sequence[str]) -> float:
    lowered = attribute.lower()
    return sum(1.0 for keyword in keywords if keyword in lowered)


def _build_candidate(entity_id: str, attribute: str, shape: BaselineShape) -> BaselineCandidate:
    keywords = {
        "sensor_dict": _SENSOR_KEYWORDS,
        "sensor_list": _SENSOR_KEYWORDS,
        "weather_sunshine": _SUNSHINE_KEYWORDS,
        "weather_cloud": _CLOUD_KEYWORDS,
    }[shape]
    # Base score of 2.0: the attribute already passed shape validation
    # (parseable ISO8601 timestamps + plausible numeric values, ADR-009
    # §3's other two scoring signals), plus the keyword bonus.
    score = 2.0 + _keyword_bonus(attribute, keywords)
    return BaselineCandidate(
        entity_id=entity_id,
        attribute=attribute,
        shape=shape,
        score=score,
        label=_LABELS[shape],
    )


def _scan_sensor_domain(hass: HomeAssistant) -> list[BaselineCandidate]:
    """Scan `sensor.*` entities for the two recognized shapes (ADR-009 §1):
    a dict-of-timestamp attribute (Forecast.Solar-like) or a list-of-dicts
    attribute (Solcast-like).
    """
    found: list[BaselineCandidate] = []
    for state in hass.states.async_all("sensor"):
        for attribute, value in state.attributes.items():
            if isinstance(value, Mapping) and normalize_candidate_series("sensor_dict", value):
                found.append(_build_candidate(state.entity_id, attribute, "sensor_dict"))
            elif (
                isinstance(value, Sequence)
                and not isinstance(value, str)
                and normalize_candidate_series("sensor_list", value)
            ):
                found.append(_build_candidate(state.entity_id, attribute, "sensor_list"))
    return found


def _weather_entry_keys(value: Any) -> set[str] | None:
    if isinstance(value, str) or not isinstance(value, Sequence) or not value:
        return None
    first = value[0]
    if not isinstance(first, Mapping):
        return None
    return {str(key).lower() for key in first}


def _scan_weather_domain(hass: HomeAssistant) -> list[BaselineCandidate]:
    """Scan `weather.*` entities for the two recognized proxy shapes
    (ADR-009 §1): a `sunshine_duration`-keyed forecast entry, or a
    `cloud_coverage`/`cloud_coverage_total`-keyed one (inverted by
    `normalize.py`).
    """
    found: list[BaselineCandidate] = []
    for state in hass.states.async_all("weather"):
        for attribute, value in state.attributes.items():
            keys = _weather_entry_keys(value)
            if keys is None:
                continue
            if SUNSHINE_DURATION_KEY in keys and normalize_candidate_series(
                "weather_sunshine", value
            ):
                found.append(_build_candidate(state.entity_id, attribute, "weather_sunshine"))
            if any(key in keys for key in CLOUD_COVERAGE_KEYS) and normalize_candidate_series(
                "weather_cloud", value
            ):
                found.append(_build_candidate(state.entity_id, attribute, "weather_cloud"))
    return found


def discover_baseline_candidates(hass: HomeAssistant) -> list[BaselineCandidate]:
    """Scan `sensor.*`/`weather.*` entities for forecast-shaped attributes
    and return every recognized candidate, ranked by score descending
    (ADR-009 §1/§3). Never auto-selects — the config flow (ADR-010)
    presents these to the user for confirmation.
    """
    candidates = _scan_sensor_domain(hass) + _scan_weather_domain(hass)
    candidates.sort(key=lambda candidate: candidate.score, reverse=True)
    return candidates


def _series_to_slots(
    series: list[tuple[datetime, float]], start: datetime, end: datetime
) -> list[float | None | str]:
    """Map a canonical series onto the `[start, end)` 5-minute slot grid
    `Provider.fetch`'s calling convention requires (ADR-007a §4) — one
    value per slot, `None` where the series has no entry for that slot.
    """
    by_timestamp = dict(series)
    slot_count = int((end - start) / _SLOT_DURATION)
    result: list[float | None | str] = []
    for index in range(slot_count):
        slot_start = start + index * _SLOT_DURATION
        result.append(map_state_value(by_timestamp.get(slot_start)))
    return result


class BaselineProvider(Provider):
    """Concrete provider for the baseline (unshaded) PV forecast (ADR-009,
    ADR-012 §1). Wraps a config-flow-confirmed `BaselineCandidate`
    resolution — `identify()` reports it back; `fetch()`/`forward()` both
    read the live attribute and normalize it through
    `normalize.normalize_candidate_series`, the same mapping function,
    for the past range and the live forward range respectively.
    """

    def __init__(
        self, hass: HomeAssistant, entity_id: str, attribute: str, shape: BaselineShape
    ) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._attribute = attribute
        self._shape = shape

    def identify(self) -> EntityRef | None:
        return EntityRef(self._entity_id, self._attribute)

    def _read_raw_attribute(self) -> Any:
        state = self._hass.states.get(self._entity_id)
        if state is None:
            return None
        return state.attributes.get(self._attribute)

    def fetch(self, start: datetime, end: datetime) -> list[float | None | str]:
        raw = self._read_raw_attribute()
        series = normalize_candidate_series(self._shape, raw) if raw is not None else []
        return _series_to_slots(series, start, end)

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None:
        raw = self._read_raw_attribute()
        if raw is None:
            return None
        series = normalize_candidate_series(self._shape, raw)
        return [(timestamp, value) for timestamp, value in series if timestamp >= now]
