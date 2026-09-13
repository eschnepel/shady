"""Zero-mocking tests for `cache.py`'s storage core (ADR-007a §1-§5, ADR-000 §6),
plus the relocated fitted-model cache (ADR-007 §1, ADR-007a §5-Amendment,
TASK-0021).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import numpy as np
from numpy.typing import NDArray

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


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
