"""Tests for `config_flow.py` (ADR-010, `TASK-0035`).

`config_flow.py` is HA-facing (it subclasses `homeassistant.config_entries
.ConfigFlow` for real, not just under `TYPE_CHECKING`) — it is outside
ADR-000 §6's zero-mocking pure tier, and the project declares no
`homeassistant` runtime dependency (it is supplied by the host HA
instance, per `manifest.json`'s `requirements`). Rather than installing
the full `homeassistant` package (a large, unrelated dependency this
project's own `pyproject.toml` deliberately does not declare), this file
registers a small, hand-written, real (non-`Mock`) stand-in for exactly
the `homeassistant.core`/`config_entries`/`data_entry_flow`/
`helpers.selector` surface `config_flow.py` touches, directly in
`sys.modules` — the same "real stand-in, not a mock" philosophy
`FakeHomeAssistant`/`FakeState` already establish in
`test_providers_discovery.py`, extended to the additional things an
HA-facing reconfigure flow needs: real classes to subclass, a real (if
minimal) `_get_reconfigure_entry`/`async_update_reload_and_abort`/
`async_show_menu` trio, and a real `EntitySelector` stand-in.

Tests call each `async_step_*` method directly rather than simulating
the full HA frontend menu-redirection dance: choosing a reconfigure-menu
option, in real Home Assistant, re-enters the flow at
`async_step_<chosen_option>` — exactly the method this file calls next,
so driving the flow this way exercises the same step sequence a real
menu selection would produce.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any, cast

from tests.support import _load, _run
from tests.support_ha import _callback


class FlowResult(dict):  # type: ignore[type-arg]
    """Real (non-Mock) stand-in for `homeassistant.data_entry_flow`'s
    `FlowResult` — a plain dict carries every key this project's flow
    steps set (`type`, `step_id`, `data_schema`, `errors`, `title`,
    `data`, `menu_options`, `reason`)."""


class FakeConfigEntry:
    """Real (non-Mock) stand-in for `homeassistant.config_entries.
    ConfigEntry` — holds `data`/`entry_id`/`title`, the attributes
    `ShadyConfigFlow` reads or writes."""

    def __init__(self, data: dict[str, Any], entry_id: str = "test_entry") -> None:
        self.data = data
        self.entry_id = entry_id
        self.title = "Shady"


class FakeConfigEntriesManager:
    """Real (non-Mock) stand-in for the slice of `hass.config_entries`
    `_get_reconfigure_entry`/`async_update_reload_and_abort` need:
    looking an entry up by id, and recording reload/update calls."""

    def __init__(self, entries: list[FakeConfigEntry] | None = None) -> None:
        self._by_id = {entry.entry_id: entry for entry in (entries or [])}
        self.reloaded_entry_ids: list[str] = []

    def async_get_entry(self, entry_id: str) -> FakeConfigEntry | None:
        return self._by_id.get(entry_id)

    def async_loaded_entries(self, domain: str) -> list[FakeConfigEntry]:
        """`_scan_forecast_solar_domain` (`providers/discovery.py`) calls
        this to find loaded Forecast.Solar config entries — always empty
        here since no test in this file exercises that discovery path
        through a real config entry (the one test that needs a
        `forecast_solar`-shaped candidate injects it directly via
        `flow._candidates`, bypassing discovery entirely)."""
        return []

    def async_update_entry(self, entry: FakeConfigEntry, *, data: dict[str, Any]) -> None:
        entry.data = data


class _FlowHandlerBase:
    """Real (non-Mock) stand-in for the slice of `homeassistant.data_
    entry_flow.FlowHandler` that `config_flow.py` actually calls."""

    hass: Any
    context: dict[str, Any]

    def __init__(self) -> None:
        self.context = {}

    def async_show_form(
        self,
        *,
        step_id: str,
        data_schema: Any = None,
        errors: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> FlowResult:
        return FlowResult(
            type="form", step_id=step_id, data_schema=data_schema, errors=errors or {}
        )

    def async_show_menu(self, *, step_id: str, menu_options: list[str]) -> FlowResult:
        return FlowResult(type="menu", step_id=step_id, menu_options=menu_options)

    def async_create_entry(self, *, title: str, data: dict[str, Any]) -> FlowResult:
        return FlowResult(type="create_entry", title=title, data=data)

    def _get_reconfigure_entry(self) -> FakeConfigEntry:
        """Real HA behavior (since the reconfigure-flow helpers were
        added): looks the entry up via `self.context["entry_id"]`,
        raising if none is set — a flow driven through
        `async_step_reconfigure` without that context is a test-harness
        bug, not a case to silently tolerate."""
        entry_id = self.context["entry_id"]
        entry = self.hass.config_entries.async_get_entry(entry_id)
        assert entry is not None
        return cast(FakeConfigEntry, entry)

    def async_update_reload_and_abort(
        self, entry: FakeConfigEntry, *, data_updates: dict[str, Any]
    ) -> FlowResult:
        """Real HA behavior: a shallow merge into `entry.data` (only the
        top-level keys present in `data_updates` are replaced — anything
        this flow never touched stays exactly as it was), schedules a
        reload, then aborts with `reason="reconfigure_successful"`. A
        `@callback`-style sync method in real HA (like `async_create_
        entry`/`async_show_form`/`async_abort`), not awaited by callers —
        `async_step_finish` below calls it the same, unawaited way."""
        merged = {**entry.data, **data_updates}
        self.hass.config_entries.async_update_entry(entry, data=merged)
        self.hass.config_entries.reloaded_entry_ids.append(entry.entry_id)
        return FlowResult(type="abort", reason="reconfigure_successful")


class ConfigFlow(_FlowHandlerBase):
    """Real (non-Mock) stand-in for `homeassistant.config_entries.
    ConfigFlow` — supports the `domain=` class-creation kwarg real
    `ShadyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN)` uses."""

    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._domain = domain  # type: ignore[attr-defined]


class _EntitySelectorConfig(dict):  # type: ignore[type-arg]
    """Real (non-Mock) stand-in for `homeassistant.helpers.selector.
    EntitySelectorConfig` — a `TypedDict` in real HA, which is a plain
    `dict` at runtime; a thin subclass here only so `isinstance` checks
    (none currently needed) would work if ever added."""


def _entity_selector_config(**kwargs: Any) -> _EntitySelectorConfig:
    return _EntitySelectorConfig(**kwargs)


class _EntitySelector:
    """Real (non-Mock) stand-in for `homeassistant.helpers.selector.
    EntitySelector` — validates/normalizes a submitted value the same
    shape real HA's selector does for `multiple=True` (a list, each
    element coerced to `str`) vs. `multiple=False` (a single `str`).
    Domain/device_class filtering is a frontend (candidate list)
    concern in real HA too — this selector's own `__call__` never
    checks a submitted entity_id against either."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def __call__(self, value: Any) -> Any:
        if self.config.get("multiple", False):
            if not isinstance(value, list):
                raise ValueError("expected a list for a multiple=True EntitySelector")
            return [str(v) for v in value]
        return str(value)


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_data_entry_flow = ModuleType("homeassistant.data_entry_flow")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers.__path__ = []  # mark as a package
    ha_helpers_selector = ModuleType("homeassistant.helpers.selector")

    ha_core.callback = _callback  # type: ignore[attr-defined]
    ha_config_entries.ConfigFlow = ConfigFlow  # type: ignore[attr-defined]
    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]
    ha_data_entry_flow.FlowResult = FlowResult  # type: ignore[attr-defined]
    ha_helpers_selector.EntitySelector = _EntitySelector  # type: ignore[attr-defined]
    ha_helpers_selector.EntitySelectorConfig = _entity_selector_config  # type: ignore[attr-defined]
    ha_helpers.selector = ha_helpers_selector  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.data_entry_flow = ha_data_entry_flow  # type: ignore[attr-defined]
    ha.helpers = ha_helpers  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.data_entry_flow"] = ha_data_entry_flow
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.selector"] = ha_helpers_selector


