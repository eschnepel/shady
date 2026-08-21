"""Third-degree weighted least squares strategy."""

from __future__ import annotations

import numpy as np

from .base import PolynomialRegressionModel, _fit_weighted_polynomial


def fit(samples: np.ndarray) -> PolynomialRegressionModel:
    return _fit_weighted_polynomial(samples, degree=3)
