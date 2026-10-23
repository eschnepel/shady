"""Tests for wiring `Cache.trim()` into the recalibration (TASK-0043,
ADR-007a §1 Amendment 2026-10-10).

Before this task nothing in production called `Cache.trim()`, so every
series list, offset map and shadow array only ever grew. These tests pin
the contract: exactly one trim per recalibration (button and midnight go
through the same `_refit_sync`), never from the slot job or a baseline
update, and -- the pitfall the task records -- that nothing
`get_regression_pools` / `get_pinned_slot_pool` reads is discarded.

`coordinator.py` is HA-facing, so this file reuses `test_coordinator.py`'s
hand-written `homeassistant` stub harness wholesale, the same way
`test_local_timezone.py` does. `Cache` itself is the real object
throughout; the only wrappers are recording *spies* that delegate to the
real method.
"""

from __future__ import annotations

import ast
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from tests import test_coordinator as tc
from tests.support import _SHADY_DIR, _run
from tests.support_ha import FakeHomeAssistant

tc._restore_modules()

ShadyCoordinator = tc.ShadyCoordinator
Cache = tc.Cache

SLOTS_PER_DAY = 288
_FIRST_DATA_DAY = datetime(2026, 6, 1, tzinfo=UTC)
_LAST_DATA_DAY = datetime(2026, 7, 15, tzinfo=UTC)
# A recalibration exactly as ADR-002 §1 schedules it: 00:01.
_RECALIBRATION = datetime(2026, 6, 20, 0, 1, tzinfo=UTC)


def _make_setup(
    window_days: int, time_zone: str = "UTC", smoothing_radius: int = 0
) -> tuple[Any, FakeHomeAssistant, dict[str, int]]:
    """A single-string coordinator whose recorder holds data for every day
    from `_FIRST_DATA_DAY` to `_LAST_DATA_DAY`, so any head fetch the cache
    makes *can* be served -- a test then proves from the fetch counter that
    none was needed, rather than relying on a fetch failing.

    The returned dict counts `fetch_fn` calls reaching the recorder side,
    keyed by sensor id (a spy that delegates to the real function).
    """
    hass = FakeHomeAssistant()
    hass.config.time_zone = time_zone
    hass.states.set(
        tc._BASELINE_ENTITY,
        {"wh_period": tc._synthetic_wh_period(_FIRST_DATA_DAY, _LAST_DATA_DAY)},
    )
    hass.states.set(tc._ACTUAL_YIELD_ENTITY, {})
    tc._seed_actual_yield_statistics(hass, _FIRST_DATA_DAY, _LAST_DATA_DAY)
    coordinator = ShadyCoordinator(
        hass, tc._make_entry(window_days=window_days, smoothing_radius=smoothing_radius)
    )
    coordinator._now = lambda: _RECALIBRATION

    fetches: dict[str, int] = {}
    real_fetch = coordinator.cache._fetch_fn

    def _counting_fetch(sensor_id: str, start: datetime, end: datetime) -> Any:
        fetches[sensor_id] = fetches.get(sensor_id, 0) + 1
        return real_fetch(sensor_id, start, end)

    coordinator.cache._fetch_fn = _counting_fetch
    return coordinator, hass, fetches


def _spy_on_trim(coordinator: Any) -> list[datetime | None]:
    """Record every `Cache.trim` call's `reference` (the real trim still
    runs); the `smoothing_radius` of each call is recorded alongside on
    `coordinator._trim_radii`."""
    references: list[datetime | None] = []
    coordinator._trim_radii = []
    real_trim = coordinator.cache.trim

    def _spy(reference: datetime | None = None, smoothing_radius: int = 0) -> None:
        references.append(reference)
        coordinator._trim_radii.append(smoothing_radius)
        real_trim(reference, smoothing_radius)

    coordinator.cache.trim = _spy
    return references


def _training_sensors(coordinator: Any) -> list[str]:
    return [tc._BASELINE_ENTITY, tc._ACTUAL_YIELD_ENTITY]


# -- AC1: exactly one trim per recalibration, from the recalibration only ------


