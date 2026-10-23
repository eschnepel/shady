"""Config flow for Shady (ADR-010's single source of truth for shape).

Five steps, linear for first setup: `baseline` (global default baseline
+ manual fallback) -> `strings` (one multi-select entity selector -- every
entity picked *is* a string) -> `string_settings_hub`/`string_settings_edit`
loop (one page per string, skipped entirely if no strings were picked) ->
`regression_tuning` -> `advanced_optional` -> `async_create_entry`.
`async_step_reconfigure` instead opens on an `async_show_menu` of the same
five sections (minus the fixed linear ordering) plus "Save & Finish",
returning to that same menu after each section rather than proceeding
onward. No other module in this project imports these classes (ADR-010's
own scope note) -- the only contract downstream code depends on is the
config-entry `data` shape the flow produces (`const.py`'s `CONF_*` keys),
already fixed by ADR-010.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.helpers import selector

from .const import (
    BASELINE_CANDIDATE_MANUAL,
    BASELINE_CANDIDATE_NONE,
    CONF_BASELINE_ATTRIBUTE,
    CONF_BASELINE_ENTITY_ID,
    CONF_BASELINE_HISTORY_ENTITY_ID,
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
    CONF_STRING_BASELINE_ATTRIBUTE,
    CONF_STRING_BASELINE_ENTITY_ID,
    CONF_STRING_BASELINE_HISTORY_ENTITY_ID,
    CONF_STRING_BASELINE_SHAPE,
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
    STRING_SETTINGS_HUB_DONE,
)
from .providers.discovery import BaselineCandidate, discover_baseline_candidates
from .providers.normalize import BaselineShape

# ADR-009 §3's manual-entry fallback needs a shape choice
# (`TASK-0009-patch-1`) — four of `BaselineShape`'s five values, in the
# same order `providers/normalize.py` declares them. `forecast_solar`
# (ADR-009 Amendment) is deliberately excluded here: that shape's
# `entity_id` field holds a Forecast.Solar config entry's own `entry_id`,
# not something a user could reasonably type into a plain text field —
# it is only ever produced by `discover_baseline_candidates`' own scan.
_BASELINE_SHAPES: tuple[BaselineShape, ...] = (
    "sensor_dict",
    "sensor_list",
    "weather_sunshine",
    "weather_cloud",
)
_DEFAULT_MANUAL_SHAPE: BaselineShape = "sensor_dict"

# `string_settings_hub`/reconfigure-menu step-id constants (`TASK-0035`) —
# named once here rather than repeating string literals at every dispatch
# site below.
_STEP_BASELINE = "baseline"
_STEP_STRINGS = "strings"
_STEP_STRING_SETTINGS_HUB = "string_settings_hub"
_STEP_STRING_SETTINGS_EDIT = "string_settings_edit"
_STEP_REGRESSION_TUNING = "regression_tuning"
_STEP_ADVANCED_OPTIONAL = "advanced_optional"
_STEP_RECONFIGURE = "reconfigure"

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.data_entry_flow import FlowResult

# --- shared helpers (module-level; kept as plain functions rather than a
# mixin, since `ShadyConfigFlow` is now the only flow class -- no second
# class to share them with). ---


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


def _blank_if_none(value: float | None) -> float | str:
    """Inverse of `_optional_float`, for computing a form default from a
    stored value: the stored `None` -> the schema's own blank-string
    sentinel, otherwise the value unchanged. `dict.get(key, "")`
    alone is not equivalent here — it only falls back to `""` when
    `key` is *absent*, not when it is present and explicitly `None`
    (`_default_string_settings`'s own shape), which every optional
    numeric field in `string_settings_edit` needs to handle correctly.
    """
    return "" if value is None else value


def _find_candidate_choice(
    entity_id: str | None, attribute: str | None, candidates: list[BaselineCandidate]
) -> str | None:
    """Inverse of `_resolve_candidate_choice`: given a stored baseline
    override (or `None`), find the dropdown value that would reproduce
    it, or `None` if it doesn't match any currently-discovered candidate
    (e.g. the candidate disappeared, or this is a manual entry).
    """
    if entity_id is None:
        return None
    for index, candidate in enumerate(candidates):
        if candidate.entity_id == entity_id and candidate.attribute == attribute:
            return str(index)
    return None


# --- "baseline" step (global, first) -----------------------------------


def _baseline_schema(candidates: list[BaselineCandidate], defaults: dict[str, Any]) -> vol.Schema:
    """The `baseline` step's schema (ADR-010)."""
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
        }
    )


