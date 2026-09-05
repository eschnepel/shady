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

import asyncio
import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# -- hand-written `homeassistant` stub (real stand-in, not a mock) ----------


def _callback(func: Any) -> Any:
    return func


class FakeState:
    def __init__(
        self,
        entity_id: str,
        attributes: dict[str, Any] | None = None,
        state: str = "unknown",
    ) -> None:
        self.entity_id = entity_id
        self.state = state
        self.attributes = attributes or {}


class FakeStates:
    def __init__(self) -> None:
        self._states: dict[str, FakeState] = {}
        self._listeners: dict[str, list[Any]] = {}

    def get(self, entity_id: str) -> FakeState | None:
        return self._states.get(entity_id)

    def async_all(self, domain: str | None = None) -> list[FakeState]:
        values = list(self._states.values())
        if domain is None:
            return values
        return [s for s in values if s.entity_id.startswith(f"{domain}.")]

    def set(
        self,
        entity_id: str,
        attributes: dict[str, Any] | None = None,
        state: float | str | None = None,
    ) -> None:
        """Set/update an entity's state and fire any registered
        state-change listeners — a real (non-mock) stand-in for a live
        HA state-changed event, sufficient for what `coordinator.py`'s
        listeners actually read (they re-derive everything from current
        state, never from the fired event's payload). `state` mirrors
        real HA: always stored as a string (`_numeric_state`'s own
        `float(state.state)` parse is what turns it back into a
        number) — `None` keeps the pre-`TASK-0012` default of
        `"unknown"`."""
        resolved_state = "unknown" if state is None else str(state)
        self._states[entity_id] = FakeState(entity_id, attributes, resolved_state)
        for listener in self._listeners.get(entity_id, []):
            listener(None)


class FakeHomeAssistant:
    def __init__(self) -> None:
        self.states = FakeStates()
        self.statistics: dict[str, dict[datetime, float]] = {}
        self._pending_tasks: list[asyncio.Task[Any]] = []
        # Backs `FakeStore` — a plain dict simulating on-disk persistence,
        # so constructing a second coordinator against this same
        # `FakeHomeAssistant` (a simulated restart) sees whatever the
        # first one saved (ADR-005 §5/§6, ADR-007 §1, TASK-0012).
        self.store_data: dict[str, Any] = {}

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        return func(*args)

    def async_create_task(self, coro: Any) -> Any:
        task = asyncio.ensure_future(coro)
        self._pending_tasks.append(task)
        return task

    async def drain(self) -> None:
        """Test-only: let every `async_create_task`-scheduled coroutine
        (recompute, midnight-triggered refit) actually run to completion
        before assertions — mirrors pumping HA's own event loop."""
        while self._pending_tasks:
            pending = self._pending_tasks
            self._pending_tasks = []
            await asyncio.gather(*pending)


class FakeStore:
    """Real (non-`Mock`) stand-in for `homeassistant.helpers.storage
    .Store` — backed by `hass.store_data` (see `FakeHomeAssistant`),
    not an in-memory-only dict of its own, so a simulated restart
    (constructing a second `FakeStore`/coordinator against the same
    `hass`) actually observes a prior `async_save`."""

    def __init__(self, hass: Any, version: int, key: str) -> None:
        self._hass = hass
        self._version = version
        self._key = key

    async def async_load(self) -> Any:
        return self._hass.store_data.get(self._key)

    async def async_save(self, data: Any) -> None:
        self._hass.store_data[self._key] = data


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers_event = ModuleType("homeassistant.helpers.event")
    ha_helpers_storage = ModuleType("homeassistant.helpers.storage")
    ha_components = ModuleType("homeassistant.components")
    ha_recorder = ModuleType("homeassistant.components.recorder")
    ha_recorder_statistics = ModuleType("homeassistant.components.recorder.statistics")

    ha_core.callback = _callback  # type: ignore[attr-defined]

    class FakeConfigEntry:
        def __init__(self, entry_id: str, data: dict[str, Any]) -> None:
            self.entry_id = entry_id
            self.data = data

    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]

    def async_track_time_change(
        hass: Any, action: Any, *, hour: int, minute: int, second: int
    ) -> Any:
        # Never auto-fires in tests — `_handle_midnight` is exercised
        # directly, which is a real (non-mocked) call into the exact
        # same handler this registration would eventually invoke.
        return lambda: None

    def async_track_time_interval(hass: Any, action: Any, interval: Any) -> Any:
        # Same non-auto-firing convention as `async_track_time_change`
        # above (TASK-0013) — `_handle_intraday_tick` is exercised
        # directly in tests that need it.
        return lambda: None

    def async_track_state_change_event(hass: Any, entity_ids: list[str], action: Any) -> Any:
        for entity_id in entity_ids:
            hass.states._listeners.setdefault(entity_id, []).append(action)

        def _unsub() -> None:
            for entity_id in entity_ids:
                listeners = hass.states._listeners.get(entity_id, [])
                if action in listeners:
                    listeners.remove(action)

        return _unsub

    ha_helpers_event.async_track_time_change = async_track_time_change  # type: ignore[attr-defined]
    ha_helpers_event.async_track_time_interval = async_track_time_interval  # type: ignore[attr-defined]
    ha_helpers_event.async_track_state_change_event = (  # type: ignore[attr-defined]
        async_track_state_change_event
    )

    def statistics_during_period(
        hass: Any,
        start_time: datetime,
        end_time: datetime | None,
        statistic_ids: set[str] | None,
        period: str,
        units: Any,
        types: set[str],
    ) -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        for entity_id in statistic_ids or set():
            by_start = hass.statistics.get(entity_id, {})
            rows = [
                {"start": start, "mean": mean}
                for start, mean in sorted(by_start.items())
                if start >= start_time and (end_time is None or start < end_time)
            ]
            result[entity_id] = rows
        return result

    ha_recorder_statistics.statistics_during_period = statistics_during_period  # type: ignore[attr-defined]

    ha_helpers_storage.Store = FakeStore  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.helpers = ha_helpers  # type: ignore[attr-defined]
    ha_helpers.event = ha_helpers_event  # type: ignore[attr-defined]
    ha_helpers.storage = ha_helpers_storage  # type: ignore[attr-defined]
    ha.components = ha_components  # type: ignore[attr-defined]
    ha_components.recorder = ha_recorder  # type: ignore[attr-defined]
    ha_recorder.statistics = ha_recorder_statistics  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.event"] = ha_helpers_event
    sys.modules["homeassistant.helpers.storage"] = ha_helpers_storage
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.recorder"] = ha_recorder
    sys.modules["homeassistant.components.recorder.statistics"] = ha_recorder_statistics


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
_load("providers/discovery.py", "shady.providers.discovery")
_load("providers/temperature.py", "shady.providers.temperature")
_load("regression/__init__.py", "shady.regression")
_load("regression/base.py", "shady.regression.base")
_load("regression/linear.py", "shady.regression.linear")
_load("regression/kernel.py", "shady.regression.kernel")
_load("regression/wls2.py", "shady.regression.wls2")
_load("regression/wls3.py", "shady.regression.wls3")
_load("yield_correction.py", "shady.yield_correction")
_load("forecast_adjust.py", "shady.forecast_adjust")
_load("aggregation.py", "shady.aggregation")
_load("cache.py", "shady.cache")
_load("string_computation.py", "shady.string_computation")
_load("diagnostics/__init__.py", "shady.diagnostics")
_diagnostics_base_mod = _load("diagnostics/base.py", "shady.diagnostics.base")
_load("diagnostics/compare_regressions.py", "shady.diagnostics.compare_regressions")
_const_mod = _load("const.py", "shady.const")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")

