"""Tests for `diagnostics/compare_regressions.py`'s `CompareRegressionsMode`
(ADR-004 §2/§2a/§2b/§3/§4/§5, TASK-0015b; ADR-015, `TASK-0038` for
`export_csv`).

Moved from the former flat `tests/test_diagnostics_compare_regressions.py`
(ADR-000 §6's 2026-09-27 Amendment, ADR-015 §7): `tests/diagnostics/` now
mirrors `custom_components/shady/diagnostics/` being a package,
`CompareRegressionsMode` being the one concrete diagnostic mode gets its
own file, alongside `tests/diagnostics/test_base.py` for the shared
base-class mechanism. Also now holds `export_csv`'s own direct unit
tests and `_replay_compare_regressions` (ADR-015 §5), the one
mode-owned function `tests/diagnostics/test_csv_regression_fixtures.py`'s
generic runner imports.

Not zero-mocking (ADR-000 §6's 2026-09-01 update): `CompareRegressionsMode`
requires a constructible `ShadyCoordinator`, so this reuses
`test_coordinator.py`'s own hand-written `homeassistant`-stub harness
wholesale (`FakeHomeAssistant`, `ShadyCoordinator`, `_make_two_string_
coordinator`, ...) rather than reimplementing it — the same way
`test_coordinator_intraday.py` already does.

These tests exercise `compute()` end-to-end through a real
`ShadyCoordinator`, deliberately, for the one thing that matters most
here: the `"sum"` entry (ADR-004 §5, fifth Amendment, 2026-09-03) has to
be demonstrably correct about which calendar day is which across
strings, not just internally consistent — a hand-rolled fake pool would
only prove the arithmetic, not the actual alignment this amendment was
written to fix.
"""

from __future__ import annotations

import math
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from numpy.typing import NDArray

from tests import test_coordinator as tc
from tests.csv_fixture_support import compare_sections, parse_csv_sections
from tests.support_ha import FakeHomeAssistant

# `test_coordinator.py`'s own harness already file-path-loaded
# `aggregation.py` into `sys.modules["shady.aggregation"]` — reuse that
# loaded module rather than a real package import (`custom_components.
# shady.aggregation` isn't on any import path this harness sets up).
# Collection-order guard, see `tc._restore_modules`'s own comment.
tc._restore_modules()
_aggregation_mod = sys.modules["shady.aggregation"]
diagnostic_accuracy = _aggregation_mod.diagnostic_accuracy
_string_computation_mod: Any = sys.modules["shady.string_computation"]
_coordinator_like_mod = sys.modules["shady.coordinator_like"]
_SLOTS_PER_DAY = sys.modules["shady.cache"].SLOTS_PER_DAY
# ADR-004 §2d (2026-09-21 Amendment): `series` entries are complete
# `plotly-graph` traces -- reuse the production builder itself for
# expected values below rather than duplicating its shape and risking
# drift. As of `TASK-0015b-patch-3`, it's a `DiagnosticMode` static
# method (`base.py`), not a `compare_regressions.py`-local function.
_xy_series_entry = sys.modules["shady.diagnostics.base"].DiagnosticMode._xy_series_entry
# TestSelectedValuePassesAllowHistoricalBackfill below constructs a
# `CompareRegressionsMode` directly against a lightweight fake
# coordinator, rather than a full `ShadyCoordinator` -- already loaded
# into `sys.modules` by `test_coordinator.py`'s own harness import
# above.
_CompareRegressionsMode = sys.modules[
    "shady.diagnostics.compare_regressions"
].CompareRegressionsMode

# A 3-day window, no smoothing (single offset "0") — small enough to hand
# -verify, big enough to demonstrate a real gap-pattern mismatch across
# strings (TestSumEntryDayAlignment below).
_WINDOW_DAYS = 3
_PIN = datetime(2026, 6, 10, 10, 0, tzinfo=UTC)  # daytime slot, FC > 0
_DAY_0 = datetime(2026, 6, 8, 10, 0, tzinfo=UTC)
_DAY_1 = datetime(2026, 6, 9, 10, 0, tzinfo=UTC)
_DAY_2 = datetime(2026, 6, 10, 10, 0, tzinfo=UTC)  # == _PIN


def _make_two_string_setup(**entry_overrides: Any) -> tuple[Any, Any]:
    """A two-string coordinator (`tc._make_two_string_coordinator`'s own
    entities/config), with a wide-enough synthetic baseline history that
    a `window_days=3` pool anchored at `_PIN` never hits the "FC itself
    missing" edge case `TestSumEntryDayAlignment`'s own debugging
    already ran into once — only each string's *actual yield* history
    is seeded selectively per test, everything else (baseline) is always
    fully present."""
    entry = tc._make_two_string_entry(
        window_days=_WINDOW_DAYS, smoothing_radius=0, **entry_overrides
    )
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
    hass.states.set(tc._SECOND_ACTUAL_YIELD_ENTITY, {})
    coordinator = tc.ShadyCoordinator(hass, entry)
    coordinator._now = lambda: _PIN
    return coordinator, hass


def _seed(hass: Any, entity_id: str, by_day: dict[datetime, float]) -> None:
    hass.statistics[entity_id] = dict(by_day)


