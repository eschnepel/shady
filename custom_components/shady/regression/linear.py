"""`linear` strategy (ADR-001 §2): weighted least squares, degree 1 —
`PV ~= beta_0 + beta_1 * FC`. The method the original proof-of-concept
validated; captures both a multiplicative scaling effect and a constant
offset (e.g. inverter standby draw)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from .base import (
    FittedModel,
    SamplePool,
    evaluate_polynomial,
    fit_weighted_polynomial,
    passthrough_where_no_confidence,
)

DEGREE = 1


@dataclass(frozen=True)
class LinearFittedModel(FittedModel):
    """`coefficients`, shape `(n_slots, 2)`: `[intercept, FC coefficient]`."""

    coefficients: NDArray[np.float64]
    confidence: NDArray[np.float64]

    def predict_unclamped(
        self, fc: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        raw = evaluate_polynomial(self.coefficients, fc)
        raw = passthrough_where_no_confidence(raw, fc, self.confidence)
        return raw, self.confidence


def fit(pool: SamplePool) -> LinearFittedModel:
    coefficients = fit_weighted_polynomial(pool, degree=DEGREE)
    return LinearFittedModel(coefficients=coefficients, confidence=pool.confidence)
