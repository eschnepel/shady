# ADR-001 – Empirical, Sun-Position-Based Shading Model

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

### 1 — Predictor space: sun azimuth/elevation, not calendar time

The regression target is `ratio = actual_yield / baseline_forecast` for a
given string, and the predictor is the **sun's azimuth and elevation** at
that timestamp (computed by `sun_geometry.py` from the configured
lat/lon/elevation), never the timestamp itself.

A static obstruction (a tree, a chimney, a neighboring roofline) blocks the
sun at the same azimuth/elevation combination every time the sun passes
through it, independent of which calendar day that happens to be. Binning
or regressing on time-of-day/day-of-year directly would conflate the
obstruction's true (fixed) geometry with the seasonal drift of the sun's
path, and would need far more historical data to disentangle the two.
Using sun position as the predictor means the model generalizes across
seasons immediately, from however much history is available.

### 2 — Regression method: a pluggable, globally-selected strategy

The regression target is always `ratio = actual_yield / baseline_forecast`,
computed over the historical sample pool that §3a/§3b already define for a
given slot (that slot's own samples, plus up to `smoothing_radius`
neighboring slots, across the rolling window) — and every sample is always
weighted by `magnitude_weight_i` (downweighting near-zero baseline
samples, e.g. sunrise/sunset, for the same reason given below) and by the
time-proximity weight from §3b. *How* that already-local, already-weighted
pool is turned into a factor is a **pluggable strategy**, chosen once by
the user for the whole integration (all strings share the same method;
see §6), not auto-selected and not configurable per string. Four
strategies are supported, behind a shared `regression/base.py` protocol
(`fit(samples) -> FittedModel`, `predict(az, el) -> (factor,
confidence)`):

| Method | Model | Character |
|---|---|---|
| `kernel` (default) | Weighted mean: `Σ w_i · ratio_i / Σ w_i`, `w_i = magnitude_weight_i · time_weight_i` (no azimuth/elevation term) | Simplest, fewest assumptions, most robust with very few samples; ignores any residual azimuth/elevation trend within the pool |
| `linear` | Weighted least squares, degree 1 over the same pool: `factor ≈ β₀ + β₁·az + β₂·el` | Captures a residual linear seasonal-drift trend within the pool; needs a few more samples than `kernel` to estimate reliably |
| `wls2` | Weighted least squares, degree 2: adds `az²`, `az·el`, `el²` | Captures gentle curvature in the residual trend; more parameters, more data-hungry |
| `wls3` | Weighted least squares, degree 3: adds cubic + cross terms | Most flexible of the parametric options; with the pool sizes in play here (at most `window_days · (2·smoothing_radius + 1)`, typically well under 100), risks overfitting the small sample rather than capturing genuine structure |

Note what changed from an earlier draft of this decision: azimuth/
elevation are no longer used as a *distance metric* to define which
historical samples are "close enough" to matter (there is no standalone
azimuth/elevation kernel bandwidth). That job is already done structurally
by the slot pool itself (§3a/§3b) — a slot's pool is, by construction,
already every sample whose sun position was close to today's, because it
is literally the same clock-time slot on other days within the window.
Layering a second, independently-tuned azimuth/elevation bandwidth on top
of that would repeat work the slot partitioning already does, and would
add a parameter with no obvious default (see the discussion this
resolved). Azimuth/elevation still matter, but strictly as **regressors**
for the three WLS variants — capturing whatever small residual trend
exists *within* an already-local pool (mostly season-driven drift over
the rolling window) — never as a distance/locality mechanism.

**Confidence is defined independently of the chosen method**, and is now
simply the normalized sum of sample weights in the slot's pool,
`Σ (magnitude_weight_i · time_weight_i)` — no azimuth/elevation density
calculation is needed, since the pool itself is already the "local
neighborhood". A global polynomial fit (`linear`/`wls2`/`wls3`) has no
intrinsic notion of "how much evidence supports this point" from its
coefficients alone; using the same pool-weight-sum for every method,
regardless of which one produced the point estimate, decouples "how good
is the point estimate" from "how sure are we of it", and means switching
methods never changes what the confidence attribute means.

`kernel` was chosen as the default because it makes the fewest
assumptions about the shape of the residual trend within a pool that is,
by construction, already small and already local (§3a/§3b) — it is simply
the weighted average shading ratio for "this time of day, recently". The
WLS variants exist for users who want the model to also account for a
residual seasonal drift *within* that pool (e.g. because the rolling
window straddles a period of fast solar-position change, like near an
equinox) at the cost of needing slightly more samples to fit reliably —
not, as an earlier draft of this ADR argued, because of any difference in
how well each method captures a "sharp edge" (that concern applied to a
single global model spanning the whole day, before slot partitioning
existed, and no longer applies once every method operates on the same
narrow, pre-localized pool).

Regardless of method, `magnitude_weight_i` downweights samples where
`baseline_forecast_i` is near zero, because `ratio_i` is a division of two
small, noisy numbers there and would otherwise dominate the fit with
spurious extreme values. This mirrors the defensive-clamping philosophy in
Effy's ADR-005 (never let a degenerate input propagate raw).

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
exactly one sample per slot. The predictor within a slot is still sun
azimuth/elevation (§1), and the chosen regression method (§2) still
applies — just fit over a much narrower, slot-local neighborhood instead
of pooling every timestamp of the day into one model. Slots where the sun
is below the horizon for the whole window (pure night) are simply never
fitted/queried.

This is chosen over one continuous per-string model for three reasons:

