"""Zero-mocking tests for `string_computation.py` (ADR-014, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module. Mirrors
`test_regression.py`'s loading convention exactly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_shady_pkg = ModuleType("shady")
_shady_pkg.__path__ = []
sys.modules["shady"] = _shady_pkg
_regression_pkg = ModuleType("shady.regression")
_regression_pkg.__path__ = []
sys.modules["shady.regression"] = _regression_pkg

base_mod = _load("regression/base.py", "shady.regression.base")
linear_mod = _load("regression/linear.py", "shady.regression.linear")
kernel_mod = _load("regression/kernel.py", "shady.regression.kernel")
wls2_mod = _load("regression/wls2.py", "shady.regression.wls2")
wls3_mod = _load("regression/wls3.py", "shady.regression.wls3")
yield_correction_mod = _load("yield_correction.py", "shady.yield_correction")
forecast_adjust_mod = _load("forecast_adjust.py", "shady.forecast_adjust")
string_computation_mod = _load("string_computation.py", "shady.string_computation")

REGRESSION_STRATEGIES: dict[str, Any] = string_computation_mod.REGRESSION_STRATEGIES
apply_training_corrections = string_computation_mod.apply_training_corrections
fit_string_model = string_computation_mod.fit_string_model
predict_string_forecast = string_computation_mod.predict_string_forecast
build_pool = base_mod.build_pool
adjust_forecast = forecast_adjust_mod.adjust_forecast
exclude_clipped = yield_correction_mod.exclude_clipped
derate_actual_to_reference = yield_correction_mod.derate_actual_to_reference
uplift_ambient_to_cell = yield_correction_mod.uplift_ambient_to_cell

RNG_SEED = 20260831


def _pool(
    n_slots: int, window_days: int, offsets: tuple[int, ...] = (-1, 0, 1)
) -> tuple[dict[int, np.ndarray], dict[int, np.ndarray]]:
    rng = np.random.default_rng(RNG_SEED)
    fc_by_offset: dict[int, np.ndarray] = {}
    pv_by_offset: dict[int, np.ndarray] = {}
    for offset in offsets:
        fc = rng.uniform(50.0, 1200.0, size=(n_slots, window_days))
        pv = fc * 0.8 + rng.normal(0, 3.0, size=(n_slots, window_days))
        fc_by_offset[offset] = fc
        pv_by_offset[offset] = np.clip(pv, 0.0, None)
    return fc_by_offset, pv_by_offset


class TestModulePurity:
    """`string_computation.py` is pure (ADR-000 §3/§6): no `cache.py`
    import, no `homeassistant.*` import."""

    def test_no_cache_or_homeassistant_import(self) -> None:
        source = (_SHADY_DIR / "string_computation.py").read_text()
        import_lines = [
            line.strip()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        ]
        assert not any("cache" in line for line in import_lines)
        assert not any("homeassistant" in line for line in import_lines)

    def test_registry_has_all_four_methods(self) -> None:
        assert set(REGRESSION_STRATEGIES) == {"linear", "kernel", "wls2", "wls3"}
        assert REGRESSION_STRATEGIES["linear"] is linear_mod
        assert REGRESSION_STRATEGIES["kernel"] is kernel_mod
        assert REGRESSION_STRATEGIES["wls2"] is wls2_mod
        assert REGRESSION_STRATEGIES["wls3"] is wls3_mod


class TestApplyTrainingCorrections:
    """Given the same inputs `coordinator.py`'s original,
    `_StringConfig`-bound `_apply_training_corrections` used to compute
    from, `apply_training_corrections` returns byte-identical results —
    a pure relocation (ADR-014 §2), verified here against the same
    `yield_correction.py` calls made directly."""

    def test_no_temperature_matches_manual_clip_and_derate(self) -> None:
        fc_by_offset, pv_by_offset = _pool(3, 5, offsets=(0,))
        result = apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            None,
            None,
            converter_limit_w=None,
            clipping_threshold=0.98,
            coefficient_per_c=-0.004,
            provider_already_corrects=False,
            rated_dc_capacity_wp=None,
            max_uplift_c=25.0,
        )
        expected = np.asarray(
            derate_actual_to_reference(
                exclude_clipped(pv_by_offset[0], None, 0.98),
                None,
                -0.004,
                provider_already_corrects=False,
            ),
            dtype=np.float64,
        )
        np.testing.assert_array_equal(result[0], expected)

    def test_cell_tier_uses_temperature_directly_no_uplift(self) -> None:
        fc_by_offset, pv_by_offset = _pool(2, 4, offsets=(0,))
        rng = np.random.default_rng(RNG_SEED)
        temperature_by_offset = {0: rng.uniform(10.0, 40.0, size=(2, 4))}
        result = apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            temperature_by_offset,
            "cell",
            converter_limit_w=None,
            clipping_threshold=0.98,
            coefficient_per_c=-0.004,
            provider_already_corrects=False,
            rated_dc_capacity_wp=None,  # cell tier never gated on this
            max_uplift_c=25.0,
        )
        expected = np.asarray(
            derate_actual_to_reference(
                exclude_clipped(pv_by_offset[0], None, 0.98),
                temperature_by_offset[0],
                -0.004,
                provider_already_corrects=False,
            ),
            dtype=np.float64,
        )
        np.testing.assert_array_equal(result[0], expected)

    def test_ambient_tier_applies_uplift_before_derating(self) -> None:
        fc_by_offset, pv_by_offset = _pool(2, 4, offsets=(0,))
        rng = np.random.default_rng(RNG_SEED)
        temperature_by_offset = {0: rng.uniform(10.0, 40.0, size=(2, 4))}
        result = apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            temperature_by_offset,
            "ambient",
            converter_limit_w=None,
            clipping_threshold=0.98,
            coefficient_per_c=-0.004,
            provider_already_corrects=False,
            rated_dc_capacity_wp=400.0,
            max_uplift_c=25.0,
        )
        uplifted = uplift_ambient_to_cell(temperature_by_offset[0], fc_by_offset[0], 400.0, 25.0)
        expected = np.asarray(
            derate_actual_to_reference(
                exclude_clipped(pv_by_offset[0], None, 0.98),
                np.asarray(uplifted, dtype=np.float64),
                -0.004,
                provider_already_corrects=False,
            ),
            dtype=np.float64,
        )
        np.testing.assert_array_equal(result[0], expected)

    def test_ambient_tier_skipped_without_rated_capacity(self) -> None:
        """No `rated_dc_capacity_wp` means the uplift formula's required
        input is missing — temperature correction is skipped entirely
        for `ambient`/`weather` (ADR-003b §1a), unlike `cell`."""
        fc_by_offset, pv_by_offset = _pool(2, 4, offsets=(0,))
        rng = np.random.default_rng(RNG_SEED)
        temperature_by_offset = {0: rng.uniform(10.0, 40.0, size=(2, 4))}
        result = apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            temperature_by_offset,
            "ambient",
            converter_limit_w=None,
            clipping_threshold=0.98,
            coefficient_per_c=-0.004,
            provider_already_corrects=False,
            rated_dc_capacity_wp=None,
            max_uplift_c=25.0,
        )
        expected = np.asarray(
            derate_actual_to_reference(
                exclude_clipped(pv_by_offset[0], None, 0.98),
                None,
                -0.004,
                provider_already_corrects=False,
            ),
            dtype=np.float64,
        )
        np.testing.assert_array_equal(result[0], expected)

    def test_provider_already_corrects_skips_temperature(self) -> None:
        fc_by_offset, pv_by_offset = _pool(2, 4, offsets=(0,))
        rng = np.random.default_rng(RNG_SEED)
        temperature_by_offset = {0: rng.uniform(10.0, 40.0, size=(2, 4))}
        result = apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            temperature_by_offset,
            "cell",
            converter_limit_w=None,
            clipping_threshold=0.98,
            coefficient_per_c=-0.004,
            provider_already_corrects=True,
            rated_dc_capacity_wp=None,
            max_uplift_c=25.0,
        )
        expected = np.asarray(
            derate_actual_to_reference(
                exclude_clipped(pv_by_offset[0], None, 0.98),
                None,
                -0.004,
                provider_already_corrects=True,
            ),
            dtype=np.float64,
        )
        np.testing.assert_array_equal(result[0], expected)

    def test_multiple_offsets_each_corrected_independently(self) -> None:
        fc_by_offset, pv_by_offset = _pool(3, 6, offsets=(-1, 0, 1))
        result = apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            None,
            None,
            converter_limit_w=1000.0,
            clipping_threshold=0.98,
            coefficient_per_c=-0.004,
            provider_already_corrects=False,
            rated_dc_capacity_wp=None,
            max_uplift_c=25.0,
        )
        assert set(result) == {-1, 0, 1}
        for offset in (-1, 0, 1):
            expected = np.asarray(
                derate_actual_to_reference(
                    exclude_clipped(pv_by_offset[offset], 1000.0, 0.98),
                    None,
                    -0.004,
                    provider_already_corrects=False,
                ),
                dtype=np.float64,
            )
            np.testing.assert_array_equal(result[offset], expected)


class TestFitStringModel:
    """Given the same pool inputs, `fit_string_model` returns the same
    `FittedModel` a direct `build_pool` + `strategy.fit()` call would
    (ADR-014 §3)."""

    def test_matches_direct_build_pool_and_fit(self) -> None:
        fc_by_offset, pv_by_offset = _pool(4, 10)
        for method in ("linear", "kernel", "wls2", "wls3"):
            model = fit_string_model(fc_by_offset, pv_by_offset, 1, 0.25, 0.5, method)
            pool = build_pool(fc_by_offset, pv_by_offset, 1, 0.25, 0.5)
            expected_model = REGRESSION_STRATEGIES[method].fit(pool)
            fc_query = np.array([100.0, 500.0, 900.0, 1100.0])
            np.testing.assert_array_equal(
                model.predict(fc_query)[0], expected_model.predict(fc_query)[0]
            )

    def test_apply_magnitude_weight_false_matches_direct_call(self) -> None:
        fc_by_offset, pv_by_offset = _pool(3, 8, offsets=(0,))
        model = fit_string_model(
            fc_by_offset, pv_by_offset, 0, 0.25, 0.5, "wls2", apply_magnitude_weight=False
        )
        pool = build_pool(fc_by_offset, pv_by_offset, 0, 0.25, 0.5, apply_magnitude_weight=False)
        expected_model = REGRESSION_STRATEGIES["wls2"].fit(pool)
        fc_query = np.array([10.0, -5.0, 30.0])
        np.testing.assert_array_equal(
            model.predict(fc_query)[0], expected_model.predict(fc_query)[0]
        )

    def test_single_slot_pool_n_slots_1(self) -> None:
        """Slot-count-agnostic (ADR-014 §1): a single-diagnosed-slot
        shaped pool (`n_slots=1`) works identically in kind to a
        multi-slot one — the shape `TASK-0015b`'s real caller needs."""
        fc_by_offset, pv_by_offset = _pool(1, 12)
        model = fit_string_model(fc_by_offset, pv_by_offset, 1, 0.25, 0.5, "linear")
        predicted, confidence = model.predict(np.array([500.0]))
        assert predicted.shape == (1,)
        assert confidence.shape == (1,)


