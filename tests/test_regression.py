"""Zero-mocking tests for `regression/` (ADR-001 §2/§2a/§3/§3a, ADR-011
§1-§3, ADR-008 §1, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test these dependency-free modules. Scenario
fixtures are shared functions reused across all four strategies, per
ADR-000 §6's explicit testing philosophy, rather than bespoke data per
strategy.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


base_mod = _load("regression/base.py", "shady.regression.base")
linear_mod = _load("regression/linear.py", "shady.regression.linear")
wls2_mod = _load("regression/wls2.py", "shady.regression.wls2")
wls3_mod = _load("regression/wls3.py", "shady.regression.wls3")
kernel_mod = _load("regression/kernel.py", "shady.regression.kernel")

ALL_STRATEGIES = [linear_mod, wls2_mod, wls3_mod, kernel_mod]

RNG_SEED = 20260821


# -- shared scenario fixtures (ADR-000 §6: reused across all four strategies) --


def _hard_shading_edge_pool() -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """A pool with a hard shading edge crossing mid-window: for the
    center offset's target slots, the first half of the rolling window's
    days is unshaded (PV/FC ~ 0.9) and the second half is heavily shaded
    (PV/FC ~ 0.3) — a genuinely non-stationary, non-trivial training set,
    not clean single-regime noise. Neighbor offsets carry ordinary,
    single-regime data.
    """
    rng = np.random.default_rng(RNG_SEED)
    n_slots = 5
    window_days = 20
    half = window_days // 2

    fc_by_offset: dict[int, np.ndarray] = {}
    pv_by_offset: dict[int, np.ndarray] = {}
    for offset in (-1, 0, 1):
        fc = rng.uniform(50.0, 1200.0, size=(n_slots, window_days))
        if offset == 0:
            ratio = np.empty((n_slots, window_days))
            ratio[:, :half] = 0.9
            ratio[:, half:] = 0.3
        else:
            ratio = np.full((n_slots, window_days), 0.7)
        pv = fc * ratio + rng.normal(0, 3.0, size=(n_slots, window_days))
        pv = np.clip(pv, 0.0, None)
        fc_by_offset[offset] = fc
        pv_by_offset[offset] = pv
    return fc_by_offset, pv_by_offset


def _clipping_ceiling_pool() -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """A pool where PV saturates at a ceiling for high-FC samples
    (inverter-clipping-style), all comfortably within a moderate FC
    range — used to query predict() at an FC well *above* anything ever
    seen in training (ADR-001 §2's documented extrapolation scenario)."""
    rng = np.random.default_rng(RNG_SEED + 1)
    n_slots = 4
    window_days = 24
    ceiling = 600.0

    fc_by_offset: dict[int, np.ndarray] = {}
    pv_by_offset: dict[int, np.ndarray] = {}
    for offset in (-1, 0, 1):
        fc = rng.uniform(100.0, 900.0, size=(n_slots, window_days))
        pv = np.minimum(fc * 0.85, ceiling) + rng.normal(0, 2.0, size=(n_slots, window_days))
        pv = np.clip(pv, 0.0, None)
        fc_by_offset[offset] = fc
        pv_by_offset[offset] = pv
    return fc_by_offset, pv_by_offset


def _deviating_neighbor_pool(
    smoothing_radius: int = 1,
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    """A center slot with a stable PV/FC ~ 0.8, and a `+1` neighbor whose
    PV/FC sits at ~0.3 — a deviation of 0.5, comfortably past the default
    `neighbor_fitting_cutoff` of 0.25 (ADR-011 §2). The `-1` neighbor
    stays close to the center (deviation ~0) as a control."""
    rng = np.random.default_rng(RNG_SEED + 2)
    n_slots = 3
    window_days = 16

    fc_by_offset: dict[int, np.ndarray] = {}
    pv_by_offset: dict[int, np.ndarray] = {}
    ratios = {-1: 0.78, 0: 0.8, 1: 0.3}
    for offset in range(-smoothing_radius, smoothing_radius + 1):
        ratio = ratios.get(offset, 0.8)
        fc = rng.uniform(200.0, 800.0, size=(n_slots, window_days))
        pv = fc * ratio + rng.normal(0, 1.5, size=(n_slots, window_days))
        pv = np.clip(pv, 0.0, None)
        fc_by_offset[offset] = fc
        pv_by_offset[offset] = pv
    return fc_by_offset, pv_by_offset


# -- AC1: clamp invariant across all four strategies -----------------------


class TestClampInvariantAcrossAllStrategies:
    """Given the shared hard-shading-edge scenario fixture, when each of
    the four strategies fits and predicts on it, every strategy's output
    satisfies 0 <= predicted <= FC for every sample (ADR-000 §6
    invariant)."""

    def test_clamp_holds_for_every_strategy_and_query(self) -> None:
        fc_by_offset, pv_by_offset = _hard_shading_edge_pool()
        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=1, neighbor_fitting_cutoff=0.25
        )
        n_slots = fc_by_offset[0].shape[0]

        query_values = [0.0, 1.0, 250.0, 600.0, 1500.0, 5000.0]
        for strategy in ALL_STRATEGIES:
            model = strategy.fit(pool)
            for query in query_values:
                fc_query = np.full(n_slots, query)
                adjusted, confidence = model.predict(fc_query)
                assert adjusted.shape == (n_slots,)
                assert confidence.shape == (n_slots,)
                assert np.all(adjusted >= 0.0), f"{strategy.__name__} went negative at FC={query}"
                assert np.all(
                    adjusted <= fc_query
                ), f"{strategy.__name__} exceeded FC at FC={query}"


# -- AC2: wls2/wls3 extrapolation safety ------------------------------------


class TestExtrapolationSafetyWls2Wls3:
    """Given a scenario with samples at/above a clipping-style ceiling,
    when wls2/wls3 predict at an out-of-training-range FC, the output
    still respects the clamp invariant (ADR-001 §2)."""

    def test_extrapolation_beyond_training_range_stays_clamped(self) -> None:
        fc_by_offset, pv_by_offset = _clipping_ceiling_pool()
        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=1, neighbor_fitting_cutoff=0.25
        )
        n_slots = fc_by_offset[0].shape[0]
        max_training_fc = max(arr.max() for arr in fc_by_offset.values())

        # Well outside anything seen in training — the exact scenario
        # ADR-001 §2 flags as the normal, not edge-case, query pattern.
        extreme_fc = np.full(n_slots, max_training_fc * 5.0)

        for strategy in (wls2_mod, wls3_mod):
            model = strategy.fit(pool)
            adjusted, _confidence = model.predict(extreme_fc)
            assert np.all(adjusted >= 0.0)
            assert np.all(adjusted <= extreme_fc)


