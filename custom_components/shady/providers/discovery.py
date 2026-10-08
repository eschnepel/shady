"""Baseline (unshaded) forecast discovery, scoring, and provider (ADR-009).

Scans `sensor.*`/`weather.*` entities for forecast-shaped attributes,
also scans for a Forecast.Solar config entry (ADR-009 Amendment,
"Forecast.Solar polling sourcing"), scores candidates, and exposes
`BaselineProvider` — the concrete `Provider` (ADR-012 §1) that wraps a
config-flow-confirmed candidate. Reads `hass.states`/`hass.config_
entries`/`hass.services`/the entity registry only, per ADR-009 §4/§1c-
Amendment /ADR-012 §5's module boundary — no writes, no recorder access
(that stays `coordinator.py`'s alone, ADR-012 §2a), no reaching into
another integration's internals.

`homeassistant.core.HomeAssistant`/`State` are imported only under
`TYPE_CHECKING` (with `from __future__ import annotations` making every
annotation lazy) so this module has no runtime dependency on the
`homeassistant` package, matching ADR-000 §6's "pytest only" testing
philosophy for the two real-hass-fixture exception modules — except one
guarded, gracefully-degrading runtime import of `homeassistant.helpers.
entity_registry` (ADR-009 §1c Amendment, `TASK-0034`), needed because an
entity registry lookup has no `hass`-attribute-based duck-typing
equivalent the way `hass.states`/`hass.services`/`hass.config_entries`
already have elsewhere in this module. See that import's own comment.

Also imports `ServiceResponseCache`/`service_call_key` from `..cache`
(ADR-007 §1a, `TASK-0036`, ADR-000 §3's new `providers --> cache` edge) —
a narrow, `hass`-free, `Cache`-independent class, not a dependency on the
rest of `cache.py`'s design or on `coordinator.py`. `_sample_weather_
forecast`/`_sample_forecast_solar` below route their service calls
through the shared, `hass.data`-held instance (`async_get_service_
response_cache`) so a transient discovery-time failure falls back to the
last usable response, the same way `coordinator.py`'s Forecast.Solar poll
does (ADR-012 §4b).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

# `ServiceResponseCache`/`service_call_key` (ADR-007 §1a, `TASK-0036`) — the
# one exception to this module's "no downstream import" convention: a
# narrow, `Cache`-independent, `hass`-free class (ADR-000 §3's new
# `providers --> cache` edge), the same kind of encapsulation-preserving
# exception `diagnostics/compare_regressions.py`'s own `SLOTS_PER_DAY`
# import already established. Used to route this module's own
# `weather.get_forecasts`/`forecast_solar.get_forecast` sampling through
# the same restart-persisted last-good-response fallback `coordinator.py`'s
# Forecast.Solar poll uses (ADR-012 §4b).
from ..cache import ServiceResponseCache, service_call_key
from ..const import SERVICE_RESPONSE_CACHE_HASS_KEY
from .base import EntityRef, Provider, map_state_value
from .normalize import (
    CLOUD_COVERAGE_KEYS,
    FORECAST_SOLAR_WH_PERIOD_KEY,
    SUNSHINE_DURATION_KEY,
    BaselineShape,
    normalize_candidate_series,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

try:
    # Entity registry lookup for `history_entity_id` resolution (ADR-009
    # §1c Amendment, "recorder-backed baseline history", `TASK-0034`) —
    # the same guarded-import precedent `coordinator.py` already
    # established for `weather.const.DATA_COMPONENT` (ADR-012 §4a): the
    # real `homeassistant.helpers.entity_registry` module is only absent
    # from this module's own hand-written test double environment
    # (`tests/test_providers_discovery.py`, which stubs just enough of it
    # in `sys.modules` to exercise the real resolution logic, not only
    # this fallback) and from any other file-path-loading test file that
    # pulls this module in as a dependency without needing that logic
    # itself (e.g. `tests/test_coordinator.py`, `tests/test_config_
    # flow.py`) — both cases degrade to `_entity_registry = None` below,
    # which `resolve_forecast_solar_history_entity` already treats as
    # "no history entity resolvable this cycle" (ADR-000 §8), not an
    # error. This one guarded import is the sole exception to this
    # module's otherwise-zero runtime `homeassistant` dependency (see the
    # module docstring above) — deliberately, not accidentally: unlike
    # `HomeAssistant`/`State`, there is no way to duck-type an entity
    # registry lookup against a bare `hass` object the way `hass.states`/
    # `hass.services`/`hass.config_entries` already are elsewhere in this
    # module, since real Home Assistant has no such attribute either —
    # `entity_registry.async_get(hass)`/`.async_entries_for_config_entry(...)`
    # are the real, public, module-level API for this.
    from homeassistant.helpers import entity_registry as _entity_registry
except ImportError:
    _entity_registry = None

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

# The two proxy shapes `weather.*` sourcing recognizes (ADR-009 §1) — the
# only shapes that have a `forecast_type` concept at all (see
# `BaselineCandidate.forecast_type`/`BaselineProvider.forecast_type`
# below). A `sensor.*` shape (`sensor_dict`/`sensor_list`) is unaffected;
# `weather.get_forecasts` doesn't enter into it.
_WEATHER_SHAPES = frozenset({"weather_sunshine", "weather_cloud"})

# Every shape whose live series arrives out-of-band (via `update_live_
# forecast()`, pushed in by `coordinator.py`) rather than by reading
# `state.attributes` directly — the two `_WEATHER_SHAPES` (ADR-009
# Amendment, "forecast subscription sourcing") plus `forecast_solar`
# (ADR-009 Amendment, "Forecast.Solar polling sourcing"). Both amendments
# exist for the same underlying reason: current HA core no longer
# exposes either integration's forecast data as a plain attribute.
_PUSH_SOURCED_SHAPES = _WEATHER_SHAPES | frozenset({"forecast_solar"})

# The one `weather.*` forecast granularity Shady ever samples/subscribes
# to (ADR-009 Amendment, "forecast subscription sourcing"): `"hourly"`.
# Baseline `FC` feeds a 5-minute-slot regression (`_SLOT_DURATION` above)
# — `"daily"`/`"twice_daily"` are far too coarse to usefully backfill
# that grid, so an entity that only supports those is not treated as a
# candidate at all, rather than falling back to a granularity ill-suited
# to this ADR's own slot model. Paired with `homeassistant.components.
# weather.const.WeatherEntityFeature.FORECAST_HOURLY`'s own bit value,
# duplicated here (rather than imported) so this module keeps its
# zero-runtime-`homeassistant`-import property (ADR-000 §6) intact for
# its own `_scan_sensor_domain`-style pure helpers — only `_sample_
# weather_forecast` below actually touches `hass` at all, and only
# through the same `hass.services.async_call` surface every HA
# integration uses.
_FORECAST_TYPE = "hourly"
_FORECAST_TYPE_FEATURE_HOURLY = 2

# Forecast.Solar polling sourcing (ADR-009 Amendment). That integration's
# own sensors expose no forecast-shaped attribute at all on current HA
# (unlike the pre-2024.4 `wh_period` attribute this module used to read)
# — the only way to see its forecast series is the
# `forecast_solar.get_forecast` service, which is keyed by that
# integration's own **config entry**, not an entity_id. A
# `forecast_solar`-shaped `BaselineCandidate`/`BaselineProvider`
# therefore stores that config entry's own `entry_id` in its `entity_id`
# field — a deliberate, documented repurposing of that field (see
# `_build_forecast_solar_candidate`/`BaselineProvider`'s own docstrings)
# rather than a real HA entity_id, since nothing about this shape has
# one to offer. A fixed, higher-than-heuristic score (`_FORECAST_SOLAR_
# SCORE`) reflects that this is a confirmed, named-integration match, not
# an attribute-shape guess (ADR-009 §3's scoring is otherwise all
# heuristic).
_FORECAST_SOLAR_DOMAIN = "forecast_solar"
_FORECAST_SOLAR_ATTRIBUTE = FORECAST_SOLAR_WH_PERIOD_KEY
_FORECAST_SOLAR_LABEL = "Forecast.Solar production estimate"
_FORECAST_SOLAR_SCORE = 5.0

# Distinct, user-facing labels per shape (ADR-009 §3: "a candidate matched
# on cloud_coverage is labeled distinctly... e.g. 'cloud coverage
# (inverted)' vs. 'sunshine duration'").
_LABELS: dict[BaselineShape, str] = {
    "sensor_dict": "forecast sensor (timestamp map)",
    "sensor_list": "forecast sensor (list)",
    "weather_sunshine": "sunshine duration",
    "weather_cloud": "cloud coverage (inverted)",
    "forecast_solar": _FORECAST_SOLAR_LABEL,
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
    # ADR-009 §1c Amendment ("recorder-backed baseline history",
    # `TASK-0034`) — a linked, recorder-backed history entity_id, only
    # ever set for a `forecast_solar` candidate whose companion "power
    # production now" sensor was resolved via the entity registry at
    # discovery time (`resolve_forecast_solar_history_entity`). `None`
    # for every other shape (deliberately never auto-linked — see that
    # amendment's own "why only forecast_solar" section) and for a
    # `forecast_solar` candidate whose companion sensor wasn't found
    # (registry unavailable, or a startup-ordering race).
    history_entity_id: str | None = None

    @property
    def forecast_type(self) -> str | None:
        """Which `weather.get_forecasts` granularity `BaselineProvider`
        should subscribe to for this candidate (ADR-009 Amendment:
        "always hourly") — derived from `shape` alone, not stored
        separately, since it is always `_FORECAST_TYPE` for a
        `weather.*`-sourced candidate and `None` (nothing to subscribe
        to) for any other candidate, `forecast_solar` included (that
        shape polls a service instead — see `BaselineProvider.shape`).
        """
        return _FORECAST_TYPE if self.shape in _WEATHER_SHAPES else None


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


def _build_forecast_solar_candidate(
    config_entry_id: str, history_entity_id: str | None = None
) -> BaselineCandidate:
    """Build the one `forecast_solar`-shaped candidate for a given config
    entry (ADR-009 Amendment) — no keyword scoring applies here (there is
    no real attribute name to score), so this bypasses `_build_candidate`
    and uses the fixed `_FORECAST_SOLAR_SCORE` instead. `history_entity_id`
    (ADR-009 §1c Amendment, `TASK-0034`) defaults to `None`, matching every
    other shape's candidate, for callers (and existing tests) that don't
    care about history-entity resolution.
    """
    return BaselineCandidate(
        entity_id=config_entry_id,
        attribute=_FORECAST_SOLAR_ATTRIBUTE,
        shape="forecast_solar",
        score=_FORECAST_SOLAR_SCORE,
        label=_FORECAST_SOLAR_LABEL,
        history_entity_id=history_entity_id,
    )


# Forecast.Solar's own `sensor.py` platform gives its continuously-sampled
# "Estimated power production - now" sensor this `translation_key` (the
# stable, code-defined `SensorEntityDescription.key` HA's entity registry
# records on every `RegistryEntry` it creates for it) — ADR-009 §1c
# Amendment's "safe pairing": the same underlying production model the
# `forecast_solar` candidate itself estimates, just read live rather than
# forecast, and already recorder-backed since it's an ordinary HA sensor
# entity. Deliberately not a guessed `unique_id`/`entity_id` composition:
# this sensor's real-world `entity_id` has no config-entry-scoping prefix
# or suffix of any kind (confirmed against a live deployment) — it is
# simply `sensor.power_production_now` — so nothing about its `unique_id`
# should be assumed either; `translation_key`, scoped to the config entry
# via the registry's own `async_entries_for_config_entry` index, needs no
# such assumption at all.
_FORECAST_SOLAR_HISTORY_TRANSLATION_KEY = "power_production_now"


def resolve_forecast_solar_history_entity(hass: HomeAssistant, config_entry_id: str) -> str | None:
    """Resolve a Forecast.Solar config entry's own companion
    `power_production_now` sensor's *current* `entity_id`, via the entity
    registry's own `(config_entry_id, domain, translation_key)` index —
    never by string-matching or guessing an `entity_id`, and never by
    composing a guessed `unique_id` either (ADR-009 §1c Amendment's own
    Acceptance Criterion, and its own note on why: this sensor's real
    `entity_id` carries no config-entry-scoping prefix or suffix at all,
    so nothing about its `unique_id`'s composition should be assumed
    either). Every entity belonging to `config_entry_id` is looked up via
    `async_entries_for_config_entry`, then narrowed to the one `sensor`
    domain entry whose `translation_key` matches — a user is free to
    rename `entity_id` (and, unlike `unique_id`, `translation_key` is not
    even guessable from one without already knowing it), but neither
    `config_entry_id` scoping nor `translation_key` changes with a rename.
    Returns `None` (never raises) if the entity registry module itself is
    unavailable (real HA not installed, or this specific hand-written test
    double did not opt in — see the module-level guarded import above),
    the registry has no matching entry yet (a startup-ordering race in the
    same family ADR-002 §1a already accepts for other entities), or the
    entity was removed — all "no history available (yet)" outcomes, not
    errors (ADR-000 §8).

    **Public, not module-private** (`ADR-009 §1c` further Amendment,
    `TASK-0034-patch-1`): originally a `_`-prefixed helper used only by
    `_scan_forecast_solar_domain` below, one call site. `coordinator.py`'s
    `async_startup` now has a second, legitimate need for exactly this
    same lookup — retrying a `forecast_solar`-shaped provider whose
    `history_entity_id` was resolved as `None` at config/options-flow
    submission time (a startup-ordering race caught *then*, at the one
    point that result gets permanently persisted, never retried since).
    Reusing this function directly, rather than duplicating its lookup
    logic in `coordinator.py` or routing through the much heavier
    `discover_baseline_candidates` (which would rescan every baseline
    shape across every domain just to re-resolve one already-known
    config entry), is the same "no second/bespoke path" principle
    `tasks/adr-summary.md`'s exclusions already apply to recorder access.
    """
    if _entity_registry is None:
        return None
    registry = _entity_registry.async_get(hass)
    if registry is None:
        return None
    for entry in _entity_registry.async_entries_for_config_entry(registry, config_entry_id):
        if (
            entry.domain == "sensor"
            and entry.translation_key == _FORECAST_SOLAR_HISTORY_TRANSLATION_KEY
        ):
            entity_id = entry.entity_id
            return entity_id if isinstance(entity_id, str) else None
    return None


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


def async_get_service_response_cache(hass: HomeAssistant) -> ServiceResponseCache | None:
    """The one `ServiceResponseCache` instance shared by this module's
    own sampling below and `coordinator.py`'s Forecast.Solar poll
    (ADR-007 §1a, ADR-012 §4b, `TASK-0036`) — held in `hass.data`
    (`SERVICE_RESPONSE_CACHE_HASS_KEY`), created on first access rather
    than requiring `coordinator.py` to have run first, since this
    module's own sampling can run earlier (config-flow discovery, before
    any config entry — and so any coordinator — exists).

    Returns `None` for a `hass` with no `.data` mapping at all (a
    minimal test double, `getattr`-guarded the same way `coordinator.py`
    already treats a `hass` lacking the `weather` entity component) —
    every caller below degrades to calling the service directly with no
    fallback, exactly today's behavior, rather than failing (ADR-000
    §8).
    """
    hass_data = getattr(hass, "data", None)
    if hass_data is None:
        return None
    cache = hass_data.get(SERVICE_RESPONSE_CACHE_HASS_KEY)
    if cache is None:
        cache = ServiceResponseCache()
        hass_data[SERVICE_RESPONSE_CACHE_HASS_KEY] = cache
    return cache  # type: ignore[no-any-return]


async def _sample_weather_forecast(hass: HomeAssistant, entity_id: str) -> Any:
    """Call `weather.get_forecasts` once, to sample an entity's current
    hourly forecast payload (ADR-009 Amendment). Since HA 2024.4, this
    service is the *only* way to see a weather entity's forecast-shaped
    data at all — the `forecast` state attribute this module used to
    read directly was removed from `WeatherEntity` in that release.

    Routed through the shared `ServiceResponseCache` (ADR-007 §1a,
    `TASK-0036`): a call that raises, or returns a response with no
    usable forecast entry for `entity_id`, falls back to the last usable
    response for this exact entity within the last 12 hours, rather than
    dropping an otherwise-valid candidate off discovery over a
    transient failure. Genuinely cold (nothing remembered, or a `hass`
    with no service-response cache available at all) still returns
    `None`, never raises (ADR-000 §8) — unchanged from before this
    amendment.
    """

    async def _call_service() -> Any:
        try:
            return await hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": _FORECAST_TYPE},
                target={"entity_id": entity_id},
                blocking=True,
                return_response=True,
            )
        except Exception:  # noqa: BLE001 - a misbehaving integration must not abort discovery
            return None

    def _usable(response: Any) -> bool:
        return isinstance(response, Mapping) and isinstance(response.get(entity_id), Mapping)

    cache = async_get_service_response_cache(hass)
    if cache is None:
        response = await _call_service()
    else:
        key = service_call_key(
            "weather", "get_forecasts", {"type": _FORECAST_TYPE}, target={"entity_id": entity_id}
        )
        response = await cache.async_call(key, _call_service, usable=_usable)
    # `response`'s value type is `JsonValueType` (a broad recursive
    # union) — narrowed here rather than trusting the `dict`-shaped
    # `{entity_id: {"forecast": [...]}}` contract blindly, since a
    # malformed/mismatched response is exactly the kind of "not a
    # usable candidate this time" case this function already treats as
    # `None`, not a crash (ADR-000 §8).
    if not isinstance(response, Mapping):
        return None
    entry = response.get(entity_id)
    if not isinstance(entry, Mapping):
        return None
    return entry.get("forecast")


async def _scan_weather_domain(hass: HomeAssistant) -> list[BaselineCandidate]:
    """Scan `weather.*` entities for the two recognized proxy shapes
    (ADR-009 §1): a `sunshine_duration`-keyed forecast entry, or a
    `cloud_coverage`/`cloud_coverage_total`-keyed one (inverted by
    `normalize.py`). Sources the sample via `weather.get_forecasts`
    (ADR-009 Amendment) rather than `state.attributes` — see
    `_sample_weather_forecast`'s docstring for why. An entity that does
    not support hourly forecasts at all is skipped entirely (ADR-009
    Amendment: "always hourly", no coarser fallback).
    """
    found: list[BaselineCandidate] = []
    for state in hass.states.async_all("weather"):
        supported_features = state.attributes.get("supported_features") or 0
        if not supported_features & _FORECAST_TYPE_FEATURE_HOURLY:
            continue
        raw = await _sample_weather_forecast(hass, state.entity_id)
        keys = _weather_entry_keys(raw)
        if keys is None:
            continue
        if SUNSHINE_DURATION_KEY in keys and normalize_candidate_series("weather_sunshine", raw):
            found.append(
                _build_candidate(state.entity_id, SUNSHINE_DURATION_KEY, "weather_sunshine")
            )
        for cloud_key in CLOUD_COVERAGE_KEYS:
            if cloud_key in keys and normalize_candidate_series("weather_cloud", raw):
                found.append(_build_candidate(state.entity_id, cloud_key, "weather_cloud"))
                break
    return found


async def _sample_forecast_solar(hass: HomeAssistant, config_entry_id: str) -> Any:
    """Call `forecast_solar.get_forecast` once, to sample a config
    entry's current forecast payload (ADR-009 Amendment, "Forecast.Solar
    polling sourcing"). Unlike `weather.get_forecasts`, this service is
    keyed by `config_entry` rather than `entity_id` — Forecast.Solar's
    own sensors have no forecast-shaped attribute left to key off of at
    all (see the module-level `_FORECAST_SOLAR_*` comment).

    Routed through the shared `ServiceResponseCache` (ADR-007 §1a,
    `TASK-0036`), same as `_sample_weather_forecast` above: a call that
    raises, or returns an empty/falsy response, falls back to the last
    usable response for this exact config entry within the last 12
    hours. Genuinely cold still returns `None`, never raises (ADR-000
    §8) — unchanged from before this amendment.
    """

    async def _call_service() -> Any:
        try:
            return await hass.services.async_call(
                _FORECAST_SOLAR_DOMAIN,
                "get_forecast",
                {"config_entry": config_entry_id},
                blocking=True,
                return_response=True,
            )
        except Exception:  # noqa: BLE001 - a misbehaving integration must not abort discovery
            return None

    cache = async_get_service_response_cache(hass)
    if cache is None:
        return await _call_service()
    key = service_call_key(
        _FORECAST_SOLAR_DOMAIN, "get_forecast", {"config_entry": config_entry_id}
    )
    return await cache.async_call(key, _call_service)


async def _scan_forecast_solar_domain(hass: HomeAssistant) -> list[BaselineCandidate]:
    """Find every loaded Forecast.Solar config entry and, for each, build
    the one `forecast_solar`-shaped candidate its `get_forecast` service
    response supports (ADR-009 Amendment). Unlike `_scan_sensor_domain`/
    `_scan_weather_domain`, this is not an attribute-shape scan at all —
    Forecast.Solar is identified by its config entry existing, not by
    any discoverable attribute (there is none left to find).
    """
    config_entries = getattr(hass, "config_entries", None)
    if config_entries is None:
        return []  # defensive fallback (ADR-000 §8) — see module docstring
    found: list[BaselineCandidate] = []
    for entry in config_entries.async_loaded_entries(_FORECAST_SOLAR_DOMAIN):
        raw = await _sample_forecast_solar(hass, entry.entry_id)
        if not normalize_candidate_series("forecast_solar", raw):
            continue
        history_entity_id = resolve_forecast_solar_history_entity(hass, entry.entry_id)
        found.append(_build_forecast_solar_candidate(entry.entry_id, history_entity_id))
    return found


async def discover_baseline_candidates(hass: HomeAssistant) -> list[BaselineCandidate]:
    """Scan `sensor.*`/`weather.*` entities for forecast-shaped data and
    every loaded Forecast.Solar config entry, returning every recognized
    candidate ranked by score descending (ADR-009 §1/§3). Never
    auto-selects — the config flow (ADR-010) presents these to the user
    for confirmation.

    `async` since ADR-009 Amendment: sampling a `weather.*` entity's
    forecast requires an awaited `weather.get_forecasts` service call
    (`_scan_weather_domain`), and sampling a Forecast.Solar config entry
    requires an awaited `forecast_solar.get_forecast` call
    (`_scan_forecast_solar_domain`), rather than a synchronous `state.
    attributes` read. `_scan_sensor_domain` itself stays a plain
    synchronous read — `sensor.*` attributes are unaffected by either
    change — so it is called directly rather than awaited.
    """
    candidates = (
        _scan_sensor_domain(hass)
        + await _scan_weather_domain(hass)
        + await _scan_forecast_solar_domain(hass)
    )
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
    read the live series and normalize it through
    `normalize.normalize_candidate_series`, the same mapping function,
    for the past range and the live forward range respectively.

    A `_PUSH_SOURCED_SHAPES` instance (`weather_sunshine`/`weather_cloud`,
    ADR-009 Amendment "forecast subscription sourcing"; `forecast_solar`,
    ADR-009 Amendment "Forecast.Solar polling sourcing") has no attribute
    left to read at all — current HA core exposes neither integration's
    forecast data as a state attribute any more — so its live series
    instead arrives out-of-band, via `update_live_forecast()`. For the
    two weather shapes this is called by `coordinator.py`'s weather
    forecast subscription listener whenever that entity's `weather.
    async_subscribe_forecast` callback fires (§4a); for `forecast_solar`
    it is called by `coordinator.py`'s hourly Forecast.Solar poll (§4b).
    A `sensor_dict`/`sensor_list` instance is unaffected by either
    amendment and keeps reading its attribute directly, exactly as
    before.

    For a `forecast_solar` instance specifically, `entity_id` (both the
    constructor argument and `self._entity_id`) does not hold a real HA
    entity_id at all — it holds that Forecast.Solar config entry's own
    `entry_id` (see `providers/discovery.py`'s module-level `_FORECAST_
    SOLAR_*` comment for why). This only matters to `identify()`
    (returns that same value, unresolvable via `hass.states.get`) and to
    `coordinator.py`'s `_poll_forecast_solar`/`missing_required_entities`
    (both already shape-aware); `fetch()`/`forward()` themselves never
    touch `_entity_id` for this shape at all, since `_read_raw_attribute`
    reads `_latest_forecast` instead.

    A `forecast_solar` instance may additionally carry a
    `history_entity_id` (ADR-009 §1c Amendment, "recorder-backed baseline
    history", `TASK-0034`) — that config entry's own companion,
    continuously-recorded sensor, resolved at discovery time. This class
    itself never reads it (`fetch()`/`forward()` are both unchanged by
    that amendment); it is `coordinator.py`'s `_fetch_fn` that calls the
    generic `Provider.history_entity_id()` (ADR-012 §1/§2a Amendment) to
    decide whether a past-dated query should go through the recorder
    instead of `fetch()`.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        attribute: str,
        shape: BaselineShape,
        history_entity_id: str | None = None,
    ) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._attribute = attribute
        self._shape = shape
        # Only ever populated for a `_PUSH_SOURCED_SHAPES` instance, by
        # `update_live_forecast()` — `None` until the first subscription
        # callback/poll fires.
        self._latest_forecast: Any = None
        # ADR-009 §1c Amendment / ADR-012 §2a Amendment (`TASK-0034`) — a
        # linked, recorder-backed history entity_id, carried through from
        # the confirmed `BaselineCandidate` (only ever non-`None` for a
        # `forecast_solar` instance). Read by `coordinator.py`'s
        # `_fetch_fn`, never by this class's own `fetch()`/`forward()` —
        # recorder access stays `coordinator.py`'s alone (ADR-012 §2a).
        self._history_entity_id = history_entity_id

    def history_entity_id(self) -> str | None:
        """This instance's linked recorder-backed history entity_id
        (ADR-009 §1c Amendment; `Provider.history_entity_id`, ADR-012
        §2a Amendment), if one was resolved at discovery time — `None`
        for every shape except a `forecast_solar` instance whose
        companion sensor was found. Read generically by
        `coordinator.py`'s `_fetch_fn` for every provider, not just this
        one (ADR-012 §2a Amendment); this override supplies the one
        concrete answer this class currently has, exactly the way
        `forward()` below supplies the one concrete push-path answer
        `_PUSH_SOURCED_SHAPES` currently has.
        """
        return self._history_entity_id

    def set_history_entity_id(self, history_entity_id: str) -> None:
        """Update this instance's linked history entity_id after
        construction (ADR-009 §1c further Amendment, `TASK-0034-patch-1`)
        — the one mutation this otherwise-immutable-after-construction
        field ever undergoes, and only ever in one direction: `None` →
        resolved. Called exclusively by `coordinator.py`'s `async_startup`
        self-heal retry, immediately after a same-session
        `resolve_forecast_solar_history_entity` re-resolution succeeds
        where the original discovery-time attempt (persisted into config
        entry data at the time) did not. Never called with `None` — a
        still-failed retry leaves the instance exactly as constructed,
        to be retried again next restart.
        """
        self._history_entity_id = history_entity_id

    @property
    def shape(self) -> BaselineShape:
        """This instance's resolved `BaselineShape` — read by
        `coordinator.py` to tell a `forecast_solar` instance (needs
        `_register_forecast_solar_polls`, §4b) apart from every other
        shape (needs neither that nor §4a's weather subscription, or
        needs §4a specifically) without re-deriving it from raw config.
        """
        return self._shape

    @property
    def forecast_type(self) -> str | None:
        """Which `weather.get_forecasts` granularity to subscribe to
        (§4a) — derived from `shape`, same as `BaselineCandidate.
        forecast_type`; `None` for a `sensor.*`-sourced instance, which
        has nothing to subscribe to, and for a `forecast_solar` instance,
        which polls a service instead (§4b) rather than subscribing.
        """
        return _FORECAST_TYPE if self._shape in _WEATHER_SHAPES else None

    def update_live_forecast(self, raw: Any) -> None:
        """Record a freshly pushed/polled forecast payload (§4a/§4b) —
        called only by `coordinator.py`'s weather forecast subscription
        listener or Forecast.Solar poll, never by `fetch()`/`forward()`
        themselves.
        """
        self._latest_forecast = raw

    def identify(self) -> EntityRef | None:
        return EntityRef(self._entity_id, self._attribute)

    def _read_raw_attribute(self) -> Any:
        if self._shape in _PUSH_SOURCED_SHAPES:
            return self._latest_forecast
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
