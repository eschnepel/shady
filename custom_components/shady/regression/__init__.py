"""Regression strategies for Shady."""

from .base import (
    KernelRegressionModel,
    PolynomialRegressionModel,
    build_training_pool,
    magnitude_weight,
    time_weight,
)
from .kernel import fit as fit_kernel
from .linear import fit as fit_linear
from .wls2 import fit as fit_wls2
from .wls3 import fit as fit_wls3

__all__ = [
    "KernelRegressionModel",
    "PolynomialRegressionModel",
    "build_training_pool",
    "fit_kernel",
    "fit_linear",
    "fit_wls2",
    "fit_wls3",
    "magnitude_weight",
    "time_weight",
]
