# ADR-004 – Diagnostics: Selectable Diagnostic Modes and Scatter-Series Sensors (Per-String and Summed)

**Date:** 2026-07-05 **Status:** Accepted **Last updated:** 2026-10-12 —
amendments collapsed into the main text (`TASK-0046`); history lives in git and
the task files

This ADR describes the current design directly. Section numbers are stable; §2c
no longer exists (see Redirects at the end).

______________________________________________________________________

## Context

Throughout this project's design process, understanding *why* a given regression
method produces the forecast it does required building ad-hoc scatter plots of
`(FC, PV)` training points with each method's fitted curve overlaid, evaluated
at today's query point. That exercise — manually repeated several times during
design — is exactly the kind of visual validation a real user would want on
their own real data, not just during design. This ADR turns that ad-hoc process
into a first-class, opt-in diagnostic feature.

______________________________________________________________________

## Decision

### 1 — A dedicated diagnostic-mode select, default off

A single `ShadyDiagnosticModeSelect` entity (one per config entry) gates all
diagnostic sensors — every per-string `ShadyDiagnosticsSensor` (§2) and the
config-entry-level `"sum"` entity (§2b, the same `ShadyDiagnosticsSensor` class)
alike. It defaults to **off**. While off, diagnostic sensors exist (so they
don't appear/disappear from the entity registry, which HA handles awkwardly) but
report `state: "disabled"` with no `series` attribute, and — importantly — the
coordinator does **not** do the extra fitting work described in §4 while no mode
is active. This keeps the cost of diagnostics at zero for the common case of a
user who never enables one, following the same "no-op when not configured"
pattern already established for the corrections in ADR-003a §2 / ADR-003b §2.

Selecting `"compare_regressions"` — the one mode this ADR specifies — activates
exactly the behavior §2/§2a/§2b/§3/§4 describe below, implemented as
`diagnostics/compare_regressions.py`'s `CompareRegressionsMode` (§1a has the
base-class shape). Everything below describes that one mode's behavior.

### 1a — The `DiagnosticMode` interface