def _normalize_baseline(
    user_input: dict[str, Any], candidates: list[BaselineCandidate]
) -> dict[str, Any]:
    """Convert a validated `baseline` submission into the canonical
    config-entry data keys (`const.py`'s `CONF_*` globals).
    """
    candidate = _resolve_candidate_choice(user_input["baseline_candidate"], candidates)
    if candidate is not None:
        baseline_entity_id: str | None = candidate.entity_id
        baseline_attribute: str | None = candidate.attribute
        baseline_shape: str | None = candidate.shape
        # ADR-009 §1c Amendment / ADR-012 §2a Amendment (`TASK-0034`) —
        # carried through unchanged alongside the three fields above,
        # never itself user-entered; `None` for every candidate except a
        # `forecast_solar` one whose companion history entity was
        # resolved at discovery time.
        baseline_history_entity_id: str | None = candidate.history_entity_id
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
        # A manual entry is never `forecast_solar`-shaped (that shape is
        # discovery-only, ADR-009 §1b) so it never has a linked history
        # entity either (ADR-009 §1c Amendment).
        baseline_history_entity_id = None
    return {
        CONF_BASELINE_ENTITY_ID: baseline_entity_id,
        CONF_BASELINE_ATTRIBUTE: baseline_attribute,
        CONF_BASELINE_SHAPE: baseline_shape,
        CONF_BASELINE_HISTORY_ENTITY_ID: baseline_history_entity_id,
        CONF_TEMPERATURE_AWARE: user_input[CONF_TEMPERATURE_AWARE],
    }


def _baseline_defaults(data: dict[str, Any], candidates: list[BaselineCandidate]) -> dict[str, Any]:
    """Reconstruct `baseline` step form defaults from the flow's
    in-progress (or reconfigure-seeded) data dict — the inverse of
    `_normalize_baseline`.
    """
    entity_id = data.get(CONF_BASELINE_ENTITY_ID)
    attribute = data.get(CONF_BASELINE_ATTRIBUTE)
    baseline_choice = _find_candidate_choice(entity_id, attribute, candidates) or (
        BASELINE_CANDIDATE_MANUAL
    )
    return {
        "baseline_candidate": baseline_choice,
        "baseline_manual_entity_id": entity_id or "",
        "baseline_manual_attribute": attribute or "",
        "baseline_manual_shape": data.get(CONF_BASELINE_SHAPE) or _DEFAULT_MANUAL_SHAPE,
        CONF_TEMPERATURE_AWARE: data.get(CONF_TEMPERATURE_AWARE, False),
    }


# --- "strings" step (multi-select) --------------------------------------


def _strings_schema(default_entity_ids: list[str]) -> vol.Schema:
    """The `strings` step's schema (ADR-010): exactly one multi-select
    entity selector — every entity picked here *is* a string, identified
    by its own `entity_id`. No other field belongs on this step.
    """
    return vol.Schema(
        {
            vol.Required(CONF_STRINGS, default=list(default_entity_ids)): selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain="sensor", device_class=["power", "energy"], multiple=True
                )
            )
        }
    )


