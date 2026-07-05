# ADR-003 – Optional Per-String Yield Corrections: Clipping and Derating

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

ADR-001 infers shading purely from the gap between a string's baseline
forecast and its actual historical yield. Two real, common phenomena
produce a gap of the *same shape* for reasons that have nothing to do with
shading, and would otherwise be silently absorbed into the learned
shading factor as if they were shading:

- **Inverter clipping.** An inverter has a maximum AC output power. If the
  array's DC potential exceeds it (e.g. a 6 kWp array on a 5 kW inverter
  at high irradiance), actual yield flatlines at the inverter's limit
  regardless of how much more sunlight is available. This happens
  systematically around solar noon / high sun elevation.
- **Temperature derating.** PV module output falls as cell temperature
  rises above the 25 °C standard test condition, by a module-specific
  coefficient (typically on the order of −0.3 to −0.5 %/°C). This
  systematically lowers yield on hot days, independent of shading — and,
  critically, in the same summer months that ADR-001 §4's rolling window
  is already trying to track for a *different* reason (deciduous canopy
  density). Left unmodeled, temperature derating and canopy-density change
  would be conflated into one number, with no way to tell how much of a
  summer shading dip is the tree and how much is heat.

Neither of these is a Shady-specific novelty — both are well-known PV
phenomena — but they are **not already conceptualized in Effy**. Effy
solves a different problem (distributing an already-measured loss between
input and output sensors, ADR-001/005 there); it never compares a forecast
to an actual value and has no notion of clipping or temperature at all.
This ADR is Shady's own.

---

## Decision

Both corrections are **optional, per-string** settings (unlike the
regression method and smoothing radius in ADR-001 §2/§3b, which are
global) — surfaced through an advanced, opt-in step in the config flow,
since not every installation is clipped or thermally exposed to the same
degree, and forcing every user to answer these questions up front would
add friction to the common case where they don't apply.

### 1 — Clipping: exclude, don't downweight

If the user configures an **inverter AC power limit** for a string, any
historical sample whose actual yield is at or above a threshold fraction
of that limit (default 98%) is **excluded entirely** from that string's
training data — not downweighted, unlike the existing
`magnitude_weight_i` treatment of near-zero baseline samples (ADR-001
§2).

The distinction matters: a near-zero baseline sample is merely *noisy*
(the true ratio is still meaningful, just unreliable), whereas a clipped
sample is *censored* — the actual yield at that moment carries no
information about what the unshaded, unclipped yield would have been, in
either direction. Downweighting a censored sample still lets it pull the
fit slightly toward "no shading here", which is not something the data
actually supports; excluding it is the correct treatment of censored
data, not a stricter version of the same downweighting mechanism.

**Amendment — the same limit also bounds the corrected output, not only
the training data.** Excluding clipped samples from training (above)
keeps the *fit itself* honest, but says nothing about what happens at
*prediction* time: a fitted model — especially `wls2`/`wls3` with their
curvature — can still predict a corrected forecast above the inverter's
physical ceiling for an unusually high `FC` value, the same extrapolation
failure mode ADR-001 §2 already demonstrates numerically. So when an
inverter AC power limit is configured for a string, it is applied as a
**second, tighter upper clamp** on top of ADR-001 §2's `[0, FC]` clamp —
the corrected output is clamped to `[0, min(FC, inverter_limit)]`. This
costs nothing extra to implement (it is the same clamp mechanism,
just with a second bound) and closes a gap that the training-time
exclusion alone does not: excluding clipped samples stops the model from
*learning* the wrong shape, but only the output clamp stops it from
*predicting* past a limit it never saw violated in training either.

### 2 — Derating: correct before the ratio is formed, not inside the model

If a temperature source is configured (see §2a) and a **temperature
coefficient** (%/°C, default −0.4, a typical crystalline-silicon value)
is set for a string, the actual yield sample is temperature-corrected to
its 25 °C-equivalent value *before* `ratio_i = actual_yield_i /
baseline_forecast_i` is computed:

```
actual_corrected = actual_raw / (1 + coefficient_per_c · (cell_temperature − 25))
```

This is a pre-processing step, not a regression concern — the regression
strategies in `regression/` (ADR-001 §2) never see raw, temperature-biased
samples in the first place, and have no knowledge that derating correction
happened at all. This keeps the learned shading factor meaning exactly one
thing (shading), rather than "shading plus whatever thermal effect wasn't
otherwise accounted for", and keeps `regression/` itself unaware of a
concern that belongs one layer below it.

### 2a — Temperature source: a hierarchy, not one fixed sensor type

A dedicated per-module/per-string temperature sensor is the most accurate
input to §2, but is uncommon — most installations have, at best, a single
ambient sensor for the whole property, or only whatever a weather
integration reports. Rather than requiring a module sensor, three source
types are supported, in order of accuracy:

