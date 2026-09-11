# ADR-004 – Diagnostics: Selectable Diagnostic Modes and Scatter-Series Sensors (Per-String and Summed)

**Date:** 2026-07-05
**Status:** Accepted
**Last updated:** 2026-09-03

This ADR is kept current in place: §1/§1a describe the current
`ShadyDiagnosticModeSelect` + `DiagnosticMode` design directly (not the
single boolean switch this ADR originally shipped with), §2b/§5
describe the current generic, `sensor_id`-driven sensor.py shape (not
the original dedicated sum-sensor class), and §4 reflects
`compute_cadence()`/`fit_cadence()`-gated caching. See ADR-013 for two
sketched future modes that validate §1a's interface shape against
needs beyond this ADR's own scope.

---

## Context

Throughout this project's design process, understanding *why* a given
regression method produces the forecast it does required building
ad-hoc scatter plots of `(FC, PV)` training points with each method's
fitted curve overlaid, evaluated at today's query point. That exercise —
manually repeated several times during design — is exactly the kind of
visual validation a real user would want on their own real data, not just
during design. This ADR turns that ad-hoc process into a first-class,
opt-in diagnostic feature.

---

## Decision

### 1 — A dedicated diagnostic-mode select, default off

A single `ShadyDiagnosticModeSelect` entity (one per config entry) gates
all diagnostic sensors — every per-string `ShadyDiagnosticsSensor` (§2)
and the config-entry-level `"sum"` entity (§2b, the same
`ShadyDiagnosticsSensor` class as of the 2026-09-03 Amendment) alike. It
defaults to **off**. While off, diagnostic sensors exist (so they don't
appear/disappear from the entity registry, which HA handles awkwardly)
but report `state: "disabled"` with no `series` attribute, and —
importantly — the coordinator does **not** do the extra fitting work
described in §4 while no mode is active. This keeps the cost of
diagnostics at zero for the common case of a user who never enables one,
following the same "no-op when not configured" pattern already
established for the corrections in ADR-003a §2 / ADR-003b §2.

Selecting `"compare_regressions"` — the one mode this ADR specifies —
activates exactly the behavior §2/§2a/§2b/§3/§4 describe below, now
implemented as `diagnostics/compare_regressions.py`'s `CompareRegressionsMode`
(§1a below has the base-class shape). Everything below describes that
one mode's behavior; "the switch" in the historical prose that follows
means "this select set to `compare_regressions`," and "the switch is
off" means "set to `off`" — the underlying behavior is identical to
what shipped in this ADR's original version, only the entity/dispatch
mechanism around it changed.

### 1a — The `DiagnosticMode` interface

The actual diagnostic calculation lives behind a shared base class in a
new pure package, `diagnostics/` — mirroring `providers/base.py`'s
`Provider` ABC (ADR-012 §1): a shared base class with required and
optional overridable methods, dispatched off a config value, so a new
concrete mode is additive rather than a rework of the gating mechanism
in §1. `diagnostics/base.py` holds the ABC and its output dataclasses;
`diagnostics/compare_regressions.py` holds this ADR's one concrete
mode, `CompareRegressionsMode`.

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

    def __init__(self, coordinator: ShadyCoordinator) -> None:
        """Every concrete mode holds the owning ShadyCoordinator
        instance and pulls whatever coordinator-owned data it needs
        (string config, registered FC providers, the cache, or
        anything added to ShadyCoordinator's public interface later)
        directly, on demand, through self._coordinator — the
        coordinator never has to anticipate or know what a given mode
        does with it. The import-level cycle this implies is resolved
        the same way this project's test files resolve a comparable
        problem (ADR-000 §6): a TYPE_CHECKING-only import of
        ShadyCoordinator in diagnostics/base.py, so no runtime import
        statement in diagnostics/ names coordinator.py or
        homeassistant.* directly. A mode may only use coordinator.py's
        *public* interface (no leading underscore) — the same module
        boundary ADR-000 §5 enforces everywhere else in this codebase;
        where a mode needs coordinator-owned data with no public
        accessor yet, the coordinator is extended with one as an
        explicit, reviewed part of whichever task needs it, not a
        silent reach into a `_`-prefixed name."""
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

