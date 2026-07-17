# ADR-006 – Intraday Deviation Correction for the Remaining-Today Forecast

**Date:** 2026-07-05
**Status:** Accepted

---

## Context

Comparing a string's actual yield against what its own already-corrected
forecast implied, in real time, reveals whether *today specifically* is
running ahead of or behind what the model predicted — capturing same-day
effects (an unmodeled event like snow cover, a sensor fault, an unusually
persistent weather pattern) that the nightly model refit (ADR-002 §1) has
no way to react to before tomorrow at the earliest. This ADR adds two
related, optional mechanisms: one that projects today's already-observed
deviation onto the future portion of a string's per-slot forecast (§1/§2),
and one that smooths the visible jump whenever the baseline provider
itself revises its forecast mid-day (§1a).

**This operates per string, not on ADR-005's aggregate sensors.** An
earlier draft of this ADR computed the deviation ratio from
`ShadyPvEnergyIntegralSensor`/`ShadyFcEnergyIntegralSensor` (ADR-005
§5/§6), which sum across all configured strings. That is wrong for the
same reason ADR-001 §3 fits a separate model per string in the first
place: shading changes the *timeline* of a same-day event, not just its
magnitude — snow covering a heavily-shaded string melts later in the day
than snow on an unshaded one, so the two strings' deviation ratios
diverge for real, physical reasons through much of the day. Computing one
combined ratio across strings would average a slowly-recovering shaded
string together with an already-recovered unshaded one and get both
wrong. Both §1 and §1a therefore run independently per string, using each
string's own actual-yield entity and its own per-string corrected-forecast
values — ADR-005's aggregate sensors remain purely a user-facing summary,
downstream of this, not an input to it.

---

## Decision

### 1 — Deviation ratio: a rolling 2-hour window, read from the recorder

```
ratio_string = pv_energy_window / fc_energy_window
```

computed **per string**, where both quantities are the energy accumulated
over the trailing **2 hours**, at 5-minute resolution. Rather than have
the coordinator maintain its own rolling cache of readings to support
this (an earlier draft of this ADR proposed exactly that), both series
are read directly from **the recorder's existing history** of two
entities that are already being recorded automatically, with no special
write path needed: the string's actual-yield entity, and the string's own
corrected-forecast sensor. This is the same `statistics_during_period`
read pattern Effy's ADR-003 established (`mean` field, 5-minute
`statistics_short_term` table) — but purely on the **read** side, using
only the public, documented API. Unlike Effy, Shady never needs the
internal `async_import_statistics` write path ADR-003 there had to fall
back on, because these are ordinary sensor entities Home Assistant already
records on its own; Shady only ever reads history it did nothing special
to create.

This is refreshed on its own schedule — **every 5 minutes**
(`async_track_time_interval(hass, ..., minutes=5)`) — independent of
ADR-002's existing triggers (midnight/button for refitting, baseline
updates for forecast recomputation). 5-minute resolution matches Shady's
own slot grid exactly, so there is no benefit to polling more often, and
polling *less* often would mean the window's edge lags behind by more
than one slot.

**Why 2 hours, not since-midnight:** snow covering the panels for the
first few hours of a morning, then melting by around noon, is exactly the
situation a since-midnight ratio gets wrong for the rest of the day — it
would keep dragging today's factor down long after the panels are clear
again, because the morning's near-zero output is still baked into an
ever-growing denominator-vs-numerator comparison. A 2-hour trailing window
"forgets" that morning once it's more than 2 hours old, letting the
correction recover on its own as conditions actually change, without
needing to detect "the snow melted" as an event — and, per the Context
above, it does so on each string's own timeline, not a blended one.

The minimum-sample-size gate from an earlier draft of this ADR — at least
12 "active" slots, reusing ADR-001 §2's magnitude-weight threshold —
still applies, per string, scoped to the trailing window: at least 12
active slots must have occurred *within* the current window (for that
string) before its ratio is trusted and applied. Before the gate is
satisfied for a given string — whether because too little of the day has
happened yet, or because its window temporarily contains too few active
slots — that string's future slots are reported at their plain,
uncorrected value regardless of the cutoff setting in §2, while another
string that has already satisfied its own gate can be corrected at the
same moment.

### 1a — Ramping across a provider forecast update, unconditionally

