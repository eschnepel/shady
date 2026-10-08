"""Shared diagnostic-mode base class and its output dataclasses (ADR-004
§1/§5, Amendment 2026-09-01, Amendment 2026-09-02, second Amendment
2026-09-02, fifth Amendment 2026-09-03).

Every concrete diagnostic mode (starting with `compare_regressions.py`'s
`CompareRegressionsMode`) subclasses `DiagnosticMode` below. This module
holds only the shared base class and the plain output dataclasses its
methods return — no concrete mode logic lives here, mirroring
`providers/base.py`'s `Provider` ABC (ADR-012 §1). The *input* side of
that same boundary — `ShadyCoordinatorLike` and the DTOs its methods return
— as of 2026-09-14 lives in `coordinator_like.py`, next to
`coordinator.py` itself (moved there the same day from a `diagnostics/`-
nested location — what it describes is `ShadyCoordinator`'s own shape,
not anything diagnostics-owned, `diagnostics/` just being its only
consumer today). `base.py` is "what a `DiagnosticMode` is and produces",
`coordinator_like.py` is "what a `DiagnosticMode` consumes", and neither
concern needs the other's contents to make sense on its own.

As of ADR-004 §5's second Amendment (2026-09-01), a `DiagnosticMode` is
constructed with a reference to the owning coordinator and pulls
whatever coordinator-owned data it needs directly, on demand, through
that reference's **public** interface only (`strings()`, `cache`, ...) —
never a `_`-prefixed attribute. This trades the module's prior purity
(no `cache.py`/`homeassistant.*` import) for not having to anticipate
every future mode's exact inputs ahead of time via a per-call context
DTO. `DiagnosticContext` and `DiagnosticSlotSample`, the prior per-call
input DTOs, are removed outright (not deprecated-and-kept) — see ADR-004
§5's second Amendment for the full rationale.

`DiagnosticMode.__init__` takes `ShadyCoordinatorLike` (`coordinator_like.py`)
— a `Protocol` mirroring exactly the subset of `ShadyCoordinator`'s
public interface a `DiagnosticMode` actually calls (`cache`, `strings()`,
`now()`, `diagnosed_slot()`, `regression_settings()`,
`string_computation_config()`, `target_cell_temperature_for_slot()`) —
not the concrete `ShadyCoordinator` class. `ShadyCoordinator` satisfies
it structurally, with no explicit inheritance and no import of
`coordinator_like.py` required on `coordinator.py`'s side beyond what it
already needs. This — not a `TYPE_CHECKING`-guarded import of
`ShadyCoordinator` — is how the `coordinator.py` <-> `diagnostics/`
reference is resolved: a `TYPE_CHECKING` guard is runtime-safe (the
import never executes), but CodeQL's `py/unsafe-cyclic-import` query
only checks whether an import sits lexically outside a `def`, not
whether it is further gated on `TYPE_CHECKING` — so a guarded
back-reference to `coordinator.py` still trips it. Depending on a local
`Protocol` instead means `diagnostics/` never imports `coordinator.py`
at all, under any condition, which resolves the alert for real rather
than suppressing it.

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

As of 2026-09-21 (`TASK-0015b-patch-3`), `DiagnosticMode` also carries
`_xy_series_entry()`, a `@staticmethod` every concrete mode inherits for
building one `series`-attribute entry in `custom:plotly-graph`'s trace
shape (ADR-004 §2d). It moved here from `compare_regressions.py`, where
`TASK-0015b-patch-2` first introduced it as a private module-level
function — `CompareRegressionsMode` was, at the time, still the only
concrete mode there was to use it. Shared base-class placement matters
once a second mode exists (ADR-013's sketched ones do, on paper): every
mode's `series` output should look identical in shape, and a shared
inherited method is what keeps that true by construction rather than by
convention two independently-written `compute()` bodies would have to
maintain by hand.

As of 2026-10-04 (`TASK-0015b-patch-4`, ADR-004 §2h), `_xy_series_entry()`
also rounds every `x`/`y` value to one decimal place and emits a `marker`
key (`symbol`, plus an optional per-point `size` list) — see its own
docstring. Still the one shared builder: a mode chooses *which* symbol and
sizes an entry gets, never the entry's shape.
"""