def _default_string_settings() -> dict[str, Any]:
    """A freshly-picked string's settings, before `string_settings_edit`
    has ever touched it — every field at its no-op/global-following
    default, matching what `string_settings_edit`'s own schema defaults
    to.
    """
    return {
        CONF_STRING_NAME: "",
        CONF_STRING_BASELINE_ENTITY_ID: None,
        CONF_STRING_BASELINE_ATTRIBUTE: None,
        CONF_STRING_BASELINE_SHAPE: None,
        CONF_STRING_BASELINE_HISTORY_ENTITY_ID: None,
        CONF_STRING_TEMPERATURE_AWARE: False,
        CONF_STRING_CONVERTER_LIMIT_W: None,
        CONF_STRING_TEMPERATURE_SOURCE: None,
        CONF_STRING_TEMPERATURE_COEFFICIENT: DEFAULT_STRING_TEMPERATURE_COEFFICIENT,
        CONF_STRING_RATED_DC_CAPACITY_WP: None,
    }


# --- "string_settings_hub" step (loop dispatcher) -----------------------


def _hub_choices(strings: dict[str, dict[str, Any]]) -> dict[str, str]:
    """Build the hub's `vol.In`-compatible dropdown: every currently
    picked string's `entity_id`, labelled with its name if already set
    this session else the `entity_id` itself, plus a "Done" sentinel.
    """
    choices = {
        entity_id: (str(settings.get(CONF_STRING_NAME) or "").strip() or entity_id)
        for entity_id, settings in strings.items()
    }
    choices[STRING_SETTINGS_HUB_DONE] = "Done"
    return choices


def _hub_schema(strings: dict[str, dict[str, Any]]) -> vol.Schema:
    choices = _hub_choices(strings)
    return vol.Schema(
        {vol.Required("entity_id", default=STRING_SETTINGS_HUB_DONE): vol.In(choices)}
    )


# --- "string_settings_edit" step (one entity_id at a time) --------------