# -- AC3: magnitude_weight_i is smooth, only exactly 0 at FC_i == 0 --------


class TestMagnitudeWeightSmoothNearZeroFC:
    """Given a pool with near-zero-FC samples (sunrise/sunset), when
    weights are computed, magnitude_weight_i smoothly approaches (but is
    only exactly 0 at) FC_i == 0 (ADR-001 §2)."""

    def test_weight_is_continuous_and_zero_only_at_exact_zero(self) -> None:
        # Isolate magnitude_weight_i cleanly: radius=0 (no neighbors, so
        # time_weight == 1.0 everywhere) and every sample valid, so the
        # center-offset weight block *is* magnitude_weight_i directly.
        fc_values = np.array([[0.0, 0.001, 1.0, 10.0, 100.0, 500.0, 1000.0]])
        pv_values = fc_values * 0.6

        fc_by_offset = {0: fc_values}
        pv_by_offset = {0: pv_values}
        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=0, neighbor_fitting_cutoff=0.25
        )
        weights = pool.weight[0]

        # Exactly 0 only where FC_i == 0.
        assert weights[0] == 0.0
        assert np.all(weights[1:] > 0.0)

        # Smooth/monotonically non-decreasing with FC (no hard cutoff,
        # no discontinuity) — every step up in FC gives a step up (or at
        # worst equal) weight.
        assert np.all(np.diff(weights) >= 0.0)

        # A small-but-nonzero FC gets a small-but-nonzero weight, not
        # excluded outright.
        assert 0.0 < weights[1] < weights[2]