class TestTrimRunsOncePerRecalibration:
    """Given a recalibration (button or midnight) has run, then
    `cache.trim(...)` was called exactly once for it."""

    def test_the_button_path_trims_exactly_once(self) -> None:
        coordinator, _hass, _fetches = _make_setup(window_days=3)
        references = _spy_on_trim(coordinator)

        _run(coordinator.async_refit(_RECALIBRATION))

        assert len(references) == 1

    def test_the_midnight_path_trims_exactly_once(self) -> None:
        coordinator, hass, _fetches = _make_setup(window_days=3)
        references = _spy_on_trim(coordinator)

        async def _drive_midnight() -> None:
            coordinator._handle_midnight(_RECALIBRATION)
            await hass.drain()

        _run(_drive_midnight())

        assert len(references) == 1

    def test_two_recalibrations_trim_twice(self) -> None:
        coordinator, _hass, _fetches = _make_setup(window_days=3)
        references = _spy_on_trim(coordinator)

        _run(coordinator.async_refit(_RECALIBRATION))
        _run(coordinator.async_refit(_RECALIBRATION + timedelta(days=1)))

        assert len(references) == 2

    def test_the_slot_job_and_a_baseline_update_never_trim(self) -> None:
        """ADR-006 §1a (5-minute tick) and ADR-002 §2 (baseline update)
        must not trim -- only the recalibration does."""
        coordinator, hass, _fetches = _make_setup(window_days=3)
        _run(coordinator.async_refit(_RECALIBRATION))
        references = _spy_on_trim(coordinator)  # armed only after the refit

        coordinator._intraday_tick_sync(_RECALIBRATION + timedelta(minutes=5))
        coordinator._diagnostics_tick_sync(_RECALIBRATION + timedelta(minutes=5))

        async def _drive_baseline_update() -> None:
            hass.states.set(
                tc._BASELINE_ENTITY,
                {"wh_period": tc._synthetic_wh_period(_FIRST_DATA_DAY, _LAST_DATA_DAY)},
            )
            await hass.drain()

        _run(_drive_baseline_update())

        assert references == []

    def test_coordinator_has_exactly_one_trim_call_site(self) -> None:
        tree = ast.parse((_SHADY_DIR / "coordinator.py").read_text())
        trim_calls = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "trim"
        ]
        assert len(trim_calls) == 1


# -- AC5: runs inside the existing recalibration executor job -------------------


class TestTrimRunsInsideTheRecalibrationCacheJob:
    """Given the trim runs, then it runs as part of the existing
    recalibration job (under `async_run_cache_job`), not on the event
    loop."""

    def test_trim_runs_inside_refit_sync_which_is_dispatched_via_the_cache_job(
        self,
    ) -> None:
        coordinator, _hass, _fetches = _make_setup(window_days=3)
        dispatched: list[str] = []
        real_job = coordinator.async_run_cache_job

        async def _recording_job(fn: Any, *args: Any) -> Any:
            dispatched.append(fn.__name__)
            return await real_job(fn, *args)

        coordinator.async_run_cache_job = _recording_job

        inside_refit = {"active": False}
        real_refit = coordinator._refit_sync

        def _flagging_refit(now: datetime) -> None:
            inside_refit["active"] = True
            try:
                real_refit(now)
            finally:
                inside_refit["active"] = False

        coordinator._refit_sync = _flagging_refit

        trimmed_inside: list[bool] = []
        real_trim = coordinator.cache.trim

        def _spy(reference: datetime | None = None, smoothing_radius: int = 0) -> None:
            trimmed_inside.append(inside_refit["active"])
            real_trim(reference, smoothing_radius)

        coordinator.cache.trim = _spy

        _run(coordinator.async_refit(_RECALIBRATION))

        assert trimmed_inside == [True]
        assert dispatched.count("_flagging_refit") == 1


class TestAFailingTrimDoesNotBreakTheRecalibration:
    """The module's convention (see `_refit_sync`'s per-string guards): a
    failure in one step is logged and does not abort the rest of the
    recalibration -- here the energy persist `async_refit` awaits after."""

    def test_a_raising_trim_is_contained(self) -> None:
        coordinator, _hass, _fetches = _make_setup(window_days=3)

        def _boom(reference: datetime | None = None, smoothing_radius: int = 0) -> None:
            raise RuntimeError("trim exploded")

        coordinator.cache.trim = _boom

        _run(coordinator.async_refit(_RECALIBRATION))  # must not raise

        assert coordinator._last_fit_at == _RECALIBRATION
        assert coordinator.cache.get_model("shading", 0) is not None