def _activate(coordinator: Any) -> None:
    ok = coordinator.pin_diagnostic_slot(_PIN)
    assert ok
    coordinator.set_active_diagnostic_mode("compare_regressions")


def _sensor(result: Any, sensor_id: str) -> Any:
    matches = [s for s in result.sensors if s.sensor_id == sensor_id]
    assert len(matches) == 1, f"expected exactly one {sensor_id!r} entry, found {len(matches)}"
    return matches[0]


class TestSensorIdsDeclaredWithoutComputing:
    """`sensor_ids()` (ADR-004 §5, fifth Amendment) must be resolvable
    cheaply — no recorder fetch, no fitting — so `sensor.py` can call it
    at platform-setup time, before any mode is necessarily active."""

    def test_one_id_per_string_plus_sum(self) -> None:
        coordinator, _hass = _make_two_string_setup()
        mode = coordinator.diagnostic_mode.__self__._diagnostic_modes["compare_regressions"]

        ids = mode.sensor_ids()

        assert ids == [
            ("0", "Dach Süd Diagnostics"),
            ("1", "Dach Nord Diagnostics"),
            ("sum", "Diagnostics Sum"),
        ]

    def test_matches_coordinator_diagnostic_sensor_ids(self) -> None:
        coordinator, _hass = _make_two_string_setup()
        assert coordinator.diagnostic_sensor_ids() == [
            ("0", "Dach Süd Diagnostics"),
            ("1", "Dach Nord Diagnostics"),
            ("sum", "Diagnostics Sum"),
        ]


class TestSumEntryDayAlignment:
    """The core correctness fix (ADR-004 §5, fifth Amendment): the
    `"sum"` entry must align strings by *calendar day*, not by position
    in each string's own already-gap-filtered display list — verified
    here with two strings whose actual-yield history has genuinely
    different gap patterns (string 0 has all 3 days, string 1 is
    missing the earliest one)."""

    def test_sum_keeps_a_day_only_one_string_has_data_for(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 500.0})
        # missing _DAY_0
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_1: 300.0, _DAY_2: 300.0})
        _activate(coordinator)

        result = coordinator.diagnostic_result()
        assert result is not None

        string_0 = _sensor(result, "0")
        assert string_0.attributes["series"] == [
            _xy_series_entry("0", [[500.0, 500.0], [500.0, 500.0], [500.0, 500.0]])
        ]

        string_1 = _sensor(result, "1")
        # Day 0 is filtered out of string 1's own display series — it has
        # nothing that day — leaving only the two days it actually has.
        assert string_1.attributes["series"] == [
            _xy_series_entry("0", [[500.0, 300.0], [500.0, 300.0]])
        ]

        summed = _sensor(result, "sum")
        # Three points, not two: day 0 is kept (string 0's FC and PV both
        # count, string 1 contributes nothing that day — not dropped, not
        # paired with the wrong calendar day the way summing the two
        # already-filtered lists above via position would have risked).
        assert summed.attributes["series"] == [
            _xy_series_entry(
                "0",
                [
                    # day 0: FC = 500(str0)+500(str1, always present) — PV = 500(str0 only)
                    [1000.0, 500.0],
                    [1000.0, 800.0],  # day 1: both strings present
                    [1000.0, 800.0],  # day 2 (== _PIN's own day): both strings present
                ],
            )
        ]

    def test_sum_matches_a_symmetric_gap_pattern_naively_too(self) -> None:
        """Sanity check the other direction: when both strings *do*
        share the same gap pattern (both missing the same day), the sum
        simply omits that day entirely — the non-buggy case a naive
        position-based zip() would also have gotten right, included here
        so the alignment test above is contrasted against a case that
        was never broken."""
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_1: 500.0, _DAY_2: 500.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_1: 300.0, _DAY_2: 300.0})
        _activate(coordinator)

        result = coordinator.diagnostic_result()
        assert result is not None
        summed = _sensor(result, "sum")
        assert summed.attributes["series"] == [
            _xy_series_entry("0", [[1000.0, 800.0], [1000.0, 800.0]])
        ]


class TestSumEntryUnavailableWhenNothingContributes:
    """Mirrors `_compute_sensor`'s own "no baseline configured"
    placeholder (ADR-004 §5, fifth Amendment) — same contract, same
    reason, when *no* string has anything to contribute."""

    def test_state_is_unavailable_when_no_string_has_a_baseline(self) -> None:
        coordinator, _hass = _make_two_string_setup()
        # both strings fall back to this; now neither resolves
        coordinator._global_baseline_entity_id = None
        _activate(coordinator)

        result = coordinator.diagnostic_result()
        assert result is not None
        summed = _sensor(result, "sum")
        assert summed.state == "unavailable"
        assert summed.attributes == {}

    def test_extra_fit_returns_none_and_caches_nothing(self) -> None:
        """The `extra_fit()` counterpart to the test above: every
        configured string's `config.baseline_entity_id` resolves to
        `None`, so `extra_fit()`'s per-string loop `continue`s every
        iteration without ever populating `by_sensor` — previously
        untested, since every other test in this file either bypasses
        `extra_fit()` entirely (seeding `cache.set_diagnostic_fit`
        directly) or has at least one string that *does* resolve a
        baseline."""
        coordinator, _hass = _make_two_string_setup()
        coordinator._global_baseline_entity_id = None
        _activate(coordinator)

        coordinator._diagnostics_tick_sync(_PIN)

        assert coordinator.cache.diagnostic_fit("0") is None
        assert coordinator.cache.diagnostic_fit("1") is None