from __future__ import annotations

import csv
import io
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    # Neither `ShadyCoordinatorLike` nor any of its own imports are needed at
    # runtime here -- `__init__` only stores `coordinator`, it never
    # constructs or inspects it, so the annotation (deferred anyway by
    # `from __future__ import annotations` above) is all this module
    # needs. Staying TYPE_CHECKING-only also matters for a narrower
    # reason: `test_diagnostics_base.py` file-path-loads this module in
    # isolation (`shady` is never registered as a real package in
    # `sys.modules`), so a real `from ..coordinator_like import ...`
    # would fail that load the same way `from ..cache import Cache`
    # would.
    from ..coordinator_like import ShadyCoordinatorLike

DiagnosticCadence = Literal["daily", "hourly", "slot"]
"""How often a mode needs `extra_fit()`/`compute()` to run, declared by
the mode itself (ADR-004 §5, second Amendment) so `coordinator.py` can
read it generically instead of hard-coding a case per mode. `"slot"` is
what `CompareRegressionsMode` (TASK-0015b) declares — it fits/computes
for exactly one diagnosed 5-minute slot, reusing TASK-0013's existing
5-minute trigger.
"""

SERIES_VALUE_DIGITS = 1
"""Decimal places every `series` entry's `x`/`y` value is rounded to
(ADR-004 §2h, 2026-10-04) — display-only; nothing fitted or exported
ever reads a rounded value back."""