# -- AC4: neighbor hard exclusion at a shading boundary ---------------------


class TestNeighborHardExclusion:
    """Given a center slot and a neighbor slot whose median PV/FC ratio
    deviates beyond neighbor_fitting_cutoff (default 0.25), when the pool
    is built, that neighbor's entire series is hard-excluded
    (time_weight_i forced to 0), not merely downweighted (ADR-011 §2)."""

    def test_deviating_neighbor_is_fully_excluded(self) -> None:
        fc_by_offset, pv_by_offset = _deviating_neighbor_pool(smoothing_radius=1)
        window_days = fc_by_offset[0].shape[1]

        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=1, neighbor_fitting_cutoff=0.25
        )

        # Pool column layout: offsets concatenated in order [-1, 0, 1],
        # each contributing `window_days` columns.
        deviating_neighbor_block = pool.weight[:, 2 * window_days : 3 * window_days]
        assert np.all(deviating_neighbor_block == 0.0)

        # The control (-1) neighbor, which agrees with the center, keeps
        # nonzero weight — proving the exclusion is specific to the
        # deviating series, not a global effect of any nonzero cutoff.
        agreeing_neighbor_block = pool.weight[:, 0:window_days]
        assert np.any(agreeing_neighbor_block > 0.0)

        # The center's own samples are of course unaffected either way.
        center_block = pool.weight[:, window_days : 2 * window_days]
        assert np.any(center_block > 0.0)


# -- AC5: rescale sentinel (-1%) retains and corrects instead of excluding -


class TestNeighborRescale:
    """Given neighbor_fitting_cutoff = -1% (the rescale sentinel), when
    the same deviating neighbor is processed, it is rescaled to the
    center slot's median and retained, not excluded (ADR-011 §3)."""

    def test_deviating_neighbor_is_rescaled_and_retained(self) -> None:
        fc_by_offset, pv_by_offset = _deviating_neighbor_pool(smoothing_radius=1)
        window_days = fc_by_offset[0].shape[1]

        pool = base_mod.build_pool(
            fc_by_offset,
            pv_by_offset,
            smoothing_radius=1,
            neighbor_fitting_cutoff=base_mod.RESCALE_SENTINEL,
        )

        deviating_fc = pool.fc[:, 2 * window_days : 3 * window_days]
        deviating_pv = pool.pv[:, 2 * window_days : 3 * window_days]
        deviating_weight = pool.weight[:, 2 * window_days : 3 * window_days]

        # Retained: nonzero weight, unlike the hard-exclusion case above.
        assert np.any(deviating_weight > 0.0)

        # Rescaled: the neighbor's ratio now sits at the *center's*
        # median (~0.8), not its own original median (~0.3).
        with np.errstate(divide="ignore", invalid="ignore"):
            rescaled_ratio = np.where(deviating_fc > 0, deviating_pv / deviating_fc, np.nan)
        center_fc = fc_by_offset[0]
        center_pv = pv_by_offset[0]
        center_median = np.median(center_pv / center_fc, axis=1, keepdims=True)

        assert np.allclose(
            np.nanmedian(rescaled_ratio, axis=1, keepdims=True), center_median, rtol=0.05
        )


# -- AC6: confidence is identical across all four methods -------------------


