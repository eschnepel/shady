# ADR-006 – Intraday Deviation Correction for the Remaining-Today Forecast

**Date:** 2026-07-05
**Status:** Accepted
**Revision note:** an earlier-draft mechanism (hard minimum-sample gate,
separate provider-update blend) was replaced in place, before
acceptance, by the ramp/blend design below — see the Revision note at
the end of this document for what changed and why.

---

## Context

Comparing a string's actual yield against what its own already-corrected
forecast implied, in real time, reveals whether *today specifically* is
running ahead of or behind what the model predicted — capturing same-day
effects (an unmodeled event like snow cover, a sensor fault, an unusually
persistent weather pattern) that the nightly model refit (ADR-002 §1) has
no way to react to before tomorrow at the earliest. This ADR adds one
mechanism, with three selectable states, that projects today's
already-observed deviation onto the future portion of a string's per-slot
forecast, and — as part of the same mechanism, not a separate one — also
governs how that projection behaves whenever the baseline provider itself
revises its forecast mid-day (§1b).

**This operates per string, not on ADR-005's aggregate sensors.** Computing
the deviation ratio from `ShadyPvEnergyIntegralSensor`/
`ShadyFcEnergyIntegralSensor` (ADR-005 §5/§6), which sum across all
configured strings, would be wrong for the same reason ADR-001 §3 fits a
separate model per string in the first place: shading changes the
*timeline* of a same-day event, not just its magnitude — snow covering a
heavily-shaded string melts later in the day than snow on an unshaded
one, so the two strings' deviation ratios diverge for real, physical
reasons through much of the day. Computing one combined ratio across
strings would average a slowly-recovering shaded string together with an
already-recovered unshaded one and get both wrong. This mechanism
therefore runs independently per string, using each string's own
actual-yield entity and its own per-string corrected-forecast values —
ADR-005's aggregate sensors remain purely a user-facing summary,
downstream of this, not an input to it.

---

## Decision

### 1 — Three-state config switch: off (default), ramping, or blending

A single config-flow field controls the whole feature — there is no
longer a separate enable gate for the ratio correction and a separately
"unconditional" behavior for provider-update transitions; both are now
one mechanism with three states:

- **Disabled (default).** No intraday correction of any kind:
  `ShadyForecastSensor` always shows the plain, uncorrected per-slot
  value, and a provider update (ADR-002 §2's trigger) applies instantly —
  exactly pre-ADR-006 behavior. No rolling window, no ramp state, nothing
  computed or retained.
- **Ramping.** The correction factor ramps in smoothly starting at the
  first active slot of the day (§1a), rather than gating on a fixed
  sample count (see the revision note at the end of this ADR). A
  provider update discards the rolling window and restarts the same
  ramp from scratch, keyed to the newly-published `FC` (§1b).
- **Blending.** Identical to Ramping for a string's very first activation
  of the day — there is nothing yet to blend against (§1a). On every
  subsequent provider update, instead of discarding the pre-update state
  outright, the displayed value crossfades between the *old* prediction
  (frozen at the moment of the update) and a *new* prediction (built the
  same way Ramping would build it, from a freshly restarted window) —
  see §1b.

Ramping and Blending share the same underlying rolling-window/ramp
mechanics (§1a); they differ only in what happens at the moment of a
provider update (§1b).

### 1a — The correction factor: a rolling window, ramped from the first active slot

```
ratio_string = pv_energy_window / fc_energy_window
```

computed **per string**, where both quantities are the energy accumulated
over the trailing **`window_slots`** slots (§3 below) at 5-minute
resolution. Both series come from `cache.py`'s `get_time_range(sensor_ids,
start=now-window_slots*5m, end=now, group_by="sensor")` accessor (ADR-007
§1e) — the string's actual-yield entity and its own `ShadyForecastSensor`.
This is the same underlying `statistics_during_period` read pattern
Effy's ADR-003 established (`mean` field, 5-minute `statistics_short_term`
table) that `cache.py`'s injected `fetch_fn` uses (ADR-007 §1d), but Shady
never calls it directly here — going through `cache.py` means this read
is validated and gap-filled the same way every other time-series access
in this design is, rather than being a second, bespoke recorder-reading
path. Unlike Effy, Shady never needs the internal `async_import_statistics`
write path ADR-003 there had to fall back on, because these are ordinary
sensor entities Home Assistant already records on its own (or, for
`ShadyForecastSensor`, values Shady itself already pushed into `cache.py`,
ADR-007 §1c) — Shady only ever reads history it did nothing special to
create.

This is refreshed on its own schedule — **every 5 minutes**
(`async_track_time_interval(hass, ..., minutes=5)`) — independent of
ADR-002's existing triggers (midnight/button for refitting, baseline
updates for forecast recomputation). 5-minute resolution matches Shady's
own slot grid exactly, so there is no benefit to polling more often, and
polling *less* often would mean the window's edge lags behind by more
than one slot. ADR-004 §2 reuses this same trigger to advance which slot
its diagnostic sensor is showing, rather than introducing a third,
near-identical schedule.

**Why a trailing window, not since-midnight:** snow covering the panels
for the first few hours of a morning, then melting by around noon, is
exactly the situation a since-midnight ratio gets wrong for the rest of
the day — it would keep dragging today's factor down long after the
panels are clear again, because the morning's near-zero output is still
baked into an ever-growing denominator-vs-numerator comparison. A
trailing window "forgets" that morning once it's aged out, letting the
correction recover on its own as conditions actually change, without
needing to detect "the snow melted" as an event — and, per the Context
above, it does so on each string's own timeline, not a blended one.

**The correction factor ramps in, rather than switching on at a
threshold.** A weight `w` ramps linearly from `0` to `1` over
**`ramp_slots`** active slots (§3), counted from whichever **reset
point** currently applies — a string's first active slot of the day, or
its most recent provider update (§1b) — and the *effective* correction
factor is:

```
w(t) = min(1, active_slots_since_reset / ramp_slots)
effective_factor(t) = 1 + w(t) × (clamp(ratio_string(t), 1-intraday_correction_cutoff, 1+intraday_correction_cutoff) - 1)
corrected_value(t) = fc_value(t) × effective_factor(t)
```

`active_slots_since_reset` counts only slots where `FC_i ≠ 0` (ADR-001
§2's `FC_i == 0` boundary, the same plain binary read of that boundary
§2 otherwise applies continuously), matching how `ratio_string` itself
only accumulates meaningful energy during active slots. At `w = 0`,
`effective_factor` is exactly `1` — the plain, uncorrected `FC` value,
with nothing yet applied — and at `w = 1` it is the full clamped ratio.
This achieves what a hard minimum-sample gate would be for — right
around a reset point, when the window may contain only one or two
active slots and a computed `ratio_string` would be noise more than
signal — without a step function: a single early sample's *influence*
on the displayed value is small (scaled by a small `w`), not absent,
and grows smoothly as more of the window fills with genuine same-day
generation. This is a real trade, not a strict improvement — see
Consequences.

### 1b — Provider-update transitions: ramping resets, blending crossfades

A baseline provider revising its forecast mid-day (ADR-002 §2's trigger)
recomputes every future slot's raw `FC`. What happens to the *correction*
at that moment depends on which of §1's two active states is configured:

**Ramping** treats the update exactly like a new reset point: the
rolling window (§1a) empties, `w` resets to `0`, and both the window and
the ramp restart from scratch using only post-update data — functionally
identical to the string's first ramp of the day, just triggered by a
provider update instead of sunrise. The displayed value reverts to the
plain, uncorrected new `FC` value at the instant of the update, then
ramps back up to full correction strength over the next `ramp_slots`
active slots. This can produce a visible dip on a dashboard at each
update, which is exactly what **Blending** exists to avoid.

**Blending** does not discard the pre-update state. Instead, it is frozen
and kept as the *old* side of a crossfade, while a *new* side is built
the same way Ramping's post-update restart would build it:

```
old_prediction(t)  = old_fc_value(t) × effective_factor_frozen
new_prediction(t)  = new_fc_value(t) × effective_factor_new(t)     [§1a, fresh window/ramp, reset at update_time]
w_blend(t)         = min(1, active_slots_since_update / ramp_slots) [same counter, same duration as effective_factor_new's own w]
displayed(t)        = (1 - w_blend(t)) × old_prediction(t) + w_blend(t) × new_prediction(t)
```

`effective_factor_frozen` is a fixed snapshot of §1a's formula taken the
instant before the update fired — its window received its last new
sample at that moment and never receives another, so it does not keep
evolving; it is simply applied, unchanged, to each of the *old* `FC`
series' still-remaining slots (itself now a stale, no-longer-updating
series) for as long as the crossfade needs it. `effective_factor_new`,
by contrast, is a live, still-ramping value exactly as Ramping's own
post-update restart computes it — its own `w` grows from `0` under the
same `ramp_slots` duration and the same start point as the outer
`w_blend`, so the two ramps run in lockstep: the new side is *both*
gaining trust *and* gaining visibility on the same timeline. This
compounds — right after an update, `new_prediction` is barely corrected
*and* barely visible; by the time `ramp_slots` have elapsed it is both
fully corrected and fully visible, and `old_prediction` has faded out
entirely, at which point `displayed(t)` equals exactly what Ramping would
show for the same slot. Ramping and Blending therefore converge to the
identical steady state once a transition completes — they differ only in
the *shape* of the transition, not its destination: Ramping shows a
visible dip back to "no correction" at every update and recovers from
there; Blending never dips, since the still-valid old view keeps covering
for the still-immature new one during the handoff.

**The first activation of the day** — before a string's first active
slot, both `FC` and `PV` are null/zero (night), so there is nothing
meaningful to treat as an "old" side. Ramping and Blending are therefore
identical at this one point: both simply start the §1a ramp at the first
slot where both `FC` and `PV` are filled (in practice, close to sunrise).
This is not a special case requiring separate handling — it is just the
first of potentially several reset points a string can have in a day, the
same starting rule applying uniformly whether the trigger is sunrise or a
later provider update.

This requires the coordinator to retain, per string, whichever ramp/window
counters are currently active, and — under Blending, for the duration of
an in-progress crossfade — the frozen old-side snapshot too. This is a
small, time-bounded piece of state, discarded once it completes; unlike
§1a's window itself (recorder-backed, restart-tolerant), none of this has
a recorder-backed equivalent to read instead, since it concerns values
that either haven't happened yet or belong to a forecast run the provider
has already superseded. Losing it on a restart just means a ramp or
crossfade restarts rather than resumes — an accepted gap per ADR-007,
matching this design's existing trade-off for exactly this kind of state.

**Ordering: one formula per side, an optional crossfade, then the output
clamp, in that order.** *(This is the canonical statement of the
clamp-ordering rule; ADR-001 §2 points here rather than restating it.)*
§1a's `effective_factor` folds the provider-update ramp and the ratio
correction into one continuous function of `w`, so Ramping needs only
ever evaluate it once per slot: `fc_value × effective_factor`, still
*unclamped* at this point
(after the temperature reverse-transform, ADR-003 §2b, but before ADR-001
§2's `[0, FC]`/inverter-limit clamp). Blending evaluates it twice — once
for `old_prediction`, once for `new_prediction`, each independently
unclamped — and only *then* crossfades the two. Either way, ADR-001 §2's
output clamp is applied exactly **once**, to the final value, after any
crossfade — never in between, and never separately to either side of a
Blending crossfade. Clamping either side beforehand would not guarantee
the actual blended (or single, for Ramping) number respects the bound:
the two sides of a crossfade can have different `FC` bounds, and either
side's own ratio (already clamped to
`[1-intraday_correction_cutoff, 1+intraday_correction_cutoff]` in §2 — a
smaller clamp on the *multiplier*, distinct from the output clamp) can
still push an otherwise-fine value back out of bounds, e.g. a >1 ratio
boosting a prediction that was already close to the inverter limit. One
clamp, applied last, after everything else, is what actually guarantees
correctness regardless of which state is active or how far into a
ramp/crossfade a given slot's value currently is.

### 2 — `intraday_correction_cutoff`: a config-flow field, now a pure magnitude clamp

A single global, config-flow-configurable field, **`intraday_correction_cutoff`**
(a fraction — named apart from ADR-011 §2's similarly-shaped
`neighbor_fitting_cutoff`, since the two clamp unrelated things and a
shared name invited confusion between them), clamps each string's
`ratio_string` from §1a to
`[1 - intraday_correction_cutoff, 1 + intraday_correction_cutoff]` before
it feeds into `effective_factor`. `intraday_correction_cutoff` does not
double as the feature's enable switch — that job belongs entirely to
§1's three-state field — so its default is a real, non-degenerate
**`0.10`** (±10%) rather than `0` (a value that would only make sense as
a disguised "off"), and applies whenever §1's switch is not Disabled. A
person who turns on Ramping or Blending without touching this field gets
a correction that is actually allowed to do something, rather than one
that is silently a no-op until they also remember to raise
`intraday_correction_cutoff` off of zero.

### 3 — Two config-flow timespans: rolling window and ramp/blend duration

Two further config-flow fields, both counted in **5-minute slots**
(matching Shady's grid, ADR-001 §3a) rather than a fixed number of hours:

- **`window_slots`** (default `24`, i.e. 2 hours) — how many trailing
  slots `pv_energy_window`/`fc_energy_window` (§1a) are accumulated
  over. A short trailing window lets a string's correction recover on
  its own from a temporary same-day anomaly (snow melting, a transient
  sensor fault) as it ages out of the window, without needing to detect
  the anomaly ending as an event.
- **`ramp_slots`** (default `12`, i.e. 1 hour) — how many active slots
  the `w` ramp (§1a) takes to go from `0` to `1`, whether ramping in
  from a string's first active slot of the day or from a provider
  update under either Ramping or Blending (§1b). One field drives all
  of these, since they are the same mechanism — a linear ramp from a
  reset point — applied at different trigger moments, not several
  durations to reason about separately.

Both fields live in the same config-flow "settings" step as
`intraday_correction_cutoff`, the training window, regression method, and
smoothing radius (ADR-010).
What changes behavior is solely whether §1's three-state switch is
turned on at all, and to which state — the defaults above apply
whenever it is not Disabled.

### 4 — Application: per string, per future slot

Once §1's switch is not Disabled, the correction is applied to **each
individual future slot of that string** — every one of the string's own
future per-slot values (the same per-string, per-slot values ADR-005 §3's
`ShadyFcDaySumSensor` sums across strings to build its cross-string
array) is replaced by `corrected_value` (Ramping, §1a) or `displayed`
(Blending, §1b). Either result then still passes through ADR-001 §2's
separate, final output clamp (`[0, FC]`/inverter limit), per the ordering
established in §1b above. Already-past values are never touched, matching
ADR-002 §3's rule that past slots are frozen once their time has passed.

Because the correction happens at the per-string source, `ShadyFcDaySumSensor`
(ADR-005 §3) and `ShadyFcRemainingTodaySensor` (ADR-005 §4) need **no
correction logic of their own** — they continue to be exactly what they
already were, sums over per-string values that are now themselves
corrected (when the feature is active) before the aggregate ever sees
them. This also means a person charting one string's own forecast
directly sees exactly the same corrected shape the aggregate is built
from — one source of truth, per string, not a separate aggregate-level
adjustment layered on top.

Each string's `ShadyForecastSensor` gains attributes for transparency
(consistent with the diagnostic philosophy in ADR-004): `intraday_ratio`
(that string's raw, unclamped §1a `ratio_string`), `intraday_state`
(`"off"` / `"ramping"` / `"blending"`, mirroring §1's config value),
`intraday_ramp_weight` (that string's current `w`, `0`–`1`), `values_raw`
(that string's pre-correction future values), and, only while Blending
and a crossfade is in progress, `intraday_blend_active` (boolean, per
string).

### 5 — Module placement

Three pure functions are added to `aggregation.py` (ADR-005) — no new
module needed:

- `intraday_correction_factor(pv_energy_window, fc_energy_window,
  ramp_weight, intraday_correction_cutoff) -> float` — §1a's
  ratio-clamp-and-ramp math in one function. Called once per string under
  Ramping, and twice per string (once per side) under Blending.
- `ramp_weight(active_slots_since_reset, ramp_slots) -> float` — §1a's
  `w(t)`, a tiny pure function shared by both the ramp-in and
  provider-update-restart cases, and by Blending's own `w_blend`.
- `crossfade(old_prediction, new_prediction, ramp_weight) -> float` —
  §1b's Blending-only linear blend, called only when §1's switch is set
  to Blending.

The trailing-window read itself (§1a) goes through `cache.py`'s
`get_time_range` accessor (ADR-007 §1e), which in turn sources any
not-yet-cached portion via `statistics_during_period` (the same public
recorder API access point Effy's ADR-003 reads with, ADR-007 §1d) —
`coordinator.py` calls `cache.py`, it does not call
`statistics_during_period` itself. The small, short-lived per-string
ramp/crossfade state from §1b lives in `cache.py` (ADR-007) too, as a
simple dict store rather than the time-series shape §1a's window uses —
it is discarded once each ramp or crossfade completes and is not
restart-persisted (there is no recorder-backed equivalent to read
instead, since it concerns future values, or a superseded forecast run,
neither of which exist in history). The three config-flow fields (§1, §2,
§3) live in the same "settings" step as the training window, regression
method, and smoothing radius (ADR-010).

---

## Consequences

- **Pro:** Reacts same-day to real deviations the nightly-refit model
  cannot see until the next recalibration (ADR-002 §1), using data the
  recorder already has — no new fitting step, and no new coordinator-side
  history-tracking either (§1a).
- **Pro:** Running this per string, not on ADR-005's aggregate sensors,
  correctly handles same-day events whose timeline itself depends on
  shading (snow melting later under a shaded string than an unshaded
  one) — an aggregate-level correction structurally cannot represent this
  since it has already discarded which string an anomaly belongs to.
- **Pro:** The configurable rolling window (§1a/§3) lets each string's
  correction recover on its own from a temporary same-day anomaly without
  needing to detect the anomaly ending as an event — it simply ages out
  of the window.
- **Pro:** A smooth ramp (§1a), rather than a hard minimum-sample-size
  gate, removes a step function's worth of behavior to explain — trust
  in the correction now grows continuously from the same reset point
  that starts the window, rather than snapping from "off" to "on" at a
  fixed sample count.
- **Pro:** Blending (§1b) removes a real, visible UX problem — a
  dashboard number jumping the instant a weather model refreshes — by
  crossfading rather than switching, while still converging to exactly
  the same steady-state value Ramping would reach for the same slot, just
  without the dip along the way.
- **Pro:** Decoupling `intraday_correction_cutoff` from the enable switch
  (§1/§2) means the three-state field alone answers "is this on", and
  `intraday_correction_cutoff` alone answers "how strong" — a person
  turning the feature on gets a cutoff that actually does something
  (default `0.10`) rather than a field they also have to remember to
  raise off of zero.
- **Pro:** Reading §1a's window from the recorder rather than maintaining
  a coordinator-side cache means it is naturally restart-tolerant with no
  extra persistence code for that part — the data was going to be there
  regardless of whether Shady itself stays running continuously.
- **Con:** This assumes each string's already-observed deviation (within
  its trailing window) is likely to continue into its own near future,
  which is not always true. This is a deliberate, simple projection, not
  a weather-aware model — exactly why `intraday_correction_cutoff` exists
  as a user-tunable clamp rather than an unclamped correction.
- **Con:** Not using a hard minimum-sample-size gate (§1a) means a
  `ratio_string` computed from a single noisy active slot right after any
  reset point can still influence the displayed value, just weakly (via a
  small `w`) rather than not at all. This is a real trade against a hard
  gate's simplicity, not a strict improvement — "smoothly down-weighted"
  is not the same guarantee as "excluded until an hour's worth of data
  exists."
- **Con:** Blending's per-string state (§1b) is strictly more than
  Ramping's: a frozen old-side snapshot must be retained, alongside the
  new side's own ramp counters, for the duration of every crossfade — all
  coordinator-side, short-lived, and not recorder-backed, on top of the
  bookkeeping Ramping alone would already need.
- **Con:** During an active ramp or crossfade, a string's `values_raw`
  and its final corrected value can both differ from what a naive "just
  recomputed with the latest FC" figure would show, for up to
  `ramp_slots` after any reset point — including a string's first
  activation of the day, not only later provider updates.
- **Con:** Adds one more correction layer, per string, on top of
  shading/clipping/derating (ADR-001/ADR-003) and the per-slot model
  itself — one more thing to account for when a number looks "off",
  though the added attributes in §4 aim to keep that debuggable without
  needing to consult ADR-004's diagnostic sensor.

---

## Revision note

Pre-acceptance drafts of this ADR gated the correction behind a hard
minimum-sample-size requirement (at least 12 active slots within the
window) before trusting `ratio_string` at all, and treated a
provider-update transition as a separate, ungated ~1-hour blend rather
than part of the same mechanism as the initial ramp. Both were replaced,
in place, by §1a's smooth ramp and §1b's unified ordering — one
continuous function of `w` covering both the first-activation case and
every later provider update, rather than two separately-gated stages —
before this ADR was accepted. `ramp_slots`' default (`12`, i.e. 1 hour)
and `intraday_correction_cutoff`'s default (`0.10`) preserve the rough
magnitude of those earlier fixed values; nothing else about them carries
forward, and neither default is validated against real installations yet
— the same caveat ADR-011's Consequences already raises about
`neighbor_fitting_cutoff`'s own (unrelated) default applies here too, for
`intraday_correction_cutoff`.
