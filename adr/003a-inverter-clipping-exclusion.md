# ADR-003a – Optional Per-String Yield Correction: Inverter Clipping Exclusion

**Date:** 2026-08-18
**Status:** Accepted
**Split from:** ADR-003 (2026-07-04), §1/§1a. Originally combined with
temperature derating in one document; separated because the two
corrections are independently optional, independently configured, and
share no decision-relevant logic beyond both living in
`yield_correction.py`. No behavior changed by this split — see ADR-003's
Revision note.

---

## Context

ADR-001 infers shading purely from the gap between a string's baseline
forecast and its actual historical yield. **Inverter clipping** produces
a gap of the same shape for a reason that has nothing to do with shading,
and would otherwise be silently absorbed into the learned shading factor
as if it were shading: an inverter has a maximum AC output power, and if
the array's DC potential exceeds it (e.g. a 6 kWp array on a 5 kW
inverter at high irradiance), actual yield flatlines at the inverter's
limit regardless of how much more sunlight is available. This happens
systematically around solar noon / high sun elevation.

This is not a Shady-specific novelty — it's a well-known PV phenomenon —
but it is **not already conceptualized in Effy**: Effy solves a different
problem (distributing an already-measured loss between input and output
sensors, ADR-001/005 there); it never compares a forecast to an actual
value and has no notion of clipping at all. This correction is Shady's
own, alongside temperature derating (ADR-003b), with which it shares a
home in `yield_correction.py` but is otherwise independent — see
ADR-003b's Context for that correction's own motivation.

---

## Decision

Clipping exclusion is optional, so it adds no friction for an
installation that isn't clipped — surfaced through an advanced, opt-in
step in the config flow (ADR-010). Its scope is a mix of global and
per-string: *whether it applies at all* is per-string (an inverter AC
power limit is a property of that specific string's hardware — a string
without one configured is never clipping-excluded), but the threshold
fraction itself is a single **global** setting shared by every string
that has a limit configured. This mirrors the same global-vs-per-string
split already established elsewhere (ADR-001 §2's regression method and
ADR-011 §1's smoothing radius are global; ADR-001 §3's models are
per-string; ADR-003b's temperature-coefficient split follows an
analogous shape) rather than following one uniform rule.

### 1 — Exclude, don't downweight

If the user configures an **inverter AC power limit** for a string, any
historical sample whose actual yield is at or above a threshold fraction
of that limit is **excluded entirely** from that string's training data —
not downweighted, unlike the existing `magnitude_weight_i` treatment of
near-zero baseline samples (ADR-001 §2). The threshold fraction itself
(default 98%) is **not** a per-string setting — it is a single global
value, config-flow-exposed (ADR-010), applied uniformly to every string
that has an inverter AC power limit configured. Splitting it out
per-string would let a user tune it to one specific inverter's clipping
curve slightly more precisely, but the fraction is not sensitive enough
hardware-to-hardware to justify a second per-string field on top of the
limit itself — one global value, close to correct everywhere, is judged
the better trade.

The distinction matters: a near-zero baseline sample is merely *noisy*
(the true ratio is still meaningful, just unreliable), whereas a clipped
sample is *censored* — the actual yield at that moment carries no
information about what the unshaded, unclipped yield would have been, in
either direction. Downweighting a censored sample still lets it pull the
fit slightly toward "no shading here", which is not something the data
actually supports; excluding it is the correct treatment of censored
data, not a stricter version of the same downweighting mechanism.

### 1a — The same limit also bounds the corrected output, not only the training data

Excluding clipped samples from training (§1) keeps the *fit itself*
honest, but says nothing about what happens at *prediction* time: a
fitted model — especially `wls2`/`wls3` with their curvature — can still
predict a corrected forecast above the inverter's physical ceiling for an
unusually high `FC` value, the same extrapolation failure mode ADR-001
§2 already demonstrates numerically. So when an inverter AC power limit
is configured for a string, it is applied as a **second, tighter upper
clamp** on top of ADR-001 §2's `[0, FC]` clamp — the corrected output is
clamped to `[0, min(FC, inverter_limit)]`. This costs nothing extra to
implement (it is the same clamp mechanism, just with a second bound) and
closes a gap that the training-time exclusion alone does not: excluding
clipped samples stops the model from *learning* the wrong shape, but only
the output clamp stops it from *predicting* past a limit it never saw
violated in training either.

### 2 — Module: lives in the shared `yield_correction.py` pre-processing layer

Clipping exclusion is one of two corrections implemented in
`yield_correction.py`, alongside temperature derating (ADR-003b) — the
module's own two-role (forward/reverse) shape is driven entirely by
derating's reverse transform (ADR-003b §1b); clipping's own treatment is
forward-only (samples are excluded from training, §1), with its
prediction-time echo being a second, tighter output clamp (§1a) applied
directly by `forecast_adjust.py`/ADR-001 §2 — not a call back into
`yield_correction.py`. See ADR-003b §2 for the module's full diagram and
up-to-date data flow.

Clipping is a no-op when no inverter AC power limit is configured for a
string (the function returns the input series unchanged) — the same
"no-op when not configured" pattern ADR-004 §1 also follows for its own
optional feature.

### 3 — Config flow: see ADR-010

ADR-010 is the single, authoritative config-flow specification —
including the fields this document introduces (the global clipping
threshold in the "settings" step; the per-string inverter AC power limit
in "add_string_advanced"). This document does not duplicate that
listing.

---

## Consequences

- **Pro:** Shading factors are no longer confounded with inverter
  clipping, improving accuracy specifically around solar noon / high sun
  elevation, where clipping is common and would otherwise masquerade as
  shading.
- **Pro:** Fully optional and per-string, so installations without a
  clipping inverter pay no config-flow cost and no runtime cost (no-op
  path, §2).
- **Pro:** §1a's output clamp closes a gap that training-time exclusion
  alone cannot: it protects the corrected forecast from exceeding a
  known physical ceiling even when the fitted model — through ordinary
  extrapolation, not a bug — would otherwise predict past it.
- **Con:** Clipping exclusion (§1) reduces the number of usable training
  samples for slots that regularly clip (typically midday, in summer) —
  precisely the slots that, for an unclipped installation, would
  otherwise have the most data. For an installation that clips often,
  this can noticeably slow how quickly midday slots reach useful
  confidence (ADR-001 §2).
- **Con:** The default clipping threshold (98%) is a reasonable
  industry-typical default, not a measured value for the user's specific
  hardware — a user who leaves it at default gets an approximation, not
  a precise correction. Accepted as reasonable for a feature that is
  itself optional.
- **Con:** This setting requires the user to know their inverter's rated
  AC power — not universally at hand, hence the setting being optional
  rather than a blocking requirement.
