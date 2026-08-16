# ADR-004 – Diagnostics: Enable Switch and Scatter-Series Sensors (Per-String and Summed)

**Date:** 2026-07-05
**Status:** Accepted

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

### 1 — A dedicated enable switch, default off

A single `ShadyDiagnosticsSwitch` entity (one per config entry) gates all
diagnostic sensors — every per-string `ShadyDiagnosticsSensor` (§2) and
the config-entry-level `ShadyDiagnosticsSumSensor` (§2b) alike. It
defaults to **off**. While off, diagnostic sensors exist (so they don't
appear/disappear from the entity registry, which HA handles awkwardly)
but report `state: "disabled"` with no `series` attribute, and —
importantly — the coordinator does **not** do the extra fitting work
described in §4 while the switch is off. This keeps the cost of
diagnostics at zero for the common case of a user who never turns it on,
following the same "no-op when not configured" pattern already
established for the corrections in ADR-003 §3.

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
    data: [ /* same shape, this slot's -1 neighbor (ADR-001 §3b) */ ],
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
  ADR-001 §3b) — each point is one historical day's `[FC_i, PV_i]` pair
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
`ShadyDiagnosticsSensor`s (§2) and the summed `ShadyDiagnosticsSumSensor`
(§2b) alike, shows the *same* moment: whichever slot `cache.py`'s
`pinned_reference` (ADR-007 §1f) currently names, or "last complete slot"
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
`get_pinned_slot_pool` (ADR-007 §1f) — whether currently pinned or
auto-tracking.** There is no separate today-only call for the
auto-tracking case: `get_pinned_slot_pool` resolves its own window
internally, `[pinned_reference − window_days, pinned_reference]` if a
pin is set to a date no later than today, else `[today − window_days,
today]` — `window_days` sizing the window the same way either time. A
pin to a **future** date is folded into that same `[today − window_days,
today]` case rather than anchored to `pinned_reference`: recalibration
(ADR-002 §1) never trains any slot's model on data newer than
yesterday — not even today's own already-elapsed slots, let alone a
future day, which has no recorded data to train on at all — so there is
no future-anchored pool for a future pin to resolve to in the first
place; a future-pinned slot's `"-1"`/`"0"`/`"1"` series show exactly
what an auto-tracking sensor would already show for that same
time-of-day, right now (ADR-007 §1f). Whether a given call needs a
genuine new recorder fetch or is served entirely from cache depends on
whether that resolved window happens to already be cached, not on
whether a pin is active. While auto-tracking, or pinned to today or a
future date, the resolved window is `[today − window_days, today]` —
exactly what the same day's recalibration already fetched moments
earlier to fit all 288 slots' models, so the call is served from
already-validated cache entries with no new recorder query. **A pin to a
*past* date outside the live window is different: its resolved window
will typically not already be cached, so the same call does trigger a
real fetch for the missing range** —
`cache.py`'s validate-before-read (ADR-007 §1d) handles this the same
as any other cache miss, on the spot. The one residual limitation is
data that was already trimmed *before* the pin was set: `cache.trim()`
(ADR-007 §1a/§1f) only extends its retained floor for a pin that already
existed at trim time, so a timestamp pinned today whose data a
*previous* day's trim already discarded cannot be recovered from the
cache alone — `selected {method}`/`selected actual` still work for such
a slot regardless, as long as the recorder itself still has that slot's
raw `FC`/`PV` history, independent of the pool cache's own retained
window. `selected {method}`/`selected actual` themselves are cheap
either way, pinned or not: evaluating the four already-fitted models at
a historical slot's own `FC` value, and reading that slot's own recorded
`PV`, do not depend on the pool cache at all.

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

Alongside the per-string sensors (§2), one config-entry-level
`ShadyDiagnosticsSumSensor` mirrors ADR-005's `ShadyPvSumSensor`/
`ShadyFcSumSensor` pattern: the same `series`/`accuracy` shape as §2, but
every point is the **pointwise sum across strings** at the one shared
diagnosed slot (§2a) — e.g. the `"0"` series' day-*i* point is
`[Σ FC_i, Σ PV_i]` across all configured strings for that day, not a
concatenation of every string's own points into one bigger cloud. This
is exactly why §2a makes the diagnosed slot config-entry-wide rather than
per-sensor: a pointwise sum across strings is only meaningful if "day
*i*'s point" means the same day and slot for every string being summed.

This sensor does **no new fitting or fetching of its own** — matching
ADR-005's sum sensors being "plain state-tracking aggregates, updating
opportunistically whenever the underlying per-string values change"
rather than independent computations. It reads each per-string sensor's
already-computed series (§2, §2a) and sums them pointwise; `accuracy` is
then computed from those *summed* predicted/actual values (`1 -
|Σ predicted_i − Σ PV_selected| / Σ PV_selected`, same clamping as §2),
not by averaging the per-string accuracy percentages — consistent with
deriving ratios from sums rather than summing ratios, the same principle
ADR-005 applies throughout. It updates on the same triggers as the
per-string sensors it reads (§2a's 5-minute tick while auto-tracking; a
pin update; recalibration for the four fitted-model points), gated by
the same `ShadyDiagnosticsSwitch` (§1).



### 3 — Caching the historical pool: refresh at midnight/system start, not every tick

