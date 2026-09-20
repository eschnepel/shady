"""Tests for `__init__.py`'s `async_setup_entry`/`async_unload_entry`
and the `shady.select_diagnostic_slot` service (ADR-002 §1/§1a/§5,
ADR-004 §2a/§5, TASK-0016).

`__init__.py` is HA-facing (real, non-`TYPE_CHECKING` imports of
`homeassistant.exceptions`, `homeassistant.helpers.start`,
`homeassistant.helpers.config_validation`, on top of everything
`coordinator.py` itself already needs) — outside ADR-000 §6's zero-
mocking pure tier. This file extends `tests/test_button.py`'s hand-
written `homeassistant` stub convention (a real, non-`Mock` stand-in,
registered directly in `sys.modules` before file-path-loading the
module under test) with the additional surface `__init__.py` touches:
`ConfigEntryNotReady`/`ServiceValidationError`, `async_at_started`,
`cv.datetime`, and `hass.config_entries`/`hass.services` as real
(non-module) objects on `FakeHomeAssistant`, since ADR-002 §1a's own
behavior hinges on `hass.is_running` and the two exceptions above,
which need real stand-ins, not mocks, to exercise meaningfully. Fully
self-contained, per that same established convention.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

from tests.support import _SHADY_DIR, _load, _run
from tests.support_ha import FakeHomeAssistant, _install_ha_stub


def _install_init_extras_stub() -> None:
    """Extends the already-installed core stub (call `_install_ha_stub()`
    first) with `homeassistant.exceptions` (`ConfigEntryNotReady`,
    `ServiceValidationError`), `homeassistant.helpers.start`
    (`async_at_started`), and `homeassistant.helpers.config_validation`
    (`datetime`) — this file's own additions, the only consumer of any
    of the three."""
    ha = sys.modules["homeassistant"]
    ha_helpers = sys.modules["homeassistant.helpers"]
    ha_exceptions = ModuleType("homeassistant.exceptions")
    ha_helpers_start = ModuleType("homeassistant.helpers.start")
    ha_helpers_config_validation = ModuleType("homeassistant.helpers.config_validation")

    # -- `homeassistant.exceptions` --

    class ConfigEntryNotReady(Exception):
        pass

    class ServiceValidationError(Exception):
        pass

    ha_exceptions.ConfigEntryNotReady = ConfigEntryNotReady  # type: ignore[attr-defined]
    ha_exceptions.ServiceValidationError = ServiceValidationError  # type: ignore[attr-defined]

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

    # -- `homeassistant.helpers.config_validation` -- real `cv.datetime`
    # accepts either an already-parsed `datetime` or an ISO-8601 string;
    # this stub mirrors exactly that narrow slice, not the full
    # validator library.
    def cv_datetime(value: Any) -> datetime:
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value)
            except ValueError:
                pass
        raise ValueError(f"Invalid datetime specified: {value}")

    ha_helpers_config_validation.datetime = cv_datetime  # type: ignore[attr-defined]

    ha.exceptions = ha_exceptions  # type: ignore[attr-defined]
    ha_helpers.start = ha_helpers_start  # type: ignore[attr-defined]
    ha_helpers.config_validation = ha_helpers_config_validation  # type: ignore[attr-defined]

    sys.modules["homeassistant.exceptions"] = ha_exceptions
    sys.modules["homeassistant.helpers.start"] = ha_helpers_start
    sys.modules["homeassistant.helpers.config_validation"] = ha_helpers_config_validation


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
SERVICE_SELECT_DIAGNOSTIC_SLOT = _init_mod.SERVICE_SELECT_DIAGNOSTIC_SLOT

ConfigEntryNotReady = sys.modules["homeassistant.exceptions"].ConfigEntryNotReady
ServiceValidationError = sys.modules["homeassistant.exceptions"].ServiceValidationError

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


class TestServicePersistsAcrossPartialUnload:
    """AUDIT-0011 item 2: `async_unload_entry` deliberately never
    unregisters the domain-wide service on a single entry's unload --
    see `__init__.py`'s own module docstring for the reasoning this
    test verifies. Reuses `TestServiceRegistration`'s own two-entry
    construction pattern for consistency."""

    def test_service_stays_registered_after_unloading_one_of_two_entries(self) -> None:
        hass = FakeHomeAssistant()
        entry_a = _make_entry()
        _seed_required_entities(hass)
        _run(async_setup_entry(hass, entry_a))

        second_yield_entity = "sensor.string_b_yield"
        entry_b = _make_entry(
            **{
                CONF_STRINGS: {
                    second_yield_entity: {
                        "name": "Dach Nord",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    }
                }
            }
        )
        hass.states.set(second_yield_entity, {})
        # `_make_entry()` always hard-codes the same "test_entry" id --
        # a real second config entry has a distinct one; without this,
        # entry_b's setup would silently overwrite entry_a's
        # hass.data[DOMAIN] slot instead of adding a second one.
        entry_b.entry_id = "test_entry_b"
        _run(async_setup_entry(hass, entry_b))
        assert hass.services.has_service(DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT)

        _run(async_unload_entry(hass, entry_a))

        assert entry_a.entry_id not in hass.data[DOMAIN]
        # entry_b is still loaded ...
        assert entry_b.entry_id in hass.data[DOMAIN]
        # ... and the domain-wide service was not touched by entry_a's
        # unload, exactly the asymmetry the module docstring documents.
        assert hass.services.has_service(DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT)


class TestServicesYamlMatchesRegisteredHandlers:
    """AUDIT-0011 item 3: the executable version of the manual
    `services.yaml`-vs-registered-handlers check the audit performed by
    hand, mirroring `test_translations.py`'s own dynamic-introspection
    pattern. Deliberately does not add a PyYAML dependency for this one
    file-structure read (real Home Assistant instances always provide
    PyYAML at runtime for this exact file, but this project declares no
    such dependency for its own test suite) -- `services.yaml`'s own
    shape is simple enough (one service, all its fields indented
    beneath it) that a top-level-key scan is sufficient and exact."""

    @staticmethod
    def _services_yaml_top_level_keys(path: Path) -> set[str]:
        keys: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line or line[0] in (" ", "\t", "#"):
                continue
            if ":" not in line:
                continue
            key = line.split(":", 1)[0].strip()
            if key:
                keys.add(key)
        return keys

    def test_declared_and_registered_service_names_match(self) -> None:
        services_yaml_path = _SHADY_DIR / "services.yaml"
        declared = self._services_yaml_top_level_keys(services_yaml_path)

        hass = FakeHomeAssistant()
        _init_mod._register_services(hass)
        registered = {service for (domain, service) in hass.services._handlers if domain == DOMAIN}

        assert declared == registered


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


class TestServiceRegistration:
    """ADR-004 §2a/§5: `shady.select_diagnostic_slot` registered exactly
    once per Home Assistant instance, not once per config entry."""

    def test_registered_exactly_once_across_two_config_entries(self) -> None:
        hass = FakeHomeAssistant()
        entry_a = _make_entry()
        _seed_required_entities(hass)
        _run(async_setup_entry(hass, entry_a))
        assert hass.services.has_service(DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT)
        handler_after_first, _schema = hass.services._handlers[
            (DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT)
        ]

        second_yield_entity = "sensor.string_b_yield"
        entry_b = _make_entry(
            **{
                CONF_STRINGS: {
                    second_yield_entity: {
                        "name": "Dach Nord",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    }
                }
            }
        )
        hass.states.set(second_yield_entity, {})
        # Re-setup (a second config entry) must not raise on
        # re-registration, and must not replace the existing handler.
        _run(async_setup_entry(hass, entry_b))

        handler_after_second, _schema2 = hass.services._handlers[
            (DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT)
        ]
        assert handler_after_first is handler_after_second

    def test_service_clears_pin_when_called_with_no_timestamp(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        _seed_required_entities(hass)
        _run(async_setup_entry(hass, entry))
        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator.pin_diagnostic_slot(_NOW, now=_NOW)
        assert coordinator.diagnosed_slot(now=_NOW).index == coordinator._pinned_slot_index

        _run(hass.services.async_call(DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT, {}))

        assert coordinator._pinned_slot_index is None

    def test_service_pins_a_valid_in_horizon_timestamp(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        _seed_required_entities(hass)
        _run(async_setup_entry(hass, entry))
        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator._now = lambda: _NOW  # deterministic horizon check
        target = datetime(2026, 6, 15, 14, 0, tzinfo=UTC)

        _run(
            hass.services.async_call(
                DOMAIN,
                SERVICE_SELECT_DIAGNOSTIC_SLOT,
                {"timestamp": target.isoformat()},
            )
        )

        from shady.cache import Cache as _Cache

        assert coordinator._pinned_slot_index == _Cache.index_for(target)

    def test_service_raises_validation_error_beyond_horizon(self) -> None:
        hass = FakeHomeAssistant()
        entry = _make_entry()
        _seed_required_entities(hass)
        _run(async_setup_entry(hass, entry))
        coordinator = hass.data[DOMAIN][entry.entry_id]
        coordinator._now = lambda: _NOW  # deterministic horizon check
        far_future = datetime(2026, 7, 1, tzinfo=UTC)

        raised = False
        try:
            _run(
                hass.services.async_call(
                    DOMAIN,
                    SERVICE_SELECT_DIAGNOSTIC_SLOT,
                    {"timestamp": far_future.isoformat()},
                )
            )
        except ServiceValidationError:
            raised = True

        assert raised
        # Rejected -- no state change.
        assert coordinator._pinned_slot_index is None

    def test_service_call_with_no_loaded_entries_is_a_safe_no_op(self) -> None:
        hass = FakeHomeAssistant()
        hass.data.setdefault(DOMAIN, {})
        # See the note in the reload test above on why this is
        # `_init_mod` (this file's own captured reference), not a
        # fresh `import shady`.
        _init_mod._register_services(hass)

        _run(hass.services.async_call(DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT, {}))
        # No exception -- nothing to iterate over.
