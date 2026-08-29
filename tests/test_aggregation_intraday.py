"""Zero-mocking tests for `aggregation.py`'s intraday-deviation-
correction pure functions (ADR-006 §1a/§1b/§2/§5, ADR-000 §6,
TASK-0013).

Loaded via direct file-path import, not package import — same
`sys.modules`-swap convention as `test_aggregation.py`, so this module
(dependency-free) never needs `homeassistant.*` on the path.
"""

from __future__ import annotations

import importlib.util
import sys
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


# -- ADR-006 §1a: ramp_weight -------------------------------------------


class TestRampWeight:
    """Given `active_slots_since_reset` and `ramp_slots`, When `w(t)`
    is computed, Then it is `min(1, active_slots_since_reset /
    ramp_slots)` — `0` before the ramp starts, `1` once it completes,
    linear in between."""

    def test_zero_at_reset(self) -> None:
        assert agg_mod.ramp_weight(0, 12) == 0.0

    def test_negative_active_slots_is_zero(self) -> None:
        assert agg_mod.ramp_weight(-1, 12) == 0.0

    def test_linear_partway_through_the_ramp(self) -> None:
        assert agg_mod.ramp_weight(6, 12) == 0.5

    def test_exactly_one_at_ramp_slots(self) -> None:
        assert agg_mod.ramp_weight(12, 12) == 1.0

    def test_clamped_to_one_beyond_ramp_slots(self) -> None:
        assert agg_mod.ramp_weight(100, 12) == 1.0

    def test_zero_ramp_slots_is_fully_ramped_defensively(self) -> None:
        # ADR-000 §8: a degenerate config value never raises.
        assert agg_mod.ramp_weight(0, 0) == 1.0

    def test_negative_ramp_slots_is_fully_ramped_defensively(self) -> None:
        assert agg_mod.ramp_weight(5, -1) == 1.0


# -- ADR-006 §1a/§2: intraday_correction_factor --------------------------


class TestIntradayCorrectionFactor:
    """Given the trailing-window PV/FC energy and a ramp weight, When
    `effective_factor` is computed, Then it is `1` at `w=0`, the full
    clamped ratio at `w=1`, and linearly ramped in between; the raw
    ratio is clamped to `[1 - cutoff, 1 + cutoff]` before ramping."""

    def test_w_zero_is_exactly_one_regardless_of_ratio(self) -> None:
        assert agg_mod.intraday_correction_factor(2000.0, 1000.0, 0.0, 0.3) == 1.0

    def test_w_one_is_the_full_clamped_ratio(self) -> None:
        # Raw ratio 1.2, well within a 0.3 cutoff -> unclamped.
        result = agg_mod.intraday_correction_factor(1200.0, 1000.0, 1.0, 0.3)
        assert result == 1.2

    def test_ratio_clamped_to_upper_cutoff_before_ramping(self) -> None:
        # Raw ratio 2.0 (PV running 2x forecast), cutoff 0.3 -> clamped to 1.3.
        result = agg_mod.intraday_correction_factor(2000.0, 1000.0, 1.0, 0.3)
        assert result == 1.3

    def test_ratio_clamped_to_lower_cutoff_before_ramping(self) -> None:
        # Raw ratio 0.1 (PV badly underperforming), cutoff 0.3 -> clamped to 0.7.
        result = agg_mod.intraday_correction_factor(100.0, 1000.0, 1.0, 0.3)
        assert result == 0.7

    def test_ramped_partway_between_neutral_and_clamped_ratio(self) -> None:
        # Clamped ratio 1.3, w=0.5 -> 1 + 0.5*(1.3-1) = 1.15.
        result = agg_mod.intraday_correction_factor(2000.0, 1000.0, 0.5, 0.3)
        assert result == 1.15

    def test_zero_fc_energy_window_treated_as_neutral_ratio(self) -> None:
        # No forecast energy accumulated yet in the window (e.g. right
        # at a reset point) -- no meaningful denominator, so the raw
        # ratio defaults to 1.0 (no correction basis) rather than
        # raising or dividing by zero (ADR-000 §8).
        assert agg_mod.intraday_correction_factor(500.0, 0.0, 1.0, 0.3) == 1.0

    def test_negative_fc_energy_window_also_treated_as_neutral(self) -> None:
        assert agg_mod.intraday_correction_factor(500.0, -10.0, 1.0, 0.3) == 1.0


# -- ADR-006 §1b: crossfade -----------------------------------------------


class TestCrossfade:
    """Given an old (frozen) and a new (live) prediction, When
    crossfaded, Then the result is a linear blend weighted by
    `ramp_weight` -- entirely old at `w=0`, entirely new at `w=1`."""

    def test_w_zero_is_entirely_old(self) -> None:
        assert agg_mod.crossfade(100.0, 200.0, 0.0) == 100.0

    def test_w_one_is_entirely_new(self) -> None:
        assert agg_mod.crossfade(100.0, 200.0, 1.0) == 200.0

    def test_w_half_is_the_midpoint(self) -> None:
        assert agg_mod.crossfade(100.0, 200.0, 0.5) == 150.0

    def test_equal_old_and_new_is_unaffected_by_w(self) -> None:
        assert agg_mod.crossfade(150.0, 150.0, 0.3) == 150.0


# -- ADR-006 §1b: Blending converges to Ramping's own steady state -------


class TestBlendingConvergesToRampingSteadyState:
    """Given the same new basis and the same ramp progression, When
    Blending's crossfade reaches `w_blend=1`, Then it produces the
    identical value Ramping would show for that slot (ADR-006 §1b's
    own acceptance criterion) -- entirely a consequence of `crossfade`
    returning `new_prediction` unchanged at `w=1`, checked here as an
    explicit regression against that promise."""

    def test_converged_crossfade_matches_plain_ramping_multiply(self) -> None:
        new_value = 850.0
        effective_factor = agg_mod.intraday_correction_factor(1200.0, 1000.0, 1.0, 0.3)
        ramping_result = new_value * effective_factor

        old_value = 900.0
        old_effective_factor = 0.85  # whatever the frozen old side happened to be
        blending_result = agg_mod.crossfade(
            old_value * old_effective_factor,
            new_value * effective_factor,
            agg_mod.ramp_weight(12, 12),
        )
        assert blending_result == ramping_result
