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

**Note for future tasks (carried over from this task's own spec):**
ADR-006 §1b's canonical ordering is raw-predict -> reverse-transform ->
intraday correction -> clamp, last. Intraday correction does not exist
yet at this task's time of implementation (TASK-0013) — the clamp is
implemented as the final step after the reverse-transform for now;
TASK-0013 will need to extend this module to insert its own correction
ahead of the clamp.
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
    shape `(n_slots,)` — the full ADR-006 §1b pipeline for one string:

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
    3. `clamp_output` — the one final clamp, last.

    `target_cell_temperature`, `coefficient_per_c`, `inverter_limit`,
    and `provider_already_corrects` are this string's own resolved
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
    adjusted = clamp_output(reverse_transformed, fc, inverter_limit)
    return adjusted, confidence