The actual diagnostic calculation lives behind a shared base class in a pure
package, `diagnostics/` — mirroring `providers/base.py`'s `Provider` ABC
(ADR-012 §1): a shared base class with required and optional overridable
methods, dispatched off a config value, so a new concrete mode is additive
rather than a rework of the gating mechanism in §1. `coordinator_like.py` (next
to `coordinator.py`, not inside `diagnostics/` — what it describes is
`ShadyCoordinator`'s own shape) holds the input-side contract
(`ShadyCoordinatorLike` and the DTOs its methods return) and
`diagnostics/base.py` holds the output side (the `DiagnosticMode` ABC and its
output dataclasses); `diagnostics/compare_regressions.py` holds this ADR's one
concrete mode, `CompareRegressionsMode`.

```python
@dataclass(frozen=True)
class RegressionSettings:
    """Global scalars string_computation.py's apply_training_
    corrections()/fit_string_model() need — the same five values
    coordinator.py's own default-method 288-slot sweep already
    resolves, exposed read-only so a DiagnosticMode can call those
    same pure functions itself without reaching into coordinator.py's
    private state. Generic, not diagnostics-specific — reusable by
    ADR-013's sketched future modes. Lives here, not in coordinator.py,
    since it exists specifically to cross the DiagnosticMode boundary
    -- and not in string_computation.py/regression/base.py despite the
    name, since its five fields don't map 1:1 onto either module's own
    parameters (three reach regression.base.build_pool only via
    string_computation.fit_string_model's pass-through; two are
    consumed directly by string_computation.apply_training_corrections
    and never reach regression/base.py at all); returned by
    ShadyCoordinatorLike.regression_settings() below."""

    smoothing_radius: int
    neighbor_fitting_cutoff: float
    recency_decay_max: float
    clipping_threshold: float
    max_uplift_c: float


@dataclass(frozen=True)
class StringComputationConfig:
    """One configured string's remaining per-string inputs to
    string_computation.py's functions — everything coordinator.py
    already resolves internally for its own fit, exposed read-only.
    baseline_entity_id/temperature_entity_id/temperature_tier are None
    when unconfigured/unresolved, exactly as coordinator.py's own fit
    already treats them (a None baseline_entity_id means this string
    cannot be fit/diagnosed at all — no baseline forecast to compare
    against). Lives here for the same reason as RegressionSettings
    above -- and not in string_computation.py despite the name, since
    baseline_entity_id/actual_yield_entity_id/temperature_entity_id are
    entity IDs compare_regressions.py uses only to fetch raw series
    from the cache before calling string_computation.py; no string_
    computation.py function signature takes an entity ID at all
    (ADR-014's explicit point of that module); returned by
    ShadyCoordinatorLike.string_computation_config()."""

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
    """Which slot is currently "the diagnosed slot" (§2/§2a) —
    always the coordinator's one stored, currently-configured slot
    (§2g): the pin while pinned, or the last complete slot as of the
    most recent slot trigger (§2i) while auto-tracking. index is the absolute slot index
    (Cache.index_for convention); slot_of_day is index's 0-287
    time-of-day component (get_pinned_slot_pool's own argument);
    is_elapsed is whether this slot's own actual/PV value can exist
    yet — False only for a manually-pinned slot still in the future
    (§2a's one exception to "selected actual"/accuracy being shown).
    Inherently a diagnostics concept, so it lives here rather than in
    coordinator.py, which only resolves it; returned by
    ShadyCoordinatorLike.diagnosed_slot() below."""

    index: int
    slot_of_day: int
    is_elapsed: bool


class ShadyCoordinatorLike(Protocol):
    """The exact subset of ShadyCoordinator's public interface a
    DiagnosticMode is allowed to depend on: cache, strings(), now(),
    diagnosed_slot(), regression_settings(), string_computation_
    config(), target_cell_temperature_for_slot() — nothing wider.
    ShadyCoordinator satisfies this structurally, with no inheritance
    and no import of this module's types required beyond what
    coordinator.py already needs for its own return types. Declaring
    this as a Protocol rather than importing ShadyCoordinator by name
    (even TYPE_CHECKING-only) means diagnostics/ never references
    coordinator.py under any condition, which is what actually
    resolves the coordinator.py <-> diagnostics/ import cycle CodeQL's
    py/unsafe-cyclic-import flags — a TYPE_CHECKING guard is
    runtime-safe (the import never executes), but that query only
    checks whether an import sits lexically outside a def, not
    whether it is further gated on TYPE_CHECKING, so a guarded
    back-reference to coordinator.py still trips it."""

    @property
    def cache(self) -> Cache: ...

    def strings(self) -> list[tuple[int, str]]: ...

    def now(self) -> datetime: ...

    def diagnosed_slot(self, now: datetime | None = None) -> DiagnosedSlot: ...

    def regression_settings(self) -> RegressionSettings: ...

    def string_computation_config(self, string_index: int) -> StringComputationConfig: ...

    def target_cell_temperature_for_slot(self, string_index: int, index: int) -> float | None: ...
```

`diagnostics/base.py`:

```python
DiagnosticCadence = Literal["daily", "hourly", "slot"]


@dataclass(frozen=True)
class DiagnosticSensorResult:
    """One entity's sensor-ready payload. `sensor_id` is however the
    producing mode chooses to identify this entity — a string index as
    text for CompareRegressionsMode, a provider name or a fixed
    sentinel for a future mode (ADR-013). name/unit/device_class are
    optional, plain-str hints sensor.py may use beyond its own
    per-mode defaults."""

    sensor_id: str
    state: str
    attributes: dict[str, Any]
    name: str | None = None
    unit: str | None = None
    device_class: str | None = None


@dataclass(frozen=True)
class DiagnosticResult:
    """A flat, self-identifying collection — however many entities a
    given mode's one compute() call produces and whatever those
    entities represent (one per string, one per provider, one for an
    entire array, ...). Not keyed by string index: that shape was
    tried and did not generalize to ADR-013's non-string-scoped
    sketched modes."""

    sensors: Sequence[DiagnosticSensorResult]


@dataclass(frozen=True)
class DiagnosticFitResult:
    """Every entity's extra-fitting output from one extra_fit() call,
    keyed by sensor_id; the inner mapping is keyed by compared-source
    name (method or provider name). coordinator.py iterates this and
    writes each entry into cache.py — the mode computes, the
    coordinator persists, the same division of labor push() already
    has for a provider's forward() result (ADR-012 §4)."""

    by_sensor: Mapping[str, Mapping[str, float]]


class DiagnosticMode(ABC):
    key: ClassVar[str]

    def __init__(self, coordinator: ShadyCoordinatorLike) -> None:
        """Every concrete mode holds a ShadyCoordinatorLike reference (in
        practice, the owning ShadyCoordinator instance, imported from
        coordinator_like.py TYPE_CHECKING-only -- this module never
        constructs or inspects it, only stores it) and pulls whatever
        coordinator-owned data it needs through self._coordinator, on
        demand — the coordinator never has to anticipate or know what a
        given mode does with it. A mode may only call what
        ShadyCoordinatorLike declares; this is the same *public*-interface
        boundary ADR-000 §5 enforces everywhere else in this codebase,
        now additionally checked by mypy at every call site rather than
        being a convention only. Where a mode needs coordinator-owned
        data with no accessor on ShadyCoordinatorLike yet, both
        ShadyCoordinator's matching public method and ShadyCoordinatorLike
        itself are extended together, as an explicit, reviewed part of
        whichever task needs it, not a silent reach into a
        `_`-prefixed name or an unrelated public method ShadyCoordinatorLike
        doesn't declare."""
        self._coordinator = coordinator

    @abstractmethod
    def fit_cadence(self) -> DiagnosticCadence:
        """How often this mode needs extra_fit() to run. Required, no
        default — core to what the mode is."""

    @abstractmethod
    def compute_cadence(self) -> DiagnosticCadence:
        """How often this mode needs compute() to run. Required, no
        default — core to what the mode is."""

    @abstractmethod
    def sensor_ids(self) -> Sequence[tuple[str, str]]:
        """Every (sensor_id, name) pair this mode's compute() will
        ever produce, resolvable without calling compute() itself —
        cheap and static (no recorder fetch, no fitting), so it can
        run at HA platform-setup time before any mode is necessarily
        active."""

    @abstractmethod
    def compute(self) -> DiagnosticResult:
        """Pure computation over data reached via self._coordinator.
        No parameters — the mode already has everything it needs
        (which slot is diagnosed, string config, the cache) through
        that reference."""

    def extra_fit(self) -> DiagnosticFitResult | None:
        """Optional. Whatever extra per-slot fitting this mode needs
        beyond the default recalibration (ADR-002 §1) — e.g. fitting
        regression/'s other three strategies for the diagnosed slot,
        for CompareRegressionsMode. Run at the recalibration trigger
        while this mode is active. Base default: None — "nothing
        extra needed," generalizing this ADR's §1 zero-cost-when-off
        guarantee to "zero cost for any mode that doesn't need extra
        fitting.\""""
        return None
```

`compute()`/`extra_fit()` are zero-argument by design: a mode that holds its own
coordinator reference has nothing left for a per-call context argument to carry
that it cannot already reach itself, and a single shared instance per mode name
(`coordinator.py`'s `_diagnostic_modes`, an instance attribute built in
`__init__` since construction needs `self`) resolves every configured entity in
one `compute()` call rather than needing one instance per entity.
`fit_cadence()`/`compute_cadence()` are both required, no default, since how
often a mode needs to fit/compute is core to what the mode *is*;
`CompareRegressionsMode` declares both `"slot"` (§4). `DiagnosticMode` also
carries the shared `series`-entry builder `_xy_series_entry` (§2e). `"off"` is a
reserved key in the registry and is never itself registered — the *absence* of
an active mode, not a `DiagnosticMode` subclass with a no-op body, the same way
a provider with nothing to push simply never registers a listener (ADR-012 §4).

`coordinator.py` exposes two generic accessors over this interface, used by
`sensor.py` (§5) rather than any mode-specific code: `diagnostic_result()` — a
cached accessor for the active mode's `compute()` output, refreshed once per
slot job per `compute_cadence()`, invalidated on a mode change or a change of
the diagnosed slot — a pin or following (§2a/§2g) — and
`diagnostic_sensor_ids()` — the union of every *registered* mode's
`sensor_ids()` (not just the active one), so entities stay stable across a
`select.py` mode switch instead of being added/removed dynamically; a
`sensor_id` belonging to a currently-inactive mode simply reads `"unavailable"`
until that mode is selected.

**Accuracy stays in `aggregation.py`, not `diagnostics/`** — its definition
(`1 - |predicted - actual| / actual`, clamped to `[0, 1]`) is independent of
which mode or scope calls it, exactly the same function whether the caller is
comparing regression methods at one slot (this ADR) or across a whole day, or
providers across a whole day (both ADR-013, sketched). Moving it into
`diagnostics/` would have coupled a mode-independent formula to one specific
mode's module for no reason.

### 2 — One scatter-series sensor per configured PV string

Each configured string gets one `ShadyDiagnosticsSensor`, exposing a `series`
attribute pre-shaped for direct use in a `custom:plotly-graph` dashboard card —
no client-side reshaping needed — and an `accuracy` attribute carrying the same
numbers in a form other automations or templates can use directly, without
parsing a series name string. The state itself is a simple timestamp (last
computed); all the content is in the attributes.

The shape of the `series` list and the canonical dashboard template are in §2d.

Each `series` entry is one `plotly-graph` trace:

```yml
series:
  - entity: ""
    name: "0"
    type: scatter
    mode: markers
    x: [16.4, 21.7, 25.4]
    "y": [5.4, 2, 3]
    marker: { symbol: circle, size: [2, 3, 4] } # size follows fit weight (§2h)
    # ...one point per day in the rolling window (ADR-001 §4);
    # shown here with 3 instead of window_days points for brevity
  - entity: ""
    name: "-1"
    type: scatter
    mode: markers
    x: [] # same shape, this slot's -1 neighbor (ADR-011 §1)
    "y": []
    marker: { symbol: line-ns, size: [] } # excluded neighbor (ADR-011 §2) -> stroke
  - entity: ""
    name: "1"
    type: scatter
    mode: markers
    x: [] # same shape, this slot's +1 neighbor
    "y": []
    marker: { symbol: circle, size: [] }
  - entity: ""
    name: selected linear (94%)
    type: scatter
    mode: markers
    x: [21.7]
    "y": [3.1]
    marker: { symbol: x }
  - entity: ""
    name: selected wls2 (96%)
    type: scatter
    mode: markers
    x: [21.7]
    "y": [3.2]
    marker: { symbol: x }
  - entity: ""
    name: selected wls3 (89%)
    type: scatter
    mode: markers
    x: [21.7]
    "y": [3.3]
    marker: { symbol: x }
  - entity: ""
    name: selected kernel (91%)
    type: scatter
    mode: markers
    x: [21.7]
    "y": [3.4]
    marker: { symbol: x }
  - entity: ""
    name: selected actual
    type: scatter
    mode: markers
    x: [21.7]
    "y": [3.15]
    marker: { symbol: x }
```

```js
// accuracy is a separate, unreshaped attribute on the same entity:
accuracy: {
  linear: 0.94,
  wls2: 0.96,
  wls3: 0.89,
  kernel: 0.91,
},
```

Two kinds of series, both keyed by `name` so `plotly-graph` renders each as its
own scatter trace/color:

- **Slot-pool series**, named by signed slot offset relative to the diagnosed
  slot (`"-1"`, `"0"`, `"1"`, … up to ±`smoothing_radius` from ADR-011 §1) —
  each point is one historical day's `[FC_i, PV_i]` pair for that slot, i.e.
  exactly the training data ADR-001 §2's regression actually sees for the
  diagnosed slot's pool. This is the same data a person would otherwise have to
  pull from the recorder by hand to reproduce the plots built during this
  project's own design process.

- **Selected-prediction series**, one per regression method, named
  `"selected {method} ({accuracy}%)"` (`linear`, `kernel`, `wls2`, `wls3`) —
  each a single-point series at `[FC_selected, predicted_i]` for that method.
  `FC_selected` is that slot's own recorded value — the training-time `FC` role
  from ADR-001 §2 — whenever the diagnosed slot has already elapsed, true for
  auto-tracking by construction (see below) and for most manually-pinned slots
  too. For a manually-pinned slot that is still in the future (§2a), there is no
  recorded value yet, so `FC_selected` is instead the same forward-looking,
  not-yet-elapsed `FC` a live prediction for that slot would already query
  (ADR-002 §2/§3) — the four methods are simply evaluated against whichever `FC`
  value actually exists for the slot. All four are always included regardless of
  which method is the configured default (ADR-001 §2) — the point of this sensor
  is comparing methods on the user's own data, so showing only the active one
  would defeat it. **Accuracy** is
  `1 - |predicted_i - PV_selected| / PV_selected`, clamped to `[0, 1]` before
  formatting as a percentage (a predicted value more than 100% off is displayed
  as `0%`, not a negative number that would need explaining) — recomputed
  whenever the diagnosed slot changes (§2a), since it depends on `PV_selected`,
  which only exists once that slot is complete. For a future-pinned slot,
  `PV_selected` does not exist yet, so accuracy cannot be computed at all: the
  series names drop the `(...%)` suffix entirely (`"selected wls2"`, not
  `"selected wls2 (96%)"`), and the `accuracy` attribute is an empty `{}` rather
  than carrying partial or placeholder numbers — see §2a. Otherwise, the
  `accuracy` attribute carries the same four numbers as plain `0.0`–`1.0`
  floats, keyed by method name, so the series-name string is a display
  convenience, not the only place this value lives. (Named `"selected"`, not
  `"today"` — see §2a: a manually chosen slot need not be from today, in either
  direction.)

  **Not to be confused with `confidence` (ADR-001 §2/§2a):** confidence is
  forward-looking and always available — it measures how much training evidence
  backs a slot's fit, independent of whether any particular prediction turned
  out to be right. `accuracy` is backward-looking and diagnostics-only — it
  measures how close a specific prediction actually landed, and only exists once
  the slot has elapsed (or, for a future-pinned slot, not at all — see above). A
  well-supported slot (high confidence) can still have a bad individual
  prediction (low accuracy), and vice versa; the two are deliberately
  independent numbers, not two views of the same thing.

- **Selected-actual series**, `"selected actual"` — a single-point series at
  `[FC_selected, PV_selected]`, the *real* measured yield for the diagnosed
  slot. This depends entirely on the diagnosed slot already being over:
  auto-tracking (below) always satisfies this by construction, and so does most
  manual pinning (§2a). The one exception is a manually-pinned slot still in the
  future — there is no `PV` reading yet, so this series is simply **omitted from
  `series` entirely** (not present with empty `x`/`y` arrays) rather than shown
  with a placeholder point. See §2a for how a future pin is validated and what
  the rest of the sensor shows in that case.

**Which slot is "the diagnosed slot"** defaults, for a given moment, to the
**last complete** 5-minute slot, not the next upcoming one. A not-yet-elapsed
slot has no actual yield to compare against, so its diagnostic view could only
ever show the four methods disagreeing with each other, never with reality.
Using the most recently finished slot means `"selected actual"` above is always
populated, letting a person directly see which method's prediction — made using
the same historical pool shown alongside it — actually came closest. This
default can be overridden to inspect a specific past **or future** slot instead
— see §2a.

### 2a — Manually selecting a specific slot via timestamp

Auto-tracking "the last complete slot" is the default, but a person debugging a
specific event (e.g. "why did the forecast look off around 14:00 yesterday")
needs to inspect *that* slot specifically, not whatever is currently most
recent. `coordinator.py`'s `pin_diagnostic_slot(timestamp)` takes a single
`timestamp`:

- **`timestamp`** (a `datetime`): pins the diagnosed slot to the slot containing
  this timestamp, rounded *down* to the nearest 5-minute boundary (matching the
  slot grid, ADR-001 §3a). Rejected (returns `False`, no state change) if the
  resulting slot falls **beyond the available `FC` data** — i.e. past ADR-002
  §3's forecast horizon (the remainder of today, plus tomorrow if and only if
  the baseline provider has published that far) — since beyond that point there
  is no `FC` value of any kind, not even a forecasted one, for the four methods
  to evaluate. A slot that has not yet elapsed but *is* within that horizon is
  accepted: `"selected {method}"` still renders (§2, evaluated against the
  forward-looking `FC` for that slot), but `"selected actual"` is omitted and
  `accuracy` is an empty `{}`, since there is no `PV` yet to compare against —
  see §2 for the exact shape this takes. Returning to auto-tracking "last
  complete slot" is `set_follow_latest_diagnostic_slot(True)` (§2g); pinning
  (`pin_diagnostic_slot`) in turn switches auto-tracking off.