# -- AC2: the training pool is untouched by the trim -----------------------------


def _pool_start_index(now: datetime, window_days: int, time_zone: str = "UTC") -> int:
    """Absolute index of slot 0 of the oldest training day, derived from
    ADR-008 §2 Amendment 2026-10-10 ("the most recent `window_days` complete
    *local* days, ending at local midnight today", today taken from the
    *instant* `now`) with `zoneinfo` alone -- no reference to the code under
    test."""
    today = now.astimezone(ZoneInfo(time_zone)).date() - timedelta(days=window_days)
    oldest_day_start = datetime(today.year, today.month, today.day, tzinfo=ZoneInfo(time_zone))
    return int(Cache.index_for(oldest_day_start))


class TestTrainingPoolSurvivesTheTrim:
    """Given a cache with `window_days` full days of history, when the
    recalibration trims, then `get_regression_pools` returns exactly the
    same arrays before and after, including slot 0 of the oldest day -- and
    needs no new recorder query to do so."""

    def _assert_pool_intact(self, now: datetime, time_zone: str, radius: int = 0) -> None:
        window_days = 3
        coordinator, _hass, fetches = _make_setup(window_days, time_zone, radius)
        cache = coordinator.cache
        sensors = _training_sensors(coordinator)

        # An untrimmed twin: same data, trim neutralised -- the reference
        # the trimmed cache's pools must equal cell for cell.
        control, _control_hass, _control_fetches = _make_setup(window_days, time_zone, radius)
        control.cache.trim = lambda reference=None, smoothing_radius=0: None

        _run(coordinator.async_refit(now))
        _run(control.async_refit(now))

        window_start = _pool_start_index(now, window_days, time_zone)
        for sensor_id in sensors:
            validated = cache.validated_range(sensor_id)
            assert validated is not None
            # The lower bound of what the cache vouches for must still
            # reach the oldest slot the pool reads: slot 0 of the oldest
            # training day less the smoothing neighbors...
            assert validated[0] <= window_start - radius, sensor_id
            # ...and so must the stored list itself (offset = index of
            # list[0]); a naive `reference=now` leaves it at window_start+1.
            assert cache._list_offset[sensor_id] <= window_start - radius, sensor_id

        fetches.clear()
        trimmed = cache.get_regression_pools(sensors, radius, reference=now)
        untrimmed = control.cache.get_regression_pools(sensors, radius, reference=now)

        for sensor_id in sensors:
            assert np.array_equal(trimmed[sensor_id], untrimmed[sensor_id], equal_nan=True)
            assert not np.isnan(trimmed[sensor_id]).any(), sensor_id  # no hole at all
        # Nothing had to be re-read from the recorder to rebuild the pool.
        assert fetches == {}

    def test_utc_recalibration_at_00_01(self) -> None:
        self._assert_pool_intact(_RECALIBRATION, "UTC")

    def test_local_timezone_midnight_trigger(self) -> None:
        """Home Assistant hands `async_track_time_change` callbacks a `now`
        already converted to local time (see `_tomorrow_end`'s note); the
        trim and the training pool must both be anchored on the same local
        day."""
        berlin_midnight = datetime(2026, 6, 20, 0, 1, tzinfo=ZoneInfo("Europe/Berlin"))
        self._assert_pool_intact(berlin_midnight, "Europe/Berlin")

    def test_a_local_evening_whose_utc_instant_is_already_the_next_day(self) -> None:
        """20:00 in New York is 00:00 the *next* day in UTC. "Today" is the
        local 20th (derived from the instant), so the window is the three
        local days before it; deriving the day from the UTC calendar date
        instead would train and trim a day too late."""
        new_york_evening = datetime(2026, 6, 20, 20, 0, tzinfo=ZoneInfo("America/New_York"))
        assert new_york_evening.astimezone(UTC).day == 21
        self._assert_pool_intact(new_york_evening, "America/New_York")

    def test_the_button_and_the_midnight_trigger_train_the_same_window(self) -> None:
        """The same instant as a UTC `now` (button) and as a local `now`
        (midnight trigger) gives the same fitted pools."""
        instant = datetime(2026, 6, 19, 22, 1, tzinfo=UTC)  # 00:01 on 20 June in Berlin
        pools = []
        for now in (instant, instant.astimezone(ZoneInfo("Europe/Berlin"))):
            coordinator, _hass, _fetches = _make_setup(3, "Europe/Berlin")
            _run(coordinator.async_refit(now))
            pools.append(
                coordinator.cache.get_regression_pools(
                    _training_sensors(coordinator), 0, reference=now
                )
            )
        for sensor_id in pools[0]:
            assert np.array_equal(pools[0][sensor_id], pools[1][sensor_id], equal_nan=True)

    def test_with_smoothing_neighbors_utc(self) -> None:
        """The neighbor slots beyond the window's ends survive the trim too."""
        self._assert_pool_intact(_RECALIBRATION, "UTC", radius=2)

    def test_with_smoothing_neighbors_local_midnight_trigger(self) -> None:
        berlin_midnight = datetime(2026, 6, 20, 0, 1, tzinfo=ZoneInfo("Europe/Berlin"))
        self._assert_pool_intact(berlin_midnight, "Europe/Berlin", radius=2)

    def test_utc_button_press_mid_day(self) -> None:
        self._assert_pool_intact(datetime(2026, 6, 20, 14, 37, tzinfo=UTC), "UTC")

    def test_the_coordinator_passes_the_configured_smoothing_radius(self) -> None:
        coordinator, _hass, _fetches = _make_setup(window_days=3, smoothing_radius=2)
        _spy_on_trim(coordinator)

        _run(coordinator.async_refit(_RECALIBRATION))

        assert coordinator._trim_radii == [2]

    def test_the_coordinator_passes_the_recalibrations_own_now(self) -> None:
        """The coordinator needs no knowledge of how the training window is
        anchored: `Cache.trim` keeps whole days back from the reference, the
        same window `get_regression_pools` reads for the same `now`
        (`tests/test_cache_regression_pools.py::TestTrimNeverDiscardsTheTrainingPool`
        is the guard for that)."""
        coordinator, _hass, _fetches = _make_setup(window_days=3)
        references = _spy_on_trim(coordinator)

        _run(coordinator.async_refit(_RECALIBRATION))

        assert references == [_RECALIBRATION]


