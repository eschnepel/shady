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

**Aggregate sensors and the energy-integral totals (ADR-005, TASK-0012):**
`pv_sum`/`fc_sum`/`fc_day_array`/`fc_day_energy_total`/
`fc_remaining_energy` are plain, poll-friendly methods — `sensor.py`'s
six aggregate entities call them directly on every read, the same
polling relationship `ShadyForecastSensor` already has with this module.
The two energy-integral totals (§5/§6) are different: they are
event-driven running sums that must survive a restart exactly, so they
live in `cache.py` (restart-persisted, ADR-007 §1) and are only ever
advanced by `_accumulate_energy`, called from three trigger points —
`_refit_sync` (recalibration), `_async_recompute` (baseline-update
recompute), and `_handle_actual_yield_update` (a new, separate
actual-yield state-change listener; actual-yield entities are not
`Provider`s, so they cannot reuse `_register_provider_listeners`).
`_accumulate_energy` itself is deliberately **hass-free** — it only
touches `self.cache` — because `_refit_sync` runs inside
`hass.async_add_executor_job`'s executor thread, not on the event loop;
it is therefore safe to call from there directly. Persisting the
updated totals to `Store` is done differently depending on whether the
trigger point already has an `await` of its own to attach to:
`async_refit` and `_async_recompute` are themselves coroutines, already
awaited/scheduled by their one respective caller, so each simply
`await self._async_persist_energy_state()`s directly at the end of its
own body — no detached task. `_handle_actual_yield_update` and
`_handle_energy_reset`, by contrast, are synchronous `@callback`s with
no `await` of their own to attach to, so those two are the only two
places that genuinely need `hass.async_create_task(self.
_async_persist_energy_state())` as a fire-and-forget schedule.
`async_restore_energy_state` — the startup counterpart — is
deliberately **not** called from `__init__`/`async_startup`: it needs a
direct call from `__init__.py` (`TASK-0016`, does not exist yet),
independent of `missing_required_entities()`'s gate, since the integral
totals need no external entity to exist in order to restore. It also
registers the midnight-reset schedule itself, at the very end (after
its own idempotency check), so that schedule structurally cannot fire
before the restore has run.
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
from homeassistant.helpers.storage import Store
from numpy.typing import NDArray