**There is exactly one diagnosed-slot state per config entry — not one per
sensor.** Every diagnostic sensor, the per-string `ShadyDiagnosticsSensor`s (§2)
and the summed `"sum"` entry (§2b, the same class) alike, shows the *same*
moment: whichever slot `coordinator.py`'s one stored, currently-configured
diagnosed slot names (§2g) — the pin while pinned, the last complete slot as of
the latest slot trigger (§2i) while auto-tracking. There is no per-sensor "is
this one pinned or still auto-tracking" toggle to keep in sync — neither
`datetime.py`'s `ShadyDiagnosticSlotDateTime` nor `switch.py`'s
`ShadyFollowDiagnosticSlotSwitch` (§2g) is targeted at any diagnostic sensor,
since there is only ever one thing, config-entry-wide, for it to affect. This is
also what makes §2b's sum sensor well-defined in the first place: summing
`FC`/`PV` values across strings only makes sense if every string's diagnostic is
looking at the same instant: a per-sensor pin would let strings disagree about
*when*, making a config-entry-level sum meaningless. In practice, one shared
moment also matches the motivating use case directly — "what did every string
look like around 14:00 yesterday" is a cross-string comparison at one moment,
not several strings each frozen at a different, unrelated one.

While pinned, the slot trigger (§2i) never advances *which* slot is diagnosed —
the pin, not the clock, decides that. For an already-elapsed pinned slot,
nothing about its underlying data changes as time passes either, so the trigger
is a true no-op end to end for it. A pinned slot that is still in the future is
the one exception — see "Refresh cadence" below for how that slot's own actual
value and accuracy eventually appear once real time catches up to it, without
the pin having to be re-issued.

