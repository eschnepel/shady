# ADR-001 – Empirical, Forecast-Value-Based Shading Model

**Date:** 2026-07-04
**Status:** Accepted
**Amended:** 2026-07-05 — §2/§2a updated to cross-reference ADR-004 and
ADR-006 once accepted. **2026-08-13** — §3d updated to reference
ADR-007 and ADR-008. **2026-08-14** — split: baseline-forecast sourcing
(formerly §5) and the config flow shape (formerly §6) moved out to
ADR-009 and ADR-010; no behavioral change — see the Revision note at
the end of this document. **2026-08-17** — split again: temporal
smoothing and neighbor-regime exclusion (formerly §3b/§3c/§3d) moved out
to ADR-011; no behavioral change — see the Revision note.

---

## Context

The original idea for Shady was to have the user manually describe the
obstruction causing shading (e.g. a tree) as a horizon profile — a list of
azimuth/elevation points, or a simplified sector. This was rejected during
brainstorming for two reasons:

1. **Poor UX.** Home Assistant's `voluptuous`-based config flow forms have
   no good widget for entering or drawing a horizon profile; a text field
   with azimuth:elevation pairs is accurate but tedious and error-prone.
2. **It duplicates information that is already implicitly present** in the
   gap between a PV forecast (which assumes a clear, unobstructed horizon)
   and the actual historical yield. If a tree blocks the sun at a given sun
   position, that shows up as a systematic, repeatable shortfall at that
   exact sun position — every time the sun returns there, regardless of
   calendar date.

This ADR replaces the horizon-profile approach with a **self-calibrating,
empirical model** that learns the shading pattern directly from recorder
history, and defines the regression model itself: the predictor,
fitting strategy, per-string/per-slot granularity, and rolling training
window. Baseline (unshaded) forecast sourcing and the config flow shape
that ties this model together with ADR-003 and ADR-006 are split out
into ADR-009 and ADR-010 respectively (originally §5 and §6 of this
ADR).

---

## Decision

### 1 — Predictor space: the raw forecast value, not sun position

**This decision was validated by a working proof-of-concept** before this
ADR was written: linear fitting with the raw forecast value as the
predictor, one model per 5-minute slot, was implemented and worked well
in practice. This ADR documents and generalizes that proven approach.

The regression predictor `x` is the **raw baseline forecast value itself**
(`FC_i`, e.g. in Watts) for the timestamp in question, and the target `y`
is the **actual historical yield** (`PV_i`) for that same timestamp —
fit directly, `PV_i ≈ f(FC_i)`, not as a ratio against some third
variable. This works *because* slot partitioning (§3a) already isolates
"which specific 5-minute time-of-day window" a sample belongs to — that is
what carries the "is this moment typically shaded" information. Once a
slot's pool is already restricted to one specific clock-time window, the
one remaining variable that is (a) genuinely informative about the
*magnitude* of expected output and (b) actually known in advance for any
future prediction is the raw forecast value itself — not a geometric
quantity that would need computing from scratch via `sun_geometry.py`.

This also means Shady needs **no astronomical calculation at all** (see
the module diagram in ADR-000 §3) — nothing in the design depends on sun
azimuth/elevation, and latitude/longitude/elevation are not needed as
regression inputs (they may still be useful for other purposes, e.g.
determining sunrise/sunset for UI purposes, but are not required by the
model itself).

### 2 — Regression method: a pluggable, globally-selected strategy

**Two distinct roles for `FC`, never conflated.** Fitting and predicting
use `FC` values from two different points in time, sourced two different
ways:

- **Training-time `FC`** — the string's raw `FC` *history* (via
  `providers/`, ADR-009, and the recorder), read for every historical
  sample in a slot's pool (§3a, ADR-011 §1). Paired with that same sample's
  (clipped-and-normalized, per ADR-003 §1/§2) actual yield, this is what
  `fit(samples)` below trains on.
