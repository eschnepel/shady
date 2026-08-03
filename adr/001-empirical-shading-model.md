# ADR-001 – Empirical, Forecast-Value-Based Shading Model

**Date:** 2026-07-04
**Status:** Accepted

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
history, and defines the supporting architecture: how the baseline
(unshaded) forecast is sourced, how the regression works, and what the
config flow needs to collect as a result.

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
  `providers/`, ADR-001 §5, and the recorder), read for every historical
  sample in a slot's pool (§3a/§3b). Paired with that same sample's
  (clipped-and-normalized, per ADR-003 §1/§2) actual yield, this is what
  `fit(samples)` below trains on.
- **Prediction-time `FC`** — the slot's *current/live* raw `FC` value for
  today or tomorrow (the same value `providers/` exposes going forward,
  ADR-002 §2's baseline-update trigger), used only to query the
  already-fitted model: `predict(fc)`. This is never part of the training
  pool itself.

Every regression strategy fits `PV_i ≈ f(FC_i)` over the historical
sample pool that §3a/§3b already define for a given slot (that slot's own
samples, plus up to `smoothing_radius` neighboring slots, across the
rolling window), with every sample weighted by `magnitude_weight_i`
(downweighting near-zero-forecast samples, e.g. sunrise/sunset, for the
reason given below) and by the time-proximity weight from §3b. *How*
`f` is fit is a **pluggable strategy**, chosen once by the user for the
whole integration (all strings share the same method; see §6), not
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
per-slot pipeline, applied once, after both of ADR-006's stages have
already run on the raw (unclamped) value: first the FC-update ramp
(§1a, blending old- and new-`FC`-based predictions over one hour), then
the intraday deviation correction (§1, multiplying by a ratio that is
itself separately clamped to `[1-cutoff, 1+cutoff]` in §2 — a different,
smaller clamp bounding the *multiplier*, not the *output*). Running this
output clamp any earlier would not guarantee the *final* value respects
the bound: the ramp's two sides can carry different `FC` bounds, and the
intraday correction can itself push a value that was fine beforehand back
above or below the limit (e.g. a >1 ratio boosting an already near-limit
prediction). Clamping only once, last, after everything else has already
been applied, is what actually guarantees the number Shady outputs never
violates a physical bound, regardless of which upstream corrections were
active.

Regardless of method, `magnitude_weight_i` downweights samples where
`FC_i` is near zero, because a near-zero forecast slot (sunrise/sunset,
or a slot the source provider considers negligible) carries very little
information and is disproportionately sensitive to small absolute
measurement noise. This mirrors the same defensive-clamping philosophy
just mentioned.

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
actual_yield_entity)` pair (see §5), and gets its own fitted model, its own
confidence, and its own adjusted-forecast output sensor.

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
value takes over. This is a property of `providers/normalize.py` (ADR-001
§5) — it broadcasts each published value across the 5-minute slots it
covers — and is transparent to `regression/` and `forecast_adjust.py`,
which only ever see one `FC_i` per slot regardless of the source's native
granularity. Slots that are consistently near-zero in both `FC` and `PV`
throughout the window (night) are inferred directly from that data — via
the same `magnitude_weight_i` mechanism (§2) that already downweights
near-zero-forecast samples — rather than computed astronomically; they
simply never accumulate a meaningfully weighted pool and are skipped as a
natural consequence, with no separate "is it night" check needed.

This is chosen over one continuous per-string model for three reasons:

- **It matches the shape of the problem.** Any baseline forecast is
  already delivered as discrete per-slot values (§5), and the recorder
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
not patched afterwards — see §3b.

### 3b — Smoothing: widen each slot's training data, not the output

Rather than smoothing the finished curve of per-slot factors after all 288
models are fit, each slot's **training data** is widened to also include
a small number of neighboring slots' historical samples, weighted by
time-of-day distance (`time_weight_i`, folded into the sample weight used
throughout §2 alongside `magnitude_weight_i`). A slot at `10:00` with a
smoothing radius of 1 is fit on samples from `09:55`, `10:00`, and `10:05`
(weighted by closeness to `10:00`), not `10:00` alone.

This was chosen over output-side smoothing (e.g. a moving average over the
288 finished factors) for two reasons:

- **It uses the confidence signal that already exists, instead of ignoring
  it.** Because a forecast provider's own published value usually changes
  gradually from one 5-minute slot to the next (and, per §3a, is often
  literally identical across several adjacent slots when the source
  publishes at coarser-than-5-minute resolution), a time-of-day-adjacent
  sample is, in practice, nearly the same kind of evidence as the slot's
  own samples — folding `time_weight_i` into the same weighted-pool
  mechanism §2 already uses for `magnitude_weight_i` means "similar
  evidence with different confidence" is blended correctly, using the
  pool's own weights. A fixed post-hoc smoothing window has no such
  notion: it would blur a genuinely sharp, well-supported shading edge
  exactly as much as it blurs pure noise between two low-confidence
  slots, since it cannot tell the two apart.
- **It also directly helps the cold-start/small-`n` problem** noted in §4
  — each slot's fit now draws on `window_days × (2·radius + 1)` samples
  instead of just `window_days`, without abandoning the "cheap,
  independent per-slot fit" property from §3a (the radius is a small
  constant, not a full search over the whole point cloud).

The temporal smoothing radius is a **global** setting (like the regression
method in §2 — one value for the whole integration, not per string or per
slot), exposed in the config flow (§6) as "smoothing radius in slots",
defaulting to `1` (±5 minutes). A radius of `0` disables temporal
smoothing entirely, reproducing the strictly-independent-slots behavior
originally described in §3a.

**`time_weight_i` formula.** Samples beyond `smoothing_radius` slots away
are not in the pool at all (hard cutoff); within it, weight decreases
linearly with slot distance:

```
time_weight_i = 1 - distance_i / (smoothing_radius + 1)
```

where `distance_i` is the slot distance to the diagnosed slot (`0` for
the slot itself, `1` for its immediate neighbors, etc.). This gives
`time_weight_i = 1.0` at the center and `1/(smoothing_radius + 1)` at the
outermost included neighbor — e.g. `1.0` / `0.5` for the default radius
of `1`, or `1.0` / `0.667` / `0.333` for a radius of `2`. A Gaussian
kernel (`exp(-distance_i² / 2σ²)`) was considered as an alternative and
rejected for this specific decision: it would need `σ` either tied to
`smoothing_radius` (in which case the outermost weight stays roughly
constant near `0.61` regardless of how large the radius is, rather than
this formula's built-in tendency to grow more conservative as the radius
grows) or exposed as its own separate field — a second, redundant
locality parameter with no obvious default, on top of `smoothing_radius`
itself. At the small radii in practical use (0–2), the two shapes are
close enough that this single-parameter linear form is a worthwhile
trade against that added complexity, not a limitation.

### 3c — Excluding a whole neighbor series at a shading boundary

§3b's `time_weight_i` handles ordinary noise well — a neighbor slot's
samples are just somewhat less trusted the farther away they are — but it
has no way to distinguish "somewhat noisier" from "systematically a
different shading regime entirely". Exactly at a shading boundary (a
tree's edge falling between two adjacent 5-minute slots, or the seasonal
sweep discussed in §3a/§3b's own history), one whole neighbor series can
be consistently better or worse than the center slot's — not scattered
around a similar central tendency, but shifted wholesale. Blending such a
neighbor in at a reduced (but still nonzero) weight still pulls the
center slot's fit toward the wrong regime; the distance-based weight
alone cannot fix this, because the problem isn't distance, it's that the
neighbor's data doesn't belong to the same regime at all.

Before a neighbor's samples are included in a slot's pool at all, its
series is checked against the center slot's own series:

```
neighbor_median = median(PV_i / FC_i for i in neighbor_series)
center_median   = median(PV_i / FC_i for i in center_series)
deviation = |neighbor_median - center_median| / center_median

