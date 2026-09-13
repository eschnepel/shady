"""Tests for `coordinator.py`'s ADR-006 intraday-deviation-correction
wiring (TASK-0013): reset semantics, the Ramping ramp, Blending's
freeze/crossfade, the clamp-once-at-the-end ordering, and the ADR-006
§4 transparency attributes.

Reuses `test_coordinator.py`'s exact hand-written `homeassistant` stub
and fixture conventions (`_make_entry`/`_make_coordinator`/
`hass_pushed_values`) rather than re-declaring them — importing the
module itself installs the stub exactly once.

**On `async_refit` already being a reset point:** `_refit_sync` calls
`_recompute_string` for every string immediately after fitting
(`TestRefitTriggersRecompute`, `test_coordinator.py`) — so
`_run(coordinator.async_refit(_NOW))` alone already performs this
string's *first* reset of the day (ADR-006 §1b). Tests below that need
a later, distinct reset (simulating an actual mid-day baseline-provider
update) call `_recompute_string` again themselves, at a later `now`;
tests that only care about the *first* reset's own properties assert
directly against the state `async_refit` itself already produced,
without an extra, same-timestamp `_recompute_string` call (which would
itself count as a second reset, per ADR-006 §1b's own "not a special
case" rule — and would wrongly make the first-reset assertions look
like a second reset's).
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pytest

from tests import test_coordinator as tc

Cache = tc.Cache
_NOW = tc._NOW
_ACTUAL_YIELD_ENTITY = tc._ACTUAL_YIELD_ENTITY
_make_entry = tc._make_entry
_make_coordinator = tc._make_coordinator
_run = tc._run
hass_pushed_values = tc.hass_pushed_values

_forecast_adjust_mod = sys.modules["shady.forecast_adjust"]
clamp_output = _forecast_adjust_mod.clamp_output


def _reseed_pv_to_match_pushed_forecast(
    coordinator: Any, hass: Any, now: datetime, ratio: float, since: datetime
) -> None:
    """Re-seed actual-yield statistics for every 5-minute slot from
    `since` up to and including `now`, at exactly `ratio x` whatever is
    *currently* pushed for that slot on the string's own
    already-corrected forecast (ADR-006 §1a's `pv_energy_window` /
    `fc_energy_window` compare PV against that same already-corrected
    series, not the raw baseline) — called fresh before every tick, so
    an earlier tick's own re-push of a still-future slot (its own
    correction applied) never silently drifts a later tick's window
    ratio away from `ratio`.
    """
    sensor_id = coordinator.forecast_sensor_id(0)
    pushed = hass_pushed_values(coordinator, sensor_id)
    ts = since
    while ts <= now:
        index = Cache.index_for(ts)
        if index in pushed:
            hass.statistics[_ACTUAL_YIELD_ENTITY][ts] = pushed[index] * ratio
        ts += timedelta(minutes=5)


class TestResetPoint:
    """Given a string's first basis of the day, When Ramping or
    Blending is configured, Then both start identically: `w=0`,
    `effective_factor=1`, nothing frozen (ADR-006 §1b's own "nothing
    yet to blend against" case). `async_refit` itself performs this
    first reset (see module docstring)."""

    @pytest.mark.parametrize("mode", ["ramping", "blending"])
    def test_first_reset_of_the_day_has_no_frozen_basis(self, mode: str) -> None:
        entry = _make_entry(intraday_correction_mode=mode)
        coordinator, _hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))

        state = coordinator.cache.intraday_state(0)
        assert state is not None
        assert state.active_slots_since_reset == 0
        assert state.effective_factor == 1.0
        assert state.frozen_basis is None

    def test_pushed_value_at_reset_matches_plain_uncorrected_basis(self) -> None:
        # w=0 -> effective_factor exactly 1 -> the pushed value is
        # identical to what `intraday_correction_mode="off"` would have
        # produced (the same basis, clamped, with no multiply at all).
        entry = _make_entry(intraday_correction_mode="ramping")
        coordinator, _hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))

        state = coordinator.cache.intraday_state(0)
        assert state is not None
        sensor_id = coordinator.forecast_sensor_id(0)
        pushed = hass_pushed_values(coordinator, sensor_id)
        first_index = Cache.index_for(_NOW) + 1

        expected = clamp_output(
            np.array([state.basis.values[first_index]]),
            np.array([state.basis.fc[first_index]]),
            state.basis.inverter_limit,
        )[0]
        assert pushed[first_index] == pytest.approx(float(expected))


class TestRampingRampsInTheDeviation:
    """Given `w(t) = min(1, active_slots_since_reset / ramp_slots)`,
    When computed over several 5-minute ticks with a known, constant
    PV/FC deviation in the trailing window, Then `effective_factor`
    moves linearly from `1` toward the clamped ratio, reaching it
    exactly at `w=1` (ADR-006 §1a/§2)."""

    def test_effective_factor_ramps_linearly_to_the_clamped_ratio(self) -> None:
        entry = _make_entry(
            intraday_correction_mode="ramping",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=4,
        )
        coordinator, hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))

        expected_w = {1: 0.25, 2: 0.5, 3: 0.75, 4: 1.0}
        for step in (1, 2, 3, 4):
            now = _NOW + timedelta(minutes=5 * step)
            _reseed_pv_to_match_pushed_forecast(coordinator, hass, now, 1.2, _NOW)
            coordinator._advance_intraday_string(coordinator._strings[0], now)

            state = coordinator.cache.intraday_state(0)
            assert state is not None
            assert state.active_slots_since_reset == step
            assert state.ratio_string == pytest.approx(1.2, rel=1e-6)
            w = expected_w[step]
            assert state.effective_factor == pytest.approx(1.0 + w * 0.2, rel=1e-6)

        final_state = coordinator.cache.intraday_state(0)
        assert final_state is not None
        assert final_state.effective_factor == pytest.approx(1.2, rel=1e-6)

    def test_ratio_beyond_cutoff_is_clamped_before_ramping(self) -> None:
        entry = _make_entry(
            intraday_correction_mode="ramping",
            intraday_correction_cutoff=0.3,
            window_slots=4,
            ramp_slots=1,
        )
        coordinator, hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))

        # PV running at 2x forecast -- well beyond the 0.3 cutoff.
        now = _NOW + timedelta(minutes=5)
        _reseed_pv_to_match_pushed_forecast(coordinator, hass, now, 2.0, _NOW)
        coordinator._advance_intraday_string(coordinator._strings[0], now)

        state = coordinator.cache.intraday_state(0)
        assert state is not None
        assert state.active_slots_since_reset == 1  # ramp_slots=1 -> already fully ramped
        assert state.effective_factor == pytest.approx(1.3, rel=1e-6)

    def test_corrected_value_never_exceeds_the_clamp(self) -> None:
        # Even at a fully-ramped, above-1 effective_factor, the pushed
        # value must never exceed min(fc, inverter_limit) -- the one
        # final clamp still applies after the correction (ADR-006 §1b).
        entry = _make_entry(
            intraday_correction_mode="ramping",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=1,
        )
        coordinator, hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))
        now = _NOW + timedelta(minutes=5)
        _reseed_pv_to_match_pushed_forecast(coordinator, hass, now, 1.4, _NOW)
        coordinator._advance_intraday_string(coordinator._strings[0], now)

        state = coordinator.cache.intraday_state(0)
        assert state is not None
        sensor_id = coordinator.forecast_sensor_id(0)
        pushed = hass_pushed_values(coordinator, sensor_id)
        index = Cache.index_for(_NOW) + 2  # first index this tick was allowed to overwrite
        assert index in pushed
        assert pushed[index] <= state.basis.fc[index] + 1e-9


class TestProviderUpdateMidDayResetsRamping:
    """Given Ramping and a provider update fires mid-day, When it
    fires, Then the rolling window empties and `w` resets to `0`
    (ADR-006 §1b) -- a fresh `_recompute_string` call is exactly this
    trigger."""

    def test_recompute_after_partial_ramp_resets_active_slots_to_zero(self) -> None:
        entry = _make_entry(
            intraday_correction_mode="ramping",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=4,
        )
        coordinator, hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))
        for step in (1, 2):
            now = _NOW + timedelta(minutes=5 * step)
            _reseed_pv_to_match_pushed_forecast(coordinator, hass, now, 1.2, _NOW)
            coordinator._advance_intraday_string(coordinator._strings[0], now)
        partially_ramped = coordinator.cache.intraday_state(0)
        assert partially_ramped is not None
        assert partially_ramped.active_slots_since_reset == 2
        assert partially_ramped.effective_factor > 1.0

        # A baseline provider update fires: another recompute.
        coordinator._recompute_string(coordinator._strings[0], _NOW + timedelta(minutes=10))

        reset_state = coordinator.cache.intraday_state(0)
        assert reset_state is not None
        assert reset_state.active_slots_since_reset == 0
        assert reset_state.effective_factor == 1.0


class TestBlendingCrossfade:
    """Given Blending and a provider update fires mid-day, When it
    fires, Then the pre-update state freezes as `old_prediction` and
    crossfades toward `new_prediction` over `ramp_slots`, converging to
    the exact same steady-state value Ramping would reach for the same
    slot (ADR-006 §1b)."""

    def test_update_freezes_old_side_and_converges_to_ramping_steady_state(self) -> None:
        blending_entry = _make_entry(
            intraday_correction_mode="blending",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=4,
        )
        blending, hass_b = _make_coordinator(blending_entry)
        _run(blending.async_refit(_NOW))
        for step in (1, 2):
            now = _NOW + timedelta(minutes=5 * step)
            _reseed_pv_to_match_pushed_forecast(blending, hass_b, now, 1.2, _NOW)
            blending._advance_intraday_string(blending._strings[0], now)
        pre_update_state = blending.cache.intraday_state(0)
        assert pre_update_state is not None
        pre_update_factor = pre_update_state.effective_factor
        pre_update_basis = pre_update_state.basis

        update_time = _NOW + timedelta(minutes=10)
        blending._recompute_string(blending._strings[0], update_time)

        frozen_state = blending.cache.intraday_state(0)
        assert frozen_state is not None
        assert frozen_state.active_slots_since_reset == 0
        assert frozen_state.frozen_basis is pre_update_basis
        assert frozen_state.frozen_effective_factor == pytest.approx(pre_update_factor)

        # w_blend=0 right at the update: displayed value is entirely
        # the frozen old side -- no visible dip to the plain new value.
        sensor_id = blending.forecast_sensor_id(0)
        pushed_at_update = hass_pushed_values(blending, sensor_id)
        first_index = Cache.index_for(update_time) + 1
        if first_index in pre_update_basis.values:
            expected_old = clamp_output(
                np.array([pre_update_basis.values[first_index] * pre_update_factor]),
                np.array([frozen_state.basis.fc[first_index]]),
                frozen_state.basis.inverter_limit,
            )[0]
            assert pushed_at_update[first_index] == pytest.approx(float(expected_old))

        # Run a full `ramp_slots` worth of ticks, feeding the same 1.2x
        # deviation against whatever is currently displayed each time,
        # so `w_blend` reaches exactly 1.
        for step in (1, 2, 3, 4):
            now = update_time + timedelta(minutes=5 * step)
            _reseed_pv_to_match_pushed_forecast(blending, hass_b, now, 1.2, update_time)
            blending._advance_intraday_string(blending._strings[0], now)

        converged_state = blending.cache.intraday_state(0)
        assert converged_state is not None
        assert converged_state.frozen_basis is None  # crossfade complete
        assert converged_state.effective_factor == pytest.approx(1.2, rel=1e-6)

        # Build an equivalent Ramping coordinator that goes through the
        # exact same update-then-4-ticks sequence, and confirm the two
        # converge to the identical pushed value for the same slot.
        ramping_entry = _make_entry(
            intraday_correction_mode="ramping",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=4,
        )
        ramping, hass_r = _make_coordinator(ramping_entry)
        _run(ramping.async_refit(_NOW))
        for step in (1, 2):
            now = _NOW + timedelta(minutes=5 * step)
            _reseed_pv_to_match_pushed_forecast(ramping, hass_r, now, 1.2, _NOW)
            ramping._advance_intraday_string(ramping._strings[0], now)
        ramping._recompute_string(ramping._strings[0], update_time)
        for step in (1, 2, 3, 4):
            now = update_time + timedelta(minutes=5 * step)
            _reseed_pv_to_match_pushed_forecast(ramping, hass_r, now, 1.2, update_time)
            ramping._advance_intraday_string(ramping._strings[0], now)

        blending_pushed = hass_pushed_values(blending, blending.forecast_sensor_id(0))
        ramping_pushed = hass_pushed_values(ramping, ramping.forecast_sensor_id(0))
        # Only indices actually written *by* the final, fully-converged
        # tick (w_blend == 1, `frozen_basis` already cleared before that
        # tick's own push) are guaranteed to match Ramping's identical
        # formula -- indices written by an earlier, still-mid-crossfade
        # tick (`0 < w_blend < 1`) are *supposed* to differ from
        # Ramping's own value for the same slot; that is the whole
        # point of a crossfade rather than an instant switch.
        final_tick_index = Cache.index_for(update_time + timedelta(minutes=5 * 4))
        shared_indices = {
            index
            for index in set(blending_pushed) & set(ramping_pushed)
            if index > final_tick_index
        }
        assert shared_indices
        for index in shared_indices:
            assert blending_pushed[index] == pytest.approx(ramping_pushed[index], rel=1e-6)


class TestIntradayAttributes:
    """ADR-006 §4's transparency attributes, read straight off
    `coordinator.intraday_attributes` (`sensor.py`'s own Consumed
    Interface)."""

    def test_off_mode_reports_state_off_and_no_computed_values(self) -> None:
        coordinator, _hass = _make_coordinator()  # default entry: mode="off"
        attrs = coordinator.intraday_attributes(0)
        assert attrs == {
            "intraday_ratio": None,
            "intraday_state": "off",
            "intraday_ramp_weight": None,
            "intraday_blend_active": False,
        }

    def test_ramping_mode_reports_live_ratio_and_ramp_weight(self) -> None:
        entry = _make_entry(
            intraday_correction_mode="ramping",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=4,
        )
        coordinator, hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))
        now = _NOW + timedelta(minutes=5)
        _reseed_pv_to_match_pushed_forecast(coordinator, hass, now, 1.2, _NOW)
        coordinator._advance_intraday_string(coordinator._strings[0], now)

        attrs = coordinator.intraday_attributes(0)
        assert attrs["intraday_state"] == "ramping"
        assert attrs["intraday_ratio"] == pytest.approx(1.2, rel=1e-6)
        assert attrs["intraday_ramp_weight"] == pytest.approx(0.25, rel=1e-6)
        assert attrs["intraday_blend_active"] is False

    def test_blend_active_true_only_while_a_crossfade_is_in_progress(self) -> None:
        entry = _make_entry(
            intraday_correction_mode="blending",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=4,
        )
        coordinator, _hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))  # first reset -- nothing to blend against yet
        assert coordinator.intraday_attributes(0)["intraday_blend_active"] is False

        # A genuine mid-day update: a second, later reset -- now there
        # is a same-day previous basis to freeze.
        coordinator._recompute_string(coordinator._strings[0], _NOW + timedelta(minutes=5))
        assert coordinator.intraday_attributes(0)["intraday_blend_active"] is True


class TestAggregateSensorsNeedNoCorrectionLogicOfTheirOwn:
    """Given `ShadyFcSumSensor`/`ShadyFcDaySumSensor`, When intraday
    correction is active, Then they read the already-corrected
    `forecast_sensor_id` series exactly as before (ADR-006 §4) -- no
    changes needed in `aggregation.py`/`coordinator.py`'s TASK-0012
    methods themselves."""

    def test_fc_sum_reflects_the_corrected_not_raw_forecast(self) -> None:
        entry = _make_entry(
            intraday_correction_mode="ramping",
            intraday_correction_cutoff=0.5,
            window_slots=4,
            ramp_slots=1,
        )
        coordinator, hass = _make_coordinator(entry)
        _run(coordinator.async_refit(_NOW))
        now = _NOW + timedelta(minutes=5)
        _reseed_pv_to_match_pushed_forecast(coordinator, hass, now, 1.3, _NOW)
        coordinator._advance_intraday_string(coordinator._strings[0], now)
        coordinator._now = lambda: now

        state = coordinator.cache.intraday_state(0)
        assert state is not None
        assert state.effective_factor == pytest.approx(1.3, rel=1e-6)

        sensor_id = coordinator.forecast_sensor_id(0)
        index = Cache.index_for(now)
        pushed_corrected_value = hass_pushed_values(coordinator, sensor_id)[index]

        assert coordinator.fc_sum() == pytest.approx(pushed_corrected_value)
