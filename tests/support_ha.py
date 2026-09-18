"""Home-Assistant-dependent test support shared by every test file
outside ADR-000 §6's zero-mocking tier (ADR-000 §6, ADR-002, ADR-005,
ADR-007): the hand-written `homeassistant` stub's universal core, plus
the `Fake*` real-not-`Mock` stand-ins every one of those files needs.

Extracted from `test_coordinator.py`, `test_button.py`, `test_init.py`,
`test_sensor_aggregates.py`, and `test_sensor_forecast.py`, which each
carried their own near-duplicate copy of this. Where those five copies
had genuinely diverged (a file needing `hass.data`/`hass.config_entries`
that another didn't, `FakeStates` gaining a `remove()` some copies
lacked), this module keeps the union of every field/method any consumer
needs rather than the intersection: an unused extra attribute on a fake
is harmless, whereas under-provisioning one would just reintroduce a
fork the next file that needs it would have to carry again. `_install_ha_
stub()` mirrors that same principle for the module-level stub tree: it
registers exactly the `homeassistant.*` surface every one of those five
files' modules-under-test imports in common (`core`, `config_entries`,
`helpers.event`, `helpers.storage`, `components.recorder.statistics`) —
a file needing more (`test_button.py`'s `homeassistant.components.
button`, `test_init.py`'s `homeassistant.exceptions`/`helpers.start`/
`helpers.config_validation`) calls this first, then extends the already-
registered `sys.modules["homeassistant"]`/`sys.modules["homeassistant.
helpers"]`/etc. itself, the same pattern `_install_sensor_stub()` below
follows for the one extension two different files actually share
(`homeassistant.const`'s `UnitOfPower`/`UnitOfEnergy` plus `homeassistant
.components.sensor`, identical between `test_sensor_aggregates.py` and
`test_sensor_forecast.py`).

`test_config_flow.py`, `test_translations.py`, `test_select.py`,
`test_providers_discovery.py`, and `test_providers_temperature.py` each
hand-roll their own, genuinely different, narrower `Fake*`/stub set
(a `ConfigFlow`/`OptionsFlow`/`FlowResult` stub for the first two, a
`FakeState`/`FakeStates`/`FakeHomeAssistant` trio constructed from a
fixed list rather than built incrementally for the rest) — deliberately
left alone here rather than force-unified: their shapes don't actually
match this module's (different constructor signatures, different
semantics), and coercing them to match would trade a real correctness
risk for a line-count reduction. `test_translations.py` does still
import this module's `FakeConfigEntry`/`_callback`, since those two are
genuinely identical to what it needs.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from enum import Enum
from types import ModuleType, SimpleNamespace
from typing import Any


def _callback(func: Any) -> Any:
    return func


class ConfigEntryState(Enum):
    """Minimal stand-in for `homeassistant.config_entries.ConfigEntryState`
    (real HA's own enum) — only `LOADED` is ever actually compared against
    by `coordinator.py`'s `_baseline_missing` (ADR-002 §1a/ADR-009
    Amendment: a `forecast_solar`-shaped baseline's own config entry must
    be genuinely loaded, not merely present, before its `forward()` can
    succeed), but every other member real HA defines is included too so a
    test can express "registered but not yet loaded" realistically.
    """

    NOT_LOADED = "not_loaded"
    LOADED = "loaded"
    SETUP_IN_PROGRESS = "setup_in_progress"
    SETUP_ERROR = "setup_error"
    SETUP_RETRY = "setup_retry"
    FAILED_UNLOAD = "failed_unload"


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
        # `state=None` means "unknown", matching real HA's own
        # `hass.states.async_set` convention -- callers that want to
        # clear a numeric value to unavailable pass `None` rather than
        # a sentinel string.
        resolved_state = "unknown" if state is None else str(state)
        self._states[entity_id] = FakeState(entity_id, attributes, resolved_state)
        for listener in self._listeners.get(entity_id, []):
            listener(None)

    def remove(self, entity_id: str) -> None:
        self._states.pop(entity_id, None)


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


class FakeConfigEntry:
    def __init__(
        self,
        entry_id: str,
        data: dict[str, Any],
        title: str = "Shady",
        state: ConfigEntryState = ConfigEntryState.LOADED,
    ) -> None:
        self.entry_id = entry_id
        self.data = data
        # `title` defaults rather than being required: only `device.py`'s
        # `device_info()` (via `sensor.py`/`button.py`/`select.py`) reads
        # it, and every existing two-positional-arg call site predates
        # that helper, so a default keeps them all unchanged.
        self.title = title
        # Defaults to `LOADED` — every existing call site predates
        # `_baseline_missing`'s state-awareness and never passes this,
        # so a default keeps them all unchanged; only a test explicitly
        # exercising the "not yet loaded" race needs to override it.
        self.state = state


class FakeConfigEntries:
    """Real (non-`Mock`) stand-in for the slice of `hass.config_entries`
    (`ConfigEntries`) `__init__.py` actually calls: forwarding/unloading
    this config entry's platforms, and scheduling a reload. Records
    every call for assertions rather than doing anything with real HA
    platform machinery — `sensor.py`/`select.py`/`button.py` are never
    executed by these fakes, matching every other platform-level test
    file's own independence from this one."""

    def __init__(self) -> None:
        self.forwarded: list[tuple[Any, list[str]]] = []
        self.unloaded: list[tuple[Any, list[str]]] = []
        self.reload_calls: list[str] = []
        # entry_id -> registered config entry object, for
        # `coordinator.py`'s `_baseline_missing`'s `forecast_solar`-shaped
        # branch (`async_get_entry`, ADR-009 Amendment) — a plain
        # (synchronous, despite the `async_` prefix, matching real HA's
        # own `ConfigEntries.async_get_entry`) lookup, not a coroutine.
        self._entries: dict[str, Any] = {}

    async def async_forward_entry_setups(self, entry: Any, platforms: list[str]) -> None:
        self.forwarded.append((entry, list(platforms)))

    async def async_unload_platforms(self, entry: Any, platforms: list[str]) -> bool:
        self.unloaded.append((entry, list(platforms)))
        return True

    def async_schedule_reload(self, entry_id: str) -> None:
        self.reload_calls.append(entry_id)

    def register_entry(
        self, entry_id: str, entry: Any = None, state: ConfigEntryState = ConfigEntryState.LOADED
    ) -> None:
        self._entries[entry_id] = (
            entry if entry is not None else SimpleNamespace(entry_id=entry_id, state=state)
        )

    def async_get_entry(self, entry_id: str) -> Any | None:
        return self._entries.get(entry_id)