- **Prediction-time `FC`** — the slot's *current/live* raw `FC` value for
  today or tomorrow (the same value `providers/` exposes going forward,
  ADR-002 §2's baseline-update trigger), used only to query the
  already-fitted model: `predict(fc)`. This is never part of the training
  pool itself.

Every regression strategy fits `PV_i ≈ f(FC_i)` over the historical
sample pool that §3a and ADR-011 §1 already define for a given slot (that
slot's own samples, plus up to `smoothing_radius` neighboring slots,
across the rolling window), with every sample weighted by
`magnitude_weight_i` (downweighting near-zero-forecast samples, e.g.
sunrise/sunset, for the reason given below) and by the time-proximity
weight from ADR-011 §1. *How*
`f` is fit is a **pluggable strategy**, chosen once by the user for the
whole integration (all strings share the same method; see ADR-010), not
auto-selected and not configurable per string. Four strategies are
supported, behind a shared `regression/base.py` protocol (`fit(samples)
-> FittedModel`, `predict(fc) -> (adjusted_forecast, confidence)`):

| Method | Model | Character |
|---|---|---|
| `linear` | Weighted least squares, degree 1: `PV ≈ β₀ + β₁·FC` | Validated by the original proof-of-concept. Captures both a multiplicative scaling effect and a constant offset (e.g. inverter standby draw); robust with the sample sizes in play here |
| `kernel` | Locally weighted average: `Σ w_i · PV_i / Σ w_i`, `w_i` additionally weighted by closeness of `FC_i` to the query `FC` | Non-parametric; can follow a saturating/clipping curve without assuming a functional shape, at the cost of needing reasonable sample density across the forecast-value range actually seen |
| `wls2` (default) | Weighted least squares, degree 2: adds `FC²` | Captures gentle curvature — both a soft approach to an inverter limit, and the diffuse/direct-light bending shading itself plausibly produces (see below) |
| `wls3` | Weighted least squares, degree 3: adds `FC³` | Most flexible of the parametric options; risks overfitting with the pool sizes in play here (at most `window_days · (2·smoothing_radius + 1)`, typically well under 100) |

**Confidence is defined independently of the chosen method**, as the
normalized sum of sample weights in the slot's pool, `Σ (magnitude_weight_i
· time_weight_i)` — no distance calculation in forecast-value space is
needed for this (that would only matter for `kernel`'s own point estimate,
not for confidence). A polynomial fit (`linear`/`wls2`/`wls3`) has no
intrinsic notion of "how much evidence supports this point" from its
coefficients alone; using the same pool-weight-sum for every method,
regardless of which one produced the point estimate, decouples "how good
is the point estimate" from "how sure are we of it", and means switching
methods never changes what the confidence attribute means.

`wls2` was chosen as the default, not `linear`, despite `linear` being
the method the original proof-of-concept validated — because pure
shading itself has a plausible physical reason to be non-linear in `FC`,
not just clipping. A shaded panel still receives most *diffuse* skylight;
what shading actually blocks is the *direct* (beam) component. On a
heavily overcast, low-`FC` day, irradiance is almost entirely diffuse, so
a shaded and an unshaded panel behave similarly — the curve should sit
close to `PV ≈ FC` there. On a clear, high-`FC` day, the direct component
dominates and shading matters much more — the curve should bend
increasingly below `PV ≈ FC` as `FC` rises. A single straight line has to
compromise between these two ends, systematically over- or
under-correcting depending on how cloudy today happens to be; `wls2`'s
one extra degree of freedom (`FC²`) can bend to fit this without the
extrapolation instability `wls3` showed. `kernel` and `linear` remain
available for installations where this curvature doesn't hold, or where
maximum robustness against a small sample is preferred over capturing it;
`wls3` remains available too, but see the warning below.

**`wls3` is deliberately not the default, and this was checked, not just
assumed.** A worked example with a realistic clipping ceiling (28 days,
weather-driven forecast values, a saturating true relationship) showed all
three parametric methods tracking the training data reasonably well
in-sample, but diverging sharply exactly where Shady's predictions always
have to operate — a query forecast value *higher* than anything seen in
the rolling window (an unusually clear day compared to recent weather,
which is a normal occurrence, not an edge case). At such an extrapolation
point, `wls2` (closest to the true clipped value), `linear`, and `wls3`
(furthest from it, overshooting the most) ranked in exactly that order —
`wls3`'s extra flexibility made its extrapolation *worse*, not better,
consistent with the same overshoot/oscillation risk noted in the
comparison table above and with an earlier pure-noise example where
`wls3` extrapolated to a negative, non-physical value. The lesson
generalizes: more polynomial degrees of freedom help fit the training
window better but do not constrain what happens just outside it, and
Shady's queries are structurally almost always just outside it. This is
exactly why `wls2` — one extra degree of freedom, not two — is the
chosen compromise: enough flexibility for the diffuse/direct argument
above, without `wls3`'s demonstrated extrapolation risk.

The predicted output is clamped to `[0, FC]` before being used (never
negative, never more than the slot's own raw forecast value) — this
mirrors the defensive-clamping philosophy in Effy's ADR-005 (never let a
degenerate input propagate raw). If a string has an inverter AC power
limit configured (ADR-003 §1), that limit is a *second*, tighter upper
clamp applied to this same output — see ADR-003 §1a for why this must
apply to the corrected output too, not just to training.

**Ordering relative to ADR-006.** This clamp is the *final* step of the
per-slot pipeline, applied exactly once, after ADR-006's correction (§1)
has already run on the raw (unclamped) value — whatever shape that takes
for the currently-configured state (Ramping, Blending, or Disabled). See
ADR-006 §1b for the full ordering rationale — including why a single
clamp applied last, rather than clamping either side of a Blending
crossfade separately, is what actually guarantees the output never
violates a physical bound.

Regardless of method, `magnitude_weight_i` downweights samples where
`FC_i` is near zero, because a near-zero forecast slot (sunrise/sunset,
or a slot the source provider considers negligible) carries very little
information and is disproportionately sensitive to small absolute
measurement noise. This mirrors the same defensive-clamping philosophy
just mentioned.

`magnitude_weight_i` itself is continuous, not a hard cutoff — it
smoothly approaches, but is only ever exactly `0` at, `FC_i == 0` itself
(the provider reporting no forecast output at all for that slot, e.g.
full night). A slot with a small but nonzero `FC_i` (deep dawn/dusk, or a
heavily overcast midday reading) is downweighted, not excluded — it still
contributes to the fit, just with little influence. This `FC_i == 0`
boundary is also, separately, the exact definition ADR-006 §1a reuses for
its "active slot" count: a slot is **active** if and only if `FC_i ≠ 0`
(equivalently, `magnitude_weight_i > 0`) — a plain binary yes/no read of
the same boundary defined here, not a second, independently-tuned
near-zero threshold. §2's own regression weighting stays continuous
throughout; ADR-006 §1a's rolling-window and ramp-weight calculations are
the one place elsewhere in this design that needs a binary answer
instead, and it gets that answer from this same boundary rather than
inventing another one.

### 2a — What "good" means here: daily total, not individual slots

An individual slot's confidence (§2 above) is not, by itself, very
meaningful to a person looking at Shady's output — nobody consumes one
isolated 5-minute prediction. What actually matters is whether **today's
and tomorrow's total energy forecast** — the sum across all of a day's
slots — tracks reality well. A slot with a mediocre individual fit
contributes only a small, bounded error to that sum, and errors in
different slots are not correlated the way a single bad global model's
error would be; some slots will run a little high, others a little low,
and a lot of that cancels out over a full day. This has a concrete
consequence for the main adjusted-forecast sensor (ADR-002 §3's today/
tomorrow horizon): its exposed confidence is the `FC_i`-weighted average
of its constituent slots' confidences (weighting by each slot's forecast
magnitude, so a low-confidence dawn/dusk slot that contributes little
energy doesn't drag down the number as much as a low-confidence midday
slot would), not a simple mean and not any single slot's value in
isolation. Per-slot confidence remains available as a diagnostic detail
(ADR-004) for anyone who wants to look under the hood, but it is not the
number Shady leads with.

### 3 — Granularity: one model per configured string

Shady fits and queries a separate regression per configured string/plane,
not one global factor for the whole system. A single global factor would
average away exactly the signal Shady exists to detect: shading that only
affects part of the array (e.g. the east string is behind a tree, the west
string is not). Each string is configured as a `(baseline_series,
actual_yield_entity)` pair (see ADR-009), and gets its own fitted model,
its own confidence, and its own adjusted-forecast output sensor.

### 3a — Slot partitioning: one model per 5-minute-of-day slot

Within each string, Shady does not fit a single continuous model queried
at an arbitrary timestamp. Instead it maintains **one independent model
per 5-minute-of-day slot** — the same 288-slots-per-day grid Effy's
ADR-003 established for recorder statistics (`00:00`, `00:05`, …,
`23:55`). A slot's model is trained only on the historical samples that
fell into that exact clock-time slot across the days in the rolling
window (§4) — at most `window_days` samples, since each day contributes
exactly one sample per slot.

**Forecast providers do not all publish at 5-minute resolution.** Some
publish hourly values, others half-hourly; Shady's own slot grid is always
5 minutes regardless. Whatever the source's native resolution, every
5-minute slot within one source period uses that period's single
published value as its `FC_i` — e.g. an hourly provider's `10:00` value is
`FC_i` for the slots `10:00`, `10:05`, …, `10:55` alike; a half-hourly
provider's value covers only `10:00`–`10:25` before the next published
value takes over. This is a property of `providers/normalize.py` (ADR-009) — it
broadcasts each published value across the 5-minute slots it covers —
and is transparent to `regression/` and `forecast_adjust.py`,
which only ever see one `FC_i` per slot regardless of the source's native
granularity. Slots that are consistently near-zero in both `FC` and `PV`
throughout the window (night) are inferred directly from that data — via
the same `magnitude_weight_i` mechanism (§2) that already downweights
near-zero-forecast samples — rather than computed astronomically; they
simply never accumulate a meaningfully weighted pool and are skipped as a
natural consequence, with no separate "is it night" check needed.

This is chosen over one continuous per-string model for three reasons:

- **It matches the shape of the problem.** Any baseline forecast is
  already delivered as discrete per-slot values (ADR-009), and the recorder
  statistics Shady reads are natively 5-minute-sliced (Effy
  ADR-003). Slot-partitioned models mean producing an adjusted forecast is
  always "look up this slot's model and evaluate it" — no per-query
  neighbor search across the full historical point cloud.
- **Cheap, independent fits.** Each slot's fit is over a small `n` (≤
  `window_days`), fast enough to refit every slot on every recalibration
  run (§4) without needing incremental/online update logic. A corrupted or
  anomalous slot's data can never leak into neighboring slots' models.
- **Simplicity of the confidence definition (§2).** "How much local
  evidence supports this point" collapses to "how many, and how
  consistent, are this slot's own samples" — no cross-slot weighting
  scheme is needed.

The trade-off is that slot models, fit in complete isolation, do not share
data with their neighbors even when the true shading pattern is smooth
across time — two adjacent slots (e.g. `10:00` and `10:05`) could
otherwise disagree more than the physical situation warrants, especially
with few samples. This is resolved directly at the training-data level,
not patched afterwards — see ADR-011 §1.

### 3b–3d — Temporal smoothing and neighbor-regime exclusion: see ADR-011

This ADR originally also specified how each slot's training pool is
widened with weighted neighbor-slot data, and how a neighbor on the wrong
side of a real shading boundary is detected and either excluded or
rescaled. That content was split out, on 2026-08-17, into ADR-011 — see
the Revision note at the end of this ADR for why.

### 4 — Rolling 28-day training window as the default

The training window defaults to the **most recent 28 days** (configurable,
matching the naming convention of Effy's `DEFAULT_MAX_HISTORY_DAYS`), used
as a rolling window rather than an accumulate-forever or fixed-year window.

This is deliberate, not a data-volume compromise: a static obstruction's
*position* is stable across the whole year, but a **deciduous tree's
canopy density is not** — dense foliage in summer casts a materially
different shadow than a bare tree in winter, even though the forecast
value for a given slot on two such days could be similar. A window
spanning many months would blend "full canopy" and "bare branches"
samples within the same slot's model (§3a), producing a fitted
relationship that is wrong in both directions depending on season. A
rolling 28-day window instead tracks *current* canopy state and re-adapts
automatically as the season (and the tree) changes, at the cost of every
slot needing up to 28 days before it has any samples at all, and never
having more than 28 to work with even at steady state — an acceptable
trade-off given the cold-start behavior described in §2 and the small-`n`
fitting cost already accepted in §3a.

### 5, 6 — Baseline sourcing and config flow: see ADR-009, ADR-010

This ADR originally also specified baseline (unshaded) forecast sourcing
and the config flow shape tying this model together with ADR-003 and
ADR-006. Both were split out, on 2026-08-14, into their own documents —
see the Revision note at the end of this ADR for why.

---

## Consequences

- **Pro:** No manual horizon-profile entry — the obstruction's effect is
  inferred from data the user already has (forecast + recorder history),
  which is both easier to set up and self-correcting if the obstruction
  changes (tree grows, is trimmed, etc.) via the rolling window in §4.
- **Pro:** `wls2` (§2, default) has a plausible physical justification
  (diffuse vs. direct light) for capturing shading's own curvature, not
  just clipping's — `linear` (the method the original proof-of-concept
  validated), `kernel`, and `wls3` remain available for installations
  where that curvature doesn't hold or where a different robustness
  trade-off is preferred, all four sharing one confidence definition so
  switching methods never changes what the confidence attribute means.
- **Pro:** Slot partitioning (§3a) means producing an adjusted forecast is
  always a direct per-slot model lookup, matching the recorder's own
  5-minute grid (Effy ADR-003) with no per-query neighbor search over the
  full historical point cloud, and keeps recalibration cost small and
  independent per slot. (The resulting slot-boundary discontinuity risk,
  and how it's resolved, is covered in ADR-011's own Consequences.)
- **Con:** The model needs real historical data to become useful; a
  freshly-configured string effectively passes the baseline through
  unmodified (low confidence everywhere) until enough per-slot samples
  accumulate — expected to take days to a few weeks.
- **Con:** A 28-day rolling default (§4) means slots (§3a) that only ever
  see a narrow range of forecast values across the window (e.g. a slot
  that's rarely anything but heavily overcast in a given season) may have
  persistently low confidence even after long-term use, since a given
  slot's samples never exceed `window_days`. Acceptable for now; may need
  a slower-decaying window specifically for such slots if this proves
  problematic in practice.

See ADR-011's own Consequences for the trade-offs specific to temporal
smoothing and neighbor-regime exclusion (formerly this document's
§3b/§3c/§3d).

---

## Revision note

**2026-08-14 split:** this ADR originally also specified baseline
(unshaded) forecast sourcing (formerly §5) and the config flow shape
(formerly §6). Both were extracted into their own documents — ADR-009
and ADR-010 respectively — because they are separable concerns from the
regression model itself, and were already being referenced externally
(ADR-003, ADR-004, ADR-005, ADR-006) as if they were independent
documents. This was a pure documentation reorganization: no decision,
default, or behavior changed. All cross-references throughout the ADR
set were updated to point at the new documents directly.

**2026-08-17 split:** this ADR originally also specified temporal
smoothing and neighbor-regime exclusion/rescaling (formerly §3b/§3c/§3d).
This was extracted into ADR-011, on the same grounds as the 2026-08-14
split above — it is a separable concern from regression-method selection
and granularity, and was already being cited externally (ADR-004,
ADR-007, ADR-008, ADR-010) as a self-contained unit. Pure documentation
reorganization: no decision, default, or behavior changed. All
cross-references throughout the ADR set were updated to point at ADR-011
directly.
