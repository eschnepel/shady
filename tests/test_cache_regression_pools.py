from __future__ import annotations

import numpy as np

from ._module_loader import load_module


cache_module = load_module("shady.cache", "cache.py")


def test_shadow_array_tracks_values_and_nans():
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=lambda *_: [])
    cache.push("pv", {0: 1.5, 1: None, 2: "unavailable"}, not_before_index=0)

    shadow = cache.shadow["pv"]
    assert shadow[0] == 1.5
    assert np.isnan(shadow[1])
    assert np.isnan(shadow[2])

    cache.invalidate("pv", 0, 0)
    assert np.isnan(cache.shadow["pv"][0])


def test_get_regression_pools_returns_batched_float64_arrays():
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=lambda *_: [])
    for index in range(3):
        cache.push("pv", {index: float(index + 1)}, not_before_index=0)

    pools = cache.get_regression_pools(["pv"], smoothing_radius=1)

    assert pools["pv"].dtype == np.float64
    assert pools["pv"].shape == (288, 3)
    assert np.isnan(pools["pv"][0, 0]) or pools["pv"][0, 0] == 1.0
