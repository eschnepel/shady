"""Tests for `diagnostics/compare_regressions.py`'s `CompareRegressionsMode`
(ADR-004 §2/§2a/§2b/§3/§4/§5, TASK-0015b).

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

import sys
from datetime import UTC, datetime, timedelta
from typing import Any

from tests import test_coordinator as tc

# `test_coordinator.py`'s own harness already file-path-loaded
# `aggregation.py` into `sys.modules["shady.aggregation"]` — reuse that
# loaded module rather than a real package import (`custom_components.
# shady.aggregation` isn't on any import path this harness sets up).
_aggregation_mod = sys.modules["shady.aggregation"]
diagnostic_accuracy = _aggregation_mod.diagnostic_accuracy

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
    hass = tc.FakeHomeAssistant()
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
            {"name": "0", "data": [[500.0, 500.0], [500.0, 500.0], [500.0, 500.0]]}
        ]

        string_1 = _sensor(result, "1")
        # Day 0 is filtered out of string 1's own display series — it has
        # nothing that day — leaving only the two days it actually has.
        assert string_1.attributes["series"] == [
            {"name": "0", "data": [[500.0, 300.0], [500.0, 300.0]]}
        ]

        summed = _sensor(result, "sum")
        # Three points, not two: day 0 is kept (string 0's FC and PV both
        # count, string 1 contributes nothing that day — not dropped, not
        # paired with the wrong calendar day the way summing the two
        # already-filtered lists above via position would have risked).
        assert summed.attributes["series"] == [
            {
                "name": "0",
                "data": [
                    # day 0: FC = 500(str0)+500(str1, always present) — PV = 500(str0 only)
                    [1000.0, 500.0],
                    [1000.0, 800.0],  # day 1: both strings present
                    [1000.0, 800.0],  # day 2 (== _PIN's own day): both strings present
                ],
            }
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
            {"name": "0", "data": [[1000.0, 800.0], [1000.0, 800.0]]}
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
        assert {"name": "selected actual", "data": [[1000.0, 530.0]]} in selected_series
        assert any(
            entry["name"].startswith("selected method_x") and entry["data"] == [[1000.0, 500.0]]
            for entry in selected_series
        )
        assert summed.attributes["accuracy"] == {"method_x": expected_accuracy}


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