class TestModelSlotsStayUtcClockWithLocalDayBoundaries:
    """ADR-008 §2 Amendment 2026-10-10 (`TASK-0044`, human decision): the
    training window's days are local days, but a model slot is still the
    UTC-clock slot -- the one the forward fill and every prediction path
    index by. The recorder fixture is periodic per UTC clock slot, so
    whatever the timezone, the pool the real coordinator fetch path builds
    must be cell-for-cell the UTC install's: a local-clock row mapping
    would shift every row by the UTC offset."""

    def _pools(self, time_zone: str) -> dict[str, Any]:
        coordinator, _hass, _fetches = _make_setup(3, time_zone)
        now = datetime(2026, 6, 20, 0, 1, tzinfo=ZoneInfo(time_zone))
        _run(coordinator.async_refit(now))
        pools: dict[str, Any] = coordinator.cache.get_regression_pools(
            _training_sensors(coordinator), 0, reference=now
        )
        return pools

    def test_pools_equal_the_utc_installs_in_every_timezone(self) -> None:
        reference_pools = self._pools("UTC")
        for time_zone in ("Europe/Berlin", "America/New_York", "Pacific/Auckland"):
            pools = self._pools(time_zone)
            for sensor_id, pool in reference_pools.items():
                assert not np.isnan(pool).any()
                assert np.array_equal(pools[sensor_id], pool), (time_zone, sensor_id)


# -- AC3: a pin older than the live window keeps its own window ------------------


class TestPinnedWindowSurvivesTheTrim:
    """Given a pinned reference older than the live window, when the
    recalibration trims, then the pin's own window is still fully readable
    (ADR-007a §6)."""

    def test_an_old_pin_is_still_served_without_a_recorder_query(self) -> None:
        window_days = 3
        coordinator, _hass, fetches = _make_setup(window_days)
        cache = coordinator.cache
        sensors = [tc._ACTUAL_YIELD_ENTITY]
        pinned_day = date(2026, 6, 14)  # 6 days before the 20th: older than the live window
        cache.pin_reference(pinned_day)

        slot_of_day = 12 * 12  # noon
        before = cache.get_pinned_slot_pool(sensors, slot_of_day, on_invalid="raw")
        assert len(before[tc._ACTUAL_YIELD_ENTITY]) == window_days
        pin_window_start = (
            Cache.index_for(datetime(pinned_day.year, pinned_day.month, pinned_day.day, tzinfo=UTC))
            - (window_days - 1) * SLOTS_PER_DAY
        )

        _run(coordinator.async_refit(_RECALIBRATION))

        # The live floor alone would be 17 June 00:00; the pin reaches back
        # to 12 June. It must still be stored.
        assert cache._list_offset[tc._ACTUAL_YIELD_ENTITY] <= pin_window_start
        fetches.clear()
        after = cache.get_pinned_slot_pool(sensors, slot_of_day, on_invalid="raw")
        assert after == before
        assert fetches == {}