**Every diagnostic sensor's slot-pool series comes from one function,
`get_pinned_slot_pool` (ADR-007a §6) — whether currently pinned or
auto-tracking.** There is no separate today-only call for the auto-tracking
case. See ADR-007a §6 for exactly how the function resolves its own window from
`pinned_reference` — including why a pin to a **future** date falls back to the
same window an auto-tracking sensor already uses, since recalibration (ADR-002
§1) never trains on data newer than yesterday, so there is no future-anchored
pool for a future pin to resolve to in the first place. What that resolution
means for this sensor specifically:

- **Auto-tracking, or pinned to today or a future date** — free. The resolved
  window is `[today − window_days, today]`, exactly what the same day's
  recalibration already fetched moments earlier to fit all 288 slots' models, so
  the call is served from already-validated cache entries with no new recorder
  query.
- **Pinned to a past date outside the live window** — not free. The resolved
  window will typically not already be cached, so the call triggers a real
  recorder fetch for the missing range (`cache.py`'s validate-before-read,
  ADR-007a §4, handles this like any other cache miss).
- **Residual limitation:** data already trimmed *before* the pin was set cannot
  be recovered from the cache alone — `cache.trim()` (ADR-007a §1/§6) only
  extends its retained floor for a pin that already existed at trim time.
  `selected {method}`/`selected actual` still work for such a slot regardless,
  as long as the recorder itself still has that slot's raw `FC`/`PV` history —
  they don't depend on the pool cache at all, and are cheap either way, pinned
  or not.

**Pinning does not freeze the predictions themselves.** When recalibration
(ADR-002 §1) next runs, the four models refit regardless of whether a pin is
currently active, and a pinned sensor's `selected {method}`/`accuracy` values
are recomputed against the *newly*-fitted models, still queried at the same
(unchanged) pinned slot's own `FC` value. Only *which slot* stays fixed while
pinned — what the current models say about that slot can still change once a
day, same as it would for an auto-tracking sensor whose slot happened to stay
put.

**Refresh cadence.** Which slot counts as "last complete" changes purely by the
passage of time, so neither ADR-002 §1's daily recalibration nor §2's irregular,
provider-driven baseline-update trigger would keep it current on their own (a
person could be looking at a diagnosed slot up to an hour stale, waiting for the
next baseline update to happen to fire). Rather than add a third schedule, the
diagnostics run on the slot trigger (§2i): on every slot job, **while
auto-tracking**, which slot is diagnosed advances and
`"selected actual"`/`"selected {method}"`/`accuracy` are refreshed (all cheap:
one PV/FC lookup plus four model evaluations per string, then a sum for §2b's
sensor). While pinned, *which* slot is diagnosed never advances — but
`"selected actual"`/`accuracy` still get re-evaluated on each job if the pinned
slot has not elapsed yet. An already-elapsed pinned slot has nothing new to find
(its `PV` was fixed the moment it happened), so the job is a genuine no-op for
it. A future-pinned slot keeps being checked, so `"selected actual"`/`accuracy`
populate — and the series-name accuracy suffix appears — on the first job after
it elapses, without the pin needing to be re-issued. The slot-pool series
(`"-1"`/`"0"`/`"1"`) do **not** get re-queried on the job either way — see §3.
The four fitted models behind the `"selected {method}"` points are unaffected
and still only change at ADR-002 §1's cadence, exactly as §4 describes; only
*which* slot's data is being displayed, and that slot's now-available actual
value and accuracy, track the slot trigger.

### 2b — A summed-up diagnostics sensor across all strings

Alongside the per-string sensors (§2), one `sensor_id="sum"` entity (same
`ShadyDiagnosticsSensor` class — not a dedicated `ShadyDiagnosticsSumSensor`
class) mirrors ADR-005's `ShadyPvSumSensor`/ `ShadyFcSumSensor` pattern: the
same `series`/`accuracy` shape as §2, but every point is the **pointwise sum
across strings** at the one shared diagnosed slot (§2a) — e.g. the `"0"` series'
day-*i* point is `[Σ FC_i, Σ PV_i]` across all configured strings for that day,
not a concatenation of every string's own points into one bigger cloud. This is
exactly why §2a makes the diagnosed slot config-entry-wide rather than
per-sensor: a pointwise sum across strings is only meaningful if "day *i*'s
point" means the same day and slot for every string being summed.

This sensor's `series`/`accuracy` are built by
`CompareRegressionsMode.compute()` itself, from each contributing string's raw
pool data — not assembled in `sensor.py` from the per-string sensors' own
already-computed output, which would be vulnerable to a cross-string
day-alignment bug once two strings' historical data had different gap patterns.
`accuracy` is still computed from *summed* predicted/actual values
(`1 - |Σ predicted_i − Σ PV_selected| / Σ PV_selected`, same clamping as §2),
not by averaging the per-string accuracy percentages — consistent with deriving
ratios from sums rather than summing ratios, the same principle ADR-005 applies
throughout. It updates on the same triggers as the per-string sensors (the slot
trigger, §2i, while auto-tracking; a pin update; recalibration for the four
fitted-model points), gated by the same diagnostic-mode select (§1).

### 2d — Series entry shape and dashboard consumption

Every `series` entry — both kinds in §2 and §2b's pointwise-summed equivalents —
is one `custom:plotly-graph` trace:
`{"entity": "", "name": ..., "type": "scatter", "mode": "markers", "x": [FC_0, FC_1, ...], "y": [PV_0, PV_1, ...], "marker": {...}}`,
the points as two parallel flat arrays because `plotly-graph` takes literal
`x`/`y` arrays per trace and needs no templating once they are supplied. This is
the only format the attribute emits. `custom:plotly-graph` was chosen because
the more common `apexcharts-card` cannot plot a numeric x-axis, which every
series here needs (`FC` on x); do not retry it for this chart.

`entity` is a **constant empty string**, not a self-reference to the sensor —
every point is supplied inline, so nothing is looked up from any entity's state
at render time, but `plotly-graph`'s schema still wants the key per trace.
`type`/`mode` are likewise constant (`"scatter"`/`"markers"`). Because none of
`entity`, `type` or `mode` depends on anything `sensor.py` alone knows,
`diagnostics/` builds the complete entry itself (§2e) and `sensor.py` performs
no reshaping at all (§5). `marker` and the rounding of the values are §2h.
`accuracy` stays a separate, plain `{method: 0.0–1.0}` dict, never series-shaped
(§2).

