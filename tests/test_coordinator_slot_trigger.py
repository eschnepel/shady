"""Tests for `coordinator.py`'s recorder-synchronized slot trigger
(`TASK-0041`; ADR-006 §1a and ADR-004 §2i Amendments 2026-10-07).

Reuses `test_coordinator.py`'s hand-written `homeassistant` stub and fixtures
(`tc`), plus `tests/support_ha.py`'s `FakeBus`.

The recorder is simulated by `_Recorder`: a slot's statistic only becomes
visible to the coordinator after a configurable number of probes — "the
event fires before the commit". Time is `_Clock`, and the probe back-off is
an injectable sleeper (`coordinator._sleep`), so nothing here waits for real.
"""

from __future__ import annotations

import ast
import asyncio
import functools
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests import test_coordinator as tc
from tests.support import _run
from tests.support_ha import FakeHomeAssistant

# Collection-order guard, see `tc._restore_modules`'s own comment.
tc._restore_modules()
Cache = tc.Cache
_coordinator_mod: Any = tc._coordinator_mod
_EVENT: str = _coordinator_mod.EVENT_RECORDER_5MIN_STATISTICS_GENERATED
_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"

# Event time: ten seconds after the 13:55 boundary, like the recorder's own
# compile. The newest complete slot is therefore 13:50-13:55, and the one
# before it (13:45) is already in the recorder.
_T = datetime(2026, 6, 15, 13, 55, 10, tzinfo=UTC)
_NEWEST_COMPLETE = Cache.index_for(_T) - 1


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class _Recorder:
    """Wraps the fake recorder executor: records every dispatched job by
    name and reveals the newest complete slot's statistic only once
    `visible_after_probes` probes have *not* seen it (`None`: never)."""

    def __init__(
        self,
        hass: Any,
        slot_index: int,
        *,
        visible_after_probes: int | None = 0,
        value: float = 400.0,
    ) -> None:
        self.hass = hass
        self.slot_index = slot_index
        self.visible_after_probes = visible_after_probes
        self.value = value
        self.probes = 0
        self.executed: list[str] = []
        self._real = hass.async_add_executor_job
        hass.async_add_executor_job = self._dispatch

    def reveal(self) -> None:
        self.hass.statistics[tc._ACTUAL_YIELD_ENTITY][Cache.timestamp_for(self.slot_index)] = (
            self.value
        )

    async def _dispatch(self, func: Callable[..., Any], *args: Any) -> Any:
        name = getattr(func, "__name__", repr(func))
        self.executed.append(name)
        if name == "_probe_slot_ready_sync":
            self.probes += 1
            if self.visible_after_probes is not None and self.probes > self.visible_after_probes:
                self.reveal()
        return await self._real(func, *args)


def _make_setup(
    clock: _Clock | None = None, **entry_overrides: Any
) -> tuple[Any, FakeHomeAssistant, _Clock, list[float]]:
    """A single-string coordinator with a 3-day training window, today's
    statistics present up to (excluding) the newest complete slot."""
    clock = clock or _Clock(_T)
    entry = tc._make_entry(window_days=3, smoothing_radius=0, **entry_overrides)
    hass = FakeHomeAssistant()
    hass.states.set(
        tc._BASELINE_ENTITY,
        {
            "wh_period": tc._synthetic_wh_period(
                datetime(2026, 6, 1, tzinfo=UTC), tc._NOW + timedelta(days=3)
            )
        },
    )
    hass.states.set(tc._ACTUAL_YIELD_ENTITY, {})
    by_start: dict[datetime, float] = {}
    ts = datetime(2026, 6, 12, tzinfo=UTC)
    while Cache.index_for(ts) < _NEWEST_COMPLETE:
        by_start[ts] = 400.0 if 6 <= ts.hour < 18 else 0.0
        ts += timedelta(minutes=5)
    hass.statistics[tc._ACTUAL_YIELD_ENTITY] = by_start

    coordinator = tc.ShadyCoordinator(hass, entry)
    coordinator._now = clock
    sleeps: list[float] = []

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)
        await asyncio.sleep(0)

    coordinator._sleep = _sleep
    return coordinator, hass, clock, sleeps


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


def _count_body_runs(coordinator: Any) -> list[tuple[Any, ...]]:
    """Wrap `_intraday_tick_sync` so each run is recorded (and still runs)."""
    runs: list[tuple[Any, ...]] = []
    real = coordinator._intraday_tick_sync

    @functools.wraps(real)
    def _wrapper(*args: Any) -> Any:
        runs.append(args)
        return real(*args)

    coordinator._intraday_tick_sync = _wrapper
    return runs


