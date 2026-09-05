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

**Temperature derating scope (ADR-003b §1/§1a, ADR-003c):** all three
tiers are implemented. `weather` (a `weather.*`-domain resolved source)
reads/forecasts natively, unchanged since the original delivery. `cell`
(a per-string `temperature_source_entity_id` override, `sensor.*`
domain — ADR-003b §1a's dedicated module/cell sensor) and `ambient` (the
global `default_temperature_source`, `sensor.*` domain — one
property-wide reading) both need ADR-003c's learned per-slot
temperature-forecast model for a target-slot forecast, since neither has
a native one (`TASK-0014`) — `cell` is used directly, with no uplift;
`ambient` passes through the same `uplift_ambient_to_cell` transform a
live ambient reading would. Both, per ADR-003c §5, are silently skipped
(exactly as if no temperature source were configured) when no global
`weather_forecast_temperature_entity` predictor is configured —
`_resolve_temperature_entity` is the one place that rule is enforced,
so every downstream caller only ever sees "configured and forecastable"
or `None`, never a half-configured in-between state.

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

**Intraday deviation correction (ADR-006, TASK-0013):** a fifth,
independent schedule — `_register_intraday_schedule`'s 5-minute poll —
only registered when `intraday_correction_mode` is not `"off"`
(`__init__`; ADR-006 §1's "nothing computed or retained" when
Disabled). `_recompute_string` (every baseline-provider update AND
every recalibration alike — ADR-006 §1b's own "not a special case"
note) is a *reset point*: `_apply_intraday_reset` establishes a fresh
per-string `IntradayState`/`IntradayBasis` in `cache.py` at
`effective_factor == 1` (`w == 0`), freezing the previous *same-day*
basis as Blending's old crossfade side, if any. The 5-minute tick
(`_advance_intraday_string`) re-derives `w`/`ratio_string`/
`effective_factor` from the trailing window against that *unchanged*
basis and re-pushes — it never re-runs the regression model or the
temperature reverse-transform. `_compute_intraday_output` applies
Ramping's single multiply or Blending's two-sided crossfade
(`aggregation.py`'s `intraday_correction_factor`/`crossfade`) ahead of
the *one* final output clamp (`forecast_adjust.clamp_output`),
canonically ordered per ADR-006 §1b. Like the energy-integral tick,
`_async_intraday_tick` dispatches the actual work via
`hass.async_add_executor_job` — `_intraday_energy_window` reads the
actual-yield entity's recorder-backed history, the same blocking-I/O
concern as `_fetch_actual_yield_statistics`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.core import callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from numpy.typing import NDArray

from . import string_computation
from .aggregation import (
    crossfade,
    day_energy_total_wh,
    intraday_correction_factor,
    ramp_weight,
    remaining_energy_wh,
    sum_values,
    trapezoidal_energy_increment,
)
from .cache import SLOT_DURATION, SLOTS_PER_DAY, Cache, EnergyKind, IntradayBasis, IntradayState
from .const import (
    CONF_BASELINE_ATTRIBUTE,
    CONF_BASELINE_ENTITY_ID,
    CONF_BASELINE_SHAPE,
    CONF_CLIPPING_THRESHOLD,
    CONF_DEFAULT_TEMPERATURE_SOURCE,
    CONF_INTRADAY_CORRECTION_CUTOFF,
    CONF_INTRADAY_CORRECTION_MODE,
    CONF_MAX_UPLIFT_C,
    CONF_NEIGHBOR_FITTING_CUTOFF,
    CONF_RAMP_SLOTS,
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
    CONF_TEMPERATURE_REGRESSION_METHOD,
    CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY,
    CONF_WINDOW_DAYS,
    CONF_WINDOW_SLOTS,
    DEFAULT_DIAGNOSTIC_MODE,
    DEFAULT_INTRADAY_CORRECTION_CUTOFF,
    DEFAULT_INTRADAY_CORRECTION_MODE,
    DEFAULT_RAMP_SLOTS,
    DEFAULT_STRING_TEMPERATURE_COEFFICIENT,
    DEFAULT_WINDOW_SLOTS,
    DOMAIN,
    TEMPERATURE_SOURCE_NONE,
)
from .diagnostics.base import DiagnosticMode, DiagnosticResult
from .diagnostics.compare_regressions import CompareRegressionsMode
from .forecast_adjust import clamp_output, reverse_transformed_forecast
from .providers.base import Provider
from .providers.discovery import BaselineProvider
from .providers.temperature import TemperatureProvider, TemperatureTier
from .regression.base import FittedModel
from .yield_correction import uplift_ambient_to_cell

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .providers.normalize import BaselineShape

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


@dataclass(frozen=True)
class _TemperatureResolution:
    """A string's resolved temperature source (ADR-003b §1/§1a,
    `TASK-0014`). `tier="weather"` reads/forecasts natively (unchanged
    since the original, weather-only delivery). `tier="cell"`
    (a per-string override — a dedicated module/cell sensor) and
    `tier="ambient"` (the global default — one property-wide sensor)
    both instead need ADR-003c's learned per-slot model for a
    target-slot forecast, since neither has a native one; `cell` alone
    skips `yield_correction.uplift_ambient_to_cell` (ADR-003b §1a's
    table: a module/cell sensor already reads the thing the uplift
    formula exists to estimate). There is no separate config field
    distinguishing `cell` from `ambient` — scope (per-string override
    vs. global default) *is* the distinction, the same precedence
    `_resolve_temperature_entity` already applies to pick the entity
    id itself.
    """

    entity_id: str
    tier: Literal["weather", "cell", "ambient"]


@dataclass(frozen=True)
class RegressionSettings:
    """Global scalars `string_computation.py`'s `apply_training_
    corrections`/`fit_string_model` need (ADR-004 §5, second Amendment)
    — the same five values `_fit_string` already resolves for the
    default-method 288-slot sweep, exposed read-only so a
    `DiagnosticMode` can call those same pure functions itself without
    reaching into this module's private state. Generic, not
    diagnostics-specific — reusable by ADR-013's sketched future modes.
    """

    smoothing_radius: int
    neighbor_fitting_cutoff: float
    recency_decay_max: float
    clipping_threshold: float
    max_uplift_c: float


@dataclass(frozen=True)
class StringComputationConfig:
    """One configured string's remaining per-string inputs to
    `string_computation.py`'s functions (ADR-004 §5, second Amendment)
    — everything `_fit_string`/`_provider_already_corrects`/`_resolve_
    temperature_entity` already resolve internally, exposed read-only.
    `baseline_entity_id`/`temperature_entity_id`/`temperature_tier` are
    `None` when unconfigured/unresolved, exactly as `_fit_string`
    already treats them (a `None` `baseline_entity_id` means this
    string cannot be fit/diagnosed at all — no baseline forecast to
    compare against)."""

    baseline_entity_id: str | None
    actual_yield_entity_id: str
    temperature_entity_id: str | None
    temperature_tier: Literal["weather", "cell", "ambient"] | None
    converter_limit_w: float | None
    coefficient_per_c: float
    provider_already_corrects: bool
    rated_dc_capacity_wp: float | None


@dataclass(frozen=True)
class DiagnosedSlot:
    """Which slot is currently "the diagnosed slot" (ADR-004 §2/§2a) —
    resolved from the pin if one is set, else "the last complete slot"
    as of `now` (auto-tracking). `index` is the absolute slot index
    (`Cache.index_for` convention); `slot_of_day` is `index`'s 0-287
    time-of-day component (`get_pinned_slot_pool`'s own argument);
    `is_elapsed` is whether this slot's own actual/PV value can exist
    yet — `False` only for a manually-pinned slot still in the future
    (§2a's one exception to "selected actual"/accuracy being shown).
    """

    index: int
    slot_of_day: int
    is_elapsed: bool


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
        # ADR-006 §1/§2/§3, TASK-0013 — `.get(..., DEFAULT_*)` rather
        # than `data[...]` since these four fields postdate ADR-010's
        # original config-flow delivery (TASK-0009-patch-2's own
        # precedent for `recency_decay_max`, retained here even though
        # `config_flow.py` itself always writes all four with defaults
        # baked in — defends a hand-built `ConfigEntry.data` dict, e.g.
        # in a test fixture, that omits them).
        self._intraday_correction_mode: str = data.get(
            CONF_INTRADAY_CORRECTION_MODE, DEFAULT_INTRADAY_CORRECTION_MODE
        )
        self._intraday_correction_cutoff: float = data.get(
            CONF_INTRADAY_CORRECTION_CUTOFF, DEFAULT_INTRADAY_CORRECTION_CUTOFF
        )
        self._window_slots: int = data.get(CONF_WINDOW_SLOTS, DEFAULT_WINDOW_SLOTS)
        self._ramp_slots: int = data.get(CONF_RAMP_SLOTS, DEFAULT_RAMP_SLOTS)
        self._global_temperature_aware: bool = data.get(CONF_TEMPERATURE_AWARE, False)
        self._default_temperature_source: str | None = data.get(CONF_DEFAULT_TEMPERATURE_SOURCE)
        # ADR-003c §3/§7, TASK-0014: the dedicated global predictor
        # entity for the cell/ambient-tier learned model, and its own
        # independent regression-method choice — both already part of
        # config_flow.py's original settings-step schema (Required with
        # a config-flow-baked default for the method; Optional,
        # normalized empty-string -> `None`, for the entity), so
        # `data[...]`/`data.get(...)` follow the same convention as
        # every other original-delivery field above, not the
        # `.get(..., DEFAULT_*)` defensive style the ADR-006/§1's later
        # four fields use for a hand-built `ConfigEntry.data` fixture.
        self._weather_forecast_temperature_entity_id: str | None = data.get(
            CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY
        )
        self._temperature_regression_method: str = data[CONF_TEMPERATURE_REGRESSION_METHOD]
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
        if self._weather_forecast_temperature_entity_id is not None:
            # ADR-003c §3/§7, TASK-0014: registered once, globally, up
            # front — same pattern as the global baseline provider just
            # above — regardless of whether any string actually ends
            # up on the `cell`/`ambient` tier that consumes it as a
            # predictor (`_fit_temperature_string`); registering it
            # unconditionally here is what makes the generic
            # `forward()`-push loop (ADR-012 §4, `_register_provider_
            # listeners`) pick it up automatically below, with no new
            # coordinator listener code (this task's own Consumed
            # Interfaces note).
            self._ensure_temperature_provider(
                self._weather_forecast_temperature_entity_id, "weather"
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

            resolution = self._resolve_temperature_entity(string)
            if resolution is not None:
                provider_tier: TemperatureTier = (
                    "weather" if resolution.tier == "weather" else "sensor"
                )
                self._ensure_temperature_provider(resolution.entity_id, provider_tier)

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
        # ADR-003c §2, TASK-0014: one fitted per-slot temperature model
        # per `cell`/`ambient`-tier string (keyed by `string.index`,
        # same convention as `self._models`) — absent for a `weather`-
        # tier string (never needs one) or a string with no resolved
        # temperature source at all. Same in-memory-only scope decision
        # as `self._models` (see its own comment just above): a restart
        # already implies "no model fitted yet", which is exactly
        # ADR-002 §1's startup safety net regardless.
        self._temperature_models: dict[int, FittedModel] = {}
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

        # -- diagnostics (ADR-004, TASK-0015b) --
        # Which slot is pinned (§2a) — a full absolute slot index (date
        # + slot-of-day together), separate from `cache.pinned_
        # reference` (a bare `date`, ADR-007a §6's own narrower scope:
        # just the `get_pinned_slot_pool` window anchor). `None` while
        # auto-tracking. `pin_diagnostic_slot`/`clear_diagnostic_slot`
        # below are the only mutators, and keep both in sync.
        self._pinned_slot_index: int | None = None
        self._active_diagnostic_mode: str = DEFAULT_DIAGNOSTIC_MODE
        # Per-instance, not module-level (ADR-004 §5, 2026-09-01
        # Amendment: a `DiagnosticMode` now needs `self` at
        # construction). Keyed by each mode's own `key` class attribute
        # rather than a literal string, so this registry entry does not
        # duplicate a hard-coded mode name anywhere (this task's own
        # "no hard-coded 'compare_regressions' outside the registry
        # entry and `const.py`'s option list" acceptance criterion).
        # `"off"` is reserved and deliberately never a key here — the
        # absence of an active mode, not a subclass with a no-op body.
        self._diagnostic_modes: dict[str, DiagnosticMode] = {
            mode.key: mode for mode in (CompareRegressionsMode(self),)
        }
        # Cache for the active mode's `compute()` output (ADR-004 §5,
        # 2026-09-03 Amendment) — refreshed once per tick by
        # `_diagnostics_tick_sync` below (mirroring how `extra_fit()`'s
        # predictions are already cached via `cache.set_diagnostic_fit`),
        # with `diagnostic_result()` computing lazily on a cache miss
        # (mode just switched on, or a slot was just pinned/cleared, both
        # invalidate this immediately below). Every `ShadyDiagnosticsSensor`
        # (one per `sensor_id` from `diagnostic_sensor_ids()` — string,
        # sum, or any other id a mode declares) reads this same cached
        # value rather than calling `compute()` itself — one `compute()`
        # call serves every entity's every poll in between refreshes,
        # not one call per entity per poll.
        self._diagnostic_result_cache: DiagnosticResult | None = None

        self._register_schedule()
        self._register_provider_listeners()
        self._register_actual_yield_listeners()
        # Always registered (unlike pre-ADR-004 TASK-0013, which only
        # registered this when `intraday_correction_mode != "off"`):
        # ADR-004 §2/§4 reuses this exact same 5-minute trigger for
        # diagnostics, and the diagnostic-mode select (`select.py`) can
        # be switched on at any time after setup, independent of
        # `intraday_correction_mode` — so the trigger must always be
        # live for that to have any effect. The tick body itself
        # (`_intraday_tick_sync`/`_diagnostics_tick_sync`) stays a
        # genuine no-op whenever both intraday correction and every
        # diagnostic mode are off, preserving ADR-006 §1's "nothing
        # computed or retained" and ADR-004 §1's "zero cost when off"
        # guarantees at the per-tick-work level, not the
        # registration level.
        self._register_intraday_schedule()

    # -- construction helpers --------------------------------------------

    def _ensure_baseline_provider(
        self, entity_id: str, attribute: str | None, shape: BaselineShape | None
    ) -> None:
        if entity_id in self._entity_providers or attribute is None or shape is None:
            return
        self._entity_providers[entity_id] = BaselineProvider(self.hass, entity_id, attribute, shape)

    def _ensure_temperature_provider(self, entity_id: str, tier: TemperatureTier) -> None:
        if entity_id in self._entity_providers:
            return
        self._entity_providers[entity_id] = TemperatureProvider(self.hass, entity_id, tier)

    def _resolve_temperature_entity(self, string: _StringConfig) -> _TemperatureResolution | None:
        """ADR-003b §1/§1a's full three-tier resolution, `TASK-0014`
        (extends this module's original weather-only version — see the
        module docstring). Same override/default precedence as before:
        `weather`-domain resolves natively regardless of which of the
        two supplied it (unchanged); a `sensor.*`-domain resolution is
        `cell` when it came from this string's own
        `temperature_source_entity_id` override (a dedicated
        module/cell sensor) or `ambient` when it came from the global
        `default_temperature_source` (one property-wide reading) — the
        *scope* it came from is the only thing distinguishing the two,
        there is no separate tier-selecting config field (see
        `_TemperatureResolution`'s own docstring).

        `None` for an unset/disabled source (the `TEMPERATURE_SOURCE_
        NONE` sentinel), unchanged — and, ADR-003c §5's "no predictor,
        no correction" rule, also `None` for an otherwise-valid `cell`/
        `ambient` resolution when no global `weather_forecast_
        temperature_entity` predictor is configured: this is the one
        place that rule is enforced, so every caller below only ever
        sees "configured and forecastable" or `None`, never needing its
        own separate predictor-presence check.
        """
        entity_id = string.temperature_source_entity_id or self._default_temperature_source
        if entity_id is None or entity_id == TEMPERATURE_SOURCE_NONE:
            return None
        if _domain(entity_id) == "weather":
            return _TemperatureResolution(entity_id, "weather")
        if self._weather_forecast_temperature_entity_id is None:
            return None
        is_per_string_override = (
            string.temperature_source_entity_id is not None
            and string.temperature_source_entity_id != TEMPERATURE_SOURCE_NONE
        )
        tier: Literal["cell", "ambient"] = "cell" if is_per_string_override else "ambient"
        return _TemperatureResolution(entity_id, tier)

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
                temperature_model = self._fit_temperature_string(string, now)
                if temperature_model is not None:
                    self._temperature_models[string.index] = temperature_model
                # Recalibration completion is itself a recompute trigger
                # (ADR-002 §2, trigger 1) — reuses the exact same
                # `_recompute_string` path §2's second trigger (a
                # baseline-entity update) already runs, applying the
                # freshly-fitted model(s) — the shading model, and, for
                # a `cell`/`ambient`-tier string, the temperature model
                # too (TASK-0014) — to whatever baseline/predictor data
                # is currently cached (TASK-0010-patch-1).
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
        resolution = self._resolve_temperature_entity(string)
        if resolution is not None:
            sensor_ids.append(resolution.entity_id)

        pools = self.cache.get_regression_pools(sensor_ids, self._smoothing_radius, reference=now)
        fc_by_offset = _split_by_offset(
            pools[baseline_entity_id], self._smoothing_radius, self._window_days
        )
        pv_by_offset = _split_by_offset(
            pools[string.actual_yield_entity_id], self._smoothing_radius, self._window_days
        )

        temperature_by_offset: dict[int, NDArray[np.float64]] | None = None
        if resolution is not None:
            temperature_by_offset = _split_by_offset(
                pools[resolution.entity_id], self._smoothing_radius, self._window_days
            )

        corrected_pv_by_offset = string_computation.apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            temperature_by_offset,
            resolution.tier if resolution is not None else None,
            converter_limit_w=string.converter_limit_w,
            clipping_threshold=self._clipping_threshold,
            coefficient_per_c=string.temperature_coefficient_pct_per_c / 100.0,
            provider_already_corrects=self._provider_already_corrects(string),
            rated_dc_capacity_wp=string.rated_dc_capacity_wp,
            max_uplift_c=self._max_uplift_c,
        )

        return string_computation.fit_string_model(
            fc_by_offset,
            corrected_pv_by_offset,
            self._smoothing_radius,
            self._neighbor_fitting_cutoff,
            self._recency_decay_max,
            self._regression_method,
        )

    def _fit_temperature_string(self, string: _StringConfig, now: datetime) -> FittedModel | None:
        """ADR-003c §2, `TASK-0014`: this string's own per-slot
        temperature-forecast model — `None` when its resolved source is
        `weather` tier (forecasts natively already, ADR-003c §1) or
        unresolved at all (`_resolve_temperature_entity` already folds
        in ADR-003c §5's "no predictor configured" case, so no separate
        check is needed here).

        Predictor (`X`) is the dedicated global `weather_forecast_
        temperature_entity` (§3, a second `TemperatureProvider`
        instance, reused as-is — TASK-0004). Target (`Y`) is this
        tier's own already-resolved sensor (§2 — "already flows through
        `cache.py` unchanged": the exact same entity id `_fit_string`
        above already reads for the training-time uplift/derate
        correction, not a new series).

        Reuses `regression/`'s fitting mechanics only, not its
        PV-specific sample-validity assumptions (§2): `smoothing_
        radius=0` opts out of ADR-011's temporal smoothing/neighbor-
        regime exclusion entirely (a single, center-only offset never
        reaches that neighbor-only code path — no `build_pool` change
        needed for this part), and `apply_magnitude_weight=False`
        (`TASK-0005-patch-5`) opts out of ADR-001 §2's near-zero-`FC`
        downweighting, which does not make sense for a routinely-
        negative predictor. `recency_decay_max` reuses the exact same
        global value the shading fit above uses — this task's own
        documented decision (Delivered Artifacts): temperature does
        have a plausible recency-relevant regime-shift argument of its
        own (e.g. a stretch of colder/warmer days), so the existing
        global default is a reasonable starting behavior for both fits
        alike, and introducing a second, so-far-unrequested per-model
        setting was judged not worth the extra config-flow surface
        for a first cut. A follow-up ADR could split it later if
        empirical tuning wants that.
        """
        resolution = self._resolve_temperature_entity(string)
        if resolution is None or resolution.tier == "weather":
            return None
        assert self._weather_forecast_temperature_entity_id is not None

        predictor_id = self._weather_forecast_temperature_entity_id
        target_id = resolution.entity_id
        pools = self.cache.get_regression_pools([predictor_id, target_id], 0, reference=now)
        predictor_by_offset = _split_by_offset(pools[predictor_id], 0, self._window_days)
        target_by_offset = _split_by_offset(pools[target_id], 0, self._window_days)

        return string_computation.fit_string_model(
            predictor_by_offset,
            target_by_offset,
            # smoothing_radius=0 is inert — ADR-011's neighbor-only code
            # path never runs with a single, center-only offset block.
            # Passed only because `fit_string_model`'s signature requires
            # a value; any value would produce an identical pool here.
            0,
            self._neighbor_fitting_cutoff,
            self._recency_decay_max,
            self._temperature_regression_method,
            apply_magnitude_weight=False,
        )

    # -- forecast recompute (ADR-002 §2/§3) ------------------------------

    def forecast_sensor_id(self, string_index: int) -> str:
        """`ShadyForecastSensor`'s cache key (TASK-0011's Consumed
        Interface) — keyed by string index, not name (names are
        free-text, config_flow.py does not enforce uniqueness).
        """
        return f"{DOMAIN}_forecast_{self.entry.entry_id}_string_{string_index}"

    def raw_forecast_sensor_id(self, string_index: int) -> str:
        """ADR-006 §4's `values_raw` transparency series (TASK-0013) —
        a second, independent `cache.py` time-series key alongside
        `forecast_sensor_id`, holding the pre-intraday-correction
        reverse-transformed values. Populated only while intraday
        correction is active (`_apply_intraday_reset`); `sensor.py`
        reads it the same way it already reads `forecast_sensor_id`'s
        own `today`/`tomorrow` arrays — never pushed to, and therefore
        all-`None`, when intraday correction is off."""
        return f"{self.forecast_sensor_id(string_index)}_raw"

    def strings(self) -> list[tuple[int, str]]:
        """Public `(index, name)` pairs, one per configured string, in
        `CONF_STRINGS` order (TASK-0010-patch-2) — lets `sensor.py`
        (TASK-0011) and, later, `TASK-0015`'s per-string diagnostics
        entities enumerate strings without depending on the private
        `_StringConfig` list/type.
        """
        return [(string.index, string.name) for string in self._strings]

    # -- diagnostics (ADR-004, TASK-0015b) --------------------------------
    #
    # Public accessors a `DiagnosticMode` reaches through its stored
    # coordinator reference (ADR-004 §5, second Amendment's
    # encapsulation boundary: coordinator-owned data a mode needs gets
    # a public accessor here, rather than the mode reaching into
    # `_`-prefixed state directly) — plus the diagnosed-slot-pin
    # service methods `__init__.py`'s `shady.select_diagnostic_slot`
    # handler calls, and the active-mode select/lookup `select.py`/
    # `sensor.py` call.

    def now(self) -> datetime:
        """Public read of the injectable clock — lets a `DiagnosticMode`
        (and its tests) see the same `now` this coordinator itself
        uses. `compute()`/`extra_fit()` take no parameter (ADR-004 §5,
        second Amendment), so this is how they reach it instead of a
        `now`-parameter of their own."""
        return self._now()

    def diagnosed_slot(self, now: datetime | None = None) -> DiagnosedSlot:
        """Which slot is currently "the diagnosed slot" (ADR-004
        §2/§2a) — the pin if `pin_diagnostic_slot` has set one, else
        the last complete 5-minute slot as of `now` (defaults to
        `self.now()`)."""
        resolved_now = now if now is not None else self._now()
        if self._pinned_slot_index is not None:
            index = self._pinned_slot_index
        else:
            index = Cache.index_for(resolved_now) - 1
        slot_of_day = index % SLOTS_PER_DAY
        is_elapsed = Cache.timestamp_for(index + 1) <= resolved_now
        return DiagnosedSlot(index=index, slot_of_day=slot_of_day, is_elapsed=is_elapsed)

    def pin_diagnostic_slot(self, timestamp: datetime, now: datetime | None = None) -> bool:
        """ADR-004 §2a: pins the diagnosed slot to `timestamp`, rounded
        down to the nearest 5-minute boundary (`Cache.index_for`'s own
        floor-division convention) — the one diagnosed-slot state for
        this whole config entry, affecting every diagnostic sensor at
        once, not one pin per sensor. Rejected (returns `False`, no
        state change) if `timestamp` falls beyond ADR-002 §3's forecast
        horizon ("remainder of today + all of tomorrow"); accepted
        (returns `True`) and pinned otherwise, including a `timestamp`
        in the past — a past pin is always accepted (ADR-007a §6: it
        may trigger a real recorder fetch outside the live window, but
        is never rejected for being "too old").
        """
        resolved_now = now if now is not None else self._now()
        if timestamp >= _tomorrow_end(resolved_now):
            return False
        index = Cache.index_for(timestamp)
        self._pinned_slot_index = index
        self.cache.pin_reference(Cache.timestamp_for(index).date())
        # A pin changes what the diagnosed slot *is* (§2a), so a
        # `compute()` result cached against the previous diagnosed slot
        # is stale the instant this returns (ADR-004 §5, 2026-09-03
        # Amendment) — the next read recomputes rather than serving the
        # old slot's numbers until the next tick.
        self._diagnostic_result_cache = None
        return True

    def clear_diagnostic_slot(self) -> None:
        """Undo `pin_diagnostic_slot` — every diagnostic sensor goes
        back to auto-tracking the last complete slot."""
        self._pinned_slot_index = None
        self.cache.clear_reference()
        self._diagnostic_result_cache = None

    def active_diagnostic_mode(self) -> str:
        """The currently selected diagnostic mode key (`const.py`'s
        `DIAGNOSTIC_MODES`, default `"off"`) — `select.py`'s
        `ShadyDiagnosticModeSelect` reads this for its own
        `current_option`."""
        return self._active_diagnostic_mode

    def set_active_diagnostic_mode(self, mode: str) -> None:
        """Set the currently selected diagnostic mode key — `select.py`
        calls this from `async_select_option`. Any key not present in
        `self._diagnostic_modes` (i.e. `"off"`, or any future
        unregistered key) behaves as "off": `diagnostic_mode()` below
        returns `None` and `_diagnostics_tick_sync` does no extra
        fitting (ADR-004 §1)."""
        self._active_diagnostic_mode = mode
        # A different (or no) mode invalidates whatever `compute()`
        # result was cached for the previous mode (ADR-004 §5,
        # 2026-09-03 Amendment) — otherwise a switch could briefly serve
        # the old mode's stale output until the next tick.
        self._diagnostic_result_cache = None

    def diagnostic_mode(self) -> DiagnosticMode | None:
        """The currently active `DiagnosticMode` instance, or `None`
        while off/unset (ADR-004 §1) — mainly for `select.py`'s own
        `current_option` and `sensor.py`'s "disabled" vs "unavailable"
        distinction. `diagnostic_result()` below is what actually reads
        `compute()`'s output; nothing outside this module calls
        `.compute()` directly any more (ADR-004 §5, 2026-09-03
        Amendment)."""
        return self._diagnostic_modes.get(self._active_diagnostic_mode)

    def diagnostic_result(self) -> DiagnosticResult | None:
        """The active mode's cached `compute()` output, or `None` while
        off (ADR-004 §5, 2026-09-03 Amendment). `_diagnostics_tick_sync`
        below refreshes this once per tick, keyed off
        `compute_cadence()` the same way it already keys `extra_fit()`
        off `fit_cadence()`; a cache miss between ticks (mode just
        switched on, or a slot was just pinned/cleared — both clear the
        cache immediately above) computes once here and caches the
        result for whatever reads follow before the next tick. Every
        `ShadyDiagnosticsSensor` (`sensor.py`, one per `sensor_id` from
        `diagnostic_sensor_ids()` below) reads this, never
        `.compute()` directly — this is what makes one `compute()` call
        actually cover every entity's every poll, not just every string
        within a single call's own body (ADR-004 §5, fourth Amendment's
        original "one call per configured string" already held; this
        closes the "but one call per *poll*" gap on top).
        """
        mode = self.diagnostic_mode()
        if mode is None:
            return None
        if self._diagnostic_result_cache is None:
            self._diagnostic_result_cache = mode.compute()
        return self._diagnostic_result_cache

    def diagnostic_sensor_ids(self) -> list[tuple[str, str]]:
        """Every `(sensor_id, name)` pair any *registered* diagnostic
        mode declares (`DiagnosticMode.sensor_ids()`) — not just
        whichever mode is currently active (ADR-004 §5, fifth
        Amendment). `sensor.py`'s `async_setup_entry` calls this once,
        at platform-setup time, to create every diagnostic sensor entity
        up front; entities for a mode that isn't the active selection
        simply read as `"unavailable"` (`ShadyDiagnosticsSensor._result`
        finds no matching `sensor_id` in `diagnostic_result()`'s output)
        until/unless `select.py` switches to that mode — no dynamic
        add/remove of entities as the selection changes.

        Only one mode is registered today
        (`self._diagnostic_modes == {"compare_regressions": ...}`), so
        this is currently equivalent to that one mode's own
        `sensor_ids()`; the union generalizes for free once a second
        mode is registered. De-duplicates by `sensor_id`, first
        registration wins — two modes should never declare the same id
        in practice, but this keeps `async_setup_entry` from creating
        two entities with the same `unique_id` if one ever did.
        """
        by_id: dict[str, str] = {}
        for mode in self._diagnostic_modes.values():
            for sensor_id, name in mode.sensor_ids():
                by_id.setdefault(sensor_id, name)
        return list(by_id.items())

    def regression_settings(self) -> RegressionSettings:
        """The global scalars `string_computation.py`'s functions need
        (ADR-004 §5, second Amendment) — see `RegressionSettings`'s own
        docstring."""
        return RegressionSettings(
            smoothing_radius=self._smoothing_radius,
            neighbor_fitting_cutoff=self._neighbor_fitting_cutoff,
            recency_decay_max=self._recency_decay_max,
            clipping_threshold=self._clipping_threshold,
            max_uplift_c=self._max_uplift_c,
        )

    def string_computation_config(self, string_index: int) -> StringComputationConfig:
        """One configured string's remaining per-string inputs to
        `string_computation.py`'s functions (ADR-004 §5, second
        Amendment) — see `StringComputationConfig`'s own docstring."""
        string = self._strings[string_index]
        resolution = self._resolve_temperature_entity(string)
        return StringComputationConfig(
            baseline_entity_id=string.baseline_entity_id or self._global_baseline_entity_id,
            actual_yield_entity_id=string.actual_yield_entity_id,
            temperature_entity_id=resolution.entity_id if resolution is not None else None,
            temperature_tier=resolution.tier if resolution is not None else None,
            converter_limit_w=string.converter_limit_w,
            coefficient_per_c=string.temperature_coefficient_pct_per_c / 100.0,
            provider_already_corrects=self._provider_already_corrects(string),
            rated_dc_capacity_wp=string.rated_dc_capacity_wp,
        )

    def target_cell_temperature_for_slot(self, string_index: int, index: int) -> float | None:
        """ADR-003b/003c's `target_cell_temperature` for a single
        absolute slot `index`, for `CompareRegressionsMode`'s own
        `predict_string_forecast` call (ADR-004 §5: "the resolved
        temperature target via the coordinator's own provider access").
        Reuses `_predict_target_slot_temperature`'s existing per-tier
        resolution (`TASK-0014`) rather than a second implementation —
        builds that method's expected whole-day `fc_array` with just
        this one slot filled in (the rest `NaN`, which `uplift_ambient_
        to_cell` already treats as excluded), since a diagnostic call
        only ever needs one slot's worth, not a full day.

        `None` when this string has no resolved temperature source at
        all, or `_predict_target_slot_temperature` itself returns `None`
        (see that method's own docstring for its own `None` cases —
        missing `rated_dc_capacity_wp`, or no temperature model fitted
        yet)."""
        string = self._strings[string_index]
        resolution = self._resolve_temperature_entity(string)
        if resolution is None:
            return None

        day_start_index = (index // SLOTS_PER_DAY) * SLOTS_PER_DAY
        slot_of_day = index - day_start_index
        day_start = Cache.timestamp_for(day_start_index)

        fc_array = np.full(SLOTS_PER_DAY, np.nan, dtype=np.float64)
        baseline_entity_id = string.baseline_entity_id or self._global_baseline_entity_id
        if baseline_entity_id is not None:
            slot_start = Cache.timestamp_for(index)
            raw = self.cache.get_time_range(
                [baseline_entity_id], slot_start, slot_start, on_invalid="raw"
            )[baseline_entity_id]
            if raw and isinstance(raw[0], float):
                fc_array[slot_of_day] = raw[0]

        predicted = self._predict_target_slot_temperature(string, resolution, fc_array, day_start)
        if predicted is None:
            return None
        value = float(predicted[slot_of_day])
        return None if np.isnan(value) else value

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

        # ADR-006 §1a/§1b's `fc_value(t)`: the reverse-transformed,
        # still-unclamped prediction for every future slot across every
        # day in the horizon, assembled once (not per-day) so a single
        # intraday `effective_factor`/crossfade applies uniformly across
        # the whole horizon (ADR-006 §4), not separately per day.
        values_by_index: dict[int, float] = {}
        fc_by_index: dict[int, float] = {}
        for day, slot_values in by_day.items():
            day_values, day_fc = self._predict_day_basis(string, day, slot_values, now)
            values_by_index.update(day_values)
            fc_by_index.update(day_fc)

        if not values_by_index:
            return

        if self._intraday_correction_mode == "off":
            pushed = self._clamp_basis(values_by_index, fc_by_index, string.converter_limit_w)
        else:
            pushed = self._apply_intraday_reset(string, now, values_by_index, fc_by_index)

        if not pushed:
            return
        not_before_index = Cache.index_for(now) + 1
        self.cache.push(self.forecast_sensor_id(string.index), pushed, not_before_index)

    def _predict_day_basis(
        self, string: _StringConfig, day: date, slot_values: dict[int, float], now: datetime
    ) -> tuple[dict[int, float], dict[int, float]]:
        """Steps 1-2 of the ADR-006 §1b pipeline
        (`forecast_adjust.reverse_transformed_forecast`) for one day of
        one string — everything the pre-TASK-0013 `_predict_day` used
        to do up to (not including) the final clamp, split out so
        `_recompute_string` can insert its own intraday-correction step
        ahead of that clamp. Returns `(reverse_transformed_by_index,
        raw_fc_by_index)`, both restricted to slots at/after `now`
        (already-past slots are never recomputed, ADR-002 §3) — the raw
        `fc` values are carried alongside since `forecast_adjust
        .clamp_output`'s per-slot upper bound needs them, whether the
        clamp happens immediately (`_clamp_basis`) or later, after an
        intraday correction/crossfade (`_compute_intraday_output`).
        """
        model = self._models[string.index]
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        fc_array = np.full(SLOTS_PER_DAY, np.nan, dtype=np.float64)
        for slot, value in slot_values.items():
            fc_array[slot] = value

        provider_already_corrects = self._provider_already_corrects(string)
        coefficient_per_c = string.temperature_coefficient_pct_per_c / 100.0
        resolution = self._resolve_temperature_entity(string)

        target_cell_temperature: NDArray[np.float64] | None = None
        if resolution is not None and not provider_already_corrects:
            target_cell_temperature = self._predict_target_slot_temperature(
                string, resolution, fc_array, day_start
            )

        reverse_transformed, _confidence = reverse_transformed_forecast(
            model,
            fc_array,
            target_cell_temperature,
            coefficient_per_c,
            provider_already_corrects=provider_already_corrects,
        )

        now_index = Cache.index_for(now)
        values: dict[int, float] = {}
        fc_by_index: dict[int, float] = {}
        for slot in slot_values:
            index = Cache.index_for(day_start) + slot
            if index < now_index:
                continue
            value = float(reverse_transformed[slot])
            if not np.isnan(value):
                values[index] = value
                fc_by_index[index] = float(fc_array[slot])
        return values, fc_by_index

    def _predict_target_slot_temperature(
        self,
        string: _StringConfig,
        resolution: _TemperatureResolution,
        fc_array: NDArray[np.float64],
        day_start: datetime,
    ) -> NDArray[np.float64] | None:
        """ADR-003b §1b's `target_cell_temperature` for one day's 288
        slots, dispatched by tier (`TASK-0014`). `weather` reads the
        entity's own native forecast, unchanged since the original,
        weather-only delivery. `cell`/`ambient` instead feed the
        weather-forecast predictor's own forecast through this string's
        fitted per-slot temperature model (ADR-003c §2, `_fit_
        temperature_string`) to get `predicted_temp` — a forecast for a
        slot this string's own sensor has no live reading for yet.
        `cell` returns `predicted_temp` directly (ADR-003c §4: no
        uplift on top of an already-cell-equivalent estimate); `ambient`
        (like `weather`) passes it through the same `uplift_ambient_
        to_cell` transform a live ambient reading would, gated on
        `rated_dc_capacity_wp` being configured (ADR-003b §1a) — `cell`
        alone is never gated on that field, since it never evaluates
        the uplift formula at all.

        `None` when the correction cannot be produced this call: no
        `rated_dc_capacity_wp` for a tier that needs uplift, or (a
        cold-start edge case — every other call site already assumes
        `_fit_temperature_string` has run at least once, the same
        assumption `self._models[string.index]`'s own direct-index
        lookup above makes for the shading model) no temperature model
        fitted yet for this string.
        """
        if resolution.tier == "weather":
            if string.rated_dc_capacity_wp is None:
                return None
            provider = self._entity_providers.get(resolution.entity_id)
            assert isinstance(provider, TemperatureProvider)
            raw_temps = provider.fetch(day_start, day_start + timedelta(days=1))
            ambient = np.array(
                [v if isinstance(v, float) else np.nan for v in raw_temps], dtype=np.float64
            )
            uplifted = uplift_ambient_to_cell(
                ambient, fc_array, string.rated_dc_capacity_wp, self._max_uplift_c
            )
            return np.asarray(uplifted, dtype=np.float64)

        temperature_model = self._temperature_models.get(string.index)
        if temperature_model is None:
            return None
        assert self._weather_forecast_temperature_entity_id is not None
        predictor = self._entity_providers.get(self._weather_forecast_temperature_entity_id)
        assert isinstance(predictor, TemperatureProvider)
        raw_predictor = predictor.fetch(day_start, day_start + timedelta(days=1))
        predictor_values = np.array(
            [v if isinstance(v, float) else np.nan for v in raw_predictor], dtype=np.float64
        )
        predicted_temp, _model_confidence = temperature_model.predict_unclamped(predictor_values)

        if resolution.tier == "cell":
            return np.asarray(predicted_temp, dtype=np.float64)

        if string.rated_dc_capacity_wp is None:
            return None
        uplifted = uplift_ambient_to_cell(
            predicted_temp, fc_array, string.rated_dc_capacity_wp, self._max_uplift_c
        )
        return np.asarray(uplifted, dtype=np.float64)

    def _clamp_basis(
        self, values: dict[int, float], fc: dict[int, float], inverter_limit: float | None
    ) -> dict[int, float]:
        """ADR-006 §1b's one final output clamp, applied directly to a
        pre-clamp basis with no intraday correction in between (the
        `intraday_correction_mode == "off"` path) — equivalent to the
        pre-TASK-0013 `adjust_forecast` pipeline's own last step."""
        indices = sorted(values)
        if not indices:
            return {}
        values_arr = np.array([values[index] for index in indices], dtype=np.float64)
        fc_arr = np.array([fc[index] for index in indices], dtype=np.float64)
        clamped = clamp_output(values_arr, fc_arr, inverter_limit)
        return {index: float(clamped[position]) for position, index in enumerate(indices)}

    # -- intraday deviation correction (ADR-006, TASK-0013) --------------

    def _apply_intraday_reset(
        self,
        string: _StringConfig,
        now: datetime,
        values: dict[int, float],
        fc: dict[int, float],
    ) -> dict[int, float]:
        """A reset point (ADR-006 §1/§1b): a fresh basis for this
        string's future slots has just been computed, whether this is
        the string's first basis of the day or a later
        baseline-provider-triggered/recalibration-triggered recompute —
        ADR-006 §1b's own "not a special case requiring separate
        handling" note means both are handled by this one path.
        `active_slots_since_reset` restarts at `0` here, so
        `effective_factor` is exactly `1` (ADR-006 §1a): Ramping simply
        shows the plain new value, unadjusted, until the next 5-minute
        tick begins ramping it in; Blending freezes whatever basis
        existed *from earlier today* (if any) as the crossfade's old
        side — a basis left over from a previous calendar day is never
        frozen against, since that is exactly ADR-006 §1b's "first
        activation of the day" case, where Ramping and Blending must
        behave identically (nothing yet to blend against).
        """
        previous = self.cache.intraday_state(string.index)
        basis = IntradayBasis(values=values, fc=fc, inverter_limit=string.converter_limit_w)

        frozen_basis: IntradayBasis | None = None
        frozen_effective_factor: float | None = None
        if (
            self._intraday_correction_mode == "blending"
            and previous is not None
            and previous.reset_at.date() == now.date()
        ):
            frozen_basis = previous.basis
            frozen_effective_factor = previous.effective_factor

        state = IntradayState(
            reset_at=now,
            active_slots_since_reset=0,
            basis=basis,
            ratio_string=None,
            effective_factor=1.0,
            frozen_basis=frozen_basis,
            frozen_effective_factor=frozen_effective_factor,
        )
        self.cache.set_intraday_state(string.index, state)

        # ADR-006 §4's `values_raw` transparency series — the
        # pre-correction basis itself, pushed once per reset (not on
        # every 5-minute tick, since the basis doesn't change between
        # resets); a second, independent cache key alongside
        # `forecast_sensor_id` (`raw_forecast_sensor_id`).
        self.cache.push(self.raw_forecast_sensor_id(string.index), values, Cache.index_for(now) + 1)
        return self._compute_intraday_output(state)

    def _compute_intraday_output(self, state: IntradayState) -> dict[int, float]:
        """Ramping's single multiply, or Blending's two-sided crossfade
        (ADR-006 §1a/§1b/§5), followed by the one final output clamp
        (ADR-006 §1b's canonical ordering: correction, then clamp,
        exactly once, never per crossfade side) — shared by both the
        reset path (`_apply_intraday_reset`, `w == 0`) and the
        5-minute-tick path (`_advance_intraday_string`, `w` evolving).
        """
        indices = sorted(state.basis.values)
        if not indices:
            return {}
        new_values = np.array([state.basis.values[index] for index in indices], dtype=np.float64)
        new_prediction = new_values * state.effective_factor

        if state.frozen_basis is not None and state.frozen_effective_factor is not None:
            frozen = state.frozen_basis
            displayed = np.array(
                [
                    crossfade(
                        frozen.values[index] * state.frozen_effective_factor,
                        float(new_prediction[position]),
                        ramp_weight(state.active_slots_since_reset, self._ramp_slots),
                    )
                    if index in frozen.values
                    else float(new_prediction[position])
                    for position, index in enumerate(indices)
                ],
                dtype=np.float64,
            )
        else:
            displayed = new_prediction

        fc_arr = np.array([state.basis.fc[index] for index in indices], dtype=np.float64)
        clamped = clamp_output(displayed, fc_arr, state.basis.inverter_limit)
        return {index: float(clamped[position]) for position, index in enumerate(indices)}

    def _intraday_energy_window(
        self, string: _StringConfig, start: datetime, now: datetime
    ) -> tuple[float, float]:
        """ADR-006 §1a's `pv_energy_window`/`fc_energy_window`: the
        trailing-window energy sums for a string's own actual-yield
        entity and its own (already-corrected) `ShadyForecastSensor`,
        via `cache.py`'s ordinary `get_time_range` accessor (ADR-007a
        §5) — never a second, bespoke recorder-read path (ADR-000 §9).
        Must only be called off the event loop (module docstring): the
        actual-yield entity's read here is recorder-backed, exactly
        like `_fetch_actual_yield_statistics`.
        """
        if now <= start:
            return 0.0, 0.0
        forecast_sensor_id = self.forecast_sensor_id(string.index)
        sensor_ids = [string.actual_yield_entity_id, forecast_sensor_id]
        raw = self.cache.get_time_range(sensor_ids, start, now, on_invalid="raw")
        pv_values = [
            v if isinstance(v, float) else None for v in raw[string.actual_yield_entity_id]
        ]
        fc_values = [v if isinstance(v, float) else None for v in raw[forecast_sensor_id]]
        return day_energy_total_wh(pv_values), day_energy_total_wh(fc_values)

    def _advance_intraday_string(self, string: _StringConfig, now: datetime) -> None:
        """The 5-minute tick's per-string body (ADR-006 §1a) — re-derives
        `w`/`ratio_string`/`effective_factor` from the *current* trailing
        window and re-applies them against the *unchanged* basis
        established at the string's last reset (`_apply_intraday_reset`);
        never re-runs the regression model or the temperature
        reverse-transform (those only change at a genuine recompute).
        A string with no basis yet (mode just turned on and no recompute
        has run since, or no model fitted yet) is skipped — the next
        recompute will establish one.
        """
        state = self.cache.intraday_state(string.index)
        if state is None:
            return

        now_index = Cache.index_for(now)
        is_active = state.basis.fc.get(now_index, 0.0) != 0.0
        active_slots_since_reset = state.active_slots_since_reset + (1 if is_active else 0)

        window_start = max(state.reset_at, now - self._window_slots * SLOT_DURATION)
        pv_window, fc_window = self._intraday_energy_window(string, window_start, now)
        ratio_string = 1.0 if fc_window <= 0 else pv_window / fc_window
        w = ramp_weight(active_slots_since_reset, self._ramp_slots)
        effective_factor = intraday_correction_factor(
            pv_window, fc_window, w, self._intraday_correction_cutoff
        )

        new_state = replace(
            state,
            active_slots_since_reset=active_slots_since_reset,
            ratio_string=ratio_string,
            effective_factor=effective_factor,
        )
        if new_state.frozen_basis is not None:
            w_blend = ramp_weight(active_slots_since_reset, self._ramp_slots)
            if w_blend >= 1.0:
                # The crossfade has fully converged to the new side
                # (ADR-006 §1b) — clearing here is equivalent to
                # `_compute_intraday_output` computing `crossfade(...,
                # w_blend=1.0)` every tick from here on, just without
                # redoing that (harmless but pointless) work forever.
                new_state = replace(new_state, frozen_basis=None, frozen_effective_factor=None)

        self.cache.set_intraday_state(string.index, new_state)
        pushed = self._compute_intraday_output(new_state)
        if pushed:
            self.cache.push(self.forecast_sensor_id(string.index), pushed, now_index + 1)

    def _register_intraday_schedule(self) -> None:
        """ADR-006 §1a's independent 5-minute poll — now always
        registered (see `__init__`), not gated on
        `intraday_correction_mode`. ADR-004 §2/§4's diagnostic-slot
        advance/extra-fit reuses this exact same trigger rather than
        introducing a third, near-identical schedule."""
        self._unsub.append(
            async_track_time_interval(self.hass, self._handle_intraday_tick, timedelta(minutes=5))
        )

    @callback  # type: ignore[untyped-decorator]
    def _handle_intraday_tick(self, now: datetime) -> None:
        self.hass.async_create_task(self._async_intraday_tick(now))

    async def _async_intraday_tick(self, now: datetime) -> None:
        """Dispatched off the event loop (module docstring: recorder
        access via `cache.py`'s injected `fetch_fn` is blocking I/O) —
        `_intraday_energy_window` reads the actual-yield entity's
        recorder-backed history, mirroring `async_refit`'s own
        `hass.async_add_executor_job` pattern exactly. `cache.py`'s
        `get_pinned_slot_pool` (`_diagnostics_tick_sync`, ADR-004 §4)
        shares the same recorder-backed-fetch concern while
        auto-tracking a not-yet-cached slot, so it rides this same
        executor-thread dispatch rather than a second one."""
        await self.hass.async_add_executor_job(self._intraday_tick_sync, now)

    def _intraday_tick_sync(self, now: datetime) -> None:
        for string in self._strings:
            self._advance_intraday_string(string, now)
        self._diagnostics_tick_sync(now)

    def _diagnostics_tick_sync(self, now: datetime) -> None:
        """ADR-004 §2/§4: while a diagnostic mode is active, refreshes
        whichever of `extra_fit()`/`compute()` the mode declares a
        `"slot"` cadence for (ADR-004 §5, 2026-09-01 Amendment —
        "slot" meaning "every slot", i.e. this same 5-minute trigger,
        not the once-daily recalibration trigger §4's own original,
        pre-cadence-getter prose describes) — the two are gated
        independently since a future mode could need one but not the
        other, even though `CompareRegressionsMode` currently declares
        `"slot"` for both.

        `extra_fit()`'s result is cached into `cache.py`
        (`set_diagnostic_fit`), mirroring how a provider's `forward()`
        result is cached (ADR-012 §4) — build/cache stays in this
        module, the mode only computes. `compute()` is attempted
        *after*, not before, `extra_fit()` within this same method —
        this only actually matters on a tick where both cadences are
        `"slot"` (`CompareRegressionsMode`'s own case): there,
        `compute()` reads back the prediction this same tick's
        `extra_fit()` call just cached, rather than a stale value from
        one tick prior. A mode with a coarser `fit_cadence()` than
        `compute_cadence()` gets no such freshness guarantee from this
        ordering — `compute()` would just read back whatever
        `extra_fit()` most recently cached, from whichever earlier tick
        last satisfied `fit_cadence()`'s own condition, which is the
        correct behaviour for that mode, not a bug: `compute()` was
        never promised anything fresher than `fit_cadence()` provides.
        `compute()`'s own result is cached directly on
        `self._diagnostic_result_cache` (ADR-004 §5, 2026-09-03
        Amendment) for `diagnostic_result()` above to serve to every
        diagnostic entity's every poll until the next tick refreshes
        it — one `compute()` call per tick, not one per entity per
        poll.

        Re-fits/-computes unconditionally on every tick, even for an
        already-elapsed pinned slot whose output cannot actually have
        changed since the last tick — the same "always redo the
        per-string work every tick regardless of whether anything
        actually changed" trade-off `_advance_intraday_string` above
        already makes; the cost is the same order of magnitude (ADR-004
        §2a's own "cheap" characterization) and keeping this
        unconditional is simpler than tracking "did the diagnosed slot
        change" separately.

        A genuine no-op — zero extra cost (ADR-004 §1) — when no mode
        is active (`self._active_diagnostic_mode == "off"`, the
        default) or the active mode declares a coarser cadence for
        both.
        """
        mode = self._diagnostic_modes.get(self._active_diagnostic_mode)
        if mode is None:
            return
        if mode.fit_cadence() == "slot":
            result = mode.extra_fit()
            if result is not None:
                for sensor_id, predictions in result.by_sensor.items():
                    self.cache.set_diagnostic_fit(sensor_id, dict(predictions))
        if mode.compute_cadence() == "slot":
            self._diagnostic_result_cache = mode.compute()

    def intraday_attributes(self, string_index: int) -> dict[str, Any]:
        """ADR-006 §4's four scalar transparency attributes
        (`values_raw` is a time-series array; `sensor.py` reads it
        directly off `raw_forecast_sensor_id`, mirroring how it already
        reads `today`/`tomorrow` off `forecast_sensor_id`).
        `intraday_state` always mirrors the configured mode, even
        `"off"`, per ADR-006 §4's own naming note; the other three are
        `None`/`False` whenever there is no active per-string state yet
        (mode off, or no recompute has run since setup)."""
        state = self.cache.intraday_state(string_index)
        return {
            "intraday_ratio": state.ratio_string if state is not None else None,
            "intraday_state": self._intraday_correction_mode,
            "intraday_ramp_weight": (
                ramp_weight(state.active_slots_since_reset, self._ramp_slots)
                if state is not None
                else None
            ),
            "intraday_blend_active": bool(
                state is not None
                and state.frozen_basis is not None
                and self._intraday_correction_mode == "blending"
            ),
        }

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