if deviation > neighbor_fitting_cutoff:  # default 0.25, global, §6
    exclude the entire neighbor series from this slot's pool
```

The comparison uses the **ratio** `PV_i/FC_i`, not raw `PV_i` values,
specifically because adjacent slots can have meaningfully different `FC`
magnitudes just from being a few minutes apart in time-of-day (most
noticeably near sunrise/sunset, where irradiance changes quickly) — a
raw-value comparison would flag that ordinary, shading-unrelated
difference as a false positive. The ratio normalizes it away and isolates
whether the neighbor's *performance relative to what was forecast* is
systematically different, which is the actual shading-regime signal.
`median`, not `mean`, is used for the same reason `magnitude_weight_i`
and the various clamps throughout this design favor robust statistics —
a handful of weather-driven outlier days should not by themselves trigger
an exclusion. `neighbor_fitting_cutoff` is a **global**, config-flow-
exposed setting (§6, default `25%`) — unlike the fixed constants
elsewhere in this design (e.g. the `12`-active-slot gate in ADR-006 §1),
this one is user-tunable from the start, since how much regime difference
counts as "a real boundary" plausibly varies by installation (canopy
density, obstruction sharpness) in a way the 12-slot gate's underlying
concept does not.

This is a **hard exclusion** (`time_weight_i` effectively forced to `0`
for every sample in that neighbor series for this slot), not a further
reduction of the existing linear weight — a systematically-shifted
neighbor is misleading signal, not merely weaker signal, so partial
trust is the wrong response to it. The check is re-evaluated at every
recalibration (ADR-002 §1), alongside the rest of the pool, since which
slots straddle a boundary can itself shift as the rolling window (§4)
advances.

### 3d — Alternative: rescale instead of exclude (`neighbor_fitting_cutoff = -1%`)

Exclusion (§3c) discards a neighbor series entirely once it disagrees
enough — throwing away real day-to-day variation and weather-response
shape along with the systematic bias. Setting `neighbor_fitting_cutoff`
to the sentinel value **`-1%`** switches to a different strategy:
**never exclude, always rescale.** Every neighbor series is corrected to
the center slot's own median before it enters the pool, rather than being
judged against a threshold at all:

```
correction_factor = center_median / neighbor_median
rescaled_PV_i = PV_i * correction_factor   for every i in neighbor_series
```

`(FC_i, rescaled_PV_i)` pairs replace the neighbor's raw pairs in the
pool, still weighted by `magnitude_weight_i · time_weight_i` exactly as
§3b already specifies — the rescaling only corrects *which level* the
neighbor's ratio sits at, nothing else about how it is weighted changes.
Because only the median shifts, day-to-day weather variation within the
neighbor series is preserved as-is (a cloudy day two days ago is still
visibly a cloudy day after rescaling, just centered on the right
baseline), and if the neighbor itself is mid-transition (its own edge
sweeping through within the window), that shape survives the correction
too — this is a single multiplicative adjustment, not a point-by-point
overwrite. `-1%` was chosen as the sentinel because it is not a value a
real percentage deviation could ever take (deviation is defined as an
absolute value, §3c), the same kind of "reuse an otherwise-impossible
value as a mode switch" trick ADR-006 §2 already uses for its own
cut-off field (`0` there means "disabled" rather than a literal
zero-width clamp).

This inherits the same near-zero-`FC` instability §2's `magnitude_weight_i`
already exists to dampen: if `neighbor_median` is itself very small
(a neighbor slot near sunrise/sunset with little historical signal),
`correction_factor` can become large and the rescaled values noisy.
`magnitude_weight_i` still applies to these rescaled samples exactly as
it would to any other, which tempers but does not eliminate this —
worth keeping in mind when choosing between §3c's exclusion and §3d's
rescaling for an installation with slots close to the day's edges.

**A useful emergent property:** if a slot sits exactly on a shading
boundary — both its `-1` and `+1` neighbors deviate enough to be excluded
— smoothing effectively (and correctly) collapses to `smoothing_radius =
0` for that specific slot at that specific time, without needing to
special-case "this slot is a boundary" anywhere. Calm, non-boundary
regions keep the full benefit of §3b's smoothing; boundary slots
automatically fall back to being judged on their own data alone.

This check lives in `regression/base.py`, alongside the shared pool-
construction logic every strategy in `regression/` relies on before its
own `fit()` runs — it is common preprocessing, not specific to any one of
`linear`/`kernel`/`wls2`/`wls3`. The raw `FC`/`PV` pairs it operates on
are supplied by `coordinator.py`, which fetches them via `cache.py`'s
`get_slot_pool` accessor (ADR-007 §1e) — `regression/base.py` itself
never reaches into `cache.py` directly (only `coordinator.py` does,
ADR-007 §2), keeping the pool-construction logic a pure function of
whatever data it is handed.

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

### 5 — Baseline (unshaded forecast) sourcing: generic attribute discovery

Rather than hardcoding adapters for specific integrations (Forecast.Solar,
Solcast, …), `providers/discovery.py` scans HA entities for
**attribute shapes that look like a forecast series**, and lets the user
confirm the match — it never applies a detected baseline silently.

Two entity domains are scanned, covering two different kinds of baseline
signal:

- **`sensor.*` entities** — for a dedicated PV-forecast integration's
  output. Attribute shapes recognized:
  - dict of `{timestamp: number}` (e.g. Forecast.Solar's `wh_period`)
  - list of dicts with a timestamp-like key and a numeric value-like key
    (e.g. Solcast's `detailedForecast`)
- **`weather.*` entities** — for users without a dedicated PV-forecast
  integration. Attribute shapes recognized: sunshine-duration-like values
  in a weather integration's forecast attribute (e.g. `sunshine_duration`,
  common in DWD/Open-Meteo-based weather integrations). This is used as a
  proxy baseline ("expected yield under a clear/predicted sky") rather than
  a direct watt/Wh series, and is normalized accordingly before it enters
  the regression.

`providers/normalize.py` maps both shapes, via a small table of known
key-name aliases (timestamp keys: `datetime`, `start`, `period_start`,
`time`; value keys: `wh`, `pv_estimate`, `power`, `value`, `energy`,
`sunshine_duration`), onto one canonical `list[tuple[datetime, float]]`
series that any strategy in `regression/` and `forecast_adjust.py` consume
without caring which integration or domain it came from.

Candidates are **scored, not auto-selected**: an attribute name containing
"forecast"/"pv"/"sunshine", parseable ISO8601 timestamps, and
plausible-unit numeric values all raise the score; the config flow (see
§6) presents the ranked candidates and always offers a manual
entity+attribute fallback, since third-party attribute shapes are not a
versioned contract (the same caution Effy's ADR-003 raises about recorder
internals applies here to other integrations' attributes).

`providers/` is explicitly the one module allowed to read `hass.states`
directly among the "pure-ish" layer (see updated diagram in ADR-000 §3) —
it still never writes state and never reaches into another integration's
internal coordinator or `hass.data`, only its public entity
state/attributes.

**Global default, per-string override.** The discovery-and-scoring
process above runs once to establish a **global default** baseline
candidate, set up before any string is configured (§6) — the common case
being one PV-forecast service for the whole installation. Any individual
string can still override this with its own baseline candidate (e.g. a
per-plane Solcast site for that specific string's orientation) if
configured; if it does not, it uses the global default. This mirrors the
same global-with-override shape already used for the temperature source
(ADR-003 §2a).

### 6 — Config flow shape

Given §3 and §5, the config flow establishes global settings **first**,
before any string exists — a person configures "how Shady should behave"
once, then adds however many strings share that behavior, rather than
being asked global questions only after already committing to a first
string:

```
Step "settings" (first):
  - Global default baseline candidate (dropdown, ranked by
    providers/discovery.py per §5; "None of these" → manual entity +
    attribute path entry) — used by any string that does not override it
  - "Does this baseline already account for temperature effects itself?"
    (boolean, default false — ADR-003 §2c; presented right alongside the
    baseline candidate above, since it is a property of *that* choice)
  - Training window in days (default 28)
  - Regression method: `wls2` (default) / `linear` / `kernel` / `wls3`
    (global — applies to every configured string, see §2; chosen manually,
    no auto-selection based on data volume)
  - Smoothing radius in slots (default 1, global; see §3b — `0` disables
    temporal smoothing)
  - Neighbor-fitting cut-off (default 25%, global; see §3c/§3d — the
    maximum median-ratio deviation a neighbor series may have before
    being excluded from a slot's training pool; the sentinel `-1%`
    switches to always-rescale instead of exclude, per §3d; not the same
    field as ADR-006's intraday-correction cut-off, despite the similar
    name)
  - Default temperature source (optional; entity selector covering
    sensor.* with device_class temperature and weather.* entities;
    leave empty to disable derating correction by default for all
    strings — ADR-003 §2a)
  - Intraday-Korrektur Cut-off (default 0 = deaktiviert; siehe ADR-006)