def _selected_actual_and_accuracy(coordinator: Any) -> tuple[bool, dict[str, Any]]:
    result = coordinator._diagnostic_result_cache
    assert result is not None, "no diagnostic result was published"
    sensor = next(s for s in result.sensors if s.sensor_id == "0")
    names = [entry["name"] for entry in sensor.attributes["series"]]
    return "selected actual" in names, dict(sensor.attributes["accuracy"])


class TestEventWiring:
    """Given the coordinator is set up, then it subscribes to the recorder's
    statistics event, and `shutdown()` removes that and cancels the job."""

    def test_subscribes_to_the_recorder_statistics_event(self) -> None:
        _coordinator, hass, _clock, _sleeps = _make_setup()
        assert hass.bus.listener_count(_EVENT) == 1

    def test_shutdown_unsubscribes_and_cancels_an_inflight_job(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=None)
            blocker = asyncio.Event()

            async def _block(_seconds: float) -> None:
                await blocker.wait()

            coordinator._sleep = _block
            hass.bus.fire(_EVENT)
            await _settle()
            task = coordinator._slot_job_task
            assert task is not None and not task.done()  # probing, parked in the back-off

            coordinator.shutdown()
            await _settle()

            assert task.cancelled()
            assert hass.bus.listener_count(_EVENT) == 0

        _run(_drive())

    def test_handler_is_a_callback_that_only_schedules_a_task(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            recorder = _Recorder(hass, _NEWEST_COMPLETE)

            returned = coordinator._handle_recorder_statistics(None)

            assert returned is None
            assert recorder.executed == []  # no recorder access in the handler itself
            assert len(hass._pending_tasks) == 1  # one scheduled task
            await hass.drain()

        _run(_drive())

    def test_coordinator_source_never_blocks_the_loop(self) -> None:
        source = (_SHADY_DIR / "coordinator.py").read_text()
        assert "time.sleep" not in source


class TestWatchdog:
    """Given the interval stays registered as a watchdog (D3), its handler
    starts a job only if none was started for `WATCHDOG`."""

    def test_registered_with_the_watchdog_period(self) -> None:
        assert _coordinator_mod.WATCHDOG == timedelta(minutes=6)
        assert _coordinator_mod.PROBE_INTERVAL == timedelta(seconds=1)
        assert _coordinator_mod.MAX_PROBES == 5

    def test_does_not_start_a_job_while_events_keep_arriving(self) -> None:
        async def _drive() -> None:
            coordinator, hass, clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            runs = _count_body_runs(coordinator)

            hass.bus.fire(_EVENT)
            await hass.drain()
            assert len(runs) == 1

            clock.now = _T + timedelta(minutes=5)
            coordinator._handle_slot_watchdog(clock.now)
            await hass.drain()
            assert len(runs) == 1  # an event job started 5 minutes ago: stay quiet

            clock.now = _T + timedelta(minutes=6)
            coordinator._handle_slot_watchdog(clock.now)
            await hass.drain()
            assert len(runs) == 2  # nothing for 6 minutes: the watchdog steps in

        _run(_drive())

    def test_with_no_event_ever_the_job_runs_and_diagnostics_advance(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            coordinator.set_active_diagnostic_mode("compare_regressions")
            stale_index = coordinator._diagnostic_slot_index

            coordinator._handle_slot_watchdog(_T)  # no event was ever fired
            await hass.drain()

            assert coordinator._diagnostic_slot_index == _NEWEST_COMPLETE != stale_index
            assert coordinator._diagnostic_result_cache is not None

        _run(_drive())


class TestDedupeAndSupersede:
    def test_two_triggers_for_the_same_slot_run_the_body_once(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            runs = _count_body_runs(coordinator)

            hass.bus.fire(_EVENT)
            hass.bus.fire(_EVENT)  # duplicate event
            coordinator._handle_slot_watchdog(_T)  # and a watchdog for the same slot
            await hass.drain()

            assert len(runs) == 1

        _run(_drive())

    def test_watchdog_then_event_for_the_same_slot_run_the_body_once(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            runs = _count_body_runs(coordinator)

            coordinator._handle_slot_watchdog(_T)
            hass.bus.fire(_EVENT)
            await hass.drain()

            assert len(runs) == 1

        _run(_drive())

    def test_a_newer_event_cancels_a_job_still_probing_and_it_never_runs_its_body(self) -> None:
        async def _drive() -> None:
            coordinator, hass, clock, _sleeps = _make_setup()
            # The first slot never becomes visible; the second one does.
            first_slot = _NEWEST_COMPLETE
            second_slot = _NEWEST_COMPLETE + 1
            recorder = _Recorder(hass, first_slot, visible_after_probes=None)
            blocker = asyncio.Event()

            async def _block(_seconds: float) -> None:
                await blocker.wait()  # parks job 1 in its probe back-off

            coordinator._sleep = _block
            runs = _count_body_runs(coordinator)

            hass.bus.fire(_EVENT)
            await _settle()
            job_one = coordinator._slot_job_task
            assert job_one is not None and not job_one.done()

            # The next slot's event: its statistic is visible straight away.
            clock.now = _T + timedelta(minutes=5)
            recorder.slot_index = second_slot
            recorder.visible_after_probes = 0
            hass.bus.fire(_EVENT)
            await hass.drain()

            assert job_one.done()
            assert [Cache.index_for(args[0]) - 1 for args in runs] == [second_slot]

        _run(_drive())


class TestProbeAndRetry:
    def test_retries_until_the_commit_is_visible_then_runs_the_body_once(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, sleeps = _make_setup()
            recorder = _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=2)
            runs = _count_body_runs(coordinator)

            hass.bus.fire(_EVENT)
            await hass.drain()

            assert recorder.probes == 3  # two misses, then the commit
            assert sleeps == [1.0, 1.0]  # PROBE_INTERVAL between probes, on the loop
            assert len(runs) == 1
            # Probe and body both ran on the recorder executor, in this order.
            assert recorder.executed == [
                "_probe_slot_ready_sync",
                "_probe_slot_ready_sync",
                "_probe_slot_ready_sync",
                "_intraday_tick_sync",
            ]

        _run(_drive())

    def test_gives_up_after_max_probes_and_runs_the_body_anyway(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, sleeps = _make_setup()
            recorder = _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=None)
            coordinator._max_probes = 3
            runs = _count_body_runs(coordinator)

            hass.bus.fire(_EVENT)
            await hass.drain()

            assert recorder.probes == 1 + 3  # the first probe plus MAX_PROBES retries
            assert len(sleeps) == 3
            assert len(runs) == 1

        _run(_drive())

    def test_a_string_with_no_data_never_delays_the_job(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, sleeps = _make_setup()
            hass.statistics[tc._ACTUAL_YIELD_ENTITY] = {}  # nothing recorded at all
            recorder = _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=None)
            runs = _count_body_runs(coordinator)

            hass.bus.fire(_EVENT)
            await hass.drain()

            assert recorder.probes == 1
            assert sleeps == []
            assert len(runs) == 1

        _run(_drive())


class TestSlotJobBody:
    def test_runs_the_former_tick_body_in_order(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            order: list[str] = []

            def _wrap(name: str) -> None:
                real = getattr(coordinator, name)

                def _recording(*args: Any) -> Any:
                    order.append(name)
                    return real(*args)

                setattr(coordinator, name, _recording)

            for name in (
                "_advance_followed_diagnostic_slot",
                "_advance_intraday_string",
                "_diagnostics_tick_sync",
            ):
                _wrap(name)

            hass.bus.fire(_EVENT)
            await hass.drain()

            assert order == [
                "_advance_followed_diagnostic_slot",
                "_advance_intraday_string",
                "_diagnostics_tick_sync",
            ]

        _run(_drive())

    def test_intraday_advance_runs_once_per_slot_job_with_the_same_inputs(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup(intraday_correction_mode="ramping")
            _Recorder(hass, _NEWEST_COMPLETE)
            calls: list[tuple[int, datetime]] = []
            real = coordinator._advance_intraday_string

            def _recording(string: Any, now: datetime) -> Any:
                calls.append((string.index, now))
                return real(string, now)

            coordinator._advance_intraday_string = _recording

            hass.bus.fire(_EVENT)
            hass.bus.fire(_EVENT)  # a duplicate must not advance twice
            await hass.drain()

            assert calls == [(0, _T)]

        _run(_drive())


class TestFailuresAreLoggedNotRaised:
    """ADR-000 §8: a failing probe or body is logged and swallowed — and
    must neither stop the correction nor wedge the cache job lock."""

    def test_a_failing_probe_does_not_stop_the_body(self, caplog: pytest.LogCaptureFixture) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            runs = _count_body_runs(coordinator)

            def _probe_boom(_slot_index: int) -> bool:
                raise RuntimeError("probe boom")

            coordinator._probe_slot_ready_sync = _probe_boom

            hass.bus.fire(_EVENT)
            await hass.drain()  # must not raise

            assert len(runs) == 1

        with caplog.at_level("ERROR"):
            _run(_drive())
        assert "Slot probe failed" in caplog.text

    def test_a_failing_body_is_logged_and_the_next_slot_still_runs(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        async def _drive() -> None:
            coordinator, hass, clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            real = coordinator._intraday_tick_sync
            calls: list[datetime] = []

            @functools.wraps(real)
            def _flaky(now: datetime) -> None:
                calls.append(now)
                if len(calls) == 1:
                    raise RuntimeError("body boom")
                real(now)

            coordinator._intraday_tick_sync = _flaky

            hass.bus.fire(_EVENT)
            await hass.drain()  # must not raise
            clock.now = _T + timedelta(minutes=5)
            hass.bus.fire(_EVENT)
            await hass.drain()

            assert len(calls) == 2  # the lock was released, the next job ran

        with caplog.at_level("ERROR"):
            _run(_drive())
        assert "Slot job failed" in caplog.text


class TestEndToEndPhaseReplay:
    """The 2026-10-07 incident, through the real event path: the recorder's
    event fires 10 s after the boundary, the commit becomes visible a
    little later, and the published diagnostic result must contain the
    newest complete slot's actual."""

    def test_followed_result_has_selected_actual_and_accuracy_when_the_commit_lags(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            recorder = _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=1)
            coordinator.set_active_diagnostic_mode("compare_regressions")

            hass.bus.fire(_EVENT)
            await hass.drain()

            assert recorder.probes == 2  # the first probe lost the race, the second won
            has_actual, accuracy = _selected_actual_and_accuracy(coordinator)
            assert coordinator._diagnostic_slot_index == _NEWEST_COMPLETE
            assert has_actual
            assert accuracy  # at least one method has an accuracy value

        _run(_drive())

    def test_without_retries_the_first_probe_loses_the_race(self) -> None:
        """Guards the simulation itself: with `MAX_PROBES = 0` the very same
        event/commit timing reproduces the reported symptom, so the test
        above passes *because of* the probe, not because the race is
        absent from the harness."""

        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=1)
            coordinator._max_probes = 0
            coordinator.set_active_diagnostic_mode("compare_regressions")

            hass.bus.fire(_EVENT)
            await hass.drain()

            has_actual, accuracy = _selected_actual_and_accuracy(coordinator)
            assert not has_actual
            assert accuracy == {}

        _run(_drive())

    def test_the_result_is_published_without_the_actual_after_bounded_retries(self) -> None:
        async def _drive() -> None:
            coordinator, hass, _clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=None)
            coordinator._max_probes = 2
            coordinator.set_active_diagnostic_mode("compare_regressions")

            hass.bus.fire(_EVENT)
            await hass.drain()

            has_actual, accuracy = _selected_actual_and_accuracy(coordinator)
            assert not has_actual
            assert accuracy == {}

        _run(_drive())

    def test_a_just_elapsed_pinned_slot_gains_its_actual_on_the_first_job_after_it_exists(
        self,
    ) -> None:
        async def _drive() -> None:
            coordinator, hass, clock, _sleeps = _make_setup()
            recorder = _Recorder(hass, _NEWEST_COMPLETE, visible_after_probes=None)
            coordinator._max_probes = 0
            pinned = Cache.timestamp_for(_NEWEST_COMPLETE)
            assert coordinator.pin_diagnostic_slot(pinned)
            coordinator.set_active_diagnostic_mode("compare_regressions")

            hass.bus.fire(_EVENT)  # the statistic is not committed yet
            await hass.drain()
            has_actual, _accuracy = _selected_actual_and_accuracy(coordinator)
            assert not has_actual
            assert coordinator._diagnostic_slot_index == _NEWEST_COMPLETE  # still pinned

            recorder.reveal()  # committed since
            clock.now = _T + timedelta(minutes=5)
            hass.bus.fire(_EVENT)  # the next slot's job
            await hass.drain()

            has_actual, accuracy = _selected_actual_and_accuracy(coordinator)
            assert has_actual
            assert accuracy

        _run(_drive())

    def test_a_pinned_in_progress_slot_still_gets_its_prediction_refreshed_each_job(self) -> None:
        async def _drive() -> None:
            coordinator, hass, clock, _sleeps = _make_setup()
            _Recorder(hass, _NEWEST_COMPLETE)
            in_progress = Cache.timestamp_for(_NEWEST_COMPLETE + 1)
            assert coordinator.pin_diagnostic_slot(in_progress)
            coordinator.set_active_diagnostic_mode("compare_regressions")
            fits: list[datetime] = []
            mode = coordinator.diagnostic_mode()
            real_fit = mode.extra_fit

            def _counting_fit() -> Any:
                fits.append(clock.now)
                return real_fit()

            mode.extra_fit = _counting_fit

            hass.bus.fire(_EVENT)
            await hass.drain()
            clock.now = _T + timedelta(minutes=5)
            hass.bus.fire(_EVENT)
            await hass.drain()

            assert len(fits) == 2

        _run(_drive())


class _FakeExecutorHass(FakeHomeAssistant):
    """`FakeHomeAssistant` whose recorder executor can overlap jobs: each
    dispatched job yields to the loop while 'running', so two jobs *would*
    run concurrently unless the coordinator serializes them."""

    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self.gates: dict[str, asyncio.Event] = {}
        self.finished: list[str] = []

    async def async_add_executor_job(self, func: Any, *args: Any) -> Any:
        label = args[0] if args else func.__name__
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        try:
            gate = self.gates.get(label)
            if gate is not None:
                await gate.wait()
            for _ in range(5):
                await asyncio.sleep(0)
            return func(*args)
        finally:
            self.active -= 1
            self.finished.append(label)


def _make_executor_setup() -> tuple[Any, _FakeExecutorHass]:
    hass = _FakeExecutorHass()
    hass.states.set(
        tc._BASELINE_ENTITY,
        {"wh_period": tc._synthetic_wh_period(tc._YESTERDAY, tc._NOW + timedelta(days=3))},
    )
    hass.states.set(tc._ACTUAL_YIELD_ENTITY, {})
    coordinator = tc.ShadyCoordinator(hass, tc._make_entry())
    coordinator._now = lambda: tc._NOW
    return coordinator, hass


class TestCacheJobLock:
    """`async_run_cache_job(fn, *args)` is the one dispatch to the recorder
    executor; it serializes jobs on a single lock on the loop."""

    def test_two_concurrent_jobs_never_overlap(self) -> None:
        async def _drive() -> None:
            coordinator, hass = _make_executor_setup()
            results = await asyncio.gather(
                coordinator.async_run_cache_job(lambda label: f"done {label}", "a"),
                coordinator.async_run_cache_job(lambda label: f"done {label}", "b"),
            )
            assert list(results) == ["done a", "done b"]
            assert hass.max_active == 1
            assert hass.finished == ["a", "b"]

        _run(_drive())

    def test_the_lock_is_held_until_a_cancelled_job_has_really_finished(self) -> None:
        async def _drive() -> None:
            coordinator, hass = _make_executor_setup()
            hass.gates["a"] = asyncio.Event()  # job "a"'s thread is still running
            job_a = asyncio.ensure_future(coordinator.async_run_cache_job(lambda label: label, "a"))
            await _settle()
            job_b = asyncio.ensure_future(coordinator.async_run_cache_job(lambda label: label, "b"))
            await _settle()

            job_a.cancel()  # the awaiting task goes away; the thread cannot
            await _settle()
            assert not job_b.done()  # "b" must not start while "a" still runs
            assert hass.active == 1

            hass.gates["a"].set()
            assert await job_b == "b"
            assert hass.max_active == 1

        _run(_drive())

    def test_every_cache_touching_dispatch_goes_through_the_method(self) -> None:
        coordinator_calls = _executor_dispatch_call_lines(_SHADY_DIR / "coordinator.py")
        http_calls = _executor_dispatch_call_lines(_SHADY_DIR / "http_export.py")
        assert len(coordinator_calls) == 1  # the one inside `async_run_cache_job`
        assert http_calls == []

    def test_jobs_in_every_path_are_serialized_by_the_method(self) -> None:
        async def _drive() -> None:
            coordinator, hass = _make_executor_setup()
            seen: list[str] = []
            real = coordinator.async_run_cache_job

            async def _recording(fn: Callable[..., Any], *args: Any) -> Any:
                seen.append(fn.__name__)
                return await real(fn, *args)

            coordinator.async_run_cache_job = _recording
            await coordinator.async_refit(tc._NOW)
            assert "_refit_sync" in seen
            coordinator.set_active_diagnostic_mode("compare_regressions")
            await coordinator._async_recompute_diagnostic_result()
            assert "compute" in seen
            assert hass.max_active == 1

        _run(_drive())

    def test_module_docstring_no_longer_claims_a_single_worker_executor(self) -> None:
        doc = _coordinator_mod.__doc__
        assert "single-worker" not in doc
        assert "POOL_SIZE" in doc


def _executor_dispatch_call_lines(path: Path) -> list[int]:
    tree = ast.parse(path.read_text())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "async_add_executor_job"
    ]
