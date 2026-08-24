"""Constants for the Shady integration.

Config-entry data keys and defaults below mirror ADR-010's field list
and step ordering exactly (§7 of `tasks/adr-summary.md`). Grouped in the
same order ADR-010 presents them: "settings" (global) fields first, then
per-string ("add_string"/"add_string_advanced") fields.
"""

from __future__ import annotations

DOMAIN = "shady"

# Regression methods shared by the shading model (ADR-001 §2) and the
# temperature-forecast learned model (ADR-003c §2) — same four
# `regression/` strategies, two independent method choices.
REGRESSION_METHODS: tuple[str, ...] = ("linear", "kernel", "wls2", "wls3")
DEFAULT_REGRESSION_METHOD = "wls2"

# Intraday deviation-correction modes (ADR-006 §1).
INTRADAY_CORRECTION_MODES: tuple[str, ...] = ("off", "ramping", "blending")
DEFAULT_INTRADAY_CORRECTION_MODE = "off"

# Sentinel used by a config-flow "baseline candidate" dropdown to mean
# "none of these — enter the entity/attribute manually" (ADR-009 §3),
# and by a per-string "baseline candidate override" dropdown to mean
# "no override — use the global default" (ADR-010's `add_string` step).
BASELINE_CANDIDATE_MANUAL = "__manual__"
BASELINE_CANDIDATE_NONE = "__none__"

# Sentinel used by a per-string "temperature source override" field to
# mean "explicitly disable derating for this string", distinct from
# leaving the field empty ("use the global default") — ADR-010's
# `add_string_advanced` step / ADR-003b §1a.
TEMPERATURE_SOURCE_NONE = "none"

# --- "settings" step (global, first) — ADR-010 ---
CONF_BASELINE_ENTITY_ID = "baseline_entity_id"
CONF_BASELINE_ATTRIBUTE = "baseline_attribute"
CONF_BASELINE_SHAPE = "baseline_shape"
CONF_TEMPERATURE_AWARE = "temperature_aware"
CONF_WINDOW_DAYS = "window_days"
CONF_REGRESSION_METHOD = "regression_method"
CONF_SMOOTHING_RADIUS = "smoothing_radius"
CONF_NEIGHBOR_FITTING_CUTOFF = "neighbor_fitting_cutoff"
CONF_CLIPPING_THRESHOLD = "clipping_threshold"
CONF_DEFAULT_TEMPERATURE_SOURCE = "default_temperature_source"
CONF_MAX_UPLIFT_C = "max_uplift_c"
CONF_WEATHER_FORECAST_TEMPERATURE_ENTITY = "weather_forecast_temperature_entity"
CONF_TEMPERATURE_REGRESSION_METHOD = "temperature_regression_method"
CONF_INTRADAY_CORRECTION_MODE = "intraday_correction_mode"
CONF_INTRADAY_CORRECTION_CUTOFF = "intraday_correction_cutoff"
CONF_WINDOW_SLOTS = "window_slots"
CONF_RAMP_SLOTS = "ramp_slots"

DEFAULT_WINDOW_DAYS = 28
DEFAULT_SMOOTHING_RADIUS = 1
DEFAULT_NEIGHBOR_FITTING_CUTOFF = 0.25
DEFAULT_CLIPPING_THRESHOLD = 0.98
DEFAULT_MAX_UPLIFT_C = 25
DEFAULT_INTRADAY_CORRECTION_CUTOFF = 0.10
DEFAULT_WINDOW_SLOTS = 24
DEFAULT_RAMP_SLOTS = 12

# --- "strings" list — one dict per configured string, ADR-010's
# `add_string`/`add_string_advanced` steps. Stored under CONF_STRINGS on
# the config entry (ADR-010 has no dedicated key name for this — the
# Lead Agent assigns one here since it is needed to store the flow's
# per-string result at all).
CONF_STRINGS = "strings"

CONF_STRING_NAME = "name"
CONF_STRING_BASELINE_ENTITY_ID = "baseline_entity_id"
CONF_STRING_BASELINE_ATTRIBUTE = "baseline_attribute"
CONF_STRING_BASELINE_SHAPE = "baseline_shape"
CONF_STRING_TEMPERATURE_AWARE = "temperature_aware"
CONF_STRING_ACTUAL_YIELD_ENTITY = "actual_yield_entity_id"
CONF_STRING_CONFIGURE_ADVANCED = "configure_advanced"
CONF_STRING_CONVERTER_LIMIT_W = "converter_limit_w"
CONF_STRING_TEMPERATURE_SOURCE = "temperature_source_entity_id"
CONF_STRING_TEMPERATURE_COEFFICIENT = "temperature_coefficient_pct_per_c"
CONF_STRING_RATED_DC_CAPACITY_WP = "rated_dc_capacity_wp"

DEFAULT_STRING_TEMPERATURE_COEFFICIENT = -0.4
