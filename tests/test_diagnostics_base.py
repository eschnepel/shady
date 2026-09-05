"""Tests for `diagnostics/base.py` (ADR-004 §1/§5, Amendment 2026-09-01,
Amendment 2026-09-02, second Amendment 2026-09-02).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this module.

As of ADR-004 §5's second Amendment (2026-09-01), `diagnostics/` has
left the zero-mocking tier (ADR-000 §6) — but these tests exercise only
`DiagnosticMode`'s own base-class shape (constructor requiredness,
abstract-member requiredness, the two cadence getters, the output
dataclasses), never real coordinator behavior, so a minimal hand-written
stand-in object stands in for `ShadyCoordinator` rather than the full
`homeassistant`-stub convention `test_coordinator.py` uses. A future test
here that actually exercises a cadence getter or stored reference
against real coordinator behavior should switch to that heavier
convention instead of inventing a third one.
"""

from __future__ import annotations

import importlib.util
import sys
from dataclasses import fields
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

import pytest

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_base_mod = _load("diagnostics/base.py", "shady.diagnostics.base")

# TYPE_CHECKING-only static import mirroring the runtime file-path load
# above (ADR-000 §6) — gives mypy real types for these names so the
# subclasses/instances below type-check normally, without reintroducing
# the package import (and therefore `homeassistant.*`) the file-path
# load avoids.
if TYPE_CHECKING:
    from shady.diagnostics.base import DiagnosticCadence as DiagnosticCadence  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticFitResult as DiagnosticFitResult  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticMode as DiagnosticMode  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticResult as DiagnosticResult  # noqa: PLC0414
    from shady.diagnostics.base import (
        DiagnosticSensorResult as DiagnosticSensorResult,  # noqa: PLC0414
    )
else:
    DiagnosticFitResult = _base_mod.DiagnosticFitResult
    DiagnosticMode = _base_mod.DiagnosticMode
    DiagnosticResult = _base_mod.DiagnosticResult
    DiagnosticSensorResult = _base_mod.DiagnosticSensorResult


class _StubCoordinator:
    """Minimal stand-in for `ShadyCoordinator` — these tests never call
    through it, they only check it is stored and reachable, so no real
    coordinator behavior (public or private) needs to be modeled here.
    """


def _stub_coordinator() -> Any:
    """Returns an `_StubCoordinator` typed `Any` — `DiagnosticMode.__init__`
    is (correctly) typed to require a real `ShadyCoordinator`, resolved
    concretely here via the `TYPE_CHECKING`-only static import above; an
    `Any`-typed factory is the same "fake object standing in for a
    strictly-typed dependency" convention `test_coordinator.py`'s own
    `Any`-typed helpers already use, rather than a `# type: ignore` at
    every call site.
    """
    return _StubCoordinator()


def _single_sensor_result(
    state: str = "ok", attributes: dict[str, Any] | None = None
) -> DiagnosticResult:
    """A one-entry DiagnosticResult — the common case for tests that
    don't care about the flat-collection shape itself, only about some
    other aspect of DiagnosticMode's shape."""
    return DiagnosticResult(
        sensors=[DiagnosticSensorResult(sensor_id="0", state=state, attributes=attributes or {})]
    )


class DummyModeMinimal(DiagnosticMode):
    """A minimal mode implementing every required abstract member."""

    key = "dummy_minimal"

    def fit_cadence(self) -> DiagnosticCadence:
        return "slot"

    def compute_cadence(self) -> DiagnosticCadence:
        return "slot"

    def sensor_ids(self) -> list[tuple[str, str]]:
        return [("0", "Dummy")]

    def compute(self) -> DiagnosticResult:
        return _single_sensor_result()


class TestDiagnosticModeConstructorRequiresCoordinator:
    """Given a minimal dummy DiagnosticMode subclass, When it is
    instantiated without a coordinator argument, Then instantiation
    fails — the constructor parameter is required, no default
    (ADR-004 §5, second Amendment)."""

    def test_missing_coordinator_fails_instantiation(self) -> None:
        with pytest.raises(TypeError):
            DummyModeMinimal()  # type: ignore[call-arg]


class TestDiagnosticModeCoordinatorReachable:
    """Given a minimal dummy DiagnosticMode subclass instantiated with a
    stand-in coordinator object, When the instance is inspected, Then
    the coordinator it was constructed with is reachable from within the
    instance for compute()/extra_fit()/the two new getters to use."""

    def test_coordinator_stored_on_instance(self) -> None:
        coordinator = _stub_coordinator()
        mode = DummyModeMinimal(coordinator)
        assert mode._coordinator is coordinator


class TestDiagnosticModeRequiresCadenceGetters:
    """Given a dummy subclass that implements compute() but omits
    fit_cadence() or compute_cadence(), When it is instantiated, Then
    instantiation fails — both getters are abstract, required, no
    default, the same requiredness compute() itself already has."""

    def test_missing_both_cadence_getters_fails_instantiation(self) -> None:
        class DummyModeNoCadence(DiagnosticMode):
            key = "dummy_no_cadence"

            def compute(self) -> DiagnosticResult:
                return _single_sensor_result()

        with pytest.raises(TypeError):
            DummyModeNoCadence(_stub_coordinator())  # type: ignore[abstract]

    def test_missing_compute_cadence_only_fails_instantiation(self) -> None:
        class DummyModeNoComputeCadence(DiagnosticMode):
            key = "dummy_no_compute_cadence"

            def fit_cadence(self) -> DiagnosticCadence:
                return "daily"

            def compute(self) -> DiagnosticResult:
                return _single_sensor_result()

        with pytest.raises(TypeError):
            DummyModeNoComputeCadence(_stub_coordinator())  # type: ignore[abstract]


class TestDiagnosticModeRequiresCompute:
    """Given a dummy subclass that omits compute() entirely, instantiation
    fails — compute is required, no default (mirrors ADR-012 §1's
    Provider.fetch() requiredness)."""

    def test_missing_compute_fails_instantiation(self) -> None:
        class DummyModeNoCompute(DiagnosticMode):
            """Deliberately omits compute()."""

            key = "dummy_no_compute"

            def fit_cadence(self) -> DiagnosticCadence:
                return "hourly"

            def compute_cadence(self) -> DiagnosticCadence:
                return "hourly"

        with pytest.raises(TypeError):
            DummyModeNoCompute(_stub_coordinator())  # type: ignore[abstract]


class TestDiagnosticCadenceValues:
    """Given a dummy subclass implementing all three abstract members,
    When fit_cadence()/compute_cadence() are called, Then each returns
    exactly one of "daily", "hourly", "slot"."""

    @pytest.mark.parametrize("cadence", ["daily", "hourly", "slot"])
    def test_cadence_getters_return_declared_value(self, cadence: DiagnosticCadence) -> None:
        class DummyModeCadence(DiagnosticMode):
            key = "dummy_cadence"

            def fit_cadence(self) -> DiagnosticCadence:
                return cadence

            def compute_cadence(self) -> DiagnosticCadence:
                return cadence

            def sensor_ids(self) -> list[tuple[str, str]]:
                return [("0", "Dummy")]

            def compute(self) -> DiagnosticResult:
                return _single_sensor_result()

        mode = DummyModeCadence(_stub_coordinator())
        assert mode.fit_cadence() == cadence
        assert mode.compute_cadence() == cadence


class TestDiagnosticModeComputeAndExtraFitTakeNoParameters:
    """Given DiagnosticMode.compute, its new signature is
    compute(self) -> DiagnosticResult — no parameter beyond self. Given
    DiagnosticMode.extra_fit, its new signature is
    extra_fit(self) -> DiagnosticFitResult | None — no parameter beyond
    self, still optional, still defaults to returning None. Unchanged by
    either of ADR-004 §5's same-day 2026-09-02 amendments — only the
    *output* dataclasses' internal shape changed, not these signatures."""

    def test_compute_takes_no_arguments(self) -> None:
        mode = DummyModeMinimal(_stub_coordinator())
        result = mode.compute()
        assert result == _single_sensor_result()

    def test_extra_fit_defaults_to_none_and_takes_no_arguments(self) -> None:
        mode = DummyModeMinimal(_stub_coordinator())
        assert mode.extra_fit() is None


class TestDiagnosticContextRemoved:
    """Given diagnostics/base.py after TASK-0015a-patch-2, When its
    exports are listed, Then DiagnosticContext and DiagnosticSlotSample
    are not among them — both are deleted outright, and remain deleted
    after both same-day 2026-09-02 patches (neither reintroduces either
    removed class)."""

    def test_diagnostic_context_not_exported(self) -> None:
        assert not hasattr(_base_mod, "DiagnosticContext")

    def test_diagnostic_slot_sample_not_exported(self) -> None:
        assert not hasattr(_base_mod, "DiagnosticSlotSample")

    def test_diagnostic_result_and_fit_result_still_exported(self) -> None:
        assert hasattr(_base_mod, "DiagnosticResult")
        assert hasattr(_base_mod, "DiagnosticFitResult")

    def test_diagnostic_sensor_result_exported(self) -> None:
        assert hasattr(_base_mod, "DiagnosticSensorResult")

    def test_diagnostic_string_result_no_longer_exported(self) -> None:
        """DiagnosticStringResult (TASK-0015a-patch-3's name) was renamed
        to DiagnosticSensorResult by this patch, not kept alongside it."""
        assert not hasattr(_base_mod, "DiagnosticStringResult")


class TestDiagnosticResultShape:
    """Given DiagnosticResult/DiagnosticSensorResult/DiagnosticFitResult
    after ADR-004 §5's fourth Amendment, When their fields are
    inspected, Then DiagnosticResult has exactly one field, sensors;
    DiagnosticSensorResult has exactly six fields (sensor_id, state,
    attributes required; name, unit, device_class optional); and
    DiagnosticFitResult has exactly one field, by_sensor."""

    def test_diagnostic_result_has_only_sensors_field(self) -> None:
        field_names = {f.name for f in fields(DiagnosticResult)}
        assert field_names == {"sensors"}

    def test_diagnostic_sensor_result_has_all_six_fields(self) -> None:
        field_names = {f.name for f in fields(DiagnosticSensorResult)}
        assert field_names == {"sensor_id", "state", "attributes", "name", "unit", "device_class"}

    def test_diagnostic_sensor_result_optional_fields_default_to_none(self) -> None:
        sensor = DiagnosticSensorResult(sensor_id="south", state="12.3", attributes={})
        assert sensor.name is None
        assert sensor.unit is None
        assert sensor.device_class is None

    def test_diagnostic_fit_result_has_only_by_sensor_field(self) -> None:
        field_names = {f.name for f in fields(DiagnosticFitResult)}
        assert field_names == {"by_sensor"}


class TestDiagnosticResultSensorListGeneralization:
    """Given a dummy subclass whose compute() returns a DiagnosticResult
    with entries using three different kinds of sensor_id — a
    string-index-derived id, a provider-name id, and a fixed whole-array
    sentinel id — When the returned value is inspected, Then all three
    are present unchanged, each reachable by its own sensor_id. This is
    the scenario the whole patch exists for: DiagnosticResult must not
    assume every mode varies over configured strings (ADR-004 §5, fourth
    Amendment; ADR-013 §1's compare_providers_daily/
    compare_regressions_daily sketches)."""

    def test_compute_bundles_three_differently_scoped_sensor_ids(self) -> None:
        class DummyModeMixedGranularity(DiagnosticMode):
            key = "dummy_mixed_granularity"

            def fit_cadence(self) -> DiagnosticCadence:
                return "slot"

            def compute_cadence(self) -> DiagnosticCadence:
                return "slot"

            def sensor_ids(self) -> list[tuple[str, str]]:
                return [
                    ("string_0", "String 0"),
                    ("provider_baseline", "Provider Baseline"),
                    ("array_total", "Array Total"),
                ]

            def compute(self) -> DiagnosticResult:
                return DiagnosticResult(
                    sensors=[
                        # A string-index-derived id (CompareRegressionsMode's own case).
                        DiagnosticSensorResult(
                            sensor_id="string_0", state="12.3", attributes={"kind": "string"}
                        ),
                        # A provider-name id (ADR-013's compare_providers_daily sketch).
                        DiagnosticSensorResult(
                            sensor_id="provider_baseline",
                            state="0.94",
                            attributes={"kind": "provider"},
                        ),
                        # A fixed whole-array sentinel id (a mode with no
                        # per-string or per-provider breakdown at all).
                        DiagnosticSensorResult(
                            sensor_id="array_total", state="41.2", attributes={"kind": "array"}
                        ),
                    ]
                )

        result = DummyModeMixedGranularity(_stub_coordinator()).compute()
        by_id = {sensor.sensor_id: sensor for sensor in result.sensors}

        assert len(result.sensors) == 3
        assert by_id["string_0"].attributes == {"kind": "string"}
        assert by_id["provider_baseline"].attributes == {"kind": "provider"}
        assert by_id["array_total"].attributes == {"kind": "array"}


class TestDiagnosticFitResult:
    """Given a dummy subclass whose extra_fit() returns a
    DiagnosticFitResult bundling two sensors' worth of predictions, When
    the returned value is inspected, Then each sensor's inner
    Mapping[str, float] is reachable via result.by_sensor[<sensor_id>]
    unchanged from what the subclass produced — the value shape
    coordinator.py will cache, not decided or consumed here."""

    def test_extra_fit_bundles_two_sensors_predictions_unchanged(self) -> None:
        sensor_0_predictions: dict[str, float] = {
            "linear": 1.0,
            "wls2": 1.1,
            "wls3": 1.2,
            "kernel": 0.9,
        }
        sensor_1_predictions: dict[str, float] = {
            "linear": 2.0,
            "wls2": 2.1,
            "wls3": 2.2,
            "kernel": 1.9,
        }

        class DummyModeWithFit(DiagnosticMode):
            key = "dummy_with_fit"

            def fit_cadence(self) -> DiagnosticCadence:
                return "slot"

            def compute_cadence(self) -> DiagnosticCadence:
                return "slot"

            def sensor_ids(self) -> list[tuple[str, str]]:
                return [("0", "Dummy")]

            def compute(self) -> DiagnosticResult:
                return _single_sensor_result()

            def extra_fit(self) -> DiagnosticFitResult | None:
                return DiagnosticFitResult(
                    by_sensor={"string_0": sensor_0_predictions, "string_1": sensor_1_predictions}
                )

        result = DummyModeWithFit(_stub_coordinator()).extra_fit()

        assert result is not None
        assert result.by_sensor["string_0"] == sensor_0_predictions
        assert result.by_sensor["string_1"] == sensor_1_predictions


class TestDiagnosticModeUsesCoordinatorInCompute:
    """Given a dummy subclass whose compute()/extra_fit() read data off
    the stored coordinator reference, When they are called, Then they
    see exactly the stand-in object passed at construction — validating
    that a real mode can resolve its own inputs on demand rather than
    receiving them via a per-call parameter (ADR-004 §5, second
    Amendment), including which sensors exist to bundle (ADR-004 §5,
    fourth Amendment)."""

    def test_compute_reads_through_stored_coordinator(self) -> None:
        class _CoordinatorWithData:
            def strings(self) -> list[tuple[int, str]]:
                return [(0, "south"), (1, "north")]

        def _coordinator_with_data() -> Any:
            return _CoordinatorWithData()

        class DummyModeReadsCoordinator(DiagnosticMode):
            key = "dummy_reads_coordinator"

            def fit_cadence(self) -> DiagnosticCadence:
                return "slot"

            def compute_cadence(self) -> DiagnosticCadence:
                return "slot"

            def sensor_ids(self) -> list[tuple[str, str]]:
                return [(str(index), name) for index, name in self._coordinator.strings()]

            def compute(self) -> DiagnosticResult:
                return DiagnosticResult(
                    sensors=[
                        DiagnosticSensorResult(
                            sensor_id=str(index), state="ok", attributes={"name": name}
                        )
                        for index, name in self._coordinator.strings()
                    ]
                )

        mode = DummyModeReadsCoordinator(_coordinator_with_data())
        result = mode.compute()
        by_id = {sensor.sensor_id: sensor for sensor in result.sensors}
        assert by_id["0"].attributes["name"] == "south"
        assert by_id["1"].attributes["name"] == "north"
