"""Shared pure helpers for Shady."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Callable

import numpy as np

from .regression.base import RegressionModel
from .regression import kernel, linear, wls2, wls3

__all__ = [
    "_ceil_to_slot",
    "_is_overridden",
    "_naive_utc",
    "_select_fit_function",
    "_slot_index",
]


def _slot_index(moment: datetime) -> int:
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return (moment.hour * 60 + moment.minute) // 5


def _ceil_to_slot(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    base = moment.replace(second=0, microsecond=0)
    remainder = base.minute % 5
    if moment.second == 0 and moment.microsecond == 0 and remainder == 0:
        return base
    return base + timedelta(minutes=5 - remainder)


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _select_fit_function(method: str) -> Callable[[np.ndarray], RegressionModel]:
    if method == "linear":
        return linear.fit
    if method == "kernel":
        return kernel.fit
    if method == "wls3":
        return wls3.fit
    return wls2.fit


def _is_overridden(instance: object, method_name: str, base_type: type) -> bool:
    return getattr(type(instance), method_name) is not getattr(base_type, method_name)
