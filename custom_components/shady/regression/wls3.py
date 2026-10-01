"""`wls3` strategy (ADR-001 §2): weighted least squares, degree 3 — adds
`FC^3`. Most flexible of the parametric options; risks overfitting with
the small pool sizes in play here, and demonstrated worse extrapolation
than `wls2` outside the training range in ADR-001 §2's worked example —
deliberately not the default for that reason, though still available."""

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

DEGREE = 3


@dataclass(frozen=True)
class Wls3FittedModel(FittedModel):
    """`coefficients`, shape `(n_slots, 4)`: `[1, FC, FC^2, FC^3]` coefficients."""

    coefficients: NDArray[np.float64]
    confidence: NDArray[np.float64]

    def predict_unclamped(
        self, fc: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        raw = evaluate_polynomial(self.coefficients, fc)
        raw = passthrough_where_no_confidence(raw, fc, self.confidence)
        return raw, self.confidence


def fit(pool: SamplePool) -> Wls3FittedModel:
    coefficients = fit_weighted_polynomial(pool, degree=DEGREE)
    return Wls3FittedModel(coefficients=coefficients, confidence=pool.confidence)
