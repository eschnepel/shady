"""Config flow for Shady (ADR-010's single source of truth for shape).

Three-step flow: `settings` (global, first) -> `add_string` (repeated)
-> optional `add_string_advanced` -> `add_another` loop. `ShadyOptionsFlow`
mirrors the same step shape for post-setup editing, pre-filled from the
existing config entry's data. No other module in this project imports
these classes (ADR-010 / TASK-0009's own scope note) — the only contract
downstream code depends on is the config-entry `data` shape the flow
produces (`const.py`'s `CONF_*` keys), already fixed by ADR-010.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    BASELINE_CANDIDATE_MANUAL,
    BASELINE_CANDIDATE_NONE,
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
    CONF_STRING_CONFIGURE_ADVANCED,
    CONF_STRING_CONVERTER_LIMIT_W,
    CONF_STRING_NAME,
    CONF_STRING_RATED_DC_CAPACITY_WP,
    CONF_STRING_TEMPERATURE_AWARE,
    CONF_STRING_TEMPERATURE_COEFFICIENT,
    CONF_STRING_TEMPERATURE_SOURCE,
    CONF_STRINGS,
    CONF_TEMPERATURE_AWARE,
    CONF_TEMPERATURE_REGRESSION_METHOD,
    CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY,
    CONF_WINDOW_DAYS,
    CONF_WINDOW_SLOTS,
    DEFAULT_CLIPPING_THRESHOLD,
    DEFAULT_INTRADAY_CORRECTION_CUTOFF,
    DEFAULT_INTRADAY_CORRECTION_MODE,
    DEFAULT_MAX_UPLIFT_C,
    DEFAULT_NEIGHBOR_FITTING_CUTOFF,
    DEFAULT_RAMP_SLOTS,
    DEFAULT_RECENCY_DECAY_MAX,
    DEFAULT_REGRESSION_METHOD,
    DEFAULT_SMOOTHING_RADIUS,
    DEFAULT_STRING_TEMPERATURE_COEFFICIENT,
    DEFAULT_WINDOW_DAYS,
    DEFAULT_WINDOW_SLOTS,
    DOMAIN,
    INTRADAY_CORRECTION_MODES,
    REGRESSION_METHODS,
)
from .providers.discovery import BaselineCandidate, discover_baseline_candidates
from .providers.normalize import BaselineShape

# ADR-009 §3's manual-entry fallback needs a shape choice
# (`TASK-0009-patch-1`) — `BaselineShape`'s own four values, in the same
# order `providers/normalize.py` declares them.
_BASELINE_SHAPES: tuple[BaselineShape, ...] = (
    "sensor_dict",
    "sensor_list",
    "weather_sunshine",
    "weather_cloud",
)
_DEFAULT_MANUAL_SHAPE: BaselineShape = "sensor_dict"

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.data_entry_flow import FlowResult

# --- shared helpers (module-level, used by both ShadyConfigFlow and
# ShadyOptionsFlow — kept as plain functions rather than a mixin base
# class to avoid the cooperative-multiple-inheritance/MRO ambiguity a
# shared base sitting alongside two different untyped HA base classes
# would introduce; a small, deliberate amount of per-class step-method
# boilerplate is the safer trade-off here). ---


def _candidate_choices(
    candidates: list[BaselineCandidate], *, include_none: bool
) -> dict[str, str]:
    """Build a `vol.In`-compatible `{value: label}` dropdown from ranked
    candidates (ADR-009 §3), highest score first (already sorted by
    `discover_baseline_candidates`). The key is the candidate's index as
    a string — cheap and unambiguous, avoids inventing a composite
    string encoding for `(entity_id, attribute, shape)`. A "None of
    these" manual-entry choice is always present (ADR-009 §3); a
    "use global default" choice is added only for per-string overrides.
    """
    choices = {
        str(index): f"{candidate.entity_id} — {candidate.label} ({candidate.attribute})"
        for index, candidate in enumerate(candidates)
    }
    if include_none:
        choices = {BASELINE_CANDIDATE_NONE: "Use global default", **choices}
    choices[BASELINE_CANDIDATE_MANUAL] = "None of these (enter manually)"
    return choices


def _resolve_candidate_choice(
    choice: str, candidates: list[BaselineCandidate]
) -> BaselineCandidate | None:
    """Map a submitted dropdown value back to the `BaselineCandidate` it
    refers to, or `None` for a sentinel choice (manual entry / "use
    global default").
    """
    if choice in (BASELINE_CANDIDATE_MANUAL, BASELINE_CANDIDATE_NONE):
        return None
    return candidates[int(choice)]


def _optional_float(value: Any) -> float | None:
    """`vol.Any("", vol.Coerce(float))`-validated optional numeric field
    -> `None` for the blank-string sentinel, `float` otherwise.
    """
    if value == "":
        return None
    return float(value)


def _settings_schema(candidates: list[BaselineCandidate], defaults: dict[str, Any]) -> vol.Schema:
    """The `settings` step's schema (ADR-010, global fields, in the
    document's own field order).
    """
    choices = _candidate_choices(candidates, include_none=False)
    fallback_choice = next(iter(choices)) if candidates else BASELINE_CANDIDATE_MANUAL
    return vol.Schema(
        {
            vol.Required(
                "baseline_candidate", default=defaults.get("baseline_candidate", fallback_choice)
            ): vol.In(choices),
            vol.Optional(
                "baseline_manual_entity_id",
                default=defaults.get("baseline_manual_entity_id", ""),
            ): str,
            vol.Optional(
                "baseline_manual_attribute",
                default=defaults.get("baseline_manual_attribute", ""),
            ): str,
            vol.Optional(
                "baseline_manual_shape",
                default=defaults.get("baseline_manual_shape", _DEFAULT_MANUAL_SHAPE),
            ): vol.In(_BASELINE_SHAPES),
            vol.Required(
                CONF_TEMPERATURE_AWARE, default=defaults.get(CONF_TEMPERATURE_AWARE, False)
            ): bool,
            vol.Required(
                CONF_WINDOW_DAYS, default=defaults.get(CONF_WINDOW_DAYS, DEFAULT_WINDOW_DAYS)
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required(
                CONF_REGRESSION_METHOD,
                default=defaults.get(CONF_REGRESSION_METHOD, DEFAULT_REGRESSION_METHOD),
            ): vol.In(REGRESSION_METHODS),
            vol.Required(
                CONF_SMOOTHING_RADIUS,
                default=defaults.get(CONF_SMOOTHING_RADIUS, DEFAULT_SMOOTHING_RADIUS),
            ): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Required(
                CONF_NEIGHBOR_FITTING_CUTOFF,
                default=defaults.get(CONF_NEIGHBOR_FITTING_CUTOFF, DEFAULT_NEIGHBOR_FITTING_CUTOFF),
            ): vol.Coerce(float),
            vol.Required(
                CONF_RECENCY_DECAY_MAX,
                default=defaults.get(CONF_RECENCY_DECAY_MAX, DEFAULT_RECENCY_DECAY_MAX),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
            vol.Required(
                CONF_CLIPPING_THRESHOLD,
                default=defaults.get(CONF_CLIPPING_THRESHOLD, DEFAULT_CLIPPING_THRESHOLD),
            ): vol.All(vol.Coerce(float), vol.Range(min=0, max=1)),
            vol.Optional(
                CONF_DEFAULT_TEMPERATURE_SOURCE,
                default=defaults.get(CONF_DEFAULT_TEMPERATURE_SOURCE, ""),
            ): str,
            vol.Required(
                CONF_MAX_UPLIFT_C, default=defaults.get(CONF_MAX_UPLIFT_C, DEFAULT_MAX_UPLIFT_C)
            ): vol.Coerce(float),
            vol.Optional(
                CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY,
                default=defaults.get(CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY, ""),
            ): str,
            vol.Required(
                CONF_TEMPERATURE_REGRESSION_METHOD,
                default=defaults.get(CONF_TEMPERATURE_REGRESSION_METHOD, DEFAULT_REGRESSION_METHOD),
            ): vol.In(REGRESSION_METHODS),
            vol.Required(
                CONF_INTRADAY_CORRECTION_MODE,
                default=defaults.get(
                    CONF_INTRADAY_CORRECTION_MODE, DEFAULT_INTRADAY_CORRECTION_MODE
                ),
            ): vol.In(INTRADAY_CORRECTION_MODES),
            vol.Required(
                CONF_INTRADAY_CORRECTION_CUTOFF,
                default=defaults.get(
                    CONF_INTRADAY_CORRECTION_CUTOFF, DEFAULT_INTRADAY_CORRECTION_CUTOFF
                ),
            ): vol.Coerce(float),
            vol.Required(
                CONF_WINDOW_SLOTS, default=defaults.get(CONF_WINDOW_SLOTS, DEFAULT_WINDOW_SLOTS)
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Required(
                CONF_RAMP_SLOTS, default=defaults.get(CONF_RAMP_SLOTS, DEFAULT_RAMP_SLOTS)
            ): vol.All(vol.Coerce(int), vol.Range(min=1)),
        }
    )


def _normalize_settings(
    user_input: dict[str, Any], candidates: list[BaselineCandidate]
) -> dict[str, Any]:
    """Convert a validated `settings` submission into the canonical
    config-entry data keys (`const.py`'s `CONF_*` globals).
    """
    candidate = _resolve_candidate_choice(user_input["baseline_candidate"], candidates)
    if candidate is not None:
        baseline_entity_id: str | None = candidate.entity_id
        baseline_attribute: str | None = candidate.attribute
        baseline_shape: str | None = candidate.shape
    else:
        baseline_entity_id = str(user_input.get("baseline_manual_entity_id") or "").strip() or None
        baseline_attribute = str(user_input.get("baseline_manual_attribute") or "").strip() or None
        # `TASK-0009-patch-1`: a manually-entered baseline still needs a
        # real `BaselineShape` for `BaselineProvider` (TASK-0010) to
        # parse it at all — only meaningful (and only stored) once an
        # entity_id was actually typed; an empty manual entry stays
        # `baseline_shape=None`, matching `baseline_entity_id=None`.
        baseline_shape = (
            user_input.get("baseline_manual_shape", _DEFAULT_MANUAL_SHAPE)
            if baseline_entity_id is not None
            else None
        )
    return {
        CONF_BASELINE_ENTITY_ID: baseline_entity_id,
        CONF_BASELINE_ATTRIBUTE: baseline_attribute,
        CONF_BASELINE_SHAPE: baseline_shape,
        CONF_TEMPERATURE_AWARE: user_input[CONF_TEMPERATURE_AWARE],
        CONF_WINDOW_DAYS: user_input[CONF_WINDOW_DAYS],
        CONF_REGRESSION_METHOD: user_input[CONF_REGRESSION_METHOD],
        CONF_SMOOTHING_RADIUS: user_input[CONF_SMOOTHING_RADIUS],
        CONF_NEIGHBOR_FITTING_CUTOFF: user_input[CONF_NEIGHBOR_FITTING_CUTOFF],
        CONF_RECENCY_DECAY_MAX: user_input[CONF_RECENCY_DECAY_MAX],
        CONF_CLIPPING_THRESHOLD: user_input[CONF_CLIPPING_THRESHOLD],
        CONF_DEFAULT_TEMPERATURE_SOURCE: (
            str(user_input.get(CONF_DEFAULT_TEMPERATURE_SOURCE) or "").strip() or None
        ),
        CONF_MAX_UPLIFT_C: user_input[CONF_MAX_UPLIFT_C],
        CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY: (
            str(user_input.get(CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY) or "").strip() or None
        ),
        CONF_TEMPERATURE_REGRESSION_METHOD: user_input[CONF_TEMPERATURE_REGRESSION_METHOD],
        CONF_INTRADAY_CORRECTION_MODE: user_input[CONF_INTRADAY_CORRECTION_MODE],
        CONF_INTRADAY_CORRECTION_CUTOFF: user_input[CONF_INTRADAY_CORRECTION_CUTOFF],
        CONF_WINDOW_SLOTS: user_input[CONF_WINDOW_SLOTS],
        CONF_RAMP_SLOTS: user_input[CONF_RAMP_SLOTS],
    }


def _settings_defaults_from_entry_data(
    data: dict[str, Any], candidates: list[BaselineCandidate]
) -> dict[str, Any]:
    """Reconstruct `settings` step form defaults from a config entry's
    current `data` (options-flow prefill) — the inverse of
    `_normalize_settings`.
    """
    baseline_choice = BASELINE_CANDIDATE_MANUAL
    entity_id = data.get(CONF_BASELINE_ENTITY_ID)
    attribute = data.get(CONF_BASELINE_ATTRIBUTE)
    if entity_id is not None:
        for index, candidate in enumerate(candidates):
            if candidate.entity_id == entity_id and candidate.attribute == attribute:
                baseline_choice = str(index)
                break
    return {
        "baseline_candidate": baseline_choice,
        "baseline_manual_entity_id": entity_id or "",
        "baseline_manual_attribute": attribute or "",
        "baseline_manual_shape": data.get(CONF_BASELINE_SHAPE) or _DEFAULT_MANUAL_SHAPE,
        CONF_TEMPERATURE_AWARE: data.get(CONF_TEMPERATURE_AWARE, False),
        CONF_WINDOW_DAYS: data.get(CONF_WINDOW_DAYS, DEFAULT_WINDOW_DAYS),
        CONF_REGRESSION_METHOD: data.get(CONF_REGRESSION_METHOD, DEFAULT_REGRESSION_METHOD),
        CONF_SMOOTHING_RADIUS: data.get(CONF_SMOOTHING_RADIUS, DEFAULT_SMOOTHING_RADIUS),
        CONF_NEIGHBOR_FITTING_CUTOFF: data.get(
            CONF_NEIGHBOR_FITTING_CUTOFF, DEFAULT_NEIGHBOR_FITTING_CUTOFF
        ),
        CONF_RECENCY_DECAY_MAX: data.get(CONF_RECENCY_DECAY_MAX, DEFAULT_RECENCY_DECAY_MAX),
        CONF_CLIPPING_THRESHOLD: data.get(CONF_CLIPPING_THRESHOLD, DEFAULT_CLIPPING_THRESHOLD),
        CONF_DEFAULT_TEMPERATURE_SOURCE: data.get(CONF_DEFAULT_TEMPERATURE_SOURCE) or "",
        CONF_MAX_UPLIFT_C: data.get(CONF_MAX_UPLIFT_C, DEFAULT_MAX_UPLIFT_C),
        CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY: (
            data.get(CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY) or ""
        ),
        CONF_TEMPERATURE_REGRESSION_METHOD: data.get(
            CONF_TEMPERATURE_REGRESSION_METHOD, DEFAULT_REGRESSION_METHOD
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


def _add_string_schema(candidates: list[BaselineCandidate], defaults: dict[str, Any]) -> vol.Schema:
    """The `add_string` step's schema (ADR-010)."""
    choices = _candidate_choices(candidates, include_none=True)
    default_override = defaults.get("baseline_override", BASELINE_CANDIDATE_NONE)
    return vol.Schema(
        {
            vol.Required(CONF_STRING_NAME, default=defaults.get(CONF_STRING_NAME, "")): vol.All(
                str, vol.Length(min=1)
            ),
            vol.Required("baseline_override", default=default_override): vol.In(choices),
            vol.Required(
                CONF_STRING_ACTUAL_YIELD_ENTITY,
                default=defaults.get(CONF_STRING_ACTUAL_YIELD_ENTITY, ""),
            ): vol.All(str, vol.Length(min=1)),
            vol.Required(
                CONF_STRING_CONFIGURE_ADVANCED,
                default=defaults.get(CONF_STRING_CONFIGURE_ADVANCED, False),
            ): bool,
        }
    )


def _string_defaults(
    existing: dict[str, Any], candidates: list[BaselineCandidate]
) -> dict[str, Any]:
    """Reconstruct `add_string` step form defaults from an already-stored
    string dict (options-flow prefill for re-confirming/editing an
    existing string).
    """
    override_choice = BASELINE_CANDIDATE_NONE
    entity_id = existing.get(CONF_STRING_BASELINE_ENTITY_ID)
    attribute = existing.get(CONF_STRING_BASELINE_ATTRIBUTE)
    if entity_id is not None:
        for index, candidate in enumerate(candidates):
            if candidate.entity_id == entity_id and candidate.attribute == attribute:
                override_choice = str(index)
                break
    return {
        CONF_STRING_NAME: existing.get(CONF_STRING_NAME, ""),
        "baseline_override": override_choice,
        CONF_STRING_ACTUAL_YIELD_ENTITY: existing.get(CONF_STRING_ACTUAL_YIELD_ENTITY, ""),
        CONF_STRING_CONFIGURE_ADVANCED: bool(
            existing.get(CONF_STRING_CONVERTER_LIMIT_W) is not None
            or existing.get(CONF_STRING_TEMPERATURE_SOURCE) is not None
            or existing.get(CONF_STRING_RATED_DC_CAPACITY_WP) is not None
        ),
    }


def _build_current_string(
    user_input: dict[str, Any], candidates: list[BaselineCandidate]
) -> dict[str, Any]:
    """Convert a validated `add_string` submission into a string entry
    dict, with advanced fields at their no-op defaults until (optionally)
    overwritten by `_apply_advanced` (ADR-010's `add_string_advanced` is
    optional per string).
    """
    candidate = _resolve_candidate_choice(user_input["baseline_override"], candidates)
    return {
        CONF_STRING_NAME: user_input[CONF_STRING_NAME],
        CONF_STRING_BASELINE_ENTITY_ID: candidate.entity_id if candidate else None,
        CONF_STRING_BASELINE_ATTRIBUTE: candidate.attribute if candidate else None,
        CONF_STRING_BASELINE_SHAPE: candidate.shape if candidate else None,
        # A string with a baseline override is, by definition, treated as
        # temperature-aware — no separate flag is asked (ADR-003b §1c /
        # ADR-010's `add_string` note).
        CONF_STRING_TEMPERATURE_AWARE: candidate is not None,
        CONF_STRING_ACTUAL_YIELD_ENTITY: user_input[CONF_STRING_ACTUAL_YIELD_ENTITY],
        CONF_STRING_CONVERTER_LIMIT_W: None,
        CONF_STRING_TEMPERATURE_SOURCE: None,
        CONF_STRING_TEMPERATURE_COEFFICIENT: DEFAULT_STRING_TEMPERATURE_COEFFICIENT,
        CONF_STRING_RATED_DC_CAPACITY_WP: None,
    }


def _add_string_advanced_schema(defaults: dict[str, Any]) -> vol.Schema:
    """The `add_string_advanced` step's schema (ADR-010). All four fields
    are shown together, matching ADR-010's own per-step field listing —
    which of them actually applies is resolved from the *stored* data by
    downstream consumers (`providers/temperature.py`, TASK-0010), not by
    dynamically hiding fields within this static form (a deliberate
    scope simplification; ADR-010 does not specify conditional field
    visibility, only which fields belong to this step).
    """
    return vol.Schema(
        {
            vol.Optional(
                CONF_STRING_CONVERTER_LIMIT_W,
                default=defaults.get(CONF_STRING_CONVERTER_LIMIT_W, ""),
            ): vol.Any("", vol.Coerce(float)),
            vol.Optional(
                CONF_STRING_TEMPERATURE_SOURCE,
                default=defaults.get(CONF_STRING_TEMPERATURE_SOURCE, ""),
            ): str,
            vol.Required(
                CONF_STRING_TEMPERATURE_COEFFICIENT,
                default=defaults.get(
                    CONF_STRING_TEMPERATURE_COEFFICIENT, DEFAULT_STRING_TEMPERATURE_COEFFICIENT
                ),
            ): vol.Coerce(float),
            vol.Optional(
                CONF_STRING_RATED_DC_CAPACITY_WP,
                default=defaults.get(CONF_STRING_RATED_DC_CAPACITY_WP, ""),
            ): vol.Any("", vol.Coerce(float)),
        }
    )


def _apply_advanced(user_input: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Merge a validated `add_string_advanced` submission into the
    in-progress string entry. A blank "rated DC capacity" (or, upstream,
    no resolved temperature source at all) leaves derating skipped for
    this string — the skip-both-sides rule ADR-003c §5 already applies
    to a missing forecast-capable predictor, applied here to a missing
    rated-capacity input (interpreted by `providers/temperature.py` /
    TASK-0010, which know a resolved source's tier; this flow only
    stores `None` faithfully).
    """
    updated = dict(current)
    updated[CONF_STRING_CONVERTER_LIMIT_W] = _optional_float(
        user_input.get(CONF_STRING_CONVERTER_LIMIT_W)
    )
    temperature_source = str(user_input.get(CONF_STRING_TEMPERATURE_SOURCE) or "").strip()
    updated[CONF_STRING_TEMPERATURE_SOURCE] = temperature_source or None
    updated[CONF_STRING_TEMPERATURE_COEFFICIENT] = user_input[CONF_STRING_TEMPERATURE_COEFFICIENT]
    updated[CONF_STRING_RATED_DC_CAPACITY_WP] = _optional_float(
        user_input.get(CONF_STRING_RATED_DC_CAPACITY_WP)
    )
    return updated


class ShadyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc, call-arg]
    """Initial setup flow (ADR-010)."""

    VERSION = 1

    def __init__(self) -> None:
        self._candidates: list[BaselineCandidate] = []
        self._data: dict[str, Any] = {}
        self._strings: list[dict[str, Any]] = []
        self._current_string: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """HA's conventional user-initiated entry point; immediately
        delegates to ADR-010's own first step, named `settings`.
        """
        return await self.async_step_settings(user_input)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if not self._candidates:
            self._candidates = discover_baseline_candidates(self.hass)
        if user_input is not None:
            self._data = _normalize_settings(user_input, self._candidates)
            return await self.async_step_add_string()
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(self._candidates, {})
        )

    async def async_step_add_string(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._current_string = _build_current_string(user_input, self._candidates)
            if user_input[CONF_STRING_CONFIGURE_ADVANCED]:
                return await self.async_step_add_string_advanced()
            self._strings.append(self._current_string)
            self._current_string = {}
            return await self.async_step_add_another()
        return self.async_show_form(
            step_id="add_string", data_schema=_add_string_schema(self._candidates, {})
        )

    async def async_step_add_string_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._current_string = _apply_advanced(user_input, self._current_string)
            self._strings.append(self._current_string)
            self._current_string = {}
            return await self.async_step_add_another()
        return self.async_show_form(
            step_id="add_string_advanced", data_schema=_add_string_advanced_schema({})
        )

    async def async_step_add_another(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            if user_input["add_another"]:
                return await self.async_step_add_string()
            return self.async_create_entry(
                title="Shady", data={**self._data, CONF_STRINGS: self._strings}
            )
        return self.async_show_form(
            step_id="add_another",
            data_schema=vol.Schema({vol.Required("add_another", default=False): bool}),
        )

    @staticmethod
    @callback  # type: ignore[untyped-decorator]
    def async_get_options_flow(config_entry: ConfigEntry) -> ShadyOptionsFlow:
        return ShadyOptionsFlow()


class ShadyOptionsFlow(config_entries.OptionsFlow):  # type: ignore[misc]
    """Post-setup editing flow (ADR-010): "mirrors [initial setup] to
    allow adding/editing strings and changing any global setting...
    following the same step shape as initial setup." Existing strings
    are walked through the same `add_string`/`add_string_advanced` forms,
    pre-filled, one at a time, so each can be re-confirmed (kept as-is)
    or edited; the trailing `add_another` loop still allows appending
    genuinely new strings after the existing ones.
    """

    def __init__(self) -> None:
        self._candidates: list[BaselineCandidate] = []
        self._data: dict[str, Any] = {}
        self._strings: list[dict[str, Any]] = []
        self._current_string: dict[str, Any] = {}
        self._pending_existing: list[dict[str, Any]] = []

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_settings(user_input)

    async def async_step_settings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        entry_data = dict(self.config_entry.data)
        if not self._candidates:
            self._candidates = discover_baseline_candidates(self.hass)
            self._pending_existing = list(entry_data.get(CONF_STRINGS, []))
        if user_input is not None:
            self._data = _normalize_settings(user_input, self._candidates)
            return await self.async_step_add_string()
        defaults = _settings_defaults_from_entry_data(entry_data, self._candidates)
        return self.async_show_form(
            step_id="settings", data_schema=_settings_schema(self._candidates, defaults)
        )

    async def async_step_add_string(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._current_string = _build_current_string(user_input, self._candidates)
            if self._pending_existing:
                self._pending_existing.pop(0)
            if user_input[CONF_STRING_CONFIGURE_ADVANCED]:
                return await self.async_step_add_string_advanced()
            self._strings.append(self._current_string)
            self._current_string = {}
            return await self.async_step_add_another()
        defaults = (
            _string_defaults(self._pending_existing[0], self._candidates)
            if self._pending_existing
            else {}
        )
        return self.async_show_form(
            step_id="add_string", data_schema=_add_string_schema(self._candidates, defaults)
        )

    async def async_step_add_string_advanced(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._current_string = _apply_advanced(user_input, self._current_string)
            self._strings.append(self._current_string)
            self._current_string = {}
            return await self.async_step_add_another()
        return self.async_show_form(
            step_id="add_string_advanced", data_schema=_add_string_advanced_schema({})
        )

    async def async_step_add_another(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            if user_input["add_another"]:
                return await self.async_step_add_string()
            return self.async_create_entry(
                title="", data={**self._data, CONF_STRINGS: self._strings}
            )
        default_more = bool(self._pending_existing)
        return self.async_show_form(
            step_id="add_another",
            data_schema=vol.Schema({vol.Required("add_another", default=default_more): bool}),
        )
