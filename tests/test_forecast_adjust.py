"""Zero-mocking tests for `forecast_adjust.py` (ADR-006 §1b, ADR-003a
§1a, ADR-003b §1b, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.

Uses a hand-written stub inheriting `regression.base.FittedModel`
directly — a real subclass of the production base class, not a `Mock`
(ADR-000 §6's zero-mocking philosophy).
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from numpy.typing import NDArray

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


# Note on the `# type: ignore[name-defined,misc]` markers below: `_load`
# returns a plain `ModuleType`, so `base_mod.FittedModel` is `Any` to
# mypy — and mypy specifically disallows subclassing an `Any`-typed
# expression ("Class cannot subclass ... has type Any"), independent of
# `mypy.ini`'s usual strictness settings elsewhere in this file. This is
# a structural limitation of the dynamic file-path-loading convention
# every test in this suite already uses (ADR-000 §6, matching
# `tests/test_regression.py`'s own `_load` pattern) — genuinely
# inheriting from the real, dynamically-loaded `FittedModel` base class
# below is correct and desired at runtime; mypy simply cannot verify it
# statically given how the module was loaded.


# regression.base and yield_correction must be loaded (and registered in
# sys.modules under their real dotted names) before forecast_adjust.py,
# which does `from .regression.base import FittedModel` / `from
# .yield_correction import apply_derate_to_prediction` — Python resolves
# those relative imports straight from the sys.modules cache by exact
# name, the same way test_regression.py's multi-module load order
# already relies on for `regression/linear.py`'s `from .base import ...`.
base_mod = _load("regression/base.py", "shady.regression.base")
linear_mod = _load("regression/linear.py", "shady.regression.linear")
wls2_mod = _load("regression/wls2.py", "shady.regression.wls2")
wls3_mod = _load("regression/wls3.py", "shady.regression.wls3")
kernel_mod = _load("regression/kernel.py", "shady.regression.kernel")
ALL_STRATEGIES = [linear_mod, wls2_mod, wls3_mod, kernel_mod]
yc_mod = _load("yield_correction.py", "shady.yield_correction")
fa_mod = _load("forecast_adjust.py", "shady.forecast_adjust")


@dataclass(frozen=True)
class _StubModel(base_mod.FittedModel):  # type: ignore[name-defined,misc]
    """A hand-written stand-in inheriting the real
    `regression.base.FittedModel` base class (ADR-000 §6):
    `predict_unclamped` returns `fc * multiplier`; `predict` is
    *inherited* from `FittedModel`, not overridden — so cross-checking
    against `model.predict(fc)` below also exercises the real, shared
    `clamp_to_forecast(*predict_unclamped(fc))` implementation, not a
    hand-rolled duplicate of it."""

    multiplier: float

    def predict_unclamped(
        self, fc: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        confidence = np.ones_like(fc)
        return fc * self.multiplier, confidence


# -- AC1: no clipping/derating configured -> predict(fc) clamped to [0,FC] -


class TestNoConfigMatchesClampedPredict:
    """Given a fitted model and a raw baseline series with no clipping/
    derating configured, when adjustment runs, the output is `predict(fc)`
    clamped to `[0, FC]` per slot (ADR-001 §2)."""

    def test_output_equals_predict_exactly(self) -> None:
        model = _StubModel(multiplier=1.3)  # raw > fc: exercises the clamp
        fc = np.array([100.0, 200.0, 0.0])
        adjusted, confidence = fa_mod.adjust_forecast(model, fc, None, None, None)
        expected_adjusted, expected_confidence = model.predict(fc)
        assert np.array_equal(adjusted, expected_adjusted)
        assert np.array_equal(confidence, expected_confidence)
        assert np.array_equal(adjusted, fc)  # multiplier > 1 -> clamp forces == fc

    def test_output_is_never_negative_or_above_fc(self) -> None:
        model = _StubModel(multiplier=-0.5)
        fc = np.array([100.0, 50.0])
        adjusted, _ = fa_mod.adjust_forecast(model, fc, None, None, None)
        assert (adjusted >= 0).all()
        assert (adjusted <= fc).all()


# -- AC2: inverter limit clamps below FC, not just to FC -------------------


class TestInverterLimitClampsBelowForecast:
    """Given a string with an inverter limit configured, when adjustment
    runs and a prediction would exceed that limit, the output is clamped
    to `min(FC, inverter_limit)`, not just `FC` (ADR-003a §1a)."""

    def test_prediction_above_limit_but_below_fc_is_clamped_to_the_limit(self) -> None:
        model = _StubModel(multiplier=0.95)  # raw = 950, below fc = 1000
        fc = np.array([1000.0])
        adjusted, _ = fa_mod.adjust_forecast(model, fc, None, None, inverter_limit=800.0)
        assert adjusted[0] == 800.0

    def test_no_inverter_limit_uses_fc_as_the_only_ceiling(self) -> None:
        model = _StubModel(multiplier=0.95)
        fc = np.array([1000.0])
        adjusted, _ = fa_mod.adjust_forecast(model, fc, None, None, None)
        assert adjusted[0] == 950.0


# -- AC3: reverse transform applied before the final clamp -----------------


class TestTemperatureReverseTransformBeforeClamp:
    """Given a string with temperature derating configured, when
    adjustment runs, `yield_correction.py`'s reverse transform is applied
    *before* the final clamp, using the target slot's own expected
    temperature (ADR-003b §1b)."""

    def test_reverse_transform_matches_the_manual_formula(self) -> None:
        model = _StubModel(multiplier=0.5)  # plenty of headroom below fc
        fc = np.array([1000.0])
        target_cell_temperature = 45.0
        coefficient_per_c = -0.004

        adjusted, _ = fa_mod.adjust_forecast(
            model, fc, target_cell_temperature, coefficient_per_c, None
        )

        raw = fc * 0.5
        expected_reverse_transformed = raw * (
            1 + coefficient_per_c * (target_cell_temperature - 25)
        )
        expected = np.clip(expected_reverse_transformed, 0.0, fc)
        assert np.allclose(adjusted, expected)

    def test_missing_coefficient_or_temperature_is_a_no_op_transform(self) -> None:
        model = _StubModel(multiplier=0.5)
        fc = np.array([1000.0])
        expected = np.clip(fc * 0.5, 0.0, fc)

        adjusted_no_coeff, _ = fa_mod.adjust_forecast(model, fc, 45.0, None, None)
        adjusted_no_temp, _ = fa_mod.adjust_forecast(model, fc, None, -0.004, None)
        assert np.allclose(adjusted_no_coeff, expected)
        assert np.allclose(adjusted_no_temp, expected)

    def test_provider_already_corrects_flag_forces_no_op_transform(self) -> None:
        model = _StubModel(multiplier=0.5)
        fc = np.array([1000.0])
        expected = np.clip(fc * 0.5, 0.0, fc)

        adjusted, _ = fa_mod.adjust_forecast(
            model, fc, 45.0, -0.004, None, provider_already_corrects=True
        )
        assert np.allclose(adjusted, expected)


# -- AC4: combined -- reverse transform, then clamp, exactly once, last ----


class TestCombinedOrderingReverseTransformThenClamp:
    """Given both an inverter limit and temperature derating configured,
    when adjustment runs, the ordering is: reverse transform, then the
    clamp, exactly once, last (ADR-006 §1b's canonical statement)."""

    def test_ordering_matters_transform_then_clamp_not_clamp_then_transform(self) -> None:
        # raw = 700, below inverter_limit = 850 *before* the reverse
        # transform runs. A cold target temperature (-75C) with a
        # negative coefficient scales the value *up* (factor 1.4) --
        # crossing the inverter limit only *after* the transform.
        model = _StubModel(multiplier=0.7)
        fc = np.array([1000.0])
        inverter_limit = 850.0
        target_cell_temperature = -75.0
        coefficient_per_c = -0.004

        adjusted, _ = fa_mod.adjust_forecast(
            model, fc, target_cell_temperature, coefficient_per_c, inverter_limit
        )

        raw = fc * 0.7  # 700.0 -- below inverter_limit pre-transform
        factor = 1 + coefficient_per_c * (target_cell_temperature - 25)
        reverse_transformed = raw * factor  # 980.0 -- now above inverter_limit
        correct_order_expected = np.clip(reverse_transformed, 0.0, inverter_limit)  # -> 850.0

        # The wrong order: clamp the raw prediction to inverter_limit
        # *first* (a no-op here, since 700 < 850), then transform --
        # never re-clamped afterward.
        wrong_order = np.clip(raw, 0.0, inverter_limit) * factor  # -> 980.0, uncapped

        assert np.allclose(adjusted, correct_order_expected)
        assert np.allclose(adjusted, [850.0])
        assert not np.allclose(adjusted, wrong_order)


# -- predict_unclamped is used, never predict -------------------------------


class TestUsesPredictUnclampedNotPredict:
    """`adjust_forecast` must call `predict_unclamped`, never `predict`
    (calling the already-clamped `predict` would clamp before the
    reverse-transform runs -- exactly the bug `TASK-0005-patch-2`
    exists to prevent)."""

    def test_predict_is_never_called(self) -> None:
        class _AssertingStub(base_mod.FittedModel):  # type: ignore[name-defined,misc]
            def predict_unclamped(
                self, fc: NDArray[np.float64]
            ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
                confidence = np.ones_like(fc)
                return fc * 0.5, confidence

            def predict(
                self, fc: NDArray[np.float64]
            ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
                raise AssertionError("predict() must never be called by adjust_forecast")

        fc = np.array([500.0])
        adjusted, _confidence = fa_mod.adjust_forecast(_AssertingStub(), fc, None, None, None)
        assert adjusted[0] == 250.0


# -- AUDIT-0004/TASK-0030 item 2: real strategies, not hand-built stubs ----


def _real_strategy_pool() -> object:
    """A small, deterministic (RNG-seeded) pool built via the real
    `regression.base.build_pool`, mirroring `test_regression.py`'s own
    fixture-construction style -- reused across all four real strategy
    modules below, not a per-strategy bespoke fixture."""
    n_slots = 2
    window_days = 12
    rng = np.random.default_rng(20260908)
    fc_by_offset: dict[int, NDArray[np.float64]] = {}
    pv_by_offset: dict[int, NDArray[np.float64]] = {}
    for offset in (-1, 0, 1):
        fc = np.linspace(200.0, 900.0, window_days)
        fc = np.tile(fc, (n_slots, 1)) + rng.normal(0, 5, size=(n_slots, window_days))
        pv = fc * 0.8 + rng.normal(0, 2.0, size=(n_slots, window_days))
        fc_by_offset[offset] = fc
        pv_by_offset[offset] = pv
    return base_mod.build_pool(
        fc_by_offset,
        pv_by_offset,
        smoothing_radius=1,
        neighbor_fitting_cutoff=0.25,
        recency_decay_max=0.0,
    )


@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ids=lambda mod: mod.__name__.split(".")[-1])
class TestRealStrategiesCallPredictUnclampedNotPredict:
    """Given each of the four real `regression/` strategies (not
    hand-built stubs -- mirroring `test_regression.py`'s own
    `TestEveryStrategyHandlesTheSharedFixtures` parametrization pattern),
    when `reverse_transformed_forecast`/`adjust_forecast` run with a
    temperature derate configured, the reverse transform is applied to
    the model's raw, unclamped prediction, not to `predict()`'s
    already-clamped output.

    FC=0 makes the two paths observably different for every real
    strategy: `predict(0)` always clamps to exactly `0.0`
    (`regression/base.py`'s `clamp_to_forecast` clips to `[0, 0]`), so a
    (wrong) implementation that clamped before transforming would have
    nothing left for the derate factor to multiply -- the transformed
    result would stay `0.0` regardless of the model's true raw
    prediction. The existing `TestUsesPredictUnclampedNotPredict` test
    above proves this call-pattern with one hand-built asserting stub;
    this test proves the same property holds for the four real strategy
    implementations `coordinator.py` actually uses.
    """

    def test_reverse_transform_uses_the_real_raw_prediction(self, strategy: ModuleType) -> None:
        pool = _real_strategy_pool()
        model = strategy.fit(pool)
        n_slots = 2
        fc_query = np.zeros(n_slots)
        target_cell_temperature = -75.0
        coefficient_per_c = -0.004

        reverse_transformed, confidence = fa_mod.reverse_transformed_forecast(
            model,
            fc_query,
            target_cell_temperature,
            coefficient_per_c,
            provider_already_corrects=False,
        )

        raw, expected_confidence = model.predict_unclamped(fc_query)
        correct = yc_mod.apply_derate_to_prediction(raw, target_cell_temperature, coefficient_per_c)
        clamped, _ = model.predict(fc_query)
        wrong = yc_mod.apply_derate_to_prediction(
            clamped, target_cell_temperature, coefficient_per_c
        )

        assert np.allclose(reverse_transformed, correct), (
            f"{strategy.__name__}: reverse_transformed_forecast did not match "
            "the predict_unclamped-based computation"
        )
        assert not np.allclose(reverse_transformed, wrong), (
            f"{strategy.__name__}: result matches the wrong (predict()-based) "
            "order -- reverse_transformed_forecast may be clamping too early"
        )
        assert np.array_equal(confidence, expected_confidence)


# -- clamp_output, tested directly ------------------------------------------


class TestClampOutputDirectly:
    """`clamp_output` in isolation: the `[0, FC]` / `[0, min(FC,
    inverter_limit)]` boundary behavior this whole module's final step
    relies on."""

    def test_clamps_to_zero_and_fc_with_no_inverter_limit(self) -> None:
        fc = np.array([100.0, 100.0, 100.0])
        adjusted = np.array([-10.0, 50.0, 150.0])
        result = fa_mod.clamp_output(adjusted, fc, None)
        assert np.array_equal(result, [0.0, 50.0, 100.0])

    def test_clamps_to_inverter_limit_when_lower_than_fc(self) -> None:
        fc = np.array([1000.0])
        adjusted = np.array([900.0])
        result = fa_mod.clamp_output(adjusted, fc, inverter_limit=800.0)
        assert result[0] == 800.0

    def test_fc_still_wins_when_lower_than_inverter_limit(self) -> None:
        fc = np.array([500.0])
        adjusted = np.array([600.0])
        result = fa_mod.clamp_output(adjusted, fc, inverter_limit=800.0)
        assert result[0] == 500.0
