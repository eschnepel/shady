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

### 2 — Regression method: forecast-magnitude-weighted kernel regression

For a query point `(az, el)`, the shading factor is a **Nadaraya-Watson
kernel-weighted average** over all historical samples `i`:

```
factor(az, el) = Σ w_i · ratio_i / Σ w_i
w_i = kernel(distance((az, el), (az_i, el_i)), bandwidth) · magnitude_weight_i
```

- `kernel(...)` is a standard distance kernel (e.g. Gaussian) over the
  (azimuth, elevation) plane with a configurable bandwidth (default on the
  order of a few degrees — exact default to be tuned empirically once real
  data is available).
- `magnitude_weight_i` downweights samples where `baseline_forecast_i` is
  near zero (sunrise/sunset), because `ratio_i` is a division of two small,
  noisy numbers there and would otherwise dominate the average with
  spurious extreme values. This mirrors the defensive-clamping philosophy
  in Effy's ADR-005 (never let a degenerate input propagate raw).

This approach was chosen over a fixed azimuth/elevation grid with a
separate nearest-neighbor interpolation step for sparse cells, because the
kernel formulation makes sparse-region interpolation and cold-start
behavior **fall out of the same formula** rather than requiring a second
mechanism:

- Sparse regions naturally borrow strength from nearby, better-sampled sun
  positions (no separate interpolation pass).
- With very little history, `Σ w_i` is small everywhere and the estimate
  naturally stays close to unweighted/uncertain rather than requiring an
  explicit "not enough data" branch.
- `Σ w_i` (normalized) is itself a natural **confidence value**, exposed as
  a diagnostic sensor attribute, without any additional bookkeeping.

### 3 — Granularity: one model per configured string

Shady fits and queries a separate regression per configured string/plane,
not one global factor for the whole system. A single global factor would
average away exactly the signal Shady exists to detect: shading that only
affects part of the array (e.g. the east string is behind a tree, the west
string is not). Each string is configured as a `(baseline_series,
actual_yield_entity)` pair (see §5), and gets its own fitted model, its own
confidence, and its own adjusted-forecast output sensor.

### 4 — Rolling 28-day training window as the default

The training window defaults to the **most recent 28 days** (configurable,
matching the naming convention of Effy's `DEFAULT_MAX_HISTORY_DAYS`), used
as a rolling window rather than an accumulate-forever or fixed-year window.

This is deliberate, not a data-volume compromise: a static obstruction's
azimuth/elevation footprint is stable across the whole year, but a
**deciduous tree's canopy density is not** — dense foliage in summer casts
a materially different shadow than a bare tree in winter. A window spanning
many months would blend "full canopy" and "bare branches" samples for the
same sun-position cell, producing a shading factor that is wrong in both
directions depending on season. A rolling 28-day window instead tracks
*current* canopy state and re-adapts automatically as the season (and the
tree) changes, at the cost of needing that many days of history before a
given sun-position cell has any coverage at all — an acceptable trade-off
given the cold-start behavior described in §2.

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
series that `shading_regression.py` and `forecast_adjust.py` consume
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
- **Pro:** Kernel regression (§2) unifies interpolation, cold-start
  behavior, and confidence reporting into a single mechanism instead of
  three separate ones.
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
- **Con:** A 28-day rolling default (§4) means sun-position cells that only
  occur briefly (e.g. a narrow azimuth range at sunrise in a specific
  season) may have persistently low confidence even after long-term use,
  since they don't recur often enough within any 28-day window. Acceptable
  for now; may need a slower-decaying window specifically for rarely-visited
  cells if this proves problematic in practice.
