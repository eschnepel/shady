from __future__ import annotations

from datetime import date, datetime, timedelta

from ._module_loader import load_module


cache_module = load_module("shady.cache", "cache.py")


def test_get_pinned_slot_pool_uses_reference_window_and_future_fallback():
    today = date.today()
    epoch = datetime(1970, 1, 1)
    cache = cache_module.ShadyCache(1, lambda sensor_id, start, end: [], epoch=epoch)
    slot = 12
    hour, minute = divmod(slot * 5, 60)
    start_day = today - timedelta(days=1)
    cache.push(
        "string-1",
        {
            cache._index_for(datetime(start_day.year, start_day.month, start_day.day, hour, minute)): 10.0,
            cache._index_for(datetime(today.year, today.month, today.day, hour, minute)): 20.0,
        },
        not_before_index=0,
    )

    cache.pin_reference(today)
    assert cache.get_pinned_slot_pool(["string-1"], slot)["string-1"] == [10.0, 20.0]

    cache.pin_reference(today + timedelta(days=10))
    assert cache.get_pinned_slot_pool(["string-1"], slot)["string-1"] == [10.0, 20.0]
