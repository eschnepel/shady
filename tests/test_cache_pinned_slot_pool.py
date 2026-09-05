"""Zero-mocking tests for `cache.py`'s TASK-0015b extension: the
cache-wide pinned diagnostic reference (`pin_reference`/`clear_reference`/
`pinned_reference`) and `get_pinned_slot_pool` (ADR-007a §6, ADR-004
§2a).

Mirrors `tests/test_cache_regression_pools.py`'s own zero-mocking,
direct file-path-import harness (loads `cache.py` on its own, without
pulling in `homeassistant.*` via package import) — this task extends the
same `cache.py` module TASK-0006 did, sequentially (see this task's own
"Reuses..." note in `tasks/TASK-0015b-...md`).

`get_pinned_slot_pool` anchors on the real wall clock
(`datetime.now(UTC)`) whenever no pin is set, or the pin is in the
future — unlike `get_regression_pools`'s injectable `reference`
parameter, there is no way to override "today" here (ADR-007a §6's
auto-tracking fallback is deliberately tied to real time, matching
whatever "today" auto-tracking already means everywhere else in the
project). Tests exercising that path compute their own expectation from
the same `datetime.now(UTC).date()` call the implementation itself
uses, rather than mocking it — genuinely zero-mocking, not just
avoiding a mock *library*.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
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


def _midnight(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)


def _index_valued_fetch_fn(
    sensor_id: str, start: datetime, end: datetime
) -> list[float | None | str]:
    """Every slot's value is its own absolute index, as a float — lets
    a test compute an expected value at any timestamp independently,
    via `Cache.index_for`, without the fetch_fn itself needing to know
    anything about the window being requested."""
    n = round((end - start) / cache_mod.SLOT_DURATION)
    start_index = cache_mod.Cache.index_for(start)
    return [float(start_index + i) for i in range(n)]


def _expected_window_values(anchor: date, window_days: int, slot_of_day: int) -> list[float]:
    """Independent re-derivation of the (oldest-day-first) values
    `get_pinned_slot_pool` should return for a fully-valid,
    all-float-backed window anchored on `anchor`."""
    window_start_date = anchor - timedelta(days=window_days - 1)
    window_start_index = cache_mod.Cache.index_for(_midnight(window_start_date))
    return [
        float(window_start_index + day_offset * cache_mod.SLOTS_PER_DAY + slot_of_day)
        for day_offset in range(window_days)
    ]


# -- pin_reference / clear_reference / pinned_reference ---------------------


class TestPinReferenceClearReferenceAndProperty:
    """Given a fresh `Cache`, `pinned_reference` starts `None`;
    `pin_reference(d)` sets it to exactly `d`; `clear_reference()` sets
    it back to `None` (ADR-007a §6)."""

    def test_starts_unset(self) -> None:
        cache = cache_mod.Cache(window_days=3, fetch_fn=_index_valued_fetch_fn)
        assert cache.pinned_reference is None

    def test_pin_reference_sets_exact_date(self) -> None:
        cache = cache_mod.Cache(window_days=3, fetch_fn=_index_valued_fetch_fn)
        pinned = date(2026, 5, 1)

        cache.pin_reference(pinned)

        assert cache.pinned_reference == pinned

    def test_clear_reference_resets_to_none(self) -> None:
        cache = cache_mod.Cache(window_days=3, fetch_fn=_index_valued_fetch_fn)
        cache.pin_reference(date(2026, 5, 1))

        cache.clear_reference()

        assert cache.pinned_reference is None

    def test_pin_reference_can_be_moved_to_a_new_date_directly(self) -> None:
        cache = cache_mod.Cache(window_days=3, fetch_fn=_index_valued_fetch_fn)
        cache.pin_reference(date(2026, 5, 1))

        cache.pin_reference(date(2026, 5, 2))

        assert cache.pinned_reference == date(2026, 5, 2)


# -- window resolution (ADR-007a §6) -----------------------------------------


class TestGetPinnedSlotPoolNoPinAutoTracksToday:
    """Given no pin is set, the window resolves to `[today -
    window_days, today]` (ADR-007a §6)."""

    def test_matches_today_anchored_window(self) -> None:
        window_days = 3
        slot_of_day = 100
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=_index_valued_fetch_fn)

        result = cache.get_pinned_slot_pool(["fc"], slot_of_day)

        today = datetime.now(UTC).date()
        assert result["fc"] == _expected_window_values(today, window_days, slot_of_day)


class TestGetPinnedSlotPoolPastPinAnchorsThere:
    """Given a pin to a past date, the window resolves to `[pinned -
    window_days, pinned]`, not today's window (ADR-007a §6)."""

    def test_anchors_on_the_pinned_past_date(self) -> None:
        window_days = 4
        slot_of_day = 42
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=_index_valued_fetch_fn)
        pinned = date(2020, 3, 15)  # far enough in the past to never be "today"
        cache.pin_reference(pinned)

        result = cache.get_pinned_slot_pool(["fc"], slot_of_day)

        assert result["fc"] == _expected_window_values(pinned, window_days, slot_of_day)

    def test_pinned_to_today_itself_still_anchors_on_it(self) -> None:
        # "no later than today" (the docstring's own phrasing) includes
        # today itself, not just strictly-past dates.
        window_days = 2
        slot_of_day = 10
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=_index_valued_fetch_fn)
        today = datetime.now(UTC).date()
        cache.pin_reference(today)

        result = cache.get_pinned_slot_pool(["fc"], slot_of_day)

        assert result["fc"] == _expected_window_values(today, window_days, slot_of_day)


