"""`linear` strategy (ADR-001 §2): weighted least squares, degree 1 —
`PV ~= beta_0 + beta_1 * FC`. The method the original proof-of-concept
validated; captures both a multiplicative scaling effect and a constant
offset (e.g. inverter standby draw)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .base import (
    SamplePool,
    clamp_to_forecast,
    evaluate_polynomial,
    fit_weighted_polynomial,
    passthrough_where_no_confidence,
)

DEGREE = 1


@dataclass(frozen=True)
class LinearFittedModel:
    """`coefficients`, shape `(n_slots, 2)`: `[intercept, FC coefficient]`."""

    coefficients: np.ndarray
    confidence: np.ndarray

    def predict(self, fc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        raw = evaluate_polynomial(self.coefficients, fc)
        raw = passthrough_where_no_confidence(raw, fc, self.confidence)
        return clamp_to_forecast(raw, fc), self.confidence


def fit(pool: SamplePool) -> LinearFittedModel:
    coefficients = fit_weighted_polynomial(pool, degree=DEGREE)
    return LinearFittedModel(coefficients=coefficients, confidence=pool.confidence)