from .aggregation import (
    day_energy_total_wh,
    remaining_energy_wh,
    sum_values,
    trapezoidal_energy_increment,
)
from .cache import SLOT_DURATION, SLOTS_PER_DAY, Cache, EnergyKind
from .const import (
    CONF_BASELINE_ATTRIBUTE,
    CONF_BASELINE_ENTITY_ID,
    CONF_BASELINE_SHAPE,
    CONF_CLIPPING_THRESHOLD,
    CONF_DEFAULT_TEMPERATURE_SOURCE,
    CONF_MAX_UPLIFT_C,
    CONF_NEIGHBOR_FITTING_CUTOFF,
    CONF_RECENCY_DECAY_MAX,
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

# ADR-005 §3/§4: the last of today's 288 slots, 23:55 — matching
# `sensor.py`'s own `_LAST_SLOT_OF_DAY` convention for `ShadyForecastSensor`'s
# day-array attributes.
_LAST_SLOT_OF_DAY = timedelta(hours=23, minutes=55)

# `homeassistant.helpers.storage.Store`'s schema version for the
# energy-integral totals (ADR-005 §5/§6, ADR-007 §1) — bump only on an
# incompatible on-disk schema change.
_ENERGY_STORE_VERSION = 1


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
        self._recency_decay_max: float = data[CONF_RECENCY_DECAY_MAX]
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
        # ADR-005 §5/§6, ADR-007 §1 — the one restart-persisted cache in
        # this design. Constructing `Store` is synchronous and cheap;
        # actually loading from disk only happens in
        # `async_restore_energy_state`, called by `__init__.py`
        # (TASK-0016), not here (see module docstring).
        self._energy_store: Store[dict[str, Any]] = Store(
            self.hass, _ENERGY_STORE_VERSION, f"{DOMAIN}_{entry.entry_id}_energy_totals"
        )
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
        self._register_actual_yield_listeners()

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

    def _numeric_state(self, entity_id: str) -> float | None:
        """The current numeric reading of `entity_id`'s live HA state
        (ADR-005 §1's `ShadyPvSumSensor`) — `None` if the entity does
        not currently exist, or its state string is not parseable as a
        float (e.g. `"unknown"`/`"unavailable"`). HA state values are
        always strings; this is the one place that ever parses one into
        a `float` (`aggregation.sum_values` is only ever handed already-
        numeric-or-`None` inputs, never a raw HA state string)."""
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

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
        # Already a coroutine, already being awaited by every caller
        # (the manual button, `_handle_midnight`'s own
        # `hass.async_create_task(self.async_refit(now))`) — awaited
        # directly rather than a second detached
        # `hass.async_create_task`, unlike the two *synchronous*
        # `@callback` trigger points below, which have no `await` of
        # their own to attach to.
        await self._async_persist_energy_state()

    def _refit_sync(self, now: datetime) -> None:
        for string in self._strings:
            model = self._fit_string(string, now)
            if model is not None:
                self._models[string.index] = model
                # Recalibration completion is itself a recompute trigger
                # (ADR-002 §2, trigger 1) — reuses the exact same
                # `_recompute_string` path §2's second trigger (a
                # baseline-entity update) already runs, applying the
                # freshly-fitted model to whatever baseline data is
                # currently cached (TASK-0010-patch-1).
                self._recompute_string(string, now)
        self._last_fit_at = now
        # ADR-005 §2/§6: recalibration completion is a recompute
        # trigger, exactly like a baseline-entity update — accumulate
        # once here too. Hass-free (see module docstring): this method
        # runs inside `async_refit`'s executor-thread dispatch, so the
        # `Store` write itself is scheduled by `async_refit`, back on
        # the event loop, not from here.
        self._accumulate_fc_energy(now)

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
            self._recency_decay_max,
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

    def strings(self) -> list[tuple[int, str]]:
        """Public `(index, name)` pairs, one per configured string, in
        `CONF_STRINGS` order (TASK-0010-patch-2) — lets `sensor.py`
        (TASK-0011) and, later, `TASK-0015`'s per-string diagnostics
        entities enumerate strings without depending on the private
        `_StringConfig` list/type.
        """
        return [(string.index, string.name) for string in self._strings]

    # -- aggregate sensors (ADR-005 §1-§4, TASK-0012) ---------------------
    #
    # All four below are plain, poll-friendly methods — `sensor.py`'s
    # `ShadyPvSumSensor`/`ShadyFcSumSensor`/`ShadyFcDaySumSensor`/
    # `ShadyFcRemainingTodaySensor` call these directly on every read,
    # the same relationship `ShadyForecastSensor` already has with this
    # module (ADR-005's own "sensor.py stays thin" note).

    def pv_sum(self) -> float | None:
        """ADR-005 §1: the current actual-yield state, summed across
        every configured string — a plain state-tracking aggregate,
        independent of the coordinator's fit/recompute cycle."""
        return sum_values(
            self._numeric_state(string.actual_yield_entity_id) for string in self._strings
        )

    def fc_sum(self, now: datetime | None = None) -> float | None:
        """ADR-005 §2: the current-slot corrected forecast, summed
        across every configured string — one `get_time_range` call
        (single-slot range) over every `ShadyForecastSensor` cache key
        at once."""
        resolved_now = now if now is not None else self._now()
        sensor_ids = [self.forecast_sensor_id(index) for index, _name in self.strings()]
        if not sensor_ids:
            return None
        raw = self.cache.get_time_range(sensor_ids, resolved_now, resolved_now, on_invalid="raw")
        return sum_values(
            value if isinstance(value := raw[sensor_id][0], float) else None
            for sensor_id in sensor_ids
        )

    def fc_day_array(
        self, now: datetime | None = None
    ) -> tuple[list[datetime], list[float | None]]:
        """ADR-005 §3: today's 288 `(timestamp, cross-string-summed
        corrected-forecast)` pairs — including already-past slots — via
        one `get_time_range(..., group_by="slot")` call, which already
        returns "for this slot, every string's value" ready to sum
        directly (ADR-007a §5). `ShadyFcDaySumSensor`'s own state
        (`fc_day_energy_total`) and `ShadyFcRemainingTodaySensor`
        (`fc_remaining_energy`) both build on this same array — no
        second data-retention mechanism (ADR-005 §4)."""
        resolved_now = now if now is not None else self._now()
        today_start = datetime(resolved_now.year, resolved_now.month, resolved_now.day, tzinfo=UTC)
        slot_timestamps = [today_start + i * SLOT_DURATION for i in range(SLOTS_PER_DAY)]

        sensor_ids = [self.forecast_sensor_id(index) for index, _name in self.strings()]
        if not sensor_ids:
            return slot_timestamps, [None] * SLOTS_PER_DAY

        slots = self.cache.get_time_range(
            sensor_ids,
            today_start,
            today_start + _LAST_SLOT_OF_DAY,
            on_invalid="raw",
            group_by="slot",
        )
        slot_values: list[float | None] = [
            sum_values(value if isinstance(value, float) else None for value in slot.values())
            for slot in slots
        ]
        return slot_timestamps, slot_values

    def fc_day_energy_total(self, now: datetime | None = None) -> float:
        """ADR-005 §3's own sensor state — not a sum of Watts, but
        `Σ (P_i × 5/60)` in Wh over `fc_day_array`'s `slot_values`."""
        _timestamps, slot_values = self.fc_day_array(now)
        return day_energy_total_wh(slot_values)

    def fc_remaining_energy(self, now: datetime | None = None) -> float:
        """ADR-005 §4: the same energy calculation, restricted to
        `fc_day_array`'s slots at/after `now` — pure post-processing of
        the exact same array §3 already produced."""
        resolved_now = now if now is not None else self._now()
        slot_timestamps, slot_values = self.fc_day_array(resolved_now)
        return remaining_energy_wh(slot_timestamps, slot_values, resolved_now)

    # -- energy-integral totals (ADR-005 §5/§6, TASK-0012) ----------------

    def _maybe_reset_energy_totals(self, now: datetime) -> bool:
        """Idempotent day-boundary guard (ADR-005 §5/§6's own
        "Restart-during-the-reset-window idempotency" note) — resets
        both energy-integral totals iff `cache.py`'s `last_reset_date`
        is not already `now`'s calendar date, and reports whether a
        reset actually happened. Called from three places: every
        `_accumulate_energy` call (so a delayed/missed midnight trigger
        can never leave a stale total to accumulate onto), the midnight
        schedule itself, and `async_restore_energy_state` — the same
        check performs the reset regardless of which of the three
        triggers it fires from, including the pathological case where
        more than one lands in the same narrow window."""
        today = now.date()
        if self.cache.last_reset_date() == today:
            return False
        self.cache.reset_energy_totals(today)
        return True

    def _accumulate_energy(self, kind: EnergyKind, now: datetime, power: float) -> None:
        """The stateful half of ADR-005 §5/§6's running total: reads
        `cache.py`'s last remembered sample for `kind`, adds
        `aggregation.trapezoidal_energy_increment`'s Wh increment onto
        `cache.py`'s running total, and remembers `(now, power)` as the
        new last sample. Deliberately **hass-free** — only touches
        `self.cache` — see the module docstring for why: this is called
        from `_refit_sync`, which runs inside an executor thread, not
        on the event loop."""
        self._maybe_reset_energy_totals(now)
        previous = self.cache.last_energy_sample(kind)
        increment = trapezoidal_energy_increment(previous, (now, power))
        self.cache.set_energy_total(kind, self.cache.energy_total(kind) + increment)
        self.cache.set_last_energy_sample(kind, (now, power))

    def _accumulate_fc_energy(self, now: datetime) -> None:
        """Shared by every recompute trigger (`_refit_sync`,
        `_async_recompute`) — ADR-005 §2's "same trigger as the
        per-string corrected-forecast sensors" applied to §6's integral:
        re-reads the *current, full* cross-string `fc_sum()` (reflecting
        every string, not just whichever ones this particular trigger
        touched) and accumulates one increment from it."""
        total = self.fc_sum(now)
        if total is not None:
            self._accumulate_energy("fc", now, total)

    async def _async_persist_energy_state(self) -> None:
        """Writes both energy-integral totals + `last_reset_date` to
        `Store` (ADR-005 §5/§6, ADR-007 §1's restart-persistence). Must
        run on the event loop — `async_refit`/`_async_recompute` await
        this directly (they're coroutines already on the event loop);
        `_handle_actual_yield_update`/`_handle_energy_reset` (plain
        synchronous `@callback`s) schedule it via
        `hass.async_create_task` instead, never from inside
        `_accumulate_energy`'s hass-free body itself."""
        last_reset = self.cache.last_reset_date() or self._now().date()
        await self._energy_store.async_save(
            {
                "pv_total": self.cache.energy_total("pv"),
                "fc_total": self.cache.energy_total("fc"),
                "last_reset_date": last_reset.isoformat(),
            }
        )

    async def async_restore_energy_state(self) -> None:
        """Restart-persistence entry point (ADR-005 §5/§6) — loads
        whatever was last saved (if anything) from `Store`, applies the
        startup idempotency check, and only then registers the
        midnight-reset schedule (see module docstring for why this
        ordering matters). **Not** called from `__init__`/
        `async_startup` — `__init__.py` (`TASK-0016`) must call this
        directly; it does not exist yet."""
        stored = await self._energy_store.async_load()
        if stored is not None:
            self.cache.restore_energy_state(
                float(stored["pv_total"]),
                float(stored["fc_total"]),
                date.fromisoformat(stored["last_reset_date"]),
            )
        self._maybe_reset_energy_totals(self._now())
        self._register_energy_reset_schedule()

    def _register_energy_reset_schedule(self) -> None:
        """ADR-005 §5/§6's fourth, independent schedule — right at the
        day boundary (`hour=0, minute=0, second=0`), deliberately not
        reusing ADR-002 §1's `minute=1`-offset recalibration trigger nor
        ADR-006 §1a's 5-minute poll (module docstring / ADR-005's own
        "deliberately not reusing either of those triggers" note)."""
        self._unsub.append(
            async_track_time_change(
                self.hass, self._handle_energy_reset, hour=0, minute=0, second=0
            )
        )

    @callback  # type: ignore[untyped-decorator]
    def _handle_energy_reset(self, now: datetime) -> None:
        if self._maybe_reset_energy_totals(now):
            self.hass.async_create_task(self._async_persist_energy_state())

    def _register_actual_yield_listeners(self) -> None:
        """A new state-change listener over every configured string's
        actual-yield entity, separate from `_register_provider_listeners`
        (actual-yield entities are plain user-selected entities, not
        `Provider`s — ADR-012 §4's generic loop has no notion of them).
        Drives `_handle_actual_yield_update`, which both `pv_sum()`
        implicitly reflects on its next poll and §5's PV energy integral
        accumulates from directly."""
        if not self._actual_yield_entity_ids:
            return
        self._unsub.append(
            async_track_state_change_event(
                self.hass, list(self._actual_yield_entity_ids), self._handle_actual_yield_update
            )
        )

    @callback  # type: ignore[untyped-decorator]
    def _handle_actual_yield_update(self, _event: Any) -> None:
        now = self._now()
        total = self.pv_sum()
        if total is not None:
            self._accumulate_energy("pv", now, total)
        self.hass.async_create_task(self._async_persist_energy_state())

    async def _async_recompute(self, strings: list[_StringConfig], now: datetime) -> None:
        for string in strings:
            self._recompute_string(string, now)
        self._accumulate_fc_energy(now)
        # Already a coroutine, already awaited/scheduled by its one
        # caller (`_make_listener`'s `hass.async_create_task(self.
        # _async_recompute(...))`) — awaited directly here too, same
        # reasoning as `async_refit`.
        await self._async_persist_energy_state()

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