The canonical dashboard consumption pattern is a single `custom:plotly-graph`
card whose `entities:` key is the *entire* `series` list, handed through Jinja,
with zero manual reshaping:

```yml
type: custom:plotly-graph
title: "{{ entity_name('sensor.string_1_diagnostics') }}"
raw_plotly_config: true
entities: "{{ state_attr('sensor.string_1_diagnostics', 'series') | string | indent(2, first=False) }}"
```

`state_attr(...)` hands the whole `series` list to Jinja as a native Python
object; `| string` renders it with Python's own `repr`-style formatting
(single-quoted strings, bare numbers) — which is also valid YAML flow-sequence
syntax, so the templated `entities:` value parses as a normal YAML list with no
extra work. This is why `series` is a plain list of flat dicts: whatever
round-trips cleanly through `str()` into valid YAML — strings, numbers, lists
and mappings, no booleans or `None`, where Python's `repr` and YAML's flow
syntax would actually diverge — is the design constraint, not any one card's
quirks. `marker` (§2h) is a nested mapping that satisfies it.

**`"y"` must stay an explicitly-quoted string key, in any YAML rendering of this
shape — never write it bare as `y:`.** YAML 1.1 (the schema PyYAML's default
loader uses, and the schema in play wherever the Jinja-rendered `entities:`
template in this section actually gets parsed back into structured data)
resolves the *bare* scalars `y`/`Y`/`yes`/`Yes`/`YES`/`n`/`N`/`no`/`No`/`NO` —
not just `true`/`false` — to booleans. An unquoted `y:` key is therefore not the
string key `"y"` at all, but the boolean key `True`, silently breaking
`plotly-graph`'s own expectation of a `y` field. (Fenced above as
```` ```yml ```` rather than ```` ```yaml ```` specifically so this ADR's own
build tooling — a markdown formatter that reflows fenced YAML — doesn't
"helpfully" strip the quotes it doesn't know are load-bearing here.) On the
Python side, `dict` key `"y"` needs no special handling — `str()`/`repr()`
always quotes a string dict key regardless of its content, so `_xy_series_entry`
(§2e, `diagnostics/base.py`) is safe by construction; this note exists for any
future hand-written YAML — in this ADR or a person's own dashboard —
representing the same shape.

### 2e — The shared entry builder: `DiagnosticMode._xy_series_entry`

`_xy_series_entry(name, points)` lives on `DiagnosticMode`
(`diagnostics/base.py`) as an inherited `@staticmethod`: every concrete mode
gets it without importing `compare_regressions.py` or anything else
mode-specific. `series`'s shape (§2d) belongs to `DiagnosticMode` output in
general, not to comparing regression strategies, and ADR-013 already sketches
future modes (`compare_providers_daily`, a whole-day snapshot mode) that need
exactly this shape; a local copy per mode would risk silent drift. It is not an
`@abstractmethod`: every mode wanting a `plotly-graph`-shaped entry wants the
identical shape, so there is nothing for a subclass to override; a mode
producing a different shape, or no `series` attribute at all, simply does not
call it.

### 2f — Setting the diagnosed slot: the `datetime` entity

`datetime.py`'s `ShadyDiagnosticSlotDateTime` (`DateTimeEntity`), one per config
entry, is how a person pins the diagnosed slot (§2a): `async_set_value` calls
`coordinator.py`'s `pin_diagnostic_slot()` with the rounding and validation
rules §2a specifies, raising `HomeAssistantError` for a timestamp beyond the
forecast horizon. What `native_value` shows is §2g's.

It is an entity rather than a service because every other piece of
config-entry-scoped, person-facing state here (the diagnostic mode, §1; a manual
recalibration, ADR-002 §1/§5) is a thin HA entity — directly pickable from a
dashboard or the entity's own more-info dialog — and a service field has no
date/time picker in Developer Tools. It is entry-scoped: one per config entry,
following the device grouping every other entity uses (`device.py`), so a person
with more than one Shady config entry pins each independently. This project
registers no service of any kind.

### 2g — Following and pinning: the `switch` and the always-set diagnosed slot

A `datetime` entity alone cannot express "stop pinning": Home Assistant's
frontend always feeds the entity's current state back to `datetime.set_value`,
and no control ever sends "no value" (§2f). A one-shot clear button was no
better — it has no state of its own, so nothing on a dashboard says whether the
slot is pinned or following. What is being modelled is one two-valued piece of
state (pinned to a chosen slot / following the newest complete one) plus one
slot value.

- **One always-set value, read unconditionally.** `coordinator.py` holds the
  diagnosed slot as a single stored index, always set, plus a following flag
  (default on). `diagnosed_slot()` — and so every diagnostic computation,
  `compute()` and `extra_fit()` of every mode — reads that stored index whether
  pinned or following; it does not derive "last complete slot" from `now` at
  read time. `is_elapsed` is still computed against `now`.
- **While following, the value is *set* on every slot trigger, not derived on
  read.** The slot trigger (§2i) sets it to `index_for(now) − 1` — first thing
  in the job, ahead of any `extra_fit()`/`compute()` that reads it, and whether
  or not a diagnostic mode is active (one integer assignment, not fitting work,
  so §1's "no extra cost while off" is unaffected). It is also set once at
  construction and immediately when following is switched on. The advance does
  not invalidate the cached `compute()` result; the mode's own
  `compute_cadence()` decides when that refreshes.
- **`ShadyDiagnosticSlotDateTime.native_value` returns that slot's start
  timestamp in both modes** — never `None` — so a dashboard shows the as-of
  timestamp by displaying the entity, with no template logic. Setting it pins
  exactly as §2a/§2f describe and thereby switches following off.
- **`switch.py`'s `ShadyFollowDiagnosticSlotSwitch`, one per config entry.**
  `is_on` means following. Turning it **on** calls
  `set_follow_latest_diagnostic_slot(True)`: clears `cache.pinned_reference`,
  sets the newest complete slot immediately, invalidates the cached `compute()`
  result. Turning it **off** calls `set_follow_latest_diagnostic_slot(False)`:
  pins the slot *as currently shown* (not a re-derivation from `now`), sets
  `cache.pinned_reference` to that slot's date, invalidates the cached result —
  so switching off never moves anything. The coordinator's other accessors are
  `is_following_latest_diagnostic_slot()` and `diagnostic_slot_timestamp()`.
- **`cache.py`'s `pinned_reference` (ADR-007a §6) is deliberately not set while
  following**, even though the stored slot is: `get_pinned_slot_pool`'s cap keys
  off "genuinely pinned" versus not, and its auto-tracking cap
  `index_for(reference) − 1` is only ever a ceiling on the stored slot, so
  nothing about that cap changes.
- **Polling, not push** — like every other entity here (`sensor.py`'s own scope
  note), the datetime and the switch use Home Assistant's default polling; no
  coordinator-to-entity push mechanism exists. The as-of timestamp can lag a
  diagnostic sensor's own attributes by up to one polling interval, exactly as
  two sensors already can.
- **Not persisted across restarts** (the pin never was): a restart returns to
  following the newest complete slot.

### 2h — Chart marker styling

Each `series` entry (§2d) carries one more key, `marker`, and its `x`/`y` values
are rounded for display; the example in §2 shows the result.

- **Values: at most one decimal**, applied in `DiagnosticMode._xy_series_entry`
  (§2e) so every mode and every series — slot-pool and `selected ...` alike —
  gets it. Display-only: `accuracy` (§2), the CSV export (ADR-015) and
  everything fitted keep full precision.
- **Slot-pool points: size follows weight.** A point's marker size scales with
  the weight it has in the fit — the per-point weight from
  `regression.base.build_pool`, taken from its `WeightBreakdown` (ADR-015 §6;
  ADR-001 §2/§4a, ADR-011 §1) so the chart can never drift from what the fit
  actually used. Sizes are whole numbers with a minimum of 1: a low-weight point
  must stay visible, since showing such points is what this chart is for.
- **Excluded neighbor series: a stroke.** A neighbor offset that ADR-011 §2
  excludes from the pool is drawn as a stroke instead of a circle, sized by the
  weight it *would* have had without the exclusion (its pool weight is `0` by
  construction, which would make every stroke invisible). All other pool series
  state `circle` explicitly rather than rely on a default. With
  `neighbor_fitting_cutoff = -1%` (ADR-011 §3, rescale instead of exclude)
  nothing is excluded, so no stroke appears.
- **Selected series: a cross**, at the default size.
- **The `"sum"` entry (§2b)** follows the same rules, evaluated on the same
  pointwise-summed pool its points come from, exactly as if the sum were one
  more string.

### 2i — The slot trigger

Every refresh in this ADR runs on the **slot trigger** defined by ADR-006 §1a:
one slot job per `EVENT_RECORDER_5MIN_STATISTICS_GENERATED`. A wall-clock
interval at an arbitrary phase could read the just-ended slot before the
recorder had compiled its statistic, so the followed slot's `"selected actual"`
and every accuracy value went missing for a whole run (ADR-007a §4). The job
first probes until the newest complete slot's actual yield is readable (bounded:
the first probe plus up to 5 retries, 1 s apart), and only then does, once, in
this order: advance the followed slot (§2g — still *first*, still independent of
whether a mode is active, still an integer assignment), refresh the active
mode's fit/compute per its cadences (§2/§4), and publish the result.
Consequences, all following from "only the with-PV compute exists":

