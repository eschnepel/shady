"""`ShadyCoordinatorLike` (ADR-004 §1a) — the structural contract a
`DiagnosticMode` depends on for whatever it needs from its owning
coordinator, plus the read-only DTOs its methods return.

Split out of `diagnostics/base.py` (2026-09-14) to separate two
different concerns that module had been holding together: `base.py`
describes what a `DiagnosticMode` *is* and *produces* (the ABC itself,
`DiagnosticResult`/`DiagnosticFitResult`/`DiagnosticSensorResult`); this
module describes what a `DiagnosticMode` *consumes* from its
coordinator — an input-side contract, not an output-side one. Moved
again the same day from `coordinator_like.py` to here,
`coordinator_like.py` next to `coordinator.py` itself: what this module
actually describes is `ShadyCoordinator`'s own shape, not anything
diagnostics-specific — `diagnostics/` is its only consumer today, but
nothing about its content is diagnostics-owned, so nesting it inside
that package was the wrong home for what it is, independent of who
currently imports it.

`diagnostics/base.py` only needs `ShadyCoordinatorLike` itself,
`TYPE_CHECKING`-only, for one constructor parameter's annotation;
`diagnostics/compare_regressions.py` only needs the three DTOs below the
same way, for its own internal parameter/return annotations — neither
module executes any of this file's code at runtime (attribute access on
an already-constructed instance needs no import of the class that built
it), so importing this module is never required at runtime by either,
only by `coordinator.py`, which actually constructs instances of the
three DTOs below.

`ShadyCoordinator` satisfies `ShadyCoordinatorLike` structurally, with no
inheritance and no import of this module required on `coordinator.py`'s
side beyond what it already needs to construct `RegressionSettings`/
`StringComputationConfig`/`DiagnosedSlot`. Depending on a local
`Protocol` here rather than `diagnostics/` importing `coordinator.py`
directly (even `TYPE_CHECKING`-only) is what resolves the
`coordinator.py` <-> `diagnostics/` CodeQL `py/unsafe-cyclic-import`
finding for real rather than suppressing it — that query flags any
import sitting lexically outside a `def`, regardless of a `TYPE_CHECKING`
guard, so a guarded back-reference to `coordinator.py` still trips it;
never importing `coordinator.py` under any condition is the only fix
that removes the finding rather than hiding it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    # `cache.py` has no dependency on this module or on `diagnostics/`,
    # even indirectly (it only imports `regression.base.FittedModel`),
    # so this import isn't part of any cycle -- unlike coordinator.py,
    # nothing here needs a `Protocol` workaround. It stays TYPE_CHECKING-
    # only for a narrower reason: `test_diagnostics_base.py` file-path-
    # loads `diagnostics/base.py` in isolation (`shady` is never
    # registered as a real package in `sys.modules`), and that load
    # transitively reaches this module's own `ShadyCoordinatorLike`
    # reference -- a real `from .cache import Cache` here would fail
    # that load with `ModuleNotFoundError: No module named 'shady'`
    # even though there's no cyclic risk.
    from .cache import Cache


@dataclass(frozen=True)
class RegressionSettings:
    """Global scalars `string_computation.py`'s `apply_training_
    corrections`/`fit_string_model` need (ADR-004 §5, second Amendment)
    — the same five values `coordinator.py`'s `_fit_string` already
    resolves for the default-method 288-slot sweep, exposed read-only so
    a `DiagnosticMode` can call those same pure functions itself without
    reaching into `coordinator.py`'s private state. Generic, not
    diagnostics-specific — reusable by ADR-013's sketched future modes.
    Returned by `ShadyCoordinatorLike.regression_settings()` below; lives
    here rather than in `coordinator.py` since it exists specifically to
    cross the `DiagnosticMode` boundary -- and rather than in
    `string_computation.py`/`regression/base.py` despite the name, since
    its five fields don't map 1:1 onto either module's own parameters
    (three reach `regression.base.build_pool` only via `string_
    computation.fit_string_model`'s pass-through; two are consumed
    directly by `string_computation.apply_training_corrections` and
    never reach `regression/base.py` at all).
    """

    smoothing_radius: int
    neighbor_fitting_cutoff: float
    recency_decay_max: float
    clipping_threshold: float
    max_uplift_c: float


@dataclass(frozen=True)
class StringComputationConfig:
    """One configured string's remaining per-string inputs to
    `string_computation.py`'s functions (ADR-004 §5, second Amendment)
    — everything `coordinator.py`'s `_fit_string`/`_provider_already_
    corrects`/`_resolve_temperature_entity` already resolve internally,
    exposed read-only. `baseline_entity_id`/`temperature_entity_id`/
    `temperature_tier` are `None` when unconfigured/unresolved, exactly
    as `_fit_string` already treats them (a `None` `baseline_entity_id`
    means this string cannot be fit/diagnosed at all — no baseline
    forecast to compare against). Returned by `ShadyCoordinatorLike.
    string_computation_config()` below; lives here rather than in
    `coordinator.py` for the same reason as `RegressionSettings` above
    -- and rather than in `string_computation.py` despite the name,
    since `baseline_entity_id`/`actual_yield_entity_id`/
    `temperature_entity_id` are entity IDs `compare_regressions.py` uses
    only to fetch raw series from the cache before calling `string_
    computation.py`; no `string_computation.py` function signature takes
    an entity ID at all (ADR-014's explicit point of that module — no
    Home-Assistant-entity-shaped concept, only arrays and scalars).
    """

    baseline_entity_id: str | None
    actual_yield_entity_id: str
    temperature_entity_id: str | None
    temperature_tier: Literal["weather", "cell", "ambient"] | None
    converter_limit_w: float | None
    coefficient_per_c: float
    provider_already_corrects: bool
    rated_dc_capacity_wp: float | None


@dataclass(frozen=True)
class DiagnosedSlot:
    """Which slot is currently "the diagnosed slot" (ADR-004 §2/§2a) —
    resolved from the pin if one is set, else "the last complete slot"
    as of `now` (auto-tracking). `index` is the absolute slot index
    (`Cache.index_for` convention); `slot_of_day` is `index`'s 0-287
    time-of-day component (`get_pinned_slot_pool`'s own argument);
    `is_elapsed` is whether this slot's own actual/PV value can exist
    yet — `False` only for a manually-pinned slot still in the future
    (§2a's one exception to "selected actual"/accuracy being shown).
    Returned by `ShadyCoordinatorLike.diagnosed_slot()` below — inherently a
    diagnostics concept, so it lives here rather than in
    `coordinator.py`, which only resolves it.
    """

    index: int
    slot_of_day: int
    is_elapsed: bool


class ShadyCoordinatorLike(Protocol):
    """Structural contract a `DiagnosticMode` needs from its owning
    coordinator (ADR-004 §5) — exactly `compare_regressions.py`'s own
    `self._coordinator.*` surface today, nothing wider. `ShadyCoordinator`
    satisfies this without inheriting it or being named here; adding a
    method a future mode needs means extending both this Protocol and
    `ShadyCoordinator`'s matching public method, same as any other
    interface change (ADR-004 §5, second Amendment's "extend the
    coordinator with a new accessor" rule still applies)."""

    @property
    def cache(self) -> Cache: ...

    def strings(self) -> list[tuple[int, str]]: ...

    def now(self) -> datetime: ...

    def diagnosed_slot(self, now: datetime | None = None) -> DiagnosedSlot: ...

    def regression_settings(self) -> RegressionSettings: ...

    def string_computation_config(self, string_index: int) -> StringComputationConfig: ...

    def target_cell_temperature_for_slot(self, string_index: int, index: int) -> float | None: ...
