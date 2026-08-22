"""Zero-mocking tests for `cache.py`'s storage core (ADR-007a §1-§5, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
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


cache_mod = _load("cache.py", "shady.cache")


class TestNoValidDataFetchesEntireWindow:
    """Given a cache constructed with a fake fetch_fn returning canned
    three-state data and no valid data yet for a sensor, when
    get_time_range is called, the entire configured window_days history
    is fetched in one call (ADR-007a §4)."""

    def test_full_window_fetched_in_one_call(self) -> None:
        calls: list[tuple[str, datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((sensor_id, start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [1.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        start = datetime(2026, 1, 10, tzinfo=UTC)
        end = start + timedelta(minutes=5)  # a tiny, 2-slot request

        cache.get_time_range(["pv"], start, end)

        assert len(calls) == 1
        sensor_id, call_start, call_end = calls[0]
        assert sensor_id == "pv"
        # Whole window_days=1 (288 slots), not just the 2 requested.
        assert (call_end - call_start) == timedelta(minutes=cache_mod.SLOT_MINUTES * 288)
        # The fetched range still covers what was actually requested.
        assert call_start <= start
        assert call_end >= end


class TestMissingTailOnlyRefetchesTail:
    """Given a sensor already valid except for a missing recent tail, when
    get_time_range is called, only the missing tail is fetched (ADR-007a
    §4)."""

    def test_only_tail_is_fetched(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [2.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        anchor = datetime(2026, 1, 10, tzinfo=UTC)
        window_start = anchor - timedelta(days=1) + cache_mod.SLOT_DURATION

        # First access establishes validity through 'anchor'.
        cache.get_time_range(["pv"], window_start, anchor)
        assert len(calls) == 1

        # Request a range extending 3 slots (15 min) past 'anchor'.
        tail_end = anchor + timedelta(minutes=15)
        cache.get_time_range(["pv"], window_start, tail_end)

        assert len(calls) == 2
        second_start, second_end = calls[1]
        # Only the missing tail — 3 slots — not the whole window again.
        assert (second_end - second_start) == timedelta(minutes=15)
        assert second_start == anchor + cache_mod.SLOT_DURATION

    def test_missing_head_is_also_fetched_correctly(self) -> None:
        """A gap before from_index (e.g. after invalidate, or after
        window_days grows) is fetched as a head range, and to_index is
        left untouched by that fetch."""
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [3.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        anchor = datetime(2026, 1, 10, tzinfo=UTC)

        # First access triggers a full-window fetch ending at 'anchor'.
        cache.get_time_range(["pv"], anchor, anchor)
        assert len(calls) == 1
        from_index, to_index = cache.validated_range("pv")

        # Carve out a genuine head gap: invalidate the first 3 slots.
        cache.invalidate("pv", from_index, from_index + 2)
        shrunk_from, shrunk_to = cache.validated_range("pv")
        assert shrunk_from == from_index + 3
        assert shrunk_to == to_index  # invalidating the head never touches to_index

        # Reading back across the invalidated head triggers exactly one
        # more fetch, for just those 3 slots.
        result = cache.get_time_range(
            ["pv"],
            cache_mod.Cache.timestamp_for(from_index),
            cache_mod.Cache.timestamp_for(from_index + 2),
            on_invalid="raw",
        )

        assert len(calls) == 2
        second_start, second_end = calls[1]
        assert (second_end - second_start) == timedelta(minutes=cache_mod.SLOT_MINUTES * 3)
        assert result == {"pv": [3.0, 3.0, 3.0]}


class TestPushGuardAndPushOnlySensor:
    """Given a push(...) call whose lowest index is below not_before_index,
    entries below that boundary are silently dropped (ADR-007a §3). Given
    a to_index=None sensor, pushed values extend validity without the
    sensor ever being (re-)queried (ADR-007a §2)."""

    def test_below_boundary_dropped_and_never_requeried(self) -> None:
        calls: list[tuple[str, datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((sensor_id, start, end))
            return []

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))

        cache.push(
            "shady_forecast",
            {base - 1: 999.0, base: 10.0, base + 1: 11.0},
            not_before_index=base,
        )

        start_ts = cache_mod.Cache.timestamp_for(base - 1)
        end_ts = cache_mod.Cache.timestamp_for(base + 1)
        result = cache.get_time_range(["shady_forecast"], start_ts, end_ts, on_invalid="raw")

        assert result == {"shady_forecast": [None, 10.0, 11.0]}
        assert calls == []  # to_index=None: never (re-)queried

    def test_validated_to_index_stays_none_after_push(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            raise AssertionError("push-only sensor must never be queried")

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))

        cache.push("shady_forecast", {base: 1.0}, not_before_index=base)
        assert cache.validated_range("shady_forecast") == (base, None)

        cache.push("shady_forecast", {base + 1: 2.0, base + 2: 3.0}, not_before_index=base)
        assert cache.validated_range("shady_forecast") == (base, None)


class TestGetTimeRangeGroupByShapes:
    """Given get_time_range(..., group_by="sensor") vs group_by="slot"
    against the same data, the two return the documented complementary
    shapes (ADR-007a §5)."""

    def test_sensor_vs_slot_grouping(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            raise AssertionError("data is pre-seeded via push for this shape test")

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        start = datetime(2026, 1, 10, tzinfo=UTC)
        start_index = cache_mod.Cache.index_for(start)

        cache.push(
            "a",
            {start_index: 10.0, start_index + 1: 11.0, start_index + 2: 12.0},
            not_before_index=start_index,
        )
        cache.push(
            "b",
            {start_index: 20.0, start_index + 1: 21.0, start_index + 2: 22.0},
            not_before_index=start_index,
        )
        end = start + timedelta(minutes=10)

        by_sensor = cache.get_time_range(["a", "b"], start, end, group_by="sensor")
        assert by_sensor == {"a": [10.0, 11.0, 12.0], "b": [20.0, 21.0, 22.0]}

        by_slot = cache.get_time_range(["a", "b"], start, end, group_by="slot")
        assert by_slot == [
            {"a": 10.0, "b": 20.0},
            {"a": 11.0, "b": 21.0},
            {"a": 12.0, "b": 22.0},
        ]


class TestTrimAdvancesOffsetWithoutOffByOne:
    """Given cache.trim() is called after the rolling window has advanced,
    list_offset advances and validated ranges stay meaningful — no
    off-by-one against the new offset (ADR-007a §1)."""

    def test_trim_advances_offset_and_keeps_validated_meaningful(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [1.0] * n

        window_days = 2
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        anchor = datetime(2026, 1, 10, tzinfo=UTC)

        cache.get_time_range(["pv"], anchor - timedelta(minutes=5), anchor)
        _, to_index = cache.validated_range("pv")
        assert to_index is not None

        # Advance the reference by exactly 10 slots (50 minutes).
        new_reference = anchor + timedelta(minutes=50)
        cache.trim(reference=new_reference)

        expected_floor = (
            cache_mod.Cache.index_for(new_reference) - window_days * cache_mod.SLOTS_PER_DAY + 1
        )
        assert cache._list_offset["pv"] == expected_floor

        new_from, new_to = cache.validated_range("pv")
        assert new_from == expected_floor
        assert new_to == to_index  # unchanged: still well within the window

        # No off-by-one: everything from the new floor through the old
        # to_index is still correctly readable, with no re-fetch.
        result = cache.get_time_range(
            ["pv"],
            cache_mod.Cache.timestamp_for(expected_floor),
            cache_mod.Cache.timestamp_for(to_index),
            on_invalid="raw",
        )
        assert len(calls) == 1  # trim triggered no new fetch
        assert all(value == 1.0 for value in result["pv"])


class TestInvalidate:
    """Given invalidate() over a range, those entries reset to None and
    validated shrinks accordingly, forcing a re-fetch before that range is
    served again (ADR-007a §3)."""

    def test_invalidate_tail_shrinks_validated_and_forces_refetch(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [5.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        anchor = datetime(2026, 1, 10, tzinfo=UTC)
        window_start = anchor - timedelta(days=1) + cache_mod.SLOT_DURATION

        cache.get_time_range(["pv"], window_start, anchor)
        assert len(calls) == 1

        anchor_index = cache_mod.Cache.index_for(anchor)
        cache.invalidate("pv", anchor_index - 2, anchor_index)

        _from_index, to_index = cache.validated_range("pv")
        assert to_index == anchor_index - 3

        # Reading the invalidated tail again triggers exactly one more
        # fetch, for just the invalidated slots.
        cache.get_time_range(["pv"], window_start, anchor)
        assert len(calls) == 2
        second_start, second_end = calls[1]
        assert (second_end - second_start) == timedelta(minutes=cache_mod.SLOT_MINUTES * 3)
