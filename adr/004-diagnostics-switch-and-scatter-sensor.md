# ADR-004 – Diagnostics: Enable Switch and Per-String Scatter-Series Sensor

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
diagnostic sensors (§2). It defaults to **off**. While off, diagnostic
sensors exist (so they don't appear/disappear from the entity registry,
which HA handles awkwardly) but report `state: "disabled"` with no
`series` attribute, and — importantly — the coordinator does **not** do
the extra fitting work described in §3 while the switch is off. This
keeps the cost of diagnostics at zero for the common case of a user who
never turns it on, following the same "no-op when not configured" pattern
already established for the corrections in ADR-003 §3.

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
  for that method. Since the diagnosed slot is always already elapsed
  (see below), `FC_selected` here is that slot's own recorded value —
  the training-time `FC` role from ADR-001 §2, not the forward-looking,
  not-yet-elapsed `FC` a live prediction would query. All four are always
  included regardless of which method is the configured default
  (ADR-001 §2) — the point of this sensor is comparing methods on the
  user's own data, so showing only the active one would defeat it.
  **Accuracy** is `1 - |predicted_i - PV_selected| / PV_selected`, clamped
  to `[0, 1]` before formatting as a percentage (a predicted value more
  than 100% off is displayed as `0%`, not a negative number that would
  need explaining) — recomputed whenever the diagnosed slot changes
  (§2a), since it depends on `PV_selected`, which only exists once that
  slot is complete. The `accuracy` attribute carries the same four
  numbers as plain `0.0`–`1.0` floats, keyed by method name, so the
  series-name string is a display convenience, not the only place this
  value lives. (Named `"selected"`, not `"today"` — see §2a: a manually
  chosen slot need not be from today.)
- **Selected-actual series**, `"selected actual"` — a single-point series
  at `[FC_selected, PV_selected]`, the *real* measured yield for the
  diagnosed slot. This is only possible because of the slot choice below:
  it must already be over.

**Which slot is "the diagnosed slot"** defaults, for a given moment, to
the **last complete** 5-minute slot, not the next upcoming one. A
not-yet-elapsed slot has no actual yield to compare against, so its
diagnostic view could only ever show the four methods disagreeing with
each other, never with reality. Using the most recently finished slot
means `"selected actual"` above is always populated, letting a person
directly see which method's prediction — made using the same historical
pool shown alongside it — actually came closest. This default can be
overridden to inspect a specific past slot instead — see §2a.

### 2a — Manually selecting a specific slot via timestamp