class TestAutoTrackingPinnedPoolSurvivesTheTrim:
    """The no-pin case of ADR-007a §6: `get_pinned_slot_pool`'s window is
    anchored on the *local* calendar day, the training pool's on `now`'s
    fields read as UTC. Whatever the offset, the trim floor must not fall
    inside the diagnostic window either."""

    def _assert_pool_intact(self, now: datetime, time_zone: str) -> None:
        window_days = 3
        coordinator, _hass, fetches = _make_setup(window_days, time_zone)
        cache = coordinator.cache
        sensors = [tc._ACTUAL_YIELD_ENTITY]
        oldest_slot = 0  # slot 0 of the oldest day is the one most at risk
        before = cache.get_pinned_slot_pool(sensors, oldest_slot, on_invalid="raw", reference=now)
        assert len(before[tc._ACTUAL_YIELD_ENTITY]) == window_days

        _run(coordinator.async_refit(now))

        fetches.clear()
        after = cache.get_pinned_slot_pool(sensors, oldest_slot, on_invalid="raw", reference=now)
        # Nothing readable before may be lost. (Not `after == before`: a
        # not-yet-elapsed slot reads `None` before the refit, and the
        # refit's own pool fetch may legitimately have filled it since.)
        for sensor_id in sensors:
            assert len(after[sensor_id]) == len(before[sensor_id])
            for value_before, value_after in zip(before[sensor_id], after[sensor_id], strict=True):
                if value_before is not None:
                    assert value_after == value_before
        assert fetches == {}  # and nothing had to be re-read from the recorder

    def test_utc(self) -> None:
        self._assert_pool_intact(_RECALIBRATION, "UTC")

    def test_east_of_utc_midnight_trigger(self) -> None:
        self._assert_pool_intact(
            datetime(2026, 6, 20, 0, 1, tzinfo=ZoneInfo("Pacific/Auckland")), "Pacific/Auckland"
        )

    def test_west_of_utc_evening(self) -> None:
        self._assert_pool_intact(
            datetime(2026, 6, 20, 20, 0, tzinfo=ZoneInfo("America/New_York")), "America/New_York"
        )


# -- AC4: bounded growth over many days ------------------------------------------


class TestSeriesStayBoundedOverManyDays:
    """Given a series list for each sensor, when many days pass with a
    recalibration each day, then its length stays bounded instead of
    growing by 288 entries a day."""

    def test_lengths_reach_a_steady_state(self) -> None:
        window_days = 2
        coordinator, _hass, _fetches = _make_setup(window_days)
        lengths_by_day: list[dict[str, int]] = []

        for day in range(window_days + 1, window_days + 11):
            now = _FIRST_DATA_DAY + timedelta(days=day, minutes=1)
            coordinator._now = lambda now=now: now
            _run(coordinator.async_refit(now))
            lengths_by_day.append({k: len(v) for k, v in coordinator.cache._values.items()})

        # Today + tomorrow's pushed forecast is the only thing allowed
        # beyond the training window.
        bound = (window_days + 2) * SLOTS_PER_DAY
        for lengths in lengths_by_day:
            for sensor_id, length in lengths.items():
                assert length <= bound, (sensor_id, length)
        # Steady state: the last several days are the same size, i.e. the
        # lists are not creeping up by a day's worth per recalibration.
        assert lengths_by_day[-1] == lengths_by_day[-2] == lengths_by_day[-3]
        # The shadow arrays are trimmed in lockstep with the lists.
        for sensor_id, values in coordinator.cache._values.items():
            assert len(coordinator.cache._shadow[sensor_id]) == len(values)
