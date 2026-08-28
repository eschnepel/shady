"""Tests for `config_flow.py` (ADR-010).

`config_flow.py` is HA-facing (it subclasses `homeassistant.config_entries
.ConfigFlow`/`OptionsFlow` for real, not just under `TYPE_CHECKING`) — it
is outside ADR-000 §6's zero-mocking pure tier, and the project declares
no `homeassistant` runtime dependency (it is supplied by the host HA
instance, per `manifest.json`'s `requirements`). Rather than installing
the full `homeassistant` package (a large, unrelated dependency this
project's own `pyproject.toml` deliberately does not declare), this file
registers a small, hand-written, real (non-`Mock`) stand-in for exactly
the `homeassistant.core`/`config_entries`/`data_entry_flow` surface
`config_flow.py` touches, directly in `sys.modules` — the same
"real stand-in, not a mock" philosophy `FakeHomeAssistant`/`FakeState`
already establish in `test_providers_discovery.py`, extended to the one
additional thing an HA-facing module needs: real classes to subclass.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class FlowResult(dict):  # type: ignore[type-arg]
    """Real (non-Mock) stand-in for `homeassistant.data_entry_flow`'s
    `FlowResult` — a plain dict carries every key this project's flow
    steps set (`type`, `step_id`, `data_schema`, `errors`, `title`,
    `data`)."""


class _FlowHandlerBase:
    """Real (non-Mock) stand-in for the slice of `homeassistant.data_
    entry_flow.FlowHandler` that `config_flow.py` actually calls."""

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

    def async_create_entry(self, *, title: str, data: dict[str, Any]) -> FlowResult:
        return FlowResult(type="create_entry", title=title, data=data)


class ConfigFlow(_FlowHandlerBase):
    """Real (non-Mock) stand-in for `homeassistant.config_entries.
    ConfigFlow` — supports the `domain=` class-creation kwarg real
    `ShadyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN)` uses."""

    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._domain = domain  # type: ignore[attr-defined]


class OptionsFlow(_FlowHandlerBase):
    """Real (non-Mock) stand-in for `homeassistant.config_entries.
    OptionsFlow`."""


def _callback(func: Any) -> Any:
    """Real (non-Mock) stand-in for `homeassistant.core.callback` — a
    plain identity decorator is a faithful stand-in for our purposes
    (ADR-000 §2 already documents this decorator as pure mypy-noise
    surface, nothing behavioral we need to reproduce here)."""
    return func


class FakeConfigEntry:
    """Real (non-Mock) stand-in for `homeassistant.config_entries.
    ConfigEntry` — holds only `data`, the one attribute `ShadyOptionsFlow`
    reads."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data
        self.entry_id = "test_entry"
        self.title = "Shady"


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_data_entry_flow = ModuleType("homeassistant.data_entry_flow")

    ha_core.callback = _callback  # type: ignore[attr-defined]
    ha_config_entries.ConfigFlow = ConfigFlow  # type: ignore[attr-defined]
    ha_config_entries.OptionsFlow = OptionsFlow  # type: ignore[attr-defined]
    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]
    ha_data_entry_flow.FlowResult = FlowResult  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.data_entry_flow = ha_data_entry_flow  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.data_entry_flow"] = ha_data_entry_flow


_install_ha_stub()

# providers/base.py, providers/normalize.py, providers/discovery.py must
# be loaded (and registered under their real dotted names) before
# config_flow.py, which does `from .providers.discovery import ...` —
# same multi-module load-order convention `test_forecast_adjust.py`
# already relies on.
_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_discovery_mod = _load("providers/discovery.py", "shady.providers.discovery")
_const_mod = _load("const.py", "shady.const")
_flow_mod = _load("config_flow.py", "shady.config_flow")

ShadyConfigFlow = _flow_mod.ShadyConfigFlow
ShadyOptionsFlow = _flow_mod.ShadyOptionsFlow
CONF_STRINGS = _const_mod.CONF_STRINGS
BASELINE_CANDIDATE_MANUAL = _const_mod.BASELINE_CANDIDATE_MANUAL


class FakeState:
    """A real (non-Mock) stand-in for `homeassistant.core.State`."""

    def __init__(self, entity_id: str, attributes: dict[str, object]) -> None:
        self.entity_id = entity_id
        self.state = "unknown"
        self.attributes = attributes


class FakeStates:
    """A real (non-Mock) stand-in for `homeassistant.core.StateMachine`."""

    def __init__(self, states: list[FakeState]) -> None:
        self._states = states

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

    def __init__(self, states: list[FakeState] | None = None) -> None:
        self.states = FakeStates(states or [])


