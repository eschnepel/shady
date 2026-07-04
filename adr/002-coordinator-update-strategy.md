# ADR-002 – Coordinator Update Strategy: Recalibration vs. Forecast Recompute

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

ADR-001 established a per-string, per-5-minute-slot model architecture
(§3/§3a): up to `num_strings × 288` independent regression models, each
fitted on a rolling window of history (default 28 days). This raises a
question ADR-001 deliberately left open: **when** does the coordinator
actually (a) refit those models, and (b) recompute the adjusted-forecast
values the user sees?

These are two genuinely different operations with very different cost and
urgency, and conflating them would be wrong in either direction:

- **Refitting** a slot's model means re-running the chosen regression
  strategy (ADR-001 §2) over up to `window_days` samples, for every slot of
  every string. It needs a full day's recorder statistics to be settled
  (so "yesterday" is complete) before it can meaningfully include that day
  — refitting continuously through the day would mostly redo the same
  work with one more/fewer partial-day sample.
- **Recomputing the forecast output** means applying the *already-fitted*
  per-slot factors to whatever the baseline provider's current today/
  tomorrow series says. This is cheap (a lookup + multiplication per
  baseline data point) and should react promptly whenever the baseline
  changes — a PV-forecast or weather integration typically refreshes its
  own forecast every 30–60 minutes as new weather data arrives, and Shady's
  output should reflect that promptly rather than staying stale until the
  next model refit.

---

## Decision

### 1 — Model recalibration: at local midnight, or on manual button press

All configured strings' slot models (ADR-001 §3a) are refitted together,
using **only recorder data up to and including yesterday** — never any
partial data from the day the refit actually runs on, regardless of which
of the two triggers below fired it. This keeps every fit's training set
exactly `window_days` worth of *complete* days (ADR-001 §4); an in-progress
day would otherwise contribute a slot-count that varies by time of day,
subtly biasing whichever slots happen to have already occurred by the time
a fit runs.

Refitting `num_strings × up to 288` slot models is the expensive operation
in this integration (ADR-001 §3a already accepts many small per-slot fits
as cheap *individually*, but the full sweep across every slot of every
string adds up). Because of that cost, exactly two things trigger a refit
— nothing else:

1. **Scheduled, once daily**, via `async_track_time_change(hass, ...,
   hour=0, minute=1, second=0)` — one minute past midnight, giving the
   recorder a moment to settle the previous day's `23:55` slot first.