- The followed slot and the chart it feeds advance together, in the same job, so
  the `datetime` entity's "as of" timestamp always matches the chart. While no
  mode is active the advance still runs on every job.
- No result without the newest actual is ever computed *and published* first and
  then replaced: until the job's compute completes, readers keep the previous
  result (a few seconds at most). If a string never delivers, the job publishes
  without it after the bounded retries (§2's existing behavior for a missing
  actual).
- Pinned slots keep their existing semantics (§2a): the job still runs every
  slot, so a future-pinned or in-progress slot's prediction and a just-elapsed
  slot's actual and accuracy appear on the first job after they exist.
- The wall-clock interval remains registered as a watchdog (ADR-006 §1a); it
  runs the same job only when no event-driven job ran for six minutes.
- §3's "not refreshed on every slot job" rule for the slot-pool series is
  unchanged.

### 3 — Caching the historical pool: refresh at midnight/system start, not on every slot job

Re-querying the recorder for a slot's full rolling-window history (`window_days`
samples, ADR-001 §4, times up to `2·smoothing_radius + 1` slots, ADR-011 §1) on
every slot job — just to redraw the same `"-1"`/`"0"`/`"1"` series with one
slot's worth of difference — would be wasteful: that data only meaningfully
changes once a day, when the rolling window advances by one calendar day.

This does not need a second recorder-reading mechanism, because the data
required is **exactly what `cache.py`'s cache already holds** — the same
per-slot historical pool `coordinator.py` reads for every one of the 288 slots
during recalibration (ADR-002 §1), since fitting all 288 slot models necessarily
means reading all 288 pools first. When the mode select (§1) is on
`compare_regressions`, every per-string sensor's `"-1"`/`"0"`/`"1"` series are
populated by calling `get_pinned_slot_pool` (ADR-007a §6) for the diagnosed slot
(and its neighbors) — the **same** call whether currently pinned or
auto-tracking (§2a); there is no separate today-only accessor diagnostics falls
back to. While auto-tracking, that call's internally-resolved window happens to
be exactly what recalibration already fetched moments earlier, so it costs
nothing extra: no new recorder query, just a read of already-validated cache
entries. While pinned to a date outside the live window, the same call's
resolved window is typically *not* already cached, so it is not free the same
way — see §2a for what that costs. §2b's sum entry adds no third fetch of its
own — it is built from the same `_gather_pool` call `compute()` already makes
for each contributing string's own per-string entry, not a separate read.

The cache refreshes on exactly the same triggers as the recalibration that
produces it — **midnight or button** (ADR-002 §1) — plus **once at system
start**, since a fresh restart has no recalibration-produced data yet to retain
until the first one runs; a restart also invalidates `cache.py`'s validated
ranges (ADR-007a §2) for these sensors, so the first `get_pinned_slot_pool` call
after one naturally triggers the full-history fetch path (ADR-007a §4) rather
than assuming stale in-memory state survived. While **auto-tracking**, the
slot-pool series are **not** refreshed on the slot trigger (§2i), nor on ADR-002
§2's baseline-update trigger — only recalibration (or a restart priming it for
the first time) changes what they show for the rest of the day. Selecting a mode
*between* two recalibrations means `get_pinned_slot_pool` may return
mostly-invalidated data until the next of those triggers fires; the slot-pool
series show nothing new until then, while
`"selected {method}"`/`"selected actual"`/`accuracy` keep working immediately,
since those only need the diagnosed slot's own live `FC`/`PV` values, not the
historical pool. While **pinned**, none of this staleness applies — see §2a.

### 4 — Extra fitting cost only while `compare_regressions` is active

Producing the four `"selected {method}"` points requires fitting all four
strategies for the diagnosed slot, not just the one configured default — extra
work beyond what ADR-002 §1's normal recalibration does. This only happens while
the select (§1) is set to `compare_regressions` —
`CompareRegressionsMode.extra_fit()` — and only for the one diagnosed slot per
string (not all 288), keeping the added cost bounded and opt-in: the three
non-default methods are fitted alongside the active one at the same
recalibration trigger (midnight or button, ADR-002 §1). All four are then
queried on the slot trigger (§2i) that advances which slot is diagnosed — not
ADR-002 §2's irregular baseline-update trigger — so the four predictions always
match whichever slot's pool and actual value are currently being displayed,
rather than momentarily lagging behind it.

### 5 — Module responsibility

`select.py` adds `ShadyDiagnosticModeSelect`, a simple, single-purpose HA entity
(`SelectEntity`) with no business logic of its own beyond exposing `const.py`'s
`DIAGNOSTIC_MODES` option list and persisting the chosen option for
`coordinator.py` to read — the same "thin entity glue" philosophy `button.py`'s
`EffyRecalculateButton`-style pattern (ADR-002 §1) already established, just for
a multi-value control instead of a single-purpose trigger. A raw-data CSV export
of a diagnosed slot's training inputs is a sibling concern, delivered through an
HTTP view rather than an entity; see ADR-015.