`compute()`/`extra_fit()` are zero-argument by design: a mode that
holds its own coordinator reference has nothing left for a per-call
context argument to carry that it cannot already reach itself, and a
single shared instance per mode name (`coordinator.py`'s
`_diagnostic_modes`, an instance attribute built in `__init__` since
construction now needs `self`) resolves every configured entity in one
`compute()` call rather than needing one instance per entity.
`fit_cadence()`/`compute_cadence()` are both required, no default,
since how often a mode needs to fit/compute is core to what the mode
*is*; `CompareRegressionsMode` declares both `"slot"` (§4). `"off"` is
a reserved key in the registry and is never itself registered — the
*absence* of an active mode, not a `DiagnosticMode` subclass with a
no-op body, the same way a provider with nothing to push simply never
registers a listener (ADR-012 §4).

`coordinator.py` exposes two generic accessors over this interface,
used by `sensor.py` (§5) rather than any mode-specific code:
`diagnostic_result()` — a cached accessor for the active mode's
`compute()` output, refreshed once per tick per `compute_cadence()`,
invalidated on a mode switch or a diagnosed-slot pin/clear (§2a) — and
`diagnostic_sensor_ids()` — the union of every *registered* mode's
`sensor_ids()` (not just the active one), so entities stay stable
across a `select.py` mode switch instead of being added/removed
dynamically; a `sensor_id` belonging to a currently-inactive mode
simply reads `"unavailable"` until that mode is selected.

**Accuracy stays in `aggregation.py`, not `diagnostics/`** — its
definition (`1 - |predicted - actual| / actual`, clamped to `[0, 1]`)
is independent of which mode or scope calls it, exactly the same
function whether the caller is comparing regression methods at one
slot (this ADR) or across a whole day, or providers across a whole day
(both ADR-013, sketched). Moving it into `diagnostics/` would have
coupled a mode-independent formula to one specific mode's module for
no reason.

### 2 — One scatter-series sensor per configured PV string

Each configured string gets one `ShadyDiagnosticsSensor`, exposing a
`series` attribute pre-shaped for direct use as an ApexCharts scatter
chart `series` option — no client-side reshaping needed — and an
`accuracy` attribute carrying the same numbers in a form other automations
or templates can use directly, without parsing a series name string. The
state itself is a simple timestamp (last computed); all the content is in
the attributes:

```js
series: [
  {
    name: '0',
    data: [
      [16.4, 5.4],
      [21.7, 2],
      [25.4, 3],
      // ...one point per day in the rolling window (ADR-001 §4);
      // shown here with 3 instead of window_days points for brevity
    ],
  },
  {
    name: '-1',
    data: [ /* same shape, this slot's -1 neighbor (ADR-011 §1) */ ],
  },
  {
    name: '1',
    data: [ /* same shape, this slot's +1 neighbor */ ],
  },
  {
    name: 'selected linear (94%)',
    data: [[21.7, 3.1]],
  },
  {
    name: 'selected wls2 (96%)',
    data: [[21.7, 3.2]],
  },
  {
    name: 'selected wls3 (89%)',
    data: [[21.7, 3.3]],
  },
  {
    name: 'selected kernel (91%)',
    data: [[21.7, 3.4]],
  },
  {
    name: 'selected actual',
    data: [[21.7, 3.15]],
  },
],
accuracy: {
  linear: 0.94,
  wls2: 0.96,
  wls3: 0.89,
  kernel: 0.91,
},
```

Two kinds of series, both keyed by `name` so ApexCharts renders each as
its own scatter series/color:

- **Slot-pool series**, named by signed slot offset relative to the
  diagnosed slot (`"-1"`, `"0"`, `"1"`, … up to ±`smoothing_radius` from
  ADR-011 §1) — each point is one historical day's `[FC_i, PV_i]` pair
  for that slot, i.e. exactly the training data ADR-001 §2's regression
  actually sees for the diagnosed slot's pool. This is the same data a
  person would otherwise have to pull from the recorder by hand to
  reproduce the plots built during this project's own design process.
