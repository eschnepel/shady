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