class TestSelectedAggregatesSummedIndependently:
    """The "selected slot" accuracy path (ADR-004 §2b/§5): `predictions`
    is summed only over strings with a cached prediction, while
    `fc_selected`/`pv_selected` sum every contributing string regardless
    — confirmed, deliberate, kept as-is (2026-09-03 review) rather than
    an oversight. Bypasses real regression fitting by seeding
    `cache.set_diagnostic_fit` directly for the one string meant to have
    a prediction, matching `_compute_sensor`'s own read path
    (`cache.diagnostic_fit(sensor_id)`)."""

    def test_actual_totals_include_a_string_with_no_cached_prediction(self) -> None:
        coordinator, hass = _make_two_string_setup()
        # Both strings have full history through the pinned slot itself,
        # so `diagnosed.is_elapsed` finds a real `pv_selected` for each.
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 480.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 50.0})
        # "Now" is after the pinned slot, so it counts as elapsed.
        coordinator._now = lambda: _PIN + timedelta(minutes=10)
        ok = coordinator.pin_diagnostic_slot(_PIN, now=_PIN + timedelta(minutes=10))
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")

        # Only string "0" has a cached prediction — string "1"'s fit
        # cache is left empty, e.g. because `extra_fit()` hasn't fit it
        # yet (a freshly added string, or a fit failure).
        coordinator.cache.set_diagnostic_fit("0", {"method_x": 500.0})

        result = coordinator.diagnostic_result()
        assert result is not None
        summed = _sensor(result, "sum")

        # fc_selected/pv_selected: both strings counted (1000 / 530).
        # predictions: only string "0" (500 for "method_x") — string "1"
        # contributes nothing to the numerator despite contributing 50 to
        # the actual/denominator side, the confirmed-and-kept asymmetry.
        expected_accuracy = diagnostic_accuracy(500.0, 530.0)
        selected_series = [
            entry for entry in summed.attributes["series"] if entry["name"].startswith("selected")
        ]
        assert _xy_series_entry("selected actual", [[1000.0, 530.0]]) in selected_series
        assert any(
            entry["name"].startswith("selected method_x")
            and entry["x"] == [1000.0]
            and entry["y"] == [500.0]
            for entry in selected_series
        )
        assert summed.attributes["accuracy"] == {"method_x": expected_accuracy}


class TestExtraFitAcrossAllRegressionStrategies:
    """`extra_fit()` (ADR-004 §2/§4) is only ever driven through
    `_diagnostics_tick_sync`, the coordinator's own 5-minute tick
    (ADR-004 §4) — no earlier test in this file calls it, since every
    scenario above bypasses real fitting by seeding `cache.set_
    diagnostic_fit` directly instead. Reuses `test_coordinator.py`'s
    weather-tier temperature-aware fixture (`_make_temperature_aware_
    coordinator`) so this same call also exercises `_gather_pool`'s and
    `_predict_all_methods`'s temperature branches (previously
    completely uncovered — `config.temperature_entity_id` was never
    non-`None` in any prior test in this file), not just the
    untempered path."""

    def test_extra_fit_populates_a_prediction_per_regression_strategy(self) -> None:
        coordinator, _hass = tc._make_temperature_aware_coordinator()
        ok = coordinator.pin_diagnostic_slot(tc._NOW)
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")

        coordinator._diagnostics_tick_sync(tc._NOW)

        predictions = coordinator.cache.diagnostic_fit("0")
        assert predictions is not None
        assert set(predictions) == set(_string_computation_mod.REGRESSION_STRATEGIES)

        # The same tick's `compute()` (both cadences are "slot") reads
        # this prediction straight back — and `_predict_all_methods`
        # only reaches its `target_cell_temperature` branch at all
        # when `coordinator.target_cell_temperature_for_slot` itself
        # resolves to a real value, not `None` — confirmed directly
        # here, since a `None` target would still silently produce *a*
        # prediction without proving the temperature branch actually
        # fed anything through.
        diagnosed = coordinator.diagnosed_slot()
        assert diagnosed is not None
        assert coordinator.target_cell_temperature_for_slot(0, diagnosed.index) is not None

    def test_temperature_tier_predicts_without_adjustment_when_unresolved(self) -> None:
        """The `resolved is not None` branch's counterpart: a
        temperature-tier string (`config.temperature_tier is not
        None`) whose `target_cell_temperature_for_slot` itself comes
        back `None` must still predict -- just without a `target_cell_
        temperature` array fed into `fit_string_model`/`predict` -- not
        raise. `fc_selected` itself must still resolve normally here
        (unlike the sibling tests above), or `extra_fit()`'s earlier
        `fc_selected is None` skip would prevent this call from ever
        reaching the branch under test at all -- hence a direct
        monkeypatch of `target_cell_temperature_for_slot` alone, rather
        than reusing one of `TestTargetCellTemperatureForSlotEdgeCases`'
        own real-data setups (`coordinator.py`, `tests/test_
        coordinator.py`), every one of which also happens to starve
        `fc_selected` of the same underlying baseline data."""
        coordinator, _hass = tc._make_temperature_aware_coordinator()
        coordinator.target_cell_temperature_for_slot = lambda *args, **kwargs: None
        ok = coordinator.pin_diagnostic_slot(tc._NOW)
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")

        coordinator._diagnostics_tick_sync(tc._NOW)  # must not raise

        predictions = coordinator.cache.diagnostic_fit("0")
        assert predictions is not None
        assert set(predictions) == set(_string_computation_mod.REGRESSION_STRATEGIES)


