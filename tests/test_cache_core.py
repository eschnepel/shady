from __future__ import annotations

from datetime import datetime

from ._module_loader import load_module


cache_module = load_module("shady.cache", "cache.py")


def _make_fetch_log():
    calls: list[tuple[str, datetime, datetime]] = []

    def fetch_fn(sensor_id: str, start: datetime, end: datetime):
        calls.append((sensor_id, start, end))
        slot_count = int((end - start).total_seconds() // 300) + 1
        return [float(index) for index in range(slot_count)]

    return calls, fetch_fn


def test_get_time_range_fetches_entire_window_on_first_access():
    calls, fetch_fn = _make_fetch_log()
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=fetch_fn)
    start = datetime(2026, 8, 20, 0, 0)
    end = datetime(2026, 8, 20, 0, 10)

    result = cache.get_time_range(["pv"], start, end)

    assert len(calls) == 1
    assert calls[0][0] == "pv"
    assert (calls[0][2] - calls[0][1]).total_seconds() == (cache.window_slots - 1) * 300
    assert len(result["pv"]) == 3


def test_get_time_range_fetches_only_missing_tail():
    calls, fetch_fn = _make_fetch_log()
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=fetch_fn)
    start = datetime(2026, 8, 20, 0, 0)
    end = datetime(2026, 8, 20, 0, 15)
    cache.get_time_range(["pv"], start, end)
    calls.clear()
    cache.invalidate("pv", cache._index_for(datetime(2026, 8, 20, 0, 10)), cache._index_for(datetime(2026, 8, 20, 0, 10)))

    result = cache.get_time_range(["pv"], start, end)

    assert len(calls) == 1
    assert 0.0 in result["pv"]


def test_push_drops_values_before_not_before_index():
    calls, fetch_fn = _make_fetch_log()
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=fetch_fn)
    cache.push("fc", {10: 1.0, 11: 2.0, 12: 3.0}, not_before_index=11)

    assert cache.values["fc"][0] == 2.0
    assert cache.validated["fc"] == (11, 12)


def test_push_for_open_ended_series_keeps_validated_open():
    calls, fetch_fn = _make_fetch_log()
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=fetch_fn)
    cache.validated["forecast"] = (10, None)
    cache.push("forecast", {13: 1.0}, not_before_index=0)

    assert cache.validated["forecast"] == (10, None)


def test_get_time_range_group_by_shapes_match():
    calls, fetch_fn = _make_fetch_log()
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=fetch_fn)
    start = datetime(2026, 8, 20, 0, 0)
    end = datetime(2026, 8, 20, 0, 10)
    cache.push("a", {cache._index_for(start): 1.0, cache._index_for(start.replace(minute=5)): 2.0, cache._index_for(end): 3.0}, not_before_index=0)
    cache.push("b", {cache._index_for(start): 4.0, cache._index_for(start.replace(minute=5)): 5.0, cache._index_for(end): 6.0}, not_before_index=0)

    by_sensor = cache.get_time_range(["a", "b"], start, end, group_by="sensor")
    by_slot = cache.get_time_range(["a", "b"], start, end, group_by="slot")

    assert by_sensor == {"a": [1.0, 2.0, 3.0], "b": [4.0, 5.0, 6.0]}
    assert by_slot == [{"a": 1.0, "b": 4.0}, {"a": 2.0, "b": 5.0}, {"a": 3.0, "b": 6.0}]


def test_trim_advances_offset_without_breaking_validated_ranges():
    calls, fetch_fn = _make_fetch_log()
    cache = cache_module.ShadyCache(window_days=1, fetch_fn=fetch_fn)
    base_index = cache._index_for(datetime(2026, 8, 20, 0, 0))
    cache.values["pv"] = [float(index) for index in range(cache.window_slots + 3)]
    cache.list_offset["pv"] = base_index
    cache.validated["pv"] = (base_index, base_index + cache.window_slots + 2)

    cache.trim()

    assert cache.list_offset["pv"] == base_index + 3
    assert cache.validated["pv"][0] == base_index + 3
