"""Zero-mocking tests for `cache.py`'s storage core (ADR-007a §1-§5, ADR-000 §6),
plus the relocated fitted-model cache (ADR-007 §1, ADR-007a §5-Amendment,
TASK-0021).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.
"""

from __future__ import annotations

import ast
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray

from tests.support import _load

# `cache.py` does `from .regression.base import FittedModel` (the
# relocated fitted-model cache, TASK-0021) — `regression/base.py` must
# be loaded and registered in sys.modules under its real dotted name
# first, the same way `tests/test_forecast_adjust.py`'s multi-module
# load order already relies on for `forecast_adjust.py`'s own
# `from .regression.base import FittedModel`.
base_mod = _load("regression/base.py", "shady.regression.base")
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


class TestValidateRangeHistoricalBackfillOptIn:
    """Given a sensor Shady pushes to (to_index=None), _validate_range's
    default behavior (allow_historical_backfill=False, the implicit
    default every other caller in this codebase relies on) still never
    (re-)queries it at all — TestPushGuardAndPushOnlySensor above pins
    this for a purely push-owned sensor with no external source. But a
    hybrid sensor — pushed forward-only *and* backed by a real external
    history source (a `forecast_solar`-shaped baseline with a resolved
    `history_entity_id`, ADR-012 §2a Amendment/TASK-0034) — needs its
    still-missing historical head fetched the first time a caller that
    knows this (get_regression_pools) asks, without losing the "future
    is always current, never re-queried" guarantee for the same sensor
    (TASK-0034-patch-2)."""

    def test_default_still_never_queries_a_push_marked_sensor(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            return []

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))
        cache.push("baseline", {base: 10.0}, not_before_index=base)

        cache._validate_range("baseline", base - 100, base)  # allow_historical_backfill=False

        assert calls == []

    def test_opt_in_fetches_the_missing_historical_head_once(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [7.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))
        cache.push("baseline", {base: 10.0}, not_before_index=base)

        cache._validate_range("baseline", base - 5, base, allow_historical_backfill=True)

        assert len(calls) == 1
        result = cache.get_time_range(
            ["baseline"],
            cache_mod.Cache.timestamp_for(base - 5),
            cache_mod.Cache.timestamp_for(base - 1),
            on_invalid="raw",
        )
        assert result == {"baseline": [7.0] * 5}
        # The future half, pushed directly, is untouched by the backfill.
        assert cache.get_time_range(
            ["baseline"],
            cache_mod.Cache.timestamp_for(base),
            cache_mod.Cache.timestamp_for(base),
            on_invalid="raw",
        ) == {"baseline": [10.0]}

    def test_opt_in_is_a_no_op_once_the_head_is_already_covered(self) -> None:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [7.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))
        cache.push("baseline", {base: 10.0}, not_before_index=base)
        cache._validate_range("baseline", base - 5, base, allow_historical_backfill=True)
        assert len(calls) == 1

        cache._validate_range("baseline", base - 5, base, allow_historical_backfill=True)

        assert len(calls) == 1  # no second fetch — the head is already validated


