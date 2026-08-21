from __future__ import annotations

from datetime import datetime, timedelta

from ._module_loader import load_module


aggregation = load_module("shady.aggregation", "aggregation.py")


def test_trapezoidal_energy_increment_matches_expected_wh():
    start = datetime(2026, 8, 21, 12, 0)
    end = start + timedelta(minutes=5)

    assert aggregation.trapezoidal_energy_increment((start, 100.0), (end, 50.0)) == 6.25


def test_sum_slot_rows_and_total_energy_from_series():
    start = datetime(2026, 8, 21, 0, 0)
    rows = [{"a": 1.0, "b": 2.0}, {"a": 3.0, "b": 4.0}]
    series = [(start, 0.0), (start + timedelta(minutes=5), 10.0), (start + timedelta(minutes=10), 20.0)]

    assert aggregation.sum_slot_rows(rows) == [3.0, 7.0]
    assert abs(aggregation.total_energy_from_series(series) - 1.6666666666666667) < 1e-9


def test_intraday_helpers_cover_ramp_and_blend():
    assert aggregation.ramp_weight(0, 12) == 0.0
    assert aggregation.ramp_weight(6, 12) == 0.5
    assert aggregation.ramp_weight(18, 12) == 1.0
    assert aggregation.ramp_weight(2, 0) == 1.0

    assert aggregation.intraday_correction_factor(100.0, 80.0, 0.5, 0.10) == 1.05
    assert aggregation.intraday_correction_factor(0.0, 80.0, 0.5, 0.10) == 1.0
    assert aggregation.crossfade(10.0, 20.0, 0.25) == 12.5


def test_diagnostic_accuracy_clamps_negative_values():
    assert aggregation.diagnostic_accuracy(100.0, 100.0) == 100.0
    assert aggregation.diagnostic_accuracy(50.0, 100.0) == 50.0
    assert aggregation.diagnostic_accuracy(250.0, 100.0) == 0.0