_FORECAST_SOLAR_LIKE = FakeState(
    "sensor.forecast_solar_estimate",
    {"wh_period": {"2026-01-01T10:00:00+00:00": 500.0, "2026-01-01T10:05:00+00:00": 520.0}},
)


def _finish_minimal_flow(hass: FakeHomeAssistant) -> dict[str, Any]:
    """Drive `ShadyConfigFlow` through a full, minimal (all-defaults,
    one string, no advanced corrections) run and return the resulting
    entry data — the shared setup several acceptance-criteria tests
    build on.
    """
    flow = ShadyConfigFlow()
    flow.hass = hass
    settings_form = flow_call(flow.async_step_settings, None)
    settings_defaults = _defaults_from_schema(settings_form["data_schema"])
    result = flow_call(flow.async_step_settings, settings_defaults)
    assert result["step_id"] == "add_string"
    add_string_defaults = _defaults_from_schema(result["data_schema"])
    add_string_defaults["name"] = "Dach Süd"
    add_string_defaults["actual_yield_entity_id"] = "sensor.string_a_yield"
    add_string_defaults["configure_advanced"] = False
    result = flow_call(flow.async_step_add_string, add_string_defaults)
    assert result["step_id"] == "add_another"
    add_another_defaults = _defaults_from_schema(result["data_schema"])
    add_another_defaults["add_another"] = False
    result = flow_call(flow.async_step_add_another, add_another_defaults)
    assert result["type"] == "create_entry"
    data: dict[str, Any] = result["data"]
    return data


def _accept_settings_defaults(flow: Any) -> Any:
    """Render the `settings` step, then immediately resubmit it with
    every field left at its default — the common first move of most
    tests below, which only care about steps after `settings`.
    """
    settings_form = flow_call(flow.async_step_settings, None)
    return flow_call(flow.async_step_settings, _defaults_from_schema(settings_form["data_schema"]))


def flow_call(step: Any, user_input: dict[str, Any] | None) -> Any:
    """Drive an `async def async_step_*` coroutine synchronously —
    `pytest.ini`'s `asyncio_mode = auto` is for `async def test_*`
    functions; these helpers stay plain `def` since nothing here awaits
    real I/O, so a direct `coroutine.send(None)`-free drive via
    `asyncio.run` keeps every test a fast, ordinary synchronous test.
    """
    import asyncio

    return asyncio.run(step(user_input))


def _defaults_from_schema(schema: Any) -> dict[str, Any]:
    """Extract every field's default value from a `voluptuous.Schema`,
    exactly what a form submitted "as-is" (accepting every default)
    would send back — used to drive the flow through a step "with
    defaults" per the acceptance criteria's own phrasing. Every field
    in every schema this module builds always specifies a `default=`
    (see `config_flow.py`), so `vol.UNDEFINED` is never actually hit
    here — the check is defensive only.
    """
    import voluptuous as vol

    defaults: dict[str, Any] = {}
    for key in schema.schema:
        if key.default is vol.UNDEFINED:
            continue
        defaults[str(key)] = key.default()
    return defaults


