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
chart `series` option — no client-side reshaping needed. The state itself
is a simple timestamp (last computed); all the content is in the
attribute:

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
    name: 'today linear',
    data: [[21.7, 3.1]],
  },
  {
    name: 'today wls2',
    data: [[21.7, 3.2]],
  },
  {
    name: 'today wls3',
    data: [[21.7, 3.3]],
  },
  {
    name: 'today kernel',
    data: [[21.7, 3.4]],
  },
],
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
- **Today-prediction series**, one per regression method, named
  `"today {method}"` (`linear`, `kernel`, `wls2`, `wls3`) — each a
  single-point series at `[FC_today, predicted_i]` for that method. All
  four are always included regardless of which method is the
  configured default (ADR-001 §2) — the point of this sensor is
  comparing methods on the user's own data, so showing only the active
  one would defeat it.

**Which slot is "the diagnosed slot"** for a given moment defaults to the
next upcoming 5-minute slot to be forecast, so the sensor's content stays
relevant as the day progresses, following the coordinator's own
today/tomorrow refresh cadence (ADR-002 §3) rather than needing a
separate schedule.

### 3 — Extra fitting cost only when the switch is on

Producing the four `"today {method}"` points requires fitting all four
strategies for the diagnosed slot, not just the one configured default —
extra work beyond what ADR-002 §1's normal recalibration does. This only
happens while the diagnostics switch (§1) is on, and only for the one
diagnosed slot per string (not all 288), keeping the added cost bounded
and opt-in: the three non-default methods are fitted alongside the
active one at the same recalibration trigger (midnight or button, ADR-002
§1), and all four are queried at the same forecast-recompute trigger
(ADR-002 §2) the active method's own prediction already goes through.

### 4 — Module responsibility

`switch.py` adds `ShadyDiagnosticsSwitch`, mirroring the existing
`button.py` pattern (Effy's `EffyRecalculateButton`, ADR-002 §1) for a
simple, single-purpose HA entity with no business logic of its own beyond
toggling a flag the coordinator reads. `sensor.py` adds
`ShadyDiagnosticsSensor`; it reads the coordinator's cached per-slot pools
and (when the switch is on) the additionally-fitted non-default models,
and shapes them into the `series` structure above — this shaping is pure
presentation and does not belong in `regression/` or `forecast_adjust.py`.

---

## Consequences

- **Pro:** Turns the manual "build a scatter plot to understand this
  slot's fit" exercise from this project's own design process into a
  standing, opt-in feature — the same validation is available to every
  installation on its own real data, not just during development.
- **Pro:** Showing all four methods' today-predictions side by side,
  against the real training pool, lets a user judge whether the
  configured default (`wls2`) is behaving sensibly for their specific
  installation, and switch methods (ADR-001 §2, a global setting) with
  actual evidence rather than guessing.
- **Pro:** Default-off plus the always-on entity / conditionally-computed
  content pattern (§1) keeps the cost at zero for installations that
  never enable it, consistent with ADR-003 §3's no-op philosophy for
  optional features.
- **Con:** With the switch on, recalibration (ADR-002 §1) does roughly
  4× the fitting work per string (all four methods instead of one) for
  the diagnosed slot — small in absolute terms (one slot, not 288), but
  not free, and scales with the number of configured strings.
- **Con:** The `series` attribute's shape is a public contract once
  dashboards are built against it (ApexCharts configs referencing series
  names like `"today wls2"`); changing the naming scheme or point
  ordering later is a breaking change for anyone with such a dashboard,
  similar in spirit to the attribute-shape stability concerns raised in
  ADR-001 §5 about *other* integrations' attributes — except here it is
  Shady's own contract to keep stable.