class TestPredictStringForecast:
    """Given the same model/fc/temperature/config, `predict_string_forecast`
    returns exactly `adjust_forecast`'s adjusted value (ADR-014 §3) —
    the reverse-transform-then-clamp sequence, minus the confidence
    return value."""

    def test_matches_adjust_forecast_no_temperature(self) -> None:
        fc_by_offset, pv_by_offset = _pool(2, 6, offsets=(0,))
        model = fit_string_model(fc_by_offset, pv_by_offset, 0, 0.25, 0.5, "wls2")
        fc = np.array([200.0, 800.0])
        result = predict_string_forecast(model, fc, None, -0.004, False, None)
        expected, _confidence = adjust_forecast(
            model, fc, None, -0.004, None, provider_already_corrects=False
        )
        np.testing.assert_array_equal(result, expected)

    def test_matches_adjust_forecast_with_temperature_and_inverter_limit(self) -> None:
        fc_by_offset, pv_by_offset = _pool(2, 6, offsets=(0,))
        model = fit_string_model(fc_by_offset, pv_by_offset, 0, 0.25, 0.5, "linear")
        fc = np.array([600.0, 1200.0])
        temperature = np.array([35.0, 42.0])
        result = predict_string_forecast(model, fc, temperature, -0.004, False, 900.0)
        expected, _confidence = adjust_forecast(
            model, fc, temperature, -0.004, 900.0, provider_already_corrects=False
        )
        np.testing.assert_array_equal(result, expected)
        assert bool(np.all(result <= 900.0))

    def test_single_slot_prediction(self) -> None:
        """Slot-count-agnostic (ADR-014 §1): a length-1 `fc` array
        (`TASK-0015b`'s real diagnosed-slot shape) works identically in
        kind to a multi-slot one."""
        fc_by_offset, pv_by_offset = _pool(1, 10)
        model = fit_string_model(fc_by_offset, pv_by_offset, 1, 0.25, 0.5, "wls3")
        fc = np.array([700.0])
        result = predict_string_forecast(model, fc, None, -0.004, False, None)
        assert result.shape == (1,)
        assert bool(result[0] >= 0.0)
        assert bool(result[0] <= 700.0)