Re-querying the recorder for a slot's full rolling-window history
(`window_days` samples, ADR-001 §4, times up to `2·smoothing_radius + 1`
slots, ADR-001 §3b) on every 5-minute tick — just to redraw the same
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
(ADR-007 §1f) for the diagnosed slot (and its neighbors) — the **same**
call whether currently pinned or auto-tracking (§2a); there is no
separate today-only accessor diagnostics falls back to. While
auto-tracking, that call's internally-resolved window happens to be
exactly what recalibration already fetched moments earlier, so it costs
nothing extra: no new recorder query, just a read of already-validated
cache entries. While pinned to a date outside the live window, the same
call's resolved window is typically *not* already cached, so it is not
free the same way — see §2a for what that costs. §2b's sum sensor adds
no third call of its own — it reads whichever result the per-string
sensors already got back from `get_pinned_slot_pool` and sums it.

The cache refreshes on exactly the same triggers as the recalibration
that produces it — **midnight or button** (ADR-002 §1) — plus **once at
system start**, since a fresh restart has no recalibration-produced data
yet to retain until the first one runs; a restart also invalidates
`cache.py`'s validated ranges (ADR-007 §1b) for these sensors, so the
first `get_pinned_slot_pool` call after one naturally triggers the
full-history fetch path (ADR-007 §1d) rather than assuming stale
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

### 4 — Extra fitting cost only when the switch is on

Producing the four `"selected {method}"` points requires fitting all four
strategies for the diagnosed slot, not just the one configured default —
extra work beyond what ADR-002 §1's normal recalibration does. This only
happens while the diagnostics switch (§1) is on, and only for the one
diagnosed slot per string (not all 288), keeping the added cost bounded
and opt-in: the three non-default methods are fitted alongside the
active one at the same recalibration trigger (midnight or button, ADR-002
§1). All four are then queried on the same 5-minute trigger that advances
which slot is diagnosed (ADR-006 §1a, per §2 above) — not ADR-002 §2's
irregular baseline-update trigger — so the four predictions always match
whichever slot's pool and actual value are currently being displayed,
rather than momentarily lagging behind it.

### 5 — Module responsibility

`switch.py` adds `ShadyDiagnosticsSwitch`, mirroring the existing
`button.py` pattern (Effy's `EffyRecalculateButton`, ADR-002 §1) for a
simple, single-purpose HA entity with no business logic of its own beyond
toggling a flag the coordinator reads. The retained per-slot pool cache
from §3 lives in `cache.py` (ADR-007), populated by `coordinator.py` as a
side effect of recalibration — not owned by `coordinator.py` directly,
matching every other cache in this design. The accuracy calculation
(`1 - |predicted - actual| / actual`, clamped, per §2) is a pure function
in `aggregation.py`, since it takes plain numbers in and returns a plain
number out, with no HA or per-string knowledge needed; §2b's pointwise
sum-then-accuracy calculation is a second, equally pure function
alongside it, taking each string's already-computed numbers in rather
than reaching back into `regression/` itself. `sensor.py` adds
`ShadyDiagnosticsSensor` (§2, one per string) and
`ShadyDiagnosticsSumSensor` (§2b, one per config entry, following the
six `ShadyPvSumSensor`-style sensors' placement in `sensor.py` per
ADR-005's "Module: a new pure aggregation layer" section), both
staying thin like every other sensor in this design: each reads
`coordinator.py`'s cached pools (from `cache.py`) and the
freshly-computed selected/accuracy values (the sum sensor reading the
per-string sensors' own already-shaped output, not `cache.py` a second
time), and shapes them into the `series`/`accuracy` structure above —
this shaping is pure presentation and does not belong in `regression/` or
`forecast_adjust.py`. The `shady.select_diagnostic_slot` service (§2a) is
registered in `__init__.py` (the usual home for service registration),
is **not** entity-targeted (§2a — there is one diagnosed-slot state per
config entry, not one per sensor), and its handler is a thin wrapper that
validates the timestamp and calls `cache.py`'s `pin_reference`/
`clear_reference` (ADR-007 §1f) directly for that config entry's
coordinator — no new module needed for a single service handler this
small.

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
  (ADR-007 §1d/§1f) otherwise; a future pin is always free the same way
  auto-tracking already is (§2a), since it resolves to the same
  already-cached window.
- **Pro:** Default-off plus the always-on entity / conditionally-computed
  content pattern (§1) keeps the cost at zero for installations that
  never enable it, consistent with ADR-003 §3's no-op philosophy for
  optional features.
- **Pro:** Embedding accuracy directly in each series name (`"selected
  wls2 (96%)"`) means the comparison is visible on the chart itself — no
  separate legend, tooltip, or lookup needed — while the plain-number
  `accuracy` attribute (§2) still gives automations/templates a value to
  read without parsing a formatted string.
- **Pro:** Both the auto-tracking and pinned cases go through the same
  `get_pinned_slot_pool` call (§3, ADR-007 §1f), reusing the exact same
  recorder-reading mechanism (`fetch_fn`/`statistics_during_period`,
  ADR-007 §1d) `coordinator.py` already uses for fitting — the diagnostic
  feature introduces no second way of talking to the recorder, only an
  occasional extra invocation of the one it already has.
- **Pro:** The summed diagnostics sensor (§2b) gives a config-entry-level
  "how did the whole system do" view alongside the per-string detail,
  matching ADR-005's existing sum-sensor pattern, at no extra fitting or
  fetching cost of its own — it only ever sums numbers the per-string
  sensors already computed.
- **Con:** With the switch on, recalibration (ADR-002 §1) does roughly
  4× the fitting work per string (all four methods instead of one) for
  the diagnosed slot — small in absolute terms (one slot, not 288), but
  not free, and scales with the number of configured strings.
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
  same category of concern ADR-001 §5 raises about *other* integrations'
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
