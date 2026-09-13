"""Normalize discovered baseline candidates onto one canonical series (ADR-009 §2).

Maps both `sensor.*` shapes (dict-of-timestamp, list-of-dicts) and both
`weather.*` shapes (sunshine duration, inverted cloud coverage) onto the
canonical `list[tuple[datetime, float]]` series every downstream consumer
(`regression/`, `forecast_adjust.py`) works with, regardless of source
shape or polarity (ADR-009 §2). Owns the key-name alias table and the
weather-cloud inversion; delegates the low-level tuple assembly to
`providers/base.py`'s `assemble_series` (ADR-012 §1a).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, Literal

from .base import assemble_series

# Known key-name aliases a discovered attribute's entries might use
# (ADR-009 §2). Order matters only for the "which key wins" tie-break in
# `_find_key` below — first match in this tuple is preferred.
TIMESTAMP_KEY_ALIASES: tuple[str, ...] = ("datetime", "start", "period_start", "time")
VALUE_KEY_ALIASES: tuple[str, ...] = (
    "wh",
    "pv_estimate",
    "power",
    "value",
    "energy",
    "sunshine_duration",
    "cloud_coverage",
)

# The shape kinds ADR-009 §1 recognizes: two `sensor.*` shapes, two
# `weather.*` shapes (each a distinct, differently-labeled proxy baseline).
BaselineShape = Literal["sensor_dict", "sensor_list", "weather_sunshine", "weather_cloud"]

CLOUD_COVERAGE_KEYS: tuple[str, ...] = ("cloud_coverage", "cloud_coverage_total")
SUNSHINE_DURATION_KEY = "sunshine_duration"


def parse_timestamp(raw: Any) -> datetime | None:
    """Parse a raw dict/entry key or value into a `datetime`, or `None` if
    it is not a parseable ISO8601 timestamp (ADR-009 §3's "parseable
    ISO8601 timestamps" scoring signal).
    """
    if isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def invert_cloud_coverage(value: float, *, scale: float = 100.0) -> float:
    """Invert a cloud-coverage-like percentage into a positive clear-sky
    proxy (ADR-009 §1: "more cloud, less expected yield" -> "the inverse
    of a clear-sky proxy"). `scale` is the source's full-scale value
    (percentage-scaled sources use the default `100.0`).
    """
    return scale - value


def _find_key(entry: Mapping[str, Any], aliases: Sequence[str]) -> str | None:
    """Return the first key in `entry` that matches one of `aliases`
    (case-insensitive), or `None` if none match.
    """
    lowered = {str(key).lower(): key for key in entry}
    for alias in aliases:
        if alias in lowered:
            return lowered[alias]
    return None


def resolve_dict_series(raw: Any) -> list[tuple[datetime, float]] | None:
    """Resolve a `{timestamp: number}`-shaped attribute (Forecast.Solar-
    like, ADR-009 §1) into the canonical series, or `None` if `raw` is not
    actually shaped this way (not a mapping, keys not parseable
    timestamps, or values not numeric).
    """
    if not isinstance(raw, Mapping) or not raw:
        return None
    parsed: dict[datetime, float] = {}
    for key, value in raw.items():
        timestamp = parse_timestamp(key)
        if timestamp is None:
            return None
        try:
            parsed[timestamp] = float(value)
        except (TypeError, ValueError):
            return None
    return assemble_series(parsed)


def resolve_list_series(
    raw: Any, *, value_key_hint: str | None = None
) -> list[tuple[datetime, float]] | None:
    """Resolve a list-of-dicts-shaped attribute (Solcast-like, or a
    `weather.*` `forecast` attribute, ADR-009 §1) into the canonical
    series, or `None` if `raw` is not actually shaped this way.

    The timestamp key is always resolved via `TIMESTAMP_KEY_ALIASES`. The
    value key is resolved via `value_key_hint` if given (used by callers
    that already know which proxy value they are looking for, e.g. a
    `weather.*` entry's `sunshine_duration`/`cloud_coverage` key) or via
    `VALUE_KEY_ALIASES` otherwise.
    """
    if isinstance(raw, str) or not isinstance(raw, Sequence) or not raw:
        return None
    first = raw[0]
    if not isinstance(first, Mapping):
        return None

    timestamp_key = _find_key(first, TIMESTAMP_KEY_ALIASES)
    if timestamp_key is None:
        return None

    if value_key_hint is not None:
        value_key = (
            value_key_hint if value_key_hint in first else _find_key(first, (value_key_hint,))
        )
    else:
        value_key = _find_key(first, VALUE_KEY_ALIASES)
    if value_key is None:
        return None

    resolved: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, Mapping) or timestamp_key not in entry or value_key not in entry:
            return None
        timestamp = parse_timestamp(entry[timestamp_key])
        if timestamp is None:
            return None
        resolved.append({"datetime": timestamp, "value": entry[value_key]})
    try:
        return assemble_series(resolved)
    except (TypeError, ValueError):
        return None


def normalize_candidate_series(shape: BaselineShape, raw: Any) -> list[tuple[datetime, float]]:
    """The one canonical-series mapping function (ADR-012 §1: "one mapping
    function, two callers") — shared by baseline discovery's candidate
    scan, `BaselineProvider.fetch()` (past range), and
    `BaselineProvider.forward()` (live forward range). Dispatches on
    `shape` (already resolved by discovery) and returns the canonical
    `list[tuple[datetime, float]]` series, inverting cloud-coverage
    values per ADR-009 §1. Returns `[]` (never raises) if `raw` turns out
    not to actually match `shape` at call time (e.g. a live attribute
    momentarily unavailable) — pure calculation modules stay
    exception-free in their normal operating range (ADR-000 §8).
    """
    if shape == "sensor_dict":
        return resolve_dict_series(raw) or []
    if shape == "sensor_list":
        return resolve_list_series(raw) or []
    if shape == "weather_sunshine":
        return resolve_list_series(raw, value_key_hint=SUNSHINE_DURATION_KEY) or []
    if shape == "weather_cloud":
        for cloud_key in CLOUD_COVERAGE_KEYS:
            series = resolve_list_series(raw, value_key_hint=cloud_key)
            if series is not None:
                return [(timestamp, invert_cloud_coverage(value)) for timestamp, value in series]
        return []
    return []
