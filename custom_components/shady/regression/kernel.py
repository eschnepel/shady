"""`kernel` strategy (ADR-001 §2): locally weighted average —
`sum(w_i * PV_i) / sum(w_i)`, `w_i` additionally weighted by closeness
of `FC_i` to the query `FC`. Non-parametric: can follow a
saturating/clipping curve without assuming a functional shape, at the
cost of needing reasonable sample density across the forecast-value
range actually seen.

Unlike the three polynomial strategies, `kernel` cannot collapse a fit
down to fixed coefficients — its `FittedModel` retains the pool itself
and recomputes the weighted average on every `predict()` call (ADR-008
§2: `fit()` calls the batched pool accessor once and caches the
resulting arrays; `predict()`, the hot path, reads them directly without
ever re-touching the time-series cache).

**Kernel bandwidth — this task's own design decision** (not specified
numerically by ADR-001 §2, which only names the general shape:
"weighted... by closeness of FC_i to the query FC"): a per-slot Gaussian
bandwidth, the pool-weighted standard deviation of that slot's own valid
`FC_i` values, floored relative to that slot's own `FC` scale so a
near-constant slot's pool never produces a degenerate near-zero
bandwidth. Downstream tasks relying on `kernel`'s exact predictions
(none currently do; only the shared `predict(fc) -> (adjusted,
confidence)` interface is a fixed contract) should treat this specific
formula as an implementation detail, not a frozen contract."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .base import FittedModel, SamplePool

_BANDWIDTH_FLOOR_FRACTION = 0.01
_BANDWIDTH_ABSOLUTE_FLOOR = 1e-6


def _bandwidth(pool: SamplePool) -> NDArray[np.float64]:
    """Per-slot Gaussian bandwidth: the pool-weighted standard deviation
    of that slot's valid `FC_i` values, floored against that slot's own
    `FC` scale (see module docstring)."""
    total_weight = pool.weight.sum(axis=1)
    safe_total = np.where(total_weight > 0, total_weight, 1.0)
    weighted_mean = (pool.weight * pool.fc).sum(axis=1) / safe_total
    weighted_variance = (pool.weight * (pool.fc - weighted_mean[:, None]) ** 2).sum(
        axis=1
    ) / safe_total
    std = np.sqrt(np.maximum(weighted_variance, 0.0))

    row_max_fc = pool.fc.max(axis=1)
    floor = np.maximum(row_max_fc * _BANDWIDTH_FLOOR_FRACTION, _BANDWIDTH_ABSOLUTE_FLOOR)
    return np.asarray(np.maximum(std, floor))


@dataclass(frozen=True)
class KernelFittedModel(FittedModel):
    """Retains the pool itself (ADR-008 §2) — `predict()` recomputes a
    locally-weighted average against it on every call."""

    fc_pool: NDArray[np.float64]
    pv_pool: NDArray[np.float64]
    weight_pool: NDArray[np.float64]
    confidence: NDArray[np.float64]
    bandwidth: NDArray[np.float64]

    def predict_unclamped(
        self, fc: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        distance = self.fc_pool - fc[:, None]
        bandwidth = self.bandwidth[:, None]
        closeness = np.exp(-(distance**2) / (2 * bandwidth**2))
        weight = self.weight_pool * closeness

        total_weight = weight.sum(axis=1)
        safe_total = np.where(total_weight > 0, total_weight, 1.0)
        weighted_average = (weight * self.pv_pool).sum(axis=1) / safe_total
        # No usable neighbor weight at all for this query: pass the raw
        # forecast through unmodified, same cold-start fallback the
        # polynomial strategies use (ADR-001's documented behavior).
        adjusted = np.where(total_weight > 0, weighted_average, fc)

        return np.asarray(adjusted), self.confidence


def fit(pool: SamplePool) -> KernelFittedModel:
    return KernelFittedModel(
        fc_pool=pool.fc,
        pv_pool=pool.pv,
        weight_pool=pool.weight,
        confidence=pool.confidence,
        bandwidth=_bandwidth(pool),
    )