- **Selected-prediction series**, one per regression method, named
  `"selected {method} ({accuracy}%)"` (`linear`, `kernel`, `wls2`,
  `wls3`) — each a single-point series at `[FC_selected, predicted_i]`
  for that method. `FC_selected` is that slot's own recorded value — the
  training-time `FC` role from ADR-001 §2 — whenever the diagnosed slot
  has already elapsed, true for auto-tracking by construction (see
  below) and for most manually-pinned slots too. For a manually-pinned
  slot that is still in the future (§2a), there is no recorded value yet,
  so `FC_selected` is instead the same forward-looking, not-yet-elapsed
  `FC` a live prediction for that slot would already query (ADR-002
  §2/§3) — the four methods are simply evaluated against whichever `FC`
  value actually exists for the slot. All four are always included
  regardless of which method is the configured default (ADR-001 §2) —
  the point of this sensor is comparing methods on the user's own data,
  so showing only the active one would defeat it. **Accuracy** is `1 -
  |predicted_i - PV_selected| / PV_selected`, clamped to `[0, 1]` before
  formatting as a percentage (a predicted value more than 100% off is
  displayed as `0%`, not a negative number that would need explaining)
  — recomputed whenever the diagnosed slot changes (§2a), since it
  depends on `PV_selected`, which only exists once that slot is
  complete. For a future-pinned slot, `PV_selected` does not exist yet,
  so accuracy cannot be computed at all: the series names drop the
  `(...%)` suffix entirely (`"selected wls2"`, not `"selected wls2
  (96%)"`), and the `accuracy` attribute is an empty `{}` rather than
  carrying partial or placeholder numbers — see §2a. Otherwise, the
  `accuracy` attribute carries the same four numbers as plain `0.0`–`1.0`
  floats, keyed by method name, so the series-name string is a display
  convenience, not the only place this value lives. (Named `"selected"`,
  not `"today"` — see §2a: a manually chosen slot need not be from
  today, in either direction.)

  **Not to be confused with `confidence` (ADR-001 §2/§2a):** confidence
  is forward-looking and always available — it measures how much
  training evidence backs a slot's fit, independent of whether any
  particular prediction turned out to be right. `accuracy` is
  backward-looking and diagnostics-only — it measures how close a
  specific prediction actually landed, and only exists once the slot has
  elapsed (or, for a future-pinned slot, not at all — see above). A
  well-supported slot (high confidence) can still have a bad individual
  prediction (low accuracy), and vice versa; the two are deliberately
  independent numbers, not two views of the same thing.
- **Selected-actual series**, `"selected actual"` — a single-point series
  at `[FC_selected, PV_selected]`, the *real* measured yield for the
  diagnosed slot. This depends entirely on the diagnosed slot already
  being over: auto-tracking (below) always satisfies this by
  construction, and so does most manual pinning (§2a). The one exception
  is a manually-pinned slot still in the future — there is no `PV`
  reading yet, so this series is simply **omitted from `series` entirely**
  (not present with an empty `data`) rather than shown with a placeholder
  point. See §2a for how a future pin is validated and what the rest of
  the sensor shows in that case.

**Which slot is "the diagnosed slot"** defaults, for a given moment, to
the **last complete** 5-minute slot, not the next upcoming one. A
not-yet-elapsed slot has no actual yield to compare against, so its
diagnostic view could only ever show the four methods disagreeing with
each other, never with reality. Using the most recently finished slot
means `"selected actual"` above is always populated, letting a person
directly see which method's prediction — made using the same historical
pool shown alongside it — actually came closest. This default can be
overridden to inspect a specific past **or future** slot instead — see
§2a.

### 2a — Manually selecting a specific slot via timestamp

Auto-tracking "the last complete slot" is the default, but a person
debugging a specific event (e.g. "why did the forecast look off around
14:00 yesterday") needs to inspect *that* slot specifically, not whatever
is currently most recent. A service, `shady.select_diagnostic_slot`,
takes a single optional parameter:

- **`timestamp`** (optional, ISO-8601 datetime): pins the diagnosed slot
  to the slot containing this timestamp, rounded *down* to the nearest
  5-minute boundary (matching the slot grid, ADR-001 §3a). Rejected with
  a validation error if the resulting slot falls **beyond the available
  `FC` data** — i.e. past ADR-002 §3's forecast horizon (the remainder of
  today, plus tomorrow if and only if the baseline provider has published
  that far) — since beyond that point there is no `FC` value of any kind,
  not even a forecasted one, for the four methods to evaluate. A slot
  that has not yet elapsed but *is* within that horizon is accepted:
  `"selected {method}"` still renders (§2, evaluated against the
  forward-looking `FC` for that slot), but `"selected actual"` is
  omitted and `accuracy` is an empty `{}`, since there is no `PV` yet to
  compare against — see §2 for the exact shape this takes. Omitting
  `timestamp` entirely (or calling the service with no parameters)
  **clears** the pin and returns to auto-tracking "last complete slot".

