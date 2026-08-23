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

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

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
    """A neighbor offset that would reach outside this call's own window
    (earliest day's negative-offset neighbor; yesterday's positive-offset
    neighbor reaching into today) is NaN — resolved via absolute-index
    arithmetic, never fetched from beyond the configured window."""

    def test_earliest_and_latest_day_edge_offsets_are_nan_others_are_not(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [3.0] * n

        window_days = 3
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        reference = datetime(2026, 1, 10, 8, 0, tzinfo=UTC)

        pool = cache.get_regression_pools(["fc"], smoothing_radius=1, reference=reference)["fc"]
        # Column layout: offset -1 -> [0:wd], offset 0 -> [wd:2wd], offset +1 -> [2wd:3wd].
        wd = window_days

        # slot=0, offset=-1, oldest day (day_i=0): wraps to a day *before*
        # the window -> NaN.
        assert np.isnan(pool[0, 0])
        # slot=0, offset=-1, a later day (day_i=1): stays in-window -> real.
        assert pool[0, 1] == 3.0

        # slot=287, offset=+1, yesterday (day_i=wd-1, the newest day):
        # wraps into today -> NaN.
        assert np.isnan(pool[287, 2 * wd + (wd - 1)])
        # slot=287, offset=+1, an earlier day: stays in-window -> real.
        assert pool[287, 2 * wd + 0] == 3.0

        # A slot away from midnight never wraps, regardless of offset.
        assert not np.isnan(pool[100, :]).any()
