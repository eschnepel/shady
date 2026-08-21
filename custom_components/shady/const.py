"""Constants for the Shady integration."""

DOMAIN = "shady"

CONF_STRINGS = "strings"
CONF_ID = "id"
CONF_NAME = "name"

CONF_BASELINE_ENTITY_ID = "baseline_entity_id"
CONF_BASELINE_ATTRIBUTE = "baseline_attribute"
CONF_BASELINE_ALLOWS_TEMPERATURE_CORRECTION = "baseline_allows_temperature_correction"

CONF_WINDOW_DAYS = "window_days"
CONF_REGRESSION_METHOD = "regression_method"
CONF_SMOOTHING_RADIUS = "smoothing_radius"
CONF_NEIGHBOR_FITTING_CUTOFF = "neighbor_fitting_cutoff"
CONF_CLIPPING_THRESHOLD = "clipping_threshold"
CONF_MAX_UPLIFT_C = "max_uplift_c"
CONF_TEMPERATURE_SOURCE_ENTITY_ID = "temperature_source_entity_id"
CONF_TEMPERATURE_REGRESSION_METHOD = "temperature_regression_method"
CONF_INTRADAY_CORRECTION_MODE = "intraday_correction_mode"
CONF_INTRADAY_CORRECTION_CUTOFF = "intraday_correction_cutoff"
CONF_WINDOW_SLOTS = "window_slots"
CONF_RAMP_SLOTS = "ramp_slots"

CONF_ACTUAL_YIELD_ENTITY_ID = "actual_yield_entity_id"
CONF_CONVERTER_LIMIT = "converter_limit"
CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID = "temperature_source_override_entity_id"
CONF_TEMPERATURE_COEFFICIENT = "temperature_coefficient"
CONF_RATED_DC_CAPACITY = "rated_dc_capacity"
CONF_TEMPERATURE_AWARE = "temperature_aware"

DEFAULT_WINDOW_DAYS = 28
DEFAULT_REGRESSION_METHOD = "wls2"
DEFAULT_SMOOTHING_RADIUS = 1
DEFAULT_NEIGHBOR_FITTING_CUTOFF = 0.25
DEFAULT_CLIPPING_THRESHOLD = 0.98
DEFAULT_MAX_UPLIFT_C = 25
DEFAULT_TEMPERATURE_REGRESSION_METHOD = "wls2"
DEFAULT_INTRADAY_CORRECTION_MODE = "off"
DEFAULT_INTRADAY_CORRECTION_CUTOFF = 0.10
DEFAULT_WINDOW_SLOTS = 24
DEFAULT_RAMP_SLOTS = 12