The actual diagnostic calculation lives in the pure package `diagnostics/` (§1a
has the full `DiagnosticMode` shape): `diagnostics/base.py` holds the shared
`DiagnosticMode` ABC; `diagnostics/compare_regressions.py` holds this ADR's one
concrete mode, `CompareRegressionsMode`. `coordinator.py` holds
`_diagnostic_modes`, a per-instance registry mirroring its
`REGRESSION_STRATEGIES` lookup in shape, and calls the active mode's
`extra_fit()` generically at the recalibration trigger, exactly as it already
runs one generic loop over `forward()`-implementing providers (ADR-012 §4) — the
same "one dispatch site, not one branch per concrete case" shape. That call
takes no arguments: `extra_fit()` resolves whatever it needs itself through the
`ShadyCoordinatorLike` reference it was constructed with (§1a).
`RegressionSettings`/`StringComputationConfig`/`DiagnosedSlot` (§1a) — the
read-only DTOs `ShadyCoordinator`'s
`regression_settings()`/`string_computation_config()`/`diagnosed_slot()` methods
return to satisfy `ShadyCoordinatorLike` — live in `coordinator_like.py`
alongside that Protocol, not in `coordinator.py`: none of the three is used by
`string_computation.py`'s own functions (ADR-014 keeps those decoupled from any
coordinator-owned type, explicit scalar parameters only), so their only real
purpose is crossing the `DiagnosticMode` boundary.

The retained per-slot pool cache from §3 lives in `cache.py` (ADR-007),
populated by `coordinator.py` as a side effect of recalibration — not owned by
`coordinator.py` directly, matching every other cache in this design. The
accuracy calculation (`1 - |predicted - actual| / actual`, clamped, per §2)
stays a pure function in `aggregation.py` — **not** in `diagnostics/`, since it
takes plain numbers in and returns a plain number out, with no per-mode or
per-string knowledge needed, and is therefore reusable by any future
`DiagnosticMode` unchanged (see ADR-013 for two sketched future modes that call
this same function); §2b's pointwise sum-then-accuracy calculation is a second,
equally pure function alongside it, taking each string's already-computed
numbers in rather than reaching back into `regression/` itself. Each
`DiagnosticMode` calls into `aggregation.py` itself, from within its own
`compute()`, having first resolved the predicted/actual values it needs via its
coordinator reference.