class TestSelectedValuePassesAllowHistoricalBackfill:
    """`_selected_value` must opt into `cache.get_time_range`'s
    `allow_historical_backfill` (ADR-007a §4 Amendment, TASK-0037
    follow-up) — without it, a `forecast_solar`-shaped (push-sourced)
    baseline's already-elapsed history is never fetched by *any*
    caller at all: `get_regression_pools`'s own opt-in (ADR-008 §2)
    never reaches "today", so a push-sourced `config.baseline_entity_id`
    would have had no way to resolve `FC_selected` for the diagnosed
    slot — permanently `None`, and therefore no `"selected ..."` series
    entry and an empty `accuracy` dict, exactly the reported symptom.
    A lightweight fake `cache`/coordinator rather than a full
    `ShadyCoordinator` — this is about *which keyword argument*
    `_selected_value` passes through, not about resolving a real
    push-sourced series end-to-end (`TestGetTimeRangeThreadsAllowHisto
    ricalBackfill`, `tests/test_cache_core.py`, already covers that)."""

    def test_get_time_range_receives_the_flag(self) -> None:
        calls: list[dict[str, Any]] = []

        class _FakeCache:
            def timestamp_for(self, index: int) -> datetime:
                return _PIN

            def get_time_range(
                self, sensor_ids: list[str], start: datetime, end: datetime, **kwargs: Any
            ) -> dict[str, list[Any]]:
                calls.append(kwargs)
                return {sensor_ids[0]: [123.0]}

        class _FakeCoordinator:
            cache = _FakeCache()

        mode = _CompareRegressionsMode(_FakeCoordinator())

        result = mode._selected_value("fs_entry_1", 0)

        assert result == 123.0
        assert len(calls) == 1
        assert calls[0]["allow_historical_backfill"] is True


class TestExtraFitPerStringIsolation:
    """One string's fit failure must not prevent every other string's
    predictions from being cached the same tick — mirrors
    `_refit_sync`'s own "leaving it unmodeled, not aborting the
    remaining strings" per-string isolation (`coordinator.py`), applied
    here to `extra_fit()`'s own per-string loop (ADR-000 §8, TASK-0037
    follow-up). Before this, one string raising inside `extra_fit()`
    (e.g. a transient data hiccup) blew up the whole call, uncaught —
    no other string's prediction got cached that tick either."""

    def test_one_string_raising_does_not_block_the_other(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 500.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 300.0})
        _activate(coordinator)
        mode = coordinator.diagnostic_mode()
        assert mode is not None
        original_predict = mode._predict_all_methods

        def _raise_for_string_0(string_index: int, *args: Any, **kwargs: Any) -> Any:
            if string_index == 0:
                raise RuntimeError("boom")
            return original_predict(string_index, *args, **kwargs)

        mode._predict_all_methods = _raise_for_string_0

        coordinator._diagnostics_tick_sync(_PIN)  # must not raise

        assert coordinator.cache.diagnostic_fit("0") is None
        assert coordinator.cache.diagnostic_fit("1") is not None


class TestExtraFitSkipsStringWhenSelectedValueUnresolved:
    """`extra_fit()`'s other per-string skip (distinct from `config.
    baseline_entity_id is None`, already covered by `TestSumEntry
    UnavailableWhenNothingContributes.test_extra_fit_returns_none_and_
    caches_nothing`): a string *with* a resolved `baseline_entity_id`
    whose `_selected_value` still comes back `None` for the diagnosed
    slot -- a genuinely reachable state (e.g. brand-new install, not a
    single slot fetched/pushed yet) -- must `continue` gracefully, not
    raise, and must not block any other string's own fit the same tick
    (same per-string isolation as `TestExtraFitPerStringIsolation`
    above, different trigger)."""

    def test_string_with_unresolved_fc_selected_is_skipped_not_raised(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 500.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 300.0})
        _activate(coordinator)
        mode = coordinator.diagnostic_mode()
        assert mode is not None
        original_selected_value = mode._selected_value
        calls = {"n": 0}

        def _none_on_first_call(entity_id: str, index: int) -> Any:
            # `self._coordinator.strings()` is dict-ordered (string "0"
            # first) and `extra_fit()`'s loop calls `_selected_value`
            # at most once per string, so the first call is always
            # string "0"'s own -- deterministic, not order-fragile.
            calls["n"] += 1
            if calls["n"] == 1:
                return None
            return original_selected_value(entity_id, index)

        mode._selected_value = _none_on_first_call

        coordinator._diagnostics_tick_sync(_PIN)  # must not raise

        assert coordinator.cache.diagnostic_fit("0") is None
        assert coordinator.cache.diagnostic_fit("1") is not None