# TYPE_CHECKING-only static import mirroring the runtime file-path load
# above (ADR-000 §6, matching `test_diagnostics_base.py`'s own
# convention) — gives mypy a real type for `DiagnosticMode` so
# `_CountingDiagnosticMode` below type-checks normally, without
# reintroducing the package import (and therefore `homeassistant.*`)
# the file-path load avoids.
if TYPE_CHECKING:
    from shady.diagnostics.base import DiagnosticMode as DiagnosticMode  # noqa: PLC0414
else:
    DiagnosticMode = _diagnostics_base_mod.DiagnosticMode

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
Cache = sys.modules["shady.cache"].Cache
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
        CONF_STRINGS: [
            {
                "name": "Dach Süd",
                "baseline_entity_id": None,
                "baseline_attribute": None,
                "baseline_shape": None,
                "temperature_aware": False,
                "actual_yield_entity_id": _ACTUAL_YIELD_ENTITY,
                "converter_limit_w": None,
                "temperature_source_entity_id": None,
                "temperature_coefficient_pct_per_c": -0.4,
                "rated_dc_capacity_wp": None,
            }
        ],
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


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


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
        button_model = coordinator._models[0]

        coordinator2, hass2 = _make_coordinator()

        async def _drive_midnight() -> None:
            coordinator2._handle_midnight(_NOW)
            await hass2.drain()

        _run(_drive_midnight())
        midnight_model = coordinator2._models[0]

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

        assert (
            coordinator._models[0].coefficients == coordinator_clean._models[0].coefficients
        ).all()


class TestStartupSafetyNet:
    """Given a config entry with no model fitted yet (or a last fit >24h
    old), When the coordinator's startup-fit entry point is called, Then
    a fit runs immediately, in addition to the daily schedule."""

    def test_async_startup_fits_when_no_model_yet(self) -> None:
        coordinator, _hass = _make_coordinator()
        assert coordinator._models == {}
        _run(coordinator.async_startup(_NOW))
        assert 0 in coordinator._models
        assert coordinator._last_fit_at is not None

    def test_async_startup_skips_when_recently_fitted(self) -> None:
        coordinator, _hass = _make_coordinator()
        _run(coordinator.async_refit(_NOW))
        first_fit_at = coordinator._last_fit_at
        _run(coordinator.async_startup(_NOW + timedelta(hours=1)))
        assert coordinator._last_fit_at == first_fit_at  # unchanged: no re-fit triggered


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

        assert coordinator._models == {}
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
                CONF_STRINGS: [
                    {
                        "name": "Dach Süd",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "actual_yield_entity_id": _ACTUAL_YIELD_ENTITY,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    },
                    {
                        "name": "Dach Nord",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "actual_yield_entity_id": second_yield_entity,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    },
                ]
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
            CONF_STRINGS: [
                {
                    "name": "Dach Süd",
                    "baseline_entity_id": None,
                    "baseline_attribute": None,
                    "baseline_shape": None,
                    "actual_yield_entity_id": _ACTUAL_YIELD_ENTITY,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                },
                {
                    "name": "Dach Nord",
                    "baseline_entity_id": None,
                    "baseline_attribute": None,
                    "baseline_shape": None,
                    "actual_yield_entity_id": _SECOND_ACTUAL_YIELD_ENTITY,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                },
            ],
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
    file already uses for `coordinator._now`/`coordinator._models`
    elsewhere) so `diagnostic_result()`'s caching behaviour can be
    verified by call count, independent of `CompareRegressionsMode`'s
    own real computation."""

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
