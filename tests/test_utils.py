from __future__ import annotations

from datetime import datetime, timezone

from ._module_loader import load_module


utils = load_module("shady.utils", "utils.py")


class _Base:
    def method(self) -> None:
        pass


class _Derived(_Base):
    def method(self) -> None:
        pass


def test_slot_helpers_normalize_and_round():
    moment = datetime(2026, 8, 21, 12, 3, tzinfo=timezone.utc)

    assert utils._slot_index(moment) == 144
    assert utils._ceil_to_slot(moment).replace(tzinfo=timezone.utc) == datetime(2026, 8, 21, 12, 5, tzinfo=timezone.utc)
    assert utils._naive_utc(moment) == datetime(2026, 8, 21, 12, 3)


def test_select_fit_function_and_override_detection():
    assert utils._select_fit_function("linear") is not None
    assert utils._is_overridden(_Derived(), "method", _Base) is True
    assert utils._is_overridden(_Base(), "method", _Base) is False
