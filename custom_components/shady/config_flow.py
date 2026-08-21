"""Config flow for Shady."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ACTUAL_YIELD_ENTITY_ID,
    CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION,
    CONF_BASELINE_ATTRIBUTE,
    CONF_BASELINE_ENTITY_ID,
    CONF_CLIPPING_THRESHOLD,
    CONF_CONVERTER_LIMIT,
    CONF_ID,
    CONF_INTRADAY_CORRECTION_CUTOFF,
    CONF_INTRADAY_CORRECTION_MODE,
    CONF_MAX_UPLIFT_C,
    CONF_NAME,
    CONF_NEIGHBOR_FITTING_CUTOFF,
    CONF_RAMP_SLOTS,
    CONF_RATED_DC_CAPACITY,
    CONF_REGRESSION_METHOD,
    CONF_SMOOTHING_RADIUS,
    CONF_STRINGS,
    CONF_TEMPERATURE_AWARE,
    CONF_TEMPERATURE_COEFFICIENT,
    CONF_TEMPERATURE_REGRESSION_METHOD,
    CONF_TEMPERATURE_SOURCE_ENTITY_ID,
    CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID,
    CONF_WINDOW_DAYS,
    CONF_WINDOW_SLOTS,
    DEFAULT_CLIPPING_THRESHOLD,
    DEFAULT_INTRADAY_CORRECTION_CUTOFF,
    DEFAULT_INTRADAY_CORRECTION_MODE,
    DEFAULT_MAX_UPLIFT_C,
    DEFAULT_NEIGHBOR_FITTING_CUTOFF,
    DEFAULT_RAMP_SLOTS,
    DEFAULT_REGRESSION_METHOD,
    DEFAULT_SMOOTHING_RADIUS,
    DEFAULT_TEMPERATURE_REGRESSION_METHOD,
    DEFAULT_WINDOW_DAYS,
    DEFAULT_WINDOW_SLOTS,
    DOMAIN,
)
from .providers.discovery import ForecastCandidate, discover_candidates, rank_candidates

REGRESSION_METHODS = ["wls2", "linear", "kernel", "wls3"]
INTRADAY_MODES = ["off", "ramping", "blending"]

__all__ = ["ShadyConfigFlow", "ShadyOptionsFlow"]


def _candidate_id(candidate: ForecastCandidate) -> str:
    return "|".join((candidate.entity_id, candidate.attribute, candidate.source_kind))


def _decode_candidate_id(candidate_id: str) -> tuple[str, str] | None:
    if candidate_id == "manual" or candidate_id == "":
        return None
    parts = candidate_id.split("|", 2)
    if len(parts) != 3:
        return None
    return parts[0], parts[1]


def _baseline_choices(hass: Any) -> dict[str, str]:
    entities = []
    if hasattr(hass, "states") and hasattr(hass.states, "async_all"):
        entities = list(hass.states.async_all())
    candidates = rank_candidates(discover_candidates(entities))
    choices = {"manual": "None of these"}
    for candidate in candidates:
        choices[_candidate_id(candidate)] = f"{candidate.label} ({candidate.entity_id})"
    return choices


def _default_string_id(strings: list[dict[str, Any]]) -> str:
    return f"string-{len(strings) + 1:02d}"


def _settings_defaults(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        CONF_WINDOW_DAYS: data.get(CONF_WINDOW_DAYS, DEFAULT_WINDOW_DAYS),
        CONF_REGRESSION_METHOD: data.get(CONF_REGRESSION_METHOD, DEFAULT_REGRESSION_METHOD),
        CONF_SMOOTHING_RADIUS: data.get(CONF_SMOOTHING_RADIUS, DEFAULT_SMOOTHING_RADIUS),
        CONF_NEIGHBOR_FITTING_CUTOFF: data.get(
            CONF_NEIGHBOR_FITTING_CUTOFF, DEFAULT_NEIGHBOR_FITTING_CUTOFF
        ),
        CONF_CLIPPING_THRESHOLD: data.get(CONF_CLIPPING_THRESHOLD, DEFAULT_CLIPPING_THRESHOLD),
        CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION: data.get(
            CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION, False
        ),
        CONF_BASELINE_ENTITY_ID: data.get(CONF_BASELINE_ENTITY_ID, ""),
        CONF_BASELINE_ATTRIBUTE: data.get(CONF_BASELINE_ATTRIBUTE, ""),
        CONF_MAX_UPLIFT_C: data.get(CONF_MAX_UPLIFT_C, DEFAULT_MAX_UPLIFT_C),
        CONF_TEMPERATURE_SOURCE_ENTITY_ID: data.get(CONF_TEMPERATURE_SOURCE_ENTITY_ID, ""),
        CONF_TEMPERATURE_REGRESSION_METHOD: data.get(
            CONF_TEMPERATURE_REGRESSION_METHOD, DEFAULT_TEMPERATURE_REGRESSION_METHOD
        ),
        CONF_INTRADAY_CORRECTION_MODE: data.get(
            CONF_INTRADAY_CORRECTION_MODE, DEFAULT_INTRADAY_CORRECTION_MODE
        ),
        CONF_INTRADAY_CORRECTION_CUTOFF: data.get(
            CONF_INTRADAY_CORRECTION_CUTOFF, DEFAULT_INTRADAY_CORRECTION_CUTOFF
        ),
        CONF_WINDOW_SLOTS: data.get(CONF_WINDOW_SLOTS, DEFAULT_WINDOW_SLOTS),
        CONF_RAMP_SLOTS: data.get(CONF_RAMP_SLOTS, DEFAULT_RAMP_SLOTS),
    }


def _string_defaults(data: Mapping[str, Any]) -> dict[str, Any]:
    return {
        CONF_ID: data.get(CONF_ID, ""),
        CONF_NAME: data.get(CONF_NAME, ""),
        CONF_ACTUAL_YIELD_ENTITY_ID: data.get(CONF_ACTUAL_YIELD_ENTITY_ID, ""),
        CONF_BASELINE_ENTITY_ID: data.get(CONF_BASELINE_ENTITY_ID, ""),
        CONF_BASELINE_ATTRIBUTE: data.get(CONF_BASELINE_ATTRIBUTE, ""),
        CONF_CONVERTER_LIMIT: data.get(CONF_CONVERTER_LIMIT, ""),
        CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID: data.get(
            CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID, ""
        ),
        CONF_TEMPERATURE_COEFFICIENT: data.get(CONF_TEMPERATURE_COEFFICIENT, -0.4),
        CONF_RATED_DC_CAPACITY: data.get(CONF_RATED_DC_CAPACITY, ""),
    }


def _string_schema(defaults: dict[str, Any], baseline_choices: dict[str, str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_ID, default=defaults[CONF_ID]): cv.string,
            vol.Required(CONF_NAME, default=defaults[CONF_NAME]): cv.string,
            vol.Required(
                CONF_ACTUAL_YIELD_ENTITY_ID,
                default=defaults[CONF_ACTUAL_YIELD_ENTITY_ID],
            ): cv.string,
            vol.Optional(
                "baseline_choice",
                default=defaults.get("baseline_choice", "manual"),
            ): vol.In(baseline_choices),
            vol.Optional(
                CONF_BASELINE_ENTITY_ID,
                default=defaults[CONF_BASELINE_ENTITY_ID],
            ): cv.string,
            vol.Optional(
                CONF_BASELINE_ATTRIBUTE,
                default=defaults[CONF_BASELINE_ATTRIBUTE],
            ): cv.string,
            vol.Optional(CONF_CONVERTER_LIMIT, default=defaults[CONF_CONVERTER_LIMIT]): cv.string,
            vol.Optional(
                CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID,
                default=defaults[CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID],
            ): cv.string,
            vol.Optional(
                CONF_TEMPERATURE_COEFFICIENT,
                default=defaults[CONF_TEMPERATURE_COEFFICIENT],
            ): vol.Coerce(float),
            vol.Optional(
                CONF_RATED_DC_CAPACITY,
                default=defaults[CONF_RATED_DC_CAPACITY],
            ): cv.string,
            vol.Optional("configure_advanced", default=False): bool,
        }
    )


def _string_advanced_schema(defaults: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Optional(CONF_CONVERTER_LIMIT, default=defaults[CONF_CONVERTER_LIMIT]): cv.string,
            vol.Optional(
                CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID,
                default=defaults[CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID],
            ): cv.string,
            vol.Optional(
                CONF_TEMPERATURE_COEFFICIENT,
                default=defaults[CONF_TEMPERATURE_COEFFICIENT],
            ): vol.Coerce(float),
            vol.Optional(
                CONF_RATED_DC_CAPACITY,
                default=defaults[CONF_RATED_DC_CAPACITY],
            ): cv.string,
        }
    )


def _resolve_baseline_fields(user_input: Mapping[str, Any]) -> tuple[str | None, str | None]:
    baseline_choice = str(user_input.get("baseline_choice", "manual"))
    baseline_override = _decode_candidate_id(baseline_choice)
    if baseline_override is None:
        baseline_entity_id = str(user_input.get(CONF_BASELINE_ENTITY_ID, "")).strip() or None
        baseline_attribute = str(user_input.get(CONF_BASELINE_ATTRIBUTE, "")).strip() or None
        return baseline_entity_id, baseline_attribute
    return baseline_override


class _ShadyFlowBase:
    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._strings: list[dict[str, Any]] = []
        self._baseline_choices: dict[str, str] = {"manual": "None of these"}

    def _apply_settings(self, user_input: Mapping[str, Any]) -> None:
        baseline_entity_id, baseline_attribute = _resolve_baseline_fields(user_input)
        self._data.update(
            {
                CONF_WINDOW_DAYS: int(user_input[CONF_WINDOW_DAYS]),
                CONF_REGRESSION_METHOD: str(user_input[CONF_REGRESSION_METHOD]),
                CONF_SMOOTHING_RADIUS: int(user_input[CONF_SMOOTHING_RADIUS]),
                CONF_NEIGHBOR_FITTING_CUTOFF: float(user_input[CONF_NEIGHBOR_FITTING_CUTOFF]),
                CONF_CLIPPING_THRESHOLD: float(user_input[CONF_CLIPPING_THRESHOLD]),
                CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION: bool(
                    user_input[CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION]
                ),
                CONF_BASELINE_ENTITY_ID: baseline_entity_id,
                CONF_BASELINE_ATTRIBUTE: baseline_attribute,
                CONF_MAX_UPLIFT_C: float(user_input[CONF_MAX_UPLIFT_C]),
                CONF_TEMPERATURE_SOURCE_ENTITY_ID: (
                    str(user_input.get(CONF_TEMPERATURE_SOURCE_ENTITY_ID, "")).strip() or None
                ),
                CONF_TEMPERATURE_REGRESSION_METHOD: str(
                    user_input[CONF_TEMPERATURE_REGRESSION_METHOD]
                ),
                CONF_INTRADAY_CORRECTION_MODE: str(user_input[CONF_INTRADAY_CORRECTION_MODE]),
                CONF_INTRADAY_CORRECTION_CUTOFF: float(
                    user_input[CONF_INTRADAY_CORRECTION_CUTOFF]
                ),
                CONF_WINDOW_SLOTS: int(user_input[CONF_WINDOW_SLOTS]),
                CONF_RAMP_SLOTS: int(user_input[CONF_RAMP_SLOTS]),
            }
        )

    def _string_defaults_from_current(self) -> dict[str, Any]:
        defaults = _string_defaults({})
        defaults[CONF_ID] = _default_string_id(self._strings)
        return defaults

    def _finalize_string(self, user_input: Mapping[str, Any], settings: Mapping[str, Any]) -> None:
        string_entry = dict(user_input)
        chosen = str(string_entry.get("baseline_choice", "manual"))
        if chosen != "manual":
            decoded = _decode_candidate_id(chosen)
            if decoded is not None:
                string_entry[CONF_BASELINE_ENTITY_ID], string_entry[CONF_BASELINE_ATTRIBUTE] = decoded
        string_entry[CONF_BASELINE_ENTITY_ID] = (
            str(string_entry.get(CONF_BASELINE_ENTITY_ID, "")).strip() or None
        )
        string_entry[CONF_BASELINE_ATTRIBUTE] = (
            str(string_entry.get(CONF_BASELINE_ATTRIBUTE, "")).strip() or None
        )
        string_entry[CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID] = (
            str(string_entry.get(CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID, "")).strip() or None
        )
        string_entry[CONF_CONVERTER_LIMIT] = (
            str(string_entry.get(CONF_CONVERTER_LIMIT, "")).strip() or None
        )
        string_entry[CONF_RATED_DC_CAPACITY] = (
            str(string_entry.get(CONF_RATED_DC_CAPACITY, "")).strip() or None
        )
        string_entry[CONF_TEMPERATURE_COEFFICIENT] = float(
            string_entry.get(CONF_TEMPERATURE_COEFFICIENT, -0.4)
        )
        string_entry[CONF_TEMPERATURE_AWARE] = bool(string_entry[CONF_BASELINE_ENTITY_ID]) or bool(
            string_entry[CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID]
        )
        if settings.get(CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION):
            string_entry[CONF_TEMPERATURE_AWARE] = True
        if not string_entry.get(CONF_ID):
            string_entry[CONF_ID] = _default_string_id(self._strings)
        self._strings.append(
            {
                CONF_ID: string_entry[CONF_ID],
                CONF_NAME: string_entry[CONF_NAME],
                CONF_ACTUAL_YIELD_ENTITY_ID: string_entry[CONF_ACTUAL_YIELD_ENTITY_ID],
                CONF_BASELINE_ENTITY_ID: string_entry[CONF_BASELINE_ENTITY_ID],
                CONF_BASELINE_ATTRIBUTE: string_entry[CONF_BASELINE_ATTRIBUTE],
                CONF_CONVERTER_LIMIT: string_entry[CONF_CONVERTER_LIMIT],
                CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID: string_entry[
                    CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID
                ],
                CONF_TEMPERATURE_COEFFICIENT: string_entry[CONF_TEMPERATURE_COEFFICIENT],
                CONF_RATED_DC_CAPACITY: string_entry[CONF_RATED_DC_CAPACITY],
                CONF_TEMPERATURE_AWARE: string_entry[CONF_TEMPERATURE_AWARE],
            }
        )

    def _create_data(self) -> dict[str, Any]:
        data = dict(self._data)
        data[CONF_STRINGS] = list(self._strings)
        return data


class ShadyConfigFlow(_ShadyFlowBase, ConfigFlow, domain=DOMAIN):
    """Shady config flow."""

    VERSION = 1

    def __init__(self) -> None:
        super().__init__()
        _ShadyFlowBase.__init__(self)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> "ShadyOptionsFlow":
        return ShadyOptionsFlow(config_entry)

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_settings(user_input)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._apply_settings(user_input)
            return await self.async_step_add_string()

        self._baseline_choices = _baseline_choices(self.hass)
        defaults = _settings_defaults(self._data)
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional("baseline_choice", default="manual"): vol.In(
                        self._baseline_choices
                    ),
                    vol.Optional(
                        CONF_BASELINE_ENTITY_ID, default=defaults[CONF_BASELINE_ENTITY_ID]
                    ): cv.string,
                    vol.Optional(
                        CONF_BASELINE_ATTRIBUTE, default=defaults[CONF_BASELINE_ATTRIBUTE]
                    ): cv.string,
                    vol.Optional(
                        CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION,
                        default=defaults[CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION],
                    ): bool,
                    vol.Required(CONF_WINDOW_DAYS, default=defaults[CONF_WINDOW_DAYS]): vol.Coerce(int),
                    vol.Required(
                        CONF_REGRESSION_METHOD, default=defaults[CONF_REGRESSION_METHOD]
                    ): vol.In(REGRESSION_METHODS),
                    vol.Required(
                        CONF_SMOOTHING_RADIUS, default=defaults[CONF_SMOOTHING_RADIUS]
                    ): vol.Coerce(int),
                    vol.Required(
                        CONF_NEIGHBOR_FITTING_CUTOFF,
                        default=defaults[CONF_NEIGHBOR_FITTING_CUTOFF],
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_CLIPPING_THRESHOLD,
                        default=defaults[CONF_CLIPPING_THRESHOLD],
                    ): vol.Coerce(float),
                    vol.Required(CONF_MAX_UPLIFT_C, default=defaults[CONF_MAX_UPLIFT_C]): vol.Coerce(
                        float
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE_SOURCE_ENTITY_ID,
                        default=defaults[CONF_TEMPERATURE_SOURCE_ENTITY_ID],
                    ): cv.string,
                    vol.Required(
                        CONF_TEMPERATURE_REGRESSION_METHOD,
                        default=defaults[CONF_TEMPERATURE_REGRESSION_METHOD],
                    ): vol.In(REGRESSION_METHODS),
                    vol.Required(
                        CONF_INTRADAY_CORRECTION_MODE,
                        default=defaults[CONF_INTRADAY_CORRECTION_MODE],
                    ): vol.In(INTRADAY_MODES),
                    vol.Required(
                        CONF_INTRADAY_CORRECTION_CUTOFF,
                        default=defaults[CONF_INTRADAY_CORRECTION_CUTOFF],
                    ): vol.Coerce(float),
                    vol.Required(CONF_WINDOW_SLOTS, default=defaults[CONF_WINDOW_SLOTS]): vol.Coerce(
                        int
                    ),
                    vol.Required(CONF_RAMP_SLOTS, default=defaults[CONF_RAMP_SLOTS]): vol.Coerce(int),
                }
            ),
        )

    async def async_step_add_string(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._pending_string = dict(user_input)
            if bool(user_input.get("configure_advanced", False)):
                return await self.async_step_add_string_advanced()
            self._finalize_string(self._pending_string, self._data)
            return await self.async_step_add_another()

        defaults = self._string_defaults_from_current()
        return self.async_show_form(
            step_id="add_string",
            data_schema=_string_schema(defaults, self._baseline_choices or {"manual": "None of these"}),
        )

    async def async_step_add_string_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._pending_string.update(user_input)
            self._finalize_string(self._pending_string, self._data)
            return await self.async_step_add_another()

        defaults = _string_defaults(self._pending_string)
        return self.async_show_form(
            step_id="add_string_advanced",
            data_schema=_string_advanced_schema(defaults),
        )

    async def async_step_add_another(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if bool(user_input.get("add_another", False)):
                return await self.async_step_add_string()
            title = self._strings[0][CONF_NAME] if self._strings else "Shady"
            return self.async_create_entry(title=title, data=self._create_data())

        return self.async_show_form(
            step_id="add_another",
            data_schema=vol.Schema({vol.Required("add_another", default=False): bool}),
        )


class ShadyOptionsFlow(_ShadyFlowBase, OptionsFlow):
    """Shady options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        super().__init__()
        _ShadyFlowBase.__init__(self)
        self._data = dict(config_entry.data)
        self._strings = list(config_entry.data.get(CONF_STRINGS, []))
        self._pending_string: dict[str, Any] = {}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self.async_step_settings(user_input)

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._apply_settings(user_input)
            return await self.async_step_add_string()

        self._baseline_choices = _baseline_choices(self.hass)
        defaults = _settings_defaults(self._data)
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema(
                {
                    vol.Optional("baseline_choice", default="manual"): vol.In(
                        self._baseline_choices
                    ),
                    vol.Optional(
                        CONF_BASELINE_ENTITY_ID, default=defaults[CONF_BASELINE_ENTITY_ID]
                    ): cv.string,
                    vol.Optional(
                        CONF_BASELINE_ATTRIBUTE, default=defaults[CONF_BASELINE_ATTRIBUTE]
                    ): cv.string,
                    vol.Optional(
                        CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION,
                        default=defaults[CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION],
                    ): bool,
                    vol.Required(CONF_WINDOW_DAYS, default=defaults[CONF_WINDOW_DAYS]): vol.Coerce(int),
                    vol.Required(
                        CONF_REGRESSION_METHOD, default=defaults[CONF_REGRESSION_METHOD]
                    ): vol.In(REGRESSION_METHODS),
                    vol.Required(
                        CONF_SMOOTHING_RADIUS, default=defaults[CONF_SMOOTHING_RADIUS]
                    ): vol.Coerce(int),
                    vol.Required(
                        CONF_NEIGHBOR_FITTING_CUTOFF,
                        default=defaults[CONF_NEIGHBOR_FITTING_CUTOFF],
                    ): vol.Coerce(float),
                    vol.Required(
                        CONF_CLIPPING_THRESHOLD,
                        default=defaults[CONF_CLIPPING_THRESHOLD],
                    ): vol.Coerce(float),
                    vol.Required(CONF_MAX_UPLIFT_C, default=defaults[CONF_MAX_UPLIFT_C]): vol.Coerce(
                        float
                    ),
                    vol.Optional(
                        CONF_TEMPERATURE_SOURCE_ENTITY_ID,
                        default=defaults[CONF_TEMPERATURE_SOURCE_ENTITY_ID],
                    ): cv.string,
                    vol.Required(
                        CONF_TEMPERATURE_REGRESSION_METHOD,
                        default=defaults[CONF_TEMPERATURE_REGRESSION_METHOD],
                    ): vol.In(REGRESSION_METHODS),
                    vol.Required(
                        CONF_INTRADAY_CORRECTION_MODE,
                        default=defaults[CONF_INTRADAY_CORRECTION_MODE],
                    ): vol.In(INTRADAY_MODES),
                    vol.Required(
                        CONF_INTRADAY_CORRECTION_CUTOFF,
                        default=defaults[CONF_INTRADAY_CORRECTION_CUTOFF],
                    ): vol.Coerce(float),
                    vol.Required(CONF_WINDOW_SLOTS, default=defaults[CONF_WINDOW_SLOTS]): vol.Coerce(
                        int
                    ),
                    vol.Required(CONF_RAMP_SLOTS, default=defaults[CONF_RAMP_SLOTS]): vol.Coerce(int),
                }
            ),
        )

    async def async_step_add_string(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._pending_string = dict(user_input)
            if bool(user_input.get("configure_advanced", False)):
                return await self.async_step_add_string_advanced()
            self._finalize_string(self._pending_string, self._data)
            return await self.async_step_add_another()

        defaults = _string_defaults(self._pending_string)
        defaults[CONF_ID] = _default_string_id(self._strings)
        return self.async_show_form(
            step_id="add_string",
            data_schema=_string_schema(defaults, self._baseline_choices or {"manual": "None of these"}),
        )

    async def async_step_add_string_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._pending_string.update(user_input)
            self._finalize_string(self._pending_string, self._data)
            return await self.async_step_add_another()

        defaults = _string_defaults(self._pending_string)
        return self.async_show_form(
            step_id="add_string_advanced",
            data_schema=_string_advanced_schema(defaults),
        )

    async def async_step_add_another(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            if bool(user_input.get("add_another", False)):
                return await self.async_step_add_string()
            return self.async_create_entry(title=self._data.get(CONF_NAME, "Shady"), data=self._create_data())

        return self.async_show_form(
            step_id="add_another",
            data_schema=vol.Schema({vol.Required("add_another", default=False): bool}),
        )