class FakeServices:
    """Real (non-`Mock`) stand-in for `hass.services` — enough surface
    for `__init__.py`'s `hass.services.has_service`/`async_register`
    and a test-side `async_call` that actually applies the registered
    `vol.Schema` (so `cv.datetime` string-parsing is exercised for
    real, not bypassed)."""

    def __init__(self) -> None:
        self._handlers: dict[tuple[str, str], tuple[Any, Any]] = {}

    def has_service(self, domain: str, service: str) -> bool:
        return (domain, service) in self._handlers

    def async_register(self, domain: str, service: str, handler: Any, schema: Any = None) -> None:
        self._handlers[(domain, service)] = (handler, schema)

    async def async_call(
        self, domain: str, service: str, service_data: dict[str, Any] | None = None
    ) -> None:
        handler, schema = self._handlers[(domain, service)]
        data = schema(service_data or {}) if schema is not None else (service_data or {})
        await handler(SimpleNamespace(data=data))


class FakeHomeAssistant:
    def __init__(self) -> None:
        self.states = FakeStates()
        self.statistics: dict[str, dict[datetime, float]] = {}
        self.data: dict[str, Any] = {}
        self._pending_tasks: list[asyncio.Task[Any]] = []
        # Backs `FakeStore` — a plain dict simulating on-disk persistence,
        # so constructing a second coordinator against this same
        # `FakeHomeAssistant` (a simulated restart) sees whatever the
        # first one saved (ADR-005 §5/§6, ADR-007 §1, TASK-0012).
        self.store_data: dict[str, Any] = {}
        self.config_entries = FakeConfigEntries()
        self.services = FakeServices()
        # ADR-002 §1a's own pivot: True by default (the common case for
        # a config-entry reload/late setup) -- tests that exercise the
        # "Home Assistant is still starting" branch set this False
        # before calling `async_setup_entry`.
        self.is_running = True
        self._at_started_callbacks: list[Any] = []

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

    async def async_finish_starting(self) -> None:
        """Test helper simulating Home Assistant reporting fully
        started: flips `is_running` and runs every callback
        `async_at_started` queued while it was `False`, awaited
        directly (deterministic, unlike the real event-bus dispatch)."""
        self.is_running = True
        callbacks, self._at_started_callbacks = self._at_started_callbacks, []
        for callback_fn in callbacks:
            await callback_fn(self)