| Source | Accuracy | How it's used |
|---|---|---|
| Per-string module/cell temperature sensor | Best — actual measured cell temperature | Used directly as `cell_temperature` in §2's formula |
| Global ambient temperature sensor (one sensor, shared across strings) | Good | Uplifted to an estimated cell temperature first (below) |
| Weather-integration current temperature (a `weather.*` entity's current condition, not its forecast) | Weakest, but still better than no correction at all | Same uplift as the ambient case |

Unlike the baseline-discovery heuristics in ADR-001 §5, no attribute-shape
scoring is needed here: Home Assistant's `device_class: temperature` on
`sensor.*` entities, and the `temperature` attribute on `weather.*`
entities, are stable, versioned conventions — a plain entity selector
filtered to those is sufficient, with no candidate-ranking step.

**Ambient → cell temperature uplift**, used whenever the configured source
is ambient or weather-based rather than a direct module reading:

```
cell_temperature ≈ ambient_temperature + max_uplift_c · (baseline_forecast_i / baseline_rated_capacity)
```

`baseline_forecast_i` at the same timestamp is reused as an irradiance
proxy — no separate irradiance sensor is required. At zero baseline
(dawn/dusk/night) the uplift is zero (module is at ambient temperature);
at full rated output, the uplift reaches its configurable maximum (default
`max_uplift_c = 25`, a common rule-of-thumb figure for module-over-ambient
temperature rise at full sun with light wind). This is a deliberately
simple approximation (no wind-speed term, unlike e.g. the Sandia/PVWatts
cell-temperature models) — accurate enough to catch the dominant "hot
summer midday" effect that motivates §2 in the first place, without
requiring a wind sensor most users won't have either.

The temperature *source* is configured **globally** (like the regression
method and smoothing radius, ADR-001 §2/§3b) — one default for the whole
integration — but can be **overridden per string** if a particular string
has its own module sensor (see §4). The temperature *coefficient* remains
per-string (§4 unchanged), since different strings can use different
module hardware with different thermal behavior even under the same
temperature source.

### 3 — Module: a new pre-processing layer, below `regression/`

Both corrections live in a new pure module, `yield_correction.py`, sitting
between `providers/` and `regression/` in the dependency chain from
ADR-000 §3:

```
providers/            (baseline + actual-yield raw series)
       ↑
yield_correction.py   (pure logic: excludes clipped samples per §1;
                        applies temperature derating correction per §2;
                        no HA imports, tested with zero mocking like the
                        rest of the pure layer, per ADR-000 §6)
       ↑
regression/            (unchanged from ADR-001 — never sees a raw,
                        clipped, or temperature-biased sample)
```

Both corrections are no-ops when not configured for a string (the
function returns the input series unchanged), so a string with no
inverter limit or temperature sensor configured behaves exactly as
specified in ADR-001, with zero overhead.

### 4 — Config flow: global default source, opt-in advanced step per string

Extending ADR-001 §6's final step, one field is added there for the
temperature source default (§2a):

```
Step "settings" (final, extended):
  - ...(training window, regression method, smoothing radius — unchanged
    from ADR-001 §6)...
  - Default temperature source (optional; entity selector covering
    sensor.* with device_class temperature and weather.* entities;
    leave empty to disable derating correction by default for all strings)
```

`add_string` gains one more question, and a new optional step, exactly as
before:

```
Step "add_string":
  - Name
  - Baseline candidate (§5 of ADR-001)
  - Actual-yield entity
  - "Configure advanced corrections (clipping/derating) for this string?"
    (boolean, default off) → yes: "add_string_advanced", no: "add_another"

Step "add_string_advanced" (optional, per string):
  - Inverter AC power limit (optional number, W; leave empty to disable
    clipping exclusion for this string)
  - Temperature source override (optional entity selector, same domains as
    the global default above; leave empty to use the global default from
    the final step, or "none" to disable derating for this string
    specifically even if a global default is set)
  - Temperature coefficient in %/°C (only shown/used if a temperature
    source — global default or override — applies to this string;
    default −0.4)
  → continues to "add_another"
```

The options flow mirrors this, so corrections can be added to or removed
from an already-configured string later, following the same pattern
established in ADR-001 §6.

---

## Consequences

- **Pro:** Shading factors are no longer confounded with two well-known,
  unrelated PV phenomena — clipping and temperature derating — improving
  accuracy specifically in the conditions (high sun elevation, hot summer
  days) where both are common and would otherwise masquerade as shading.
- **Pro:** Both corrections are fully optional and per-string, so
  installations without a clipping inverter or without a temperature
  sensor pay no config-flow cost and no runtime cost (no-op path, §3).
- **Pro:** Keeping corrections in a dedicated pre-processing module means
  `regression/` (ADR-001 §2) and its four strategies stay exactly as
  specified, with no special-casing for corrected vs. uncorrected samples.
- **Pro:** The output-clamp amendment to §1 closes a gap that
  training-time exclusion alone cannot: it protects the corrected forecast
  itself from exceeding a known physical ceiling even when the fitted
  model — through ordinary extrapolation, not a bug — would otherwise
  predict past it.
- **Pro:** The temperature-source hierarchy (§2a) means derating
  correction is available even without a dedicated module sensor — the
  common case — using a global ambient or weather-provider reading plus
  the existing baseline series as an irradiance proxy, with no new sensor
  type required.
- **Con:** Clipping exclusion (§1) reduces the number of usable samples
  for slots that regularly clip (typically midday, in summer) — precisely
  the slots that, for an unclipped installation, would otherwise have the
  most data. For an installation that clips often, this can noticeably
  slow how quickly midday slots reach useful confidence (ADR-001 §2).
- **Con:** The default clipping threshold (98%) and temperature
  coefficient (−0.4%/°C) are reasonable industry-typical defaults, not
  measured values for the user's specific hardware — a user who leaves
  them at default gets an approximation, not a precise correction.
  Accepted as a reasonable default for a feature that is itself optional.
- **Con:** These settings require the user to know their inverter's rated
  AC power and, if they want derating correction, to already have a
  module/ambient temperature sensor in Home Assistant — not universally
  available, hence the settings being optional rather than a blocking
  requirement.
- **Con:** The ambient → cell temperature uplift (§2a) is a deliberately
  simple approximation (no wind term, a fixed default maximum uplift) —
  it corrects the dominant effect (hot, sunny midday) but is less accurate
  than a real module sensor, and a weather-provider's current-temperature
  reading may itself lag or differ from the actual on-site ambient
  temperature.