2. **On demand, via a diagnostic button entity** (`ShadyRecalculateButton`,
   mirroring Effy's `EffyRecalculateButton` in `button.py`) — e.g. after
   the user changes a config option, or simply wants an up-to-date model
   without waiting for the next scheduled run. A button press runs exactly
   the same refit routine as the midnight schedule, including the
   up-to-yesterday cutoff above — pressing the button at 14:00 does not
   pull in today's partial data any more than the midnight run would.

In particular, a baseline-provider update during the day never triggers a
refit by itself (only a forecast recompute, see §2) — that would mean
paying the full-sweep cost every time any provider happens to refresh,
which is neither necessary (the models don't need to change intra-day)
nor affordable at the stated cost.

**Startup safety net:** if, at `async_setup_entry`, no model has been
fitted yet for a config entry (first-ever setup) or the last successful
fit is more than 24h old (e.g. Home Assistant was offline through a
scheduled midnight run), the coordinator runs a fit immediately on
startup, in addition to the daily schedule and the button. This mirrors
Effy's ADR-006 observation that a restart naturally replays initial state
and should trigger the equivalent of a first calculation, rather than
leaving a config entry without any model until the next scheduled time.

### 2 — Forecast recompute: on model update, and on every baseline update

The adjusted-forecast output — for the **future slots only** covered by
§3's today/tomorrow horizon — is recomputed and pushed to the
corresponding sensors, following the shared-coordinator/subscriber
pattern from Effy's ADR-006 Option C, whenever either of two things
happens:

1. **A model recalibration completes** (§1, from either trigger) — the
   newly-fitted factors are applied to whatever baseline data is currently
   cached.
2. **A configured baseline entity (ADR-001 §5) publishes new today/
   tomorrow data** — the coordinator has a listener on every string's
   baseline entity; each update re-applies the *current* (last-fitted, not
   necessarily just-refit) per-slot models to the new baseline series and
   pushes the result.

This is the cheap operation in the system — a lookup-and-multiply per
baseline data point against an already-fitted model, not a refit — which
is precisely why it can afford to run on every baseline update without
the cost concern that limits §1 to exactly two triggers.

No debounce delay is applied by default: unlike Effy's high-frequency
power/energy sensors (ADR-006's original motivation for debouncing),
baseline forecast/weather entities update at most every 30–60 minutes and
are not expected to burst multiple updates within a short window. This
can be revisited (adding the same debounce mechanism as Effy's coordinator)
if a specific provider is found to emit bursts of updates in practice.

### 3 — Forecast horizon: today (remaining) + tomorrow

Each recompute produces adjusted values for:

- the **remainder of today** — from the next upcoming slot after "now"
  through `23:55`, and
- **all of tomorrow** — `00:00` through `23:55`, if and only if the
  baseline provider's data reaches that far.

This mirrors the today/tomorrow shape most PV-forecast integrations
already expose (e.g. `energy_production_today` /
`energy_production_tomorrow`-style sensors), so Shady's output slots
naturally into dashboards built around that convention. Slots already in
the past (earlier today) are not recomputed or exposed — Shady adjusts a
forward-looking forecast, not a historical record, and does not write
recorder statistics the way Effy does (out of scope for this integration;
see the open question in the README).

If the baseline provider has not yet published tomorrow's data at the
time of a recompute (e.g. some providers only publish the next day's
forecast later in the evening), Shady simply outputs whatever horizon is
currently available — this is not an error condition, and the missing
period is filled in on the next baseline update.

### 4 — Resulting module responsibilities

- `coordinator.py` owns: the per-string, per-slot fitted-model cache; the
  daily recalibration schedule and up-to-yesterday cutoff (§1); listeners
  on every configured baseline entity (§2); and pushing recomputed results
  to subscriber sensors. It exposes the refit routine as a single public
  method so both the midnight schedule and the button (§1) call the exact
  same code path.
- `button.py` adds one diagnostic `ShadyRecalculateButton` per config
  entry (mirroring Effy's `EffyRecalculateButton`), whose `async_press`
  simply calls the coordinator's refit method and logs/swallows exceptions
  per ADR-000 §8.
- `forecast_adjust.py` stays a pure function: given a baseline series (any
  length/horizon) and a slot → model lookup, it returns the adjusted
  series. It has no opinion on *when* it is called or *how far* the input
  series reaches — §3's today/tomorrow windowing is the coordinator's
  concern (it decides what slice of the baseline to pass in), not
  `forecast_adjust.py`'s.

---

## Consequences

- **Pro:** Refit cost is bounded and predictable — at most once per day
  per config entry on the schedule, plus whatever the user explicitly asks
  for via the button, regardless of how often the baseline provider
  updates.
- **Pro:** The manual button (§1) gives the user an explicit, low-surprise
  way to force a refit (e.g. right after changing which entities are
  configured) without needing to understand or wait for the schedule —
  same UX Effy already establishes for its own recalculation button.
- **Pro:** The user-visible forecast still reacts promptly (within one
  event loop cycle, same as Effy's Option A/C) to new weather/forecast
  data, without waiting for the next midnight refit.
- **Pro:** Today/tomorrow output matches the shape of existing PV-forecast
  integrations, so it drops into the same dashboard cards/automations
  users already have.
- **Con:** If the daily midnight run is missed for more than one day in a
  row (e.g. multi-day HA outage), models only catch up gradually via the
  startup safety net firing once, then resuming the normal daily schedule
  — there is no "catch-up" logic to backfill multiple missed days at once,
  since the rolling window (ADR-001 §4) only ever looks at the most recent
  `window_days` of recorder history regardless of when it is run.
- **Con:** No debounce on baseline-update-triggered recomputes (§2) is a
  deliberate simplification that assumes low-frequency baseline updates;
  this is a documented assumption, not a proven one, and may need revisiting
  per-provider.
- **Neutral:** Because recalibration and forecast recompute are decoupled,
  there is a window (up to 24h, between refits) where the forecast output
  is being produced by a model that is up to a day "older" than the
  latest recorder history — this is intentional (§1) and not a bug.
