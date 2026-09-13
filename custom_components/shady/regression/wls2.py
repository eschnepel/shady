"""`wls2` strategy (ADR-001 §2, default): weighted least squares, degree
2 — adds `FC^2`. Captures gentle curvature: a soft approach to an
inverter limit, and the diffuse/direct-light bending shading itself
plausibly produces. Chosen as the default over `linear` for this
physical reason, and over `wls3` for its better-behaved extrapolation
outside the training range (see ADR-001 §2's worked-example discussion)."""

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

DEGREE = 2


@dataclass(frozen=True)
class Wls2FittedModel(FittedModel):
    """`coefficients`, shape `(n_slots, 3)`: `[1, FC, FC^2]` coefficients."""

    coefficients: NDArray[np.float64]
    confidence: NDArray[np.float64]

    def predict_unclamped(
        self, fc: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        raw = evaluate_polynomial(self.coefficients, fc)
        raw = passthrough_where_no_confidence(raw, fc, self.confidence)
        return raw, self.confidence


def fit(pool: SamplePool) -> Wls2FittedModel:
    coefficients = fit_weighted_polynomial(pool, degree=DEGREE)
    return Wls2FittedModel(coefficients=coefficients, confidence=pool.confidence)
