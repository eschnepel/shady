"""Shared diagnostic-mode base class and its dataclasses (ADR-004 §1/§5,
Amendment 2026-08-30).

Every concrete diagnostic mode (starting with `compare_regressions.py`'s
`CompareRegressionsMode`) subclasses `DiagnosticMode` below. This module
holds only the shared base class and the plain dataclasses its methods
use — no concrete mode logic lives here, mirroring `providers/base.py`'s
`Provider` ABC (ADR-012 §1). `DiagnosticContext.samples` is a `Sequence`
rather than a single value specifically so a future whole-day mode
(ADR-013 §1, 288 samples) needs no change to this module — only a new
subclass.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True)
class DiagnosticSlotSample:
    """One slot's already-resolved comparison inputs.

    `predicted` is keyed by whatever this mode compares — regression-
    method name for `CompareRegressionsMode`, provider name for a future
    provider-comparison mode (ADR-013 §1). `actual` is `None` for a slot
    that hasn't elapsed yet (mirrors ADR-004 §2a's future-pin handling).
    `pool` is the optional historical scatter data (ADR-004 §2) —
    meaningful for a single-slot scatter-style mode, left `None` for a
    mode with no scatter concept of its own (e.g. a whole-day mode,
    ADR-013 §1).
    """

    slot_of_day: int
    predicted: Mapping[str, float]
    actual: float | None
    pool: Mapping[str, list[tuple[float, float]]] | None = None


@dataclass(frozen=True)
class DiagnosticContext:
    """One or more slots' already-fetched comparison inputs — never raw
    HA/recorder access, that's `coordinator.py`'s job before this is
    built.

    A single-slot mode (`CompareRegressionsMode`, ADR-004) receives
    exactly one sample; a whole-day mode (ADR-013 §1, not yet scheduled)
    receives 288 — same shape, different cardinality, no base-class
    change needed either way. Also the parameter type for `extra_fit()`
    below — the same already-fetched inputs `compute()` receives, since
    a mode's extra fitting operates on the same diagnosed slot(s) it is
    about to render (ADR-004 §1/§5 Amendment).
    """

    samples: Sequence[DiagnosticSlotSample]


@dataclass(frozen=True)
class DiagnosticResult:
    """Pure, sensor-ready payload — `sensor.py` sets `state`/extends its
    attributes with `attributes` directly, no further shaping.
    """

    state: str
    attributes: dict[str, Any]


@dataclass(frozen=True)
class DiagnosticFitResult:
    """Whatever a mode's extra fitting produced, per compared source
    (method or provider name) — `coordinator.py` is the one that writes
    this into `cache.py`, same division of labor `push()` already has
    for provider `forward()` results (ADR-012 §4): the mode computes,
    the coordinator persists.
    """

    predictions: Mapping[str, float]


class DiagnosticMode(ABC):
    """Shared base class for diagnostic modes (ADR-004 §1/§5, Amendment
    2026-08-30).

    One required, pure method and one optional, no-op-by-default hook —
    the same shape `providers/base.py`'s `Provider` ABC already
    established (ADR-012 §1), dispatched generically by `coordinator.py`
    without knowing which concrete mode it's talking to. Different
    triggers than `Provider` (a recalibration trigger for `extra_fit()`,
    not a live push listener), same shape.
    """

    key: ClassVar[str]

    @abstractmethod
    def compute(self, context: DiagnosticContext) -> DiagnosticResult:
        """Pure. No HA import — zero-mocking tier (ADR-000 §6)."""

    def extra_fit(self, context: DiagnosticContext) -> DiagnosticFitResult | None:
        """Optional, pure. Whatever extra per-slot fitting this mode
        needs beyond the default recalibration (ADR-002 §1) — e.g.
        fitting `regression/`'s other three strategies for the diagnosed
        slot, for `CompareRegressionsMode`.

        Run at the recalibration trigger while this mode is active; the
        returned `DiagnosticFitResult` (or `None`) is what
        `coordinator.py` caches, mirroring how it already handles a
        provider's `forward()` result (ADR-012 §4) — build/cache stays
        in `coordinator.py`, the mode only computes. Base default:
        `None` — "nothing extra needed," the same role `None` already
        plays for `Provider.forward()` (ADR-012 §1), generalizing ADR-004
        §1's original zero-cost-when-off guarantee to "zero cost for any
        mode that doesn't need extra fitting."
        """
        return None