A baseline provider revising its forecast mid-day (ADR-002 §2's trigger)
recomputes every future slot's corrected value using the newly-published
raw `FC`. Applied instantly, this can produce a visible step in the
remaining-day curve at the exact moment a weather model updates — the
kind of discontinuity a person watching a dashboard notices and
(reasonably) distrusts, especially since a single new model run is not
necessarily more correct than the previous one, merely newer.

Instead, for the **one hour following any update**, each future slot's
value is a linear blend between what it would have been under the
*previous* `FC` data and what it is under the *new* `FC` data:

```
blended_value(t) = (1 - w) × value_under_old_fc + w × value_under_new_fc
w = min(1, (t - update_time) / 1h)
```

`w` ramps from `0` at the moment of the update to `1` one hour later, at
which point the blend is complete and the slot's value is simply
`value_under_new_fc` — same as an instant switch would have given, just
arrived at gradually. **This applies unconditionally, including a
string's very first update of the day** — an earlier draft of this ADR
implicitly special-cased "the first update has nothing to ramp from and
so skips the ramp", which was an unintended exception, not a deliberate
one.

**Anchor point for the day's first ramp.** Before the day's first slot
with real data, both `FC` and `PV` are null/zero (night) — there is
nothing meaningful to ramp *from* there, and anchoring to midnight or to
some flat placeholder would just be arbitrary. Instead, the first ramp of
the day starts at **the first slot where both `PV` and `FC` are filled**
(both have an actual, non-null value) — in practice, close to sunrise,
whenever the first meaningful same-day forecast and the first non-zero
actual output both exist. Every later provider update during the day
ramps from whatever value was previously displayed, exactly as already
described above; this rule only resolves what "previously displayed"
means for the very first one.

This requires the coordinator to retain the previous update's future-slot
values alongside the new ones, per string, for the duration of the ramp
(a small, time-bounded piece of state, discarded once the ramp
completes — unlike §1, this one genuinely has no recorder-backed
equivalent to read instead, since it concerns values that haven't
happened yet).

**Ordering: a two-stage blend, then the output clamp, in that order.**
`value_under_old_fc` and `value_under_new_fc` above are each the model's
*raw* prediction (after the temperature reverse-transform, ADR-003 §2b,
but before ADR-001 §2's `[0, FC]`/inverter-limit clamp). This ramp is
**stage 1** of a two-stage adjustment: its output (still unclamped) feeds
directly into §1's intraday deviation correction as **stage 2**, and only
*after both stages* is ADR-001 §2's output clamp applied — once, to the
final value, not in between the two stages and not separately to either
stage's inputs. Clamping earlier would not guarantee the actual final
number respects the bound: the ramp's two sides can have different `FC`
bounds, and stage 2's ratio (itself already clamped to `[1-cutoff,
1+cutoff]` in §2 — a smaller clamp on the *multiplier*, distinct from
the output clamp) can still push an otherwise-fine value back out of
bounds, e.g. a >1 ratio boosting a prediction that was already close to
the inverter limit. One clamp, applied last, after everything else, is
what actually guarantees correctness regardless of which of the two
stages were active for a given slot at a given moment.

### 2 — Cut-off: one config-flow field, doubling as the enable switch

A single global, config-flow-configurable **cut-off** (a fraction, e.g.
`0.0`–`0.5`) clamps each string's `ratio_string` from §1 to `[1 - cutoff,
1 + cutoff]` before it is applied. The **default is `0`**, which collapses
that clamp range to exactly `[1, 1]` — i.e. the correction factor is
always exactly `1` (no-op) — functionally disabling the entire mechanism
using the same numeric field that, at any positive value, both enables
and bounds it, for every string alike (this field is global, not
per-string, even though §1/§1a's computation itself is per-string). This
was chosen over a separate boolean "enable intraday correction" toggle
plus a magnitude field: one field with a meaningful zero is one fewer
setting to explain, and `0` is the safest possible default for a feature
that changes same-day forecast behavior.

### 3 — Application: per string, per future slot

Once both gates (§1's sample-size minimum for that string, and §2's
cutoff being non-zero) are satisfied, the correction is applied to **each
individual future slot of that string** — every one of the string's own
future per-slot values (the same per-string, per-slot values ADR-005 §3's
`ShadyFcDaySumSensor` sums across strings to build its cross-string
array) is replaced by `value × clamp(ratio_string, 1-cutoff, 1+cutoff)`.
The `clamp(...)` here bounds only the *ratio* (§2) — the result of this
multiplication then still passes through ADR-001 §2's separate, final
output clamp (`[0, FC]`/inverter limit), per the ordering established in
§1a above; this section's multiplication is stage 2 of that two-stage
pipeline, not the pipeline's last step. Already-past values are never
touched, matching ADR-002 §3's amendment that past slots are frozen once
their time has passed.

Because the correction happens at the per-string source, `ShadyFcDaySumSensor`
(ADR-005 §3) and `ShadyFcRemainingTodaySensor` (ADR-005 §4) need **no
correction logic of their own** — they continue to be exactly what they
already were, sums over per-string values that are now themselves
corrected (when the feature is active) before the aggregate ever sees
them. This also means a person charting one string's own forecast
directly sees exactly the same corrected shape the aggregate is built
from — one source of truth, per string, not a separate aggregate-level
adjustment layered on top.

Each string's underlying sensor gains attributes for transparency
(consistent with the diagnostic philosophy in ADR-004): `intraday_ratio`
(that string's raw, unclamped §1 value), `intraday_correction_active`
(boolean, per string), `values_raw` (that string's pre-correction future
values), and `fc_update_ramp_active` (boolean, per string — is §1a's
one-hour blend currently in progress for this string).

### 4 — Module placement

Two pure functions are added to `aggregation.py` (ADR-005) — no new
module needed:

- `intraday_correction_factor(pv_energy_window, fc_energy_window,
  active_slot_count, cutoff) -> float` — §1/§2's ratio-and-clamp math,
  called once per string.
- `apply_fc_update_ramp(old_values, new_values, update_time, now) ->
  list[float]` — §1a's linear blend, called once per string.

The trailing-window read itself (§1) is a `coordinator.py` responsibility
using `statistics_during_period` (the same public recorder API access
point Effy's ADR-003 reads with), added alongside its existing "pulls
recorder history" role (ADR-000 §3) — no new module needed there either,
since fetching historical statistics for regression training data was
already this module's job. `coordinator.py` also owns §1a's small,
short-lived per-string ramp state (discarded once each ramp completes;
unlike §1 there is no recorder-backed equivalent to read instead, since a
ramp concerns future values that don't exist in history yet). The
config-flow field lives in the same "settings" step as the training
window, regression method, and smoothing radius (ADR-001 §6).

---

## Consequences

- **Pro:** Reacts same-day to real deviations the nightly-refit model
  cannot see until the next recalibration (ADR-002 §1), using data the
  recorder already has — no new fitting step, and (per §1) no new
  coordinator-side history-tracking either.
- **Pro:** Running §1/§1a per string, not on ADR-005's aggregate sensors,
  correctly handles same-day events whose timeline itself depends on
  shading (snow melting later under a shaded string than an unshaded
  one) — an aggregate-level correction structurally cannot represent this
  since it has already discarded which string an anomaly belongs to.
- **Pro:** The 2-hour rolling window (§1) lets each string's correction
  recover on its own from a temporary same-day anomaly without needing to
  detect the anomaly ending as an event — it simply ages out of the
  window.
- **Pro:** The provider-update ramp (§1a), now applying uniformly
  including a string's first update of the day (anchored at the first
  slot with real `PV`/`FC` data, not an arbitrary midnight placeholder),
  removes a real, visible UX problem (a dashboard number jumping the
  instant a weather model refreshes, at any time of day) with a mechanism
  that needs no judgment about which forecast run is "more correct" — it
  just blends smoothly and finishes trusting the new one within an hour
  regardless.
- **Pro:** A single numeric field serving as both enable-flag and safety
  clamp means the default (`0`) is simultaneously "off" and the most
  conservative possible value — a person who never touches this setting
  gets exactly today's status quo behavior.
- **Pro:** Reading §1's window from the recorder rather than maintaining
  a coordinator-side cache means it is naturally restart-tolerant with no
  extra persistence code — the data was going to be there regardless of
  whether Shady itself stays running continuously.
- **Con:** This assumes each string's already-observed deviation (within
  its trailing window) is likely to continue into its own near future,
  which is not always true. This is a deliberate, simple projection, not
  a weather-aware model — exactly why the cutoff exists as a user-tunable
  clamp rather than an unclamped correction.
- **Con:** §1a's ramp state is still coordinator-side, short-lived, and
  not recorder-backed (future values have no history to read) — genuinely
  new bookkeeping, per string, even though §1 no longer needs any.
- **Con:** During an active §1a ramp, a string's `values_raw` and its
  final corrected value can both differ from what a naive "just
  recomputed with the latest FC" figure would show, for up to an hour
  after any update — including, now, the first update of the day, not
  only later revisions.
- **Con:** Adds one more correction layer, per string, on top of
  shading/clipping/derating (ADR-001/ADR-003) and the per-slot model
  itself — one more thing to account for when a number looks "off",
  though the added attributes in §3 aim to keep that debuggable without
  needing to consult ADR-004's diagnostic sensor.