_install_ha_stub()

# providers/base.py, providers/normalize.py, providers/discovery.py must
# be loaded (and registered under their real dotted names) before
# config_flow.py, which does `from .providers.discovery import ...` —
# same multi-module load-order convention `test_forecast_adjust.py`
# already relies on.
_load("providers/base.py", "shady.providers.base")
_normalize_mod = _load("providers/normalize.py", "shady.providers.normalize")
_discovery_mod = _load("providers/discovery.py", "shady.providers.discovery")
_const_mod = _load("const.py", "shady.const")
_flow_mod = _load("config_flow.py", "shady.config_flow")

ShadyConfigFlow = _flow_mod.ShadyConfigFlow
CONF_STRINGS = _const_mod.CONF_STRINGS
BASELINE_CANDIDATE_MANUAL = _const_mod.BASELINE_CANDIDATE_MANUAL
BASELINE_CANDIDATE_NONE = _const_mod.BASELINE_CANDIDATE_NONE
STRING_SETTINGS_HUB_DONE = _const_mod.STRING_SETTINGS_HUB_DONE


class FakeState:
    """A real (non-Mock) stand-in for `homeassistant.core.State`."""

    def __init__(self, entity_id: str, attributes: dict[str, object]) -> None:
        self.entity_id = entity_id
        self.state = "unknown"
        self.attributes = attributes


