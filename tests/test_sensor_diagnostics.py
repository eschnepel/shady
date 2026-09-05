"""Tests for `sensor.py`'s `ShadyDiagnosticsSensor` (ADR-004 §5, fifth
Amendment, 2026-09-03, TASK-0015b).

Reuses `test_sensor_forecast.py`'s already-executed HA-stub/module-load
harness wholesale (`ShadyCoordinator`, `_sensor_mod`, `FakeHomeAssistant`,
`_make_ready_coordinator`, ...) rather than re-registering the same
`homeassistant.*` stand-ins a second time — the same "reuse, don't
reimplement" convention `test_diagnostics_compare_regressions.py`
already applies to `test_coordinator.py`'s own harness.

`test_coordinator.py`'s `TestDiagnosticResultCaching` already proves
`coordinator.diagnostic_result()` itself caches a `DiagnosticMode`'s
`compute()` output, refreshed once per tick. What that suite does
*not* cover is `sensor.py`'s own lookup behaviour: whether
`ShadyDiagnosticsSensor` actually goes through that cached accessor on
every read, or reaches around it and calls `.compute()` directly (the
exact bug the fifth Amendment fixed). This file closes that gap by
substituting a call-counting `DiagnosticMode` and reading several
`ShadyDiagnosticsSensor` instances' `native_value`/
`extra_state_attributes` repeatedly, asserting the counted `compute()`
calls never move beyond whatever `coordinator.diagnostic_result()`
itself already produced.
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Any

from tests import test_sensor_forecast as tf

ShadyCoordinator = tf.ShadyCoordinator
ShadyDiagnosticsSensor = tf._sensor_mod.ShadyDiagnosticsSensor
_make_ready_coordinator = tf._make_ready_coordinator
_diagnostics_base_mod = sys.modules["shady.diagnostics.base"]

# TYPE_CHECKING-only static import mirroring the runtime file-path load
# `test_sensor_forecast.py` already performed (ADR-000 §6) — gives mypy
# real types for these names, the same convention `test_diagnostics_base
# .py`/`test_coordinator.py` already establish, without reintroducing a
# package import here.
if TYPE_CHECKING:
    from shady.diagnostics.base import DiagnosticMode as DiagnosticMode  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticResult as DiagnosticResult  # noqa: PLC0414
    from shady.diagnostics.base import (
        DiagnosticSensorResult as DiagnosticSensorResult,  # noqa: PLC0414
    )
else:
    DiagnosticMode = _diagnostics_base_mod.DiagnosticMode
    DiagnosticResult = _diagnostics_base_mod.DiagnosticResult
    DiagnosticSensorResult = _diagnostics_base_mod.DiagnosticSensorResult


class _CountingDiagnosticMode(DiagnosticMode):
    """Mirrors `test_coordinator.py`'s own `_CountingDiagnosticMode`
    (same white-box-substitution convention, `coordinator.
    _diagnostic_modes`) — built against `test_sensor_forecast.py`'s own
    loaded `diagnostics/base.py` instance so it is a genuine subclass of
    the exact `DiagnosticMode` this file's `ShadyCoordinator` checks
    against, rather than a same-shape-but-different-module lookalike."""

    key = "compare_regressions"

    def __init__(self, coordinator: Any) -> None:
        super().__init__(coordinator)
        self.compute_calls = 0

    def fit_cadence(self) -> Any:
        return "slot"

    def compute_cadence(self) -> Any:
        return "slot"

    def sensor_ids(self) -> list[tuple[str, str]]:
        return [("0", "String 0"), ("1", "String 1")]

    def compute(self) -> Any:
        self.compute_calls += 1
        return DiagnosticResult(
            sensors=[
                DiagnosticSensorResult(
                    sensor_id="0", state="ok", attributes={"n": self.compute_calls}
                ),
                # "1" deliberately omitted -> exercises the "declared but
                # not present in this compute() output" unavailable path.
            ]
        )


def _make_setup() -> tuple[Any, _CountingDiagnosticMode]:
    coordinator, _hass, _entry = _make_ready_coordinator()
    fake_mode = _CountingDiagnosticMode(coordinator)
    coordinator._diagnostic_modes["compare_regressions"] = fake_mode
    return coordinator, fake_mode


class TestDiagnosticsSensorNeverCallsComputeItself:
    """Given several `ShadyDiagnosticsSensor` instances sharing one
    coordinator, When their `native_value`/`extra_state_attributes` are
    read repeatedly, Then the active mode's `compute()` is never called
    by the sensors themselves — only `coordinator.diagnostic_result()`
    is (ADR-004 §5, fifth Amendment)."""

    def test_many_reads_across_many_sensors_add_no_compute_calls(self) -> None:
        coordinator, fake_mode = _make_setup()
        coordinator.set_active_diagnostic_mode("compare_regressions")

        # One explicit read establishes the tick-cached baseline, the
        # same way a real poll cycle would.
        assert coordinator.diagnostic_result() is not None
        assert fake_mode.compute_calls == 1

        sensor_0 = ShadyDiagnosticsSensor(coordinator, tf._make_entry(), "0", "String 0")
        sensor_1 = ShadyDiagnosticsSensor(coordinator, tf._make_entry(), "1", "String 1")

        for _ in range(5):
            _ = sensor_0.native_value
            _ = sensor_0.extra_state_attributes
            _ = sensor_1.native_value
            _ = sensor_1.extra_state_attributes

        # Ten additional reads across two sensors — still exactly the
        # one compute() call from the explicit read above.
        assert fake_mode.compute_calls == 1

    def test_sensor_reflects_the_cached_result_without_recomputing(self) -> None:
        coordinator, fake_mode = _make_setup()
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.diagnostic_result()  # prime the cache once
        assert fake_mode.compute_calls == 1

        sensor_0 = ShadyDiagnosticsSensor(coordinator, tf._make_entry(), "0", "String 0")

        assert sensor_0.native_value == "ok"
        assert sensor_0.extra_state_attributes == {"n": 1}
        # Reading again must not bump `n` (which only `compute()`
        # increments) — confirms the sensor is reading the same cached
        # object, not triggering a fresh call.
        assert sensor_0.extra_state_attributes == {"n": 1}
        assert fake_mode.compute_calls == 1


class TestDiagnosticsSensorStateWithoutTriggeringCompute:
    """State resolution for the "off"/"unavailable" cases also never
    calls `.compute()` — there is nothing to compute when the mode is
    off, and an inactive/missing `sensor_id` is resolved from whatever
    the cache already holds, not by calling anything fresh."""

    def test_disabled_when_mode_is_off_without_any_compute_call(self) -> None:
        coordinator, fake_mode = _make_setup()
        # Mode registered but never activated -> diagnostic_mode() is None.
        sensor_0 = ShadyDiagnosticsSensor(coordinator, tf._make_entry(), "0", "String 0")

        assert sensor_0.native_value == "disabled"
        assert sensor_0.extra_state_attributes == {}
        assert fake_mode.compute_calls == 0

    def test_unavailable_for_a_declared_id_missing_from_compute_output(self) -> None:
        coordinator, fake_mode = _make_setup()
        coordinator.set_active_diagnostic_mode("compare_regressions")
        coordinator.diagnostic_result()
        assert fake_mode.compute_calls == 1

        # "1" is declared by sensor_ids() but this fake's compute()
        # deliberately never includes it.
        sensor_1 = ShadyDiagnosticsSensor(coordinator, tf._make_entry(), "1", "String 1")

        assert sensor_1.native_value == "unavailable"
        assert sensor_1.extra_state_attributes == {}
        assert fake_mode.compute_calls == 1
