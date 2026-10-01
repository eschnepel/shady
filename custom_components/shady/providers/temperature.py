"""Temperature source provider: a three-tier hierarchy, one config-flow
selector, no discovery/scoring (ADR-003b §1a, ADR-012 §1).

Unlike baseline discovery (ADR-009), temperature sourcing needs no
attribute-shape scoring — `device_class: temperature` on `sensor.*`
entities and the `temperature`/`forecast` attributes on `weather.*`
entities are stable, versioned HA conventions (ADR-003b §1a). This
module resolves whichever entity the config flow (ADR-010) already
selected and provides `fetch()`/`forward()` per tier. The same class
is reused, unmodified, for ADR-003c's independent weather-forecast-
temperature predictor field (TASK-0014) — a second instance, always
pointed at a `weather.*` entity.

`homeassistant.core.HomeAssistant` is imported only under
`TYPE_CHECKING` (see `providers/discovery.py` for the same pattern and
its rationale) so this module has no runtime dependency on the
`homeassistant` package.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from .base import EntityRef, Provider, assemble_series, map_state_value

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

# Same 5-minute slot convention `providers/discovery.py` and `cache.py`
# independently establish (ADR-007a §4) — duplicated, not imported, since
# `providers/` sits upstream of `cache.py` (ADR-000 §3).
_SLOT_DURATION = timedelta(minutes=5)

# The three source types ADR-003b §1a lists collapse to two *fetch
# mechanisms*: a plain sensor.* reading (module/cell or ambient tier —
# both read identically here; the uplift formula that tells them apart
# is yield_correction.py's concern, not this provider's) and a weather.*
# entity (current condition + native forecast). "sensor" covers both the
# module/cell and ambient tiers.
TemperatureTier = Literal["sensor", "weather"]

_WEATHER_CURRENT_ATTRIBUTE = "temperature"
_WEATHER_FORECAST_ATTRIBUTE = "forecast"
_FORECAST_TIMESTAMP_KEY = "datetime"
_FORECAST_TEMPERATURE_KEY = "temperature"


def _parse_forecast_series(forecast_raw: Any) -> list[tuple[datetime, float]]:
    """Resolve a `weather.*` entity's `forecast` attribute (a stable,
    versioned HA shape — list of dicts, each with a `datetime` key and a
    `temperature` key, ADR-003b §1a) into the canonical series. Reuses
    `providers.base.assemble_series` (ADR-012 §1a) once timestamps are
    parsed; returns `[]` (never raises) if `forecast_raw` isn't actually
    shaped this way.
    """
    if isinstance(forecast_raw, str) or not isinstance(forecast_raw, Sequence):
        return []
    resolved: list[dict[str, Any]] = []
    for entry in forecast_raw:
        if not isinstance(entry, Mapping):
            continue
        raw_timestamp = entry.get(_FORECAST_TIMESTAMP_KEY)
        raw_temperature = entry.get(_FORECAST_TEMPERATURE_KEY)
        if raw_timestamp is None or raw_temperature is None:
            continue
        timestamp = raw_timestamp
        if not isinstance(timestamp, datetime):
            try:
                timestamp = datetime.fromisoformat(str(raw_timestamp))
            except ValueError:
                continue
        resolved.append({"datetime": timestamp, "value": raw_temperature})
    try:
        return assemble_series(resolved)
    except (TypeError, ValueError):
        return []


def _fill_slots(
    series: list[tuple[datetime, float]],
    fallback: float | None | str,
    start: datetime,
    end: datetime,
) -> list[float | None | str]:
    """Map a (possibly sparse) series onto the `[start, end)` 5-minute
    slot grid `Provider.fetch`'s calling convention requires (ADR-007a
    §4): a slot with an exact series entry uses it (the "prediction-time
    case" per ADR-003b §1b, when the entry came from a `forecast`
    attribute); every other slot uses `fallback` (the current/live
    reading — the "training set" case per ADR-003b §1a).
    """
    by_timestamp = dict(series)
    slot_count = int((end - start) / _SLOT_DURATION)
    result: list[float | None | str] = []
    for index in range(slot_count):
        slot_start = start + index * _SLOT_DURATION
        if slot_start in by_timestamp:
            result.append(map_state_value(by_timestamp[slot_start]))
        else:
            result.append(fallback)
    return result


class TemperatureProvider(Provider):
    """Concrete provider for a resolved temperature source (ADR-003b
    §1a, ADR-012 §1). `identify()` reports back exactly the config-flow
    selection, with no ranking step. `fetch()` reads the live reading
    (both tiers) and, for the weather tier, the live `forecast`
    attribute — a slot with a matching forecast entry uses it (prediction-
    time case, ADR-003b §1b), every other slot falls back to the current
    reading (training-set case, ADR-003b §1a). `forward()` is meaningful
    only for the weather tier (ADR-003c's Context: "plain live sensors
    have no forecasting concept of their own") — the sensor tier leaves
    it returning `None`.
    """

    def __init__(self, hass: HomeAssistant, entity_id: str, tier: TemperatureTier) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._tier = tier

    def identify(self) -> EntityRef | None:
        if self._tier == "weather":
            return EntityRef(self._entity_id, _WEATHER_CURRENT_ATTRIBUTE)
        return EntityRef(self._entity_id, None)

    def fetch(self, start: datetime, end: datetime) -> list[float | None | str]:
        state = self._hass.states.get(self._entity_id)
        if state is None:
            return [None] * int((end - start) / _SLOT_DURATION)

        if self._tier == "weather":
            current = map_state_value(state.attributes.get(_WEATHER_CURRENT_ATTRIBUTE))
            raw_forecast = state.attributes.get(_WEATHER_FORECAST_ATTRIBUTE)
            forecast_series = _parse_forecast_series(raw_forecast)
            return _fill_slots(forecast_series, current, start, end)

        current = map_state_value(state.state)
        return [current] * int((end - start) / _SLOT_DURATION)

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None:
        if self._tier != "weather":
            return None
        state = self._hass.states.get(self._entity_id)
        if state is None:
            return None
        series = _parse_forecast_series(state.attributes.get(_WEATHER_FORECAST_ATTRIBUTE))
        return [(timestamp, value) for timestamp, value in series if timestamp >= now]