class TestSettingsStepDefaults:
    """Given the `settings` step, when submitted with defaults, the
    resulting config-entry data contains exactly ADR-010's documented
    global fields at their documented defaults."""

    def test_documented_defaults_are_stored(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        data = _finish_minimal_flow(hass)
        assert data["window_days"] == 28
        assert data["regression_method"] == "wls2"
        assert data["smoothing_radius"] == 1
        assert data["neighbor_fitting_cutoff"] == 0.25
        assert data["clipping_threshold"] == 0.98
        assert data["max_uplift_c"] == 25
        assert data["temperature_regression_method"] == "wls2"
        assert data["intraday_correction_mode"] == "off"
        assert data["intraday_correction_cutoff"] == 0.10
        assert data["window_slots"] == 24
        assert data["ramp_slots"] == 12


class TestBaselineDropdownDiscovery:
    """Given the global baseline-candidate dropdown, when rendered, it is
    populated by TASK-0003's discovery/scoring function, ranked, with a
    "None of these" manual fallback always present (ADR-009 §3)."""

    def test_discovered_candidate_and_manual_fallback_present(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        flow = ShadyConfigFlow()
        flow.hass = hass
        form = flow_call(flow.async_step_settings, None)
        choices = _in_choices(form["data_schema"], "baseline_candidate")
        assert BASELINE_CANDIDATE_MANUAL in choices
        assert any("forecast_solar_estimate" in label for label in choices.values())

    def test_manual_fallback_present_with_no_candidates(self) -> None:
        hass = FakeHomeAssistant([])
        flow = ShadyConfigFlow()
        flow.hass = hass
        form = flow_call(flow.async_step_settings, None)
        choices = _in_choices(form["data_schema"], "baseline_candidate")
        assert choices == {BASELINE_CANDIDATE_MANUAL: "None of these (enter manually)"}


def _in_choices(schema: Any, field_name: str) -> dict[str, str]:
    validator = schema.schema[_key(schema, field_name)]
    container: dict[str, str] = validator.container
    return container


def _key(schema: Any, name: str) -> Any:
    for key in schema.schema:
        if str(key) == name:
            return key
    raise AssertionError(f"no such field: {name}")


class TestAddStringSkipsAdvanced:
    """Given `add_string` with "Configure advanced corrections?" left
    off, when submitted, the flow proceeds directly to `add_another`,
    skipping `add_string_advanced` entirely."""

    def test_skips_to_add_another(self) -> None:
        hass = FakeHomeAssistant([])
        flow = ShadyConfigFlow()
        flow.hass = hass
        _accept_settings_defaults(flow)
        add_string_form = flow_call(flow.async_step_add_string, None)
        defaults = _defaults_from_schema(add_string_form["data_schema"])
        defaults["name"] = "Dach Süd"
        defaults["actual_yield_entity_id"] = "sensor.string_a_yield"
        defaults["configure_advanced"] = False
        result = flow_call(flow.async_step_add_string, defaults)
        assert result["step_id"] == "add_another"


class TestBaselineOverrideImpliesTemperatureAware:
    """Given `add_string_advanced` with a baseline candidate override set
    for that string, when the flow completes, that string is
    automatically treated as temperature-aware, with no separate flag
    asked (ADR-003b §1c)."""

    def test_override_sets_temperature_aware(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        flow = ShadyConfigFlow()
        flow.hass = hass
        settings_form = flow_call(flow.async_step_settings, None)
        flow_call(flow.async_step_settings, _defaults_from_schema(settings_form["data_schema"]))
        add_string_form = flow_call(flow.async_step_add_string, None)
        defaults = _defaults_from_schema(add_string_form["data_schema"])
        defaults["name"] = "Dach Süd"
        defaults["actual_yield_entity_id"] = "sensor.string_a_yield"
        defaults["baseline_override"] = "0"  # the one discovered candidate
        defaults["configure_advanced"] = False
        result = flow_call(flow.async_step_add_string, defaults)
        add_another_defaults = _defaults_from_schema(result["data_schema"])
        add_another_defaults["add_another"] = False
        final = flow_call(flow.async_step_add_another, add_another_defaults)
        strings = final["data"][CONF_STRINGS]
        assert strings[0]["temperature_aware"] is True
        assert strings[0]["baseline_entity_id"] == "sensor.forecast_solar_estimate"
        # no separate "is this string temperature-aware?" flag is ever
        # asked in the add_string form itself:
        field_names = {str(key) for key in add_string_form["data_schema"].schema}
        assert "temperature_aware" not in field_names


class TestRatedCapacitySkipsDerating:
    """Given `add_string_advanced`'s "Rated DC capacity" field left empty
    for a string on the ambient/weather temperature tier, when the flow
    completes, the stored config reflects "skip derating for this
    string" (ADR-003c §5 / ADR-010) — i.e. the stored value is `None`."""

    def test_empty_rated_capacity_stores_none(self) -> None:
        hass = FakeHomeAssistant([])
        flow = ShadyConfigFlow()
        flow.hass = hass
        _accept_settings_defaults(flow)
        add_string_form = flow_call(flow.async_step_add_string, None)
        defaults = _defaults_from_schema(add_string_form["data_schema"])
        defaults["name"] = "Dach Süd"
        defaults["actual_yield_entity_id"] = "sensor.string_a_yield"
        defaults["configure_advanced"] = True
        result = flow_call(flow.async_step_add_string, defaults)
        assert result["step_id"] == "add_string_advanced"
        advanced_defaults = _defaults_from_schema(result["data_schema"])
        advanced_defaults["temperature_source_entity_id"] = "sensor.ambient_temp"
        # rated_dc_capacity_wp left at its default (blank string sentinel)
        result = flow_call(flow.async_step_add_string_advanced, advanced_defaults)
        add_another_defaults = _defaults_from_schema(result["data_schema"])
        add_another_defaults["add_another"] = False
        final = flow_call(flow.async_step_add_another, add_another_defaults)
        strings = final["data"][CONF_STRINGS]
        assert strings[0]["rated_dc_capacity_wp"] is None
        assert strings[0]["temperature_source_entity_id"] == "sensor.ambient_temp"


class TestNoLatLongElevationField:
    """Given the completed flow, when rendered against ADR-001 §1's
    decision, no latitude/longitude/elevation field is presented
    anywhere."""

    def test_no_geo_fields_in_any_step_schema(self) -> None:
        hass = FakeHomeAssistant([])
        flow = ShadyConfigFlow()
        flow.hass = hass
        settings_form = flow_call(flow.async_step_settings, None)
        flow_call(flow.async_step_settings, _defaults_from_schema(settings_form["data_schema"]))
        add_string_form = flow_call(flow.async_step_add_string, None)
        defaults = _defaults_from_schema(add_string_form["data_schema"])
        defaults["name"] = "Dach Süd"
        defaults["actual_yield_entity_id"] = "sensor.string_a_yield"
        defaults["configure_advanced"] = True
        advanced_form = flow_call(flow.async_step_add_string, defaults)

        geo_terms = {"latitude", "longitude", "elevation"}
        for form in (settings_form, add_string_form, advanced_form):
            field_names = {str(key) for key in form["data_schema"].schema}
            assert not (field_names & geo_terms)


class TestManualBaselineShape:
    """`TASK-0009-patch-1`: manual baseline entry needs a shape selector
    so `BaselineProvider` (TASK-0010) can parse it at all."""

    def test_manual_shape_field_present_and_stored(self) -> None:
        hass = FakeHomeAssistant([])
        flow = ShadyConfigFlow()
        flow.hass = hass
        form = flow_call(flow.async_step_settings, None)
        field_names = {str(key) for key in form["data_schema"].schema}
        assert "baseline_manual_shape" in field_names

        defaults = _defaults_from_schema(form["data_schema"])
        assert defaults["baseline_manual_shape"] == "sensor_dict"
        defaults["baseline_manual_entity_id"] = "sensor.my_forecast"
        defaults["baseline_manual_attribute"] = "hourly"
        defaults["baseline_manual_shape"] = "sensor_list"
        add_string_form = flow_call(flow.async_step_settings, defaults)
        assert add_string_form["step_id"] == "add_string"

        add_string_defaults = _defaults_from_schema(add_string_form["data_schema"])
        add_string_defaults["name"] = "Dach Süd"
        add_string_defaults["actual_yield_entity_id"] = "sensor.string_a_yield"
        add_string_defaults["configure_advanced"] = False
        result = flow_call(flow.async_step_add_string, add_string_defaults)
        add_another_defaults = _defaults_from_schema(result["data_schema"])
        add_another_defaults["add_another"] = False
        final = flow_call(flow.async_step_add_another, add_another_defaults)

        assert final["data"]["baseline_entity_id"] == "sensor.my_forecast"
        assert final["data"]["baseline_shape"] == "sensor_list"

    def test_manual_shape_ignored_when_a_candidate_is_chosen(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        data = _finish_minimal_flow(hass)
        assert data["baseline_entity_id"] == "sensor.forecast_solar_estimate"
        assert data["baseline_shape"] == "sensor_dict"


class TestRecencyDecayMax:
    """`TASK-0009-patch-2`: `recency_decay_max` (ADR-001 §4a, ADR-010) —
    the maximum downweight applied to the oldest day in the rolling
    training window."""

    def test_default_applies_when_absent(self) -> None:
        hass = FakeHomeAssistant([])
        flow = ShadyConfigFlow()
        flow.hass = hass
        form = flow_call(flow.async_step_settings, None)
        field_names = {str(key) for key in form["data_schema"].schema}
        assert "recency_decay_max" in field_names
        defaults = _defaults_from_schema(form["data_schema"])
        assert defaults["recency_decay_max"] == 0.5

    def test_round_trips_through_options_flow_prefill(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        data = _finish_minimal_flow(hass)
        assert data["recency_decay_max"] == 0.5

        entry = FakeConfigEntry(data=data)
        options_flow = ShadyOptionsFlow()
        options_flow.hass = hass
        options_flow.config_entry = entry
        settings_form = flow_call(options_flow.async_step_init, None)
        settings_defaults = _defaults_from_schema(settings_form["data_schema"])
        assert settings_defaults["recency_decay_max"] == 0.5
        settings_defaults["recency_decay_max"] = 0.75
        result = flow_call(options_flow.async_step_settings, settings_defaults)
        add_string_defaults = _defaults_from_schema(result["data_schema"])
        add_string_defaults["configure_advanced"] = False
        result = flow_call(options_flow.async_step_add_string, add_string_defaults)
        add_another_defaults = _defaults_from_schema(result["data_schema"])
        add_another_defaults["add_another"] = False
        final = flow_call(options_flow.async_step_add_another, add_another_defaults)
        assert final["data"]["recency_decay_max"] == 0.75

    def test_zero_is_accepted(self) -> None:
        hass = FakeHomeAssistant([_FORECAST_SOLAR_LIKE])
        flow = ShadyConfigFlow()
        flow.hass = hass
        settings_form = flow_call(flow.async_step_settings, None)
        settings_defaults = _defaults_from_schema(settings_form["data_schema"])
        settings_defaults["recency_decay_max"] = 0.0
        result = flow_call(flow.async_step_settings, settings_defaults)
        assert result["step_id"] == "add_string"

    def test_prefill_falls_back_to_default_for_pre_patch_entry(self) -> None:
        """An entry created before this patch has no `recency_decay_max`
        key at all — prefill must fall back to the default, no data
        migration needed (same pattern every other field already
        follows)."""
        existing_entry = FakeConfigEntry(
            data={
                "baseline_entity_id": "sensor.forecast_solar_estimate",
                "baseline_attribute": "wh_period",
                "baseline_shape": "sensor_dict",
                "temperature_aware": False,
                "window_days": 28,
                "regression_method": "wls2",
                "smoothing_radius": 1,
                "neighbor_fitting_cutoff": 0.25,
                "clipping_threshold": 0.98,
                "default_temperature_source": None,
                "max_uplift_c": 25,
                "weather_forecast_temperature_entity": None,
                "temperature_regression_method": "wls2",
                "intraday_correction_mode": "off",
                "intraday_correction_cutoff": 0.10,
                "window_slots": 24,
                "ramp_slots": 12,
                CONF_STRINGS: [],
            }
        )
        hass = FakeHomeAssistant([])
        flow = ShadyOptionsFlow()
        flow.hass = hass
        flow.config_entry = existing_entry
        settings_form = flow_call(flow.async_step_init, None)
        settings_defaults = _defaults_from_schema(settings_form["data_schema"])
        assert settings_defaults["recency_decay_max"] == 0.5


class TestOptionsFlowEditsAndChangesSettings:
    """Given `ShadyOptionsFlow`, when invoked on an existing config
    entry, it can add/edit strings and change any global setting,
    following the same step shape as initial setup."""

    def test_edit_existing_string_and_global_setting(self) -> None:
        existing_entry = FakeConfigEntry(
            data={
                "baseline_entity_id": "sensor.forecast_solar_estimate",
                "baseline_attribute": "wh_period",
                "baseline_shape": "sensor_dict",
                "temperature_aware": False,
                "window_days": 28,
                "regression_method": "wls2",
                "smoothing_radius": 1,
                "neighbor_fitting_cutoff": 0.25,
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
                        "name": "Dach Süd (old name)",
                        "baseline_entity_id": None,
                        "baseline_attribute": None,
                        "baseline_shape": None,
                        "temperature_aware": False,
                        "actual_yield_entity_id": "sensor.string_a_yield",
                        "converter_limit_w": None,
                        "temperature_source_entity_id": None,
                        "temperature_coefficient_pct_per_c": -0.4,
                        "rated_dc_capacity_wp": None,
                    }
                ],
            }
        )
        hass = FakeHomeAssistant([])
        flow = ShadyOptionsFlow()
        flow.hass = hass
        flow.config_entry = existing_entry

        settings_form = flow_call(flow.async_step_init, None)
        assert settings_form["step_id"] == "settings"
        settings_defaults = _defaults_from_schema(settings_form["data_schema"])
        # existing values are prefilled from the entry, per the same
        # step shape as initial setup, but editable:
        assert settings_defaults["window_days"] == 28
        settings_defaults["window_days"] = 21  # change a global setting
        result = flow_call(flow.async_step_settings, settings_defaults)
        assert result["step_id"] == "add_string"

        add_string_defaults = _defaults_from_schema(result["data_schema"])
        assert add_string_defaults["name"] == "Dach Süd (old name)"  # pre-filled for editing
        add_string_defaults["name"] = "Dach Süd"  # edit it
        add_string_defaults["configure_advanced"] = False
        result = flow_call(flow.async_step_add_string, add_string_defaults)
        assert result["step_id"] == "add_another"
        add_another_defaults = _defaults_from_schema(result["data_schema"])
        add_another_defaults["add_another"] = False
        final = flow_call(flow.async_step_add_another, add_another_defaults)

        assert final["data"]["window_days"] == 21
        assert final["data"][CONF_STRINGS][0]["name"] == "Dach Süd"