class TestConfidenceMethodIndependence:
    """Given confidence is computed for the same pool across all four
    strategies, when compared, confidence is identical regardless of
    which strategy produced the point estimate (ADR-001 §2)."""

    def test_confidence_matches_across_all_strategies(self) -> None:
        fc_by_offset, pv_by_offset = _hard_shading_edge_pool()
        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=1, neighbor_fitting_cutoff=0.25
        )
        n_slots = fc_by_offset[0].shape[0]
        fc_query = np.full(n_slots, 400.0)

        confidences = []
        for strategy in ALL_STRATEGIES:
            model = strategy.fit(pool)
            _adjusted, confidence = model.predict(fc_query)
            confidences.append(confidence)

        for confidence in confidences[1:]:
            assert np.allclose(confidence, confidences[0])
        # And it must equal the pool's own precomputed confidence exactly
        # — every strategy reads it straight off the shared SamplePool.
        for confidence in confidences:
            assert np.array_equal(confidence, pool.confidence)


# -- Cold start: documented pass-through fallback (not one of the 6 ACs, --
# -- but directly follows from ADR-001's cold-start Consequences bullet) --


class TestColdStartPassthrough:
    """Given a pool with zero weight everywhere (no historical samples
    yet), every strategy passes the raw forecast value through unmodified
    rather than trusting a numerically-arbitrary regularized fit."""

    def test_zero_weight_pool_passes_forecast_through(self) -> None:
        n_slots = 2
        window_days = 5
        fc_by_offset = {o: np.full((n_slots, window_days), np.nan) for o in (-1, 0, 1)}
        pv_by_offset = {o: np.full((n_slots, window_days), np.nan) for o in (-1, 0, 1)}
        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=1, neighbor_fitting_cutoff=0.25
        )
        assert np.array_equal(pool.confidence, np.zeros(n_slots))

        fc_query = np.array([123.0, 456.0])
        for strategy in ALL_STRATEGIES:
            model = strategy.fit(pool)
            adjusted, confidence = model.predict(fc_query)
            assert np.allclose(adjusted, fc_query)
            assert np.array_equal(confidence, np.zeros(n_slots))


class TestSmoothingRadiusZeroReproducesIndependentSlots:
    """A smoothing_radius=0 pool contains only the center offset,
    reproducing ADR-001 §3a's strictly-independent-slots behavior."""

    def test_radius_zero_pool_has_only_center_columns(self) -> None:
        n_slots, window_days = 2, 6
        fc_by_offset = {0: np.full((n_slots, window_days), 300.0)}
        pv_by_offset = {0: np.full((n_slots, window_days), 200.0)}

        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=0, neighbor_fitting_cutoff=0.25
        )

        assert pool.fc.shape == (n_slots, window_days)


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda mod: mod.__name__.split(".")[-1])
class TestEveryStrategyHandlesTheSharedFixtures:
    """Sanity: every strategy fits and predicts without error against
    both shared fixtures, returning correctly-shaped, finite output."""

    def test_hard_shading_edge_fixture(self, strategy: ModuleType) -> None:
        fc_by_offset, pv_by_offset = _hard_shading_edge_pool()
        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=1, neighbor_fitting_cutoff=0.25
        )
        n_slots = fc_by_offset[0].shape[0]
        adjusted, confidence = strategy.fit(pool).predict(np.full(n_slots, 300.0))
        assert np.all(np.isfinite(adjusted))
        assert np.all(np.isfinite(confidence))

    def test_clipping_ceiling_fixture(self, strategy: ModuleType) -> None:
        fc_by_offset, pv_by_offset = _clipping_ceiling_pool()
        pool = base_mod.build_pool(
            fc_by_offset, pv_by_offset, smoothing_radius=1, neighbor_fitting_cutoff=0.25
        )
        n_slots = fc_by_offset[0].shape[0]
        adjusted, confidence = strategy.fit(pool).predict(np.full(n_slots, 300.0))
        assert np.all(np.isfinite(adjusted))
        assert np.all(np.isfinite(confidence))
