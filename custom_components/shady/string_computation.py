"""`string_computation.py` — the shared, pure per-string fit/predict
computation (ADR-014): training-time corrections, the regression-method
registry and fit call, and the predict-then-reverse-transform-then-clamp
sequence that turns a fitted model and a raw forecast value into the
actual (corrected) forecast.

No `cache.py` import, no `homeassistant.*` import (ADR-000 §3/§6) — one
layer above `regression/`, `forecast_adjust.py`, and
`yield_correction.py`, exactly the way `regression/base.py` itself sits
one layer above nothing (pools are passed in, not fetched). Every
function here is **slot-count-agnostic**: no signature assumes 288
slots, 1 slot, or any other specific count, so the same functions serve
`coordinator.py`'s whole-day recalibration sweep and
`diagnostics/compare_regressions.py`'s single diagnosed slot alike
(ADR-004 §4) with no branch and no second implementation.

**What moved here, verbatim in behavior, from `coordinator.py`**
(ADR-014 §2): `REGRESSION_STRATEGIES` (previously the private
`_REGRESSION_STRATEGIES` registry) and `apply_training_corrections`
(previously the private, `_StringConfig`-bound method of the same name
minus the `apply_` prefix — de-methodized here, every value it used to
read off `self`/`string` is now an explicit parameter). Neither is any
other task's declared Consumed Interface, so this is ordinary
same-module refactoring, not a Scenario C interface break.

**What's new** (ADR-014 §3): `fit_string_model` and
`predict_string_forecast`, each factoring out a pattern previously
inlined twice in `coordinator.py` (`_fit_string`/`_fit_temperature_string`
for the first; `_predict_day_basis`+`_clamp_basis` for the second) and
now needed a third time, by `diagnostics/compare_regressions.py`
(`TASK-0015b`) — which is what makes extracting it worthwhile rather
than inlining it a third time too. `predict_string_forecast` is a thin
wrapper over `forecast_adjust.adjust_forecast` (already exactly this
combined reverse-transform-then-clamp sequence) that drops the
confidence return value, since neither `coordinator.py`'s own "no
intraday correction" path nor a diagnostic single-slot caller needs it
kept alongside the adjusted value; `coordinator.py`'s intraday-ON path
still calls `forecast_adjust.reverse_transformed_forecast`/
`clamp_output` directly with its own correction step spliced in between
(ADR-006 §1b's canonical ordering) — that split-then-multi-day-clamp
shape has exactly one caller and duplicates nothing, so it is left as
`coordinator.py`'s own concern, not relocated here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from .forecast_adjust import adjust_forecast
from .regression import kernel, linear, wls2, wls3
from .regression.base import FittedModel, build_pool
from .yield_correction import derate_actual_to_reference, exclude_clipped, uplift_ambient_to_cell

# Same registry ADR-001 §2's global shading-model method choice and
# ADR-003c §2's independent temperature-forecast method both look up by
# name (`const.py`'s `REGRESSION_METHODS`) — one place mapping the four
# config-flow choices to their `regression/` module. Exported (not
# private) because `diagnostics/compare_regressions.py` (ADR-004 §4)
# iterates every entry, where `coordinator.py`'s own configured-method
# lookup only ever needs one.
REGRESSION_STRATEGIES: dict[str, Any] = {
    "linear": linear,
    "kernel": kernel,
    "wls2": wls2,
    "wls3": wls3,
}


def apply_training_corrections(
    fc_by_offset: Mapping[int, NDArray[np.float64]],
    pv_by_offset: Mapping[int, NDArray[np.float64]],
    temperature_by_offset: Mapping[int, NDArray[np.float64]] | None,
    temperature_tier: Literal["weather", "cell", "ambient"] | None,
    converter_limit_w: float | None,
    clipping_threshold: float,
    coefficient_per_c: float,
    provider_already_corrects: bool,
    rated_dc_capacity_wp: float | None,
    max_uplift_c: float,
) -> dict[int, NDArray[np.float64]]:
    """ADR-003a §1/§1a (clipping) then ADR-003b §1/§1a (temperature
    derating, all three tiers), applied per offset, in that order
    (`yield_correction.py`'s own module docstring: exclude clipped
    before deriving to reference). `weather`/`ambient` both pass their
    raw reading through `uplift_ambient_to_cell` before deriving
    (unchanged for `weather`; same formula, just training-time-resolved
    for `ambient`); `cell` uses its own reading directly, never
    evaluating that formula at all (ADR-003b §1a) — and is therefore,
    alone among the three, not gated on `rated_dc_capacity_wp` (the
    uplift formula's own required input) being configured.

    De-methodized from `coordinator.py`'s original, `_StringConfig`-
    bound `_apply_training_corrections` (ADR-014 §2) — every value the
    original read off `self`/`string` is an explicit parameter here
    instead, so this function has no dependency on `coordinator.py`'s
    private `_StringConfig` type.
    """
    needs_uplift = temperature_tier in ("weather", "ambient")
    use_temperature = (
        temperature_by_offset is not None
        and not provider_already_corrects
        and (temperature_tier == "cell" or (needs_uplift and rated_dc_capacity_wp is not None))
    )

    corrected: dict[int, NDArray[np.float64]] = {}
    for offset, pv in pv_by_offset.items():
        excluded = exclude_clipped(pv, converter_limit_w, clipping_threshold)
        cell_temperature: NDArray[np.float64] | None = None
        if use_temperature:
            assert temperature_by_offset is not None
            if needs_uplift:
                assert rated_dc_capacity_wp is not None
                uplifted = uplift_ambient_to_cell(
                    temperature_by_offset[offset],
                    fc_by_offset[offset],
                    rated_dc_capacity_wp,
                    max_uplift_c,
                )
                cell_temperature = np.asarray(uplifted, dtype=np.float64)
            else:
                cell_temperature = temperature_by_offset[offset]
        corrected[offset] = np.asarray(
            derate_actual_to_reference(
                excluded,
                cell_temperature,
                coefficient_per_c,
                provider_already_corrects=provider_already_corrects,
            ),
            dtype=np.float64,
        )
    return corrected


def fit_string_model(
    fc_by_offset: Mapping[int, NDArray[np.float64]],
    corrected_pv_by_offset: Mapping[int, NDArray[np.float64]],
    smoothing_radius: int,
    neighbor_fitting_cutoff: float,
    recency_decay_max: float,
    method: str,
    *,
    apply_magnitude_weight: bool = True,
) -> FittedModel:
    """`regression.base.build_pool` then `method`'s own `fit(pool)`
    (ADR-001 §2, ADR-008 §1) — the three-line sequence previously
    written out separately in `coordinator.py`'s `_fit_string` (the
    shading model, `apply_magnitude_weight=True`) and
    `_fit_temperature_string` (the temperature-forecast model, ADR-003c
    §2, `apply_magnitude_weight=False` — `TASK-0005-patch-5`), now one
    call both share plus a third caller, `diagnostics
    /compare_regressions.py` (ADR-004 §4), which needs it once per
    regression method rather than once for whichever method is
    currently configured.

    `method` is looked up in `REGRESSION_STRATEGIES` with no additional
    validation layer — every existing caller already only ever passes a
    value `const.py`'s `REGRESSION_METHODS`/config-flow validation
    already constrains, and `diagnostics/compare_regressions.py` iterates
    `REGRESSION_STRATEGIES`'s own keys directly rather than supplying an
    independently-sourced name (ADR-014 §6).
    """
    pool = build_pool(
        fc_by_offset,
        corrected_pv_by_offset,
        smoothing_radius,
        neighbor_fitting_cutoff,
        recency_decay_max,
        apply_magnitude_weight=apply_magnitude_weight,
    )
    strategy = REGRESSION_STRATEGIES[method]
    model: FittedModel = strategy.fit(pool)
    return model


def predict_string_forecast(
    model: FittedModel,
    fc: NDArray[np.float64],
    target_cell_temperature: NDArray[np.float64] | None,
    coefficient_per_c: float,
    provider_already_corrects: bool,
    inverter_limit: float | None,
) -> NDArray[np.float64]:
    """`forecast_adjust.adjust_forecast`'s reverse-transform-then-clamp
    sequence (ADR-006 §1b's canonical ordering), returning only the
    adjusted forecast — a thin wrapper, not a reimplementation, so this
    stays exactly in sync with `forecast_adjust.py`'s own already-tested
    behavior. Used by `coordinator.py`'s no-intraday-correction path and
    by `diagnostics/compare_regressions.py` (ADR-004 §4) alike: both
    want one already-clamped value with no correction step to insert in
    between. `coordinator.py`'s intraday-ON path does **not** use this
    — it needs Ramping/Blending's correction spliced in between the
    reverse-transform and the clamp (ADR-006 §1b), so it calls
    `forecast_adjust.reverse_transformed_forecast`/`clamp_output`
    directly instead, unchanged by this module's existence.
    """
    adjusted, _confidence = adjust_forecast(
        model,
        fc,
        target_cell_temperature,
        coefficient_per_c,
        inverter_limit,
        provider_already_corrects=provider_already_corrects,
    )
    return adjusted
