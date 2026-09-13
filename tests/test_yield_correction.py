"""Zero-mocking tests for `yield_correction.py` (ADR-003a §1/§1a/§2,
ADR-003b §1/§1a/§1b/§1c, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.
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


yc_mod = _load("yield_correction.py", "shady.yield_correction")


# -- AC1: clipped samples are excluded entirely, not downweighted ----------


class TestExcludeClipped:
    """Given a historical sample whose actual yield is at or above
    clipping_threshold (default 0.98) of a configured inverter limit,
    when training data is prepared, that sample is excluded entirely
    (marked NaN, the same "fully excluded" sentinel `regression/base.py`
    treats as zero weight), not downweighted (ADR-003a §1)."""

    def test_sample_at_or_above_threshold_is_excluded(self) -> None:
        # inverter_limit=1000, threshold=0.98 -> cutoff at 980.
        actual = np.array([500.0, 979.9, 980.0, 995.0, 1000.0])
        result = yc_mod.exclude_clipped(actual, inverter_limit=1000.0)
        assert np.isnan(result[2:]).all()
        assert not np.isnan(result[:2]).any()

    def test_below_threshold_samples_are_untouched(self) -> None:
        actual = np.array([0.0, 100.0, 979.9])
        result = yc_mod.exclude_clipped(actual, inverter_limit=1000.0)
        assert np.array_equal(result, actual)

    def test_exclusion_is_not_a_downweight_but_a_full_exclusion(self) -> None:
        # Excluded samples become exactly NaN -- not scaled, not
        # partially retained -- so a caller can never accidentally treat
        # them as a low-weight-but-present sample.
        actual = np.array([1000.0])
        result = yc_mod.exclude_clipped(actual, inverter_limit=1000.0)
        assert np.isnan(result[0])

    def test_custom_threshold_is_respected(self) -> None:
        actual = np.array([500.0, 900.0])
        result = yc_mod.exclude_clipped(actual, inverter_limit=1000.0, clipping_threshold=0.5)
        assert np.isnan(result).all()


# -- AC2: no inverter limit configured -> no-op -----------------------------


class TestExcludeClippedNoOp:
    """Given no inverter limit configured for a string, when clipping
    exclusion runs, it is a no-op: the input series is returned unchanged
    (ADR-003a §2)."""

    def test_no_limit_returns_input_unchanged(self) -> None:
        actual = np.array([500.0, 5000.0, 1e9])
        result = yc_mod.exclude_clipped(actual, inverter_limit=None)
        assert np.array_equal(result, actual)
        # Same object -- genuinely a no-op, not a defensive copy.
        assert result is actual


# -- AC3: forward transform matches the exact ADR-003b §1 formula ----------


class TestDerateActualToReference:
    """Given a raw actual-yield sample and a cell temperature, when the
    forward transform runs, it computes
    actual_corrected = actual_raw / (1 + coefficient_per_c * (cell_temperature - 25))
    exactly (ADR-003b §1)."""

    def test_forward_formula_matches_exactly(self) -> None:
        actual_raw = 800.0
        cell_temperature = 45.0
        coefficient_per_c = -0.004  # -0.4 %/C as a fraction
        expected = actual_raw / (1 + coefficient_per_c * (cell_temperature - 25))
        result = yc_mod.derate_actual_to_reference(actual_raw, cell_temperature, coefficient_per_c)
        assert result == expected

    def test_forward_formula_at_reference_temperature_is_identity(self) -> None:
        # cell_temperature == 25 -> denominator == 1 -> unchanged.
        result = yc_mod.derate_actual_to_reference(650.0, 25.0, -0.004)
        assert result == 650.0

    def test_forward_formula_batches_over_arrays(self) -> None:
        actual_raw = np.array([500.0, 800.0])
        cell_temperature = np.array([25.0, 45.0])
        coefficient_per_c = -0.004
        result = yc_mod.derate_actual_to_reference(actual_raw, cell_temperature, coefficient_per_c)
        expected = actual_raw / (1 + coefficient_per_c * (cell_temperature - 25))
        assert np.allclose(result, expected)


# -- AC4: reverse transform is the exact algebraic inverse of forward ------


class TestReverseTransformRoundTrip:
    """Given a 25 C-equivalent prediction and a target-slot temperature,
    when the reverse transform runs, it is the exact algebraic inverse of
    the forward transform: forward then reverse recovers the original
    value within floating-point tolerance (ADR-003b §1b)."""

    def test_round_trip_recovers_original_value(self) -> None:
        original = 733.4
        cell_temperature = 38.2
        coefficient_per_c = -0.0037

        normalized = yc_mod.derate_actual_to_reference(
            original, cell_temperature, coefficient_per_c
        )
        recovered = yc_mod.apply_derate_to_prediction(
            normalized, cell_temperature, coefficient_per_c
        )
        assert recovered == pytest.approx(original, rel=1e-9)

    def test_round_trip_recovers_original_array(self) -> None:
        original = np.array([200.0, 500.0, 950.0])
        cell_temperature = np.array([10.0, 25.0, 41.0])
        coefficient_per_c = -0.0045

        normalized = yc_mod.derate_actual_to_reference(
            original, cell_temperature, coefficient_per_c
        )
        recovered = yc_mod.apply_derate_to_prediction(
            normalized, cell_temperature, coefficient_per_c
        )
        assert np.allclose(recovered, original)

    def test_reverse_formula_matches_exactly(self) -> None:
        predicted_at_reference = 700.0
        target_cell_temperature = 30.0
        coefficient_per_c = -0.004
        expected = predicted_at_reference * (1 + coefficient_per_c * (target_cell_temperature - 25))
        result = yc_mod.apply_derate_to_prediction(
            predicted_at_reference, target_cell_temperature, coefficient_per_c
        )
        assert result == expected


# -- AC5: ambient->cell uplift boundary conditions --------------------------


class TestUpliftAmbientToCell:
    """Given ambient/weather-tier inputs at baseline_forecast_i = 0 and at
    baseline_forecast_i = baseline_rated_capacity, when the uplift formula
    runs, it yields 0 uplift and the full max_uplift_c respectively
    (ADR-003b §1a boundary conditions)."""

    def test_zero_baseline_forecast_yields_zero_uplift(self) -> None:
        ambient = 15.0
        result = yc_mod.uplift_ambient_to_cell(
            ambient_temperature=ambient,
            baseline_forecast=0.0,
            baseline_rated_capacity=5000.0,
        )
        assert result == ambient

    def test_full_rated_baseline_forecast_yields_full_max_uplift(self) -> None:
        ambient = 15.0
        max_uplift_c = 25.0
        result = yc_mod.uplift_ambient_to_cell(
            ambient_temperature=ambient,
            baseline_forecast=5000.0,
            baseline_rated_capacity=5000.0,
            max_uplift_c=max_uplift_c,
        )
        assert result == ambient + max_uplift_c

    def test_partial_baseline_forecast_scales_linearly(self) -> None:
        ambient = 10.0
        max_uplift_c = 20.0
        result = yc_mod.uplift_ambient_to_cell(
            ambient_temperature=ambient,
            baseline_forecast=2500.0,
            baseline_rated_capacity=5000.0,
            max_uplift_c=max_uplift_c,
        )
        assert result == ambient + 10.0

    def test_uplift_batches_over_arrays(self) -> None:
        ambient = np.array([10.0, 10.0])
        baseline_forecast = np.array([0.0, 5000.0])
        result = yc_mod.uplift_ambient_to_cell(
            ambient_temperature=ambient,
            baseline_forecast=baseline_forecast,
            baseline_rated_capacity=5000.0,
            max_uplift_c=25.0,
        )
        assert np.allclose(result, [10.0, 35.0])


# -- AC6: provider-already-corrects flag skips both sides together --------


class TestProviderAlreadyCorrectsFlag:
    """Given the provider-already-corrects flag is true, when forward/
    reverse are invoked, both are skipped entirely (input returned
    unchanged), not just one side (ADR-003b §1c)."""

    def test_forward_is_skipped_when_flag_set(self) -> None:
        result = yc_mod.derate_actual_to_reference(
            800.0, 45.0, -0.004, provider_already_corrects=True
        )
        assert result == 800.0

    def test_reverse_is_skipped_when_flag_set(self) -> None:
        result = yc_mod.apply_derate_to_prediction(
            700.0, 45.0, -0.004, provider_already_corrects=True
        )
        assert result == 700.0

    def test_flag_overrides_an_otherwise_fully_configured_string(self) -> None:
        # Even with a valid coefficient and temperature, the flag alone
        # is enough to force a no-op on both sides -- not merely one.
        forward = yc_mod.derate_actual_to_reference(
            500.0, 40.0, -0.004, provider_already_corrects=True
        )
        reverse = yc_mod.apply_derate_to_prediction(
            500.0, 40.0, -0.004, provider_already_corrects=True
        )
        assert forward == 500.0
        assert reverse == 500.0


# -- AC7: no coefficient/source configured -> no-op, same pattern as clipping


class TestDeratingNoOpWhenNotConfigured:
    """Given no temperature coefficient/source configured for a string,
    when derating runs, it is a no-op, matching the same "no-op when not
    configured" pattern as clipping (ADR-003b §2)."""

    def test_forward_no_op_when_coefficient_missing(self) -> None:
        result = yc_mod.derate_actual_to_reference(800.0, 45.0, None)
        assert result == 800.0

    def test_forward_no_op_when_temperature_missing(self) -> None:
        result = yc_mod.derate_actual_to_reference(800.0, None, -0.004)
        assert result == 800.0

    def test_reverse_no_op_when_coefficient_missing(self) -> None:
        result = yc_mod.apply_derate_to_prediction(700.0, 45.0, None)
        assert result == 700.0

    def test_reverse_no_op_when_temperature_missing(self) -> None:
        result = yc_mod.apply_derate_to_prediction(700.0, None, -0.004)
        assert result == 700.0
