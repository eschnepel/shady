"""Kernel regression strategy."""

from __future__ import annotations

import numpy as np

from .base import KernelRegressionModel, _fit_kernel


def fit(samples: np.ndarray) -> KernelRegressionModel:
    return _fit_kernel(samples)