class FakeStates:
    """A real (non-Mock) stand-in for `homeassistant.core.StateMachine`."""

    def __init__(self, states: list[FakeState] | None = None) -> None:
        self._states = states or []

    def async_all(self, domain: str | None = None) -> list[FakeState]:
        if domain is None:
            return list(self._states)
        return [s for s in self._states if s.entity_id.startswith(f"{domain}.")]

    def get(self, entity_id: str) -> FakeState | None:
        for state in self._states:
            if state.entity_id == entity_id:
                return state
        return None


class FakeHomeAssistant:
    """A real (non-Mock) stand-in for `homeassistant.core.HomeAssistant`."""

    def __init__(
        self,
        states: list[FakeState] | None = None,
        entries: list[FakeConfigEntry] | None = None,
    ) -> None:
        self.states = FakeStates(states)
        self.config_entries = FakeConfigEntriesManager(entries)


_FORECAST_SOLAR_LIKE = FakeState(
    "sensor.forecast_solar_estimate",
    {"wh_period": {"2026-01-01T10:00:00+00:00": 500.0, "2026-01-01T10:05:00+00:00": 520.0}},
)

_YIELD_ENTITY = "sensor.string_a_yield"


def flow_call(step: Any, user_input: dict[str, Any] | None) -> Any:
    """Drive an `async def async_step_*` coroutine synchronously, via the
    shared `_run` (`asyncio.run`) wrapper `tests/support.py` provides."""
    return _run(step(user_input))


def _defaults_from_schema(schema: Any) -> dict[str, Any]:
    """Extract every field's default value from a `voluptuous.Schema`,
    exactly what a form submitted "as-is" (accepting every default)
    would send back. Every field in every schema this module builds
    always specifies a `default=` (see `config_flow.py`), so
    `vol.UNDEFINED` is never actually hit here — the check is
    defensive only.
    """
    import voluptuous as vol

    defaults: dict[str, Any] = {}
    for key in schema.schema:
        if key.default is vol.UNDEFINED:
            continue
        defaults[str(key)] = key.default()
    return defaults


def _field_names(schema: Any) -> set[str]:
    return {str(key) for key in schema.schema}


def _in_choices(schema: Any, field_name: str) -> dict[str, str]:
    validator = schema.schema[_key(schema, field_name)]
    container: dict[str, str] = validator.container
    return container


def _key(schema: Any, name: str) -> Any:
    for key in schema.schema:
        if str(key) == name:
            return key
    raise AssertionError(f"no such field: {name}")


def _new_flow(hass: FakeHomeAssistant) -> Any:
    flow = ShadyConfigFlow()
    flow.hass = hass
    return flow


def _run_baseline(flow: Any, *, overrides: dict[str, Any] | None = None) -> Any:
    form = flow_call(flow.async_step_baseline, None)
    defaults = _defaults_from_schema(form["data_schema"])
    defaults.update(overrides or {})
    return flow_call(flow.async_step_baseline, defaults)


def _run_strings(flow: Any, entity_ids: list[str]) -> Any:
    return flow_call(flow.async_step_strings, {CONF_STRINGS: entity_ids})


def _finish_hub_immediately(flow: Any) -> Any:
    """Submit `string_settings_hub` with its "Done" default, without
    editing any string — used by tests that only care about steps
    after the hub."""
    hub_form = flow_call(flow.async_step_string_settings_hub, None)
    defaults = _defaults_from_schema(hub_form["data_schema"])
    return flow_call(flow.async_step_string_settings_hub, defaults)


def _run_regression_tuning(flow: Any, *, overrides: dict[str, Any] | None = None) -> Any:
    form = flow_call(flow.async_step_regression_tuning, None)
    defaults = _defaults_from_schema(form["data_schema"])
    defaults.update(overrides or {})
    return flow_call(flow.async_step_regression_tuning, defaults)


def _run_advanced_optional(flow: Any, *, overrides: dict[str, Any] | None = None) -> Any:
    form = flow_call(flow.async_step_advanced_optional, None)
    defaults = _defaults_from_schema(form["data_schema"])
    defaults.update(overrides or {})
    return flow_call(flow.async_step_advanced_optional, defaults)


def _finish_minimal_flow(
    hass: FakeHomeAssistant, *, string_entity_ids: list[str] | None = None
) -> dict[str, Any]:
    """Drive `ShadyConfigFlow` through a full, minimal (all-defaults)
    `async_step_user` run and return the resulting entry data — the
    shared setup several acceptance-criteria tests build on. Defaults to
    one string (`_YIELD_ENTITY`) unless `string_entity_ids` says
    otherwise (`[]` for the zero-strings case)."""
    entity_ids = [_YIELD_ENTITY] if string_entity_ids is None else string_entity_ids
    flow = _new_flow(hass)
    flow_call(flow.async_step_user, None)  # renders `baseline`
    result = _run_baseline(flow)
    assert result["step_id"] == "strings"
    result = _run_strings(flow, entity_ids)
    if entity_ids:
        assert result["step_id"] == "string_settings_hub"
        result = _finish_hub_immediately(flow)
    assert result["step_id"] == "regression_tuning"
    result = _run_regression_tuning(flow)
    assert result["step_id"] == "advanced_optional"
    result = _run_advanced_optional(flow)
    assert result["type"] == "create_entry"
    data: dict[str, Any] = result["data"]
    return data