class TestGetPinnedSlotPoolFuturePinFallsBackToToday:
    """Given a pin to a future date, `get_pinned_slot_pool` falls back
    to the same today-anchored window an unset pin would use — a future
    pin never resolves to a future-anchored window (ADR-007a §6)."""

    def test_future_pin_matches_the_unpinned_today_anchored_result(self) -> None:
        window_days = 3
        slot_of_day = 77

        unpinned_cache = cache_mod.Cache(window_days=window_days, fetch_fn=_index_valued_fetch_fn)
        unpinned_result = unpinned_cache.get_pinned_slot_pool(["fc"], slot_of_day)

        future_pinned_cache = cache_mod.Cache(
            window_days=window_days, fetch_fn=_index_valued_fetch_fn
        )
        future_pinned_cache.pin_reference(datetime.now(UTC).date() + timedelta(days=30))
        future_pinned_result = future_pinned_cache.get_pinned_slot_pool(["fc"], slot_of_day)

        assert future_pinned_result["fc"] == unpinned_result["fc"]


# -- shape / ordering ---------------------------------------------------------


class TestGetPinnedSlotPoolShapeAndOrder:
    """One value per day in the window, `window_days` points per
    sensor, oldest day first (ADR-007a §6, ADR-004 §2)."""

    def test_one_point_per_day_oldest_first(self) -> None:
        window_days = 5
        slot_of_day = 200
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=_index_valued_fetch_fn)
        pinned = date(2026, 1, 20)
        cache.pin_reference(pinned)

        result = cache.get_pinned_slot_pool(["fc"], slot_of_day)

        values = result["fc"]
        assert len(values) == window_days
        # Strictly increasing by exactly SLOTS_PER_DAY between
        # consecutive entries confirms both the day-spacing and the
        # oldest-first ordering at once.
        for earlier, later in pairwise(values):
            assert isinstance(earlier, float) and isinstance(later, float)
            assert later - earlier == cache_mod.SLOTS_PER_DAY

    def test_multiple_sensors_each_get_their_own_independent_pool(self) -> None:
        calls: list[str] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append(sensor_id)
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [1.0 if sensor_id == "fc" else 2.0] * n

        cache = cache_mod.Cache(window_days=3, fetch_fn=fetch_fn)
        cache.pin_reference(date(2026, 1, 20))

        result = cache.get_pinned_slot_pool(["fc", "pv"], 5)

        assert calls == ["fc", "pv"]
        assert result["fc"] == [1.0, 1.0, 1.0]
        assert result["pv"] == [2.0, 2.0, 2.0]


# -- on_invalid handling (ADR-007a §5) ---------------------------------------


class TestGetPinnedSlotPoolOnInvalidSkipDefault:
    """Default `on_invalid="skip"` drops missing/invalid days entirely
    rather than synthesizing a `0.0` — unlike `get_time_range`'s
    default (ADR-007a §6's own rationale: a scatter/comparison chart
    should never plot a fake zero)."""

    def test_missing_days_are_dropped_not_zeroed(self) -> None:
        window_days = 4
        slot_of_day = 30
        pinned = date(2026, 2, 10)

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            start_index = cache_mod.Cache.index_for(start)
            out: list[float | None | str] = []
            for i in range(n):
                day_offset, pos_in_day = divmod(i, cache_mod.SLOTS_PER_DAY)
                if pos_in_day == slot_of_day:
                    # Make the oldest day's own slot "unavailable".
                    out.append("unavailable" if day_offset == 0 else float(start_index + i))
                else:
                    out.append(1.0)
            return out

        cache = cache_mod.Cache(window_days=window_days, fetch_fn=fetch_fn)
        cache.pin_reference(pinned)

        result = cache.get_pinned_slot_pool(["fc"], slot_of_day)

        assert len(result["fc"]) == window_days - 1
        assert "unavailable" not in result["fc"]
        assert None not in result["fc"]

    def test_all_valid_window_keeps_every_day(self) -> None:
        window_days = 3
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=_index_valued_fetch_fn)
        cache.pin_reference(date(2026, 2, 10))

        result = cache.get_pinned_slot_pool(["fc"], 15)

        assert len(result["fc"]) == window_days


