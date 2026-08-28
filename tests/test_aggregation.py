"""Zero-mocking tests for `aggregation.py` (ADR-005, ADR-000 §6,
TASK-0012).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


agg_mod = _load("aggregation.py", "shady.aggregation")

_T0 = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


# -- ADR-005 §1/§2: cross-string sum -----------------------------------------


class TestSumValues:
    """Given a list of per-string values, some of which may be
    unavailable, When summed, Then unavailable entries are excluded
    rather than zeroed, and an all-unavailable list sums to `None`."""

    def test_sums_present_floats(self) -> None:
        assert agg_mod.sum_values([100.0, 200.0, 50.0]) == 350.0

    def test_none_entries_excluded_not_zeroed(self) -> None:
        assert agg_mod.sum_values([100.0, None, 50.0]) == 150.0

    def test_all_none_is_none_not_zero(self) -> None:
        assert agg_mod.sum_values([None, None]) is None

    def test_empty_is_none(self) -> None:
        assert agg_mod.sum_values([]) is None

    def test_single_value_passes_through(self) -> None:
        assert agg_mod.sum_values([42.0]) == 42.0


# -- ADR-005 §3/§4: slot-power -> energy ------------------------------------


class TestSlotEnergyWh:
    def test_converts_power_to_5_minute_energy(self) -> None:
        # 600 W for 5 minutes = 50 Wh.
        assert agg_mod.slot_energy_wh(600.0) == 50.0

    def test_zero_power_is_zero_energy(self) -> None:
        assert agg_mod.slot_energy_wh(0.0) == 0.0


class TestDayEnergyTotalWh:
    """Given a day's 288-slot `slot_values` array (possibly with gaps),
    When the daily total is computed, Then it is the sum of each
    valid slot's energy, ignoring `None` slots entirely (ADR-005 §3)."""

    def test_sums_every_slot(self) -> None:
        # Four slots at 600 W each = 200 Wh.
        assert agg_mod.day_energy_total_wh([600.0, 600.0, 600.0, 600.0]) == 200.0

    def test_none_slots_contribute_nothing(self) -> None:
        assert agg_mod.day_energy_total_wh([600.0, None, 600.0]) == 100.0

    def test_all_none_is_zero(self) -> None:
        assert agg_mod.day_energy_total_wh([None, None]) == 0.0

    def test_empty_is_zero(self) -> None:
        assert agg_mod.day_energy_total_wh([]) == 0.0


class TestRemainingEnergyWh:
    """Given §3's own `(slot_timestamps, slot_values)` arrays, When
    restricted to slots at/after `now`, Then only those slots'
    energy is summed — reusing §3's array, no separate mechanism
    (ADR-005 §4)."""

    def test_only_future_slots_counted(self) -> None:
        timestamps = [_T0, _T0 + timedelta(minutes=5), _T0 + timedelta(minutes=10)]
        values = [600.0, 600.0, 600.0]
        # now = the second slot's own timestamp: that slot and the
        # third both count (>=), the first (past) does not.
        now = _T0 + timedelta(minutes=5)
        assert agg_mod.remaining_energy_wh(timestamps, values, now) == 100.0

    def test_none_slots_within_the_future_range_still_excluded(self) -> None:
        timestamps = [_T0, _T0 + timedelta(minutes=5)]
        values = [600.0, None]
        assert agg_mod.remaining_energy_wh(timestamps, values, _T0) == 50.0

    def test_now_after_every_slot_is_zero(self) -> None:
        timestamps = [_T0, _T0 + timedelta(minutes=5)]
        values = [600.0, 600.0]
        now = _T0 + timedelta(hours=1)
        assert agg_mod.remaining_energy_wh(timestamps, values, now) == 0.0


# -- ADR-005 §5/§6: trapezoidal energy increment -----------------------------


class TestTrapezoidalEnergyIncrement:
    """Given a previous and current `(timestamp, power)` sample, When
    the increment between them is computed, Then it matches the
    trapezoidal rule — average power x elapsed time (ADR-005 §5/§6's
    implementation notes)."""

    def test_correct_wh_increment_for_a_5_minute_interval(self) -> None:
        previous = (_T0, 400.0)
        current = (_T0 + timedelta(minutes=5), 600.0)
        # Average power 500 W over 5/60 h = 41.666... Wh.
        expected = 500.0 * (5.0 / 60.0)
        assert agg_mod.trapezoidal_energy_increment(previous, current) == expected

    def test_constant_power_over_one_hour_is_exactly_that_power(self) -> None:
        previous = (_T0, 1000.0)
        current = (_T0 + timedelta(hours=1), 1000.0)
        assert agg_mod.trapezoidal_energy_increment(previous, current) == 1000.0

    def test_no_previous_sample_contributes_zero(self) -> None:
        current = (_T0, 500.0)
        assert agg_mod.trapezoidal_energy_increment(None, current) == 0.0

    def test_non_advancing_timestamp_contributes_zero(self) -> None:
        previous = (_T0, 400.0)
        current = (_T0, 600.0)
        assert agg_mod.trapezoidal_energy_increment(previous, current) == 0.0

    def test_out_of_order_timestamp_contributes_zero_not_negative(self) -> None:
        previous = (_T0, 400.0)
        current = (_T0 - timedelta(minutes=5), 600.0)
        assert agg_mod.trapezoidal_energy_increment(previous, current) == 0.0