# -- Linear first-setup flow (`async_step_user`) -------------------------


class TestLinearStepOrder:
    """Given a fresh setup, when it proceeds, the step order is exactly
    `baseline` -> `strings` -> (hub/edit loop, skipped if zero strings)
    -> `regression_tuning` -> `advanced_optional` -> `create_entry`."""

    def test_full_order_with_one_string(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        result = flow_call(flow.async_step_user, None)
        assert result["step_id"] == "baseline"
        result = _run_baseline(flow)
        assert result["step_id"] == "strings"
        result = _run_strings(flow, [_YIELD_ENTITY])
        assert result["step_id"] == "string_settings_hub"
        result = _finish_hub_immediately(flow)
        assert result["step_id"] == "regression_tuning"
        result = _run_regression_tuning(flow)
        assert result["step_id"] == "advanced_optional"
        result = _run_advanced_optional(flow)
        assert result["type"] == "create_entry"
        assert result["title"] == "Shady"

    def test_zero_strings_skips_the_hub_entirely(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        result = _run_strings(flow, [])
        # hub is skipped entirely -- goes straight to regression_tuning:
        assert result["step_id"] == "regression_tuning"


class TestStringsStepSchema:
    """Given the `strings` step, when its schema is built, it is exactly
    one `selector.EntitySelector` field (`domain="sensor"`,
    `device_class=["power", "energy"]`, `multiple=True`) -- no other
    field, and no separate per-string "add" step exists anywhere."""

    def test_exactly_one_entity_selector_field(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        result = _run_baseline(flow)
        assert result["step_id"] == "strings"
        schema = result["data_schema"]
        assert _field_names(schema) == {CONF_STRINGS}
        validator = schema.schema[_key(schema, CONF_STRINGS)]
        assert isinstance(validator, _EntitySelector)
        assert validator.config["domain"] == "sensor"
        assert validator.config["device_class"] == ["power", "energy"]
        assert validator.config["multiple"] is True

    def test_no_add_string_method_exists(self) -> None:
        assert not hasattr(ShadyConfigFlow, "async_step_add_string")
        assert not hasattr(ShadyConfigFlow, "async_step_add_string_advanced")
        assert not hasattr(ShadyConfigFlow, "async_step_add_another")


class TestStringSettingsHubDispatch:
    """Given at least one entity was picked in `strings`, when
    `string_settings_hub` is entered, it presents a choice of every
    picked entity_id (label: name if set this session, else entity_id)
    plus "Done"; picking an entity_id enters `string_settings_edit` for
    it and returns to this same hub afterward; picking "Done" proceeds
    to `regression_tuning`."""

    def test_hub_choices_default_to_entity_id_label(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        hub_form = flow_call(flow.async_step_string_settings_hub, None)
        choices = _in_choices(hub_form["data_schema"], "entity_id")
        assert choices[_YIELD_ENTITY] == _YIELD_ENTITY  # no name set yet
        assert choices[STRING_SETTINGS_HUB_DONE] == "Done"

    def test_editing_a_string_then_returns_to_the_hub(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        assert result["step_id"] == "string_settings_edit"
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["name"] = "Dach Süd"
        result = flow_call(flow.async_step_string_settings_edit, edit_defaults)
        assert result["step_id"] == "string_settings_hub"
        # label now reflects the freshly-set name:
        choices = _in_choices(result["data_schema"], "entity_id")
        assert choices[_YIELD_ENTITY] == "Dach Süd"

    def test_done_proceeds_to_regression_tuning(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = _finish_hub_immediately(flow)
        assert result["step_id"] == "regression_tuning"


class TestStringSettingsEditSchema:
    """Given `string_settings_edit` for a specific entity_id, its schema
    contains exactly the documented fields, with no "configure advanced
    corrections?" gate of any kind -- every field always shown."""

    def test_exact_field_set(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        field_names = _field_names(result["data_schema"])
        assert field_names == {
            "name",
            "baseline_override",
            "temperature_source_entity_id",
            "converter_limit_w",
            "temperature_coefficient_pct_per_c",
            "rated_dc_capacity_wp",
        }
        assert "configure_advanced" not in field_names
        assert "actual_yield_entity_id" not in field_names

    def test_baseline_override_dropdown_has_distinct_use_global_sentinel(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        choices = _in_choices(result["data_schema"], "baseline_override")
        assert choices[BASELINE_CANDIDATE_NONE] == "Use global default"
        assert choices[BASELINE_CANDIDATE_MANUAL] == "None of these (enter manually)"
        assert BASELINE_CANDIDATE_NONE != BASELINE_CANDIDATE_MANUAL


class TestRemovingAStringDiscardsItsSettings:
    """Given an entity was picked, given `string_settings_edit` was used
    to configure it, when that same entity is later removed from
    `strings` (same session, before the flow's final step),
    `string_settings_hub` no longer offers it and its settings are
    absent from the flow's eventual result entirely."""

    def test_discarded_on_removal(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        second_entity = "sensor.string_b_yield"
        _run_strings(flow, [_YIELD_ENTITY, second_entity])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["name"] = "Dach Süd"
        edit_defaults["converter_limit_w"] = 5000.0
        flow_call(flow.async_step_string_settings_edit, edit_defaults)
        # now remove the second (never-edited) entity from the selection:
        result = _run_strings(flow, [_YIELD_ENTITY])
        assert result["step_id"] == "string_settings_hub"
        choices = _in_choices(result["data_schema"], "entity_id")
        assert second_entity not in choices
        result = _finish_hub_immediately(flow)
        result = _run_regression_tuning(flow)
        final = _run_advanced_optional(flow)
        strings = final["data"][CONF_STRINGS]
        assert second_entity not in strings
        assert strings[_YIELD_ENTITY]["name"] == "Dach Süd"  # first string's edit survives

    def test_readding_within_the_same_session_starts_fresh(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["name"] = "Dach Süd"
        flow_call(flow.async_step_string_settings_edit, edit_defaults)
        _run_strings(flow, [])  # remove it
        result = _run_strings(flow, [_YIELD_ENTITY])  # re-add, same session
        assert result["step_id"] == "string_settings_hub"
        choices = _in_choices(result["data_schema"], "entity_id")
        assert choices[_YIELD_ENTITY] == _YIELD_ENTITY  # back to entity_id, name not retained


class TestRegressionTuningSchema:
    """Given `regression_tuning`, its schema contains exactly the
    documented six fields -- the `baseline`/`temperature_aware` pair and
    every `advanced_optional` field are absent."""

    def test_exact_field_set(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [])
        result = flow_call(flow.async_step_regression_tuning, None)
        assert _field_names(result["data_schema"]) == {
            "window_days",
            "regression_method",
            "smoothing_radius",
            "neighbor_fitting_cutoff",
            "recency_decay_max",
            "clipping_threshold",
        }

    def test_documented_defaults(self) -> None:
        hass = FakeHomeAssistant([])
        data = _finish_minimal_flow(hass, string_entity_ids=[])
        assert data["window_days"] == 28
        assert data["regression_method"] == "wls2"
        assert data["smoothing_radius"] == 1
        assert data["neighbor_fitting_cutoff"] == 0.25
        assert data["recency_decay_max"] == 0.5
        assert data["clipping_threshold"] == 0.98


class TestAdvancedOptionalSchema:
    """Given `advanced_optional`, its schema contains exactly the
    documented eight fields."""

    def test_exact_field_set(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [])
        _run_regression_tuning(flow)
        result = flow_call(flow.async_step_advanced_optional, None)
        assert _field_names(result["data_schema"]) == {
            "default_temperature_source",
            "max_uplift_c",
            "weather_forecast_temperature_entity",
            "temperature_regression_method",
            "intraday_correction_mode",
            "intraday_correction_cutoff",
            "window_slots",
            "ramp_slots",
        }

    def test_documented_defaults(self) -> None:
        hass = FakeHomeAssistant([])
        data = _finish_minimal_flow(hass, string_entity_ids=[])
        assert data["max_uplift_c"] == 25
        assert data["temperature_regression_method"] == "wls2"
        assert data["intraday_correction_mode"] == "off"
        assert data["intraday_correction_cutoff"] == 0.10
        assert data["window_slots"] == 24
        assert data["ramp_slots"] == 12


# -- Menu-driven reconfigure (`async_step_reconfigure`) -------------------


def _existing_entry() -> FakeConfigEntry:
    return FakeConfigEntry(
        data={
            "baseline_entity_id": "sensor.forecast_solar_estimate",
            "baseline_attribute": "wh_period",
            "baseline_shape": "sensor_dict",
            "baseline_history_entity_id": None,
            "temperature_aware": False,
            "window_days": 28,
            "regression_method": "wls2",
            "smoothing_radius": 1,
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
                _YIELD_ENTITY: {
                    "name": "Dach Süd (old name)",
                    "baseline_entity_id": None,
                    "baseline_attribute": None,
                    "baseline_shape": None,
                    "baseline_history_entity_id": None,
                    "temperature_aware": False,
                    "converter_limit_w": None,
                    "temperature_source_entity_id": None,
                    "temperature_coefficient_pct_per_c": -0.4,
                    "rated_dc_capacity_wp": None,
                }
            },
        },
        entry_id="test_entry",
    )


def _start_reconfigure(hass: FakeHomeAssistant, entry: FakeConfigEntry) -> Any:
    flow = _new_flow(hass)
    flow.context = {"entry_id": entry.entry_id}
    return flow


class TestReconfigureMenu:
    """Given a person opens reconfigure on an existing entry, the flow
    shows an `async_show_menu` with exactly the five documented options
    -- not the linear sequence."""

    def test_shows_exactly_the_documented_menu_options(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        result = flow_call(flow.async_step_reconfigure, None)
        assert result["type"] == "menu"
        assert result["menu_options"] == [
            "baseline",
            "strings",
            "regression_tuning",
            "advanced_optional",
            "finish",
        ]


class TestReconfigureSectionsReturnToMenu:
    """Given any one menu option other than "Save & Finish" is chosen,
    when its step (or, for "Strings", its hub/loop sequence) is
    submitted, the flow returns to this same top-level menu -- never
    proceeds onward to another section linearly."""

    def test_baseline_returns_to_menu(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        result = _run_baseline(flow)
        assert result["type"] == "menu"

    def test_strings_with_zero_picked_returns_to_menu_directly(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        result = _run_strings(flow, [])
        assert result["type"] == "menu"

    def test_strings_then_hub_done_returns_to_menu_not_regression_tuning(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        result = _run_strings(flow, [_YIELD_ENTITY])
        assert result["step_id"] == "string_settings_hub"
        result = _finish_hub_immediately(flow)
        assert result["type"] == "menu"

    def test_regression_tuning_returns_to_menu(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        result = _run_regression_tuning(flow)
        assert result["type"] == "menu"

    def test_advanced_optional_returns_to_menu_not_create_entry(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        result = _run_advanced_optional(flow)
        assert result["type"] == "menu"


class TestReconfigurePrefill:
    """Given any step reached from the menu, every field is pre-filled
    from the existing config entry's current data -- global settings,
    and (for "Strings") the currently-configured entity_ids and each
    one's existing per-string settings."""

    def test_baseline_prefilled(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        form = flow_call(flow.async_step_baseline, None)
        defaults = _defaults_from_schema(form["data_schema"])
        assert defaults["baseline_candidate"] == "0"  # matches the discovered candidate

    def test_regression_tuning_prefilled(self) -> None:
        entry = _existing_entry()
        entry.data["window_days"] = 21
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        form = flow_call(flow.async_step_regression_tuning, None)
        defaults = _defaults_from_schema(form["data_schema"])
        assert defaults["window_days"] == 21

    def test_strings_prefilled_with_existing_entity_ids(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        form = flow_call(flow.async_step_strings, None)
        defaults = _defaults_from_schema(form["data_schema"])
        assert defaults[CONF_STRINGS] == [_YIELD_ENTITY]

    def test_string_settings_edit_prefilled_with_existing_name(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        _run_strings(flow, [_YIELD_ENTITY])
        form = flow_call(flow.async_step_string_settings_hub, None)
        choices = _in_choices(form["data_schema"], "entity_id")
        assert choices[_YIELD_ENTITY] == "Dach Süd (old name)"
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        assert edit_defaults["name"] == "Dach Süd (old name)"


class TestReconfigureSaveAndFinish:
    """Given "Save & Finish" is chosen, the flow calls
    `async_update_reload_and_abort` with the accumulated changes;
    `entry.data` reflects every changed value, and no data is lost for
    a section the person never opened."""

    def test_changed_and_untouched_sections_both_reflected(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        # only change regression_tuning -- never open baseline/strings/advanced_optional:
        result = _run_regression_tuning(flow, overrides={"window_days": 14})
        assert result["type"] == "menu"
        final = flow_call(flow.async_step_finish, None)
        assert final["type"] == "abort"
        assert final["reason"] == "reconfigure_successful"
        assert entry.data["window_days"] == 14  # changed section
        assert entry.data["max_uplift_c"] == 25  # untouched section, unchanged
        assert entry.data[CONF_STRINGS][_YIELD_ENTITY]["name"] == "Dach Süd (old name)"

    def test_reloads_the_entry(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        _run_regression_tuning(flow)
        flow_call(flow.async_step_finish, None)
        assert hass.config_entries.reloaded_entry_ids == [entry.entry_id]

    def test_string_edit_is_reflected_after_save(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["name"] = "Dach Süd"
        flow_call(flow.async_step_string_settings_edit, edit_defaults)
        _finish_hub_immediately(flow)
        flow_call(flow.async_step_finish, None)
        assert entry.data[CONF_STRINGS][_YIELD_ENTITY]["name"] == "Dach Süd"


class TestReconfigureAbandoned:
    """Given the reconfigure flow is abandoned before "Save & Finish",
    the existing config entry is completely untouched."""

    def test_visiting_sections_without_finishing_leaves_entry_untouched(self) -> None:
        entry = _existing_entry()
        original_window_days = entry.data["window_days"]
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        _run_regression_tuning(flow, overrides={"window_days": 3})
        # ... flow simply never reaches async_step_finish ...
        assert entry.data["window_days"] == original_window_days


# -- Cross-cutting ---------------------------------------------------------


class TestOptionsFlowRemoved:
    """Given `ShadyOptionsFlow` is removed, `async_get_options_flow` is
    removed too -- not left pointing at a deleted class."""

    def test_no_options_flow_class_or_hook_remains(self) -> None:
        assert not hasattr(_flow_mod, "ShadyOptionsFlow")
        assert not hasattr(ShadyConfigFlow, "async_get_options_flow")


class TestNoUniqueIdScheme:
    """Given this integration defines no `unique_id` scheme,
    `async_step_reconfigure` does not call
    `async_set_unique_id`/`_abort_if_unique_id_mismatch`."""

    def test_reconfigure_entry_has_no_unique_id_methods_stubbed_or_called(self) -> None:
        # The stub `ConfigFlow` base class deliberately has no
        # `async_set_unique_id`/`_abort_if_unique_id_mismatch` at all --
        # if `async_step_reconfigure` called either, this would raise
        # `AttributeError` rather than silently no-op.
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        result = flow_call(flow.async_step_reconfigure, None)  # must not raise
        assert result["type"] == "menu"


class TestNoLatLongElevationField:
    """Given the completed flow, no latitude/longitude/elevation field
    is presented anywhere (ADR-001 §1)."""

    def test_no_geo_fields_in_any_step_schema(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        baseline_form = flow_call(flow.async_step_baseline, None)
        _run_baseline(flow)
        strings_form = flow_call(flow.async_step_strings, None)
        _run_strings(flow, [_YIELD_ENTITY])
        edit_result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        regression_result = _finish_hub_immediately(flow)
        advanced_result = _run_regression_tuning(flow)

        geo_terms = {"latitude", "longitude", "elevation"}
        for form in (
            baseline_form,
            strings_form,
            edit_result,
            regression_result,
            advanced_result,
        ):
            field_names = _field_names(form["data_schema"])
            assert not (field_names & geo_terms)


class TestBaselineOverrideImpliesTemperatureAware:
    """Given a baseline candidate override set for a string, that string
    is automatically treated as temperature-aware -- no separate flag is
    ever asked in `string_settings_edit`'s own schema (ADR-003b §1c)."""

    def test_override_sets_temperature_aware(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["baseline_override"] = "0"  # the one discovered candidate
        field_names = _field_names(result["data_schema"])
        assert "temperature_aware" not in field_names
        flow_call(flow.async_step_string_settings_edit, edit_defaults)
        _finish_hub_immediately(flow)
        _run_regression_tuning(flow)
        final = _run_advanced_optional(flow)
        strings = final["data"][CONF_STRINGS]
        assert strings[_YIELD_ENTITY]["temperature_aware"] is True
        assert strings[_YIELD_ENTITY]["baseline_entity_id"] == "sensor.forecast_solar_estimate"


class TestBaselineHistoryEntityIdCarriedThrough:
    """ADR-009 §1c Amendment / ADR-012 §2a Amendment: a `forecast_solar`
    -shaped baseline candidate's linked history entity carries through
    both the global `baseline` step and a per-string override."""

    _HISTORY_ENTITY = "sensor.power_production_now"

    @staticmethod
    def _forecast_solar_candidate() -> Any:
        BaselineCandidate = _discovery_mod.BaselineCandidate
        return BaselineCandidate(
            entity_id="fs_entry_1",
            attribute="wh_period",
            shape="forecast_solar",
            label="Forecast.Solar",
            score=100,
            history_entity_id=TestBaselineHistoryEntityIdCarriedThrough._HISTORY_ENTITY,
        )

    def test_global_baseline_stores_history_entity_id(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow._candidates = [self._forecast_solar_candidate()]
        result = _run_baseline(flow, overrides={"baseline_candidate": "0"})
        assert result["step_id"] == "strings"
        assert flow._data["baseline_entity_id"] == "fs_entry_1"
        assert flow._data["baseline_history_entity_id"] == self._HISTORY_ENTITY

    def test_string_override_stores_history_entity_id(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow._candidates = [self._forecast_solar_candidate()]
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["baseline_override"] = "0"
        flow_call(flow.async_step_string_settings_edit, edit_defaults)
        assert flow._strings[_YIELD_ENTITY]["baseline_history_entity_id"] == self._HISTORY_ENTITY


class TestManualBaselineShape:
    """`TASK-0009-patch-1`: manual baseline entry needs a shape selector
    so `BaselineProvider` can parse it at all."""

    def test_manual_shape_field_present_and_stored(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        form = flow_call(flow.async_step_baseline, None)
        field_names = _field_names(form["data_schema"])
        assert "baseline_manual_shape" in field_names
        flow_call(flow.async_step_user, None)
        result = _run_baseline(
            flow, overrides={"baseline_manual_entity_id": "sensor.manual_forecast"}
        )
        assert result["step_id"] == "strings"
        assert flow._data["baseline_entity_id"] == "sensor.manual_forecast"
        assert flow._data["baseline_shape"] == "sensor_dict"

    def test_manual_entry_stores_none_history_entity_id(self) -> None:
        hass = FakeHomeAssistant([])
        data = _finish_minimal_flow(hass, string_entity_ids=[])
        assert data["baseline_entity_id"] is None
        assert data["baseline_history_entity_id"] is None


class TestRatedCapacitySkipsDerating:
    """Given `string_settings_edit`'s "Rated DC capacity" field left
    empty, the stored config reflects "skip derating for this string"
    (ADR-003c §5 / ADR-010) -- i.e. the stored value is `None`."""

    def test_empty_rated_capacity_stores_none(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        flow_call(flow.async_step_user, None)
        _run_baseline(flow)
        _run_strings(flow, [_YIELD_ENTITY])
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["temperature_source_entity_id"] = "sensor.ambient_temp"
        # rated_dc_capacity_wp left at its default (blank string sentinel)
        flow_call(flow.async_step_string_settings_edit, edit_defaults)
        _finish_hub_immediately(flow)
        _run_regression_tuning(flow)
        final = _run_advanced_optional(flow)
        strings = final["data"][CONF_STRINGS]
        assert strings[_YIELD_ENTITY]["rated_dc_capacity_wp"] is None
        assert strings[_YIELD_ENTITY]["temperature_source_entity_id"] == "sensor.ambient_temp"


class TestRecencyDecayMax:
    """`TASK-0009-patch-2`: `recency_decay_max` (ADR-001 §4a, ADR-010) --
    the maximum downweight applied to the oldest day in the rolling
    training window -- now lives on `regression_tuning`."""

    def test_default_applies_when_absent(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        form = flow_call(flow.async_step_regression_tuning, None)
        assert "recency_decay_max" in _field_names(form["data_schema"])
        defaults = _defaults_from_schema(form["data_schema"])
        assert defaults["recency_decay_max"] == 0.5

    def test_zero_is_accepted(self) -> None:
        hass = FakeHomeAssistant([])
        flow = _new_flow(hass)
        result = _run_regression_tuning(flow, overrides={"recency_decay_max": 0.0})
        assert result["step_id"] == "advanced_optional"

    def test_round_trips_through_reconfigure(self) -> None:
        entry = _existing_entry()
        entry.data["recency_decay_max"] = 0.75
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)
        form = flow_call(flow.async_step_regression_tuning, None)
        assert _defaults_from_schema(form["data_schema"])["recency_decay_max"] == 0.75


class TestReconfigureEditsStringsAndGlobalSettings:
    """Given reconfigure, when invoked on an existing config entry, it
    can add/edit strings and change any global setting."""

    def test_edit_existing_string_and_global_setting(self) -> None:
        entry = _existing_entry()
        hass = FakeHomeAssistant([], entries=[entry])
        flow = _start_reconfigure(hass, entry)
        flow_call(flow.async_step_reconfigure, None)

        result = _run_regression_tuning(flow, overrides={"window_days": 21})
        assert result["type"] == "menu"

        _run_strings(flow, [_YIELD_ENTITY])
        hub_form = flow_call(flow.async_step_string_settings_hub, None)
        choices = _in_choices(hub_form["data_schema"], "entity_id")
        assert choices[_YIELD_ENTITY] == "Dach Süd (old name)"  # pre-filled for editing
        result = flow_call(flow.async_step_string_settings_hub, {"entity_id": _YIELD_ENTITY})
        edit_defaults = _defaults_from_schema(result["data_schema"])
        edit_defaults["name"] = "Dach Süd"  # edit it
        flow_call(flow.async_step_string_settings_edit, edit_defaults)
        _finish_hub_immediately(flow)

        final = flow_call(flow.async_step_finish, None)
        assert final["reason"] == "reconfigure_successful"
        assert entry.data["window_days"] == 21
        assert entry.data[CONF_STRINGS][_YIELD_ENTITY]["name"] == "Dach Süd"
