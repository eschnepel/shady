# ADR-011 – Temporal Smoothing and Neighbor-Regime Exclusion for Slot Training Pools

**Date:** 2026-08-17
**Status:** Accepted
**Note:** Extracted from ADR-001 §3b/§3c/§3d (2026-08-17 split) — see the
Revision note at the end of this document, and ADR-001's own Revision
note. Pure documentation reorganization, following the same precedent as
ADR-001's earlier 2026-08-14 split into ADR-009/ADR-010: no decision,
default, or behavior changed.

---

## Context

ADR-001 §3a fits one independent regression model per 5-minute-of-day
slot, deliberately isolated from its neighbors — cheap, easy to reason
about, and immune to a corrupted slot contaminating the ones around it
(ADR-001 §3a's own reasoning). The trade-off, flagged in ADR-001 §3a
itself, is that two adjacent slots (e.g. `10:00` and `10:05`) can
disagree more than the physical situation warrants, especially with few
samples, since nothing about strictly-independent per-slot models shares
information across a slot boundary.

This ADR covers how that trade-off is resolved directly at the
training-data level: each slot's pool is widened to include nearby
slots' historical samples (§1), together with a mechanism to detect and
handle the case where a "nearby" slot is actually on the other side of a
real shading boundary rather than just ordinary noise (§2/§3). It does
not change ADR-001's regression method, granularity, or window sizing —
those remain ADR-001's own decisions; this ADR is scoped entirely to
what goes into a slot's training pool before any of ADR-001 §2's four
regression strategies ever see it.

---

## Decision

### 1 — Smoothing: widen each slot's training data, not the output

Rather than smoothing the finished curve of per-slot factors after all 288
models are fit, each slot's **training data** is widened to also include
a small number of neighboring slots' historical samples, weighted by
time-of-day distance (`time_weight_i`, folded into the sample weight used
throughout ADR-001 §2 alongside `magnitude_weight_i`). A slot at `10:00`
with a smoothing radius of 1 is fit on samples from `09:55`, `10:00`, and
`10:05` (weighted by closeness to `10:00`), not `10:00` alone.

This was chosen over output-side smoothing (e.g. a moving average over the
288 finished factors) for two reasons:

- **It uses the confidence signal that already exists, instead of ignoring
  it.** Because a forecast provider's own published value usually changes
  gradually from one 5-minute slot to the next (and, per ADR-001 §3a, is
  often literally identical across several adjacent slots when the source
  publishes at coarser-than-5-minute resolution), a time-of-day-adjacent
  sample is, in practice, nearly the same kind of evidence as the slot's
  own samples — folding `time_weight_i` into the same weighted-pool
  mechanism ADR-001 §2 already uses for `magnitude_weight_i` means
  "similar evidence with different confidence" is blended correctly,
  using the pool's own weights. A fixed post-hoc smoothing window has no
  such notion: it would blur a genuinely sharp, well-supported shading
  edge exactly as much as it blurs pure noise between two low-confidence
  slots, since it cannot tell the two apart.
- **It also directly helps the cold-start/small-`n` problem** noted in
  ADR-001 §4 — each slot's fit now draws on
  `window_days × (2·radius + 1)` samples instead of just `window_days`,
  without abandoning the "cheap, independent per-slot fit" property from
  ADR-001 §3a (the radius is a small constant, not a full search over the
  whole point cloud).

The temporal smoothing radius is a **global** setting (like the regression
method in ADR-001 §2 — one value for the whole integration, not per
string or per slot), exposed in the config flow (ADR-010) as "smoothing
radius in slots", defaulting to `1` (±5 minutes). A radius of `0`
disables temporal smoothing entirely, reproducing the
strictly-independent-slots behavior originally described in ADR-001 §3a.

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

### 2 — Excluding a whole neighbor series at a shading boundary

§1's `time_weight_i` handles ordinary noise well — a neighbor slot's
samples are just somewhat less trusted the farther away they are — but it
has no way to distinguish "somewhat noisier" from "systematically a
different shading regime entirely". Exactly at a shading boundary (a
tree's edge falling between two adjacent 5-minute slots, or the seasonal
sweep discussed in ADR-001 §3a and §1 above), one whole neighbor series
can be consistently better or worse than the center slot's — not
scattered around a similar central tendency, but shifted wholesale.
Blending such a neighbor in at a reduced (but still nonzero) weight still
pulls the center slot's fit toward the wrong regime; the distance-based
weight alone cannot fix this, because the problem isn't distance, it's
that the neighbor's data doesn't belong to the same regime at all.

Before a neighbor's samples are included in a slot's pool at all, its
series is checked against the center slot's own series:

```
neighbor_median = median(PV_i / FC_i for i in neighbor_series)
center_median   = median(PV_i / FC_i for i in center_series)
deviation = |neighbor_median - center_median| / center_median

if deviation > neighbor_fitting_cutoff:  # default 0.25, global, ADR-010
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
and the various clamps throughout ADR-001 favor robust statistics —
a handful of weather-driven outlier days should not by themselves trigger
an exclusion. `neighbor_fitting_cutoff` is a **global**, config-flow-
exposed setting (ADR-010, default `25%`), user-tunable from the start, since
how much regime difference counts as "a real boundary" plausibly varies
by installation (canopy density, obstruction sharpness) in a way a single
fixed, one-size-fits-all threshold could not capture.

This is a **hard exclusion** (`time_weight_i` effectively forced to `0`
for every sample in that neighbor series for this slot), not a further
reduction of the existing linear weight — a systematically-shifted
neighbor is misleading signal, not merely weaker signal, so partial
trust is the wrong response to it. The check is re-evaluated at every
recalibration (ADR-002 §1), alongside the rest of the pool, since which
slots straddle a boundary can itself shift as the rolling window
(ADR-001 §4) advances.

### 3 — Alternative: rescale instead of exclude (`neighbor_fitting_cutoff = -1%`)

Exclusion (§2) discards a neighbor series entirely once it disagrees
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
§1 already specifies — the rescaling only corrects *which level* the
neighbor's ratio sits at, nothing else about how it is weighted changes.
Because only the median shifts, day-to-day weather variation within the
neighbor series is preserved as-is (a cloudy day two days ago is still
visibly a cloudy day after rescaling, just centered on the right
baseline), and if the neighbor itself is mid-transition (its own edge
sweeping through within the window), that shape survives the correction
too — this is a single multiplicative adjustment, not a point-by-point
overwrite. `-1%` was chosen as the sentinel because it is not a value a
real percentage deviation could ever take (deviation is defined as an
absolute value, §2) — an otherwise-impossible value repurposed as a
marker, the same general pattern `regression/base.py` uses `NaN` for, as
both "invalid sample" and "pad" (ADR-008).

This inherits the same near-zero-`FC` instability ADR-001 §2's
`magnitude_weight_i` already exists to dampen: if `neighbor_median` is
itself very small (a neighbor slot near sunrise/sunset with little
historical signal), `correction_factor` can become large and the
rescaled values noisy. `magnitude_weight_i` still applies to these
rescaled samples exactly as it would to any other, which tempers but
does not eliminate this — worth keeping in mind when choosing between
§2's exclusion and this section's rescaling for an installation with
slots close to the day's edges.

**A useful emergent property:** if a slot sits exactly on a shading
boundary — both its `-1` and `+1` neighbors deviate enough to be excluded
— smoothing effectively (and correctly) collapses to `smoothing_radius =
0` for that specific slot at that specific time, without needing to
special-case "this slot is a boundary" anywhere. Calm, non-boundary
regions keep the full benefit of §1's smoothing; boundary slots
automatically fall back to being judged on their own data alone.

This check lives in `regression/base.py`, alongside the shared pool-
construction logic every strategy in `regression/` relies on before its
own `fit()` runs — it is common preprocessing, not specific to any one of
`linear`/`kernel`/`wls2`/`wls3` (ADR-001 §2). The raw `FC`/`PV` pairs it
operates on are supplied by `coordinator.py`, which fetches them via
`cache.py`'s `get_regression_pools` accessor (ADR-008 §2) —
`regression/base.py` itself never reaches into `cache.py` directly (only
`coordinator.py` does, ADR-007 §2), keeping the pool-construction logic a
pure function of whatever data it is handed.

---

## Consequences

- **Pro:** Temporal smoothing (§1) resolves the slot-boundary
  discontinuity risk inherent to independently-fit per-slot models
  (ADR-001 §3a) directly in the training-data weights — reusing the same
  weighted-pool mechanism as `magnitude_weight_i` (ADR-001 §2) — instead
  of a separate, blind post-hoc smoothing pass.
- **Pro:** §2's median-based exclusion means smoothing (§1) does not
  have to choose between "smooth everywhere" and "smooth nowhere" — it
  gets the benefit of pooling neighbor data in calm regions while
  automatically backing off exactly at shading boundaries, where pooling
  would otherwise actively hurt, without needing to detect "this is a
  boundary" as a special case anywhere in the code. §3's rescale
  alternative (`-1%` sentinel) gives a second option for installations
  that would rather keep every neighbor's data, corrected, than lose it
  outright.
- **Con:** Temporal smoothing (§1) trades a small amount of temporal
  resolution for stability — with the default radius of 1, a genuinely
  very sharp shading transition that occurs within a single 5-minute slot
  will be very slightly softened across its two immediate neighbors. This
  is deliberately tunable (down to `0`, disabling it) rather than fixed,
  precisely because how sharp a "real" transition is expected to be varies
  by installation.
- **Con:** §2's default 25% deviation cut-off, while config-flow exposed
  (ADR-010), still ships with a default that is a reasonable starting
  point, not a value validated against real installations yet. Set too
  low, it would exclude neighbors over ordinary weather variance, quietly
  shrinking the effective smoothing radius most of the time; set too
  high, it would let a genuine regime difference through.

---

## Revision note

**2026-08-17 split:** this content originally lived in ADR-001 as
§3b/§3c/§3d. It was extracted into this document because it is a
separable concern from ADR-001's own regression-method and granularity
decisions, and was already being referenced externally (ADR-004,
ADR-007, ADR-008, ADR-010) as a self-contained unit — the same rationale
ADR-001's 2026-08-14 split (into ADR-009/ADR-010) already used. This was
a pure documentation reorganization: no decision, default, or behavior
changed. All cross-references throughout the ADR set were updated to
point at this document directly.