class TestGetTimeRangeThreadsAllowHistoricalBackfill:
    """`get_time_range` itself (not just `_validate_range` directly, as
    `TestValidateRangeHistoricalBackfillOptIn` above already covers) now
    accepts and threads through `allow_historical_backfill` (ADR-007a §4
    Amendment, TASK-0037 follow-up) — the accessor
    `diagnostics/compare_regressions.py`'s `_selected_value` and
    `coordinator.py`'s `target_cell_temperature_for_slot` both actually
    call, for reading a single already-elapsed slot of a possibly
    push-sourced (`forecast_solar`-shaped) baseline. Without this, such
    a baseline's already-elapsed history was never fetched by *any*
    caller — `get_regression_pools`'s own opt-in never reaches "today"."""

    def test_default_still_never_queries_a_push_marked_sensor(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            raise AssertionError("must not be queried without opting in")

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))
        cache.push("baseline", {base: 10.0}, not_before_index=base)

        result = cache.get_time_range(
            ["baseline"],
            cache_mod.Cache.timestamp_for(base - 1),
            cache_mod.Cache.timestamp_for(base - 1),
            on_invalid="raw",
        )

        assert result == {"baseline": [None]}  # nothing ever fetched for it

    def test_opt_in_resolves_an_already_elapsed_slot_of_a_push_sourced_sensor(self) -> None:
        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [42.0] * n

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        base = cache_mod.Cache.index_for(datetime(2026, 1, 10, tzinfo=UTC))
        # Only the *future* was ever pushed -- exactly a forecast_solar
        # -shaped baseline's own shape: `push()` only ever writes
        # forward from `not_before_index`, never an already-elapsed slot.
        cache.push("baseline", {base: 10.0}, not_before_index=base)

        result = cache.get_time_range(
            ["baseline"],
            cache_mod.Cache.timestamp_for(base - 1),
            cache_mod.Cache.timestamp_for(base - 1),
            on_invalid="raw",
            allow_historical_backfill=True,
        )

        assert result == {"baseline": [42.0]}  # fetched for real, not left `None`


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
    off-by-one against the new offset (ADR-007a §1).

    The retained floor is a **whole-day** boundary: `reference`'s day minus
    `window_days` (ADR-007a §1 Amendment 2026-10-10, TASK-0043) — the first
    slot of the oldest day `get_regression_pools` reads for that reference.
    (Until then it was a rolling `window_days * 288` slots ending at the
    reference slot, which cut one slot too many at the 00:01 recalibration
    and part of a day when run mid-day.)"""

    def _setup(self) -> tuple[Any, list[tuple[datetime, datetime]], datetime]:
        calls: list[tuple[datetime, datetime]] = []

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            calls.append((start, end))
            n = round((end - start) / cache_mod.SLOT_DURATION)
            return [1.0] * n

        cache = cache_mod.Cache(window_days=2, fetch_fn=fetch_fn)
        anchor = datetime(2026, 1, 10, tzinfo=UTC)  # a day boundary
        # Three full days of history: 7th, 8th, 9th.
        cache.get_time_range(
            ["pv"], anchor - timedelta(days=3), anchor - cache_mod.SLOT_DURATION, on_invalid="raw"
        )
        assert len(calls) == 1
        return cache, calls, anchor

    def test_trim_advances_offset_and_keeps_validated_meaningful(self) -> None:
        cache, calls, anchor = self._setup()
        _, to_index = cache.validated_range("pv")
        assert to_index is not None
        oldest_day_start = cache_mod.Cache.index_for(anchor) - 2 * cache_mod.SLOTS_PER_DAY

        # `reference` 50 minutes into the 10th: keeps the 8th and 9th (and
        # the 10th), so exactly the 7th is dropped.
        cache.trim(reference=anchor + timedelta(minutes=50))

        assert cache._list_offset["pv"] == oldest_day_start
        new_from, new_to = cache.validated_range("pv")
        assert new_from == oldest_day_start
        assert new_to == to_index  # unchanged: still well within the window

        # No off-by-one: slot 0 of the oldest retained day (the very first
        # slot of the floor) through the old to_index is readable, with no
        # re-fetch.
        result = cache.get_time_range(
            ["pv"],
            cache_mod.Cache.timestamp_for(oldest_day_start),
            cache_mod.Cache.timestamp_for(to_index),
            on_invalid="raw",
        )
        assert len(calls) == 1  # trim triggered no new fetch
        assert all(value == 1.0 for value in result["pv"])
        assert len(result["pv"]) == to_index - oldest_day_start + 1

    def test_the_floor_does_not_move_within_a_day(self) -> None:
        """Trimming at 00:01, mid-day or 23:55 of the same day keeps the same
        data — the floor only ever moves on a whole-day boundary."""
        cache, _calls, anchor = self._setup()
        cache.trim(reference=anchor + timedelta(minutes=1))
        floor = cache._list_offset["pv"]
        length = len(cache._values["pv"])
        for hour_minutes in (14 * 60 + 37, 23 * 60 + 55):
            cache.trim(reference=anchor + timedelta(minutes=hour_minutes))
            assert cache._list_offset["pv"] == floor
            assert len(cache._values["pv"]) == length

    def test_the_floor_advances_by_exactly_one_day_per_day(self) -> None:
        cache, _calls, anchor = self._setup()
        cache.trim(reference=anchor + timedelta(minutes=1))
        floor = cache._list_offset["pv"]
        cache.trim(reference=anchor + timedelta(days=1, minutes=1))
        assert cache._list_offset["pv"] == floor + cache_mod.SLOTS_PER_DAY
        assert len(cache._shadow["pv"]) == len(cache._values["pv"])


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


class TestEnergyIntegralTotals:
    """Given the two energy-integral running totals (ADR-005 §5/§6,
    TASK-0012) — the one restart-persisted cache in this module
    (ADR-007 §1) — the accessors behave as a plain in-memory pair of
    scalars per `EnergyKind`, independent of the index-addressable
    time-series machinery covered by every other test class above."""

    def test_fresh_instance_defaults(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])

        assert cache.energy_total("pv") == 0.0
        assert cache.energy_total("fc") == 0.0
        assert cache.last_energy_sample("pv") is None
        assert cache.last_energy_sample("fc") is None
        assert cache.last_reset_date() is None

    def test_set_and_get_energy_total_per_kind(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])

        cache.set_energy_total("pv", 42.5)
        assert cache.energy_total("pv") == 42.5
        assert cache.energy_total("fc") == 0.0  # independent of "pv"

    def test_set_and_get_last_energy_sample_per_kind(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        sample = (datetime(2026, 1, 1, tzinfo=UTC), 600.0)

        cache.set_last_energy_sample("fc", sample)
        assert cache.last_energy_sample("fc") == sample
        assert cache.last_energy_sample("pv") is None  # independent of "fc"

    def test_reset_zeroes_both_totals_and_clears_both_samples(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        cache.set_energy_total("pv", 10.0)
        cache.set_energy_total("fc", 20.0)
        cache.set_last_energy_sample("pv", (datetime(2026, 1, 1, tzinfo=UTC), 100.0))
        cache.set_last_energy_sample("fc", (datetime(2026, 1, 1, tzinfo=UTC), 200.0))

        cache.reset_energy_totals(datetime(2026, 1, 2, tzinfo=UTC).date())

        assert cache.energy_total("pv") == 0.0
        assert cache.energy_total("fc") == 0.0
        assert cache.last_energy_sample("pv") is None
        assert cache.last_energy_sample("fc") is None
        assert cache.last_reset_date() == datetime(2026, 1, 2, tzinfo=UTC).date()

    def test_restore_sets_totals_and_reset_date_but_not_samples(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        # Simulate a sample already present before restore runs — a
        # brand-new `Cache` never has one, but this proves restore
        # actively leaves whatever's there untouched rather than merely
        # defaulting to `None` by omission.
        cache.set_last_energy_sample("pv", (datetime(2026, 1, 1, tzinfo=UTC), 999.0))

        cache.restore_energy_state(10.0, 20.0, datetime(2026, 1, 3, tzinfo=UTC).date())

        assert cache.energy_total("pv") == 10.0
        assert cache.energy_total("fc") == 20.0
        assert cache.last_reset_date() == datetime(2026, 1, 3, tzinfo=UTC).date()
        # Deliberately NOT restored/cleared (ADR-005 §5/§6): the next
        # accumulation after a restart starts from `previous=None`.
        assert cache.last_energy_sample("pv") == (datetime(2026, 1, 1, tzinfo=UTC), 999.0)

    def test_kinds_are_independent_across_a_full_reset_restore_cycle(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        cache.restore_energy_state(1.0, 2.0, datetime(2026, 1, 1, tzinfo=UTC).date())
        cache.set_last_energy_sample("pv", (datetime(2026, 1, 1, tzinfo=UTC), 50.0))
        cache.set_last_energy_sample("fc", (datetime(2026, 1, 1, tzinfo=UTC), 60.0))

        cache.reset_energy_totals(datetime(2026, 1, 2, tzinfo=UTC).date())

        assert cache.energy_total("pv") == 0.0
        assert cache.energy_total("fc") == 0.0
        assert cache.last_energy_sample("pv") is None
        assert cache.last_energy_sample("fc") is None


# -- fitted-model cache (ADR-007 §1, ADR-007a §5-Amendment, TASK-0021) -----


@dataclass(frozen=True)
class _StubModel(base_mod.FittedModel):  # type: ignore[name-defined,misc]
    """A hand-written stand-in inheriting the real
    `regression.base.FittedModel` base class (ADR-000 §6, same pattern
    `tests/test_forecast_adjust.py`'s own `_StubModel` already
    establishes) — `cache.py`'s model-cache methods never inspect a
    model's contents, only store/return the object, so a minimal
    concrete subclass with a `tag` field (to tell instances apart in
    assertions) is enough; `predict_unclamped` itself is never called
    here."""

    tag: str

    def predict_unclamped(
        self, fc: NDArray[np.float64]
    ) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
        return fc, np.ones_like(fc)


class TestFittedModelCacheRoundTrip:
    """Given a model is `set_model`-ed for a given `(kind, string_index)`,
    when `get_model` is called with the same key, then the exact same
    object comes back — and every other key stays independently `None`
    (ADR-007 §1, ADR-007a §5-Amendment)."""

    def test_never_set_key_returns_none(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        assert cache.get_model("shading", 0) is None

    def test_set_then_get_returns_the_same_object(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        model = _StubModel(tag="string-0-shading")

        cache.set_model("shading", 0, model)

        assert cache.get_model("shading", 0) is model

    def test_kind_and_string_index_are_independent_keys(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        shading_0 = _StubModel(tag="shading-0")
        temperature_0 = _StubModel(tag="temperature-0")
        shading_1 = _StubModel(tag="shading-1")

        cache.set_model("shading", 0, shading_0)
        cache.set_model("temperature", 0, temperature_0)
        cache.set_model("shading", 1, shading_1)

        assert cache.get_model("shading", 0) is shading_0
        assert cache.get_model("temperature", 0) is temperature_0
        assert cache.get_model("shading", 1) is shading_1
        assert cache.get_model("temperature", 1) is None  # never set


class TestFittedModelCacheInvalidation:
    """Given one or more models are `set_model`-ed, when
    `invalidate_models` is called, then `get_model` returns `None` for
    every key — mirroring `invalidate()`'s "reset, force a fresh write
    before serving again" contract for the time-series stores — but the
    stale object itself is still physically retained internally, not
    discarded, exactly like an invalidated time-series range still
    holds its now-stale entries rather than forgetting them outright."""

    def test_invalidate_clears_every_key(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        cache.set_model("shading", 0, _StubModel(tag="shading-0"))
        cache.set_model("temperature", 0, _StubModel(tag="temperature-0"))
        cache.set_model("shading", 1, _StubModel(tag="shading-1"))

        cache.invalidate_models()

        assert cache.get_model("shading", 0) is None
        assert cache.get_model("temperature", 0) is None
        assert cache.get_model("shading", 1) is None

    def test_invalidate_retains_the_stale_object_internally(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        stale = _StubModel(tag="shading-0")
        cache.set_model("shading", 0, stale)

        cache.invalidate_models()

        assert cache.get_model("shading", 0) is None  # not served
        assert cache._models[("shading", 0)] is stale  # but not discarded

    def test_set_model_after_invalidate_makes_it_valid_again(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        cache.set_model("shading", 0, _StubModel(tag="old"))
        cache.invalidate_models()
        assert cache.get_model("shading", 0) is None

        fresh = _StubModel(tag="new")
        cache.set_model("shading", 0, fresh)

        assert cache.get_model("shading", 0) is fresh

    def test_invalidate_on_an_empty_cache_is_a_no_op(self) -> None:
        cache = cache_mod.Cache(window_days=1, fetch_fn=lambda *a: [])
        cache.invalidate_models()  # must not raise
        assert cache.get_model("shading", 0) is None


# -- TASK-0037-patch-5: a `None` in the freshest slots is not yet an answer ----


class _RecorderSim:
    """A fake recorder plus an injectable clock (ADR-007a §4 Amendment
    2026-10-07). Slot `i` becomes readable `COMPILE_DELAY` after it ended,
    exactly like the recorder's own `second=10` statistics compile;
    before that `fetch_fn` answers `None` for it. `gaps` lists slots that
    never become readable, `strings` slots that answer a `str` outcome."""

    COMPILE_DELAY = timedelta(seconds=10)

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.gaps: set[int] = set()
        self.strings: dict[int, str] = {}
        self.calls: list[tuple[str, int, int]] = []

    def clock(self) -> datetime:
        return self.now

    def fetch_fn(self, sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
        first = cache_mod.Cache.index_for(start)
        count = round((end - start) / cache_mod.SLOT_DURATION)
        self.calls.append((sensor_id, first, first + count - 1))
        out: list[float | None | str] = []
        for index in range(first, first + count):
            readable_at = cache_mod.Cache.timestamp_for(index + 1) + self.COMPILE_DELAY
            if index in self.strings:
                out.append(self.strings[index])
            elif index in self.gaps or self.now < readable_at:
                out.append(None)
            else:
                out.append(float(index))
        return out

    def cache(self, window_days: int = 1) -> Any:
        return cache_mod.Cache(window_days=window_days, fetch_fn=self.fetch_fn, clock=self.clock)


def _slot_start(index: int) -> datetime:
    start: datetime = cache_mod.Cache.timestamp_for(index)
    return start


_BASE = datetime(2026, 10, 7, 13, 50, tzinfo=UTC)  # an exact slot boundary


class TestUnsettledTailIsNotFrozen:
    """Given a trailing `None` for a slot that ended less than
    `SETTLE_GRACE` ago, or has not ended, then it is not validated and the
    next read re-fetches it (ADR-007a §4 Amendment 2026-10-07)."""

    def test_settle_grace_is_ten_minutes(self) -> None:
        assert cache_mod.SETTLE_GRACE == timedelta(minutes=10)

    def test_just_ended_slot_is_refetched_once_the_recorder_has_it(self) -> None:
        index = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + cache_mod.SLOT_DURATION + timedelta(seconds=3))
        cache = sim.cache()

        first = cache.get_time_range(["pv"], _slot_start(index), _slot_start(index), "raw")
        assert first == {"pv": [None]}

        sim.now += timedelta(seconds=30)  # the recorder has compiled it by now
        second = cache.get_time_range(["pv"], _slot_start(index), _slot_start(index), "raw")
        assert second == {"pv": [float(index)]}

    def test_a_slot_older_than_settle_grace_is_a_final_none(self) -> None:
        index = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + cache_mod.SLOT_DURATION + timedelta(minutes=11))
        sim.gaps.add(index)
        cache = sim.cache()

        cache.get_time_range(["pv"], _slot_start(index), _slot_start(index), "raw")
        cache.get_time_range(["pv"], _slot_start(index), _slot_start(index), "raw")

        # One whole-window fetch; the second read is served from `validated`.
        assert len(sim.calls) == 1
        validated = cache.validated_range("pv")
        assert validated is not None and validated[1] == index

    def test_in_progress_slot_is_never_validated_and_only_the_tail_is_refetched(self) -> None:
        in_progress = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + timedelta(minutes=2))
        cache = sim.cache()

        cache.get_time_range(["pv"], _slot_start(in_progress - 3), _slot_start(in_progress), "raw")
        assert len(sim.calls) == 1
        validated = cache.validated_range("pv")
        assert validated is not None and validated[1] == in_progress - 1

        cache.get_time_range(["pv"], _slot_start(in_progress - 3), _slot_start(in_progress), "raw")
        assert len(sim.calls) == 2
        assert sim.calls[1] == ("pv", in_progress, in_progress)  # the tail only
        validated = cache.validated_range("pv")
        assert validated is not None and validated[1] == in_progress - 1

    def test_interior_gap_is_validated_immediately(self) -> None:
        index = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + 2 * cache_mod.SLOT_DURATION + timedelta(seconds=30))
        sim.gaps.add(index)  # a hole, followed by a real value at index + 1
        cache = sim.cache()

        out = cache.get_time_range(["pv"], _slot_start(index), _slot_start(index + 1), "raw")
        assert out == {"pv": [None, float(index + 1)]}
        validated = cache.validated_range("pv")
        assert validated is not None and validated[1] == index + 1

        cache.get_time_range(["pv"], _slot_start(index), _slot_start(index + 1), "raw")
        assert len(sim.calls) == 1

    def test_str_outcome_is_validated_immediately_however_recent(self) -> None:
        index = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + cache_mod.SLOT_DURATION + timedelta(seconds=1))
        sim.strings[index] = "unavailable"
        cache = sim.cache()

        out = cache.get_time_range(["pv"], _slot_start(index), _slot_start(index), "raw")
        assert out == {"pv": ["unavailable"]}
        validated = cache.validated_range("pv")
        assert validated is not None and validated[1] == index
        cache.get_time_range(["pv"], _slot_start(index), _slot_start(index), "raw")
        assert len(sim.calls) == 1

    def test_fully_settled_fetch_validates_exactly_as_before(self) -> None:
        index = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + timedelta(hours=1))
        cache = sim.cache()

        cache.get_time_range(["pv"], _slot_start(index - 2), _slot_start(index + 1), "raw")
        cache.get_time_range(["pv"], _slot_start(index - 2), _slot_start(index + 1), "raw")
        assert len(sim.calls) == 1
        validated = cache.validated_range("pv")
        assert validated is not None and validated[1] == index + 1

    def test_first_fetch_with_unsettled_tail_ends_validated_at_last_settled_slot(self) -> None:
        in_progress = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + timedelta(minutes=4))
        cache = sim.cache()

        cache.get_time_range(["pv"], _slot_start(in_progress), _slot_start(in_progress), "raw")
        validated = cache.validated_range("pv")
        assert validated is not None
        assert validated[1] == in_progress - 1
        assert validated[0] == in_progress - 287  # the whole window, as before

    def test_degenerate_empty_validated_range_is_handled_everywhere(self) -> None:
        index = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + timedelta(minutes=2))
        cache = sim.cache()

        # Every slot of this first fetch is unsettled: validated is empty.
        cache._fetch_and_store("pv", index, index + 1)
        assert cache.validated_range("pv") == (index, index - 1)

        # The next read fetches from the start of that empty range.
        cache.get_time_range(["pv"], _slot_start(index), _slot_start(index), "raw")
        assert sim.calls[-1] == ("pv", index, index)

        # `invalidate()` and `trim()` accept the empty range.
        cache._validated["pv"] = (index, index - 1)
        cache.invalidate("pv", index, index)
        assert cache.validated_range("pv") is None
        cache._validated["pv"] = (index, index - 1)
        cache.trim(sim.now)
        assert cache.validated_range("pv") is None

    def test_head_backfill_ending_in_a_recent_none_is_not_trimmed(self) -> None:
        """A head fetch ends right before an already-validated range, so a
        trailing `None` in it is interior to the combined range."""
        index = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + timedelta(hours=1))
        cache = sim.cache()
        cache.get_time_range(["pv"], _slot_start(index), _slot_start(index + 1), "raw")
        validated = cache.validated_range("pv")
        assert validated is not None
        from_index = validated[0]

        sim.gaps.add(from_index - 1)
        sim.now = _slot_start(from_index) + timedelta(seconds=5)  # that slot "just ended"
        cache.get_time_range(["pv"], _slot_start(from_index - 2), _slot_start(index + 1), "raw")
        validated = cache.validated_range("pv")
        assert validated is not None
        assert validated == (from_index - 2, index + 1)


class TestTickPhaseReplay:
    """Replay of the 2026-10-07 incident (`TASK-0037-patch-5`): a tick every
    5 minutes whose phase is wherever Home Assistant happened to start,
    reading the cache the way the coordinator does — `get_pinned_slot_pool`
    for the diagnosed slot's offsets -3..+3 (auto-tracking) and, with
    intraday correction on, `get_time_range` through `now`
    (`_intraday_energy_window`). A phase within the recorder's compile
    delay of a slot boundary used to freeze every slot at `None`."""

    WINDOW_DAYS = 2
    FIRST_TICK = datetime(2026, 10, 7, 6, 30, tzinfo=UTC)
    LAST_TICK = datetime(2026, 10, 7, 13, 55, tzinfo=UTC)

    def _run(self, phase_seconds: int, *, pool: bool, intraday: bool) -> tuple[Any, _RecorderSim]:
        phase = timedelta(seconds=phase_seconds)
        sim = _RecorderSim(self.FIRST_TICK + phase)
        cache = sim.cache(self.WINDOW_DAYS)
        tick = self.FIRST_TICK + phase
        while tick <= self.LAST_TICK + phase:
            sim.now = tick
            now_index = cache_mod.Cache.index_for(tick)
            if pool:
                diagnosed = now_index - 1
                local_midnight = datetime(tick.year, tick.month, tick.day, tzinfo=UTC)
                day_start = cache_mod.Cache.index_for(local_midnight)
                for offset in range(-3, 4):
                    slot_of_day = diagnosed + offset - day_start
                    cache.get_pinned_slot_pool(["pv"], slot_of_day, "raw", reference=tick)
            if intraday:
                cache.get_time_range(["pv"], tick - 24 * cache_mod.SLOT_DURATION, tick, "raw")
            tick += cache_mod.SLOT_DURATION
        # The recorder has long compiled everything by the time anyone looks.
        sim.now = self.LAST_TICK + phase + timedelta(minutes=1)
        return cache, sim

    @pytest.mark.parametrize("phase_seconds", [3, 40])
    @pytest.mark.parametrize(
        ("pool", "intraday"), [(True, False), (False, True), (True, True)], ids=lambda v: str(v)
    )
    def test_every_elapsed_slot_reads_its_real_value(
        self, phase_seconds: int, pool: bool, intraday: bool
    ) -> None:
        cache, sim = self._run(phase_seconds, pool=pool, intraday=intraday)
        first = cache_mod.Cache.index_for(self.FIRST_TICK)
        last_complete = cache_mod.Cache.index_for(sim.now) - 1
        out = cache.get_time_range(["pv"], _slot_start(first), _slot_start(last_complete), "raw")
        assert out == {"pv": [float(i) for i in range(first, last_complete + 1)]}

    def test_slot_in_progress_at_one_tick_holds_its_value_at_the_next(self) -> None:
        in_progress = cache_mod.Cache.index_for(_BASE)
        sim = _RecorderSim(_BASE + timedelta(minutes=2))
        cache = sim.cache()
        window = 24 * cache_mod.SLOT_DURATION

        cache.get_time_range(["pv"], sim.now - window, sim.now, "raw")  # tick N
        sim.now = _BASE + timedelta(minutes=7)
        out = cache.get_time_range(["pv"], sim.now - window, sim.now, "raw")  # tick N+1

        values = out["pv"]
        # `values[-2]` is the slot that was in progress one tick earlier.
        assert values[-2] == float(in_progress)


# -- TASK-0042: a threading contract for loop-thread readers ------------------


class _GatedList(list[float | None | str]):
    """A real `list` that pauses its mutator right *after* a slice
    assignment or slice deletion — i.e. between `Cache._write`'s /
    `Cache.trim`'s list mutation and the `_list_offset` update that must
    follow it. The only instrumentation: no behavior of the list changes."""

    hook: Callable[[], None] | None = None

    def _fire(self) -> None:
        hook, self.hook = self.hook, None
        if hook is not None:
            hook()

    def __setitem__(self, key: Any, value: Any) -> None:
        super().__setitem__(key, value)
        if isinstance(key, slice):
            self._fire()

    def __delitem__(self, key: Any) -> None:
        super().__delitem__(key)
        if isinstance(key, slice):
            self._fire()


def _pause_writer_mid_mutation(
    cache: Any, sensor_id: str, mutate: Callable[[], None]
) -> tuple[threading.Thread, threading.Event]:
    """Start `mutate` on thread A and return once A sits between the list
    mutation and the offset update (list changed, offset not yet)."""
    entered = threading.Event()
    gate = threading.Event()

    def _hook() -> None:
        entered.set()
        gate.wait(5)

    gated = _GatedList(cache._values[sensor_id])
    gated.hook = _hook
    cache._values[sensor_id] = gated
    writer = threading.Thread(target=mutate, daemon=True)
    writer.start()
    assert entered.wait(5), "the writer never reached the mutation"
    return writer, gate


def _call_on_thread(fn: Callable[[], Any]) -> tuple[threading.Thread, threading.Event, list[Any]]:
    box: list[Any] = []
    done = threading.Event()

    def _run_it() -> None:
        box.append(fn())
        done.set()

    thread = threading.Thread(target=_run_it, daemon=True)
    thread.start()
    return thread, done, box


def _never_fetch(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
    raise AssertionError("a pushed series must never be fetched")


class TestThreadingContract:
    """ADR-007a §4 Amendment 2026-10-09 (`TASK-0042`): `Cache` guards its
    in-memory state with its own `threading.RLock`, never held across
    `fetch_fn`, so a loop-thread reader (`sensor.py`) can never pair a
    list with the wrong `_list_offset` while an executor job mutates it."""

    def test_reader_never_sees_a_prepend_halfway_through(self) -> None:
        """Reproducer 1: `_write` extending the list at the front (a
        backfill of already-elapsed slots after the forecast was pushed)
        updates the list first and `_list_offset` second."""
        cache = cache_mod.Cache(window_days=1, fetch_fn=_never_fetch)
        cache.push("s", {100: 1.0, 101: 2.0}, 0)
        writer, gate = _pause_writer_mid_mutation(cache, "s", lambda: cache.push("s", {98: 9.0}, 0))
        reader, done, box = _call_on_thread(
            lambda: cache.get_time_range(
                ["s"], cache_mod.Cache.timestamp_for(100), cache_mod.Cache.timestamp_for(100), "raw"
            )
        )
        done.wait(0.3)  # unlocked: returns at once, with the wrong slot's value
        gate.set()
        writer.join(5)
        reader.join(5)

        assert box == [{"s": [1.0]}]  # slot 100's own value, never slot 98's `None`

    def test_reader_never_sees_a_trim_halfway_through(self) -> None:
        """Reproducer 2: `trim` deletes the head of the list first and
        advances `_list_offset` second (nothing in production calls
        `trim` yet — ADR-007a §1 says midnight — but it must be safe when
        something does)."""
        cache = cache_mod.Cache(window_days=1, fetch_fn=_never_fetch)
        boundary = 3 * cache_mod.SLOTS_PER_DAY  # a whole-day boundary (the floor's granularity)
        cache.push(
            "s",
            {
                boundary - 2: 1.0,
                boundary - 1: 2.0,
                boundary: 3.0,
                boundary + 1: 4.0,
                boundary + 2: 5.0,
            },
            0,
        )
        # floor = start of (reference's day - window_days) = `boundary`: drops
        # the two slots before it.
        reference = cache_mod.Cache.timestamp_for(boundary + cache_mod.SLOTS_PER_DAY)
        writer, gate = _pause_writer_mid_mutation(cache, "s", lambda: cache.trim(reference))
        reader, done, box = _call_on_thread(
            lambda: cache.get_time_range(
                ["s"],
                cache_mod.Cache.timestamp_for(boundary),
                cache_mod.Cache.timestamp_for(boundary),
                "raw",
            )
        )
        done.wait(0.3)
        gate.set()
        writer.join(5)
        reader.join(5)

        assert box == [{"s": [3.0]}]  # the boundary slot's own value, never slot boundary+2's

    def test_a_single_slot_read_is_guarded_on_its_own(self) -> None:
        """`_read` is the single-slot primitive every range reader builds
        on; it holds the lock itself, not only through its callers."""
        cache = cache_mod.Cache(window_days=1, fetch_fn=_never_fetch)
        cache.push("s", {100: 1.0, 101: 2.0}, 0)
        writer, gate = _pause_writer_mid_mutation(cache, "s", lambda: cache.push("s", {98: 9.0}, 0))
        reader, done, box = _call_on_thread(lambda: cache._read("s", 100))
        done.wait(0.3)
        gate.set()
        writer.join(5)
        reader.join(5)

        assert box == [1.0]

    def test_a_reader_is_not_blocked_while_another_thread_is_inside_fetch_fn(self) -> None:
        inside = threading.Event()
        release = threading.Event()

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            count = round((end - start) / cache_mod.SLOT_DURATION)
            if sensor_id == "slow":
                inside.set()
                release.wait(5)
            first = cache_mod.Cache.index_for(start)
            return [float(first + i) for i in range(count)]

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        slot = cache_mod.Cache.timestamp_for(500)
        cache.push("pushed", {500: 7.0}, 0)
        cache.get_time_range(["warm"], slot, slot, "raw")  # validated before anything races

        fetcher, _done, _box = _call_on_thread(lambda: cache.get_time_range(["slow"], slot, slot))
        assert inside.wait(5)
        reader, done, box = _call_on_thread(
            lambda: cache.get_time_range(["pushed", "warm"], slot, slot, "raw")
        )
        finished = done.wait(2)  # the lock must not be held across `fetch_fn`
        release.set()
        fetcher.join(5)
        reader.join(5)

        assert finished
        assert box == [{"pushed": [7.0], "warm": [500.0]}]

    def test_a_stale_overlapping_fetch_never_overwrites_a_newer_one(self) -> None:
        """Thread A is paused inside `fetch_fn` (its data already read from
        the 'recorder'); thread B fetches an overlapping range to completion
        with newer data. When A resumes, the cache keeps B's values and
        `validated` is the union — it never shrinks."""
        lock = threading.Lock()
        calls = 0
        a_inside = threading.Event()
        release_a = threading.Event()

        def fetch_fn(sensor_id: str, start: datetime, end: datetime) -> list[float | None | str]:
            nonlocal calls
            with lock:
                calls += 1
                version = calls
            first = cache_mod.Cache.index_for(start)
            count = round((end - start) / cache_mod.SLOT_DURATION)
            data: list[float | None | str] = [version * 1000.0 + first + i for i in range(count)]
            if version == 1:  # thread A: holds already-read, soon stale data
                a_inside.set()
                release_a.wait(5)
            return data

        cache = cache_mod.Cache(window_days=1, fetch_fn=fetch_fn)
        ts = cache_mod.Cache.timestamp_for
        thread_a, _done_a, _box_a = _call_on_thread(
            lambda: cache.get_time_range(["p"], ts(100), ts(110), "raw")
        )
        assert a_inside.wait(5)
        cache.get_time_range(["p"], ts(105), ts(120), "raw")  # B, on this thread, completes
        b_validated = cache.validated_range("p")
        release_a.set()
        thread_a.join(5)

        assert b_validated is not None
        validated = cache.validated_range("p")
        assert validated is not None
        assert validated[0] <= b_validated[0] and validated[1] == b_validated[1]  # a union
        out = cache.get_time_range(["p"], ts(105), ts(120), "raw")
        assert out == {"p": [2000.0 + i for i in range(105, 121)]}  # B's newer data won

    def test_cache_module_still_imports_nothing_from_home_assistant_or_the_coordinator(
        self,
    ) -> None:
        path = Path(__file__).resolve().parents[1] / "custom_components/shady/cache.py"
        imported: list[str] = []
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported.append(("." * node.level) + (node.module or ""))
        assert not [name for name in imported if name.startswith("homeassistant")]
        assert ".coordinator" not in imported