def _install_ha_stub() -> None:
    """Registers the shared core of the hand-written `homeassistant`
    stub into `sys.modules`: `homeassistant`, `.core` (`callback`),
    `.config_entries` (`ConfigEntry`), `.helpers`, `.helpers.event`
    (`async_track_time_change`/`async_track_time_interval`/
    `async_track_state_change_event`), `.helpers.storage` (`Store`),
    `.helpers.device_registry` (`DeviceInfo`/`DeviceEntryType`, for
    `device.py`'s `device_info()`), `.components`, `.components.recorder`
    (`get_instance`), `.components.recorder.statistics`
    (`statistics_during_period`). Every HA-dependent test file that
    shares this module calls this first, then layers its own further
    `homeassistant.*` stub modules on top for whatever else its module
    under test imports, by fetching the already-registered parent
    module back out of `sys.modules` and extending it — see
    `_install_sensor_stub()` below for a worked example."""
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers_event = ModuleType("homeassistant.helpers.event")
    ha_helpers_storage = ModuleType("homeassistant.helpers.storage")
    ha_helpers_device_registry = ModuleType("homeassistant.helpers.device_registry")
    ha_components = ModuleType("homeassistant.components")
    ha_recorder = ModuleType("homeassistant.components.recorder")
    ha_recorder_statistics = ModuleType("homeassistant.components.recorder.statistics")

    ha_core.callback = _callback  # type: ignore[attr-defined]

    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]
    ha_config_entries.ConfigEntryState = ConfigEntryState  # type: ignore[attr-defined]

    def async_track_time_change(
        hass: Any, action: Any, *, hour: int, minute: int, second: int
    ) -> Any:
        # Never auto-fires in tests — the handler this registration
        # would eventually invoke is exercised directly instead, a
        # real (non-mocked) call into the exact same code path.
        return lambda: None

    def async_track_time_interval(hass: Any, action: Any, interval: Any) -> Any:
        # Same non-auto-firing convention as `async_track_time_change`
        # above (TASK-0013).
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

    def get_instance(hass: Any) -> Any:
        # Real HA's recorder instance exposes `async_add_executor_job`;
        # `FakeHomeAssistant` already implements the identical method
        # directly, so `hass` itself doubles as the "recorder instance"
        # every `get_instance(hass).async_add_executor_job(...)` call
        # site (`coordinator.py`) needs.
        return hass

    ha_recorder.get_instance = get_instance  # type: ignore[attr-defined]

    ha_helpers_storage.Store = FakeStore  # type: ignore[attr-defined]

    class DeviceEntryType:
        """Real (non-`Mock`) stand-in for HA's `DeviceEntryType` enum —
        `device.py` only ever reads `.SERVICE`."""

        SERVICE = "service"

    def DeviceInfo(**kwargs: Any) -> dict[str, Any]:
        # Real HA's `DeviceInfo` is a `TypedDict` — calling it just
        # builds a plain `dict` of its keyword arguments at runtime, so
        # a thin function mirrors that exactly without pulling in the
        # real `homeassistant.helpers.device_registry` module.
        return dict(kwargs)

    ha_helpers_device_registry.DeviceEntryType = DeviceEntryType  # type: ignore[attr-defined]
    ha_helpers_device_registry.DeviceInfo = DeviceInfo  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.helpers = ha_helpers  # type: ignore[attr-defined]
    ha_helpers.event = ha_helpers_event  # type: ignore[attr-defined]
    ha_helpers.storage = ha_helpers_storage  # type: ignore[attr-defined]
    ha_helpers.device_registry = ha_helpers_device_registry  # type: ignore[attr-defined]
    ha.components = ha_components  # type: ignore[attr-defined]
    ha_components.recorder = ha_recorder  # type: ignore[attr-defined]
    ha_recorder.statistics = ha_recorder_statistics  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.event"] = ha_helpers_event
    sys.modules["homeassistant.helpers.storage"] = ha_helpers_storage
    sys.modules["homeassistant.helpers.device_registry"] = ha_helpers_device_registry
    sys.modules["homeassistant.components"] = ha_components
    sys.modules["homeassistant.components.recorder"] = ha_recorder
    sys.modules["homeassistant.components.recorder.statistics"] = ha_recorder_statistics


def _install_sensor_stub() -> None:
    """Extends the already-installed core stub (call `_install_ha_stub()`
    first) with `homeassistant.const` (`UnitOfPower`/`UnitOfEnergy`) and
    `homeassistant.components.sensor` (`SensorEntity`/`SensorDeviceClass`
    /`SensorStateClass`) — identical between `test_sensor_aggregates.py`
    and `test_sensor_forecast.py`, the only two consumers, hence shared
    here rather than left as a second pair of near-duplicates."""
    ha = sys.modules["homeassistant"]
    ha_components = sys.modules["homeassistant.components"]
    ha_const = ModuleType("homeassistant.const")
    ha_components_sensor = ModuleType("homeassistant.components.sensor")

    class SensorEntity:
        """Real (non-Mock) stand-in — nothing beyond a plain base class
        carrying `_attr_*` attributes; every aggregate sensor overrides
        every relevant property itself (ADR-000 §3's thin-glue rule)."""

    class SensorDeviceClass:
        POWER = "power"
        ENERGY = "energy"

    class SensorStateClass:
        MEASUREMENT = "measurement"
        TOTAL = "total"
        TOTAL_INCREASING = "total_increasing"

    ha_components_sensor.SensorEntity = SensorEntity  # type: ignore[attr-defined]
    ha_components_sensor.SensorDeviceClass = SensorDeviceClass  # type: ignore[attr-defined]
    ha_components_sensor.SensorStateClass = SensorStateClass  # type: ignore[attr-defined]

    class UnitOfPower:
        WATT = "W"

    class UnitOfEnergy:
        WATT_HOUR = "Wh"

    ha_const.UnitOfPower = UnitOfPower  # type: ignore[attr-defined]
    ha_const.UnitOfEnergy = UnitOfEnergy  # type: ignore[attr-defined]

    ha.const = ha_const  # type: ignore[attr-defined]
    ha_components.sensor = ha_components_sensor  # type: ignore[attr-defined]

    sys.modules["homeassistant.const"] = ha_const
    sys.modules["homeassistant.components.sensor"] = ha_components_sensor