class TestGetPinnedSlotPoolOnInvalidRawAndFloatDefault:
    """`on_invalid="raw"` keeps the original `None`/`str` entry in
    place (no drop); `on_invalid=<float>` substitutes that float
    instead of dropping (ADR-007a §5's shared `_shape` semantics)."""

    def _fetch_fn_with_one_unavailable_day(self, slot_of_day: int) -> object:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            start_index = cache_mod.Cache.index_for(start)
            out: list[float | None | str] = []
            for i in range(n):
                day_offset, pos_in_day = divmod(i, cache_mod.SLOTS_PER_DAY)
                if pos_in_day == slot_of_day:
                    out.append("unavailable" if day_offset == 0 else float(start_index + i))
                else:
                    out.append(1.0)
            return out

        return fetch_fn

    def test_raw_keeps_the_original_string_entry(self) -> None:
        window_days = 3
        slot_of_day = 30
        cache = cache_mod.Cache(
            window_days=window_days, fetch_fn=self._fetch_fn_with_one_unavailable_day(slot_of_day)
        )
        cache.pin_reference(date(2026, 2, 10))

        result = cache.get_pinned_slot_pool(["fc"], slot_of_day, on_invalid="raw")

        assert len(result["fc"]) == window_days
        assert result["fc"][0] == "unavailable"

    def test_float_default_substitutes_the_given_value(self) -> None:
        window_days = 3
        slot_of_day = 30
        cache = cache_mod.Cache(
            window_days=window_days, fetch_fn=self._fetch_fn_with_one_unavailable_day(slot_of_day)
        )
        cache.pin_reference(date(2026, 2, 10))

        result = cache.get_pinned_slot_pool(["fc"], slot_of_day, on_invalid=-1.0)

        assert len(result["fc"]) == window_days
        assert result["fc"][0] == -1.0


# -- validation (ADR-007a §4) --------------------------------------------


class TestGetPinnedSlotPoolValidatesWholeWindowInOneFetchCall:
    """The whole day-range spanned by the window is validated in one
    call per sensor when nothing is validated yet — not one call per
    day or per slot (ADR-007a §4/§6, mirroring
    `get_regression_pools`'s own single-fetch-call guarantee)."""

    def test_single_fetch_call_for_a_fresh_sensor(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [5.0] * n

        cache = cache_mod.Cache(window_days=4, fetch_fn=fetch_fn)
        cache.pin_reference(date(2026, 2, 10))

        cache.get_pinned_slot_pool(["fc"], 15)

        assert len(calls) == 1

    def test_already_validated_window_triggers_no_new_fetch(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [5.0] * n

        cache = cache_mod.Cache(window_days=4, fetch_fn=fetch_fn)
        pinned = date(2026, 2, 10)
        cache.pin_reference(pinned)

        cache.get_pinned_slot_pool(["fc"], 15)
        assert len(calls) == 1

        # Same pin, same window -> already validated, no second fetch.
        cache.get_pinned_slot_pool(["fc"], 200)
        assert len(calls) == 1


# -- effect on trim() (ADR-007a §6's own note) -------------------------------


class TestPinnedReferenceExtendsTrimFloor:
    """A pin outliving several days of real time keeps its own window's
    data from being trimmed out from under it (ADR-007a §6's "effect on
    trimming" note on `trim()`)."""

    def test_trim_does_not_drop_data_still_covered_by_an_old_pin(self) -> None:
        window_days = 2
        cache = cache_mod.Cache(window_days=window_days, fetch_fn=_index_valued_fetch_fn)
        old_pin = date(2026, 1, 1)
        cache.pin_reference(old_pin)

        # Populate and validate the pinned window.
        result_before = cache.get_pinned_slot_pool(["fc"], 0)
        assert len(result_before["fc"]) == window_days

        # "Real" now is much later — without the pin's floor, a plain
        # today-anchored trim would drop the pinned window entirely.
        far_future_now = _midnight(date(2026, 6, 1))
        cache.trim(reference=far_future_now)

        result_after = cache.get_pinned_slot_pool(["fc"], 0)
        assert result_after["fc"] == result_before["fc"]
