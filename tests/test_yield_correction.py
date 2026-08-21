from __future__ import annotations

import numpy as np

from ._module_loader import load_module


correction = load_module("shady.yield_correction", "yield_correction.py")


def test_clipping_exclusion_drops_samples_at_or_above_threshold():
    samples = np.array([[100.0, 97.0], [200.0, 196.0], [300.0, 150.0]], dtype=float)
    filtered = correction.exclude_clipped_samples(samples, inverter_limit=200.0, clipping_threshold=0.98)

    assert filtered.shape == (2, 2)
    assert np.all(filtered[:, 1] < 196.0)


def test_temperature_derating_round_trip_recovers_original_value():
    corrected = correction.apply_temperature_derating(100.0, 35.0, -0.004)
    restored = correction.reverse_temperature_derating(corrected, 35.0, -0.004)

    assert np.isclose(restored, 100.0)


def test_temperature_uplift_boundaries_are_respected():
    assert correction.estimate_cell_temperature_from_ambient(20.0, 0.0, 1000.0) == 20.0
    assert correction.estimate_cell_temperature_from_ambient(20.0, 1000.0, 1000.0) == 45.0


def test_provider_already_corrects_skips_both_sides():
    assert correction.apply_temperature_derating(100.0, 35.0, -0.004, provider_already_corrects=True) == 100.0
    assert correction.reverse_temperature_derating(100.0, 35.0, -0.004, provider_already_corrects=True) == 100.0