class TestAppendSelectedSeriesEmptyWhenForecastUnresolved:
    """`_append_selected_series`'s own guard (distinct from every
    scenario above, all of which resolve a real `fc_selected`): when
    `fc_selected` itself is `None` -- a resolved `baseline_entity_id`
    whose `_selected_value` still can't produce a number for the
    diagnosed slot -- it returns immediately, appending *nothing* to
    `series` (not even a pool-less "selected {method}" placeholder) and
    `accuracy` stays `{}`. This was the original `TASK-0037` report's
    own failure mode end-to-end, before any of its three patches;
    confirmed here to still degrade gracefully rather than raise now
    that all three have landed."""

    def test_no_selected_entries_and_empty_accuracy(self) -> None:
        coordinator, _hass = tc._make_coordinator()
        coordinator._now = lambda: _PIN
        _activate(coordinator)
        mode = coordinator.diagnostic_mode()
        assert mode is not None
        mode._selected_value = lambda entity_id, index: None

        coordinator.cache.set_diagnostic_fit("0", {"method_x": 500.0})
        result = coordinator.diagnostic_result()
        assert result is not None
        string_0 = _sensor(result, "0")

        assert not any(
            entry["name"].startswith("selected") for entry in string_0.attributes["series"]
        )
        assert string_0.attributes["accuracy"] == {}


class TestFuturePinnedSlotOmitsSelectedActual:
    """Given a future-pinned slot (ADR-004 §2/§2a), When rendered, Then
    `"selected {method}"` entries still appear (evaluated against the
    forward-looking `FC`), but `"selected actual"` is omitted from
    `series` and `accuracy` is an empty `{}` — there is nothing to
    compare a future forecast against yet."""

    def test_selected_method_appears_without_selected_actual_or_accuracy(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 480.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 50.0})
        # `coordinator._now` stays at `_PIN` (the fixture's own default);
        # pinning a few hours later than that same "now" is what makes
        # `diagnosed.is_elapsed` false, regardless of any actual-yield
        # data existing for that day.
        future_pin = _PIN + timedelta(hours=3)
        ok = coordinator.pin_diagnostic_slot(future_pin)
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")
        # Bypasses real regression fitting, same convention as
        # `TestSelectedAggregatesSummedIndependently` above.
        coordinator.cache.set_diagnostic_fit("0", {"method_x": 500.0})

        result = coordinator.diagnostic_result()
        assert result is not None
        string_0 = _sensor(result, "0")

        selected_series = [
            entry for entry in string_0.attributes["series"] if entry["name"].startswith("selected")
        ]
        assert any(entry["name"].startswith("selected method_x") for entry in selected_series)
        assert not any(entry["name"] == "selected actual" for entry in selected_series)
        assert string_0.attributes["accuracy"] == {}


class TestFuturePinnedSlotSelectedResolvesOffHourAlignment:
    """Live bug report (`TASK-0037-patch-3`): the `\"selected {method}\"`
    series only ever appeared when the diagnosed slot happened to land on
    minute 0. Root cause was in `_push_provider_series` (`coordinator.py`,
    ADR-012 §4 Amendment) — it pushed a `forward()` series straight into
    `cache.py` with a 1:1 timestamp match instead of forward-filling it,
    so a coarser-than-5-minute source (`forecast_solar`/weather-shaped —
    always hourly, ADR-009 §1a) only ever populated the exact slot each
    raw sample happened to land on, leaving `FC_selected` permanently
    `None` everywhere else. A future pin (as in
    `TestFuturePinnedSlotOmitsSelectedActual` above) is the cleanest way
    to isolate this: `_selected_value` has no recorder-backed fallback
    for a not-yet-elapsed slot, so it depends entirely on the pushed
    series, with nothing else able to mask the bug.

    Fails against the pre-fix `_push_provider_series`: pinning to a
    quarter past the hour, against an hourly-only `forward()` series,
    would leave `\"selected method_x\"` absent from `series` entirely
    (the same absence `TASK-0037`'s own original report described).
    """

    def test_selected_method_appears_for_a_quarter_past_the_hour_pin(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 480.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 50.0})

        # Simulate an hourly-resolution baseline source: `forward()`
        # only ever reports exactly on the hour, same as a real
        # `forecast_solar`/weather-shaped provider (ADR-009 §1a).
        provider = coordinator._entity_providers[tc._BASELINE_ENTITY]
        hourly_series = [(_PIN + timedelta(hours=h), 500.0) for h in range(5)]
        provider.forward = lambda now: hourly_series
        coordinator._push_provider_series(tc._BASELINE_ENTITY, _PIN)

        # A quarter past the hour, still within the pushed horizon --
        # never itself one of `hourly_series`'s own timestamps.
        off_hour_pin = _PIN + timedelta(hours=3, minutes=25)
        ok = coordinator.pin_diagnostic_slot(off_hour_pin)
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.cache.set_diagnostic_fit("0", {"method_x": 500.0})

        result = coordinator.diagnostic_result()
        assert result is not None
        string_0 = _sensor(result, "0")

        selected_series = [
            entry for entry in string_0.attributes["series"] if entry["name"].startswith("selected")
        ]
        assert any(entry["name"].startswith("selected method_x") for entry in selected_series)