Auto-tracking "the last complete slot" is the default, but a person
debugging a specific event (e.g. "why did the forecast look off around
14:00 yesterday") needs to inspect *that* slot specifically, not whatever
is currently most recent. A service, `shady.select_diagnostic_slot`,
targets one or more `ShadyDiagnosticsSensor` entities (the standard HA
service-target pattern — a person can select all of a config entry's
diagnostic sensors at once, or just one string's) with a single optional
parameter:

- **`timestamp`** (optional, ISO-8601 datetime): pins the targeted
  sensor(s) to the slot containing this timestamp, rounded *down* to the
  nearest 5-minute boundary (matching the slot grid, ADR-001 §3a).
  Rejected with a validation error if the timestamp does not correspond
  to an already-elapsed slot — the whole feature depends on
  `PV_selected` existing (§2), so a future or still-in-progress slot has
  nothing to show. Omitting `timestamp` entirely (or calling the service
  with no parameters) **clears** the pin and returns the targeted
  sensor(s) to auto-tracking "last complete slot".

While pinned, the 5-minute tick (§2's "Refresh cadence") does not advance
the diagnosed slot for that sensor, and effectively becomes a no-op for
it: a manually-selected slot is, by construction, already fully elapsed,
so nothing about its underlying data changes as time passes — there is
nothing to refresh. Pinning one string's sensor does not affect any
other string's, consistent with the service being entity-targeted rather
than a global setting.

**No new data-fetching is needed to support this.** §3's cache already
retains every one of the 288 slots' pools as a byproduct of the day's
recalibration, precisely because fitting all 288 models requires reading
all 288 pools anyway — picking an arbitrary already-cached slot instead
of whichever one auto-tracking would have picked is just a different
lookup key into data that was already there. The same applies to
`selected {method}`/`selected actual`: evaluating the four already-fitted
models at a different historical slot's own `FC` value, and reading that
slot's own recorded `PV`, are the same cheap operations §2 already
performs for the auto-tracked case.

A manually-selected slot from **outside the current rolling window**
(older than `window_days`, ADR-001 §4) will show an empty or stale
slot-pool series, since the cache only retains the current window's
pools — this is an accepted limitation (re-fetching an arbitrary past
window on demand would reintroduce the per-tick recorder load §3 exists
to avoid), not a bug; `selected {method}`/`selected actual` still work
for such a slot as long as the recorder itself still has that slot's raw
`FC`/`PV` history, independent of the pool cache's own window.

**Pinning does not freeze the predictions themselves.** When
recalibration (ADR-002 §1) next runs, the four models refit regardless of
whether any sensor is currently pinned, and a pinned sensor's `selected
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
§1 already introduces (`async_track_time_interval(hass, ...,
minutes=5)`) — advancing which slot is diagnosed, and refreshing
`"selected actual"`/`"selected {method}"`/`accuracy` (all cheap: one
PV/FC lookup plus four model evaluations), on every tick, **for sensors
currently auto-tracking**. A sensor pinned to a manually-selected slot
(§2a) does not advance on this tick at all — see §2a for why that is
correct, not merely skipped. The slot-pool series (`"-1"`/`"0"`/`"1"`) do
**not** get re-queried on this same tick either way — see §3. The four
fitted models behind the `"selected {method}"` points are unaffected by
this faster tick and still only change at ADR-002 §1's cadence, exactly
as §4 describes; only *which* slot's data is being displayed, and that
slot's now-available actual value and accuracy, track the 5-minute tick.

### 3 — Caching the historical pool: refresh at midnight/system start, not every tick

Re-querying the recorder for a slot's full rolling-window history
(`window_days` samples, ADR-001 §4, times up to `2·smoothing_radius + 1`
slots, ADR-001 §3b) on every 5-minute tick — just to redraw the same
`"-1"`/`"0"`/`"1"` series with one slot's worth of difference — would be
wasteful: that data only meaningfully changes once a day, when the
rolling window advances by one calendar day.

This does not need a second recorder-reading mechanism, because the data
required is **exactly what `cache.py`'s `get_slot_pool` accessor already
provides** (ADR-007 §1e) — the same per-slot historical pool
`coordinator.py` reads for every one of the 288 slots during
recalibration (ADR-002 §1), since fitting all 288 slot models
necessarily means reading all 288 pools first. When the diagnostics
switch (§1) is on, the sensor's `"-1"`/`"0"`/`"1"` series are populated by
calling `get_slot_pool` for the diagnosed slot (and its neighbors) — and
because `cache.py`'s validation (ADR-007 §1d) already knows this data was
fetched moments ago for recalibration, this call costs nothing extra: no
new recorder query, just a read of already-validated cache entries.

The cache refreshes on exactly the same triggers as the recalibration
that produces it — **midnight or button** (ADR-002 §1) — plus **once at
system start**, since a fresh restart has no recalibration-produced data
yet to retain until the first one runs; a restart also invalidates
`cache.py`'s validated ranges (ADR-007 §1b) for these sensors, so the
first `get_slot_pool` call after one naturally triggers the full-history
fetch path (ADR-007 §1d) rather than assuming stale in-memory state
survived. The slot-pool series are **not** refreshed on the 5-minute tick
from §2, nor on ADR-002 §2's baseline-update trigger — only recalibration
(or a restart priming it for the first time) changes what they show for
the rest of the day. Turning the diagnostics switch on *between* two
recalibrations means `get_slot_pool` may return mostly-invalidated data
until the next of those triggers fires; the slot-pool series show nothing
new until then, while `"selected {method}"`/`"selected actual"`/`accuracy`
keep working immediately, since those only need the diagnosed slot's own
live `FC`/`PV` values, not the historical pool.

### 4 — Extra fitting cost only when the switch is on

Producing the four `"selected {method}"` points requires fitting all four
strategies for the diagnosed slot, not just the one configured default —
extra work beyond what ADR-002 §1's normal recalibration does. This only
happens while the diagnostics switch (§1) is on, and only for the one
diagnosed slot per string (not all 288), keeping the added cost bounded
and opt-in: the three non-default methods are fitted alongside the
active one at the same recalibration trigger (midnight or button, ADR-002
§1). All four are then queried on the same 5-minute trigger that advances
which slot is diagnosed (ADR-006 §1, per §2 above) — not ADR-002 §2's
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
number out, with no HA or per-string knowledge needed. `sensor.py` adds
`ShadyDiagnosticsSensor`, staying thin like every other sensor in this
design: it reads `coordinator.py`'s cached pools (from `cache.py`) and
the freshly-computed selected/accuracy values, and shapes them into the
`series`/`accuracy` structure above — this shaping is pure presentation
and does not belong in `regression/` or
`forecast_adjust.py`. The `shady.select_diagnostic_slot` service (§2a) is
registered in `__init__.py` (the usual home for service registration)
and its handler is a thin wrapper that validates the timestamp and
delegates to a method on the targeted `ShadyDiagnosticsSensor` entities —
no new module needed for a single service handler this small.

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
  investigating a specific past event, at no extra data-fetching cost
  since §3's cache already holds every slot's pool.
- **Pro:** Default-off plus the always-on entity / conditionally-computed
  content pattern (§1) keeps the cost at zero for installations that
  never enable it, consistent with ADR-003 §3's no-op philosophy for
  optional features.
- **Pro:** Embedding accuracy directly in each series name (`"selected
  wls2 (96%)"`) means the comparison is visible on the chart itself — no
  separate legend, tooltip, or lookup needed — while the plain-number
  `accuracy` attribute (§2) still gives automations/templates a value to
  read without parsing a formatted string.
- **Pro:** Caching the historical pool as a side effect of recalibration
  (§3) means the diagnostic feature adds no new recorder-query pattern to
  the system at all — it reuses data `coordinator.py` was already reading
  for fitting, at the same cadence, at the cost of retaining it in memory
  slightly longer.
- **Con:** With the switch on, recalibration (ADR-002 §1) does roughly
  4× the fitting work per string (all four methods instead of one) for
  the diagnosed slot — small in absolute terms (one slot, not 288), but
  not free, and scales with the number of configured strings.
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
