"""`wls3` strategy (ADR-001 §2): weighted least squares, degree 3 — adds
`FC^3`. Most flexible of the parametric options; risks overfitting with
the small pool sizes in play here, and demonstrated worse extrapolation
than `wls2` outside the training range in ADR-001 §2's worked example —
deliberately not the default for that reason, though still available."""

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

DEGREE = 3


@dataclass(frozen=True)
class Wls3FittedModel:
    """`coefficients`, shape `(n_slots, 4)`: `[1, FC, FC^2, FC^3]` coefficients."""

    coefficients: np.ndarray
    confidence: np.ndarray

    def predict(self, fc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        raw = evaluate_polynomial(self.coefficients, fc)
        raw = passthrough_where_no_confidence(raw, fc, self.confidence)
        return clamp_to_forecast(raw, fc), self.confidence


def fit(pool: SamplePool) -> Wls3FittedModel:
    coefficients = fit_weighted_polynomial(pool, degree=DEGREE)
    return Wls3FittedModel(coefficients=coefficients, confidence=pool.confidence)
