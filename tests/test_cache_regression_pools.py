"""Zero-mocking tests for `cache.py`'s TASK-0006 extension: the shadow
`float64` array and `get_regression_pools` (ADR-008 §2, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.

`tests/test_cache_core.py` (TASK-0002) is re-run unmodified as part of
this task's own Definition of Done (regression check) — not duplicated
here; this file covers only the shadow-array/`get_regression_pools`
behavior this task adds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from tests.support import _load

# `cache.py` does `from .regression.base import FittedModel` (the
# relocated fitted-model cache, TASK-0021) — pre-load it under its real
# dotted name first, same convention as `tests/test_cache_core.py`.
base_mod = _load("regression/base.py", "shady.regression.base")
cache_mod = _load("cache.py", "shady.cache")


# -- AC1: shadow array mirrors the three-state list exactly ----------------


class TestShadowArrayMirrorsThreeStateList:
    """Given a sensor with some None/str entries in its three-state list,
    when the shadow array is read, those positions are NaN and all float
    positions match exactly (ADR-008 §2)."""

    def test_none_and_str_entries_become_nan_float_entries_match_exactly(self) -> None:
        canned: list[float | None | str] = [10.0, None, "unavailable", 20.5, None]

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            result: list[float | None | str] = (canned * (n // len(canned) + 1))[:n]
            return result

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        start = datetime(2026, 1, 10, tzinfo=UTC)
        cache.get_time_range(["pv"], start, start)  # triggers the full-window fetch

        shadow = cache._shadow["pv"]
        three_state = cache._values["pv"]
        assert len(shadow) == len(three_state)
        for pos, value in enumerate(three_state[: len(canned) * 2]):
            if isinstance(value, float):
                assert shadow[pos] == value
            else:
                assert np.isnan(shadow[pos])


# -- AC2: push()/invalidate() keep the shadow array in sync immediately ----


class TestShadowArrayKeptInSyncOnMutation:
    """Given a push() or invalidate() call, the shadow array is updated in
    the same call — kept incrementally in sync, not rebuilt on read
    (ADR-008 §2)."""

    def test_push_updates_shadow_immediately(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            raise AssertionError("push-only sensor must never be queried")

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))

        cache.push("shady_forecast", {base: 42.0}, not_before_index=base)

        pos = base - cache._list_offset["shady_forecast"]
        assert cache._shadow["shady_forecast"][pos] == 42.0

    def test_invalidate_resets_shadow_to_nan(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [7.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        anchor = datetime(2026, 1, 10, tzinfo=UTC)
        cache.get_time_range(["pv"], anchor, anchor)

        anchor_index = cache_mod.Cache.index_for(anchor)
        pos = anchor_index - cache._list_offset["pv"]
        assert cache._shadow["pv"][pos] == 7.0

        cache.invalidate("pv", anchor_index, anchor_index)
        assert np.isnan(cache._shadow["pv"][pos])

    def test_shadow_grows_and_prepends_in_lockstep_with_three_state_list(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            raise AssertionError("push-only sensor must never be queried")

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))

        cache.push("shady_forecast", {base: 1.0}, not_before_index=base - 100)
        assert len(cache._shadow["shady_forecast"]) == len(cache._values["shady_forecast"]) == 1

        # Append/grow past the current end.
        cache.push("shady_forecast", {base + 5: 2.0}, not_before_index=base - 100)
        assert len(cache._shadow["shady_forecast"]) == len(cache._values["shady_forecast"])
        assert cache._shadow["shady_forecast"][-1] == 2.0

        # Prepend before the current start.
        cache.push("shady_forecast", {base - 3: 3.0}, not_before_index=base - 100)
        assert len(cache._shadow["shady_forecast"]) == len(cache._values["shady_forecast"])
        assert cache._list_offset["shady_forecast"] == base - 3
        assert cache._shadow["shady_forecast"][0] == 3.0


# -- AC3: get_regression_pools is one batched call, correct shape ----------


class TestGetRegressionPoolsBatchedSingleCall:
    """Given get_regression_pools(sensor_ids, smoothing_radius=1), it
    returns one 2-D array per sensor of shape (288, window_days*3) in a
    single call — not 864 individual per-slot calls (ADR-008 §2)."""

    def test_shape_dtype_and_single_fetch_call(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [5.0] * n

        window_days = 4
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)

        pools = cache.get_regression_pools(["fc"], smoothing_radius=1, reference=reference)

        assert set(pools) == {"fc"}
        pool = pools["fc"]
        assert pool.shape == (288, window_days * 3)
        assert pool.dtype == np.float64
        assert len(calls) == 1  # a single fetch_fn call for this sensor's window

    def test_multiple_sensors_each_get_their_own_pool_and_fetch(self) -> None:
        calls: list[str] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append(sensor_id)
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [1.0 if sensor_id == "fc" else 2.0] * n

        cache = cache_mod.Cache(window_days=2, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, tzinfo=UTC)

        pools = cache.get_regression_pools(["fc", "pv"], smoothing_radius=0, reference=reference)

        assert calls == ["fc", "pv"]
        assert np.allclose(pools["fc"], 1.0)
        assert np.allclose(pools["pv"], 2.0)

    def test_smoothing_radius_zero_has_window_days_wide_columns(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [1.0] * n

        window_days = 5
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, tzinfo=UTC)

        pool = cache.get_regression_pools(["fc"], smoothing_radius=0, reference=reference)["fc"]
        assert pool.shape == (288, window_days)


class TestGetRegressionPoolsBackfillsAPushMarkedBaseline:
    """Given a `forecast_solar`-shaped baseline that's already been
    pushed to (to_index=None — its live forward() series, same as any
    other push-based sensor, ADR-007a §2) before get_regression_pools
    ever runs, the historical pool is still populated from its real
    external source (ADR-012 §2a Amendment, TASK-0034), not silently
    left all-NaN just because the sensor happens to also be push-marked
    (TASK-0034-patch-2's own bug report and fix)."""

    def test_historical_pool_is_populated_despite_prior_push(self) -> None:
        fetch_calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            fetch_calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [42.0] * n

        window_days = 2
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
        now_index = cache_mod.Cache.index_for(reference)

        # Simulate _push_provider_series: the live forward() series gets
        # pushed *before* any refit/get_regression_pools call, marking
        # "fc" to_index=None with no fetch involved at all.
        cache.push("fc", {now_index + 1: 999.0}, not_before_index=now_index + 1)
        assert cache.validated_range("fc") == (now_index + 1, None)
        assert fetch_calls == []  # the push itself never touches fetch_fn

        pools = cache.get_regression_pools(["fc"], smoothing_radius=0, reference=reference)

        assert len(fetch_calls) == 1  # the missing historical head was fetched
        assert not np.isnan(pools["fc"]).any()
        assert np.allclose(pools["fc"], 42.0)

    def test_future_pushed_value_is_unaffected_by_the_historical_backfill(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [42.0] * n

        cache = cache_mod.Cache(window_days=2, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, 12, 0, tzinfo=UTC)
        now_index = cache_mod.Cache.index_for(reference)

        cache.push("fc", {now_index + 1: 999.0}, not_before_index=now_index + 1)
        cache.get_regression_pools(["fc"], smoothing_radius=0, reference=reference)

        # A live read for the pushed future slot still sees the pushed
        # value, not something re-fetched over it (the to_index=None
        # marker must survive the historical backfill merge).
        result = cache.get_time_range(
            ["fc"],
            cache_mod.Cache.timestamp_for(now_index + 1),
            cache_mod.Cache.timestamp_for(now_index + 1),
            on_invalid="raw",
        )
        assert result == {"fc": [999.0]}


# -- AC4: get_time_range's own behavior/output stay unaffected -------------


class TestGetTimeRangeUnaffected:
    """Given the existing get_time_range accessor from TASK-0002, this
    task's changes leave its behavior and output unaffected — the
    unmodified `tests/test_cache_core.py` suite is this task's own
    regression check; this test adds a same-cache-instance cross-check
    alongside the new accessor."""

    def test_get_time_range_unaffected_by_get_regression_pools(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [9.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        start = datetime(2026, 1, 10, tzinfo=UTC)
        end = start + timedelta(minutes=10)

        by_sensor = cache.get_time_range(["pv"], start, end)
        assert by_sensor == {"pv": [9.0, 9.0, 9.0]}

        cache.get_regression_pools(["pv"], smoothing_radius=1, reference=start + timedelta(days=2))

        by_sensor_again = cache.get_time_range(["pv"], start, end)
        assert by_sensor_again == {"pv": [9.0, 9.0, 9.0]}


# -- AC5: NaN entries support a valid ~np.isnan(pool) mask ------------------


class TestNaNAsValidMaskForRegressionBase:
    """Given a NaN entry in the returned pool, ~np.isnan(pool) is a valid
    mask this accessor's shape/dtype supports (regression/base.py's own
    `build_pool` derives its weight mask exactly this way) — this task
    verifies shape/dtype only, not the weighting logic itself."""

    def test_isnan_mask_has_matching_shape_and_dtype(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [1.0 if i % 2 == 0 else "unavailable" for i in range(n)]

        window_days = 2
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, tzinfo=UTC)

        pool = cache.get_regression_pools(["fc"], smoothing_radius=0, reference=reference)["fc"]
        mask = ~np.isnan(pool)
        assert mask.shape == pool.shape
        assert mask.dtype == np.bool_
        assert mask.any() and (~mask).any()  # genuinely mixed, not degenerate


# -- 288-slot day-boundary wraparound (not one of the 5 ACs, but directly --
# -- follows from ADR-008 §2 / regression/base.py's documented gap) --------


class TestDayBoundaryWraparound:
    """A neighbor offset that reaches past the window's first or last slot
    (earliest day's negative-offset neighbor; the newest day's positive-offset
    neighbor reaching into today) is resolved via absolute-index arithmetic
    and read from the **extended** window `get_regression_pools` validates
    (the window widened by `smoothing_radius` slots at each end, ADR-008 §2
    Amendment 2026-10-10, `TASK-0044`) — a real value wherever the source has
    one, not whatever an earlier read left in the cache."""

    def test_edge_neighbors_are_real_values_from_the_extended_window(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [3.0] * n

        window_days = 3
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)

        pool = cache.get_regression_pools(["fc"], smoothing_radius=1, reference=reference)["fc"]
        wd = window_days  # column layout: offset -1 -> [0:wd], 0 -> [wd:2wd], +1 -> [2wd:3wd]

        assert pool[0, 0] == 3.0  # slot 0, offset -1, oldest day: one slot before the window
        assert pool[287, 2 * wd + (wd - 1)] == 3.0  # slot 287, offset +1, newest day: into today
        assert not np.isnan(pool).any()

    def test_the_extended_range_is_what_gets_validated(self) -> None:
        cache = TestTrimNeverDiscardsTheTrainingPool._cache_and_fetch_log(3)[0]
        reference = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)
        first = cache._training_window_start_index(reference)
        last = first + 3 * cache_mod.SLOTS_PER_DAY - 1

        cache.get_regression_pools(["s"], smoothing_radius=2, reference=reference)

        assert cache.validated_range("s") == (first - 2, last + 2)

    def test_the_pool_does_not_depend_on_what_the_cache_already_held(self) -> None:
        """The reason for the extension: a fit right after a restart (empty
        cache) and one in steady state (cache holding neighboring days) read
        identical pools."""
        reference = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)
        fresh, _ = TestTrimNeverDiscardsTheTrainingPool._cache_and_fetch_log(3)
        fresh_pool = fresh.get_regression_pools(["s"], 2, reference=reference)["s"]

        warm, _ = TestTrimNeverDiscardsTheTrainingPool._cache_and_fetch_log(3)
        first = warm._training_window_start_index(reference)
        warm.get_time_range(  # an earlier recalibration's days on both sides
            ["s"],
            cache_mod.Cache.timestamp_for(first - 2 * cache_mod.SLOTS_PER_DAY),
            cache_mod.Cache.timestamp_for(first + 5 * cache_mod.SLOTS_PER_DAY),
            on_invalid="raw",
        )
        warm_pool = warm.get_regression_pools(["s"], 2, reference=reference)["s"]

        assert np.array_equal(fresh_pool, warm_pool, equal_nan=True)

    def test_a_not_yet_settled_tail_is_nan_and_is_re_read_later(self) -> None:
        """At the 00:01 recalibration today's first slot has not elapsed: the
        source has nothing there, so the newest day's positive neighbor of the
        last slot is `NaN` -- and, being unsettled, stays unvalidated so the
        next read asks again (the settled-end rule of ADR-007a §4)."""
        reference = datetime(2026, 1, 10, 0, 1, tzinfo=UTC)
        today_start = int(cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC)))
        calls: list[tuple[int, int]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            first = int(cache_mod.Cache.index_for(start))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            calls.append((first, first + n - 1))
            return [3.0 if first + i < today_start else None for i in range(n)]

        cache = cache_mod.Cache(3, fetch_fn, clock=lambda: reference)
        pool = cache.get_regression_pools(["s"], 1, reference=reference)["s"]

        assert np.isnan(pool[287, 2 * 3 + 2])  # slot 287, offset +1, newest day
        assert not np.isnan(pool[0, 0])  # the head side is real
        assert cache.validated_range("s")[1] == today_start - 1  # tail left unvalidated

        calls.clear()
        cache.get_regression_pools(["s"], 1, reference=reference)
        assert calls == [(today_start, today_start)]  # asked again, only for the tail


# -- TASK-0043: trim never discards what the training pool reads -----------


class TestTrimNeverDiscardsTheTrainingPool:
    """ADR-007a §1 Amendment 2026-10-10: `trim(reference)` keeps whole days
    back from `reference`, exactly the window `get_regression_pools` reads for
    the same `reference` — so a trim at *any* time of day (the 00:01
    recalibration, a button press mid-day, just before midnight) discards
    nothing the pool reads, and the next pool read needs no new fetch."""

    @staticmethod
    def _cache_and_fetch_log(
        window_days: int, time_zone: str = "UTC"
    ) -> tuple[Any, list[tuple[int, int]]]:
        calls: list[tuple[int, int]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            first = cache_mod.Cache.index_for(start)
            n = round((end - start) / cache_mod.SLOT_DURATION)
            calls.append((first, first + n - 1))
            # The value *is* the absolute slot index: any misplaced or
            # missing slot changes the array.
            return [float(first + i) for i in range(n)]

        cache = cache_mod.Cache(
            window_days=window_days, fetch_fn=fetch_fn, local_tz=ZoneInfo(time_zone)
        )
        return cache, calls

    @pytest.mark.parametrize(
        "time_zone", ["UTC", "Europe/Berlin", "America/New_York", "Pacific/Auckland"]
    )
    @pytest.mark.parametrize("window_days", [1, 3])
    @pytest.mark.parametrize("smoothing_radius", [0, 2])
    @pytest.mark.parametrize(
        "time_of_day",
        [(0, 0), (0, 1), (14, 37), (23, 55)],
        ids=["00:00", "00:01", "14:37", "23:55"],
    )
    def test_pool_is_identical_and_needs_no_refetch(
        self, time_zone: str, window_days: int, smoothing_radius: int, time_of_day: tuple[int, int]
    ) -> None:
        cache, calls = self._cache_and_fetch_log(window_days, time_zone)
        # `time_of_day` is the *local* clock time of the recalibration.
        reference = datetime(2026, 6, 20, *time_of_day, tzinfo=ZoneInfo(time_zone))
        before = cache.get_regression_pools(["s"], smoothing_radius, reference=reference)["s"]
        window_start = cache._training_window_start_index(reference)

        cache.trim(reference=reference, smoothing_radius=smoothing_radius)

        # The stored list still starts at (or before) the oldest read slot --
        # slot 0 of the oldest training day less the neighbor slots -- and
        # the validated range still vouches for it.
        oldest_read = window_start - smoothing_radius
        assert cache._list_offset["s"] <= oldest_read
        assert cache.validated_range("s")[0] <= oldest_read

        calls.clear()
        after = cache.get_regression_pools(["s"], smoothing_radius, reference=reference)["s"]
        assert np.array_equal(before, after, equal_nan=True)
        assert calls == []

    @pytest.mark.parametrize("smoothing_radius", [0, 2])
    def test_the_floor_is_exactly_the_oldest_slot_the_pool_reads(
        self, smoothing_radius: int
    ) -> None:
        """Not merely "at or before": it keeps nothing older either, so the
        cache is bounded (this is what stops the daily growth)."""
        window_days = 3
        cache, _calls = self._cache_and_fetch_log(window_days)
        reference = datetime(2026, 6, 20, 14, 37, tzinfo=UTC)
        cache.get_regression_pools(["s"], smoothing_radius, reference=reference)
        # Pre-seed an extra older day, as a previous recalibration would have.
        window_start = cache._training_window_start_index(reference)
        oldest_read = window_start - smoothing_radius
        cache.get_time_range(
            ["s"],
            cache_mod.Cache.timestamp_for(window_start - cache_mod.SLOTS_PER_DAY),
            cache_mod.Cache.timestamp_for(oldest_read - 1),
            on_invalid="raw",
        )
        assert cache._list_offset["s"] == window_start - cache_mod.SLOTS_PER_DAY

        cache.trim(reference=reference, smoothing_radius=smoothing_radius)

        assert cache._list_offset["s"] == oldest_read
        assert cache.validated_range("s")[0] == oldest_read

    def test_a_trim_without_the_radius_would_force_a_refetch(self) -> None:
        """The reason `trim` takes the radius: without it the neighbor slots
        before the window are dropped and the next pool read must fetch them
        again, every recalibration."""
        cache, calls = self._cache_and_fetch_log(3)
        reference = datetime(2026, 6, 20, 0, 1, tzinfo=UTC)
        cache.get_regression_pools(["s"], 2, reference=reference)

        cache.trim(reference=reference)  # radius omitted
        calls.clear()
        cache.get_regression_pools(["s"], 2, reference=reference)

        assert len(calls) == 1  # the two head slots, fetched again


# -- TASK-0044: local day boundaries, UTC-clock slots ----------------------

_TIME_ZONES = ["UTC", "Europe/Berlin", "America/New_York", "Pacific/Auckland", "Asia/Kolkata"]


def _local_midnight_index(day: Any, time_zone: str) -> int:
    """Absolute index of local midnight on `day` -- derived here with
    `zoneinfo` alone, independently of the code under test."""
    local_midnight = datetime(day.year, day.month, day.day, tzinfo=ZoneInfo(time_zone))
    return int(cache_mod.Cache.index_for(local_midnight))


def _window_bounds(reference: datetime, window_days: int, time_zone: str) -> tuple[int, int]:
    """`(first_index, last_index)` of the training window per ADR-008 §2
    Amendment 2026-10-10: `window_days` complete local days ending at local
    midnight today, `today` taken from the *instant* `reference`."""
    today = reference.astimezone(ZoneInfo(time_zone)).date()
    first = _local_midnight_index(today - timedelta(days=window_days), time_zone)
    end = _local_midnight_index(today, time_zone)
    return first, end - 1


class TestTrainingWindowIsLocalDaysWithUtcClockSlots:
    """ADR-008 §2 Amendment 2026-10-10 (`TASK-0044`, human decision):
    the training window is `window_days` complete *local* days, but a model
    slot stays the *UTC-clock* slot (`index % 288`)."""

    @staticmethod
    def _cache(window_days: int, time_zone: str, value: str) -> Any:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            first = cache_mod.Cache.index_for(start)
            n = round((end - start) / cache_mod.SLOT_DURATION)
            if value == "utc_slot":
                return [float((first + i) % cache_mod.SLOTS_PER_DAY) for i in range(n)]
            return [float(first + i) for i in range(n)]  # "index"

        return cache_mod.Cache(window_days, fetch_fn, local_tz=ZoneInfo(time_zone))

    @pytest.mark.parametrize("time_zone", _TIME_ZONES)
    def test_every_row_is_one_utc_clock_slot_in_every_local_day(self, time_zone: str) -> None:
        """Fetch returns each slot's own UTC slot-of-day: row `s` must be
        constant `s` across all days -- i.e. the model slot is the UTC clock
        slot whatever the timezone -- with no hole (all days complete)."""
        cache = self._cache(3, time_zone, "utc_slot")
        reference = datetime(2026, 6, 20, 14, 37, tzinfo=UTC)

        pool = cache.get_regression_pools(["s"], 0, reference=reference)["s"]

        assert pool.shape == (cache_mod.SLOTS_PER_DAY, 3)
        assert not np.isnan(pool).any()
        expected = np.repeat(np.arange(cache_mod.SLOTS_PER_DAY, dtype=float)[:, None], 3, axis=1)
        assert np.array_equal(pool, expected)

    @pytest.mark.parametrize("time_zone", _TIME_ZONES)
    def test_the_window_is_exactly_the_complete_local_days_ending_at_local_midnight(
        self, time_zone: str
    ) -> None:
        window_days = 3
        cache = self._cache(window_days, time_zone, "index")
        reference = datetime(2026, 6, 20, 14, 37, tzinfo=UTC)
        first, last = _window_bounds(reference, window_days, time_zone)

        pool = cache.get_regression_pools(["s"], 0, reference=reference)["s"]

        assert cache.validated_range("s") == (first, last)
        assert pool.min() == first  # starts at local midnight of today - window_days
        assert pool.max() == last  # ends the slot before local midnight today
        assert len(np.unique(pool)) == pool.size  # no slot read twice

    @pytest.mark.parametrize("time_zone", _TIME_ZONES[1:])
    def test_the_same_instant_gives_the_same_pools_whatever_its_tzinfo(
        self, time_zone: str
    ) -> None:
        """The button passes a UTC `now`, the midnight trigger a local one."""
        instant = datetime(2026, 6, 20, 14, 37, tzinfo=UTC)
        pools = []
        for reference in (instant, instant.astimezone(ZoneInfo(time_zone))):
            cache = self._cache(3, time_zone, "index")
            pools.append(cache.get_regression_pools(["s"], 1, reference=reference)["s"])
        assert np.array_equal(pools[0], pools[1], equal_nan=True)

    @pytest.mark.parametrize("time_zone", _TIME_ZONES)
    def test_the_window_advances_exactly_one_local_day_at_local_midnight(
        self, time_zone: str
    ) -> None:
        cache = self._cache(3, time_zone, "index")
        zone = ZoneInfo(time_zone)
        before = datetime(2026, 6, 20, 23, 55, tzinfo=zone)
        after = datetime(2026, 6, 21, 0, 5, tzinfo=zone)
        assert (
            cache._training_window_start_index(after) - cache._training_window_start_index(before)
            == cache_mod.SLOTS_PER_DAY
        )

    def test_utc_is_unchanged_from_the_previous_utc_day_definition(self) -> None:
        cache = self._cache(3, "UTC", "index")
        reference = datetime(2026, 6, 20, 14, 37, tzinfo=UTC)
        today_start = datetime(2026, 6, 20, tzinfo=UTC)
        expected_first = int(cache_mod.Cache.index_for(today_start)) - 3 * cache_mod.SLOTS_PER_DAY
        assert cache._training_window_start_index(reference) == expected_first

    def test_a_23_hour_dst_day_leaves_the_slots_it_lacks_nan_and_reads_nothing_twice(self) -> None:
        # Europe/Berlin springs forward on 2026-03-29: that local day has 276 slots.
        time_zone = "Europe/Berlin"
        cache = self._cache(3, time_zone, "index")
        reference = datetime(2026, 3, 31, 12, 0, tzinfo=ZoneInfo(time_zone))  # days: 28, 29, 30 Mar
        first, last = _window_bounds(reference, 3, time_zone)
        assert last - first + 1 == 3 * 288 - 12

        pool = cache.get_regression_pools(["s"], 0, reference=reference)["s"]

        assert int(np.isnan(pool).sum()) == 12
        values = pool[~np.isnan(pool)]
        assert len(np.unique(values)) == values.size
        assert values.min() == first and values.max() == last
        assert values.size == last - first + 1  # every slot of the window is read exactly once

    def test_a_25_hour_dst_day_uses_its_first_288_slots_only(self) -> None:
        # Europe/Berlin falls back on 2026-10-25: that local day has 300 slots.
        time_zone = "Europe/Berlin"
        cache = self._cache(3, time_zone, "index")
        reference = datetime(
            2026, 10, 27, 12, 0, tzinfo=ZoneInfo(time_zone)
        )  # days: 24, 25, 26 Oct
        first, last = _window_bounds(reference, 3, time_zone)
        assert last - first + 1 == 3 * 288 + 12

        pool = cache.get_regression_pools(["s"], 0, reference=reference)["s"]

        assert not np.isnan(pool).any()
        assert len(np.unique(pool)) == pool.size  # nothing twice
        assert pool.min() == first
        assert pool.max() <= last
        assert pool.size == 3 * 288

    @pytest.mark.parametrize("time_zone", _TIME_ZONES)
    def test_smoothing_neighbors_come_from_the_extended_window(self, time_zone: str) -> None:
        window_days = 3
        radius = 2
        cache = self._cache(window_days, time_zone, "index")
        reference = datetime(2026, 6, 20, 14, 37, tzinfo=UTC)
        first, last = _window_bounds(reference, window_days, time_zone)

        pool = cache.get_regression_pools(["s"], radius, reference=reference)["s"]

        assert not np.isnan(pool).any()  # every neighbor is a real, fetched value
        assert pool.min() == first - radius and pool.max() == last + radius
        assert cache.validated_range("s") == (first - radius, last + radius)

    @pytest.mark.parametrize("time_zone", _TIME_ZONES)
    def test_the_trim_floor_is_the_pools_first_slot(self, time_zone: str) -> None:
        cache = self._cache(3, time_zone, "index")
        reference = datetime(2026, 6, 20, 14, 37, tzinfo=UTC)
        first, _last = _window_bounds(reference, 3, time_zone)
        assert cache._training_window_start_index(reference) == first