**There is exactly one diagnosed-slot state per config entry — not one
per sensor.** Every diagnostic sensor, the per-string
`ShadyDiagnosticsSensor`s (§2) and the summed `"sum"` entry (§2b,
the same class as of the 2026-09-03 Amendment) alike, shows the *same*
moment: whichever slot `cache.py`'s
`pinned_reference` (ADR-007a §6) currently names, or "last complete slot"
if it is unset. There is no per-sensor "is this one pinned or still
auto-tracking" toggle to keep in sync — the service is not entity-
targeted at all, since there is only ever one thing, config-entry-wide,
for it to affect. This is also what makes §2b's sum sensor well-defined
in the first place: summing `FC`/`PV` values across strings only makes
sense if every string's diagnostic is looking at the same instant: a
per-sensor pin would let strings disagree about *when*, making a
config-entry-level sum meaningless. In practice, one shared moment also
matches the motivating use case directly — "what did every string look
like around 14:00 yesterday" is a cross-string comparison at one moment,
not several strings each frozen at a different, unrelated one.

While pinned, the 5-minute tick (§2's "Refresh cadence") never advances
*which* slot is diagnosed — the pin, not the clock, decides that. For an
already-elapsed pinned slot, nothing about its underlying data changes as
time passes either, so the tick is a true no-op end to end, same as
before. A pinned slot that is still in the future is the one exception —
see "Refresh cadence" below for how that slot's own actual value and
accuracy eventually appear once real time catches up to it, without the
pin having to be re-issued.

**Every diagnostic sensor's slot-pool series comes from one function,
`get_pinned_slot_pool` (ADR-007a §6) — whether currently pinned or
auto-tracking.** There is no separate today-only call for the
auto-tracking case. See ADR-007a §6 for exactly how the function
resolves its own window from `pinned_reference` — including why a pin to
a **future** date falls back to the same window an auto-tracking sensor
already uses, since recalibration (ADR-002 §1) never trains on data
newer than yesterday, so there is no future-anchored pool for a future
pin to resolve to in the first place. What that resolution means for
this sensor specifically:

- **Auto-tracking, or pinned to today or a future date** — free. The
  resolved window is `[today − window_days, today]`, exactly what the
  same day's recalibration already fetched moments earlier to fit all
  288 slots' models, so the call is served from already-validated cache
  entries with no new recorder query.
- **Pinned to a past date outside the live window** — not free. The
  resolved window will typically not already be cached, so the call
  triggers a real recorder fetch for the missing range (`cache.py`'s
  validate-before-read, ADR-007a §4, handles this like any other cache
  miss).
- **Residual limitation:** data already trimmed *before* the pin was set
  cannot be recovered from the cache alone — `cache.trim()` (ADR-007a
  §1/§6) only extends its retained floor for a pin that already
  existed at trim time. `selected {method}`/`selected actual` still work
  for such a slot regardless, as long as the recorder itself still has
  that slot's raw `FC`/`PV` history — they don't depend on the pool
  cache at all, and are cheap either way, pinned or not.

**Pinning does not freeze the predictions themselves.** When
recalibration (ADR-002 §1) next runs, the four models refit regardless of
whether a pin is currently active, and a pinned sensor's `selected
{method}`/`accuracy` values are recomputed against the *newly*-fitted
models, still queried at the same (unchanged) pinned slot's own `FC`
value. Only *which slot* stays fixed while pinned — what the current
models say about that slot can still change once a day, same as it
would for an auto-tracking sensor whose slot happened to stay put.

**Refresh cadence.** Which slot counts as "last complete" changes purely
by the passage of time — every 5 minutes, independent of any event — so
neither ADR-002 §1's daily recalibration nor §2's irregular,
provider-driven baseline-update trigger would keep it current on their
own (a person could be looking at a diagnosed slot up to an hour stale,
waiting for the next baseline update to happen to fire). Rather than add
a third schedule, this reuses the 5-minute recorder-poll trigger ADR-006
§1a already introduces (`async_track_time_interval(hass, ...,
minutes=5)`) — advancing which slot is diagnosed, and refreshing
`"selected actual"`/`"selected {method}"`/`accuracy` (all cheap: one
PV/FC lookup plus four model evaluations per string, then a sum for
§2b's sensor) on every tick, **while auto-tracking**. While pinned
(§2a), *which* slot is diagnosed never advances on this tick — but
`"selected actual"`/`accuracy` still get re-evaluated on the same tick
if the pinned slot has not elapsed yet. An already-elapsed pinned slot
has nothing new to find (its `PV` was fixed the moment it happened), so
the tick is a genuine no-op for it, same as before this ADR's change. A
future-pinned slot's tick keeps checking whether it has elapsed yet, so
`"selected actual"`/`accuracy` populate — and the series-name accuracy
suffix appears — on the first tick after it does, without the pin
needing to be re-issued. The slot-pool series (`"-1"`/`"0"`/`"1"`) do
**not** get re-queried on this same tick either way — see §3. The four
fitted models behind the `"selected {method}"` points are unaffected by
this faster tick and still only change at ADR-002 §1's cadence, exactly
as §4 describes; only *which* slot's data is being displayed, and that
slot's now-available actual value and accuracy, track the 5-minute
tick.

### 2b — A summed-up diagnostics sensor across all strings

Alongside the per-string sensors (§2), one `sensor_id="sum"` entity
(same `ShadyDiagnosticsSensor` class, per §5's 2026-09-03 revision —
not a dedicated `ShadyDiagnosticsSumSensor` class) mirrors ADR-005's
`ShadyPvSumSensor`/
`ShadyFcSumSensor` pattern: the same `series`/`accuracy` shape as §2, but
every point is the **pointwise sum across strings** at the one shared
diagnosed slot (§2a) — e.g. the `"0"` series' day-*i* point is
`[Σ FC_i, Σ PV_i]` across all configured strings for that day, not a
concatenation of every string's own points into one bigger cloud. This
is exactly why §2a makes the diagnosed slot config-entry-wide rather than
per-sensor: a pointwise sum across strings is only meaningful if "day
*i*'s point" means the same day and slot for every string being summed.

This sensor's `series`/`accuracy` are built by
`CompareRegressionsMode.compute()` itself, from each contributing
string's raw pool data — not assembled in `sensor.py` from the
per-string sensors' own already-computed output, since the original
approach here was vulnerable to a cross-string day-alignment bug once
two strings' historical data had different gap patterns. `accuracy` is
still computed from *summed*
predicted/actual values (`1 - |Σ predicted_i − Σ PV_selected| /
Σ PV_selected`, same clamping as §2), not by averaging the per-string
accuracy percentages — consistent with deriving ratios from sums rather
than summing ratios, the same principle ADR-005 applies throughout,
unchanged by the 2026-09-03 revision. It updates on the same triggers
as the per-string sensors (§2a's 5-minute tick while auto-tracking; a
pin update; recalibration for the four fitted-model points), gated by
the same diagnostic-mode select (§1).



### 3 — Caching the historical pool: refresh at midnight/system start, not every tick

Re-querying the recorder for a slot's full rolling-window history
(`window_days` samples, ADR-001 §4, times up to `2·smoothing_radius + 1`
slots, ADR-011 §1) on every 5-minute tick — just to redraw the same
`"-1"`/`"0"`/`"1"` series with one slot's worth of difference — would be
wasteful: that data only meaningfully changes once a day, when the
rolling window advances by one calendar day.

This does not need a second recorder-reading mechanism, because the data
required is **exactly what `cache.py`'s cache already holds** — the same
per-slot historical pool `coordinator.py` reads for every one of the 288
slots during recalibration (ADR-002 §1), since fitting all 288 slot
models necessarily means reading all 288 pools first. When the
diagnostics switch (§1) is on, every per-string sensor's
`"-1"`/`"0"`/`"1"` series are populated by calling `get_pinned_slot_pool`
(ADR-007a §6) for the diagnosed slot (and its neighbors) — the **same**
call whether currently pinned or auto-tracking (§2a); there is no
separate today-only accessor diagnostics falls back to. While
auto-tracking, that call's internally-resolved window happens to be
exactly what recalibration already fetched moments earlier, so it costs
nothing extra: no new recorder query, just a read of already-validated
cache entries. While pinned to a date outside the live window, the same
call's resolved window is typically *not* already cached, so it is not
free the same way — see §2a for what that costs. §2b's sum entry adds
no third fetch of its own — as of the 2026-09-03 Amendment, it's built
from the same `_gather_pool` call `compute()` already makes for each
contributing string's own per-string entry, not a separate read.

The cache refreshes on exactly the same triggers as the recalibration
that produces it — **midnight or button** (ADR-002 §1) — plus **once at
system start**, since a fresh restart has no recalibration-produced data
yet to retain until the first one runs; a restart also invalidates
`cache.py`'s validated ranges (ADR-007a §2) for these sensors, so the
first `get_pinned_slot_pool` call after one naturally triggers the
full-history fetch path (ADR-007a §4) rather than assuming stale
in-memory state survived. While **auto-tracking**, the slot-pool series
are **not** refreshed on the 5-minute tick from §2, nor on ADR-002 §2's
baseline-update trigger — only recalibration (or a restart priming it
for the first time) changes what they show for the rest of the day.
Turning the diagnostics switch on *between* two recalibrations means
`get_pinned_slot_pool` may return mostly-invalidated data until the next
of those triggers fires; the slot-pool series show nothing new until
then, while `"selected {method}"`/`"selected actual"`/`accuracy` keep
working immediately, since those only need the diagnosed slot's own live
`FC`/`PV` values, not the historical pool. While **pinned**, none of
this staleness applies — see §2a.

### 4 — Extra fitting cost only while `compare_regressions` is active

Producing the four `"selected {method}"` points requires fitting all four
strategies for the diagnosed slot, not just the one configured default —
extra work beyond what ADR-002 §1's normal recalibration does. This only
happens while the select (§1) is set to `compare_regressions` — as of the
2026-08-30 amendment, `CompareRegressionsMode.extra_fit()` — and only for
the one diagnosed slot per string (not all 288), keeping the added cost
bounded and opt-in: the three non-default methods are fitted alongside
the active one at the same recalibration trigger (midnight or button,
ADR-002 §1). All four are then queried on the same 5-minute trigger that
advances which slot is diagnosed (ADR-006 §1a, per §2 above) — not
ADR-002 §2's irregular baseline-update trigger — so the four predictions
always match whichever slot's pool and actual value are currently being
displayed, rather than momentarily lagging behind it.

### 5 — Module responsibility

`select.py` adds `ShadyDiagnosticModeSelect`, a simple, single-purpose HA
entity (`SelectEntity`) with no business logic of its own beyond exposing
`const.py`'s `DIAGNOSTIC_MODES` option list and persisting the chosen
option for `coordinator.py` to read — the same "thin entity glue"
philosophy `button.py`'s `EffyRecalculateButton`-style pattern (ADR-002
§1) already established, just for a multi-value control instead of a
single-purpose trigger. The actual diagnostic calculation lives in the new
pure package `diagnostics/` (§1a has the full `DiagnosticMode` shape):
`diagnostics/base.py` holds the shared `DiagnosticMode` ABC; `diagnostics/
compare_regressions.py` holds this ADR's one concrete mode,
`CompareRegressionsMode`. `coordinator.py` holds `_diagnostic_modes` (a
per-instance registry as of the 2026-09-01 amendment — mirroring its
existing `REGRESSION_STRATEGIES` lookup in shape) and calls the active
mode's `extra_fit()` generically at the recalibration trigger, exactly as
it already runs one generic loop over `forward()`-implementing providers
(ADR-012 §4) — same "one dispatch site, not one branch per concrete case"
shape. As of 2026-09-01, that call takes no arguments — `extra_fit()`
resolves whatever it needs itself through the `ShadyCoordinator` reference
it was constructed with, rather than `coordinator.py` assembling anything
for it first.

The retained per-slot pool cache from §3 lives in `cache.py` (ADR-007),
populated by `coordinator.py` as a side effect of recalibration — not
owned by `coordinator.py` directly, matching every other cache in this
design. The accuracy calculation (`1 - |predicted - actual| / actual`,
clamped, per §2) stays a pure function in `aggregation.py` — **not** in
`diagnostics/`, since it takes plain numbers in and returns a plain
number out, with no per-mode or per-string knowledge needed, and is
therefore reusable by any future `DiagnosticMode` unchanged (see ADR-013
for two sketched future modes that call this same function); §2b's
pointwise sum-then-accuracy calculation is a second, equally pure
function alongside it, taking each string's already-computed numbers in
rather than reaching back into `regression/` itself. As of 2026-09-01,
each `DiagnosticMode` calls into `aggregation.py` itself, from within its
own `compute()`, having first resolved the predicted/actual values it
needs via its coordinator reference — `aggregation.py`'s functions
themselves are untouched by this amendment.

`sensor.py` adds `ShadyDiagnosticsSensor` — as of 2026-09-03, one
generic instance per `(sensor_id, name)` pair from
`coordinator.diagnostic_sensor_ids()` (§2's per-string ids and §2b's
`"sum"` id alike, no dedicated `ShadyDiagnosticsSumSensor` class),
following the six `ShadyPvSumSensor`-style sensors' placement in
`sensor.py` per ADR-005's "Module: a new pure aggregation layer"
section — staying thin like every other sensor in this design. **As of
2026-09-01, this got thinner still, and as of 2026-09-03, thinner
again:** each instance looks up its own `sensor_id` in
`coordinator.diagnostic_result()` — a cached accessor over the active
mode's `.compute()` output, not a direct call — and sets
`state`/`attributes` straight from the matching entry (the `"sum"`
entry included: built by the mode itself now, not reassembled here from
sibling sensors' output); if no mode is active, it reports `disabled`
as §1 specifies. `sensor.py` no longer assembles anything for the mode
to consume, nor knows how many entities a mode produces or what any of
them represent beyond a `(sensor_id, name)` pair — resolving which slot
is being diagnosed (reading `cache.py`'s `pinned_reference` scalar via
its coordinator reference, or falling back to the last-complete-slot
default when unset, §2a), fetching that slot's pool/predicted/actual
values, and deciding what aggregate entities (if any) to produce
alongside the per-string ones are all the mode's own job, done inside
`compute()`/`extra_fit()`/`sensor_ids()` via the coordinator reference
each was constructed with. This shaping is pure presentation and does
not belong in `regression/` or `forecast_adjust.py`. The
`shady.select_diagnostic_slot` service (§2a) is registered in
`__init__.py` (the usual home for service registration), is **not**
entity-targeted (§2a — there is one diagnosed-slot state per config
entry, not one per sensor), and its handler is a thin wrapper that
validates the timestamp and calls that config entry's coordinator, which
in turn forwards to `cache.py`'s `pin_reference`/`clear_reference`
(ADR-007a §6) — `cache.py` is still only ever reached through
`coordinator.py` (ADR-007 §2), the same as every other caller; `__init__.py`
does not reach into `cache.py` directly, and no new module is needed for
a single service handler this small.

---

## Consequences

- **Pro:** Turns the manual "build a scatter plot to understand this
  slot's fit" exercise from this project's own design process into a
  standing, opt-in feature — the same validation is available to every
  installation on its own real data, not just during development.
- **Pro:** Diagnosing the last complete slot rather than the next upcoming
  one means the sensor always has a real measured value to compare all
  four methods against, not just the four methods disagreeing with each
  other — turning it from "which prediction do I trust" guesswork into a
  direct accuracy check against what just actually happened.
- **Pro:** Showing all four methods' selected-predictions side by side,
  against the real training pool, lets a user judge whether the
  configured default (`wls2`) is behaving sensibly for their specific
  installation, and switch methods (ADR-001 §2, a global setting) with
  actual evidence rather than guessing.
- **Pro:** Manually selecting a slot by timestamp (§2a) turns this from a
  "what does it look like right now" tool into one that can also answer
  "what did it look like at that specific moment" — useful precisely when
  investigating a specific past event — or "what does it look like at an
  upcoming moment", e.g. previewing how the four methods currently
  disagree on a slot later today or tomorrow, without waiting for it to
  elapse. A past pin costs nothing extra when the pinned date is recent
  enough to already be cached, and at most one bounded, on-demand fetch
  (ADR-007a §4/§6) otherwise; a future pin is always free the same way
  auto-tracking already is (§2a), since it resolves to the same
  already-cached window.
- **Pro:** Default-off plus the always-on entity / conditionally-computed
  content pattern (§1) keeps the cost at zero for installations that
  never enable it, consistent with ADR-003a §2 / ADR-003b §2's no-op
  philosophy for optional features.
- **Pro:** Embedding accuracy directly in each series name (`"selected
  wls2 (96%)"`) means the comparison is visible on the chart itself — no
  separate legend, tooltip, or lookup needed — while the plain-number
  `accuracy` attribute (§2) still gives automations/templates a value to
  read without parsing a formatted string.
- **Pro:** Both the auto-tracking and pinned cases go through the same
  `get_pinned_slot_pool` call (§3, ADR-007a §6), reusing the exact same
  recorder-reading mechanism (`fetch_fn`/`statistics_during_period`,
  ADR-007a §4) `coordinator.py` already uses for fitting — the diagnostic
  feature introduces no second way of talking to the recorder, only an
  occasional extra invocation of the one it already has.
- **Pro:** The summed diagnostics sensor (§2b) gives a config-entry-level
  "how did the whole system do" view alongside the per-string detail,
  matching ADR-005's existing sum-sensor pattern, at no extra fitting or
  fetching cost of its own — it only ever sums numbers the per-string
  sensors already computed.
- **Con:** With `compare_regressions` active, recalibration (ADR-002 §1)
  does roughly 4× the fitting work per string (all four methods instead
  of one) for the diagnosed slot — small in absolute terms (one slot, not
  288), but not free, and scales with the number of configured strings.
- **Con:** There is exactly one diagnosed-slot state per config entry
  (§2a), not one per string — a direct trade against the summed sensor
  (§2b) being well-defined at all. A person cannot pin string A to one
  moment while comparing it against string B at a different moment; every
  currently-pinned view, across every string, moves together.
- **Con:** The slot-pool series (§3) can be up to a day stale relative to
  the diagnosed slot's own live position — e.g. right before the next
  midnight recalibration, the cached pool still reflects yesterday's
  rolling window, not one that has already silently advanced by a day.
  This is a deliberate trade for avoiding constant re-querying, but it
  means the slot-pool series and the `"selected {method}"`/`"selected actual"`
  points are not always drawn from windows that agree to the day.
- **Con:** The `series` attribute's shape is a public contract once
  dashboards are built against it, and embedding accuracy in the name
  (`"selected wls2 (96%)"`) makes this sharper than a plain `"selected
  wls2"` would have been: the percentage changes on every 5-minute tick
  for auto-tracking sensors (§2), so a dashboard cannot match against an
  exact series name at all — it must match by prefix (`"selected wls2"`)
  or, better, ignore `series` names for programmatic use and read the
  plain `accuracy` attribute instead, which
  exists precisely to give a stable, unformatted alternative. This is the
  same category of concern ADR-009 raises about *other* integrations'
  attributes — except here it is Shady's own contract to keep predictable.
  A future-pinned slot (§2a) sharpens this further: `accuracy` is `{}`
  and the `"selected actual"` entry is absent from `series` altogether,
  so a consumer needs to treat "not present yet" as a valid state, not
  just anticipate different numbers.
- **Con:** A future-pinned slot (§2a) is a genuinely incomplete view by
  design — `"selected actual"` and `accuracy` are simply unavailable
  until real time catches up to it, and the series-name accuracy suffix
  disappears along with them (§2). Pinning a future slot to "see what the
  forecast currently looks like there" gets exactly that, and nothing
  that claims to have validated it yet.
- **Pro:** The select-plus-base-class design (§1a) turns "add a second
  diagnostic mode" from a rework of a boolean-gated entity and its
  inline logic into an additive change — a new option string, a new
  `DiagnosticMode` subclass, one registry entry. ADR-013's two sketched
  modes are the validation of this: both fit the interface as written,
  with no further change to `diagnostics/base.py` needed for either.
- **Con:** `diagnostics/` sits outside ADR-000 §6's zero-mocking test
  tier — every `DiagnosticMode` test needs a real or hand-stubbed
  `ShadyCoordinator` (the same `hass`-stub convention `coordinator.py`'s
  own tests already use, TASK-0009), not a bare dataclass, since a mode
  holds a live coordinator reference (§1a) rather than being handed a
  pure input DTO.
- **Con:** A `DiagnosticMode` can, in principle, reach any public
  method `ShadyCoordinator` exposes (§1a) — the boundary that keeps
  this disciplined (only public, non-`_`-prefixed access; extend the
  coordinator's public surface deliberately rather than reaching into
  private state) is a convention this ADR states, not one the type
  system enforces, the same category of "runtime-not-enforced
  contract" ADR-012 §1 already accepts for `forward()`'s optionality.
- **Pro:** A mode holding its own coordinator reference (§1a) means
  there is exactly one path to a mode's inputs, with nothing to keep in
  sync between a constructor-time reference and a separate per-call
  DTO — and no need to keep extending a shared input dataclass every
  time a new or changed mode needs one more coordinator-owned value.
- **Pro:** `fit_cadence()`/`compute_cadence()` (§1a) give
  `coordinator.py` a generic, declared answer to "how often does this
  mode need to run," directly useful for ADR-013's sketched whole-day
  modes' unresolved cadence question without committing to scheduling
  them now.
