"""Shady – Shading-Adjusted PV Forecast integration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
import logging
from typing import Any

from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
import voluptuous as vol

from .cache import ShadyCache
from .const import CONF_STRINGS, CONF_TEMPERATURE_SOURCE_ENTITY_ID, CONF_WINDOW_DAYS, DOMAIN
from .coordinator import ShadyCoordinator
from .providers.discovery import ForecastCandidate, ShadyBaselineForecastProvider, discover_candidates
from .providers.temperature import ShadyTemperatureProvider

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["button", "sensor", "switch"]


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _state_series_source(hass: HomeAssistant, entity_id: str, attribute: str) -> Any:
    state = hass.states.get(entity_id)
    if state is None:
        return []
    if attribute:
        return state.attributes.get(attribute, [])
    return state.state


def _candidate_map(hass: HomeAssistant) -> dict[tuple[str, str], ForecastCandidate]:
    candidates = discover_candidates(hass.states.async_all())
    return {(candidate.entity_id, candidate.attribute): candidate for candidate in candidates}


def _baseline_provider(
    hass: HomeAssistant,
    candidate_map: Mapping[tuple[str, str], ForecastCandidate],
    string_data: Mapping[str, Any],
) -> ShadyBaselineForecastProvider:
    entity_id = str(string_data.get("baseline_entity_id") or "")
    attribute = str(string_data.get("baseline_attribute") or "")
    candidate = candidate_map.get((entity_id, attribute))
    source_kind = candidate.source_kind if candidate is not None else "sensor-mapping"
    return ShadyBaselineForecastProvider(
        entity_id,
        attribute,
        source_kind,
        series_source=lambda resolved_entity_id, resolved_attribute: _state_series_source(
            hass, resolved_entity_id, resolved_attribute
        ),
    )


def _build_baseline_providers(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, ShadyBaselineForecastProvider]:
    candidate_map = _candidate_map(hass)
    providers: dict[str, ShadyBaselineForecastProvider] = {}
    for string_data in entry.data.get(CONF_STRINGS, []):
        string_id = str(string_data["id"])
        providers[string_id] = _baseline_provider(hass, candidate_map, string_data)
    return providers


def _build_temperature_providers(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, ShadyTemperatureProvider]:
    entity_id = str(entry.data.get(CONF_TEMPERATURE_SOURCE_ENTITY_ID) or "").strip()
    if not entity_id:
        return {}
    return {
        entity_id: ShadyTemperatureProvider(
            entity_id,
            "weather",
            series_source=lambda resolved_entity_id, resolved_attribute: _state_series_source(
                hass, resolved_entity_id, resolved_attribute
            ),
        )
    }


def _recorder_fetch_fn(
    hass: HomeAssistant,
) -> Callable[[str, datetime, datetime], list[float | None | str]]:
    def _fetch(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
        state = hass.states.get(sensor_id)
        units = None
        if state is not None:
            unit = state.attributes.get("unit_of_measurement")
            if isinstance(unit, str) and unit:
                units = {sensor_id: unit}
        rows = statistics_during_period(
            hass,
            start,
            end,
            {sensor_id},
            "5minute",
            units,
            {"state"},
        ).get(sensor_id, [])
        by_timestamp: dict[datetime, float | None] = {}
        for row in rows:
            timestamp = datetime.fromtimestamp(row.start, tz=timezone.utc)
            by_timestamp[_naive_utc(timestamp)] = row.state
        values: list[float | None | str] = []
        current = start
        while current <= end:
            values.append(by_timestamp.get(_naive_utc(current)))
            current += timedelta(minutes=5)
        return values

    return _fetch


def _build_cache(hass: HomeAssistant, entry: ConfigEntry) -> ShadyCache:
    return ShadyCache(
        int(entry.data.get(CONF_WINDOW_DAYS, 28)),
        _recorder_fetch_fn(hass),
    )


def _register_select_diagnostic_slot_service(hass: HomeAssistant) -> None:
    if not hasattr(hass, "services") or not hasattr(hass.services, "has_service"):
        return
    if hass.services.has_service(DOMAIN, "select_diagnostic_slot"):
        return

    async def _handle(call: Any) -> None:
        entry_id = str(call.data["entry_id"])
        timestamp = call.data["timestamp"]
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        if coordinator is None:
            raise ValueError(f"Unknown Shady entry_id: {entry_id}")
        coordinator.select_diagnostic_slot(timestamp)
        await coordinator.async_refresh_diagnostics(timestamp)

    hass.services.async_register(
        DOMAIN,
        "select_diagnostic_slot",
        _handle,
        schema=vol.Schema({vol.Required("entry_id"): cv.string, vol.Required("timestamp"): cv.datetime}),
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Shady from a config entry."""

    hass.data.setdefault(DOMAIN, {})
    _register_select_diagnostic_slot_service(hass)
    coordinator = ShadyCoordinator(
        hass,
        _build_cache(hass, entry),
        entry.data,
        _build_baseline_providers(hass, entry),
        _build_temperature_providers(hass, entry),
    )
    await coordinator.async_setup()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unloaded: bool = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        coordinator = hass.data.get(DOMAIN, {}).get(entry.entry_id)
        if coordinator is not None:
            await coordinator.async_shutdown()
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded
