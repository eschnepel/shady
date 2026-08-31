"""Zero-mocking tests for `diagnostics/base.py` (ADR-004 §1/§5, ADR-000 §6).

Loaded via direct file-path import, not package import, so that
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test this dependency-free module.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING

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
    from shady.diagnostics.base import DiagnosticContext as DiagnosticContext  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticFitResult as DiagnosticFitResult  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticMode as DiagnosticMode  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticResult as DiagnosticResult  # noqa: PLC0414
    from shady.diagnostics.base import DiagnosticSlotSample as DiagnosticSlotSample  # noqa: PLC0414
else:
    DiagnosticContext = _base_mod.DiagnosticContext
    DiagnosticFitResult = _base_mod.DiagnosticFitResult
    DiagnosticMode = _base_mod.DiagnosticMode
    DiagnosticResult = _base_mod.DiagnosticResult
    DiagnosticSlotSample = _base_mod.DiagnosticSlotSample


class DummyModeMinimal(DiagnosticMode):
    """A minimal mode that only implements the required `compute()`."""

    key = "dummy_minimal"

    def compute(self, context: DiagnosticContext) -> DiagnosticResult:
        return DiagnosticResult(state="ok", attributes={"count": len(context.samples)})


class TestDiagnosticModeBaseClassDefaults:
    """Given a dummy subclass that only implements compute(), the base
    class's extra_fit() default applies (ADR-004 §1/§5 Amendment,
    mirrors ADR-012 §1's Provider.forward() optionality)."""

    def test_minimal_subclass_instantiates(self) -> None:
        mode = DummyModeMinimal()
        sample = DiagnosticSlotSample(slot_of_day=0, predicted={"linear": 1.0}, actual=0.9)
        result = mode.compute(DiagnosticContext(samples=[sample]))
        assert result == DiagnosticResult(state="ok", attributes={"count": 1})

    def test_extra_fit_defaults_to_none(self) -> None:
        mode = DummyModeMinimal()
        sample = DiagnosticSlotSample(slot_of_day=0, predicted={"linear": 1.0}, actual=0.9)
        assert mode.extra_fit(DiagnosticContext(samples=[sample])) is None


class TestDiagnosticModeRequiresCompute:
    """Given a dummy subclass that omits compute() entirely, instantiation
    fails — compute is required, no default (ADR-004 §1/§5 Amendment,
    mirrors ADR-012 §1's Provider.fetch() requiredness)."""

    def test_missing_compute_fails_instantiation(self) -> None:
        class DummyModeNoCompute(DiagnosticMode):
            """Deliberately omits compute()."""

            key = "dummy_no_compute"

        with pytest.raises(TypeError):
            DummyModeNoCompute()  # type: ignore[abstract]


class TestDiagnosticContextCardinality:
    """Given a DiagnosticContext built with either one or 288
    DiagnosticSlotSample entries, a mode's compute() receives a Sequence
    of the matching length — no base-class change needed for
    cardinality alone (validates ADR-013 §1's premise, single-slot case
    is what CompareRegressionsMode will use)."""

    def test_single_sample_context(self) -> None:
        sample = DiagnosticSlotSample(slot_of_day=42, predicted={"wls2": 3.1}, actual=3.0)
        context = DiagnosticContext(samples=[sample])

        captured: dict[str, int] = {}

        class DummyModeCapture(DiagnosticMode):
            key = "dummy_capture"

            def compute(self, context: DiagnosticContext) -> DiagnosticResult:
                captured["length"] = len(context.samples)
                return DiagnosticResult(state="ok", attributes={})

        DummyModeCapture().compute(context)
        assert captured["length"] == 1

    def test_whole_day_288_sample_context(self) -> None:
        samples = [
            DiagnosticSlotSample(slot_of_day=i, predicted={"wls2": float(i)}, actual=float(i))
            for i in range(288)
        ]
        context = DiagnosticContext(samples=samples)

        captured: dict[str, int] = {}

        class DummyModeCapture(DiagnosticMode):
            key = "dummy_capture_daily"

            def compute(self, context: DiagnosticContext) -> DiagnosticResult:
                captured["length"] = len(context.samples)
                return DiagnosticResult(state="ok", attributes={})

        DummyModeCapture().compute(context)
        assert captured["length"] == 288


class TestDiagnosticSlotSamplePartialData:
    """Given a DiagnosticSlotSample with actual=None or pool=None, it is
    accepted — the base class makes no assumption that every sample has
    a real value or a pool (ADR-004 §2a's future-pin partial-data shape;
    ADR-013 §1's no-scatter-concept whole-day modes)."""

    def test_actual_none_is_accepted(self) -> None:
        sample = DiagnosticSlotSample(slot_of_day=10, predicted={"wls2": 1.5}, actual=None)
        assert sample.actual is None

    def test_pool_none_is_accepted(self) -> None:
        sample = DiagnosticSlotSample(
            slot_of_day=10, predicted={"wls2": 1.5}, actual=1.4, pool=None
        )
        assert sample.pool is None

    def test_pool_defaults_to_none_when_omitted(self) -> None:
        sample = DiagnosticSlotSample(slot_of_day=10, predicted={"wls2": 1.5}, actual=1.4)
        assert sample.pool is None


class TestDiagnosticFitResult:
    """Given a dummy subclass whose extra_fit() returns a
    DiagnosticFitResult, the returned value's predictions mapping is
    accessible unchanged — the value shape coordinator.py will cache,
    not decided or consumed here (ADR-004 §1/§5 Amendment)."""

    def test_extra_fit_predictions_accessible_unchanged(self) -> None:
        expected = {"linear": 1.0, "wls2": 1.1, "wls3": 1.2, "kernel": 0.9}

        class DummyModeWithFit(DiagnosticMode):
            key = "dummy_with_fit"

            def compute(self, context: DiagnosticContext) -> DiagnosticResult:
                return DiagnosticResult(state="ok", attributes={})

            def extra_fit(self, context: DiagnosticContext) -> DiagnosticFitResult | None:
                return DiagnosticFitResult(predictions=expected)

        sample = DiagnosticSlotSample(slot_of_day=0, predicted={"wls2": 1.1}, actual=1.0)
        result = DummyModeWithFit().extra_fit(DiagnosticContext(samples=[sample]))

        assert result is not None
        assert result.predictions == expected
