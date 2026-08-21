from __future__ import annotations

import numpy as np

from ._module_loader import load_module


base = load_module("shady.regression.base", "regression/base.py")
linear = load_module("shady.regression.linear", "regression/linear.py")
kernel = load_module("shady.regression.kernel", "regression/kernel.py")
wls2 = load_module("shady.regression.wls2", "regression/wls2.py")
wls3 = load_module("shady.regression.wls3", "regression/wls3.py")


def _scenario_pool() -> np.ndarray:
    center = np.array(
        [
            [0.0, 0.0],
            [100.0, 90.0],
            [200.0, 170.0],
            [300.0, 240.0],
        ],
        dtype=float,
    )
    neighbor = np.array(
        [
            [0.0, 0.0],
            [100.0, 30.0],
            [200.0, 60.0],
            [300.0, 90.0],
        ],
        dtype=float,
    )
    return base.build_training_pool(center, [neighbor], smoothing_radius=1, neighbor_fitting_cutoff=0.25)


def test_magnitude_weight_is_continuous_and_zero_only_at_zero():
    assert base.magnitude_weight(0.0) == 0.0
    assert 0.0 < base.magnitude_weight(1.0) < base.magnitude_weight(1000.0)


def test_neighbor_exclusion_and_rescale_behaviors():
    center = np.array([[100.0, 90.0], [200.0, 170.0]], dtype=float)
    neighbor = np.array([[100.0, 20.0], [200.0, 40.0]], dtype=float)

    excluded = base.build_training_pool(center, [neighbor], smoothing_radius=1, neighbor_fitting_cutoff=0.25)
    assert np.allclose(excluded[2:, 2], 0.0)

    rescaled = base.build_training_pool(center, [neighbor], smoothing_radius=1, neighbor_fitting_cutoff=-0.01)
    center_median = np.median(center[:, 1] / center[:, 0])
    rescaled_neighbor_median = np.median(rescaled[2:, 1] / rescaled[2:, 0])
    assert np.isclose(rescaled_neighbor_median, center_median)


def test_all_strategies_respect_output_clamp_and_confidence():
    pool = _scenario_pool()
    models = [
        linear.fit(pool),
        kernel.fit(pool),
        wls2.fit(pool),
        wls3.fit(pool),
    ]

    outputs = [model.predict(250.0) for model in models]
    predictions = [output[0] for output in outputs]
    confidences = [output[1] for output in outputs]

    for prediction in predictions:
        assert 0.0 <= prediction <= 250.0
    assert confidences[0] == confidences[1] == confidences[2] == confidences[3]


def test_wls3_handles_out_of_training_range_safely():
    pool = _scenario_pool()
    model = wls3.fit(pool)
    prediction, confidence = model.predict(1000.0)

    assert 0.0 <= prediction <= 1000.0
    assert confidence >= 0.0