Step "add_string" (repeated):
  - Name (free text, e.g. "Dach Süd")
  - Baseline candidate override (optional; same dropdown as the global
    default above; leave empty to use the global default set in
    "settings"). A string that *does* override is, by definition,
    treated as temperature-aware (ADR-003 §2c) — no separate per-string
    flag is offered, on the assumption that the realistic reason to
    override per string at all is a per-plane setup on a dedicated
    PV-forecast service (e.g. Solcast configured with one site per
    string), which is exactly the kind of provider ADR-003 §2c's flag
    is about in the first place.
  - Actual-yield entity (standard HA entity selector, sensor domain,
    power or energy device_class)
  - "Configure advanced corrections (clipping/derating) for this string?"
    (boolean, default off) → yes: "add_string_advanced", no:
    "add_another"

Step "add_string_advanced" (optional, per string):
  - Converter/inverter AC power limit (optional number, W; leave empty
    to disable clipping exclusion for this string — ADR-003 §1)
  - Temperature source override (optional; leave empty to use the global
    default; "none" disables derating for this string specifically even
    if a global default is set — ADR-003 §2a)
  - Temperature coefficient in %/°C (only shown/used if a temperature
    source — global default or override — applies to this string;
    default −0.4 — ADR-003 §2)

Step "add_another":
  - "Add another string?" (boolean) → back to "add_string" or finish