def _string_settings_edit_schema(
    candidates: list[BaselineCandidate], defaults: dict[str, Any]
) -> vol.Schema:
    """The `string_settings_edit` step's schema (ADR-010). Every field is
    always shown — no "configure advanced corrections?" gate; which of
    them actually applies is resolved from the *stored* data by
    downstream consumers (`providers/temperature.py`, TASK-0010), not by
    dynamically hiding fields within this static form.
    """
    choices = _candidate_choices(candidates, include_none=True)
    default_override = defaults.get("baseline_override", BASELINE_CANDIDATE_NONE)
    return vol.Schema(
        {
            vol.Optional(CONF_STRING_NAME, default=defaults.get(CONF_STRING_NAME, "")): str,
            vol.Required("baseline_override", default=default_override): vol.In(choices),
            vol.Optional(
                CONF_STRING_TEMPERATURE_SOURCE,
                default=defaults.get(CONF_STRING_TEMPERATURE_SOURCE, ""),
            ): str,
            vol.Optional(
                CONF_STRING_CONVERTER_LIMIT_W,
                default=defaults.get(CONF_STRING_CONVERTER_LIMIT_W, ""),
            ): vol.Any("", vol.Coerce(float)),
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


def _string_settings_defaults(
    existing: dict[str, Any], candidates: list[BaselineCandidate]
) -> dict[str, Any]:
    """Reconstruct `string_settings_edit` step form defaults from an
    already-stored per-string settings dict — the inverse of
    `_build_string_settings`.
    """
    override_choice = (
        _find_candidate_choice(
            existing.get(CONF_STRING_BASELINE_ENTITY_ID),
            existing.get(CONF_STRING_BASELINE_ATTRIBUTE),
            candidates,
        )
        or BASELINE_CANDIDATE_NONE
    )
    return {
        CONF_STRING_NAME: existing.get(CONF_STRING_NAME, ""),
        "baseline_override": override_choice,
        CONF_STRING_TEMPERATURE_SOURCE: existing.get(CONF_STRING_TEMPERATURE_SOURCE) or "",
        CONF_STRING_CONVERTER_LIMIT_W: _blank_if_none(existing.get(CONF_STRING_CONVERTER_LIMIT_W)),
        CONF_STRING_TEMPERATURE_COEFFICIENT: existing.get(
            CONF_STRING_TEMPERATURE_COEFFICIENT, DEFAULT_STRING_TEMPERATURE_COEFFICIENT
        ),
        CONF_STRING_RATED_DC_CAPACITY_WP: _blank_if_none(
            existing.get(CONF_STRING_RATED_DC_CAPACITY_WP)
        ),
    }


def _build_string_settings(
    user_input: dict[str, Any], candidates: list[BaselineCandidate]
) -> dict[str, Any]:
    """Convert a validated `string_settings_edit` submission into that
    string's settings dict (everything except its `entity_id`, which is
    the `CONF_STRINGS` key it is stored under, not a field of its own).
    """
    candidate = _resolve_candidate_choice(user_input["baseline_override"], candidates)
    temperature_source = str(user_input.get(CONF_STRING_TEMPERATURE_SOURCE) or "").strip()
    return {
        CONF_STRING_NAME: user_input.get(CONF_STRING_NAME, ""),
        CONF_STRING_BASELINE_ENTITY_ID: candidate.entity_id if candidate else None,
        CONF_STRING_BASELINE_ATTRIBUTE: candidate.attribute if candidate else None,
        CONF_STRING_BASELINE_SHAPE: candidate.shape if candidate else None,
        # ADR-009 §1c Amendment / ADR-012 §2a Amendment (`TASK-0034`) — same
        # carry-through as `_normalize_baseline` above.
        CONF_STRING_BASELINE_HISTORY_ENTITY_ID: candidate.history_entity_id if candidate else None,
        # A string with a baseline override is, by definition, treated as
        # temperature-aware — no separate flag is asked (ADR-003b §1c /
        # ADR-010's `string_settings_edit` note).
        CONF_STRING_TEMPERATURE_AWARE: candidate is not None,
        CONF_STRING_CONVERTER_LIMIT_W: _optional_float(
            user_input.get(CONF_STRING_CONVERTER_LIMIT_W)
        ),
        CONF_STRING_TEMPERATURE_SOURCE: temperature_source or None,
        CONF_STRING_TEMPERATURE_COEFFICIENT: user_input[CONF_STRING_TEMPERATURE_COEFFICIENT],
        CONF_STRING_RATED_DC_CAPACITY_WP: _optional_float(
            user_input.get(CONF_STRING_RATED_DC_CAPACITY_WP)
        ),
    }


# --- "regression_tuning" step (global) -----------------------------------


def _regression_tuning_schema(defaults: dict[str, Any]) -> vol.Schema:
    """The `regression_tuning` step's schema (ADR-010)."""
    return vol.Schema(
        {
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
        }
    )


def _normalize_regression_tuning(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_WINDOW_DAYS: user_input[CONF_WINDOW_DAYS],
        CONF_REGRESSION_METHOD: user_input[CONF_REGRESSION_METHOD],
        CONF_SMOOTHING_RADIUS: user_input[CONF_SMOOTHING_RADIUS],
        CONF_NEIGHBOR_FITTING_CUTOFF: user_input[CONF_NEIGHBOR_FITTING_CUTOFF],
        CONF_RECENCY_DECAY_MAX: user_input[CONF_RECENCY_DECAY_MAX],
        CONF_CLIPPING_THRESHOLD: user_input[CONF_CLIPPING_THRESHOLD],
    }


def _regression_tuning_defaults(data: dict[str, Any]) -> dict[str, Any]:
    return {
        CONF_WINDOW_DAYS: data.get(CONF_WINDOW_DAYS, DEFAULT_WINDOW_DAYS),
        CONF_REGRESSION_METHOD: data.get(CONF_REGRESSION_METHOD, DEFAULT_REGRESSION_METHOD),
        CONF_SMOOTHING_RADIUS: data.get(CONF_SMOOTHING_RADIUS, DEFAULT_SMOOTHING_RADIUS),
        CONF_NEIGHBOR_FITTING_CUTOFF: data.get(
            CONF_NEIGHBOR_FITTING_CUTOFF, DEFAULT_NEIGHBOR_FITTING_CUTOFF
        ),
        CONF_RECENCY_DECAY_MAX: data.get(CONF_RECENCY_DECAY_MAX, DEFAULT_RECENCY_DECAY_MAX),
        CONF_CLIPPING_THRESHOLD: data.get(CONF_CLIPPING_THRESHOLD, DEFAULT_CLIPPING_THRESHOLD),
    }


# --- "advanced_optional" step (global, last of the linear sequence) -----


def _advanced_optional_schema(defaults: dict[str, Any]) -> vol.Schema:
    """The `advanced_optional` step's schema (ADR-010)."""
    return vol.Schema(
        {
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


def _normalize_advanced_optional(user_input: dict[str, Any]) -> dict[str, Any]:
    return {
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


def _advanced_optional_defaults(data: dict[str, Any]) -> dict[str, Any]:
    return {
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


class ShadyConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore[misc, call-arg]
    """Setup and reconfigure flow (ADR-010). `async_step_user` walks the
    five sections linearly; `async_step_reconfigure` opens on a menu of
    the same sections instead, returning to that menu after each one.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._candidates: list[BaselineCandidate] = []
        # Flat, canonical `entry.data`-shaped dict (minus `CONF_STRINGS`),
        # accumulated across `baseline`/`regression_tuning`/
        # `advanced_optional` submissions — seeded from the existing
        # entry's data on reconfigure, empty on first setup. Reading
        # defaults back out of this one dict (rather than tracking
        # "linear in-progress" and "reconfigure prefill" separately) is
        # what lets every step's default-computation stay reconfigure-
        # agnostic (`homeassistant.helpers.schema_config_entry_flow`
        # itself documents this "one evolving dict" pattern for a flow
        # that serves both entry points).
        self._data: dict[str, Any] = {}
        # `entity_id -> settings dict`, same "one evolving dict" pattern
        # as `self._data` above, for `CONF_STRINGS`.
        self._strings: dict[str, dict[str, Any]] = {}
        # Which string `string_settings_edit` currently targets — the
        # `homeassistant.helpers.schema_config_entry_flow`-documented
        # "sub-item being edited" pattern.
        self._editing_entity_id: str | None = None
        # `None` during first setup; the entry being reconfigured once
        # `async_step_reconfigure` has run — distinguishes linear-vs-menu
        # dispatch in every step method below.
        self._reconfigure_entry: ConfigEntry | None = None

    # -- entry points ------------------------------------------------

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """HA's conventional user-initiated entry point; immediately
        delegates to ADR-010's own first step, `baseline`.
        """
        return await self.async_step_baseline(user_input)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Opens on a menu of the same five sections `async_step_user`
        walks linearly (ADR-010) — no `async_set_unique_id`/
        `_abort_if_unique_id_mismatch`: this integration defines no
        `unique_id` scheme (one relevant config entry per physical
        installation, no external account to mismatch), so there is no
        identity here for a mismatch to protect against.
        """
        if self._reconfigure_entry is None:
            self._reconfigure_entry = self._get_reconfigure_entry()
            entry_data = self._reconfigure_entry.data
            self._data = {k: v for k, v in entry_data.items() if k != CONF_STRINGS}
            self._strings = {
                entity_id: dict(settings)
                for entity_id, settings in entry_data.get(CONF_STRINGS, {}).items()
            }
        if not self._candidates:
            self._candidates = await discover_baseline_candidates(self.hass)
        return await self._async_reconfigure_menu()

    async def _async_reconfigure_menu(self) -> FlowResult:
        return self.async_show_menu(
            step_id=_STEP_RECONFIGURE,
            menu_options=[
                _STEP_BASELINE,
                _STEP_STRINGS,
                _STEP_REGRESSION_TUNING,
                _STEP_ADVANCED_OPTIONAL,
                "finish",
            ],
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """ "Save & Finish" — commits every accumulated change (from
        whichever sections were actually visited; unvisited sections'
        fields are still present in `self._data`/`self._strings`, seeded
        from the entry at `async_step_reconfigure` entry) via HA's own
        recommended reconfigure-commit helper: updates `entry.data`
        directly, reloads the entry, and aborts with
        `reason="reconfigure_successful"` in one call.
        """
        assert self._reconfigure_entry is not None
        return self.async_update_reload_and_abort(
            self._reconfigure_entry,
            data_updates={**self._data, CONF_STRINGS: self._strings},
        )

    # -- "baseline" ----------------------------------------------------

    async def async_step_baseline(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if not self._candidates:
            self._candidates = await discover_baseline_candidates(self.hass)
        if user_input is not None:
            self._data.update(_normalize_baseline(user_input, self._candidates))
            if self._reconfigure_entry is not None:
                return await self._async_reconfigure_menu()
            return await self.async_step_strings()
        return self.async_show_form(
            step_id=_STEP_BASELINE,
            data_schema=_baseline_schema(
                self._candidates, _baseline_defaults(self._data, self._candidates)
            ),
        )

    # -- "strings" -------------------------------------------------------

    async def async_step_strings(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            selected: list[str] = list(user_input[CONF_STRINGS])
            # Removing an entity from the multi-select discards its
            # settings entirely (ADR-010) — nothing retained for a
            # possible later re-add within the same session. A still-
            # selected entity keeps whatever settings it already has
            # (freshly default if this is its first time being picked).
            self._strings = {
                entity_id: self._strings.get(entity_id) or _default_string_settings()
                for entity_id in selected
            }
            return await self._after_strings_step()
        return self.async_show_form(
            step_id=_STEP_STRINGS, data_schema=_strings_schema(list(self._strings.keys()))
        )

    async def _after_strings_step(self) -> FlowResult:
        if self._strings:
            return await self.async_step_string_settings_hub()
        if self._reconfigure_entry is not None:
            return await self._async_reconfigure_menu()
        return await self.async_step_regression_tuning()

    # -- "string_settings_hub" / "string_settings_edit" ------------------

    async def async_step_string_settings_hub(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            choice = user_input["entity_id"]
            if choice == STRING_SETTINGS_HUB_DONE:
                if self._reconfigure_entry is not None:
                    return await self._async_reconfigure_menu()
                return await self.async_step_regression_tuning()
            self._editing_entity_id = choice
            return await self.async_step_string_settings_edit()
        return self.async_show_form(
            step_id=_STEP_STRING_SETTINGS_HUB, data_schema=_hub_schema(self._strings)
        )

    async def async_step_string_settings_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        entity_id = self._editing_entity_id
        assert entity_id is not None
        if user_input is not None:
            self._strings[entity_id] = _build_string_settings(user_input, self._candidates)
            self._editing_entity_id = None
            return await self.async_step_string_settings_hub()
        defaults = _string_settings_defaults(self._strings[entity_id], self._candidates)
        return self.async_show_form(
            step_id=_STEP_STRING_SETTINGS_EDIT,
            data_schema=_string_settings_edit_schema(self._candidates, defaults),
        )

    # -- "regression_tuning" ----------------------------------------------

    async def async_step_regression_tuning(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._data.update(_normalize_regression_tuning(user_input))
            if self._reconfigure_entry is not None:
                return await self._async_reconfigure_menu()
            return await self.async_step_advanced_optional()
        return self.async_show_form(
            step_id=_STEP_REGRESSION_TUNING,
            data_schema=_regression_tuning_schema(_regression_tuning_defaults(self._data)),
        )

    # -- "advanced_optional" (last of the linear sequence) ----------------

    async def async_step_advanced_optional(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        if user_input is not None:
            self._data.update(_normalize_advanced_optional(user_input))
            if self._reconfigure_entry is not None:
                return await self._async_reconfigure_menu()
            return self.async_create_entry(
                title="Shady", data={**self._data, CONF_STRINGS: self._strings}
            )
        return self.async_show_form(
            step_id=_STEP_ADVANCED_OPTIONAL,
            data_schema=_advanced_optional_schema(_advanced_optional_defaults(self._data)),
        )
