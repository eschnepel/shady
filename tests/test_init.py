"""Tests for `__init__.py`'s `async_setup_entry`/`async_unload_entry`
(ADR-002 §1/§1a/§5, TASK-0016). The diagnosed-slot pin this module used
to expose via the `shady.select_diagnostic_slot` service (ADR-004 §2a)
is entity-only now (ADR-004 §2f) — see `tests/test_datetime.py` and
`tests/test_button.py` for its coverage; `__init__.py` itself registers
no service at all any more.

`__init__.py` is HA-facing (real, non-`TYPE_CHECKING` imports of
`homeassistant.exceptions`, `homeassistant.helpers.start`, on top of
everything `coordinator.py` itself already needs) — outside ADR-000
§6's zero-mocking pure tier. This file extends `tests/test_button.py`'s
hand-written `homeassistant` stub convention (a real, non-`Mock`
stand-in, registered directly in `sys.modules` before file-path-loading
the module under test) with the additional surface `__init__.py`
touches: `ConfigEntryNotReady`, `async_at_started`, and
`hass.config_entries` as a real (non-module) object on
`FakeHomeAssistant`, since ADR-002 §1a's own behavior hinges on
`hass.is_running` and that exception, which needs a real stand-in, not
a mock, to exercise meaningfully. Fully self-contained, per that same
established convention.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any

from tests.support import _load, _run
from tests.support_ha import FakeHomeAssistant, _install_ha_stub


def _install_init_extras_stub() -> None:
    """Extends the already-installed core stub (call `_install_ha_stub()`
    first) with `homeassistant.exceptions` (`ConfigEntryNotReady`) and
    `homeassistant.helpers.start` (`async_at_started`) — this file's own
    additions, the only consumer of either."""
    ha = sys.modules["homeassistant"]
    ha_helpers = sys.modules["homeassistant.helpers"]
    ha_exceptions = ModuleType("homeassistant.exceptions")
    ha_helpers_start = ModuleType("homeassistant.helpers.start")

    # -- `homeassistant.exceptions` --

    class ConfigEntryNotReady(Exception):
        pass

    ha_exceptions.ConfigEntryNotReady = ConfigEntryNotReady  # type: ignore[attr-defined]

    # -- `homeassistant.helpers.start` --
    # Real HA fires immediately if `hass.is_running` is already True by
    # registration time, else waits for the started event -- mirrored
    # here via `FakeHomeAssistant._at_started_callbacks` /
    # `async_finish_starting`.
    def async_at_started(hass: Any, at_start_cb: Any) -> Any:
        if hass.is_running:
            hass.async_create_task(at_start_cb(hass))
        else:
            hass._at_started_callbacks.append(at_start_cb)
        return lambda: None

    ha_helpers_start.async_at_started = async_at_started  # type: ignore[attr-defined]

    ha.exceptions = ha_exceptions  # type: ignore[attr-defined]
    ha_helpers.start = ha_helpers_start  # type: ignore[attr-defined]

    sys.modules["homeassistant.exceptions"] = ha_exceptions
    sys.modules["homeassistant.helpers.start"] = ha_helpers_start


_install_ha_stub()
_install_init_extras_stub()

_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []
sys.modules["shady"] = _shady_pkg

_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_load("regression/base.py", "shady.regression.base")
_const_mod = _load("const.py", "shady.const")
_load("cache.py", "shady.cache")
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
_load("diagnostics/base.py", "shady.diagnostics.base")
_load("diagnostics/compare_regressions.py", "shady.diagnostics.compare_regressions")
_load("coordinator_like.py", "shady.coordinator_like")
_coordinator_mod = _load("coordinator.py", "shady.coordinator")
_init_mod = _load("__init__.py", "shady")

ShadyCoordinator = _coordinator_mod.ShadyCoordinator
CONF_STRINGS = _const_mod.CONF_STRINGS
CONF_WINDOW_DAYS = _const_mod.CONF_WINDOW_DAYS
DOMAIN = _const_mod.DOMAIN
async_setup_entry = _init_mod.async_setup_entry
async_unload_entry = _init_mod.async_unload_entry
PLATFORMS = _init_mod.PLATFORMS

ConfigEntryNotReady = sys.modules["homeassistant.exceptions"].ConfigEntryNotReady

# -- shared test fixture (mirrors test_button.py's own) ---------------------

_NOW = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 6, 14, tzinfo=UTC)
_BASELINE_ENTITY = "sensor.forecast_solar_estimate"
_ACTUAL_YIELD_ENTITY = "sensor.string_a_yield"


def _synthetic_wh_period(start: datetime, end: datetime) -> dict[str, float]:
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


def _seed_required_entities(hass: FakeHomeAssistant) -> None:
    hass.states.set(
        _BASELINE_ENTITY,
        {"wh_period": _synthetic_wh_period(_YESTERDAY, _NOW + timedelta(days=3))},
    )
    hass.states.set(_ACTUAL_YIELD_ENTITY, {})
    _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))


# -- tests --------------------------------------------------------------


class TestPlatforms:
    """`PLATFORMS` forwards every entity platform this integration ships,
    the diagnosed-slot `datetime` and its auto-follow `switch` (ADR-004
    §2f/§2g) included — a platform missing here would silently never be
    set up, whatever its own module does."""

    def test_forwards_the_diagnosed_slot_datetime_and_follow_switch(self) -> None:
        assert set(PLATFORMS) == {"sensor", "select", "button", "datetime", "switch"}


class TestAsyncSetupEntryGenuineConstructionFailure:
    """AUDIT-0011 item 1: a genuine (non-`ConfigEntryNotReady`)
    exception during `ShadyCoordinator` construction must propagate
    unhandled -- `__init__.py` has zero `try`/`except` around this call
    (ADR-000 §8), so a malformed config entry's exception reaches Home
    Assistant's own loader directly, never swallowed or converted into
    a different exception type. `coordinator.py`'s own `__init__` does
    a plain `data[CONF_WINDOW_DAYS]` lookup with no `.get()` fallback
    (unlike several later-added fields it *does* default) -- a config
    entry missing that key is the natural "malformed" case, achievable
    entirely within the existing `hass`/`ConfigEntry` stub convention,
    no harness expansion needed."""

    def test_malformed_entry_missing_required_field_propagates_unhandled(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        del entry.data[CONF_WINDOW_DAYS]

        raised: BaseException | None = None
        try:
            _run(async_setup_entry(hass, entry))
        # Deliberately broad, same reason as the noqa below: this test
        # exists specifically to prove *any* exception propagates
        # unconverted, not just a specific expected type (see class
        # docstring) -- narrowing to Exception would weaken exactly the
        # guarantee being tested.
        # codeql[py/catch-base-exception]
        except BaseException as exc:  # noqa: BLE001 -- deliberately broad: proving *any* exception propagates, unconverted, not just a specific expected type
            raised = exc

        assert isinstance(raised, KeyError)
        assert not isinstance(raised, ConfigEntryNotReady)
        # Not swallowed into a return value or a stored coordinator --
        # the failed construction never got that far.
        assert entry.entry_id not in hass.data.get(DOMAIN, {})
        assert hass.config_entries.forwarded == []


class TestAsyncSetupEntryHassRunning:
    """ADR-002 §1a, point 1: `hass.is_running` already `True`."""

    def test_missing_required_entities_raises_not_ready(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        # Deliberately not seeding any hass.states -- both the baseline
        # and actual-yield entities are missing.

        raised = False
        try:
            _run(async_setup_entry(hass, entry))
        except ConfigEntryNotReady:
            raised = True

        assert raised
        assert entry.entry_id not in hass.data.get(DOMAIN, {})
        assert hass.config_entries.forwarded == []
        # The transient coordinator's own listeners were cancelled, not
        # left dangling behind for a retry to pile duplicates onto.
        assert hass.states._listeners.get(_ACTUAL_YIELD_ENTITY, []) == []

    def test_all_entities_present_constructs_stores_and_runs_startup_fit(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        _seed_required_entities(hass)

        result = _run(async_setup_entry(hass, entry))

        assert result is True
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert isinstance(coordinator, ShadyCoordinator)
        assert hass.config_entries.forwarded == [(entry, PLATFORMS)]
        # The startup fit actually ran, inline, before returning.
        assert coordinator._last_fit_at is not None
        # async_restore_energy_state() ran too (TASK-0012's "Known gap"
        # note) -- last_reset_date is only ever set by that call.
        assert coordinator.cache.last_reset_date() is not None

    def test_missing_baseline_only_still_raises_not_ready(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        hass.states.set(_ACTUAL_YIELD_ENTITY, {})
        _seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
        # Baseline entity deliberately left unset.

        raised = False
        try:
            _run(async_setup_entry(hass, entry))
        except ConfigEntryNotReady:
            raised = True
        assert raised


class TestAsyncSetupEntryHassStarting:
    """ADR-002 §1a, point 2: `hass.is_running` still `False`."""

    def test_missing_entities_still_stores_and_forwards_platforms(self) -> None:
        hass = FakeHomeAssistant()
        hass.is_running = False
        entry = _make_entry()
        # No entities seeded at all.

        result = _run(async_setup_entry(hass, entry))

        assert result is True
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert isinstance(coordinator, ShadyCoordinator)
        assert hass.config_entries.forwarded == [(entry, PLATFORMS)]
        # The fit itself is deferred, not run inline.
        assert coordinator._last_fit_at is None
        # Energy-state restore is not gated on entity availability.
        assert coordinator.cache.last_reset_date() is not None

    def test_deferred_callback_runs_fit_once_started_if_entities_present(self) -> None:
        hass = FakeHomeAssistant()
        hass.is_running = False
        entry = _make_entry()
        _seed_required_entities(hass)

        _run(async_setup_entry(hass, entry))
        coordinator = hass.data[DOMAIN][entry.entry_id]
        assert coordinator._last_fit_at is None

        _run(hass.async_finish_starting())

        assert coordinator._last_fit_at is not None
        assert hass.config_entries.reload_calls == []

    def test_deferred_callback_schedules_reload_if_still_missing(self) -> None:
        hass = FakeHomeAssistant()
        hass.is_running = False
        entry = _make_entry()
        # Still no entities once "started" fires.

        _run(async_setup_entry(hass, entry))
        coordinator = hass.data[DOMAIN][entry.entry_id]

        async def _finish_and_wait() -> None:
            await hass.async_finish_starting()
            # Drain the sleep-then-reload task the deferred callback
            # itself scheduled via hass.async_create_task.
            for task in list(hass._pending_tasks):
                if not task.done():
                    _ = await task

        # `_init_mod` is this file's own captured reference (from load
        # time) to the executed `__init__.py` module -- NOT a fresh
        # `import shady`, which would resolve via `sys.modules["shady"]`
        # at call time and could by then point at whatever placeholder
        # a *different* test file's own independent stub-install left
        # behind there (every test file in this project freely stomps
        # `sys.modules["shady"]` for its own self-contained loading).
        _init_mod._MISSING_ENTITIES_RELOAD_DELAY_S = 0.0  # type: ignore[attr-defined]
        _run(_finish_and_wait())

        assert coordinator._last_fit_at is None
        assert hass.config_entries.reload_calls == [entry.entry_id]


class TestAsyncUnloadEntry:
    def test_unload_cancels_listeners_and_removes_data_slot(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        _seed_required_entities(hass)
        _run(async_setup_entry(hass, entry))
        assert entry.entry_id in hass.data[DOMAIN]
        assert hass.states._listeners.get(_ACTUAL_YIELD_ENTITY, []) != []

        result = _run(async_unload_entry(hass, entry))

        assert result is True
        assert entry.entry_id not in hass.data[DOMAIN]
        assert hass.config_entries.unloaded == [(entry, PLATFORMS)]
        assert hass.states._listeners.get(_ACTUAL_YIELD_ENTITY, []) == []

    def test_unload_of_never_loaded_entry_is_a_safe_no_op(self) -> None:
        hass = FakeHomeAssistant()
        hass.data.setdefault(DOMAIN, {})
        entry = _make_entry()

        result = _run(async_unload_entry(hass, entry))

        assert result is True
        assert entry.entry_id not in hass.data[DOMAIN]
