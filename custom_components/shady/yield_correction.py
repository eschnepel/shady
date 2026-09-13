"""`yield_correction.py` — optional per-string yield corrections: inverter
clipping exclusion (ADR-003a) and temperature derating (ADR-003b).

Pure, stateless functions — no HA imports, no `cache.py`/`regression/`
coupling; `cell_temperature`/`target_cell_temperature` values are always
supplied by the caller (already resolved by `providers/temperature.py`
and, for the cell/ambient tiers' prediction-time forecast, ADR-003c's
learned model). Both corrections are no-ops when their configuration is
absent, matching the pattern ADR-004 §1 establishes for optional features
elsewhere.

Used at two points in the pipeline (ADR-003b §2): forward, preparing a
string's training data (`exclude_clipped` + `derate_actual_to_reference`),
and in reverse, finishing a fitted model's prediction
(`apply_derate_to_prediction`) — `forecast_adjust.py` (TASK-0008) is the
reverse-direction caller. Callers preparing training data should apply
`exclude_clipped` *before* `derate_actual_to_reference`: the clipping
threshold (ADR-003a §1) is a raw physical inverter limit, evaluated
against the un-normalized actual-yield value, not a temperature-corrected
one.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

# ADR-003a §1: global default clipping-threshold fraction of a configured
# inverter AC power limit.
DEFAULT_CLIPPING_THRESHOLD = 0.98

# ADR-003b §1: the standard-test-condition reference temperature every
# derated sample/prediction is normalized to and from.
REFERENCE_TEMPERATURE_C = 25.0

# ADR-003b §1a: global default maximum ambient->cell uplift at full rated
# output.
DEFAULT_MAX_UPLIFT_C = 25.0


def exclude_clipped(
    actual_yield: NDArray[np.float64],
    inverter_limit: float | None,
    clipping_threshold: float = DEFAULT_CLIPPING_THRESHOLD,
) -> NDArray[np.float64]:
    """ADR-003a §1/§2: exclude (not downweight) samples at/above
    `clipping_threshold` of `inverter_limit` from a string's training
    data, by marking them `NaN` — the same "invalid" sentinel
    `regression/base.py`'s `build_pool` (ADR-008 §2) already treats as
    fully excluded (zero weight), so a caller can hand this function's
    output straight to `build_pool` with no further masking step.

    No-op — returns `actual_yield` unchanged, same object, no copy — when
    no inverter limit is configured for the string (ADR-003a §2), the
    common case for an installation with no clipping inverter.
    """
    if inverter_limit is None:
        return actual_yield
    excluded = actual_yield.astype(float, copy=True)
    excluded[excluded >= clipping_threshold * inverter_limit] = np.nan
    return excluded


def uplift_ambient_to_cell(
    ambient_temperature: float | NDArray[np.float64],
    baseline_forecast: float | NDArray[np.float64],
    baseline_rated_capacity: float,
    max_uplift_c: float = DEFAULT_MAX_UPLIFT_C,
) -> float | NDArray[np.float64]:
    """ADR-003b §1a: approximate a module's cell temperature from a
    global ambient/weather reading, using the string's own raw baseline
    forecast value at the same timestamp as an irradiance proxy —

        cell_temperature ~= ambient_temperature
            + max_uplift_c * (baseline_forecast / baseline_rated_capacity)

    `0` uplift at `baseline_forecast == 0` (dawn/dusk/night, module at
    ambient temperature); the full `max_uplift_c` at
    `baseline_forecast == baseline_rated_capacity` (full rated output) —
    both boundary conditions hold exactly, by construction.

    Used for the ambient-sensor and weather-integration temperature tiers
    only (ADR-003b §1a) — a module/cell-sensor tier reads cell
    temperature directly and never calls this. Callers are responsible
    for skipping this (and, with it, the entire derating correction) when
    `baseline_rated_capacity` is left unset for a string that needs it
    (ADR-003b §1a's "skip both sides rather than degrade one" rule) —
    this function itself has no sentinel for "unset" and always evaluates
    the formula it is given.
    """
    return ambient_temperature + max_uplift_c * (baseline_forecast / baseline_rated_capacity)


def derate_actual_to_reference(
    actual_raw: float | NDArray[np.float64],
    cell_temperature: float | NDArray[np.float64] | None,
    coefficient_per_c: float | None,
    *,
    provider_already_corrects: bool = False,
) -> float | NDArray[np.float64]:
    """ADR-003b §1: forward transform — normalize a raw actual-yield
    sample to its 25 C-equivalent value *before* `ratio_i` is formed
    (ADR-001 §2), so `regression/` never sees a temperature-biased
    sample:

        actual_corrected = actual_raw / (1 + coefficient_per_c * (cell_temperature - 25))

    No-op — returns `actual_raw` unchanged — when `provider_already_corrects`
    is set (ADR-003b §1c: the configured baseline provider already models
    temperature internally, e.g. Solcast) or when either
    `coefficient_per_c` or `cell_temperature` is `None` (not configured
    for this string / source not resolved, ADR-003b §2) — the same
    "no-op when not configured" pattern `exclude_clipped` follows above,
    and ADR-003b §1c's "skip together" rule this function's reverse
    counterpart also follows.
    """
    if provider_already_corrects or coefficient_per_c is None or cell_temperature is None:
        return actual_raw
    return actual_raw / (1.0 + coefficient_per_c * (cell_temperature - REFERENCE_TEMPERATURE_C))


def apply_derate_to_prediction(
    predicted_at_reference: float | NDArray[np.float64],
    target_cell_temperature: float | NDArray[np.float64] | None,
    coefficient_per_c: float | None,
    *,
    provider_already_corrects: bool = False,
) -> float | NDArray[np.float64]:
    """ADR-003b §1b: reverse transform — the exact algebraic inverse of
    `derate_actual_to_reference`, converting a fitted model's
    25 C-equivalent prediction back to the *target slot's own expected*
    temperature:

        predicted_actual = predicted_at_25c * (
            1 + coefficient_per_c * (target_cell_temperature - 25)
        )

    Called by `forecast_adjust.py` (TASK-0008) after `regression/`'s
    `predict()`, before the final output clamp (ADR-006 §1b's canonical
    ordering). `target_cell_temperature` is resolved the same way
    `cell_temperature` is for training (direct reading, or
    `uplift_ambient_to_cell`) — but evaluated for the slot being
    predicted, per ADR-003b §1b.

    Same no-op conditions as the forward transform, kept in lockstep
    deliberately (ADR-003b §1c: both sides skip together, never just
    one) — a caller invoking both with mismatched flags/config would
    introduce exactly the systematic bias ADR-003b §1b's Context warns
    about.
    """
    if provider_already_corrects or coefficient_per_c is None or target_cell_temperature is None:
        return predicted_at_reference
    return predicted_at_reference * (
        1.0 + coefficient_per_c * (target_cell_temperature - REFERENCE_TEMPERATURE_C)
    )