class TestExportCsvUnsupportedSensorIds:
    """Given a sensor_id that isn't a real configured string — including
    `"sum"` (ADR-015 §2, TASK-0038's own 2026-09-27 implementation
    decision: the pointwise-summed pseudo-string has no single coherent
    per-string temperature_tier/config the `# metadata` schema could
    represent) — When export_csv is called, Then it returns None, the
    same "nothing to export" contract http_export.py reports as
    HTTPStatus.NOT_FOUND for."""

    def test_sum_is_not_exportable(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 500.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 300.0})
        _activate(coordinator)
        mode = coordinator.diagnostic_mode()
        assert mode is not None

        assert mode.export_csv("sum") is None

    def test_unrecognized_sensor_id_returns_none(self) -> None:
        coordinator, _hass = _make_two_string_setup()
        _activate(coordinator)
        mode = coordinator.diagnostic_mode()
        assert mode is not None

        assert mode.export_csv("5") is None
        assert mode.export_csv("not-a-number") is None

    def test_string_with_no_baseline_returns_none(self) -> None:
        coordinator, _hass = _make_two_string_setup()
        coordinator._global_baseline_entity_id = None
        _activate(coordinator)
        mode = coordinator.diagnostic_mode()
        assert mode is not None

        assert mode.export_csv("0") is None


class TestExportCsvShapeAndWeightDecomposition:
    """Given a diagnosed slot with a resolved baseline, When export_csv
    is called for one of its strings, Then the returned CSV has the
    leading `# diagnostic_mode` section plus the four content sections,
    and every `training_pool` row's `combined_weight` equals
    `magnitude_weight * time_weight * recency_weight *
    (not neighbor_excluded) * is_valid` exactly — the pre-exclusion
    `magnitude_weight` decomposition ADR-015 §6 clarifies (`TASK-0038`)."""

    def test_sections_present_and_ordered(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 500.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 300.0})
        coordinator._now = lambda: _PIN + timedelta(minutes=10)
        ok = coordinator.pin_diagnostic_slot(_PIN, now=_PIN + timedelta(minutes=10))
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")
        mode = coordinator.diagnostic_mode()
        assert mode is not None

        text = mode.export_csv("0")
        assert text is not None

        sections = parse_csv_sections(text, source="test")
        assert list(sections) == [
            "diagnostic_mode",
            "metadata",
            "training_pool",
            "predictions",
            "prediction_inputs",
        ]
        assert sections["diagnostic_mode"] == [{"diagnostic_mode": "compare_regressions"}]
        assert len(sections["metadata"]) == 1
        assert sections["metadata"][0]["string_index"] == "0"
        assert sections["metadata"][0]["string_name"] == "Dach Süd"
        # smoothing_radius=0 (`_make_two_string_setup`'s own config) ->
        # exactly one offset ("0"), window_days=3 rows.
        assert len(sections["training_pool"]) == _WINDOW_DAYS

    def test_combined_weight_reconstructs_from_its_own_factors(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 500.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 300.0})
        coordinator._now = lambda: _PIN + timedelta(minutes=10)
        ok = coordinator.pin_diagnostic_slot(_PIN, now=_PIN + timedelta(minutes=10))
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")
        mode = coordinator.diagnostic_mode()
        assert mode is not None

        text = mode.export_csv("0")
        assert text is not None
        sections = parse_csv_sections(text, source="test")

        assert len(sections["training_pool"]) > 0
        for row in sections["training_pool"]:
            magnitude_weight = float(row["magnitude_weight"])
            time_weight = float(row["time_weight"])
            recency_weight = float(row["recency_weight"])
            neighbor_excluded = row["neighbor_excluded"] == "1"
            is_valid = row["is_valid"] == "1"
            combined_weight = float(row["combined_weight"])
            expected = (
                magnitude_weight
                * time_weight
                * recency_weight
                * (0.0 if neighbor_excluded else 1.0)
                * (1.0 if is_valid else 0.0)
            )
            assert math.isclose(combined_weight, expected, rel_tol=1e-9, abs_tol=1e-12)


class TestExportCsvNotYetElapsedBlanksSelectedFields:
    """Given a not-yet-elapsed (future-pinned) diagnosed slot, When
    export_csv is called, Then `predictions`' `pv_selected`/`accuracy`
    and `prediction_inputs`' `pv_selected` are blank rather than
    fabricated — the export mirrors `_append_selected_series`'s own
    contract, not an approximation of it."""

    def test_pv_selected_and_accuracy_blank_for_future_pin(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 480.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 50.0})
        future_pin = _PIN + timedelta(hours=3)
        ok = coordinator.pin_diagnostic_slot(future_pin)
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.cache.set_diagnostic_fit("0", {"linear": 500.0})
        mode = coordinator.diagnostic_mode()
        assert mode is not None

        text = mode.export_csv("0")
        assert text is not None
        sections = parse_csv_sections(text, source="test")

        prediction_row = next(row for row in sections["predictions"] if row["method"] == "linear")
        assert prediction_row["predicted"] == repr(500.0)
        assert prediction_row["pv_selected"] == ""
        assert prediction_row["accuracy"] == ""

        pv_selected_row = next(
            row for row in sections["prediction_inputs"] if row["key"] == "pv_selected"
        )
        assert pv_selected_row["value"] == ""