def _round_value(value: float) -> float:
    """`value` rounded to `SERIES_VALUE_DIGITS` places, with a `-0.0`
    result normalised to `0.0` (a tiny negative value would otherwise
    render as `-0.0` in a dashboard's hover label)."""
    return round(value, SERIES_VALUE_DIGITS) + 0.0


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

    Constructed with the owning coordinator (typed as `ShadyCoordinatorLike`
    in `coordinator_like.py`, not the concrete `ShadyCoordinator`);
    `compute()`/`extra_fit()` take no further parameters and resolve
    whatever they need through that reference's public interface,
    covering every diagnostic entity this mode produces in one call
    (ADR-004 §5, fourth Amendment). Encapsulation boundary despite
    dropping purity: a `DiagnosticMode` may use only `coordinator.py`'s
    public (non-`_`-prefixed) interface — extend the coordinator with a
    new accessor rather than reach into private state (ADR-004 §5,
    second Amendment).
    """

    key: ClassVar[str]

    def __init__(self, coordinator: ShadyCoordinatorLike) -> None:
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

    def export_csv(self, sensor_id: str) -> str | None:
        """Optional. A raw-data CSV export of `sensor_id`'s own current
        diagnosed state, for a human to analyse -- one of this mode's
        own declared `sensor_ids()` (ADR-004 §5). Returns `None` if
        `sensor_id` is not one of this mode's own, or if this mode does
        not support export at all (ADR-015 §2, `TASK-0038`). Base
        default: `None`, the same role `None` already plays for
        `extra_fit()` above -- every mode is free to override this or
        not, at zero cost to the ones that don't.

        `http_export.py`'s registered view is this method's only real
        caller, mode-agnostic itself: it resolves *some* `DiagnosticMode`
        (the active one, or an explicit override, ADR-015 §4/§4a) and
        calls `mode.export_csv(sensor_id)` with zero knowledge of what
        the result contains, reporting `HTTPStatus.NOT_FOUND` for `None`.
        """
        return None

    @staticmethod
    def _write_csv_sections(sections: list[tuple[str, list[dict[str, str]]]]) -> str:
        """Format-only helper (ADR-015 §3, `TASK-0038`) shared by every
        concrete mode's own `export_csv` -- a `# name` marker line, a
        header row (the first row's own keys, in insertion order), the
        data rows, then a blank line, repeated per section in the order
        given. Mirrors `_xy_series_entry`'s own placement rationale
        exactly: a `@staticmethod` on the base class specifically so
        every mode gets identical file mechanics for free, without
        importing a sibling mode's module -- never the column
        *content*, which stays entirely each mode's own. Every mode's
        own export's first section is, by convention (not enforced
        here -- a mode-owned choice, ADR-015 §3), `# diagnostic_mode`,
        one column, one row identifying which mode produced the file,
        ahead of everything else, in this exact same shape.

        A section with zero rows still gets its `# name` marker line
        but no header row (nothing to derive one from) -- not expected
        in practice (every section this codebase's one mode produces
        always has at least one row, `CompareRegressionsMode.export_csv`'s
        own `# predictions` section included, since it always has
        exactly the four `regression/` strategies even when their
        accuracy isn't known yet), but handled rather than raising,
        matching ADR-000 §8's clamp-over-exception preference for a
        case this formatting-only helper has no reason to treat as
        invalid.
        """
        buffer = io.StringIO()
        for name, rows in sections:
            buffer.write(f"# {name}\r\n")
            if rows:
                writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
            buffer.write("\r\n")
        return buffer.getvalue()

    @staticmethod
    def _xy_series_entry(
        name: str,
        points: list[list[float]],
        *,
        symbol: str = "circle",
        sizes: Sequence[int] | None = None,
    ) -> dict[str, Any]:
        """`points` (`[[x_i, y_i], ...]`) -> one `series`-attribute entry
        in `custom:plotly-graph`'s own trace shape (ADR-004 §2d,
        2026-09-21 Amendment, `TASK-0015b-patch-3`) — `{"entity": "",
        "name": name, "type": "scatter", "mode": "markers", "x": [...],
        "y": [...], "marker": {...}}`, `entity`/`type`/`mode` constant on
        every entry.
        Lives here rather than in any one concrete mode's own module
        because it's the one shared building block ADR-004 §2/§5 expects
        *every* `DiagnosticMode` to use for its own `series` output —
        `CompareRegressionsMode` (`compare_regressions.py`) is the only
        one that exists yet, but ADR-013's sketched future modes
        (`compare_providers_daily`, a whole-day snapshot mode) will want
        the same shape for the same reason, not a second, possibly
        drifted, reimplementation. A `@staticmethod` (not a module-level
        function, ADR-004 §2d's original home for this) specifically so
        it's inherited automatically — a new mode subclassing
        `DiagnosticMode` gets it via `self._xy_series_entry(...)` with no
        import of `compare_regressions.py` (or anything else
        `CompareRegressionsMode`-specific) needed at all.

        ADR-004 §2h (2026-10-04, `TASK-0015b-patch-4`): every `x`/`y`
        value is rounded to `SERIES_VALUE_DIGITS` decimal places here, so
        no mode can forget to (display-only — callers keep full-precision
        values for everything else), and `marker` is always present:
        `{"symbol": symbol}`, plus `"size": [...]` (one integer per
        point) when `sizes` is given. `symbol` is a Plotly marker symbol
        name; which one an entry gets is the calling mode's decision
        (`CompareRegressionsMode` documents its own), not this shape's.
        """
        assert sizes is None or len(sizes) == len(points), (
            "sizes must hold exactly one entry per point"
        )
        marker: dict[str, Any] = {"symbol": symbol}
        if sizes is not None:
            marker["size"] = list(sizes)
        return {
            "entity": "",
            "name": name,
            "type": "scatter",
            "mode": "markers",
            "x": [_round_value(p[0]) for p in points],
            "y": [_round_value(p[1]) for p in points],
            "marker": marker,
        }
