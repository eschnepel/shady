"""Tests for `coordinator.py`'s local-timezone resolution (TASK-0039).

The reported bug: a person in `Europe/Berlin` (`UTC+2` in summer, CEST)
had to pin the diagnostic slot two hours earlier than they actually
meant for the diagnostic dashboard series to show the entry they
expected. Root cause — every "which calendar day/what time of day is
this" question `coordinator.py`/`cache.py` asked (`diagnosed_slot()`'s
`slot_of_day`, the diagnostic-slot pin's own `pinned_reference` date,
`_tomorrow_end`'s forecast horizon, `fc_day_array`'s "today", the
energy-integral midnight reset) was silently answered in `UTC`, never
in HA's own configured local timezone (`hass.config.time_zone`), even
though `cache.py`'s absolute-instant slot-index arithmetic (`EPOCH`
itself `UTC`-anchored) was — and still is — entirely correct
regardless.

Reuses `test_coordinator.py`'s own hand-written `homeassistant`-stub
harness wholesale (`FakeHomeAssistant`, `ShadyCoordinator`,
`_make_entry`, ...) rather than reimplementing it, the same way
`tests/diagnostics/test_compare_regressions.py` already does.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tests import test_coordinator as tc
from tests.support_ha import FakeHomeAssistant

tc._restore_modules()

# `Any`, not `tc.ShadyCoordinator` itself, for every annotation below —
# a file-path-loaded class isn't valid as a static type (mypy: "not
# valid as a type"), the same reason `test_coordinator.py`'s own
# `_make_coordinator` returns `tuple[Any, FakeHomeAssistant]` rather
# than annotating with it directly. `ShadyCoordinator` stays usable as
# a plain callable (constructing instances) either way.
ShadyCoordinator = tc.ShadyCoordinator
Cache = tc.Cache

_BERLIN = ZoneInfo("Europe/Berlin")
# Deep summer -- unambiguous CEST (`UTC+2`), no DST-transition edge case.
_NOW_UTC = datetime(2026, 6, 15, 10, 0, tzinfo=UTC)
_YESTERDAY = datetime(2026, 6, 14, tzinfo=UTC)


def _make_berlin_coordinator() -> tuple[Any, FakeHomeAssistant]:
    hass = FakeHomeAssistant()
    hass.config.time_zone = "Europe/Berlin"
    hass.states.set(
        tc._BASELINE_ENTITY,
        {"wh_period": tc._synthetic_wh_period(_YESTERDAY, _NOW_UTC + timedelta(days=3))},
    )
    hass.states.set(tc._ACTUAL_YIELD_ENTITY, {})
    tc._seed_actual_yield_statistics(hass, _YESTERDAY, _YESTERDAY + timedelta(days=1))
    coordinator = ShadyCoordinator(hass, tc._make_entry())
    coordinator._now = lambda: _NOW_UTC
    return coordinator, hass


class TestLocalTimezoneResolution:
    """Given `hass.config.time_zone`, the coordinator resolves it into
    a real `tzinfo` up front, falling back to `UTC` (this module's own
    prior, implicit behavior) if it is ever missing or unrecognized —
    never failing setup entirely over it (ADR-000 §8)."""

    def test_resolves_hass_configured_time_zone(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()
        assert coordinator._local_tz == _BERLIN

    def test_default_fake_hass_still_resolves_to_utc(self) -> None:
        coordinator, _hass = tc._make_coordinator()
        # `ZoneInfo("UTC")`, not the `datetime.UTC` singleton (`hass.
        # config.time_zone` defaults to the string `"UTC"`, `support_ha.
        # py`) -- behaviorally identical (zero offset, no DST), which is
        # all this module's own calendar-day arithmetic ever depends on.
        assert coordinator._local_tz.utcoffset(_NOW_UTC) == timedelta(0)

    def test_falls_back_to_utc_for_an_unrecognized_zone_name(self) -> None:
        hass = FakeHomeAssistant()
        hass.config.time_zone = "Not/A/Real/Zone"
        coordinator = ShadyCoordinator(hass, tc._make_entry())
        assert coordinator._local_tz is UTC


class TestDiagnosedSlotIsLocalTimeOfDay:
    """Pinning a local wall-clock time must diagnose *that* slot's own
    local time of day — `slot_of_day` counted from local midnight, not
    `index % SLOTS_PER_DAY` (`UTC` midnight, since `Cache`'s `EPOCH` is
    itself `UTC`-anchored) — the exact reported bug."""

    def test_pin_at_local_afternoon_reports_the_local_slot_of_day(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()
        target_local = datetime(2026, 6, 15, 14, 0, tzinfo=_BERLIN)

        assert coordinator.pin_diagnostic_slot(target_local, now=_NOW_UTC) is True
        slot = coordinator.diagnosed_slot(_NOW_UTC)

        # 14:00 local == 168 five-minute slots since *local* midnight --
        # not 144 (168 - 24), which `index % SLOTS_PER_DAY`'s `UTC`
        # framing would have reported pre-fix (14:00 CEST == 12:00 UTC).
        assert slot.slot_of_day == 168
        assert coordinator.cache.pinned_reference == date(2026, 6, 15)

    def test_pin_just_after_local_midnight_keeps_the_local_calendar_date(self) -> None:
        """Local `2026-06-15 01:00 CEST` is `UTC 2026-06-14 23:00` — the
        exact boundary a `UTC`-relative `.date()` extraction gets wrong
        (it would have pinned `pinned_reference` to June 14)."""
        coordinator, _hass = _make_berlin_coordinator()
        target_local = datetime(2026, 6, 15, 1, 0, tzinfo=_BERLIN)

        coordinator.pin_diagnostic_slot(target_local, now=_NOW_UTC)
        slot = coordinator.diagnosed_slot(_NOW_UTC)

        assert coordinator.cache.pinned_reference == date(2026, 6, 15)
        assert slot.slot_of_day == 12  # 01:00 local == 12 slots since local midnight.

    def test_following_slot_also_reports_the_local_slot_of_day(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()
        # `_NOW_UTC` is 2026-06-15 10:00 UTC == 12:00 CEST; the newest
        # complete slot starts 11:55 CEST (== 09:55 UTC).
        coordinator.set_follow_latest_diagnostic_slot(True, now=_NOW_UTC)

        slot = coordinator.diagnosed_slot(_NOW_UTC)

        assert coordinator.diagnostic_slot_timestamp() == datetime(2026, 6, 15, 9, 55, tzinfo=UTC)
        assert slot.slot_of_day == 143  # 11:55 local == 143 slots since local midnight.


class TestForecastHorizonIsLocalCalendarDay:
    """ADR-002 §3's "remainder of today + all of tomorrow" means HA's
    configured local calendar day, not `UTC`'s (TASK-0039) — a pin
    exactly at the start of the local day after tomorrow is rejected;
    one 5-minute slot earlier is accepted."""

    def test_rejects_a_timestamp_at_the_local_horizon_boundary(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()
        # `_NOW_UTC` local date is 2026-06-15 (CEST) -- the horizon ends
        # at local midnight starting 2026-06-17.
        horizon_end_local = datetime(2026, 6, 17, 0, 0, tzinfo=_BERLIN)

        assert coordinator.pin_diagnostic_slot(horizon_end_local, now=_NOW_UTC) is False

    def test_accepts_the_last_slot_within_the_local_horizon(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()
        last_slot_local = datetime(2026, 6, 16, 23, 55, tzinfo=_BERLIN)

        assert coordinator.pin_diagnostic_slot(last_slot_local, now=_NOW_UTC) is True


class TestFcDayArrayIsLocalCalendarDay:
    """`fc_day_array` (`ShadyFcDaySumSensor`'s `slot_timestamps`/`slot_
    values`, the one genuine time-series dashboard export) starts at
    real local midnight, not `UTC` midnight (TASK-0039)."""

    def test_first_slot_timestamp_is_local_midnight(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()

        slot_timestamps, _slot_values = coordinator.fc_day_array(_NOW_UTC)

        assert slot_timestamps[0] == datetime(2026, 6, 15, 0, 0, tzinfo=_BERLIN)
        assert slot_timestamps[0] == datetime(2026, 6, 14, 22, 0, tzinfo=UTC)


class TestEnergyResetIsLocalMidnight:
    """The energy-integral midnight reset (ADR-005 §5/§6) compares
    *local* calendar dates (TASK-0039, matching that ADR's own explicit
    "HA's local timezone" text) — for a `UTC+2` zone, local midnight
    (`00:00 CEST`) arrives *two hours before* `UTC`'s own midnight
    (`22:00 UTC` the previous day). A `UTC`-relative `now.date()` (this
    method's pre-fix behavior) would have kept reporting "yesterday"
    for those two hours, delaying the reset past real local midnight."""

    def test_does_not_reset_before_local_midnight(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()
        coordinator._maybe_reset_energy_totals(datetime(2026, 6, 14, 10, 0, tzinfo=UTC))
        assert coordinator.cache.last_reset_date() == date(2026, 6, 14)

        # 2026-06-14 21:00 UTC == 2026-06-14 23:00 CEST -- still June 14
        # in both conventions, one hour before local midnight.
        reset_too_early = coordinator._maybe_reset_energy_totals(
            datetime(2026, 6, 14, 21, 0, tzinfo=UTC)
        )

        assert reset_too_early is False
        assert coordinator.cache.last_reset_date() == date(2026, 6, 14)

    def test_resets_right_at_local_midnight_two_hours_before_the_utc_one(self) -> None:
        coordinator, _hass = _make_berlin_coordinator()
        coordinator._maybe_reset_energy_totals(datetime(2026, 6, 14, 10, 0, tzinfo=UTC))

        # 2026-06-14 22:00 UTC == 2026-06-15 00:00 CEST -- local midnight
        # has arrived, but `UTC`'s own calendar date is still June 14
        # (its own midnight is two hours away yet, at 2026-06-15 00:00
        # UTC) -- exactly the window a `UTC`-relative `now.date()` got
        # wrong pre-fix.
        reset_at_local_midnight = coordinator._maybe_reset_energy_totals(
            datetime(2026, 6, 14, 22, 0, tzinfo=UTC)
        )

        assert reset_at_local_midnight is True
        assert coordinator.cache.last_reset_date() == date(2026, 6, 15)