class TestExportReplayRoundTrip:
    """Given a real export from a live coordinator, When it is parsed and
    replayed through `_replay_compare_regressions` (the function the
    generic fixture runner dispatches to), Then the regenerated CSV
    matches the original section by section — the only end-to-end proof
    the replay function reconstructs `export_csv`'s inputs faithfully,
    since no curated golden fixtures exist yet (they are added by the
    maintainer afterward, ADR-015 §5). Covers both a plain string and a
    weather-tier one (the `temperature_raw`/`target_cell_temperature`
    branches)."""

    @staticmethod
    def _round_trip(coordinator: Any, sensor_id: str) -> list[str]:
        mode = coordinator.diagnostic_mode()
        assert mode is not None
        original_text = mode.export_csv(sensor_id)
        assert original_text is not None
        original = parse_csv_sections(original_text, source="original")
        regenerated = parse_csv_sections(
            _replay_compare_regressions(original), source="regenerated"
        )
        return compare_sections(original, regenerated)

    def test_plain_string_round_trips(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 480.0, _DAY_2: 510.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 290.0, _DAY_2: 310.0})
        coordinator._now = lambda: _PIN + timedelta(minutes=10)
        assert coordinator.pin_diagnostic_slot(_PIN, now=_PIN + timedelta(minutes=10))
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator._diagnostics_tick_sync(_PIN + timedelta(minutes=10))

        assert self._round_trip(coordinator, "0") == []

    def test_weather_tier_string_round_trips(self) -> None:
        coordinator, _hass = tc._make_temperature_aware_coordinator()
        assert coordinator.pin_diagnostic_slot(tc._NOW)
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator._diagnostics_tick_sync(tc._NOW)

        mode = coordinator.diagnostic_mode()
        assert mode is not None
        text = mode.export_csv("0")
        assert text is not None
        sections = parse_csv_sections(text, source="original")
        assert sections["metadata"][0]["temperature_tier"] == "weather"
        assert any(row["key"] == "target_cell_temperature" for row in sections["prediction_inputs"])

        assert self._round_trip(coordinator, "0") == []

    def test_round_trip_detects_a_tampered_fixture(self) -> None:
        """The comparison has teeth: changing one recorded weight in a
        fixture makes the regenerated CSV disagree with it."""
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 480.0, _DAY_2: 510.0})
        coordinator._now = lambda: _PIN + timedelta(minutes=10)
        assert coordinator.pin_diagnostic_slot(_PIN, now=_PIN + timedelta(minutes=10))
        coordinator.set_active_diagnostic_mode("compare_regressions")
        mode = coordinator.diagnostic_mode()
        assert mode is not None
        text = mode.export_csv("0")
        assert text is not None
        original = parse_csv_sections(text, source="original")
        original["training_pool"][0]["combined_weight"] = "123.0"

        regenerated = parse_csv_sections(_replay_compare_regressions(original), source="regen")

        assert compare_sections(original, regenerated) != []


def _parse_or_none(value: str) -> float | None:
    return float(value) if value != "" else None


def _to_nan_array(values: list[float | None]) -> NDArray[np.float64]:
    return np.array([v if v is not None else np.nan for v in values], dtype=np.float64)


