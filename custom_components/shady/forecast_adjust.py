"""`forecast_adjust.py` — turns a fitted per-slot model and a raw
baseline series into a final adjusted forecast, in ADR-006 §1b's
canonical order: raw model prediction, then the temperature
reverse-transform (ADR-003b §1b, when configured), then the output
clamp — `[0, FC]`, or `[0, min(FC, inverter_limit)]` when an inverter
limit is configured (ADR-003a §1a) — applied exactly once, as the *last*
step.

This module has no opinion on *when* it's called, how far the input
series reaches, or which slots' models to use — that is entirely
`coordinator.py`'s concern (TASK-0010). No `cache.py`/`hass` coupling
here (ADR-000 §3/§6), same as `regression/` and `yield_correction.py`.

**Why `predict_unclamped`, not `predict`:** `regression/`'s
`FittedModel.predict()` already applies the `[0, FC]` clamp internally
(`TASK-0005`'s own design decision, made before ADR-006 §1b's ordering
rule was in view — see `TASK-0005-patch-2`). Calling `predict()` here
would clamp *before* the reverse-transform runs, which can silently
destroy information the transform needs (an extrapolated negative
prediction clamped to `0` stays exactly `0` through any subsequent
multiplicative reverse-transform, regardless of the true corrected
value) — so this module always calls `predict_unclamped()` and owns the
one true final clamp itself.

**TASK-0013 update:** `reverse_transformed_forecast` below splits steps
1-2 (raw predict + reverse-transform) out of what used to be
`adjust_forecast`'s single body, still unclamped and not yet
intraday-corrected — the exact value ADR-006 §1a/§1b call
`fc_value(t)`/`old_fc_value(t)`/`new_fc_value(t)`. `coordinator.py`
calls this directly so it can insert its own intraday-correction step
(Ramping's single multiply, or Blending's two-sided crossfade,
`aggregation.py`'s `intraday_correction_factor`/`crossfade`, ADR-006
§5) between this and `clamp_output` — exactly ADR-006 §1b's canonical
ordering. `adjust_forecast` itself is unchanged (behaviorally and in
its public signature) for callers with no intraday step to insert —
now implemented on top of `reverse_transformed_forecast` + this
module's own `clamp_output`.
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

from .regression.base import FittedModel
from .yield_correction import apply_derate_to_prediction


def clamp_output(
    adjusted: float | NDArray[np.float64],
    fc: NDArray[np.float64],
    inverter_limit: float | None = None,
) -> NDArray[np.float64]:
    """The one final output clamp (ADR-006 §1b, ADR-003a §1a): `[0, FC]`,
    or `[0, min(FC, inverter_limit)]` when a per-string inverter limit is
    configured. `fc` is floored at `0.0` first, defensively, the same
    way `regression/base.py`'s own `clamp_to_forecast` is (ADR-000 §8:
    pure calculation modules use clamps, not validation errors, for
    unexpected input) — this is a deliberately separate function from
    that one, not a reuse of it, since it additionally knows about
    `inverter_limit`, which `regression/` never does.
    """
    safe_fc = np.maximum(fc, 0.0)
    upper = safe_fc if inverter_limit is None else np.minimum(safe_fc, inverter_limit)
    return np.asarray(np.clip(adjusted, 0.0, upper))


def reverse_transformed_forecast(
    model: FittedModel,
    fc: NDArray[np.float64],
    target_cell_temperature: float | NDArray[np.float64] | None,
    coefficient_per_c: float | None,
    *,
    provider_already_corrects: bool = False,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """`fc`, shape `(n_slots,)` -> `(reverse_transformed, confidence)`,
    both shape `(n_slots,)` — steps 1-2 only of ADR-006 §1b's pipeline,
    still unclamped and not yet intraday-corrected:

    1. `model.predict_unclamped(fc)` — the raw, not-yet-clamped
       prediction (`TASK-0005-patch-2`), with the model's own cold-start
       passthrough already applied.
    2. `yield_correction.apply_derate_to_prediction` — the temperature
       reverse-transform (ADR-003b §1b), using `target_cell_temperature`
       (this call's per-slot or single expected temperature for the
       slot(s) being predicted, *not* the training-time temperature).
       No-op when `coefficient_per_c`/`target_cell_temperature` is
       `None` or `provider_already_corrects` is set — this function
       passes its own per-string configuration straight through and
       implements none of those conditions itself.

    `target_cell_temperature`, `coefficient_per_c`, and
    `provider_already_corrects` are this string's own resolved
    per-string configuration — resolving *what* they are (e.g. running
    `yield_correction.uplift_ambient_to_cell` for an ambient/weather
    temperature tier, or deciding a string is unconfigured) is the
    caller's job (`coordinator.py`, TASK-0010), not this function's.
    """
    raw, confidence = model.predict_unclamped(fc)
    reverse_transformed = apply_derate_to_prediction(
        raw,
        target_cell_temperature,
        coefficient_per_c,
        provider_already_corrects=provider_already_corrects,
    )
    return np.asarray(reverse_transformed, dtype=np.float64), confidence


def adjust_forecast(
    model: FittedModel,
    fc: NDArray[np.float64],
    target_cell_temperature: float | NDArray[np.float64] | None,
    coefficient_per_c: float | None,
    inverter_limit: float | None = None,
    *,
    provider_already_corrects: bool = False,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """`fc`, shape `(n_slots,)` -> `(adjusted_forecast, confidence)`, both
    shape `(n_slots,)` — the full ADR-006 §1b pipeline for one string,
    for callers with no intraday-correction step to insert:
    `reverse_transformed_forecast` (steps 1-2 above), then
    `clamp_output` — the one final clamp, last. `coordinator.py`
    (TASK-0013) calls the two halves separately instead, so it can
    insert its own intraday-correction step in between; this function's
    own behavior and signature are otherwise unchanged from before that
    task (ADR-006 §1a's `effective_factor` reduces to `1` when intraday
    correction is off or absent, so composing the two unconditionally
    would also be correct — this composition just avoids any
    intraday-specific plumbing for call sites that don't need it).
    """
    reverse_transformed, confidence = reverse_transformed_forecast(
        model,
        fc,
        target_cell_temperature,
        coefficient_per_c,
        provider_already_corrects=provider_already_corrects,
    )
    adjusted = clamp_output(reverse_transformed, fc, inverter_limit)
    return adjusted, confidence
