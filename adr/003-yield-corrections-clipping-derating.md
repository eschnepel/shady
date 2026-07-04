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

### 2 — Derating: correct before the ratio is formed, not inside the model

If the user configures a **module temperature sensor** and a **temperature
coefficient** (%/°C, default −0.4, a typical crystalline-silicon value)
for a string, the actual yield sample is temperature-corrected to its
25 °C-equivalent value *before* `ratio_i = actual_yield_i /
baseline_forecast_i` is computed:

```
actual_corrected = actual_raw / (1 + coefficient_per_c · (temperature − 25))
```

This is a pre-processing step, not a regression concern — the regression
strategies in `regression/` (ADR-001 §2) never see raw, temperature-biased
samples in the first place, and have no knowledge that derating correction
happened at all. This keeps the learned shading factor meaning exactly one
thing (shading), rather than "shading plus whatever thermal effect wasn't
otherwise accounted for", and keeps `regression/` itself unaware of a
concern that belongs one layer below it.

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

### 4 — Config flow: an opt-in advanced step per string

Extending ADR-001 §6, `add_string` gains one more question, and a new
optional step:

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
  - Module temperature sensor (optional entity selector, sensor domain,
    device_class temperature; leave empty to disable derating correction)
  - Temperature coefficient in %/°C (only shown/used if a temperature
    sensor is set; default −0.4)
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
