"""`coordinator.py` — the only module that imports `cache.py` (ADR-000
§3, ADR-007). Owns: the daily recalibration schedule + button-triggered
refit sharing one code path (ADR-002 §1), the startup safety net and
`missing_required_entities()` startup-ordering check `__init__.py`
(TASK-0016) calls (ADR-002 §1a), baseline-update-triggered forecast
recompute with no debounce (ADR-002 §2/§3), and the one generic
provider-push loop shared by every `forward()`-overriding provider
(ADR-012 §4).

**Recorder access runs off the event loop.** `cache.py`'s `fetch_fn` is
a plain synchronous callable (ADR-007a §4) — for the actual-yield
entity (the only source read via the recorder's `statistics_during_period`
rather than a `Provider`, per `adr-summary.md` §4) that means blocking
I/O. `async_refit`/`async_startup` therefore dispatch the entire
cache-touching body via `hass.async_add_executor_job`, never awaiting
partway through — see the module docstring in `cache.py` and ADR-007a
§4 for why `fetch_fn` itself has no async awareness at all. Push and
recompute never touch the recorder (`BaselineProvider`/`TemperatureProvider`
only read `hass.states`, an in-memory, non-blocking lookup) and so run
directly on the event loop.

**Temperature derating scope, this task (ADR-003b §1/§1a):** only the
weather-integration tier is implemented here — the module/cell and
ambient-sensor tiers' forward+reverse correction structurally depends on
ADR-003c's learned per-slot temperature-forecast model, which does not
exist yet (`TASK-0014`, still `todo`). A string whose resolved
temperature source is a `sensor.*` entity is therefore left with
derating skipped entirely for now, exactly as ADR-003b §1's own stated
dependency chain requires — not a shortcut invented here. `TASK-0014`'s
own job is to extend this module's temperature resolution to cover that
tier once its learned-model machinery exists.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from numpy.typing import NDArray

from .cache import SLOT_DURATION, SLOTS_PER_DAY, Cache
from .const import (
    CONF_BASELINE_ATTRIBUTE,
    CONF_BASELINE_ENTITY_ID,
    CONF_BASELINE_SHAPE,
    CONF_CLIPPING_THRESHOLD,
    CONF_DEFAULT_TEMPERATURE_SOURCE,
    CONF_MAX_UPLIFT_C,
    CONF_NEIGHBOR_FITTING_CUTOFF,
    CONF_REGRESSION_METHOD,
    CONF_SMOOTHING_RADIUS,
    CONF_STRING_ACTUAL_YIELD_ENTITY,
    CONF_STRING_BASELINE_ATTRIBUTE,
    CONF_STRING_BASELINE_ENTITY_ID,
    CONF_STRING_BASELINE_SHAPE,
    CONF_STRING_CONVERTER_LIMIT_W,
    CONF_STRING_NAME,
    CONF_STRING_RATED_DC_CAPACITY_WP,
    CONF_STRING_TEMPERATURE_COEFFICIENT,
    CONF_STRING_TEMPERATURE_SOURCE,
    CONF_STRINGS,
    CONF_TEMPERATURE_AWARE,
    CONF_WINDOW_DAYS,
    DEFAULT_STRING_TEMPERATURE_COEFFICIENT,
    DOMAIN,
    TEMPERATURE_SOURCE_NONE,
)
from .forecast_adjust import adjust_forecast
from .providers.base import Provider
from .providers.discovery import BaselineProvider
from .providers.temperature import TemperatureProvider
from .regression import kernel, linear, wls2, wls3
from .regression.base import FittedModel, build_pool
from .yield_correction import derate_actual_to_reference, exclude_clipped, uplift_ambient_to_cell

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .providers.normalize import BaselineShape

# Same registry shape for both the shading model's global method choice
# (ADR-001 §2) and, later, ADR-003c's independent temperature-forecast
# method — one place mapping the four config-flow choices (`const.py`'s
# `REGRESSION_METHODS`) to their `regression/` module.
_REGRESSION_STRATEGIES: dict[str, Any] = {
    "linear": linear,
    "kernel": kernel,
    "wls2": wls2,
    "wls3": wls3,
}

_STATISTICS_PERIOD = "5minute"


def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0]


def _slot_of_day(timestamp: datetime) -> int:
    day_start = datetime(timestamp.year, timestamp.month, timestamp.day, tzinfo=timestamp.tzinfo)
    return int((timestamp - day_start) / SLOT_DURATION)


def _tomorrow_end(now: datetime) -> datetime:
    """The exclusive end of ADR-002 §3's horizon: start of the day after
    tomorrow — "remainder of today + all of tomorrow"."""
    today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
    return today_start + timedelta(days=2)


def _split_by_offset(
    pooled: NDArray[np.float64], smoothing_radius: int, window_days: int
) -> dict[int, NDArray[np.float64]]:
    """Slice `cache.py`'s `get_regression_pools` column layout (ascending
    offset blocks, `window_days` columns each — see that method's own
    "Column layout" docstring) into `regression/base.py`'s `build_pool`
    per-offset input contract (`dict[offset, NDArray]`, shape
    `(n_slots, window_days)` each) — the exact adapter gap TASK-0005's
    own module docstring flags as `coordinator.py`'s (this task's) job.
    """
    result: dict[int, NDArray[np.float64]] = {}
    for position, offset in enumerate(range(-smoothing_radius, smoothing_radius + 1)):
        start_col = position * window_days
        result[offset] = pooled[:, start_col : start_col + window_days]
    return result


@dataclass(frozen=True)
class _StringConfig:
    """Resolved, ready-to-use per-string configuration — `const.py`'s
    stored dict, parsed once at coordinator construction rather than
    re-parsed on every trigger. `index` is this string's position in
    `CONF_STRINGS` — used for `forecast_sensor_id` (TASK-0011's Consumed
    Interface), since a string's `name` is free-text and not guaranteed
    unique (config_flow.py, TASK-0009, only validates non-empty).
    """

    index: int
    name: str
    actual_yield_entity_id: str
    baseline_entity_id: str | None
    baseline_attribute: str | None
    baseline_shape: BaselineShape | None
    converter_limit_w: float | None
    temperature_source_entity_id: str | None
    temperature_coefficient_pct_per_c: float
    rated_dc_capacity_wp: float | None

    @property
    def has_baseline_override(self) -> bool:
        return self.baseline_entity_id is not None


def _resolve_string(index: int, raw: dict[str, Any]) -> _StringConfig:
    return _StringConfig(
        index=index,
        name=raw[CONF_STRING_NAME],
        actual_yield_entity_id=raw[CONF_STRING_ACTUAL_YIELD_ENTITY],
        baseline_entity_id=raw.get(CONF_STRING_BASELINE_ENTITY_ID),
        baseline_attribute=raw.get(CONF_STRING_BASELINE_ATTRIBUTE),
        baseline_shape=raw.get(CONF_STRING_BASELINE_SHAPE),
        converter_limit_w=raw.get(CONF_STRING_CONVERTER_LIMIT_W),
        temperature_source_entity_id=raw.get(CONF_STRING_TEMPERATURE_SOURCE),
        temperature_coefficient_pct_per_c=raw.get(
            CONF_STRING_TEMPERATURE_COEFFICIENT, DEFAULT_STRING_TEMPERATURE_COEFFICIENT
        ),
        rated_dc_capacity_wp=raw.get(CONF_STRING_RATED_DC_CAPACITY_WP),
    )


class ShadyCoordinator:
    """Per-config-entry orchestrator (ADR-002, ADR-007, ADR-012 §4)."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        data = entry.data

        self._window_days: int = data[CONF_WINDOW_DAYS]
        self._regression_method: str = data[CONF_REGRESSION_METHOD]
        self._smoothing_radius: int = data[CONF_SMOOTHING_RADIUS]
        self._neighbor_fitting_cutoff: float = data[CONF_NEIGHBOR_FITTING_CUTOFF]
        self._clipping_threshold: float = data[CONF_CLIPPING_THRESHOLD]
        self._max_uplift_c: float = data[CONF_MAX_UPLIFT_C]
        self._global_temperature_aware: bool = data.get(CONF_TEMPERATURE_AWARE, False)
        self._default_temperature_source: str | None = data.get(CONF_DEFAULT_TEMPERATURE_SOURCE)
        self._global_baseline_entity_id: str | None = data.get(CONF_BASELINE_ENTITY_ID)
        self._global_baseline_attribute: str | None = data.get(CONF_BASELINE_ATTRIBUTE)
        self._global_baseline_shape: BaselineShape | None = data.get(CONF_BASELINE_SHAPE)

        self._strings: list[_StringConfig] = [
            _resolve_string(index, raw) for index, raw in enumerate(data.get(CONF_STRINGS, []))
        ]

        # sensor_id -> Provider, for both `_fetch_fn`'s cache-miss
        # dispatch and the generic push loop (ADR-012 §4). Populated
        # entirely from static config below — no `hass.states` access
        # at construction time (ADR-002 §1a: this must work even before
        # any referenced entity exists yet).
        self._entity_providers: dict[str, Provider] = {}
        self._actual_yield_entity_ids: set[str] = set()
        # resolved baseline entity_id -> strings using it (ADR-002 §2).
        self._baseline_entity_strings: dict[str, list[_StringConfig]] = {}

        if self._global_baseline_entity_id is not None:
            self._ensure_baseline_provider(
                self._global_baseline_entity_id,
                self._global_baseline_attribute,
                self._global_baseline_shape,
            )

        for string in self._strings:
            self._actual_yield_entity_ids.add(string.actual_yield_entity_id)
            if string.has_baseline_override:
                assert string.baseline_entity_id is not None
                self._ensure_baseline_provider(
                    string.baseline_entity_id, string.baseline_attribute, string.baseline_shape
                )
            baseline_entity_id = string.baseline_entity_id or self._global_baseline_entity_id
            if baseline_entity_id is not None:
                self._baseline_entity_strings.setdefault(baseline_entity_id, []).append(string)

            temperature_entity_id = self._resolve_weather_temperature_entity(string)
            if temperature_entity_id is not None:
                self._ensure_temperature_provider(temperature_entity_id)

        self.cache = Cache(self._window_days, self._fetch_fn)
        self._models: dict[int, FittedModel] = {}
        # In-memory only (this task's own scope decision — see
        # Delivered Artifacts): every restart already implies "no model
        # fitted yet" below, which alone satisfies ADR-002 §1's startup
        # safety net on every restart regardless of this timestamp: the
        # >24h branch only ever matters within one long-lived process
        # (e.g. the midnight trigger silently failing to fire once).
        self._last_fit_at: datetime | None = None

        self._unsub: list[Callable[[], None]] = []
        # Injectable clock (a plain callable, not a `Mock`) — the one
        # place this module reads "now" without an explicit parameter
        # (state-change-triggered push/recompute, ADR-012 §4/ADR-002
        # §2); tests substitute a fixed value the same way `cache.py`'s
        # own `reference` parameter is used elsewhere for determinism.
        self._now: Callable[[], datetime] = lambda: datetime.now(UTC)
        self._register_schedule()
        self._register_provider_listeners()

    # -- construction helpers --------------------------------------------

    def _ensure_baseline_provider(
        self, entity_id: str, attribute: str | None, shape: BaselineShape | None
    ) -> None:
        if entity_id in self._entity_providers or attribute is None or shape is None:
            return
        self._entity_providers[entity_id] = BaselineProvider(self.hass, entity_id, attribute, shape)

    def _ensure_temperature_provider(self, entity_id: str) -> None:
        if entity_id in self._entity_providers:
            return
        self._entity_providers[entity_id] = TemperatureProvider(self.hass, entity_id, "weather")

    def _resolve_weather_temperature_entity(self, string: _StringConfig) -> str | None:
        """This task's temperature-source resolution (module docstring):
        weather tier only. `None` for an unset/disabled/sensor-tier
        source alike — the caller cannot and need not distinguish those
        cases further (all three mean "no derating for this string").
        """
        entity_id = string.temperature_source_entity_id or self._default_temperature_source
        if entity_id is None or entity_id == TEMPERATURE_SOURCE_NONE:
            return None
        if _domain(entity_id) != "weather":
            return None
        return entity_id

    def _provider_already_corrects(self, string: _StringConfig) -> bool:
        """ADR-003b §1c: a per-string baseline override is
        temperature-aware by definition; a string on the global default
        follows the global flag."""
        return True if string.has_baseline_override else self._global_temperature_aware

    # -- fetch_fn dispatch (ADR-007a §4) ---------------------------------

    def _fetch_fn(self, sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
        provider = self._entity_providers.get(sensor_id)
        if provider is not None:
            return provider.fetch(start, end)
        if sensor_id in self._actual_yield_entity_ids:
            return self._fetch_actual_yield_statistics(sensor_id, start, end)
        # Defensive fallback (ADR-000 §8) — every sensor_id this
        # coordinator ever queries comes from its own resolved config
        # above; this should be unreachable in practice.
        slot_count = int((end - start) / SLOT_DURATION)
        return [None] * slot_count

    def _fetch_actual_yield_statistics(
        self, entity_id: str, start: datetime, end: datetime
    ) -> list[float | None | str]:
        """The one recorder-backed source (ADR-007a §4, ADR-006 §1a's
        established `statistics_during_period` pattern; adr-summary.md
        §4: actual-yield has "nothing to identify or normalize", so it
        bypasses the `Provider` layer entirely). Must only be called
        off the event loop — see the module docstring.
        """
        raw = statistics_during_period(
            self.hass, start, end, {entity_id}, _STATISTICS_PERIOD, None, {"mean"}
        )
        rows = raw.get(entity_id, [])
        by_start: dict[datetime, float] = {}
        for row in rows:
            row_start = row["start"]
            if not isinstance(row_start, datetime):
                row_start = datetime.fromtimestamp(float(row_start), tz=UTC)
            mean = row.get("mean")
            if mean is not None:
                by_start[row_start] = float(mean)
        slot_count = int((end - start) / SLOT_DURATION)
        return [by_start.get(start + i * SLOT_DURATION) for i in range(slot_count)]

    # -- startup ordering (ADR-002 §1a, consumed by TASK-0016) ----------

    def missing_required_entities(self) -> list[str]:
        """Every required entity (per-string actual-yield; per-string
        resolved baseline, if configured) currently absent from
        `hass.states` — never an optional correction-tier entity
        (ADR-002 §1a)."""
        missing: list[str] = []
        for string in self._strings:
            if self.hass.states.get(string.actual_yield_entity_id) is None:
                missing.append(string.actual_yield_entity_id)
            baseline_entity_id = string.baseline_entity_id or self._global_baseline_entity_id
            if baseline_entity_id is not None and self.hass.states.get(baseline_entity_id) is None:
                missing.append(baseline_entity_id)
        return missing

    async def async_startup(self, now: datetime | None = None) -> None:
        """ADR-002 §1's startup safety net — called by `__init__.py`
        (TASK-0016), immediately or via its deferred `async_at_started`
        path, once `missing_required_entities()` is empty. `now`
        defaults to the real current time but is exposed as a parameter
        for testability, matching `cache.py`'s own `reference`
        convention.
        """
        resolved_now = now if now is not None else self._now()
        if self._last_fit_at is None or (resolved_now - self._last_fit_at) > timedelta(hours=24):
            await self.async_refit(resolved_now)

    def shutdown(self) -> None:
        """Cancel every registered listener/schedule (TASK-0016's
        `async_unload_entry`)."""
        while self._unsub:
            self._unsub.pop()()

    # -- recalibration (ADR-002 §1) --------------------------------------

    def _register_schedule(self) -> None:
        self._unsub.append(
            async_track_time_change(self.hass, self._handle_midnight, hour=0, minute=1, second=0)
        )

    @callback  # type: ignore[untyped-decorator]
    def _handle_midnight(self, now: datetime) -> None:
        self.hass.async_create_task(self.async_refit(now))

    async def async_refit(self, now: datetime | None = None) -> None:
        """The single refit routine both the midnight schedule and the
        manual button (`button.py`, TASK-0011) call (ADR-002 §1/§5).
        Dispatched via `hass.async_add_executor_job` — see module
        docstring.
        """
        resolved_now = now if now is not None else self._now()
        await self.hass.async_add_executor_job(self._refit_sync, resolved_now)

    def _refit_sync(self, now: datetime) -> None:
        for string in self._strings:
            model = self._fit_string(string, now)
            if model is not None:
                self._models[string.index] = model
        self._last_fit_at = now

    def _fit_string(self, string: _StringConfig, now: datetime) -> FittedModel | None:
        baseline_entity_id = string.baseline_entity_id or self._global_baseline_entity_id
        if baseline_entity_id is None or baseline_entity_id not in self._entity_providers:
            return None

        sensor_ids = [baseline_entity_id, string.actual_yield_entity_id]
        temperature_entity_id = self._resolve_weather_temperature_entity(string)
        if temperature_entity_id is not None:
            sensor_ids.append(temperature_entity_id)

        pools = self.cache.get_regression_pools(sensor_ids, self._smoothing_radius, reference=now)
        fc_by_offset = _split_by_offset(
            pools[baseline_entity_id], self._smoothing_radius, self._window_days
        )
        pv_by_offset = _split_by_offset(
            pools[string.actual_yield_entity_id], self._smoothing_radius, self._window_days
        )

        temperature_by_offset: dict[int, NDArray[np.float64]] | None = None
        if temperature_entity_id is not None:
            temperature_by_offset = _split_by_offset(
                pools[temperature_entity_id], self._smoothing_radius, self._window_days
            )

        corrected_pv_by_offset = self._apply_training_corrections(
            string, fc_by_offset, pv_by_offset, temperature_by_offset
        )

        pool = build_pool(
            fc_by_offset,
            corrected_pv_by_offset,
            self._smoothing_radius,
            self._neighbor_fitting_cutoff,
        )
        strategy = _REGRESSION_STRATEGIES[self._regression_method]
        model: FittedModel = strategy.fit(pool)
        return model

    def _apply_training_corrections(
        self,
        string: _StringConfig,
        fc_by_offset: dict[int, NDArray[np.float64]],
        pv_by_offset: dict[int, NDArray[np.float64]],
        temperature_by_offset: dict[int, NDArray[np.float64]] | None,
    ) -> dict[int, NDArray[np.float64]]:
        """ADR-003a §1/§2 (clipping) then ADR-003b §1/§1a (temperature
        derating, weather tier only this task — see module docstring),
        applied per offset, in that order (`yield_correction.py`'s own
        module docstring: exclude clipped before deriving to reference).
        """
        provider_already_corrects = self._provider_already_corrects(string)
        coefficient_per_c = string.temperature_coefficient_pct_per_c / 100.0
        use_temperature = (
            temperature_by_offset is not None
            and string.rated_dc_capacity_wp is not None
            and not provider_already_corrects
        )

        corrected: dict[int, NDArray[np.float64]] = {}
        for offset, pv in pv_by_offset.items():
            excluded = exclude_clipped(pv, string.converter_limit_w, self._clipping_threshold)
            cell_temperature: NDArray[np.float64] | None = None
            if use_temperature:
                assert temperature_by_offset is not None
                assert string.rated_dc_capacity_wp is not None
                uplifted = uplift_ambient_to_cell(
                    temperature_by_offset[offset],
                    fc_by_offset[offset],
                    string.rated_dc_capacity_wp,
                    self._max_uplift_c,
                )
                cell_temperature = np.asarray(uplifted, dtype=np.float64)
            corrected[offset] = np.asarray(
                derate_actual_to_reference(
                    excluded,
                    cell_temperature,
                    coefficient_per_c,
                    provider_already_corrects=provider_already_corrects,
                ),
                dtype=np.float64,
            )
        return corrected

    # -- forecast recompute (ADR-002 §2/§3) ------------------------------

    def forecast_sensor_id(self, string_index: int) -> str:
        """`ShadyForecastSensor`'s cache key (TASK-0011's Consumed
        Interface) — keyed by string index, not name (names are
        free-text, config_flow.py does not enforce uniqueness).
        """
        return f"{DOMAIN}_forecast_{self.entry.entry_id}_string_{string_index}"

    async def _async_recompute(self, strings: list[_StringConfig], now: datetime) -> None:
        for string in strings:
            self._recompute_string(string, now)

    def _recompute_string(self, string: _StringConfig, now: datetime) -> None:
        model = self._models.get(string.index)
        if model is None:
            return
        baseline_entity_id = string.baseline_entity_id or self._global_baseline_entity_id
        if baseline_entity_id is None:
            return
        provider = self._entity_providers.get(baseline_entity_id)
        if not isinstance(provider, BaselineProvider):
            return
        raw_series = provider.forward(now)
        if not raw_series:
            return

        horizon_end = _tomorrow_end(now)
        series = [(ts, value) for ts, value in raw_series if now <= ts < horizon_end]
        if not series:
            return

        by_day: dict[date, dict[int, float]] = {}
        for ts, value in series:
            by_day.setdefault(ts.date(), {})[_slot_of_day(ts)] = value

        pushed: dict[int, float] = {}
        for day, slot_values in by_day.items():
            pushed.update(self._predict_day(string, day, slot_values, now))

        if not pushed:
            return
        not_before_index = Cache.index_for(now) + 1
        self.cache.push(self.forecast_sensor_id(string.index), pushed, not_before_index)

    def _predict_day(
        self, string: _StringConfig, day: date, slot_values: dict[int, float], now: datetime
    ) -> dict[int, float]:
        model = self._models[string.index]
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        fc_array = np.full(SLOTS_PER_DAY, np.nan, dtype=np.float64)
        for slot, value in slot_values.items():
            fc_array[slot] = value

        provider_already_corrects = self._provider_already_corrects(string)
        coefficient_per_c = string.temperature_coefficient_pct_per_c / 100.0
        temperature_entity_id = self._resolve_weather_temperature_entity(string)

        target_cell_temperature: NDArray[np.float64] | None = None
        if (
            temperature_entity_id is not None
            and string.rated_dc_capacity_wp is not None
            and not provider_already_corrects
        ):
            temp_provider = self._entity_providers[temperature_entity_id]
            assert isinstance(temp_provider, TemperatureProvider)
            raw_temps = temp_provider.fetch(day_start, day_start + timedelta(days=1))
            ambient = np.array(
                [v if isinstance(v, float) else np.nan for v in raw_temps], dtype=np.float64
            )
            uplifted = uplift_ambient_to_cell(
                ambient, fc_array, string.rated_dc_capacity_wp, self._max_uplift_c
            )
            target_cell_temperature = np.asarray(uplifted, dtype=np.float64)

        adjusted, _confidence = adjust_forecast(
            model,
            fc_array,
            target_cell_temperature,
            coefficient_per_c,
            string.converter_limit_w,
            provider_already_corrects=provider_already_corrects,
        )

        now_index = Cache.index_for(now)
        result: dict[int, float] = {}
        for slot in slot_values:
            index = Cache.index_for(day_start) + slot
            if index < now_index:
                continue
            value = float(adjusted[slot])
            if not np.isnan(value):
                result[index] = value
        return result

    # -- generic provider-push loop (ADR-012 §4) -------------------------

    def _register_provider_listeners(self) -> None:
        for entity_id, provider in self._entity_providers.items():
            if type(provider).forward is Provider.forward:
                continue  # this provider has no forecast concept (ADR-012 §4)
            self._unsub.append(
                async_track_state_change_event(
                    self.hass, [entity_id], self._make_listener(entity_id)
                )
            )

    def _make_listener(self, entity_id: str) -> Callable[[Any], None]:
        """One handler per entity, but the *body* is fully generic —
        `entity_id` is the only thing that varies (ADR-012 §4's "no
        provider-specific listener code" requirement)."""

        @callback  # type: ignore[untyped-decorator]
        def _handle(_event: Any) -> None:
            now = self._now()
            self._push_provider_series(entity_id, now)
            strings = self._baseline_entity_strings.get(entity_id)
            if strings:
                self.hass.async_create_task(self._async_recompute(strings, now))

        return _handle  # type: ignore[no-any-return]

    def _push_provider_series(self, entity_id: str, now: datetime) -> None:
        provider = self._entity_providers.get(entity_id)
        if provider is None:
            return
        series = provider.forward(now)
        if not series:
            return
        values = {Cache.index_for(ts): value for ts, value in series}
        if not values:
            return
        not_before_index = Cache.index_for(now) + 1
        self.cache.push(entity_id, values, not_before_index)