`sensor.py` adds `ShadyDiagnosticsSensor`: one generic instance per
`(sensor_id, name)` pair from `coordinator.diagnostic_sensor_ids()` (§2's
per-string ids and §2b's `"sum"` id alike, no dedicated
`ShadyDiagnosticsSumSensor` class), following the six `ShadyPvSumSensor`-style
sensors' placement in `sensor.py` per ADR-005's "Module: a new pure aggregation
layer" section — staying thin like every other sensor in this design. Each
instance looks up its own `sensor_id` in `coordinator.diagnostic_result()` — a
cached accessor over the active mode's `.compute()` output, not a direct call —
and sets `state`/`attributes` straight from the matching entry (the `"sum"`
entry included: built by the mode itself, not reassembled here from sibling
sensors' output); if no mode is active, it reports `disabled` as §1 specifies.
`sensor.py` performs **no reshaping of any kind** on what `diagnostics/` returns
— every `series` entry (§2d, §2h) comes straight from `compute()` unchanged. It
otherwise assembles nothing for the mode to consume, and knows neither how many
entities a mode produces nor what any of them represent beyond a
`(sensor_id, name)` pair: resolving which slot is being diagnosed (reading
`coordinator.diagnosed_slot()`, the one stored, currently-configured slot —
pinned or following alike, §2a/§2g), fetching that slot's pool/predicted/actual
values, and deciding what aggregate entities (if any) to produce alongside the
per-string ones are all the mode's own job, done inside
`compute()`/`extra_fit()`/`sensor_ids()` via the coordinator reference each was
constructed with. This shaping is pure presentation and does not belong in
`regression/` or `forecast_adjust.py`.

`datetime.py`'s `ShadyDiagnosticSlotDateTime` (§2f) and `switch.py`'s
`ShadyFollowDiagnosticSlotSwitch` (§2g), both entity-scoped to their own config
entry, are the only callers of `coordinator.py`'s
`pin_diagnostic_slot`/`set_follow_latest_diagnostic_slot`; `__init__.py`
registers no service of any kind, and `cache.py` is only ever reached through
`coordinator.py` (ADR-007 §2), the same as every other caller.

______________________________________________________________________

## Consequences

- **Pro:** Turns the manual "build a scatter plot to understand this slot's fit"
  exercise from this project's own design process into a standing, opt-in
  feature — the same validation is available to every installation on its own
  real data, not just during development.
- **Pro:** Diagnosing the last complete slot rather than the next upcoming one
  means the sensor always has a real measured value to compare all four methods
  against, not just the four methods disagreeing with each other — turning it
  from "which prediction do I trust" guesswork into a direct accuracy check
  against what just actually happened.
- **Pro:** Showing all four methods' selected-predictions side by side, against
  the real training pool, lets a user judge whether the configured default
  (`wls2`) is behaving sensibly for their specific installation, and switch
  methods (ADR-001 §2, a global setting) with actual evidence rather than
  guessing.
- **Pro:** Manually selecting a slot by timestamp (§2a) turns this from a "what
  does it look like right now" tool into one that can also answer "what did it
  look like at that specific moment" — useful precisely when investigating a
  specific past event — or "what does it look like at an upcoming moment", e.g.
  previewing how the four methods currently disagree on a slot later today or
  tomorrow, without waiting for it to elapse. A past pin costs nothing extra
  when the pinned date is recent enough to already be cached, and at most one
  bounded, on-demand fetch (ADR-007a §4/§6) otherwise; a future pin is always
  free the same way auto-tracking already is (§2a), since it resolves to the
  same already-cached window.
- **Pro:** Default-off plus the always-on entity / conditionally-computed
  content pattern (§1) keeps the cost at zero for installations that never
  enable it, consistent with ADR-003a §2 / ADR-003b §2's no-op philosophy for
  optional features.
- **Pro:** Embedding accuracy directly in each series name
  (`"selected wls2 (96%)"`) means the comparison is visible on the chart itself
  — no separate legend, tooltip, or lookup needed — while the plain-number
  `accuracy` attribute (§2) still gives automations/templates a value to read
  without parsing a formatted string.
- **Pro:** Both the auto-tracking and pinned cases go through the same
  `get_pinned_slot_pool` call (§3, ADR-007a §6), reusing the exact same
  recorder-reading mechanism (`fetch_fn`/`statistics_during_period`, ADR-007a
  §4) `coordinator.py` already uses for fitting — the diagnostic feature
  introduces no second way of talking to the recorder, only an occasional extra
  invocation of the one it already has.
- **Pro:** The summed diagnostics sensor (§2b) gives a config-entry-level "how
  did the whole system do" view alongside the per-string detail, matching
  ADR-005's existing sum-sensor pattern, at no extra fitting or fetching cost of
  its own — it only ever sums numbers the per-string sensors already computed.
- **Con:** With `compare_regressions` active, recalibration (ADR-002 §1) does
  roughly 4× the fitting work per string (all four methods instead of one) for
  the diagnosed slot — small in absolute terms (one slot, not 288), but not
  free, and scales with the number of configured strings.
- **Con:** There is exactly one diagnosed-slot state per config entry (§2a), not
  one per string — a direct trade against the summed sensor (§2b) being
  well-defined at all. A person cannot pin string A to one moment while
  comparing it against string B at a different moment; every currently-pinned
  view, across every string, moves together.
- **Con:** The slot-pool series (§3) can be up to a day stale relative to the
  diagnosed slot's own live position — e.g. right before the next midnight
  recalibration, the cached pool still reflects yesterday's rolling window, not
  one that has already silently advanced by a day. This is a deliberate trade
  for avoiding constant re-querying, but it means the slot-pool series and the
  `"selected {method}"`/`"selected actual"` points are not always drawn from
  windows that agree to the day.
- **Con:** The `series` attribute's shape is a public contract once dashboards
  are built against it, and embedding accuracy in the name
  (`"selected wls2 (96%)"`) makes this sharper than a plain `"selected wls2"`
  would have been: the percentage changes on every slot trigger for
  auto-tracking sensors (§2i), so a dashboard cannot match against an exact
  series name at all — it must match by prefix (`"selected wls2"`) or, better,
  ignore `series` names for programmatic use and read the plain `accuracy`
  attribute instead, which exists precisely to give a stable, unformatted
  alternative. This is the same category of concern ADR-009 raises about *other*
  integrations' attributes — except here it is Shady's own contract to keep
  predictable. A future-pinned slot (§2a) sharpens this further: `accuracy` is
  `{}` and the `"selected actual"` entry is absent from `series` altogether, so
  a consumer needs to treat "not present yet" as a valid state, not just
  anticipate different numbers.
- **Con:** A future-pinned slot (§2a) is a genuinely incomplete view by design —
  `"selected actual"` and `accuracy` are simply unavailable until real time
  catches up to it, and the series-name accuracy suffix disappears along with
  them (§2). Pinning a future slot to "see what the forecast currently looks
  like there" gets exactly that, and nothing that claims to have validated it
  yet.
- **Pro:** The select-plus-base-class design (§1a) turns "add a second
  diagnostic mode" from a rework of a boolean-gated entity and its inline logic
  into an additive change — a new option string, a new `DiagnosticMode`
  subclass, one registry entry. ADR-013's two sketched modes are the validation
  of this: both fit the interface as written, with no further change to
  `diagnostics/base.py`/`coordinator_like.py` needed for either.
- **Con:** `diagnostics/` sits outside ADR-000 §6's zero-mocking test tier —
  every `DiagnosticMode` test needs something satisfying `ShadyCoordinatorLike`
  (§1a) — in practice a real or hand-stubbed `ShadyCoordinator` (the same
  `hass`-stub convention `coordinator.py`'s own tests already use, TASK-0009),
  not a bare dataclass, since a mode holds a live coordinator reference rather
  than being handed a pure input DTO. `test_diagnostics_base.py`'s own
  base-class-shape tests are the one exception: since they exercise only
  `DiagnosticMode`'s shared machinery, never a concrete mode's actual
  coordinator calls, a minimal hand-written stand-in duck-typed against
  `ShadyCoordinatorLike` is enough there.
- **Con:** `DiagnosticMode` depends on `ShadyCoordinatorLike` (§1a) — a
  structural `Protocol` declaring exactly the members a mode may call — rather
  than importing `ShadyCoordinator` by name. This is a real improvement over a
  convention-only boundary (mypy flags a call to any `ShadyCoordinator` public
  method absent from `ShadyCoordinatorLike` as a type error at every call site,
  not just at review time), but it is still not airtight: nothing at *runtime*
  stops a mode from calling a method that happens to exist on whatever concrete
  object was passed in, and a `# type: ignore` can always bypass the check, the
  same category of "runtime-not-enforced contract" ADR-012 §1 already accepts
  for `forward()`'s optionality. Extending `ShadyCoordinatorLike` itself remains
  a deliberate, reviewed step (§1a) — the Protocol changes how a boundary
  violation is *caught*, not who decides where the boundary sits.
- **Pro:** A mode holding its own coordinator reference (§1a) means there is
  exactly one path to a mode's inputs, with nothing to keep in sync between a
  constructor-time reference and a separate per-call DTO — and no need to keep
  extending a shared input dataclass every time a new or changed mode needs one
  more coordinator-owned value.
- **Pro:** `fit_cadence()`/`compute_cadence()` (§1a) give `coordinator.py` a
  generic, declared answer to "how often does this mode need to run," directly
  useful for ADR-013's sketched whole-day modes' unresolved cadence question
  without committing to scheduling them now.

______________________________________________________________________

## Redirects

Sections that no longer exist as headings. A reference to one resolves here
(`python utils/adr_refs.py`, ADR-000 §10).

| Old | Now |
| -- | -- |
| §2c | §2d |

## Citations by amendment name

Some code comments, tests and task files cite former amendments of this ADR by
name, for example "§5, second Amendment". Such a citation is a double hop: it
has to be looked up here to find the real target. **Whenever a text carrying one
is edited for any other reason, replace the citation with the real target
section at the same time.** `utils/adr_refs.py` only checks section references;
these named ones need a search for `Amendment`.

| Cited as | Date | What it changed | Now in |
| -- | -- | -- | -- |
| ADR-004's 2026-08-30 amendment | 2026-08-30 | boolean switch became the mode select plus the `DiagnosticMode` base class | §1, §1a |
| §5 second Amendment | 2026-09-01 | a mode is constructed with its coordinator reference; zero-argument `compute()`/`extra_fit()`; per-call context DTOs removed | §1a, §5 |
| §5 third Amendment | 2026-09-02 | outputs briefly keyed by string index; replaced the same day | not kept |
| §5 fourth Amendment | 2026-09-02 | flat, self-identifying `DiagnosticResult`/`DiagnosticFitResult` | §1a |
| §5 fifth Amendment, "2026-09-03 Amendment" | 2026-09-03 | `sensor_ids()`; one generic sensor per declared id; the `"sum"` entry built by the mode | §1a, §2b, §5 |
| §5 "2026-09-21 Amendment" | 2026-09-21 | `sensor.py` briefly injected `entity` into each entry | not kept; §2d and §5 say `sensor.py` reshapes nothing |
| §2d to §2i Amendments | 2026-09-21 to 2026-10-07 | the sections of that number | the section of that number (§2c: see Redirects) |

## Decision record

Human decisions that shaped the sections above. Details and rationale are in git
and the task files.

| Date | Decision | Section | Task |
| -- | -- | -- | -- |
| 2026-09-21 | `series` shape and dashboard template confirmed against a running instance | §2d | `TASK-0015b-patch-2` |
| 2026-09-21 | the entry builder belongs on `DiagnosticMode` | §2e | `TASK-0015b-patch-3` |
| 2026-09-23 | a `datetime` entity instead of a service | §2f | — |
| 2026-09-24 | follow/pin switch instead of a clear button; the slot is set on every trigger; diagnostics read the configured slot | §2g | `TASK-0037-patch-4` |
| 2026-10-04 | marker styling: one-decimal values, weight-sized points, stroke for excluded neighbors, cross for selected | §2h | `TASK-0015b-patch-4` |
| 2026-10-07 | the recorder-synchronized slot trigger; retry and watchdog parameters confirmed at Gate 2 on 2026-10-08 | §2i | `TASK-0041` |
| 2026-10-12 | the Lead-Agent details of §2g and §2h confirmed; implementation detail kept out of the ADR | §2g, §2h | `TASK-0046` |
