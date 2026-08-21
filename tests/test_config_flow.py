from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

from ._module_loader import load_module


config_flow = load_module("shady.config_flow", "config_flow.py")


@dataclass
class _FakeEntity:
    entity_id: str
    attributes: dict[str, object]


class _FakeStates:
    def __init__(self, entities: list[_FakeEntity]) -> None:
        self._entities = entities

    def async_all(self) -> list[_FakeEntity]:
        return list(self._entities)


def _settings_input() -> dict[str, object]:
    defaults = config_flow._settings_defaults({})  # noqa: SLF001
    return {
        "baseline_choice": "manual",
        config_flow.CONF_BASELINE_ENTITY_ID: "",
        config_flow.CONF_BASELINE_ATTRIBUTE: "",
        config_flow.CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION: False,
        config_flow.CONF_WINDOW_DAYS: defaults[config_flow.CONF_WINDOW_DAYS],
        config_flow.CONF_REGRESSION_METHOD: defaults[config_flow.CONF_REGRESSION_METHOD],
        config_flow.CONF_SMOOTHING_RADIUS: defaults[config_flow.CONF_SMOOTHING_RADIUS],
        config_flow.CONF_NEIGHBOR_FITTING_CUTOFF: defaults[config_flow.CONF_NEIGHBOR_FITTING_CUTOFF],
        config_flow.CONF_CLIPPING_THRESHOLD: defaults[config_flow.CONF_CLIPPING_THRESHOLD],
        config_flow.CONF_MAX_UPLIFT_C: defaults[config_flow.CONF_MAX_UPLIFT_C],
        config_flow.CONF_TEMPERATURE_SOURCE_ENTITY_ID: "",
        config_flow.CONF_TEMPERATURE_REGRESSION_METHOD: defaults[
            config_flow.CONF_TEMPERATURE_REGRESSION_METHOD
        ],
        config_flow.CONF_INTRADAY_CORRECTION_MODE: defaults[config_flow.CONF_INTRADAY_CORRECTION_MODE],
        config_flow.CONF_INTRADAY_CORRECTION_CUTOFF: defaults[config_flow.CONF_INTRADAY_CORRECTION_CUTOFF],
        config_flow.CONF_WINDOW_SLOTS: defaults[config_flow.CONF_WINDOW_SLOTS],
        config_flow.CONF_RAMP_SLOTS: defaults[config_flow.CONF_RAMP_SLOTS],
    }


def _string_input(
    *,
    name: str,
    actual_entity_id: str,
    baseline_choice: str = "manual",
    configure_advanced: bool = False,
) -> dict[str, object]:
    return {
        config_flow.CONF_ID: "",
        config_flow.CONF_NAME: name,
        config_flow.CONF_ACTUAL_YIELD_ENTITY_ID: actual_entity_id,
        "baseline_choice": baseline_choice,
        config_flow.CONF_BASELINE_ENTITY_ID: "",
        config_flow.CONF_BASELINE_ATTRIBUTE: "",
        config_flow.CONF_CONVERTER_LIMIT: "",
        config_flow.CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID: "",
        config_flow.CONF_TEMPERATURE_COEFFICIENT: -0.4,
        config_flow.CONF_RATED_DC_CAPACITY: "",
        "configure_advanced": configure_advanced,
    }


def test_baseline_choices_include_manual_and_ranked_candidate():
    hass = SimpleNamespace(
        states=_FakeStates(
            [
                _FakeEntity(
                    "weather.home",
                    {
                        "forecast": [
                            {
                                "datetime": datetime(2026, 8, 21, 12, 0),
                                "sunshine_duration": 1800,
                            }
                        ]
                    },
                )
            ]
        )
    )

    choices = config_flow._baseline_choices(hass)  # noqa: SLF001

    assert choices["manual"] == "None of these"
    assert any(label.startswith("sunshine duration") for label in choices.values())


def test_config_flow_add_string_skips_advanced_when_not_requested():
    flow = config_flow.ShadyConfigFlow()
    flow.hass = SimpleNamespace(states=_FakeStates([]))
    flow._baseline_choices = {"manual": "None of these"}  # noqa: SLF001
    flow._apply_settings(_settings_input())  # noqa: SLF001

    result = asyncio.run(flow.async_step_add_string(_string_input(name="Roof", actual_entity_id="sensor.actual")))

    assert result["step_id"] == "add_another"

    entry = asyncio.run(flow.async_step_add_another({"add_another": False}))
    assert entry["type"] == "create_entry"
    assert entry["data"][config_flow.CONF_WINDOW_DAYS] == 28
    assert entry["data"][config_flow.CONF_STRINGS][0][config_flow.CONF_NAME] == "Roof"
    assert entry["data"][config_flow.CONF_STRINGS][0][config_flow.CONF_TEMPERATURE_AWARE] is False


def test_config_flow_marks_string_temperature_aware_for_candidate_override():
    hass = SimpleNamespace(
        states=_FakeStates(
            [
                _FakeEntity(
                    "weather.home",
                    {
                        "forecast": [
                            {
                                "datetime": datetime(2026, 8, 21, 12, 0),
                                "sunshine_duration": 1800,
                            }
                        ]
                    },
                )
            ]
        )
    )
    flow = config_flow.ShadyConfigFlow()
    flow.hass = hass
    flow._baseline_choices = config_flow._baseline_choices(hass)  # noqa: SLF001
    flow._apply_settings(_settings_input())  # noqa: SLF001
    candidate_choice = next(key for key in flow._baseline_choices if key != "manual")

    result = asyncio.run(
        flow.async_step_add_string(
            _string_input(
                name="Roof",
                actual_entity_id="sensor.actual",
                baseline_choice=candidate_choice,
                configure_advanced=True,
            )
        )
    )
    assert result["step_id"] == "add_string_advanced"

    asyncio.run(
        flow.async_step_add_string_advanced(
            {
                config_flow.CONF_CONVERTER_LIMIT: "",
                config_flow.CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID: "",
                config_flow.CONF_TEMPERATURE_COEFFICIENT: -0.4,
                config_flow.CONF_RATED_DC_CAPACITY: "",
            }
        )
    )
    entry = asyncio.run(flow.async_step_add_another({"add_another": False}))

    string_data = entry["data"][config_flow.CONF_STRINGS][0]
    assert string_data[config_flow.CONF_BASELINE_ENTITY_ID] == "weather.home"
    assert string_data[config_flow.CONF_TEMPERATURE_AWARE] is True
