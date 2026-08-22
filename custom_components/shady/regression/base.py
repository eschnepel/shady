"""`regression/base.py` — shared pool-construction and fitting machinery
every strategy in `regression/` (linear, kernel, wls2, wls3) relies on
before its own `fit()` runs (ADR-001 §2, ADR-011 §1-§3, ADR-008 §1).

No `cache.py` coupling: `build_pool` operates on raw, already-assembled
`numpy` arrays handed to it — pools are passed in, not fetched. No
`hass` import anywhere in this module (ADR-000 §3/§6).

**Input contract for `build_pool`** (this task's own design decision,
since `cache.py`'s `get_regression_pools` accessor — ADR-008 §2 — is out
of scope here and TASK-0006 hasn't run yet): `fc_by_offset`/`pv_by_offset`
are `dict[int, np.ndarray]` keyed by neighbor slot offset (`0` = the
target slot itself, `-radius..+radius` = its temporal neighbors, ADR-011
§1), each value shaped `(n_slots, window_days)` — one row per target
slot in the batch, one column per day in the rolling window, **already
aligned** so row `s` in every offset's array refers to the same target
slot `s` (the caller has already applied any 288-slot wraparound). `NaN`
marks an invalid/not-yet-available raw sample, doubling as pad exactly
as ADR-008 §2 establishes for `cache.py`'s own shadow array. Whoever
eventually wires `cache.py`'s `get_regression_pools` (TASK-0006) or
`coordinator.py` (TASK-0010) up to this function must produce (or adapt
to) this exact shape.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

import numpy as np

# The rescale sentinel (ADR-011 §3): "-1%", expressed in the same
# fractional convention `neighbor_fitting_cutoff` (a plain 0-1 fraction,
# e.g. 0.25 for the 25% default) already uses.
RESCALE_SENTINEL = -0.01

# Tiny ridge term added to every batched normal-equations solve purely for
# numerical stability (a genuinely zero-weight row would otherwise be an
# exactly-singular matrix) — negligible next to any real weighted sum,
# never meant to bias a well-populated slot's fit.
_RIDGE_EPSILON = 1e-8


@dataclass(frozen=True)
class SamplePool:
    """Batched, padded, fully-weighted training samples for a sweep of
    slots (ADR-008 §1) — the output of `build_pool` and the shared input
    every strategy's `fit()` consumes.

    `fc`, `pv`, `weight` all share shape `(n_slots, pool_width)`. `fc`/
    `pv` are already NaN-free ("safe"): a pad/invalid/excluded position
    holds `0.0` in both, and `0.0` in `weight` — safe to use directly in
    any weighted arithmetic with no further NaN-guarding needed.
    `confidence`, shape `(n_slots,)`, is `weight.sum(axis=1)` — computed
    once here so it is identical regardless of which strategy's `fit()`
    a caller goes on to use (ADR-001 §2's method-independence guarantee).
    """

    fc: np.ndarray
    pv: np.ndarray
    weight: np.ndarray
    confidence: np.ndarray


class FittedModel(Protocol):
    """Shared protocol every strategy's fitted model implements
    (ADR-001 §2)."""

    def predict(self, fc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """`fc`, shape `(n_slots,)` → `(adjusted_forecast, confidence)`,
        both shape `(n_slots,)`. `adjusted_forecast` is always clamped to
        `[0, fc]` (ADR-001 §2, ADR-000 §8)."""
        ...


def clamp_to_forecast(adjusted: np.ndarray, fc: np.ndarray) -> np.ndarray:
    """Clamp a raw prediction to `[0, FC]` — never negative, never more
    than the slot's own raw forecast value (ADR-001 §2). Applied
    unconditionally, so it holds even for a wild out-of-training-range
    extrapolation (ADR-001 §2's `wls2`/`wls3` extrapolation-safety note).
    `fc` is itself floored at `0.0` first, defensively (ADR-000 §8: pure
    calculation modules use clamps, not validation errors, for
    unexpected input)."""
    safe_fc = np.maximum(fc, 0.0)
    return np.asarray(np.clip(adjusted, 0.0, safe_fc))


def passthrough_where_no_confidence(
    adjusted: np.ndarray, fc: np.ndarray, confidence: np.ndarray
) -> np.ndarray:
    """A slot with zero pool weight (cold start: no historical samples
    yet) has nothing to base a fit on — its regression coefficients are
    numerically arbitrary (from `_RIDGE_EPSILON`'s regularization, not
    real evidence). Falling back to the raw forecast value there mirrors
    ADR-001's documented cold-start behavior: "a freshly-configured
    string effectively passes the baseline through unmodified"."""
    return np.where(confidence > 0.0, adjusted, fc)


def _magnitude_weight(fc: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """`magnitude_weight_i` (ADR-001 §2): continuous, downweights samples
    with a near-zero `FC_i`, exactly `0` only at `FC_i == 0`. Scaled
    against the pool's own per-row maximum valid `FC` — scale-invariant,
    no installation-specific constant needed."""
    masked_fc = np.where(valid_mask, fc, 0.0)
    row_max = masked_fc.max(axis=1, keepdims=True)
    with np.errstate(divide="ignore", invalid="ignore"):
        weight = np.where(row_max > 0, masked_fc / row_max, 0.0)
    return np.asarray(weight)


def _median_ratio(fc: np.ndarray, pv: np.ndarray, valid_mask: np.ndarray) -> np.ndarray:
    """`median(PV_i / FC_i)` per row, over valid, `FC_i > 0` entries only
    (ADR-011 §2/§3). `NaN` for a row with no such entries."""
    ratio_mask = valid_mask & (fc > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(ratio_mask, pv / np.where(fc > 0, fc, 1.0), np.nan)
    with warnings.catch_warnings():
        # An all-NaN row (no valid samples at all for this offset/slot)
        # is an expected, benign case here, not a bug to surface.
        warnings.simplefilter("ignore", category=RuntimeWarning)
        return np.asarray(np.nanmedian(ratio, axis=1))


def build_pool(
    fc_by_offset: Mapping[int, np.ndarray],
    pv_by_offset: Mapping[int, np.ndarray],
    smoothing_radius: int,
    neighbor_fitting_cutoff: float,
) -> SamplePool:
    """Build one batch's fully-weighted `SamplePool` from raw per-offset
    arrays (ADR-001 §2's `magnitude_weight_i`, ADR-011 §1's
    `time_weight_i`, and ADR-011 §2/§3's neighbor exclusion/rescale).

    `fc_by_offset`/`pv_by_offset` must contain exactly the offsets
    `-smoothing_radius .. +smoothing_radius` (a `smoothing_radius=0` pool
    is just the center slot, reproducing ADR-001 §3a's
    strictly-independent-slots behavior).
    """
    offsets = list(range(-smoothing_radius, smoothing_radius + 1))
    center_fc = fc_by_offset[0]
    center_valid = ~np.isnan(center_fc) & ~np.isnan(pv_by_offset[0])
    center_median = _median_ratio(center_fc, pv_by_offset[0], center_valid)

    fc_blocks: list[np.ndarray] = []
    pv_blocks: list[np.ndarray] = []
    weight_blocks: list[np.ndarray] = []

    for offset in offsets:
        raw_fc = fc_by_offset[offset]
        raw_pv = pv_by_offset[offset]
        valid_mask = ~np.isnan(raw_fc) & ~np.isnan(raw_pv)

        magnitude_weight = _magnitude_weight(raw_fc, valid_mask)
        time_weight = 1.0 - abs(offset) / (smoothing_radius + 1)

        pv_contribution = raw_pv
        neighbor_scale = np.ones(raw_fc.shape[0])

        if offset != 0:
            neighbor_median = _median_ratio(raw_fc, raw_pv, valid_mask)
            with np.errstate(divide="ignore", invalid="ignore"):
                deviation = np.abs(neighbor_median - center_median) / center_median

            if neighbor_fitting_cutoff == RESCALE_SENTINEL:
                # §3: never exclude, always rescale to the center's median.
                # A NaN/zero center or neighbor median makes the
                # correction factor undefined — fall back to *no*
                # rescale (factor 1.0) rather than corrupting pv with NaN.
                undefined = (
                    np.isnan(center_median) | np.isnan(neighbor_median) | (neighbor_median == 0)
                )
                with np.errstate(divide="ignore", invalid="ignore"):
                    factor = np.where(undefined, 1.0, center_median / neighbor_median)
                neighbor_scale = factor
            else:
                # §2: hard exclusion. A NaN deviation (center or neighbor
                # row has no comparable data yet, e.g. cold start) is
                # left un-excluded — an unjudgeable neighbor is trusted
                # rather than defeating cold-start smoothing entirely;
                # `valid_mask`/`magnitude_weight` already zero out rows
                # with no real data regardless.
                excluded = deviation > neighbor_fitting_cutoff
                magnitude_weight = np.where(excluded[:, None], 0.0, magnitude_weight)

        pv_contribution = raw_pv * neighbor_scale[:, None]
        combined_weight = magnitude_weight * time_weight * valid_mask

        fc_blocks.append(np.where(valid_mask, raw_fc, 0.0))
        pv_blocks.append(np.where(valid_mask, pv_contribution, 0.0))
        weight_blocks.append(combined_weight)

    fc_pool = np.concatenate(fc_blocks, axis=1)
    pv_pool = np.concatenate(pv_blocks, axis=1)
    weight_pool = np.concatenate(weight_blocks, axis=1)
    confidence = weight_pool.sum(axis=1)

    return SamplePool(fc=fc_pool, pv=pv_pool, weight=weight_pool, confidence=confidence)


def fit_weighted_polynomial(pool: SamplePool, degree: int) -> np.ndarray:
    """Batched weighted-least-squares polynomial fit (ADR-008 §1): one
    `numpy.linalg.solve` call for every slot in the batch at once, never
    one call per slot. Returns coefficients, shape `(n_slots, degree+1)`,
    lowest power first (`coefficients[:, 0]` is the intercept).

    Shared by `linear.py` (`degree=1`), `wls2.py` (`degree=2`), and
    `wls3.py` (`degree=3`) — the only difference between those three
    strategies is this one parameter.
    """
    powers = np.arange(degree + 1)
    design = pool.fc[:, :, None] ** powers[None, None, :]  # (n_slots, pool_width, degree+1)
    weight = pool.weight

    xt_w_x = np.einsum("npi,np,npj->nij", design, weight, design)
    xt_w_y = np.einsum("npi,np,np->ni", design, weight, pool.pv)

    ridge = np.eye(degree + 1) * _RIDGE_EPSILON
    xt_w_x_regularized = xt_w_x + ridge[None, :, :]

    # numpy >= 2.0: `b` is only treated as a shape-(M,) vector if it is
    # *exactly* 1-D; otherwise it's a stack of (M, K) matrices, not an
    # implicit (..., M) vector stack. Add an explicit trailing K=1 axis
    # for the batched per-slot solve, then drop it again.
    solved = np.linalg.solve(xt_w_x_regularized, xt_w_y[..., None])
    coefficients: np.ndarray = solved[..., 0]
    return coefficients


def evaluate_polynomial(coefficients: np.ndarray, fc: np.ndarray) -> np.ndarray:
    """Evaluate a batch of polynomials (one per row of `coefficients`) at
    `fc`, shape `(n_slots,)`. Shared by `linear.py`/`wls2.py`/`wls3.py`'s
    `predict()`."""
    degree = coefficients.shape[1] - 1
    powers = np.arange(degree + 1)
    design = fc[:, None] ** powers[None, :]  # (n_slots, degree+1)
    result: np.ndarray = np.einsum("ni,ni->n", design, coefficients)
    return result