- **It matches the shape of the problem.** Any baseline forecast is
  already delivered as discrete per-slot values (§5), and the recorder
  statistics Shady reads/writes are natively 5-minute-sliced (Effy
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
  it.** Because neighboring slots' sun positions are almost always very
  close (the sun moves continuously and monotonically through the day), a
  time-of-day-adjacent sample is, physically, nearly the same kind of
  evidence as the slot's own samples — folding `time_weight_i` into the
  same weighted-pool mechanism §2 already uses for `magnitude_weight_i`
  means "similar sun positions with different confidence" is blended
  correctly, using the pool's own weights. A fixed post-hoc smoothing
  window has no such notion: it would blur a genuinely sharp,
  well-supported shading edge exactly as much as it blurs pure noise
  between two low-confidence slots, since it cannot tell the two apart.
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

### 4 — Rolling 28-day training window as the default

The training window defaults to the **most recent 28 days** (configurable,
matching the naming convention of Effy's `DEFAULT_MAX_HISTORY_DAYS`), used
as a rolling window rather than an accumulate-forever or fixed-year window.

This is deliberate, not a data-volume compromise: a static obstruction's
azimuth/elevation footprint is stable across the whole year, but a
**deciduous tree's canopy density is not** — dense foliage in summer casts
a materially different shadow than a bare tree in winter. A window spanning
many months would blend "full canopy" and "bare branches" samples within
the same slot's model (§3a), producing a shading factor that is wrong in
both directions depending on season. A rolling 28-day window instead
tracks *current* canopy state and re-adapts automatically as the season
(and the tree) changes, at the cost of every slot needing up to 28 days
before it has any samples at all, and never having more than 28 to work
with even at steady state — an acceptable trade-off given the cold-start
behavior described in §2 and the small-`n` fitting cost already accepted
in §3a.

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

### 6 — Config flow shape

Given §3 and §5, the config flow collects one or more string definitions
iteratively rather than via parallel multi-selects (which would risk
misordered pairs):

```
Step "add_string":
  - Name (free text, e.g. "Dach Süd")
  - Baseline candidate (dropdown, ranked by providers/discovery.py;
    "None of these" → manual entity + attribute path entry)
  - Actual-yield entity (standard HA entity selector, sensor domain,
    power or energy device_class)
Step "add_another":
  - "Add another string?" (boolean) → back to "add_string" or continue
Step "location_and_window" (final):
  - Latitude/longitude/elevation (default from hass.config, overridable)
  - Training window in days (default 28)
  - Regression method: `kernel` (default) / `linear` / `wls2` / `wls3`
    (global — applies to every configured string, see §2; chosen manually,
    no auto-selection based on data volume)
  - Smoothing radius in slots (default 1, global; see §3b — `0` disables
    temporal smoothing)
```

The options flow mirrors this to allow adding/editing strings and changing
the training window after initial setup, following the same pattern as
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
- **Pro:** `kernel` (§2, default) makes the fewest assumptions and needs
  the least data of the four strategies, since it is just the weighted
  mean of an already-local pool (§3a/§3b) — a sensible default precisely
  because that pool is small; the `linear`/`wls2`/`wls3` alternatives let
  a user trade some of that robustness for capturing a residual seasonal
  trend within the same pool, all four sharing one confidence definition
  so switching methods never changes what the confidence attribute means.
- **Pro:** Slot partitioning (§3a) means producing an adjusted forecast is
  always a direct per-slot model lookup, matching the recorder's own
  5-minute grid (Effy ADR-003) with no per-query neighbor search over the
  full historical point cloud, and keeps recalibration cost small and
  independent per slot; temporal smoothing (§3b) resolves the resulting
  slot-boundary discontinuity risk directly in the training-data weights
  (reusing the same weighted-pool mechanism as `magnitude_weight_i`),
  instead of a separate blind post-hoc smoothing pass — and removes the
  need for a second, hard-to-default azimuth/elevation bandwidth parameter
  entirely (§2).
- **Con:** The model needs real historical data to become useful; a
  freshly-configured string effectively passes the baseline through
  unmodified (low confidence everywhere) until enough sun-position
  coverage accumulates — expected to take days to a few weeks depending on
  latitude and time of year.
- **Con:** Attribute-shape discovery (§5) is inherently heuristic and reads
  data across an unversioned surface (other integrations' attributes).
  Mitigated by always requiring user confirmation and offering a manual
  fallback, but a future HA core or integration update could still change
  an attribute's shape without notice, same caveat as Effy's ADR-003.
- **Con:** A 28-day rolling default (§4) means slots (§3a) that only ever
  see a narrow, drifting sun position across the window (e.g. near
  sunrise/sunset in a specific season) may have persistently low
  confidence even after long-term use, since a given slot's samples never
  exceed `window_days`. Acceptable for now; may need a slower-decaying
  window specifically for such slots if this proves problematic in
  practice.
- **Con:** Temporal smoothing (§3b) trades a small amount of temporal
  resolution for stability — with the default radius of 1, a genuinely
  very sharp shading transition that occurs within a single 5-minute slot
  will be very slightly softened across its two immediate neighbors. This
  is deliberately tunable (down to `0`, disabling it) rather than fixed,
  precisely because how sharp a "real" transition is expected to be varies
  by installation.
- **Con:** The regression method (§2) is a single, global choice across all
  configured strings. A system with genuinely different characteristics
  per string (e.g. one string whose pool has a strong residual seasonal
  trend worth capturing with `wls2`, another where `kernel`'s plain
  weighted mean is already sufficient) cannot mix methods; the user must
  pick the one method that serves the whole installation. Revisit as a
  per-string option if this turns out to matter in practice (see also the
  "pro String" decision in §3, which already allows separate *models* —
  just not separate *methods* — per string).