def _replay_compare_regressions(sections: dict[str, list[dict[str, str]]]) -> str:
    """ADR-015 §5's one mode-owned fixture-replay function
    (`_replay_compare_regressions`, 2026-09-27 Amendment: `sections` is
    now a `dict`, looked up by name — `tests/csv_fixture_support.py`).
    Reconstructs `CompareRegressionsMode.export_csv`'s real typed
    inputs from a parsed fixture, calls the real `export_csv`, and
    returns the fresh CSV text it produces — imported by
    `tests/diagnostics/test_csv_regression_fixtures.py`'s generic
    runner, registered there under this mode's own key.

    `apply_training_corrections`'s own correction parameters
    (`converter_limit_w`/`coefficient_per_c`/`provider_already_corrects`/
    `rated_dc_capacity_wp`) aren't part of the `# metadata` schema (only
    `temperature_tier` is) — recomputing `pv_corrected` from `pv_raw`
    would need config this replay doesn't have. Instead,
    `string_computation.apply_training_corrections` is monkeypatched
    for the duration of this one call to return the fixture's own
    recorded `pv_corrected` values directly, bypassing recomputation —
    the correction *logic* is `string_computation.py`'s own
    zero-mocking test concern (`tests/test_string_computation.py`), not
    this fixture's.
    """
    metadata = sections["metadata"][0]
    string_index = int(metadata["string_index"])
    string_name = metadata["string_name"]
    window_days = int(metadata["window_days"])
    smoothing_radius = int(metadata["smoothing_radius"])
    temperature_tier = metadata["temperature_tier"] or None
    slot_of_day = int(metadata["slot_of_day"])
    diagnosed_index = int(metadata["diagnosed_index"])
    is_pinned = metadata["is_pinned"] == "true"
    is_elapsed = metadata["is_elapsed"] == "true"
    diagnosed_at = datetime.fromisoformat(metadata["diagnosed_at"])

    offsets = list(range(-smoothing_radius, smoothing_radius + 1))
    slot_to_offset = {(slot_of_day + offset) % _SLOTS_PER_DAY: offset for offset in offsets}

    fc_by_offset: dict[int, list[float | None]] = {
        offset: [None] * window_days for offset in offsets
    }
    pv_raw_by_offset: dict[int, list[float | None]] = {
        offset: [None] * window_days for offset in offsets
    }
    pv_corrected_by_offset: dict[int, list[float | None]] = {
        offset: [None] * window_days for offset in offsets
    }
    temperature_by_offset: dict[int, list[float | None]] | None = (
        {offset: [None] * window_days for offset in offsets}
        if temperature_tier is not None
        else None
    )
    for row in sections["training_pool"]:
        offset = int(row["offset"])
        day_index = int(row["day_index"])
        fc_by_offset[offset][day_index] = _parse_or_none(row["fc_raw"])
        pv_raw_by_offset[offset][day_index] = _parse_or_none(row["pv_raw"])
        pv_corrected_by_offset[offset][day_index] = _parse_or_none(row["pv_corrected"])
        if temperature_by_offset is not None:
            temperature_by_offset[offset][day_index] = _parse_or_none(row["temperature_raw"])

    prediction_inputs = {row["key"]: row["value"] for row in sections["prediction_inputs"]}
    fc_selected = _parse_or_none(prediction_inputs.get("fc_selected", ""))
    pv_selected = _parse_or_none(prediction_inputs.get("pv_selected", ""))
    target_cell_temperature = _parse_or_none(prediction_inputs.get("target_cell_temperature", ""))
    predictions = {row["method"]: float(row["predicted"]) for row in sections["predictions"]}

    baseline_entity_id = "replay_baseline"
    actual_yield_entity_id = "replay_actual_yield"
    temperature_entity_id = "replay_temperature" if temperature_tier is not None else None

    class _ReplayCache:
        def timestamp_for(self, index: int) -> datetime:
            return diagnosed_at

        def get_pinned_slot_pool(
            self, sensor_ids: list[str], offset_slot: int, **kwargs: Any
        ) -> dict[str, list[float | None]]:
            offset = slot_to_offset[offset_slot]
            raw: dict[str, list[float | None]] = {
                baseline_entity_id: fc_by_offset[offset],
                actual_yield_entity_id: pv_raw_by_offset[offset],
            }
            if temperature_entity_id is not None:
                assert temperature_by_offset is not None
                raw[temperature_entity_id] = temperature_by_offset[offset]
            return raw

        def get_time_range(
            self, sensor_ids: list[str], start: datetime, end: datetime, **kwargs: Any
        ) -> dict[str, list[float | None]]:
            sensor_id = sensor_ids[0]
            if sensor_id == baseline_entity_id:
                return {sensor_id: [fc_selected]}
            if sensor_id == actual_yield_entity_id:
                return {sensor_id: [pv_selected]}
            return {sensor_id: [None]}

        def diagnostic_fit(self, sensor_id: str) -> dict[str, float] | None:
            return predictions or None

    class _ReplayCoordinator:
        cache = _ReplayCache()

        def strings(self) -> list[tuple[int, str]]:
            return [(string_index, string_name)]

        def string_computation_config(self, index: int) -> Any:
            return _coordinator_like_mod.StringComputationConfig(
                baseline_entity_id=baseline_entity_id,
                actual_yield_entity_id=actual_yield_entity_id,
                temperature_entity_id=temperature_entity_id,
                temperature_tier=temperature_tier,
                converter_limit_w=None,
                coefficient_per_c=0.0,
                provider_already_corrects=False,
                rated_dc_capacity_wp=None,
            )

        def diagnosed_slot(self, now: datetime | None = None) -> Any:
            return _coordinator_like_mod.DiagnosedSlot(
                index=diagnosed_index, slot_of_day=slot_of_day, is_elapsed=is_elapsed
            )

        def regression_settings(self) -> Any:
            return _coordinator_like_mod.RegressionSettings(
                smoothing_radius=smoothing_radius,
                neighbor_fitting_cutoff=float(metadata["neighbor_fitting_cutoff"]),
                recency_decay_max=float(metadata["recency_decay_max"]),
                clipping_threshold=float(metadata["clipping_threshold"]),
                max_uplift_c=float(metadata["max_uplift_c"]),
            )

        def configured_regression_method(self) -> str:
            return metadata["regression_method_configured"]

        def pinned_diagnostic_slot(self) -> datetime | None:
            return diagnosed_at if is_pinned else None

        def now(self) -> datetime:
            return diagnosed_at

        def target_cell_temperature_for_slot(self, index: int, slot_index: int) -> float | None:
            return target_cell_temperature

    def _passthrough_corrections(*_args: Any, **_kwargs: Any) -> dict[int, NDArray[np.float64]]:
        return {
            offset: _to_nan_array(pv_corrected_by_offset[offset])[None, :] for offset in offsets
        }

    original_corrections = _string_computation_mod.apply_training_corrections
    _string_computation_mod.apply_training_corrections = _passthrough_corrections
    try:
        mode = _CompareRegressionsMode(_ReplayCoordinator())
        result = mode.export_csv(str(string_index))
    finally:
        _string_computation_mod.apply_training_corrections = original_corrections

    assert isinstance(result, str)
    return result