```

Note there is no latitude/longitude/elevation field: the regression needs
no astronomical calculation (§1), so location is not collected anywhere
in Shady's config flow.

The options flow mirrors this to allow adding/editing strings and changing
any global setting after initial setup, following the same pattern as
Effy's `EffyOptionsFlow`.

---

## Consequences

- **Pro:** No manual horizon-profile entry — the obstruction's effect is
  inferred from data the user already has (forecast + recorder history),
  which is both easier to set up and self-correcting if the obstruction
  changes (tree grows, is trimmed, etc.) via the rolling window in §4.
- **Pro:** The provider-discovery approach (§5) means Shady works with
  whatever PV-forecast or weather integration the user already has,
  without per-integration adapter code to maintain.
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
  independent per slot; temporal smoothing (§3b) resolves the resulting
  slot-boundary discontinuity risk directly in the training-data weights
  (reusing the same weighted-pool mechanism as `magnitude_weight_i`),
  instead of a separate blind post-hoc smoothing pass.
- **Pro:** §3c's median-based exclusion means smoothing (§3b) does not
  have to choose between "smooth everywhere" and "smooth nowhere" — it
  gets the benefit of pooling neighbor data in calm regions while
  automatically backing off exactly at shading boundaries, where pooling
  would otherwise actively hurt, without needing to detect "this is a
  boundary" as a special case anywhere in the code. §3d's rescale
  alternative (`-1%` sentinel) gives a second option for installations
  that would rather keep every neighbor's data, corrected, than lose it
  outright.
- **Pro:** Config flow ordering (§6) establishes every global setting
  before a person configures their first string, so string-specific
  questions (baseline override, converter limit, temperature override)
  are answered with the relevant global defaults already visible, rather
  than the reverse.
- **Con:** The model needs real historical data to become useful; a
  freshly-configured string effectively passes the baseline through
  unmodified (low confidence everywhere) until enough per-slot samples
  accumulate — expected to take days to a few weeks.
- **Con:** Attribute-shape discovery (§5) is inherently heuristic and reads
  data across an unversioned surface (other integrations' attributes).
  Mitigated by always requiring user confirmation and offering a manual
  fallback, but a future HA core or integration update could still change
  an attribute's shape without notice, same caveat as Effy's ADR-003.
- **Con:** A 28-day rolling default (§4) means slots (§3a) that only ever
  see a narrow range of forecast values across the window (e.g. a slot
  that's rarely anything but heavily overcast in a given season) may have
  persistently low confidence even after long-term use, since a given
  slot's samples never exceed `window_days`. Acceptable for now; may need
  a slower-decaying window specifically for such slots if this proves
  problematic in practice.
- **Con:** Temporal smoothing (§3b) trades a small amount of temporal
  resolution for stability — with the default radius of 1, a genuinely
  very sharp shading transition that occurs within a single 5-minute slot
  will be very slightly softened across its two immediate neighbors. This
  is deliberately tunable (down to `0`, disabling it) rather than fixed,
  precisely because how sharp a "real" transition is expected to be varies
  by installation.
- **Con:** §3c's default 25% deviation cut-off, while now config-flow
  exposed (§6) rather than fixed, still ships with a default that is a
  reasonable starting point, not a value validated against real
  installations yet. Set too low, it would exclude neighbors over
  ordinary weather variance, quietly shrinking the effective smoothing
  radius most of the time; set too high, it would let a genuine regime
  difference through.
