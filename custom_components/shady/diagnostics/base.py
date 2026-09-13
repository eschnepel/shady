"""Shared diagnostic-mode base class and its output dataclasses (ADR-004
§1/§5, Amendment 2026-09-01, Amendment 2026-09-02, second Amendment
2026-09-02, fifth Amendment 2026-09-03).

Every concrete diagnostic mode (starting with `compare_regressions.py`'s
`CompareRegressionsMode`) subclasses `DiagnosticMode` below. This module
holds only the shared base class and the plain output dataclasses its
methods return — no concrete mode logic lives here, mirroring
`providers/base.py`'s `Provider` ABC (ADR-012 §1).

As of ADR-004 §5's second Amendment (2026-09-01), a `DiagnosticMode` is
constructed with a reference to the owning `ShadyCoordinator` and pulls
whatever coordinator-owned data it needs directly, on demand, through
that reference's **public** interface only (`strings()`, `cache`, ...) —
never a `_`-prefixed attribute. This trades the module's prior purity
(no `cache.py`/`homeassistant.*` import) for not having to anticipate
every future mode's exact inputs ahead of time via a per-call context
DTO. The `ShadyCoordinator` import below is `TYPE_CHECKING`-only, so no
runtime import of `coordinator.py` (and therefore no `homeassistant.*`)
is introduced by this module itself — the cycle is resolved the same way
this project's own test files already resolve a comparable problem
(ADR-000 §6), not by restoring purity. `DiagnosticContext` and
`DiagnosticSlotSample`, the prior per-call input DTOs, are removed
outright (not deprecated-and-kept) — see ADR-004 §5's second Amendment
for the full rationale.

As of ADR-004 §5's third Amendment (2026-09-02), `compute()`'s and
`extra_fit()`'s zero-argument signatures are unchanged, but their output
dataclasses briefly bundled every configured string in one call, keyed
by string index — because `coordinator.py`'s `_diagnostic_modes` holds
one shared instance per mode name, not one per string, so a single call
has to cover every string at once rather than relying on per-call state
a shared instance doesn't have.

As of ADR-004 §5's fourth Amendment (2026-09-02, later the same day),
that string-index keying was replaced: it didn't generalize to a mode
that isn't string-scoped at all (ADR-013's sketched
`compare_providers_daily`, e.g., compares providers, not strings).
`DiagnosticResult`/`DiagnosticFitResult` now hold a flat,
self-identifying collection instead — each `DiagnosticSensorResult`
carries its own `sensor_id`, however the producing mode chooses to
identify it (a string index as text, a provider name, a fixed sentinel
for a whole-array total, ...), rather than the container itself assuming
what dimension a mode varies over.

As of ADR-004 §5's fifth Amendment (2026-09-03), `sensor.py` no longer
special-cases "one entity per configured string plus one fixed sum
entity" — that shape was `CompareRegressionsMode`'s own, leaking into
the platform-setup code of a module meant to stay mode-agnostic (the
same complaint the fourth Amendment already applied to the *output*
side of `compute()`, now extended to the *entity-creation* side).
`sensor_ids()` below lets a mode declare, cheaply and without running
`compute()` itself, exactly which `sensor_id`s (and display names) it
will ever produce — `sensor.py`'s `async_setup_entry` creates one
generic diagnostic sensor entity per declared id, for every registered
mode, not just whichever mode happens to be active at setup time (ADR
entities are added once for a config entry's lifetime; a mode selected
later via `select.py` must already have its entities in place). A mode
producing several distinct aggregate entities — more than one kind of
"sum" — is handled exactly the same way as one that doesn't: it simply
declares more `sensor_id`s.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from ..coordinator import ShadyCoordinator

DiagnosticCadence = Literal["daily", "hourly", "slot"]
"""How often a mode needs `extra_fit()`/`compute()` to run, declared by
the mode itself (ADR-004 §5, second Amendment) so `coordinator.py` can
read it generically instead of hard-coding a case per mode. `"slot"` is
what `CompareRegressionsMode` (TASK-0015b) declares — it fits/computes
for exactly one diagnosed 5-minute slot, reusing TASK-0013's existing
5-minute trigger.
"""


@dataclass(frozen=True)
class DiagnosticSensorResult:
    """One diagnostic entity's sensor-ready payload, self-identifying via
    `sensor_id` so `DiagnosticResult` can hold a flat collection of
    however many of these a given mode's `compute()` call produces — not
    assumed to be "one per configured string" (ADR-004 §5, fourth
    Amendment, 2026-09-02). A mode that isn't string-scoped at all
    (ADR-013's sketched `compare_providers_daily`, comparing providers,
    or a mode producing a single whole-array total) is represented
    exactly the same way as `CompareRegressionsMode`'s one-per-string
    case: a flat collection, however long, each entry carrying its own
    identity.

    `state`/`attributes` are `sensor.py`'s sensor-ready payload — it sets
    `state`/extends its attributes with `attributes` directly, no
    further shaping. `name`/`unit`/`device_class` are optional, plain-
    `str` (not `homeassistant.*` enums — this module stays free of that
    runtime import) hints `sensor.py` may use when shaping the real
    entity beyond its own per-mode defaults; a mode with nothing to
    override leaves them `None`.
    """

    sensor_id: str
    state: str
    attributes: dict[str, Any]
    name: str | None = None
    unit: str | None = None
    device_class: str | None = None


@dataclass(frozen=True)
class DiagnosticResult:
    """Every diagnostic entity this mode's one `compute()` call produced,
    as a flat collection identified by each entry's own `sensor_id` —
    not keyed by string index or any other dimension the container
    itself assumes (ADR-004 §5, fourth Amendment). `sensor.py`'s
    per-string `ShadyDiagnosticsSensor` finds its own entry by matching
    `sensor_id`; a future mode that isn't string-scoped populates this
    the same way, with whatever `sensor_id`s make sense for what it
    compares.
    """

    sensors: Sequence[DiagnosticSensorResult]


@dataclass(frozen=True)
class DiagnosticFitResult:
    """Every diagnostic entity's extra-fitting output from one
    `extra_fit()` call, keyed by the same `sensor_id`
    `DiagnosticResult` uses — not string index (ADR-004 §5, fourth
    Amendment; same generalization rationale as `DiagnosticResult`
    above). Each entry's inner mapping is keyed by compared source
    (method or provider name), unchanged since before either same-day
    amendment — `coordinator.py` iterates `by_sensor` and writes each
    entry's inner mapping into `cache.py` individually, same division of
    labor `push()` already has for provider `forward()` results
    (ADR-012 §4): the mode computes, the coordinator persists.
    """

    by_sensor: Mapping[str, Mapping[str, float]]


class DiagnosticMode(ABC):
    """Shared base class for diagnostic modes (ADR-004 §1/§5, Amendment
    2026-09-01, Amendment 2026-09-02, second Amendment 2026-09-02).

    Constructed with the owning `ShadyCoordinator`; `compute()`/
    `extra_fit()` take no further parameters and resolve whatever they
    need through that reference's public interface, covering every
    diagnostic entity this mode produces in one call (ADR-004 §5, fourth
    Amendment). Encapsulation boundary despite dropping purity: a
    `DiagnosticMode` may use only `coordinator.py`'s public
    (non-`_`-prefixed) interface — extend the coordinator with a new
    accessor rather than reach into private state (ADR-004 §5, second
    Amendment).
    """

    key: ClassVar[str]

    def __init__(self, coordinator: ShadyCoordinator) -> None:
        self._coordinator = coordinator

    @abstractmethod
    def fit_cadence(self) -> DiagnosticCadence:
        """How often this mode needs `extra_fit()` to run. Required, no
        default — core to what the mode is."""

    @abstractmethod
    def compute_cadence(self) -> DiagnosticCadence:
        """How often this mode needs `compute()` to run. Required, no
        default — core to what the mode is."""

    @abstractmethod
    def sensor_ids(self) -> Sequence[tuple[str, str]]:
        """Every `(sensor_id, name)` pair this mode's `compute()` will
        ever produce, resolvable cheaply — no recorder fetches, no
        fitting — without calling `compute()` itself (ADR-004 §5, fifth
        Amendment). `sensor.py`'s `async_setup_entry` calls this once,
        at platform-setup time, to create one generic diagnostic sensor
        entity per declared id; `compute()`'s own output must only ever
        use `sensor_id`s declared here, never an ad hoc one invented on
        the fly, or the corresponding entity will never have been
        created to show it."""

    @abstractmethod
    def compute(self) -> DiagnosticResult:
        """Resolves whatever it needs via `self._coordinator`'s public
        interface, for every diagnostic entity this mode produces in one
        call (ADR-004 §5, fourth Amendment) — not one call per entity.
        No parameters beyond `self`."""

    def extra_fit(self) -> DiagnosticFitResult | None:
        """Optional. Whatever extra fitting this mode needs beyond the
        default recalibration (ADR-002 §1) — e.g. fitting `regression/`'s
        other three strategies for the diagnosed slot, for
        `CompareRegressionsMode` — resolved via `self._coordinator`'s
        public interface, same as `compute()`, for every diagnostic
        entity this mode produces in one call (ADR-004 §5, fourth
        Amendment).

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
