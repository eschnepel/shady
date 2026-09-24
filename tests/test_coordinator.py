"""Tests for `coordinator.py` (ADR-002, ADR-012 §4).

`coordinator.py` is HA-facing (real, non-`TYPE_CHECKING` imports of
`homeassistant.core`, `homeassistant.helpers.event`, and
`homeassistant.components.recorder.statistics`) — outside ADR-000 §6's
zero-mocking pure tier, same as `config_flow.py` (TASK-0009). This file
extends that task's hand-written `homeassistant` stub convention
(`tasks/INDEX.md`'s refinement log) with the additional surface this
module touches: `async_track_time_change`/`async_track_state_change_event`
and `statistics_during_period` — all real (non-`Mock`) stand-ins, not
mocks, registered directly in `sys.modules` before file-path-loading the
module under test.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

from tests.support import _load, _run
from tests.support_ha import ConfigEntryState, FakeHomeAssistant, _install_ha_stub

_install_ha_stub()

# `coordinator.py` does `from .regression import kernel, linear, wls2,
# wls3` (package-level, not `from .regression.kernel import ...`) —
# resolving that requires the top-level `shady` package itself to be a
# real (if empty) entry in `sys.modules`, not just its submodules
# individually; `providers.*`/`regression.*`'s own direct
# `from .x.y import z`-style imports never needed this, since Python's
# import machinery short-circuits on an exact dotted-name cache hit
# before ever falling back to package-attribute + recursive-import
# resolution — a fallback only `from .regression import <submodule>`
# actually triggers.
_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []  # mark as a package, matching a real `shady/`
sys.modules["shady"] = _shady_pkg

_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_load("regression/base.py", "shady.regression.base")
_const_mod = _load("const.py", "shady.const")
_cache_mod = _load("cache.py", "shady.cache")
_load("providers/discovery.py", "shady.providers.discovery")
_load("providers/temperature.py", "shady.providers.temperature")
_load("regression/__init__.py", "shady.regression")
_load("regression/linear.py", "shady.regression.linear")
_load("regression/kernel.py", "shady.regression.kernel")
_load("regression/wls2.py", "shady.regression.wls2")
_load("regression/wls3.py", "shady.regression.wls3")
_load("yield_correction.py", "shady.yield_correction")
_load("forecast_adjust.py", "shady.forecast_adjust")
_load("aggregation.py", "shady.aggregation")
_load("string_computation.py", "shady.string_computation")
_load("diagnostics/__init__.py", "shady.diagnostics")
_diagnostics_base_mod = _load("diagnostics/base.py", "shady.diagnostics.base")
_compare_regressions_mod = _load(
    "diagnostics/compare_regressions.py", "shady.diagnostics.compare_regressions"
)
_load("coordinator_like.py", "shady.coordinator_like")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")

# `_DIAGNOSTIC_LOG` (both modules) is `False` in production -- opt-in,
# hand-flipped debug logging (`coordinator.py`'s `_fit_string`/
# `_fetch_fn`/`_fetch_provider_history_statistics`/
# `_diagnostics_tick_sync`; `compare_regressions.py`'s `extra_fit`/
# `compute_sensor`/`_selected_value`), never exercised by this suite
# while it stays `False`. Flipped to `True` here, for the whole test
# run, so every one of those bodies actually executes at least once
# (most already run *inside* an existing, otherwise-unrelated test,
# via whatever ordinary path already calls `_fit_string`/`extra_fit`/
# etc. -- no dedicated test needed for that alone) rather than sitting
# untested until someone flips the flag on a live deployment to debug
# something *else* already broken, the worst possible moment to
# discover a second, unrelated bug in the debug logging itself (a
# `KeyError`/`IndexError`/wrong `%`-arg count would raise from *inside*
# `_LOGGER.warning`'s own call, not be silently swallowed). Both
# modules were already file-path-loaded above for this file's own
# tests; `test_diagnostics_compare_regressions.py` and every other
# file that does `from tests import test_coordinator as tc` reuses
# these same `sys.modules` entries rather than loading its own, so
# setting this once here covers the whole suite.
_coordinator_mod._DIAGNOSTIC_LOG = True  # type: ignore[attr-defined]
_compare_regressions_mod._DIAGNOSTIC_LOG = True  # type: ignore[attr-defined]

# TYPE_CHECKING-only static import mirroring the runtime file-path load
# above (ADR-000 §6, matching `test_diagnostics_base.py`'s own
# convention) — gives mypy a real type for `DiagnosticMode` so
# `_CountingDiagnosticMode` below type-checks normally, without
# reintroducing the package import (and therefore `homeassistant.*`)
# the file-path load avoids.
if TYPE_CHECKING:
    from shady.diagnostics.base import DiagnosticMode as DiagnosticMode  # noqa: PLC0414
    from shady.providers.base import Provider as Provider  # noqa: PLC0414
    from shady.providers.discovery import BaselineProvider as BaselineProvider  # noqa: PLC0414
else:
    DiagnosticMode = _diagnostics_base_mod.DiagnosticMode
    Provider = sys.modules["shady.providers.base"].Provider
    BaselineProvider = sys.modules["shady.providers.discovery"].BaselineProvider

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = _cache_mod.Cache
IntradayBasis = _cache_mod.IntradayBasis
IntradayState = _cache_mod.IntradayState
CONF_STRINGS = _const_mod.CONF_STRINGS

# -- shared test fixture -----------------------------------------------

_NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 6, 14, tzinfo=UTC)
_BASELINE_ENTITY = "sensor.forecast_solar_estimate"
_ACTUAL_YIELD_ENTITY = "sensor.string_a_yield"


def _synthetic_wh_period(start: datetime, end: datetime) -> dict[str, float]:
    """A simple, deterministic daytime-shaped series (06:00-18:00 sunny,
    else zero) covering `[start, end)` at 5-minute resolution — enough
    for a non-degenerate fit without needing real-world data."""
    out: dict[str, float] = {}
    step = timedelta(minutes=5)
    current = start
    while current < end:
        out[current.isoformat()] = 500.0 if 6 <= current.hour < 18 else 0.0
        current += step
    return out


def _seed_actual_yield_statistics(hass: FakeHomeAssistant, start: datetime, end: datetime) -> None:
    by_start: dict[datetime, float] = {}
    step = timedelta(minutes=5)
    current = start
    while current < end:
        by_start[current] = 400.0 if 6 <= current.hour < 18 else 0.0
        current += step
    hass.statistics[_ACTUAL_YIELD_ENTITY] = by_start


def _make_entry(**overrides: Any) -> Any:
    data: dict[str, Any] = {
        "baseline_entity_id": _BASELINE_ENTITY,
        "baseline_attribute": "wh_period",
        "baseline_shape": "sensor_dict",
        "temperature_aware": False,
        "window_days": 1,
        "regression_method": "wls2",
        "smoothing_radius": 0,
        "neighbor_fitting_cutoff": 0.25,
        "recency_decay_max": 0.5,
        "clipping_threshold": 0.98,
        "default_temperature_source": None,
        "max_uplift_c": 25,
        "weather_forecast_temperature_entity": None,
        "temperature_regression_method": "wls2",
        "intraday_correction_mode": "off",
        "intraday_correction_cutoff": 0.10,
        "window_slots": 24,
        "ramp_slots": 12,
        CONF_STRINGS: {
            _ACTUAL_YIELD_ENTITY: {
                "name": "Dach Süd",
                "baseline_entity_id": None,
                "baseline_attribute": None,
                "baseline_shape": None,
                "temperature_aware": False,
                "converter_limit_w": None,
                "temperature_source_entity_id": None,
                "temperature_coefficient_pct_per_c": -0.4,
                "rated_dc_capacity_wp": None,
            }
        },
    }
    data.update(overrides)
    config_entries_mod = sys.modules["homeassistant.config_entries"]
    return config_entries_mod.ConfigEntry("test_entry", data)


def _make_coordinator(entry: Any | None = None) -> tuple[Any, FakeHomeAssistant]:
    hass = FakeHomeAssistant()
    hass.states.set(
        _BASELINE_ENTITY,
        {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
    )
    hass.states.set(_ACTUAL_YIELD_ENTITY, {})
    _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
    coordinator = ShadyCoordinator(hass, entry or _make_entry())
    coordinator._now = lambda: _NOW  # deterministic clock for state-change-triggered paths
    return coordinator, hass


def _make_temperature_aware_coordinator() -> tuple[Any, FakeHomeAssistant]:
    """A single string resolving a `weather`-tier temperature source
    (ADR-003b §1a) — the simplest tier to fixture: unlike `cell`/
    `ambient`, `weather` needs no separate `weather_forecast_
    temperature_entity` predictor (`_resolve_temperature_entity`
    resolves it from the string's own domain check alone), and
    `TemperatureProvider.fetch()` falls back to the entity's current
    `temperature` attribute for every historical slot with no matching
    `forecast` entry (`providers/temperature.py`), so one static state
    is enough for a full `window_days` history. `rated_dc_capacity_wp`
    is set because the weather tier's uplift branch
    (`_predict_target_slot_temperature`) gates to `None` without it.

    Used both for `_fit_string`'s own temperature-aware branch
    (`coordinator.py`) and, via `tests/test_diagnostics_compare_
    regressions.py`'s reuse of this module, `CompareRegressionsMode.
    extra_fit()`'s temperature-aware `_gather_pool`/`_predict_all_
    methods` branches — both previously only exercised formula-by-
    formula in isolation (`test_coordinator_temperature_forecast.py`),
    never through a real end-to-end fit/predict call."""
    entry = _make_entry(
        strings={
            _ACTUAL_YIELD_ENTITY: {
                "name": "Dach Süd",
                "baseline_entity_id": None,
                "baseline_attribute": None,
                "baseline_shape": None,
                "temperature_aware": False,
                "converter_limit_w": None,
                "temperature_source_entity_id": "weather.home",
                "temperature_coefficient_pct_per_c": -0.4,
                "rated_dc_capacity_wp": 5000.0,
            }
        },
    )
    coordinator, hass = _make_coordinator(entry)
    hass.states.set("weather.home", {"temperature": 15.0, "forecast": []})
    return coordinator, hass


def _set_state(
    hass: FakeHomeAssistant,
    entity_id: str,
    attributes: dict[str, Any] | None = None,
    state: float | str | None = None,
) -> None:
    """`FakeStates.set` inside a running event loop, draining whatever
    fire-and-forget task the state-change listener schedules
    afterward — necessary for any `_ACTUAL_YIELD_ENTITY`-family
    `entity_id`, since `_handle_actual_yield_update` (ADR-005 §5) is a
    synchronous `@callback` that calls `hass.async_create_task`, which
    needs a running loop to attach to; a bare `hass.states.set(...)`
    outside of `_run`/`asyncio.run` has none."""

    async def _drive() -> None:
        hass.states.set(entity_id, attributes, state)
        await hass.drain()

    _run(_drive())


class TestCacheAttributeIsReadOnly:
    """Given `ShadyCoordinator.cache` (ADR-000 §3-Amendment, TASK-0023),
    when code attempts `coordinator.cache = ...`, then it raises
    `AttributeError` — a getter with no matching setter, so a wrong
    implementation anywhere that reaches a coordinator instance cannot
    silently replace the cache it holds. Reading through the property
    and calling methods on the returned object are both unaffected."""

    def test_assignment_raises_attribute_error(self) -> None:
        coordinator, _hass = _make_coordinator()
        with pytest.raises(AttributeError):
            coordinator.cache = object()

    def test_reading_and_calling_methods_on_it_still_works(self) -> None:
        coordinator, _hass = _make_coordinator()
        # a plain read (property getter) and a real method call on the
        # object it returns, proving the property only blocks
        # *reassignment*, not read access or the cache's own API.
        assert coordinator.cache.get_model("shading", 0) is None


class TestRecencyDecayMaxWiring:
    """`TASK-0010-patch-3`: `recency_decay_max` (ADR-001 §4a) reaches
    `ShadyCoordinator` from `entry.data` exactly like its sibling
    `neighbor_fitting_cutoff`, and flows through to `build_pool` at
    `_fit_string`'s refit call site — `TestRecencyWeight`
    (`tests/test_regression.py`) already covers the weighting math
    itself, so this only needs to prove the wiring."""

    def test_resolved_onto_the_coordinator_from_entry_data(self) -> None:
        coordinator, _hass = _make_coordinator(_make_entry(recency_decay_max=0.2))
        assert coordinator._recency_decay_max == 0.2

    def test_default_entry_value_flows_through_unmodified(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator._recency_decay_max == 0.5


class TestRefitSharedCodePath:
    """Given a manual button press and the scheduled midnight trigger,
    When either fires, Then both call the exact same refit code path,
    using only recorder data up to and including yesterday."""

    def test_button_and_midnight_produce_the_same_fit(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        button_model = coordinator.cache.get_model("shading", 0)
        assert button_model is not None

        coordinator2, hass2 = _make_coordinator()

        async def _drive_midnight() -> None:
            coordinator2._handle_midnight(_NOW)
            await hass2.drain()

        _run(_drive_midnight())
        midnight_model = coordinator2.cache.get_model("shading", 0)
        assert midnight_model is not None

        assert (button_model.coefficients == midnight_model.coefficients).all()
        assert coordinator._last_fit_at == _NOW
        assert coordinator2._last_fit_at == _NOW

    def test_refit_only_uses_data_through_yesterday(self) -> None:
        coordinator, hass = _make_coordinator()
        # Pollute "today"'s statistics with an extreme value; if refit
        # accidentally included today's partial data the fit would be
        # visibly different from a run where today is left untouched.
        hass.statistics[_ACTUAL_YIELD_ENTITY][_NOW] = 999_999.0
        _run(coordinator.async_refit(_NOW))

        coordinator_clean, _hass_clean = _make_coordinator()
        _run(coordinator_clean.async_refit(_NOW))

        model = coordinator.cache.get_model("shading", 0)
        model_clean = coordinator_clean.cache.get_model("shading", 0)
        assert model is not None
        assert model_clean is not None
        assert (model.coefficients == model_clean.coefficients).all()


class TestStartupSafetyNet:
    """Given a config entry with no model fitted yet (or a last fit >24h
    old), When the coordinator's startup-fit entry point is called, Then
    a fit runs immediately, in addition to the daily schedule."""

    def test_async_startup_fits_when_no_model_yet(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator.cache.get_model("shading", 0) is None
        _run(coordinator.async_startup(_NOW))
        assert coordinator.cache.get_model("shading", 0) is not None
        assert coordinator._last_fit_at is not None

    def test_async_startup_skips_when_recently_fitted(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        first_fit_at = coordinator._last_fit_at
        _run(coordinator.async_startup(_NOW + timedelta(hours=1)))
        assert coordinator._last_fit_at == first_fit_at  # unchanged: no re-fit triggered

    def test_async_startup_backfills_todays_elapsed_slots(self) -> None:
        """`async_startup` (ADR-002 §1a) also closes the startup gap
        `_recompute_string` deliberately leaves — a fresh coordinator's
        in-memory forecast cache has nothing at all for today's already-
        elapsed slots until this runs."""
        coordinator, _hass = _make_coordinator()
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        today_start_index = Cache.index_for(today_start)
        now_index = Cache.index_for(_NOW)

        _run(coordinator.async_startup(_NOW))

        pushed = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        elapsed = {index: value for index, value in pushed.items() if index < now_index}
        assert elapsed  # today's elapsed slots were actually backfilled
        assert all(index >= today_start_index for index in elapsed)


class TestMissingRequiredEntities:
    """Given a config entry's per-string actual-yield or resolved
    baseline entity does not currently exist, When
    `missing_required_entities()` is called, Then it returns those
    entity IDs (and only those — never optional correction-tier
    entities)."""

    def test_reports_missing_actual_yield_and_baseline(self) -> None:
        hass = FakeHomeAssistant()
        # Neither entity set at all: both required entities missing.
        coordinator = ShadyCoordinator(hass, _make_entry())
        missing = coordinator.missing_required_entities()
        assert set(missing) == {_BASELINE_ENTITY, _ACTUAL_YIELD_ENTITY}

    def test_none_missing_once_both_exist(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator.missing_required_entities() == []

    def test_optional_temperature_entity_never_required(self) -> None:
        entry = _make_entry(default_temperature_source="weather.home")
        hass = FakeHomeAssistant()
        hass.states.set(_BASELINE_ENTITY, {"wh_period": {}})
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        # weather.home deliberately never set — must not appear below.
        coordinator = ShadyCoordinator(hass, entry)
        assert coordinator.missing_required_entities() == []


class TestRefitTriggersRecompute:
    """Given a string's model is freshly (re)fit, When fitting succeeds,
    Then the exact same recompute path runs immediately for that string
    against whatever baseline data is currently cached (ADR-002 §2,
    trigger 1) — TASK-0010-patch-1."""

    def test_refit_pushes_a_forecast_without_any_baseline_update(self) -> None:
        coordinator, _hass = _make_coordinator()
        sensor_id = coordinator.forecast_sensor_id(0)
        assert coordinator.cache.validated_range(sensor_id) is None  # nothing pushed yet

        _run(coordinator.async_refit(_NOW))

        pushed = hass_pushed_values(coordinator, sensor_id)
        assert pushed  # recompute ran as part of refit itself, no separate trigger fired

    def test_no_recompute_attempted_when_fitting_fails(self) -> None:
        # A string with no baseline provider configured at all: `_fit_string`
        # returns None, so there must be nothing to recompute either.
        entry = _make_entry(baseline_entity_id=None, baseline_attribute=None, baseline_shape=None)
        strings = entry.data[CONF_STRINGS]
        entry.data[CONF_STRINGS] = strings
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW

        _run(coordinator.async_refit(_NOW))

        assert coordinator.cache.get_model("shading", 0) is None
        # `validated_range` alone is no longer a reliable "nothing
        # happened" check on its own: TASK-0012's `fc_sum()` (called
        # from `_accumulate_fc_energy` at the end of every refit) also
        # queries this same sensor_id via `get_time_range` — the same
        # "validate before read" `fetch_fn` dispatch a never-pushed
        # sensor's *any* query goes through, exactly like
        # `ShadyForecastSensor.native_value` already does (ADR-007a
        # §4) — not something recompute-specific. The invariant this
        # test actually cares about — no recompute ever *pushed* a
        # value — is `hass_pushed_values` returning empty.
        assert hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0)) == {}


class TestStringLevelBaselineOverrideRegistration:
    """Given a string configures its own `baseline_entity_id` (ADR-002
    §2's per-string override, distinct from — here, in place of
    entirely — the global default), When the coordinator is
    constructed, Then `_ensure_baseline_provider` actually registers a
    working `BaselineProvider` for it and a model can be fit through
    it end to end. Previously untested: every other coordinator test in
    this file relies on the *global* `baseline_entity_id` fallback
    (`string.has_baseline_override` was always `False`)."""

    def test_shading_model_fits_from_a_per_string_override_entity(self) -> None:
        override_entity = "sensor.string_a_own_baseline"
        entry = _make_entry(
            baseline_entity_id=None,  # no global fallback configured at all
            strings={
                _ACTUAL_YIELD_ENTITY: {
                    "name": "Dach Süd",
                    "baseline_entity_id": override_entity,
                    "baseline_attribute": "wh_period",
                    "baseline_shape": "sensor_dict",
                    "temperature_aware": False,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                }
            },
        )
        hass = FakeHomeAssistant()
        hass.states.set(
            override_entity,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW

        _run(coordinator.async_refit(_NOW))

        assert coordinator.cache.get_model("shading", 0) is not None


class TestFitStringWithResolvedTemperatureSource:
    """Given a string resolves a temperature source (weather tier —
    ADR-003b §1a's simplest case, no separate predictor entity needed),
    When `_fit_string` runs (via `async_refit`), Then the temperature-
    aware branch — gathering a `temperature_by_offset` pool and passing
    it into `apply_training_corrections` — actually executes end to
    end. Previously only exercised formula-by-formula in isolation
    (`test_coordinator_temperature_forecast.py`'s own docstring says as
    much: "deliberately does NOT re-test regression/'s fitting math...
    only the coordinator-level wiring" — but that file's one true
    end-to-end test, `TestNoPredictorSkipsBothSidesEndToEnd`, is
    specifically the *unconfigured* skip path, not this one)."""

    def test_shading_model_still_fits_with_a_resolved_temperature_source(self) -> None:
        coordinator, _hass = _make_temperature_aware_coordinator()

        _run(coordinator.async_refit(_NOW))

        assert coordinator.cache.get_model("shading", 0) is not None


class TestRefitInvalidatesStaleModelOnSubsequentFailure:
    """Given a string has a previously-valid fitted model from a prior
    successful refit, When a later refit's fit attempt for that same
    string fails, Then the stale model is actually cleared, not
    silently kept (AUDIT-0017/TASK-0021: `_refit_sync`'s unconditional
    `self.cache.invalidate_models()` call must be exercised end to end,
    not just the storage-layer contract in isolation —
    `tests/test_cache_core.py::TestFittedModelCacheInvalidation` already
    covers that half)."""

    def test_model_is_cleared_not_left_stale_after_a_failed_refit(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        assert coordinator.cache.get_model("shading", 0) is not None  # valid model exists

        # Simulate the string's baseline provider becoming unavailable
        # before the next refit: `_fit_string` (coordinator.py:761)
        # returns `None` whenever the resolved `baseline_entity_id` has
        # no registered provider, which is exactly the "persistently
        # failing fit" scenario TASK-0021 called out.
        del coordinator._entity_providers[_BASELINE_ENTITY]

        _run(coordinator.async_refit(_NOW))

        # Not "still None because never set" (that's the other,
        # already-covered scenario in TestRefitTriggersRecompute) —
        # here a model *was* valid and must now be gone, proving
        # `invalidate_models()` actually ran and nothing re-set it.
        assert coordinator.cache.get_model("shading", 0) is None


class TestRecomputeOnBaselineUpdate:
    """Given a baseline-provider update fires mid-day, When it fires,
    Then a forecast recompute happens immediately with no debounce, but
    no recalibration is triggered by this alone."""

    def test_baseline_update_triggers_recompute_not_recalibration(self) -> None:
        coordinator, hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        fit_count_before = coordinator._last_fit_at

        async def _drive_update() -> None:
            hass.states.set(
                _BASELINE_ENTITY,
                {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
            )
            await hass.drain()

        _run(_drive_update())

        assert coordinator._last_fit_at == fit_count_before  # no recalibration
        pushed = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert pushed  # a recompute actually produced+pushed something


def hass_pushed_values(coordinator: Any, sensor_id: str) -> dict[int, float]:
    cache = coordinator.cache
    validated = cache.validated_range(sensor_id)
    assert validated is not None
    result: dict[int, float] = {}
    lst = cache._values.get(sensor_id, [])
    offset = cache._list_offset.get(sensor_id, 0)
    for position, value in enumerate(lst):
        if isinstance(value, float):
            result[offset + position] = value
    return result


class TestRecomputeHorizon:
    """Given a recompute, When it runs, Then it produces adjusted values
    only for the remainder of today plus tomorrow, and never recomputes
    already-past slots."""

    def test_only_remainder_of_today_and_tomorrow_pushed(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        coordinator._recompute_string(coordinator._strings[0], _NOW)

        sensor_id = coordinator.forecast_sensor_id(0)
        pushed = hass_pushed_values(coordinator, sensor_id)
        now_index = Cache.index_for(_NOW)
        horizon_end = _NOW.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=2)

        assert pushed  # something was produced
        assert all(index >= now_index + 1 for index in pushed)  # never before "now"
        assert all(index < Cache.index_for(horizon_end) for index in pushed)


class TestRecomputeForwardFillsSparseRawSamples:
    """A raw baseline series that only reports on a coarser grid than
    `FC`'s own 5-minute slots (e.g. an hourly weather/PV-forecast
    provider, ADR-009 §1a) must have each sample held forward across
    every slot up to the next sample's own timestamp — not just the one
    slot its timestamp happens to land on, which used to leave every
    other slot in that hour permanently `None`/unpushed."""

    def test_every_remaining_slot_in_the_hour_is_filled_not_just_one(self) -> None:
        coordinator, hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        hour_start = _NOW.replace(minute=0, second=0, microsecond=0)

        class _HourlyProvider(BaselineProvider):
            def forward(self, now: datetime) -> list[tuple[datetime, float]]:
                return [(hour_start, 500.0), (hour_start + timedelta(hours=1), 600.0)]

        coordinator._entity_providers[_BASELINE_ENTITY] = _HourlyProvider(
            hass, _BASELINE_ENTITY, "wh_period", "sensor_dict"
        )

        coordinator._recompute_string(coordinator._strings[0], _NOW)

        pushed = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        hour_start_index = Cache.index_for(hour_start)
        # Offset 0 (the current slot, `_NOW` itself) is frozen by
        # `not_before_index`; every one of the 11 remaining slots this
        # hour must have been filled from the same 500.0 raw sample.
        for offset in range(1, 12):
            assert hour_start_index + offset in pushed

    def test_zero_raw_forecast_fills_its_whole_span_with_zero(self) -> None:
        coordinator, hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        hour_start = _NOW.replace(minute=0, second=0, microsecond=0)

        class _ZeroThenPositiveProvider(BaselineProvider):
            def forward(self, now: datetime) -> list[tuple[datetime, float]]:
                return [(hour_start, 0.0), (hour_start + timedelta(hours=1), 500.0)]

        coordinator._entity_providers[_BASELINE_ENTITY] = _ZeroThenPositiveProvider(
            hass, _BASELINE_ENTITY, "wh_period", "sensor_dict"
        )

        coordinator._recompute_string(coordinator._strings[0], _NOW)

        pushed = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        hour_start_index = Cache.index_for(hour_start)
        for offset in range(1, 12):
            assert pushed[hour_start_index + offset] == 0.0


class TestPushSemantics:
    """Given a `ShadyForecastSensor`-shaped output value is computed for
    a slot, When it is first computed, Then it is immediately pushed
    into `cache.py` with `to_index=None` semantics."""

    def test_pushed_value_has_to_index_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        coordinator._recompute_string(coordinator._strings[0], _NOW)
        sensor_id = coordinator.forecast_sensor_id(0)
        validated = coordinator.cache.validated_range(sensor_id)
        assert validated is not None
        assert validated[1] is None  # to_index=None: actively pushed


class TestGenericProviderPushLoop:
    """Given both the baseline provider and the temperature provider
    override `forward()`, When a config entry sets up, Then exactly one
    generic coordinator listener is registered per such provider
    instance — no provider-specific listener code exists in
    `coordinator.py`."""

    def test_one_listener_per_forward_overriding_provider(self) -> None:
        entry = _make_entry(default_temperature_source="weather.home")
        strings = entry.data[CONF_STRINGS]
        entry.data[CONF_STRINGS] = strings
        hass = FakeHomeAssistant()
        hass.states.set(_BASELINE_ENTITY, {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW)})
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set("weather.home", {"temperature": 20.0, "forecast": []})
        coordinator = ShadyCoordinator(hass, entry)

        assert _BASELINE_ENTITY in hass.states._listeners
        assert "weather.home" in hass.states._listeners
        assert len(hass.states._listeners[_BASELINE_ENTITY]) == 1
        assert len(hass.states._listeners["weather.home"]) == 1
        assert coordinator is not None  # keep reference alive for clarity


class TestGenericPushNotBeforeIndex:
    """Given a provider's `forward()` returns a series, When the listener
    fires, Then `push(sensor_id, dict[index, value])` is called with
    `not_before_index` set to "the next upcoming slot after now"."""

    def test_push_freezes_slots_before_next_upcoming(self) -> None:
        coordinator, _hass = _make_coordinator()
        # Pre-seed the raw baseline cache entry for the current slot to
        # a sentinel, so we can confirm it is left untouched by the push
        # (frozen, per `not_before_index`).
        current_index = Cache.index_for(_NOW)
        coordinator.cache.push(_BASELINE_ENTITY, {current_index: -1.0}, current_index)

        coordinator._push_provider_series(_BASELINE_ENTITY, _NOW)

        raw_now = coordinator.cache.get_time_range(
            [_BASELINE_ENTITY], _NOW, _NOW + timedelta(minutes=1), on_invalid="raw"
        )[_BASELINE_ENTITY][0]
        assert raw_now == -1.0  # current slot frozen, not overwritten

        next_slot_start = Cache.timestamp_for(current_index + 1)
        next_slot_end = next_slot_start + timedelta(minutes=1)
        raw_next = coordinator.cache.get_time_range(
            [_BASELINE_ENTITY], next_slot_start, next_slot_end, on_invalid="raw"
        )[_BASELINE_ENTITY][0]
        assert raw_next == 500.0


class TestGenericPushForwardFillsCoarserGrid:
    """`_push_provider_series` (ADR-012 §4 Amendment, `TASK-0037-patch-3`,
    live bug report) must forward-fill a coarser-than-5-minute `forward()`
    series -- `forecast_solar`/weather-shaped sources report hourly
    (ADR-009 §1a) -- across every 5-minute slot in each sample's span,
    not just the exact slot each raw sample happens to land on, mirroring
    `_recompute_string`'s own `_forward_fill_by_day` handling of the
    identical concern. Fails against the pre-fix `_push_provider_series`
    (a plain `{Cache.index_for(ts): value for ts, value in series}`
    dict), which would leave every slot below `None` — the reported
    symptom, root-caused directly: the diagnosed "selected" series only
    ever appeared for a diagnosed slot matching minute 0.
    """

    def test_hourly_forward_series_fills_every_5_minute_slot(self) -> None:
        coordinator, _hass = _make_coordinator()
        provider = coordinator._entity_providers[_BASELINE_ENTITY]
        hourly_now = _NOW  # 2026-06-15 10:00 -- already hour-aligned itself
        hourly_series = [(hourly_now + timedelta(hours=h), 500.0) for h in range(1, 3)]
        provider.forward = lambda now: hourly_series

        coordinator._push_provider_series(_BASELINE_ENTITY, hourly_now)

        # A quarter and half past the hour, and just before the next
        # hour mark -- never one of `hourly_series`'s own timestamps,
        # only ever reachable via the forward-fill.
        for minute_offset in (65, 90, 115):
            ts = hourly_now + timedelta(minutes=minute_offset)
            index = Cache.index_for(ts)
            assert coordinator.cache._read(_BASELINE_ENTITY, index) == 500.0
        # The second hour's own sample still lands exactly where expected.
        second_hour_index = Cache.index_for(hourly_now + timedelta(hours=2))
        assert coordinator.cache._read(_BASELINE_ENTITY, second_hour_index) == 500.0

    def test_forward_fill_stops_at_the_next_raw_sample_not_the_value(self) -> None:
        """A change in value between two raw samples is still a step
        function, not interpolated — the forward-filled span ends the
        instant the next sample's own timestamp starts."""
        coordinator, _hass = _make_coordinator()
        provider = coordinator._entity_providers[_BASELINE_ENTITY]
        hourly_now = _NOW
        hourly_series = [
            (hourly_now + timedelta(hours=1), 500.0),
            (hourly_now + timedelta(hours=2), 0.0),
        ]
        provider.forward = lambda now: hourly_series

        coordinator._push_provider_series(_BASELINE_ENTITY, hourly_now)

        just_before_second = hourly_now + timedelta(hours=2) - timedelta(minutes=5)
        just_before_second_sample = Cache.index_for(just_before_second)
        assert coordinator.cache._read(_BASELINE_ENTITY, just_before_second_sample) == 500.0
        at_second_sample = Cache.index_for(hourly_now + timedelta(hours=2))
        assert coordinator.cache._read(_BASELINE_ENTITY, at_second_sample) == 0.0


class TestStringEnumeration:
    """Given a config entry with N configured strings, When
    `coordinator.strings()` is called, Then it returns exactly N
    `(index, name)` pairs in `CONF_STRINGS` order, with no private
    `_StringConfig` exposed (TASK-0010-patch-2)."""

    def test_single_string_default_fixture(self) -> None:
        coordinator, _hass = _make_coordinator()

        result = coordinator.strings()

        assert result == [(0, "Dach Süd")]
        assert all(isinstance(pair, tuple) and isinstance(pair[1], str) for pair in result)

    def test_multiple_strings_preserve_config_order(self) -> None:
        second_yield_entity = "sensor.string_b_yield"
        entry = _make_entry(
            **{
                CONF_STRINGS: {
                    _ACTUAL_YIELD_ENTITY: {
                        "name": "Dach Süd",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    },
                    second_yield_entity: {
                        "name": "Dach Nord",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    },
                }
            }
        )
        hass = FakeHomeAssistant()
        hass.states.set(
            _BASELINE_ENTITY,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set(second_yield_entity, {})
        _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
        coordinator = ShadyCoordinator(hass, entry)

        assert coordinator.strings() == [(0, "Dach Süd"), (1, "Dach Nord")]


# -- ADR-005 / TASK-0012: aggregate sensors + energy-integral totals -------

_SECOND_ACTUAL_YIELD_ENTITY = "sensor.string_b_yield"


def _push_forecast(coordinator: Any, string_index: int, timestamp: datetime, value: float) -> None:
    """Test-only helper: writes one slot directly into a
    `ShadyForecastSensor` cache key, bypassing the fit pipeline —
    `Cache.push`'s real signature takes an index->value dict and a
    `not_before_index` floor, not a single `(timestamp, value)` pair."""
    index = Cache.index_for(timestamp)
    coordinator.cache.push(coordinator.forecast_sensor_id(string_index), {index: value}, index)


def _make_two_string_entry(**overrides: Any) -> Any:
    return _make_entry(
        **{
            CONF_STRINGS: {
                _ACTUAL_YIELD_ENTITY: {
                    "name": "Dach Süd",
                    "baseline_entity_id": None,
                    "baseline_attribute": None,
                    "baseline_shape": None,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                },
                _SECOND_ACTUAL_YIELD_ENTITY: {
                    "name": "Dach Nord",
                    "baseline_entity_id": None,
                    "baseline_attribute": None,
                    "baseline_shape": None,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                },
            },
            **overrides,
        }
    )


def _make_two_string_coordinator() -> tuple[Any, FakeHomeAssistant]:
    entry = _make_two_string_entry()
    hass = FakeHomeAssistant()
    hass.states.set(
        _BASELINE_ENTITY,
        {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
    )
    hass.states.set(_ACTUAL_YIELD_ENTITY, {})
    hass.states.set(_SECOND_ACTUAL_YIELD_ENTITY, {})
    _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
    coordinator = ShadyCoordinator(hass, entry)
    coordinator._now = lambda: _NOW
    return coordinator, hass


class TestPvSum:
    """ADR-005 §1: `pv_sum()` sums the current actual-yield state
    across every configured string, reading straight from live HA
    state — independent of the fit/recompute cycle."""

    def test_single_string_reads_its_actual_yield_state(self) -> None:
        coordinator, hass = _make_coordinator()
        _set_state(hass, _ACTUAL_YIELD_ENTITY, state=321.5)
        assert coordinator.pv_sum() == 321.5

    def test_sums_across_multiple_strings(self) -> None:
        coordinator, hass = _make_two_string_coordinator()
        _set_state(hass, _ACTUAL_YIELD_ENTITY, state=100.0)
        _set_state(hass, _SECOND_ACTUAL_YIELD_ENTITY, state=50.0)
        assert coordinator.pv_sum() == 150.0

    def test_non_numeric_state_excluded_not_zeroed(self) -> None:
        coordinator, hass = _make_two_string_coordinator()
        _set_state(hass, _ACTUAL_YIELD_ENTITY, state=100.0)
        _set_state(hass, _SECOND_ACTUAL_YIELD_ENTITY, state="unavailable")
        assert coordinator.pv_sum() == 100.0

    def test_all_missing_returns_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        # default fixture state is "unknown" (non-numeric)
        assert coordinator.pv_sum() is None


class TestFcSum:
    """ADR-005 §2: `fc_sum(now)` sums the current-slot corrected
    forecast across every configured string, reading from `cache.py`."""

    def test_single_string_current_slot(self) -> None:
        coordinator, _hass = _make_coordinator()
        _push_forecast(coordinator, 0, _NOW, 200.0)
        assert coordinator.fc_sum(_NOW) == 200.0

    def test_sums_across_multiple_strings(self) -> None:
        coordinator, _hass = _make_two_string_coordinator()
        _push_forecast(coordinator, 0, _NOW, 200.0)
        _push_forecast(coordinator, 1, _NOW, 300.0)
        assert coordinator.fc_sum(_NOW) == 500.0

    def test_unpushed_slot_returns_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator.fc_sum(_NOW) is None

    def test_defaults_now_to_coordinator_clock(self) -> None:
        coordinator, _hass = _make_coordinator()
        _push_forecast(coordinator, 0, _NOW, 77.0)
        assert coordinator.fc_sum() == 77.0


class TestFcDayArray:
    """ADR-005 §3: `fc_day_array(now)` returns today's 288
    `(timestamp, cross-string-summed-value)` pairs via one
    `get_time_range(group_by="slot")` call."""

    def test_array_shape_and_timestamps(self) -> None:
        coordinator, _hass = _make_coordinator()
        timestamps, values = coordinator.fc_day_array(_NOW)
        assert len(timestamps) == 288
        assert len(values) == 288
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        assert timestamps[0] == today_start
        assert timestamps[1] == today_start + timedelta(minutes=5)
        assert timestamps[-1] == today_start + timedelta(hours=23, minutes=55)

    def test_sums_pushed_slots_across_strings(self) -> None:
        coordinator, _hass = _make_two_string_coordinator()
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        slot = today_start + timedelta(hours=8)
        _push_forecast(coordinator, 0, slot, 100.0)
        _push_forecast(coordinator, 1, slot, 50.0)

        _timestamps, values = coordinator.fc_day_array(_NOW)

        slot_index = int((slot - today_start) / timedelta(minutes=5))
        assert values[slot_index] == 150.0

    def test_unpushed_slots_are_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        _timestamps, values = coordinator.fc_day_array(_NOW)
        assert all(value is None for value in values)


class TestFcDayEnergyTotalAndRemaining:
    """ADR-005 §3/§4: `fc_day_energy_total`/`fc_remaining_energy` are
    pure post-processing of `fc_day_array`'s own output."""

    def test_day_energy_total_matches_aggregation_module(self) -> None:
        coordinator, _hass = _make_coordinator()
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        _push_forecast(coordinator, 0, today_start, 600.0)

        expected = 600.0 * 5 / 60  # one slot at 600W for 5 minutes, in Wh
        assert coordinator.fc_day_energy_total(_NOW) == expected

    def test_remaining_energy_excludes_past_slots(self) -> None:
        coordinator, _hass = _make_coordinator()
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        past_slot = today_start + timedelta(hours=1)  # before _NOW (10:00)
        future_slot = today_start + timedelta(hours=12)  # after _NOW
        _push_forecast(coordinator, 0, past_slot, 1000.0)
        _push_forecast(coordinator, 0, future_slot, 600.0)

        total = coordinator.fc_day_energy_total(_NOW)
        remaining = coordinator.fc_remaining_energy(_NOW)

        assert remaining < total
        assert remaining == 600.0 * 5 / 60


class TestEnergyAccumulation:
    """ADR-005 §5/§6: `_accumulate_energy` advances `cache.py`'s
    running totals via `aggregation.trapezoidal_energy_increment`, and
    `_maybe_reset_energy_totals` is the idempotent day-boundary guard
    both the midnight schedule and restore rely on."""

    def test_first_sample_contributes_zero(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._accumulate_energy("pv", _NOW, 600.0)
        assert coordinator.cache.energy_total("pv") == 0.0
        assert coordinator.cache.last_energy_sample("pv") == (_NOW, 600.0)

    def test_second_sample_adds_trapezoidal_increment(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._accumulate_energy("pv", _NOW, 600.0)
        later = _NOW + timedelta(minutes=5)
        coordinator._accumulate_energy("pv", later, 600.0)
        # constant 600W for 5 minutes = 50 Wh
        assert coordinator.cache.energy_total("pv") == 50.0

    def test_pv_and_fc_totals_are_independent(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._accumulate_energy("pv", _NOW, 600.0)
        coordinator._accumulate_energy("pv", _NOW + timedelta(minutes=5), 600.0)
        coordinator._accumulate_energy("fc", _NOW, 100.0)
        assert coordinator.cache.energy_total("pv") == 50.0
        assert coordinator.cache.energy_total("fc") == 0.0

    def test_maybe_reset_is_idempotent_within_a_day(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator._maybe_reset_energy_totals(_NOW) is True
        assert coordinator._maybe_reset_energy_totals(_NOW) is False
        assert coordinator._maybe_reset_energy_totals(_NOW + timedelta(hours=1)) is False

    def test_maybe_reset_fires_again_on_a_new_day(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._accumulate_energy("pv", _NOW, 600.0)
        coordinator._accumulate_energy("pv", _NOW + timedelta(minutes=5), 600.0)
        assert coordinator.cache.energy_total("pv") == 50.0

        next_day = _NOW + timedelta(days=1)
        coordinator._accumulate_energy("pv", next_day, 600.0)
        # reset cleared the total and the last-sample, so this sample
        # is a fresh "first sample" — contributes zero, not a bridge
        # across the reset boundary.
        assert coordinator.cache.energy_total("pv") == 0.0
        assert coordinator.cache.last_reset_date() == next_day.date()

    def test_accumulate_fc_energy_skips_when_fc_sum_is_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._accumulate_fc_energy(_NOW)
        assert coordinator.cache.energy_total("fc") == 0.0
        assert coordinator.cache.last_energy_sample("fc") is None

    def test_accumulate_fc_energy_uses_full_cross_string_total(self) -> None:
        coordinator, _hass = _make_two_string_coordinator()
        _push_forecast(coordinator, 0, _NOW, 200.0)
        _push_forecast(coordinator, 1, _NOW, 300.0)
        coordinator._accumulate_fc_energy(_NOW)
        assert coordinator.cache.last_energy_sample("fc") == (_NOW, 500.0)


class TestActualYieldTriggeredAccumulation:
    """ADR-005 §5: a real actual-yield entity state change (via the new
    `_register_actual_yield_listeners`) triggers PV energy accumulation
    and schedules a persist — a real end-to-end path, not a direct
    `_accumulate_energy` call."""

    def test_state_change_accumulates_and_schedules_persist(self) -> None:
        coordinator, hass = _make_coordinator()
        _set_state(hass, _ACTUAL_YIELD_ENTITY, state=600.0)

        assert coordinator.cache.last_energy_sample("pv") == (_NOW, 600.0)
        assert hass.store_data  # persisted


class TestEnergyRestorePersistence:
    """ADR-005 §5/§6, ADR-007 §1: `async_restore_energy_state` loads
    from `Store`, applies the startup idempotency check, and only then
    registers the midnight-reset schedule; `_async_persist_energy_state`
    is its write-side counterpart. A simulated restart is two
    coordinators sharing one `FakeHomeAssistant` (and so one
    `hass.store_data`)."""

    def test_restore_with_nothing_stored_zeroes_and_sets_today(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_restore_energy_state())
        assert coordinator.cache.energy_total("pv") == 0.0
        assert coordinator.cache.last_reset_date() == _NOW.date()

    def test_persist_then_restore_across_a_simulated_restart(self) -> None:
        coordinator, hass = _make_coordinator()
        coordinator._accumulate_energy("pv", _NOW, 600.0)
        coordinator._accumulate_energy("pv", _NOW + timedelta(minutes=5), 600.0)
        _run(coordinator._async_persist_energy_state())

        entry = _make_entry()
        coordinator2 = ShadyCoordinator(hass, entry)
        coordinator2._now = lambda: _NOW + timedelta(minutes=5)
        _run(coordinator2.async_restore_energy_state())

        assert coordinator2.cache.energy_total("pv") == 50.0
        # deliberately NOT restored — next accumulation starts fresh
        assert coordinator2.cache.last_energy_sample("pv") is None

    def test_restore_resets_if_stored_reset_date_is_in_the_past(self) -> None:
        coordinator, hass = _make_coordinator()
        coordinator._accumulate_energy("pv", _NOW, 600.0)
        coordinator._accumulate_energy("pv", _NOW + timedelta(minutes=5), 600.0)
        _run(coordinator._async_persist_energy_state())

        entry = _make_entry()
        coordinator2 = ShadyCoordinator(hass, entry)
        next_day = _NOW + timedelta(days=1)
        coordinator2._now = lambda: next_day
        _run(coordinator2.async_restore_energy_state())

        assert coordinator2.cache.energy_total("pv") == 0.0
        assert coordinator2.cache.last_reset_date() == next_day.date()

    def test_restore_not_called_from_init(self) -> None:
        coordinator, hass = _make_coordinator()
        # nothing loaded/registered until explicitly called
        assert coordinator.cache.last_reset_date() is None
        assert not hass.store_data


class TestRecomputeTriggersFcAccumulation:
    """ADR-005 §2/§6: both recompute paths — recalibration
    (`_refit_sync`/`async_refit`) and baseline-update recompute
    (`_async_recompute`) — accumulate one FC-energy increment after
    recomputing, and schedule a persist afterward."""

    def test_async_refit_accumulates_fc_energy_and_persists(self) -> None:
        coordinator, hass = _make_coordinator()
        # Simulate an earlier cycle having already frozen the current
        # slot (`Cache.push`'s own `not_before_index` freezing means a
        # brand-new coordinator's very first refit never has *this*
        # exact slot written yet — see `TestRefitSharedCodePath`'s
        # "current slot frozen" test for the same property from the
        # opposite direction).
        _push_forecast(coordinator, 0, _NOW, 111.0)
        _run(coordinator.async_refit(_NOW))
        assert coordinator.cache.last_energy_sample("fc") == (_NOW, 111.0)
        # `async_refit` awaits the persist directly (it's already a
        # coroutine on the event loop) — no separate drain needed.
        assert hass.store_data

    def test_async_recompute_accumulates_fc_energy_and_persists(self) -> None:
        coordinator, hass = _make_coordinator()
        _push_forecast(coordinator, 0, _NOW, 222.0)

        async def _drive() -> None:
            await coordinator._async_recompute(coordinator._strings, _NOW)
            await hass.drain()

        _run(_drive())
        assert coordinator.cache.last_energy_sample("fc") == (_NOW, 222.0)
        assert hass.store_data

    def test_first_ever_refit_with_nothing_pre_frozen_skips_accumulation(self) -> None:
        """Documents the edge case above explicitly: a truly fresh
        coordinator's first-ever refit accumulates nothing (`fc_sum`
        of the still-unwritten current slot is `None`) — not a bug,
        just the natural consequence of `_predict_day`'s own
        `not_before_index` freezing; the very next trigger (once this
        slot has since been frozen by this run's own push) will find
        something to accumulate."""
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        assert coordinator.cache.last_energy_sample("fc") is None
        assert coordinator.cache.energy_total("fc") == 0.0


# -- diagnostic_result()/diagnostic_sensor_ids() (ADR-004 §5, fifth Amendment, 2026-09-03) --


class _CountingDiagnosticMode(DiagnosticMode):
    """A hand-written `DiagnosticMode` that records every `compute()`/
    `extra_fit()` call (count and order) instead of doing real work —
    substituted directly into `coordinator._diagnostic_modes` (the same
    "reach into private state for a white-box test" convention this
    file already uses for `coordinator._now` elsewhere) so
    `diagnostic_result()`'s caching behaviour can be verified by call
    count, independent of `CompareRegressionsMode`'s own real
    computation."""

    key = "compare_regressions"

    def __init__(
        self, coordinator: Any, fit_cadence: str = "slot", compute_cadence: str = "slot"
    ) -> None:
        super().__init__(coordinator)
        self.compute_calls = 0
        self.extra_fit_calls = 0
        self.call_order: list[str] = []
        self._fit_cadence = fit_cadence
        self._compute_cadence = compute_cadence

    def fit_cadence(self) -> Any:
        return self._fit_cadence

    def compute_cadence(self) -> Any:
        return self._compute_cadence

    def sensor_ids(self) -> list[tuple[str, str]]:
        return [("0", "Dummy")]

    def compute(self) -> Any:
        self.compute_calls += 1
        self.call_order.append("compute")
        return _diagnostics_base_mod.DiagnosticResult(
            sensors=[
                _diagnostics_base_mod.DiagnosticSensorResult(
                    sensor_id="0", state="ok", attributes={"n": self.compute_calls}
                )
            ]
        )

    def extra_fit(self) -> Any:
        self.extra_fit_calls += 1
        self.call_order.append("extra_fit")
        return None


# -- diagnosed_slot()/pin_diagnostic_slot()/clear_diagnostic_slot() (ADR-004 §2/§2a) --


class TestDiagnosedSlotAutoTracking:
    """Given no pin is set, `diagnosed_slot()` (ADR-004 §2) defaults to
    the last **complete** 5-minute slot as of `now` — not the next
    upcoming one."""

    def test_defaults_to_the_last_complete_slot(self) -> None:
        coordinator, _hass = _make_coordinator()
        now = datetime(2026, 6, 15, 10, 7, tzinfo=UTC)

        diagnosed = coordinator.diagnosed_slot(now)

        # 10:07 -> the slot starting 10:05 is still in progress; the
        # last *complete* slot is the one starting 10:00.
        assert diagnosed.index == Cache.index_for(now) - 1
        assert diagnosed.is_elapsed is True

    def test_uses_coordinators_own_now_when_not_given(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW

        diagnosed = coordinator.diagnosed_slot()

        assert diagnosed.index == Cache.index_for(_NOW) - 1


class TestPinDiagnosticSlot:
    """`pin_diagnostic_slot()` (ADR-004 §2a): rounds down to the
    nearest 5-minute boundary, accepts any timestamp within ADR-002
    §3's horizon (including one in the past), and rejects (no state
    change) anything at or beyond the end of tomorrow."""

    def test_rounds_down_to_the_five_minute_boundary(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW
        off_boundary = datetime(2026, 6, 15, 10, 7, 30, tzinfo=UTC)

        ok = coordinator.pin_diagnostic_slot(off_boundary)

        assert ok
        diagnosed = coordinator.diagnosed_slot()
        assert diagnosed.index == Cache.index_for(datetime(2026, 6, 15, 10, 5, tzinfo=UTC))

    def test_a_past_pin_is_always_accepted(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW

        ok = coordinator.pin_diagnostic_slot(_NOW - timedelta(days=30))

        assert ok
        diagnosed = coordinator.diagnosed_slot()
        assert diagnosed.index == Cache.index_for(_NOW - timedelta(days=30))

    def test_rejects_a_timestamp_beyond_the_horizon(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW
        # Horizon is "remainder of today + all of tomorrow"; the day
        # after tomorrow is out of range.
        beyond_horizon = datetime(2026, 6, 17, 0, 0, tzinfo=UTC)

        ok = coordinator.pin_diagnostic_slot(beyond_horizon)

        assert ok is False
        # No state change: still auto-tracking.
        diagnosed = coordinator.diagnosed_slot()
        assert diagnosed.index == Cache.index_for(_NOW) - 1

    def test_accepts_the_last_instant_of_the_horizon(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW
        last_valid = datetime(2026, 6, 16, 23, 55, tzinfo=UTC)

        ok = coordinator.pin_diagnostic_slot(last_valid)

        assert ok

    def test_clear_reverts_to_auto_tracking(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW
        coordinator.pin_diagnostic_slot(_NOW - timedelta(days=1))

        coordinator.clear_diagnostic_slot()

        diagnosed = coordinator.diagnosed_slot()
        assert diagnosed.index == Cache.index_for(_NOW) - 1

    def test_is_elapsed_false_for_a_future_pin(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW

        ok = coordinator.pin_diagnostic_slot(_NOW + timedelta(hours=3))

        assert ok
        assert coordinator.diagnosed_slot().is_elapsed is False

    def test_is_elapsed_true_for_a_past_pin(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW

        ok = coordinator.pin_diagnostic_slot(_NOW - timedelta(hours=3))

        assert ok
        assert coordinator.diagnosed_slot().is_elapsed is True


class TestDiagnosticResultCaching:
    """`coordinator.diagnostic_result()` (ADR-004 §5, fifth Amendment,
    2026-09-03): caches the active mode's `compute()` output rather
    than calling it on every read, refreshed once per tick."""

    def test_off_by_default_returns_none_without_calling_compute(self) -> None:
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode

        assert coordinator.diagnostic_result() is None
        assert fake_mode.compute_calls == 0

    def test_multiple_reads_share_one_compute_call(self) -> None:
        """Given the mode is active and no tick has refreshed the cache
        yet, When `diagnostic_result()` is read many times, Then
        `compute()` is only actually called once — the first read
        computes and caches; every read after that shares the cached
        result (this is the exact bug flagged during review: every
        `ShadyDiagnosticsSensor` used to call `compute()` itself, once
        per poll)."""
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")

        for _ in range(5):
            result = coordinator.diagnostic_result()
            assert result is not None
            assert result.sensors[0].sensor_id == "0"

        assert fake_mode.compute_calls == 1

    def test_tick_refreshes_the_cache(self) -> None:
        """Given a cached result already exists, When
        `_diagnostics_tick_sync` runs again (`compute_cadence() ==
        "slot"`), Then `compute()` is called again — the cache is
        refreshed once per tick, not frozen forever after the first
        read."""
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")

        coordinator.diagnostic_result()
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 1

        coordinator._diagnostics_tick_sync(_NOW)
        assert fake_mode.compute_calls == 2

        coordinator.diagnostic_result()
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 2  # still just the one from the tick

    def test_tick_skips_compute_when_compute_cadence_is_coarser(self) -> None:
        """Given a mode that declares `fit_cadence() == "slot"` but
        `compute_cadence() != "slot"`, When `_diagnostics_tick_sync`
        runs, Then `extra_fit()` still runs every tick but `compute()`
        is never called from the tick — the two cadences are gated
        independently."""
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(
            coordinator, fit_cadence="slot", compute_cadence="daily"
        )
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")

        coordinator._diagnostics_tick_sync(_NOW)
        assert fake_mode.extra_fit_calls == 1
        assert fake_mode.compute_calls == 0

    def test_extra_fit_runs_before_compute_within_one_tick(self) -> None:
        """Given both cadences are `"slot"`, When
        `_diagnostics_tick_sync` runs, Then `extra_fit()` is attempted
        before `compute()` within that same call — so a mode whose
        `compute()` reads back `extra_fit()`'s own cached predictions
        sees this tick's, not last tick's (only guaranteed when both
        cadences fire the same tick, per the corrected docstring)."""
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")

        coordinator._diagnostics_tick_sync(_NOW)
        assert fake_mode.call_order == ["extra_fit", "compute"]

    def test_switching_mode_invalidates_the_cache(self) -> None:
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 1

        coordinator.set_active_diagnostic_mode("off")
        assert coordinator.diagnostic_result() is None

        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 2

    def test_pinning_a_slot_invalidates_the_cache(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 1

        coordinator.pin_diagnostic_slot(_NOW - timedelta(days=1))
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 2

    def test_clearing_a_pinned_slot_invalidates_the_cache(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._now = lambda: _NOW
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.pin_diagnostic_slot(_NOW - timedelta(days=1))
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 1

        coordinator.clear_diagnostic_slot()
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 2


class TestDiagnosticsTickSyncSwallowsModeExceptions:
    """ADR-000 §8: background failures are logged and swallowed, not
    raised. `_diagnostics_tick_sync` previously had no try/except at
    all around `extra_fit()`/`compute()` — unlike `_refit_sync`'s own
    per-string one — so an exception from either would propagate all
    the way up through `_intraday_tick_sync`'s executor dispatch as an
    unhandled task exception, repeating every single tick for as long
    as the underlying condition persisted and silently preventing
    every diagnostic entity from ever updating again, with no
    attributable trace of why (TASK-0037 follow-up)."""

    def test_extra_fit_exception_does_not_prevent_compute_from_running(self) -> None:
        coordinator, _hass = _make_coordinator()

        class _RaisingExtraFitMode(_CountingDiagnosticMode):
            def extra_fit(self) -> Any:
                self.extra_fit_calls += 1
                self.call_order.append("extra_fit")
                raise RuntimeError("boom")

        fake_mode = _RaisingExtraFitMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")

        coordinator._diagnostics_tick_sync(_NOW)  # must not raise

        assert fake_mode.extra_fit_calls == 1
        # compute() still ran this same tick despite extra_fit()'s
        # exception -- one mode method failing does not block the
        # other.
        assert fake_mode.compute_calls == 1

    def test_compute_exception_does_not_raise_and_keeps_the_previous_result(self) -> None:
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator._diagnostics_tick_sync(_NOW)
        first_result = coordinator.diagnostic_result()
        assert first_result is not None

        class _RaisingComputeMode(_CountingDiagnosticMode):
            def compute(self) -> Any:
                self.compute_calls += 1
                self.call_order.append("compute")
                raise RuntimeError("boom")

        raising_mode = _RaisingComputeMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = raising_mode

        coordinator._diagnostics_tick_sync(_NOW)  # must not raise

        # The stale-but-not-`None` previous result is still served,
        # rather than the tick's failure wiping it out.
        assert coordinator.diagnostic_result() is first_result


class TestDiagnosticResultOffEventLoopDispatch:
    """`diagnostic_result()`'s lazy cache-miss `compute()` call must
    never run directly on the event loop (module docstring:
    `mode.compute()` can perform the same blocking recorder read
    `_fetch_actual_yield_statistics` warns about) — `_running_on_the_
    event_loop()` is what tells apart every other test in this class
    above (a plain synchronous call, computed inline exactly as
    before) from a call reached with a real asyncio event loop running
    in the current thread, the same situation `sensor.py`'s
    `native_value` is actually called from in production (this is the
    exact `RuntimeError: Caught blocking call ... inside the event
    loop` crash this dispatch fixes)."""

    def test_cache_miss_on_the_event_loop_does_not_compute_inline(self) -> None:
        """Given a cache miss reached while a loop is running, When
        `diagnostic_result()` is read, Then `compute()` is not called
        synchronously here — the read sees `None` (the still-empty
        cache) rather than a freshly (and potentially blockingly)
        computed result."""
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")

        async def _read_on_the_event_loop() -> None:
            # No `await` between the read and these assertions — the
            # dispatched recompute task is merely *scheduled*
            # (`asyncio.ensure_future`), never run synchronously as
            # part of this call, so `compute_calls` cannot have
            # advanced yet at this point in the coroutine's own step,
            # regardless of how soon the event loop gets around to it
            # afterwards.
            result = coordinator.diagnostic_result()
            assert result is None
            assert fake_mode.compute_calls == 0

        _run(_read_on_the_event_loop())

    def test_deferred_recompute_populates_the_cache_off_the_event_loop(self) -> None:
        """Given that same cache miss, When the dispatched
        `_async_recompute_diagnostic_result` task actually runs (`hass.
        drain()`, mirroring pumping HA's own event loop), Then
        `compute()` has run exactly once and the result is cached —
        the very next read (the next poll, or the next `"slot"`-cadence
        tick) sees it."""
        coordinator, hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        coordinator.set_active_diagnostic_mode("compare_regressions")

        async def _read_then_drain() -> None:
            coordinator.diagnostic_result()
            await hass.drain()

        _run(_read_then_drain())

        assert fake_mode.compute_calls == 1
        assert coordinator._diagnostic_result_cache is not None
        assert coordinator._diagnostic_result_cache.sensors[0].sensor_id == "0"

    def test_async_recompute_is_a_no_op_when_no_mode_is_active(self) -> None:
        """`_async_recompute_diagnostic_result` mirrors `diagnostic_
        result()`'s own "off" guard — a mode switched back to `"off"`
        (or never selected) before the dispatched task actually runs
        must not call `compute()` on nothing, and must leave the cache
        at `None` rather than caching a stray result for the wrong
        mode."""
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode

        _run(coordinator._async_recompute_diagnostic_result())

        assert fake_mode.compute_calls == 0
        assert coordinator._diagnostic_result_cache is None


class TestDiagnosticSensorIds:
    """`coordinator.diagnostic_sensor_ids()` (ADR-004 §5, fifth
    Amendment, 2026-09-03): the union of every *registered* mode's own
    `sensor_ids()`, not just whichever mode is currently active."""

    def test_returns_the_one_registered_modes_own_ids(self) -> None:
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode

        assert coordinator.diagnostic_sensor_ids() == [("0", "Dummy")]

    def test_available_even_while_off(self) -> None:
        """Entities must exist before any mode is necessarily selected
        (HA entities are added once, at platform setup) — so this must
        not depend on `active_diagnostic_mode()`."""
        coordinator, _hass = _make_coordinator()
        fake_mode = _CountingDiagnosticMode(coordinator)
        coordinator._diagnostic_modes["compare_regressions"] = fake_mode
        assert coordinator.active_diagnostic_mode() == "off"

        assert coordinator.diagnostic_sensor_ids() == [("0", "Dummy")]

    def test_unions_multiple_registered_modes_deduplicated(self) -> None:
        coordinator, _hass = _make_coordinator()
        mode_a = _CountingDiagnosticMode(coordinator)

        class _SecondMode(_CountingDiagnosticMode):
            key = "second_mode"

            def sensor_ids(self) -> list[tuple[str, str]]:
                return [("0", "Should Not Win"), ("extra", "Extra")]

        mode_b = _SecondMode(coordinator)
        coordinator._diagnostic_modes = {"compare_regressions": mode_a, "second_mode": mode_b}

        result = coordinator.diagnostic_sensor_ids()
        assert result == [("0", "Dummy"), ("extra", "Extra")]  # first registration wins for "0"


class TestEnsureBaselineProviderGuards:
    """`_ensure_baseline_provider` (construction helper) is a no-op —
    the already-registered provider is left in place, not replaced —
    when `entity_id` is already registered, and never registers
    anything at all when `attribute`/`shape` is `None` (a per-string
    override with only `baseline_entity_id` set, e.g., ADR-002 §2)."""

    def test_duplicate_entity_id_is_left_untouched(self) -> None:
        coordinator, _hass = _make_coordinator()
        existing = coordinator._entity_providers[_BASELINE_ENTITY]

        coordinator._ensure_baseline_provider(_BASELINE_ENTITY, "wh_period", "sensor_dict")

        assert coordinator._entity_providers[_BASELINE_ENTITY] is existing

    def test_none_attribute_registers_nothing(self) -> None:
        coordinator, _hass = _make_coordinator()

        coordinator._ensure_baseline_provider("sensor.never_registered", None, None)

        assert "sensor.never_registered" not in coordinator._entity_providers

    def test_history_entity_id_threads_through_to_the_constructed_provider(self) -> None:
        """ADR-009 §1c Amendment / ADR-012 §2a Amendment (`TASK-0034`) —
        `_ensure_baseline_provider`'s new optional fifth argument reaches
        the constructed `BaselineProvider` unchanged, readable back via
        the generic `Provider.history_entity_id()` method."""
        coordinator, _hass = _make_coordinator()

        coordinator._ensure_baseline_provider(
            "fs_entry_new", "wh_period", "forecast_solar", "sensor.power_production_now"
        )

        provider = coordinator._entity_providers["fs_entry_new"]
        assert provider.history_entity_id() == "sensor.power_production_now"

    def test_history_entity_id_defaults_to_none(self) -> None:
        coordinator, _hass = _make_coordinator()

        coordinator._ensure_baseline_provider("fs_entry_new", "wh_period", "forecast_solar")

        provider = coordinator._entity_providers["fs_entry_new"]
        assert provider.history_entity_id() is None


class TestFetchActualYieldStatisticsEpochTimestamp:
    """`_fetch_actual_yield_statistics` (ADR-007a §4) parses a
    recorder-returned row's `"start"` via `datetime.fromtimestamp` when
    it comes back as a raw epoch number rather than an already-parsed
    `datetime` — real HA's recorder can return either shape depending
    on the query path; `support_ha.py`'s own `statistics_during_period`
    stand-in always returns `datetime`s, so this monkeypatches the
    coordinator module's imported name directly, for this one test
    only, to exercise the other shape."""

    def test_epoch_float_start_is_parsed_into_a_datetime(self) -> None:
        coordinator, _hass = _make_coordinator()
        epoch = _NOW.timestamp()
        original = _coordinator_mod.statistics_during_period

        def _fake_statistics_during_period(
            hass: Any, start: Any, end: Any, statistic_ids: Any, period: Any, units: Any, types: Any
        ) -> dict[str, list[dict[str, Any]]]:
            return {_ACTUAL_YIELD_ENTITY: [{"start": epoch, "mean": 123.0}]}

        _coordinator_mod.statistics_during_period = _fake_statistics_during_period  # type: ignore[attr-defined]
        try:
            result = coordinator._fetch_actual_yield_statistics(
                _ACTUAL_YIELD_ENTITY, _NOW, _NOW + timedelta(minutes=5)
            )
        finally:
            _coordinator_mod.statistics_during_period = original  # type: ignore[attr-defined]

        assert result == [123.0]


class TestFetchFnHistoryEntityRouting:
    """`_fetch_fn` (ADR-007a §4) routes a past-dated query to the new
    `_fetch_provider_history_statistics` — generically, via
    `Provider.history_entity_id()` (ADR-012 §1/§2a Amendment), never an
    `isinstance(provider, BaselineProvider)` check — instead of
    `provider.fetch()`, whenever the registered provider resolves a
    non-`None` history entity; a provider whose `history_entity_id()`
    stays at the base class's `None` default keeps routing to
    `provider.fetch()` exactly as before this amendment (`TASK-0034`)."""

    _HISTORY_ENTITY = "sensor.power_production_now"

    def test_routes_to_recorder_when_history_entity_id_resolved(self) -> None:
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
            baseline_history_entity_id=self._HISTORY_ENTITY,
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.statistics[self._HISTORY_ENTITY] = {
            _YESTERDAY: 111.0,
            _YESTERDAY + timedelta(minutes=5): 222.0,
        }

        async def _construct() -> Any:
            # Construction itself schedules an immediate Forecast.Solar
            # poll task (`_register_forecast_solar_polls`) for this
            # shape — needs a running loop to attach to, like every
            # other `hass.async_create_task` call site (mirrors
            # `TestBaselineMissingForecastSolarShape` above).
            coordinator = ShadyCoordinator(hass, entry)
            await hass.drain()
            return coordinator

        coordinator = _run(_construct())

        result = coordinator._fetch_fn("fs_entry_1", _YESTERDAY, _YESTERDAY + timedelta(minutes=15))

        assert result == [111.0, 222.0, None]

    def test_falls_back_to_provider_fetch_when_no_history_entity_id(self) -> None:
        """The default fixture's global baseline (`sensor_dict`, no
        `baseline_history_entity_id`) is unaffected by this amendment —
        `provider.history_entity_id()` stays `None`, so `_fetch_fn`
        still calls `provider.fetch()`, reading the seeded
        `_synthetic_wh_period` state exactly as before `TASK-0034`."""
        coordinator, _hass = _make_coordinator()

        result = coordinator._fetch_fn(_BASELINE_ENTITY, _NOW, _NOW + timedelta(minutes=5))

        assert result == [500.0]

    def test_history_entity_routing_leaves_forward_push_path_untouched(self) -> None:
        """ADR-012 §2a's own explicit claim: a resolved `history_
        entity_id` only ever changes `_fetch_fn`'s dispatch, never
        `forward()`/the push path."""
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
            baseline_history_entity_id=self._HISTORY_ENTITY,
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})

        async def _construct() -> Any:
            coordinator = ShadyCoordinator(hass, entry)
            await hass.drain()
            return coordinator

        coordinator = _run(_construct())
        provider = coordinator._entity_providers["fs_entry_1"]
        provider.update_live_forecast({"wh_period": {_NOW.isoformat(): 999.0}})

        forwarded = provider.forward(_NOW)

        assert forwarded == [(_NOW, 999.0)]


class TestFetchProviderHistoryStatistics:
    """`_fetch_provider_history_statistics` (ADR-012 §2a Amendment,
    `TASK-0034`) mirrors `_fetch_actual_yield_statistics` exactly — same
    epoch-timestamp parsing, same slot-mapping — deliberately not shared
    or refactored between the two (ADR-012 §2a's own explicit scope)."""

    def test_returns_seeded_recorder_values_by_slot(self) -> None:
        coordinator, hass = _make_coordinator()
        hass.statistics["sensor.power_production_now"] = {
            _YESTERDAY: 50.0,
            _YESTERDAY + timedelta(minutes=5): 75.0,
        }

        result = coordinator._fetch_provider_history_statistics(
            "sensor.power_production_now", _YESTERDAY, _YESTERDAY + timedelta(minutes=10)
        )

        assert result == [50.0, 75.0]

    def test_epoch_float_start_is_parsed_into_a_datetime(self) -> None:
        coordinator, _hass = _make_coordinator()
        epoch = _NOW.timestamp()
        original = _coordinator_mod.statistics_during_period

        def _fake_statistics_during_period(
            hass: Any, start: Any, end: Any, statistic_ids: Any, period: Any, units: Any, types: Any
        ) -> dict[str, list[dict[str, Any]]]:
            return {"sensor.power_production_now": [{"start": epoch, "mean": 321.0}]}

        _coordinator_mod.statistics_during_period = _fake_statistics_during_period  # type: ignore[attr-defined]
        try:
            result = coordinator._fetch_provider_history_statistics(
                "sensor.power_production_now", _NOW, _NOW + timedelta(minutes=5)
            )
        finally:
            _coordinator_mod.statistics_during_period = original  # type: ignore[attr-defined]

        assert result == [321.0]


class TestResolveStaleForecastSolarHistoryEntities:
    """`_resolve_stale_forecast_solar_history_entities` (ADR-009 §1c
    further Amendment, `TASK-0034-patch-1`) — the startup self-heal for
    a `forecast_solar`-shaped baseline whose `history_entity_id`
    resolved to `None` at config/options-flow submission time (a
    startup-ordering race caught then, at the one point that result
    gets permanently persisted) and was never retried since. Every test
    here monkeypatches the coordinator module's imported
    `resolve_forecast_solar_history_entity` directly, matching this
    file's existing `statistics_during_period` monkeypatch convention —
    the entity-registry matching semantics that function itself
    implements are already fully covered by
    `test_providers_discovery.py`'s own resolution tests; these tests
    are about the coordinator-level orchestration around it."""

    _RESOLVED_ENTITY = "sensor.power_production_now"

    @staticmethod
    def _construct(entry: Any, hass: FakeHomeAssistant) -> Any:
        async def _do() -> Any:
            # Construction itself schedules an immediate Forecast.Solar
            # poll task for a `forecast_solar`-shaped provider — needs a
            # running loop to attach to (mirrors
            # `TestBaselineMissingForecastSolarShape` above).
            coordinator = ShadyCoordinator(hass, entry)
            await hass.drain()
            return coordinator

        return _run(_do())

    def test_resolves_and_persists_global_baseline(self) -> None:
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        coordinator = self._construct(entry, hass)
        provider = coordinator._entity_providers["fs_entry_1"]
        assert provider.history_entity_id() is None  # sanity: starts unresolved

        original = _coordinator_mod.resolve_forecast_solar_history_entity
        _coordinator_mod.resolve_forecast_solar_history_entity = (  # type: ignore[attr-defined]
            lambda hass, config_entry_id: self._RESOLVED_ENTITY
        )
        try:
            coordinator._resolve_stale_forecast_solar_history_entities()
        finally:
            _coordinator_mod.resolve_forecast_solar_history_entity = original  # type: ignore[attr-defined]

        assert provider.history_entity_id() == self._RESOLVED_ENTITY
        assert coordinator.entry.data["baseline_history_entity_id"] == self._RESOLVED_ENTITY
        assert len(hass.config_entries.update_calls) == 1

    def test_resolves_and_persists_per_string_override(self) -> None:
        entry = _make_entry(
            strings={
                _ACTUAL_YIELD_ENTITY: {
                    "name": "Dach Süd",
                    "baseline_entity_id": "fs_entry_2",
                    "baseline_attribute": "wh_period",
                    "baseline_shape": "forecast_solar",
                    "temperature_aware": False,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                }
            },
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        coordinator = self._construct(entry, hass)
        provider = coordinator._entity_providers["fs_entry_2"]
        assert provider.history_entity_id() is None

        original = _coordinator_mod.resolve_forecast_solar_history_entity
        _coordinator_mod.resolve_forecast_solar_history_entity = (  # type: ignore[attr-defined]
            lambda hass, config_entry_id: self._RESOLVED_ENTITY
        )
        try:
            coordinator._resolve_stale_forecast_solar_history_entities()
        finally:
            _coordinator_mod.resolve_forecast_solar_history_entity = original  # type: ignore[attr-defined]

        assert provider.history_entity_id() == self._RESOLVED_ENTITY
        persisted_string = coordinator.entry.data[CONF_STRINGS][_ACTUAL_YIELD_ENTITY]
        assert persisted_string["baseline_history_entity_id"] == self._RESOLVED_ENTITY
        # The global baseline field must stay untouched — this fix is
        # scoped to whichever field(s) actually referenced this config
        # entry, never a blanket write.
        assert coordinator.entry.data.get("baseline_history_entity_id") is None

    def test_still_unresolved_leaves_provider_and_config_untouched(self) -> None:
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        coordinator = self._construct(entry, hass)
        provider = coordinator._entity_providers["fs_entry_1"]

        original = _coordinator_mod.resolve_forecast_solar_history_entity
        _coordinator_mod.resolve_forecast_solar_history_entity = (  # type: ignore[attr-defined]
            lambda hass, config_entry_id: None
        )
        try:
            coordinator._resolve_stale_forecast_solar_history_entities()  # must not raise
        finally:
            _coordinator_mod.resolve_forecast_solar_history_entity = original  # type: ignore[attr-defined]

        assert provider.history_entity_id() is None
        assert hass.config_entries.update_calls == []  # no write for a still-failed retry

    def test_already_resolved_provider_is_never_retried(self) -> None:
        """A provider whose `history_entity_id` was already resolved
        (at flow-submission time, or by an earlier retry) is never
        re-scanned — the entity registry is only worth querying when
        there is actually a gap to fill."""
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
            baseline_history_entity_id=self._RESOLVED_ENTITY,
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        coordinator = self._construct(entry, hass)
        provider = coordinator._entity_providers["fs_entry_1"]
        assert provider.history_entity_id() == self._RESOLVED_ENTITY

        calls: list[str] = []
        original = _coordinator_mod.resolve_forecast_solar_history_entity

        def _spy(hass: Any, config_entry_id: str) -> str:
            calls.append(config_entry_id)
            return "sensor.should_never_be_used"

        _coordinator_mod.resolve_forecast_solar_history_entity = _spy  # type: ignore[attr-defined]
        try:
            coordinator._resolve_stale_forecast_solar_history_entities()
        finally:
            _coordinator_mod.resolve_forecast_solar_history_entity = original  # type: ignore[attr-defined]

        assert calls == []  # never even queried
        assert provider.history_entity_id() == self._RESOLVED_ENTITY  # unchanged
        assert hass.config_entries.update_calls == []

    def test_non_forecast_solar_provider_is_unaffected(self) -> None:
        """The default fixture's global baseline (`sensor_dict`) has no
        `history_entity_id()` concept at all — this must be a silent
        no-op for it, not an `AttributeError`."""
        coordinator, hass = _make_coordinator()

        coordinator._resolve_stale_forecast_solar_history_entities()  # must not raise

        assert hass.config_entries.update_calls == []

    def test_one_update_entry_call_covers_every_resolved_provider(self) -> None:
        """Two distinct `forecast_solar` config entries both unresolved
        — a global baseline and a per-string override — resolve in the
        same pass but persist via exactly one `async_update_entry` call,
        not one per provider."""
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
            strings={
                _ACTUAL_YIELD_ENTITY: {
                    "name": "Dach Süd",
                    "baseline_entity_id": "fs_entry_2",
                    "baseline_attribute": "wh_period",
                    "baseline_shape": "forecast_solar",
                    "temperature_aware": False,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                }
            },
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        coordinator = self._construct(entry, hass)

        resolved_by_entry = {
            "fs_entry_1": "sensor.power_production_now_1",
            "fs_entry_2": self._RESOLVED_ENTITY,
        }
        original = _coordinator_mod.resolve_forecast_solar_history_entity
        _coordinator_mod.resolve_forecast_solar_history_entity = (  # type: ignore[attr-defined]
            lambda hass, config_entry_id: resolved_by_entry[config_entry_id]
        )
        try:
            coordinator._resolve_stale_forecast_solar_history_entities()
        finally:
            _coordinator_mod.resolve_forecast_solar_history_entity = original  # type: ignore[attr-defined]

        assert (
            coordinator._entity_providers["fs_entry_1"].history_entity_id()
            == "sensor.power_production_now_1"
        )
        assert (
            coordinator._entity_providers["fs_entry_2"].history_entity_id() == self._RESOLVED_ENTITY
        )
        assert len(hass.config_entries.update_calls) == 1

    def test_async_startup_self_heals_in_time_for_this_runs_own_backfill(self) -> None:
        """End-to-end: the exact race report this patch fixes. A
        `forecast_solar` baseline's `history_entity_id` was persisted as
        `None` from a past discovery-time race; by the time
        `async_startup` actually runs, Forecast.Solar's companion sensor
        is available with real recorder history — `_resolve_stale_
        forecast_solar_history_entities` (called before `_backfill_
        elapsed_today_slots`, `async_startup`'s own ordering) must
        already unblock this *same* run's backfill, not just the next
        restart's."""
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.config_entries.register_entry("fs_entry_1")
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        hass.statistics[self._RESOLVED_ENTITY] = {
            today_start: 111.0,
            today_start + timedelta(minutes=5): 222.0,
        }
        coordinator = self._construct(entry, hass)
        coordinator._now = lambda: _NOW
        borrowed_model = _fit_a_real_model()
        coordinator.cache.set_model("shading", 0, borrowed_model)
        coordinator._last_fit_at = _NOW  # skip async_refit, isolate the self-heal + backfill

        original = _coordinator_mod.resolve_forecast_solar_history_entity
        _coordinator_mod.resolve_forecast_solar_history_entity = (  # type: ignore[attr-defined]
            lambda hass, config_entry_id: self._RESOLVED_ENTITY
        )
        try:
            _run(coordinator.async_startup(_NOW))
        finally:
            _coordinator_mod.resolve_forecast_solar_history_entity = original  # type: ignore[attr-defined]

        assert (
            coordinator._entity_providers["fs_entry_1"].history_entity_id() == self._RESOLVED_ENTITY
        )
        pushed = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        now_index = Cache.index_for(_NOW)
        elapsed = {index: value for index, value in pushed.items() if index < now_index}
        assert elapsed  # this same run's backfill actually found historical data

    """`_numeric_state` (ADR-005 §1) returns `None`, not a `KeyError`/
    `AttributeError`, for an entity that does not currently exist."""

    def test_missing_entity_returns_none(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator._numeric_state("sensor.does_not_exist_at_all") is None


class TestBaselineMissingForecastSolarShape:
    """`_baseline_missing` (ADR-009 Amendment) checks a `forecast_solar`-
    shaped baseline's existence via `hass.config_entries.async_get_entry`
    rather than `hass.states.get` — that shape stores a config entry's
    own `entry_id` in the field HA entity IDs normally occupy."""

    def test_missing_when_no_matching_config_entry_is_loaded(self) -> None:
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})

        async def _construct() -> Any:
            # Construction itself schedules an immediate Forecast.Solar
            # poll task (`_register_forecast_solar_polls`) for this
            # shape — needs a running loop to attach to, like every
            # other `hass.async_create_task` call site.
            coordinator = ShadyCoordinator(hass, entry)
            await hass.drain()
            return coordinator

        coordinator = _run(_construct())

        assert coordinator._baseline_missing("fs_entry_1") is True
        assert "fs_entry_1" in coordinator.missing_required_entities()

    def test_missing_when_config_entry_exists_but_is_not_yet_loaded(self) -> None:
        """The exact race a real user hit: `async_get_entry` already
        returns a non-`None` entry the moment Home Assistant has begun
        setting up Forecast.Solar, well before that setup (and its
        `get_forecast` service) is actually ready — mere presence must
        not be mistaken for readiness."""
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.config_entries.register_entry("fs_entry_1", state=ConfigEntryState.SETUP_IN_PROGRESS)

        async def _construct() -> Any:
            coordinator = ShadyCoordinator(hass, entry)
            await hass.drain()
            return coordinator

        coordinator = _run(_construct())

        assert coordinator._baseline_missing("fs_entry_1") is True
        assert "fs_entry_1" in coordinator.missing_required_entities()

    def test_not_missing_once_the_config_entry_is_loaded(self) -> None:
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.config_entries.register_entry("fs_entry_1")

        async def _construct() -> Any:
            coordinator = ShadyCoordinator(hass, entry)
            await hass.drain()
            return coordinator

        coordinator = _run(_construct())

        assert coordinator._baseline_missing("fs_entry_1") is False
        assert "fs_entry_1" not in coordinator.missing_required_entities()


class TestTargetCellTemperatureForSlotEdgeCases:
    """`target_cell_temperature_for_slot` (ADR-004 §5's coordinator-level
    diagnostic wiring) returns `None`, rather than raising, both when
    the string has no resolved temperature source at all and when
    `_predict_target_slot_temperature` itself can't produce a value."""

    def test_none_when_no_temperature_source_resolved(self) -> None:
        coordinator, _hass = _make_coordinator()  # default fixture: no temperature source
        index = Cache.index_for(_NOW)
        assert coordinator.target_cell_temperature_for_slot(0, index) is None

    def test_none_when_predict_target_slot_temperature_returns_none(self) -> None:
        # Weather tier resolved, but no `rated_dc_capacity_wp` configured
        # -> `_predict_target_slot_temperature` itself returns `None`
        # (its own documented "no correction can be produced" case).
        entry = _make_entry(default_temperature_source="weather.home")
        hass = FakeHomeAssistant()
        hass.states.set(
            _BASELINE_ENTITY,
            {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
        )
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set("weather.home", {"temperature": 20.0, "forecast": []})
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW

        index = Cache.index_for(_NOW)
        assert coordinator.target_cell_temperature_for_slot(0, index) is None

    def test_fc_array_stays_all_nan_when_no_baseline_resolves(self) -> None:
        """Weather tier resolved, but neither the string's own nor the
        global `baseline_entity_id` is set — `fc_array` must stay
        entirely `NaN` (never touched) rather than raise on a `None`
        sensor_id, falling through straight to `_predict_target_slot_
        temperature`, itself still perfectly able to return `None`
        gracefully for the same reason `test_none_when_predict_target_
        slot_temperature_returns_none` above does (no `rated_dc_
        capacity_wp`)."""
        entry = _make_entry(
            baseline_entity_id=None,
            default_temperature_source="weather.home",
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set("weather.home", {"temperature": 20.0, "forecast": []})
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW

        index = Cache.index_for(_NOW)
        assert coordinator.target_cell_temperature_for_slot(0, index) is None

    def test_fc_array_slot_stays_nan_when_baseline_value_unavailable(self) -> None:
        """Weather tier resolved and `baseline_entity_id` is set, but
        the baseline entity has no `wh_period` data at all for the
        queried slot — `cache.get_time_range`'s `raw[0]` comes back
        `None`, not a `float`, so the slot must stay `NaN` rather than
        assign a non-float into `fc_array`."""
        entry = _make_entry(default_temperature_source="weather.home")
        hass = FakeHomeAssistant()
        hass.states.set(_BASELINE_ENTITY, {})  # no `wh_period` attribute at all
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.states.set("weather.home", {"temperature": 20.0, "forecast": []})
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW

        index = Cache.index_for(_NOW)
        assert coordinator.target_cell_temperature_for_slot(0, index) is None


class TestHandleActualYieldUpdateWithNoYieldTotal:
    """`_handle_actual_yield_update` (ADR-005 §5) must skip the PV
    energy-integral accumulation, not raise, when `pv_sum()` itself
    comes back `None` (e.g. every configured actual-yield entity is
    currently unavailable) — the update still gets persisted either
    way, just without accumulating anything this tick."""

    def test_energy_not_accumulated_when_pv_sum_is_none(self) -> None:
        coordinator, hass = _make_coordinator()
        coordinator._now = lambda: _NOW
        coordinator.pv_sum = lambda: None
        accumulated: list[tuple[str, Any, float]] = []
        coordinator._accumulate_energy = lambda kind, now, total: accumulated.append(
            (kind, now, total)
        )

        async def _drive() -> None:
            coordinator._handle_actual_yield_update(None)
            await hass.drain()

        _run(_drive())

        assert accumulated == []


class TestFcSumFcDayArrayNoStrings:
    """`fc_sum`/`fc_day_array` (ADR-005 §2/§3) degrade gracefully — no
    `IndexError`/empty-`get_time_range` crash — for a config entry with
    zero configured strings."""

    @staticmethod
    def _make_no_strings_coordinator() -> Any:
        entry = _make_entry(**{CONF_STRINGS: {}})
        hass = FakeHomeAssistant()
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW
        return coordinator

    def test_fc_sum_is_none_with_no_strings(self) -> None:
        coordinator = self._make_no_strings_coordinator()
        assert coordinator.fc_sum(_NOW) is None

    def test_fc_day_array_is_all_none_with_no_strings(self) -> None:
        coordinator = self._make_no_strings_coordinator()
        timestamps, values = coordinator.fc_day_array(_NOW)
        assert len(timestamps) == 288
        assert values == [None] * 288


class TestActualYieldListenersNoStrings:
    """`_register_actual_yield_listeners` (ADR-005 §5) registers no
    listener at all for a config entry with zero configured strings —
    there is no actual-yield entity to track (unlike the global
    baseline provider, which is still registered independent of any
    string — see `TestGenericProviderPushLoop` — so only the
    actual-yield entity itself is asserted absent here)."""

    def test_no_listener_registered_with_no_strings(self) -> None:
        entry = _make_entry(**{CONF_STRINGS: {}})
        hass = FakeHomeAssistant()
        ShadyCoordinator(hass, entry)
        assert _ACTUAL_YIELD_ENTITY not in hass.states._listeners


class TestEnergyResetHandlerFiresPersist:
    """`_handle_energy_reset` (ADR-005 §5/§6's day-boundary schedule)
    schedules a persist only when `_maybe_reset_energy_totals` actually
    performed a reset — true for a freshly constructed coordinator,
    whose `cache.last_reset_date()` starts as `None`."""

    def test_fresh_coordinator_triggers_a_persist_task(self) -> None:
        coordinator, hass = _make_coordinator()
        assert coordinator.cache.last_reset_date() is None

        async def _drive() -> None:
            coordinator._handle_energy_reset(_NOW)
            await hass.drain()

        _run(_drive())
        assert coordinator.cache.last_reset_date() == _NOW.date()


class TestRecomputeStringEarlyReturns:
    """`_recompute_string` (ADR-002 §2/ADR-006 §1) returns early — no
    push, no exception — for every one of its defensive "nothing to
    recompute yet" branches."""

    def test_no_baseline_configured_at_all(self) -> None:
        entry = _make_entry(
            baseline_entity_id=None,
            baseline_attribute=None,
            baseline_shape=None,
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW
        # A model wouldn't normally exist without a resolvable baseline
        # (`_fit_string`'s own matching guard) — set one by hand purely
        # to reach this method's own, independent baseline check.
        borrowed_model = _fit_a_real_model()
        coordinator.cache.set_model("shading", 0, borrowed_model)

        coordinator._recompute_string(coordinator._strings[0], _NOW)

        assert coordinator.cache.validated_range(coordinator.forecast_sensor_id(0)) is None

    def test_resolved_baseline_entity_has_no_registered_provider(self) -> None:
        # A per-string `baseline_entity_id` with no `baseline_attribute`/
        # `baseline_shape` (ADR-002 §2's override fields) never gets a
        # `BaselineProvider` registered (`_ensure_baseline_provider`'s
        # own `attribute is None or shape is None` guard) — so it
        # resolves non-`None` here but has nothing in
        # `_entity_providers` to recompute from.
        entry = _make_entry(
            strings={
                _ACTUAL_YIELD_ENTITY: {
                    "name": "Dach Süd",
                    "baseline_entity_id": "sensor.orphan_baseline",
                    "baseline_attribute": None,
                    "baseline_shape": None,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                }
            },
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        coordinator = ShadyCoordinator(hass, entry)
        coordinator._now = lambda: _NOW
        borrowed_model = _fit_a_real_model()
        coordinator.cache.set_model("shading", 0, borrowed_model)

        coordinator._recompute_string(coordinator._strings[0], _NOW)

        assert coordinator.cache.validated_range(coordinator.forecast_sensor_id(0)) is None

    def test_baseline_series_entirely_outside_the_recompute_horizon(self) -> None:
        coordinator, hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        before = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert before  # sanity: the normal refit did push something

        class _OutOfHorizonProvider(BaselineProvider):
            def forward(self, now: datetime) -> list[tuple[datetime, float]]:
                return [(now + timedelta(days=5), 500.0)]

        coordinator._entity_providers[_BASELINE_ENTITY] = _OutOfHorizonProvider(
            hass, _BASELINE_ENTITY, "wh_period", "sensor_dict"
        )

        coordinator._recompute_string(coordinator._strings[0], _NOW)

        after = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert after == before  # unchanged: the early return, not a crash-then-silent-push

    def test_empty_values_by_index_after_predict_day_basis(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        before = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))

        original = coordinator._predict_day_basis
        coordinator._predict_day_basis = lambda *args, **kwargs: ({}, {})
        try:
            coordinator._recompute_string(coordinator._strings[0], _NOW)
        finally:
            coordinator._predict_day_basis = original

        after = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert after == before

    def test_empty_pushed_dict_after_clamp(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        before = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))

        original = coordinator._clamp_basis
        coordinator._clamp_basis = lambda *args, **kwargs: {}
        try:
            coordinator._recompute_string(coordinator._strings[0], _NOW)
        finally:
            coordinator._clamp_basis = original

        after = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert after == before


def _fit_a_real_model() -> Any:
    """A real, validly-fitted `FittedModel` instance (borrowed from a
    normally-configured coordinator), for tests that need
    `cache.get_model("shading", ...)` to be non-`None` purely to reach
    an unrelated, later branch — not to exercise the fit itself."""
    donor, _hass = _make_coordinator()
    _run(donor.async_refit(_NOW))
    model = donor.cache.get_model("shading", 0)
    assert model is not None
    return model


class TestPredictDayBasisPastSlotSkip:
    """`_predict_day_basis` (ADR-002 §3) skips any slot whose absolute
    index is already before `now` — called directly here with a
    same-day, earlier-than-`now` slot, since `_recompute_string`'s own
    pre-filter (`now <= ts < horizon_end`) never actually lets such a
    slot reach this method through the normal call path."""

    def test_past_slot_is_excluded_from_the_result(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        string = coordinator._strings[0]
        day = _NOW.date()
        midnight_slot = 0  # 00:00 same day -- strictly before _NOW (10:00)

        values, fc = coordinator._predict_day_basis(string, day, {midnight_slot: 500.0}, _NOW)

        assert values == {}
        assert fc == {}


class TestPredictDayBasisBefore:
    """`_predict_day_basis_before` (ADR-002 §1a) is the mirror image of
    `_predict_day_basis`: restricted to slots strictly *before* a given
    index, rather than at/after `now` — the one piece
    `_backfill_elapsed_today_slots_for_string` needs and the normal
    recompute path never does."""

    def test_only_slots_before_the_given_index_are_included(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        string = coordinator._strings[0]
        day = _NOW.date()
        day_start_index = Cache.index_for(datetime(day.year, day.month, day.day, tzinfo=UTC))
        before_index = day_start_index + 5

        values, fc = coordinator._predict_day_basis_before(
            string, day, {4: 500.0, 5: 500.0, 6: 500.0}, before_index
        )

        assert set(values) == {day_start_index + 4}
        assert set(fc) == {day_start_index + 4}


class TestBackfillElapsedTodaySlots:
    """`_backfill_elapsed_today_slots` (ADR-002 §1a) — `async_startup`'s
    own one-time catch-up for today's already-elapsed slots, which a
    fresh restart's empty in-memory forecast cache would otherwise
    leave permanently `None`: `_recompute_string` deliberately never
    fills a slot before `now` (ADR-002 §3), since under continuous
    operation it was always written before it became past."""

    def test_fills_elapsed_slots_from_history(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        today_start_index = Cache.index_for(today_start)
        now_index = Cache.index_for(_NOW)
        before = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        # Sanity: the normal recompute never touched anything before "now".
        assert all(index > now_index for index in before)

        coordinator._backfill_elapsed_today_slots(_NOW)

        after = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        newly_filled = set(after) - set(before)
        assert newly_filled  # something was actually backfilled
        assert all(today_start_index <= index < now_index for index in newly_filled)

    def test_no_op_at_exactly_midnight(self) -> None:
        coordinator, _hass = _make_coordinator()
        midnight = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        _run(coordinator.async_refit(midnight))
        before = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))

        coordinator._backfill_elapsed_today_slots(midnight)

        after = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        assert after == before  # nothing has elapsed yet today, nothing to backfill

    def test_skips_a_string_with_no_fitted_model_yet(self) -> None:
        coordinator, _hass = _make_coordinator()
        # Deliberately never fit — no model at all yet.
        coordinator._backfill_elapsed_today_slots(_NOW)
        assert coordinator.cache.validated_range(coordinator.forecast_sensor_id(0)) is None

    def test_finds_history_even_after_this_runs_own_successful_forward_push(self) -> None:
        """The exact real-world race this backfill exists for, with the
        one variable none of the other `forecast_solar` tests actually
        exercise: a *successful* Forecast.Solar poll. `async_startup`
        always polls (and therefore pushes fs_entry_1's forward series,
        marking it `to_index=None` — ADR-007a §2) before running this
        backfill, on every restart, not just as an occasional race —
        so a real installation's baseline entity is never actually
        queryable through `Cache.get_time_range()` by the time this
        method runs. The already-resolved `history_entity_id`'s real
        recorder statistics for today's already-elapsed slots must
        still be found (via `_fetch_fn`, bypassing the cache entirely
        for this read) despite that."""
        history_entity = "sensor.power_production_now"
        entry = _make_entry(
            baseline_entity_id="fs_entry_1",
            baseline_attribute="wh_period",
            baseline_shape="forecast_solar",
            baseline_history_entity_id=history_entity,
        )
        hass = FakeHomeAssistant()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        hass.config_entries.register_entry("fs_entry_1")
        today_start = datetime(_NOW.year, _NOW.month, _NOW.day, tzinfo=UTC)
        hass.statistics[history_entity] = {
            today_start: 111.0,
            today_start + timedelta(minutes=5): 222.0,
            today_start + timedelta(minutes=10): 333.0,
        }

        class _WorkingForecastSolarServices:
            """Unlike `support_ha.py`'s own `FakeServices` (`async_call`
            raises `KeyError` for an unregistered handler, silently
            swallowed by `_poll_forecast_solar`'s `except Exception` —
            every other `forecast_solar`-shaped test in this file relies
            on exactly that to keep push out of its way), this always
            succeeds — a *future* sample, so `push()` actually has
            something at/after `not_before_index` to mark the sensor
            "actively pushed" with."""

            def __init__(self) -> None:
                self.calls: list[str] = []

            async def async_call(
                self,
                domain: str,
                service: str,
                service_data: dict[str, Any] | None = None,
                *,
                blocking: bool = False,
                return_response: bool = False,
            ) -> Any:
                assert (domain, service) == ("forecast_solar", "get_forecast")
                self.calls.append((service_data or {})["config_entry"])
                future = (_NOW + timedelta(hours=1)).isoformat()
                return {"wh_period": {future: 500.0}}

        hass.services = _WorkingForecastSolarServices()  # type: ignore[assignment]

        async def _construct() -> Any:
            coordinator = ShadyCoordinator(hass, entry)
            await hass.drain()
            return coordinator

        coordinator = _run(_construct())
        coordinator._now = lambda: _NOW
        borrowed_model = _fit_a_real_model()
        coordinator.cache.set_model("shading", 0, borrowed_model)
        coordinator._last_fit_at = _NOW  # skip the heavy refit; still runs the push refresh

        _run(coordinator.async_startup(_NOW))

        # Sanity: the push actually happened and poisoned naive
        # `Cache.get_time_range()` access for fs_entry_1, same as a real
        # restart — if this ever stops being true the test below would
        # pass for the wrong reason. (Two calls, not one: construction's
        # own fire-and-forget "immediate first sample", plus
        # `async_startup`'s own awaited refresh.)
        assert hass.services.calls == ["fs_entry_1", "fs_entry_1"]  # type: ignore[attr-defined]
        assert coordinator.cache.validated_range("fs_entry_1") is not None
        assert coordinator.cache.validated_range("fs_entry_1")[1] is None

        pushed = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(0))
        now_index = Cache.index_for(_NOW)
        elapsed = {index: value for index, value in pushed.items() if index < now_index}
        assert elapsed  # this same run's backfill still found real historical data

    def test_one_strings_failure_does_not_abort_the_others(self) -> None:
        coordinator, _hass = _make_two_string_coordinator()
        borrowed_model = _fit_a_real_model()
        coordinator.cache.set_model("shading", 0, borrowed_model)
        coordinator.cache.set_model("shading", 1, borrowed_model)

        original = coordinator._backfill_elapsed_today_slots_for_string

        def _boom(string: Any, today_start: datetime, now: datetime) -> None:
            if string.index == 0:
                raise RuntimeError("synthetic backfill failure")
            original(string, today_start, now)

        coordinator._backfill_elapsed_today_slots_for_string = _boom

        coordinator._backfill_elapsed_today_slots(_NOW)  # must not raise

        after = hass_pushed_values(coordinator, coordinator.forecast_sensor_id(1))
        assert after  # string 1 still got backfilled despite string 0's failure


class TestClampBasisEmptyInput:
    """`_clamp_basis` (ADR-006 §1b) returns `{}` for an empty basis,
    rather than building a zero-length `numpy` array and indexing into
    it."""

    def test_empty_values_returns_empty_dict(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator._clamp_basis({}, {}, None) == {}


class TestComputeIntradayOutputEmptyBasis:
    """`_compute_intraday_output` (ADR-006 §1a/§1b) returns `{}` for an
    `IntradayState` whose basis has no slots at all."""

    def test_empty_basis_returns_empty_dict(self) -> None:
        coordinator, _hass = _make_coordinator()
        basis = IntradayBasis(values={}, fc={}, inverter_limit=None)
        state = IntradayState(
            reset_at=_NOW,
            active_slots_since_reset=0,
            basis=basis,
            ratio_string=None,
            effective_factor=1.0,
        )
        assert coordinator._compute_intraday_output(state) == {}


class TestIntradayEnergyWindowNoElapsedTime:
    """`_intraday_energy_window` (ADR-006 §1a) returns `(0.0, 0.0)`
    without querying the cache at all when `now` has not advanced past
    the window's own start — the zero-width-window edge case."""

    def test_now_equal_to_start_returns_zero_zero(self) -> None:
        coordinator, _hass = _make_coordinator()
        string = coordinator._strings[0]
        assert coordinator._intraday_energy_window(string, _NOW, _NOW) == (0.0, 0.0)


class TestAdvanceIntradayStringNoState:
    """`_advance_intraday_string` (ADR-006 §1a) is a no-op for a string
    with no `IntradayState` yet (mode just turned on, or no recompute
    has run since) — the next recompute establishes one, not this
    method."""

    def test_no_state_yet_is_a_no_op(self) -> None:
        coordinator, _hass = _make_coordinator()
        string = coordinator._strings[0]
        assert coordinator.cache.intraday_state(string.index) is None

        coordinator._advance_intraday_string(string, _NOW)

        assert coordinator.cache.intraday_state(string.index) is None


class TestIntradayTickFullDispatchPath:
    """The 5-minute intraday/diagnostics tick's full, real dispatch
    chain (`_handle_intraday_tick` -> `_async_intraday_tick` ->
    `_intraday_tick_sync`, ADR-006 §1a/ADR-004 §2/§4) — every other
    intraday test in this module calls `_advance_intraday_string`
    directly; this is the one test exercising the actual scheduled-
    callback/executor-job path those tests all bypass."""

    def test_tick_completes_without_error_when_everything_is_off(self) -> None:
        coordinator, hass = _make_coordinator()  # default fixture: intraday + diagnostics off

        async def _drive() -> None:
            coordinator._handle_intraday_tick(_NOW)
            await hass.drain()  # let the scheduled task actually run to completion

        _run(_drive())

        assert hass._pending_tasks == []  # the task ran, not just got queued


class TestDiagnosticsTickSyncModeOff:
    """`_diagnostics_tick_sync` (ADR-004 §2/§4) is a genuine no-op — the
    zero-extra-cost guarantee ADR-004 §1 promises — when no diagnostic
    mode is active, the default state for every config entry."""

    def test_no_active_mode_is_a_no_op(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator.active_diagnostic_mode() == "off"

        coordinator._diagnostics_tick_sync(_NOW)

        assert coordinator._diagnostic_result_cache is None


class TestRegisterProviderListenersSkipsNonForwardingProviders:
    """`_register_provider_listeners` (ADR-012 §4) registers no
    listener at all for a `Provider` that leaves `forward()` at its
    base-class default — "no forecast concept of its own" — even
    though every provider this project actually ships
    (`BaselineProvider`/`TemperatureProvider`) does override it."""

    def test_provider_without_forward_gets_no_listener(self) -> None:
        coordinator, hass = _make_coordinator()

        class _NoForwardConceptProvider(Provider):
            def fetch(self, start: datetime, end: datetime) -> list[float | None | str]:
                return []

        coordinator._entity_providers["sensor.no_forward_concept"] = _NoForwardConceptProvider()

        coordinator._register_provider_listeners()

        assert "sensor.no_forward_concept" not in hass.states._listeners


class TestPushProviderSeriesEdgeCases:
    """`_push_provider_series` (ADR-012 §4) is a no-op, not a crash, for
    an unrecognized entity_id and for a provider whose `forward()`
    returns a non-`list` iterable that turns out empty once consumed
    (the `if not series`/`if not values` distinction: a bare iterator
    object is always truthy, unlike an empty `list`)."""

    def test_unregistered_entity_id_is_a_no_op(self) -> None:
        coordinator, _hass = _make_coordinator()
        coordinator._push_provider_series("sensor.totally_unregistered", _NOW)  # must not raise

    def test_empty_iterator_forward_result_is_a_no_op(self) -> None:
        coordinator, hass = _make_coordinator()

        class _EmptyIteratorProvider(BaselineProvider):
            def forward(self, now: datetime) -> Any:
                return iter(())  # truthy iterator, yields nothing

        coordinator._entity_providers[_BASELINE_ENTITY] = _EmptyIteratorProvider(
            hass, _BASELINE_ENTITY, "wh_period", "sensor_dict"
        )

        coordinator._push_provider_series(_BASELINE_ENTITY, _NOW)  # must not raise
