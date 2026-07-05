# ADR-006 – Intraday Deviation Correction for the Remaining-Today Forecast

**Date:** 2026-07-05
**Status:** Accepted

---

## Context

ADR-005 §5/§6 introduced two parallel running integrals since midnight:
actual energy produced (`ShadyPvEnergyIntegralSensor`) and what the
already-corrected forecast implied should have accumulated by now
(`ShadyFcEnergyIntegralSensor`). Comparing them in real time reveals
whether *today specifically* is running ahead of or behind what the model
predicted — capturing same-day effects (an unmodeled event like snow
cover, a sensor fault, an unusually persistent weather pattern) that the
nightly model refit (ADR-002 §1) has no way to react to before tomorrow
at the earliest. This ADR adds an optional mechanism that projects
today's already-observed deviation onto the future portion of ADR-005
§3's per-slot forecast array, so the remaining-day picture — both the
day-array's shape and `ShadyFcRemainingTodaySensor`'s aggregate, which
simply sums that array — can adapt within the same day, not just from one
day to the next.

---

## Decision

### 1 — Deviation ratio, gated by a minimum sample size

```
ratio = pv_integral_today / fc_integral_today
```

using the two ADR-005 §5/§6 integrals as they stand at the moment of
calculation. This ratio is only considered meaningful — and is only
applied at all — once at least **12 "active" slots** (1 hour) have
elapsed today, where "active" reuses the same magnitude-weight threshold
ADR-001 §2 already uses to exclude near-zero-forecast slots (so a slot
before sunrise, or one the source provider considers negligible, does not
count toward the 12). Before that point, `ShadyFcRemainingTodaySensor`
reports its plain, uncorrected value regardless of the cutoff setting in
§2. Gating by **slot count**, not a fixed clock time (e.g. "after
07:00"), keeps this correct across seasons and latitudes without any
extra configuration — what counts as "enough of the day has happened to
trust this" already varies naturally with how early/late "active" slots
begin, which the existing magnitude-weight concept already tracks.

### 2 — Cut-off: one config-flow field, doubling as the enable switch

A single global, config-flow-configurable **cut-off** (a fraction, e.g.
`0.0`–`0.5`) clamps the ratio from §1 to `[1 - cutoff, 1 + cutoff]` before
it is applied. The **default is `0`**, which collapses that clamp range to
exactly `[1, 1]` — i.e. the correction factor is always exactly `1`
(no-op) — functionally disabling the entire mechanism using the same
numeric field that, at any positive value, both enables and bounds it.
This was chosen over a separate boolean "enable intraday correction"
toggle plus a magnitude field: one field with a meaningful zero is one
fewer setting to explain, and `0` is the safest possible default for a
feature that changes same-day forecast behavior.

### 3 — Application: per future slot, not as a single aggregate multiplier

Once both gates (§1's sample-size minimum, and §2's cutoff being
non-zero) are satisfied, the correction is applied to **each individual
future slot** in ADR-005 §3's `slot_values` array — every entry where
`slot_timestamps[i] >= now` is replaced by `slot_values[i] × clamp(ratio,
1-cutoff, 1+cutoff)`. Already-past entries in that array (§3's snapshot
cache) are never touched, matching ADR-002 §3's amendment that past slots
are frozen once their time has passed.

`ShadyFcRemainingTodaySensor` (ADR-005 §4) does **not** gain any
correction logic of its own — it continues to be exactly what it already
was, a filter-and-sum over `slot_values` for `slot_timestamps[i] >= now`.
Since those entries are now themselves corrected (when the feature is
active), §4's aggregate reflects the correction automatically, without
duplicating the ratio/clamp math at the aggregate level. This also means
anyone charting `ShadyFcDaySumSensor`'s raw array (ADR-004/ADR-005) sees
the same corrected shape for the remaining slots that the aggregate
sensor is summing — one source of truth for "what does the rest of today
look like", not two.

The sensor gains attributes for transparency (consistent with the
diagnostic philosophy in ADR-004), attached to `ShadyFcDaySumSensor`
rather than to the remaining-today aggregate, since that is where the
correction actually happens: `intraday_ratio` (the raw, unclamped §1
value), `intraday_correction_active` (boolean — were both gates satisfied
this update), and `slot_values_raw` (the pre-correction array, so a
person can always see what the plain per-slot models said versus what
today's specific performance adjusted them to).

### 4 — Module placement

The ratio-and-clamp math (`intraday_correction_factor(pv_integral,
fc_integral, active_slot_count, cutoff) -> float`) is a pure function
added to `aggregation.py` (ADR-005) — no new module needed, this is the
same kind of cross-string, cross-sensor arithmetic that module already
owns. A second small pure function applies that factor to the future
portion of a `slot_values` array (`apply_intraday_correction(slot_values,
slot_timestamps, now, factor) -> list[float]`), also in `aggregation.py`.
`sensor.py`'s `ShadyFcDaySumSensor` calls both and stores the corrected
array; `ShadyFcRemainingTodaySensor` is unchanged — it already only reads
that array and sums, so it picks up the correction for free. The
config-flow field lives in the same "settings" step as the training
window, regression method, and smoothing radius (ADR-001 §6).

---

## Consequences

- **Pro:** Reacts same-day to real deviations the nightly-refit model
  cannot see until the next recalibration (ADR-002 §1), using only
  already-computed sums — no new fitting or regression step required.
- **Pro:** A single numeric field serving as both enable-flag and safety
  clamp means the default (`0`) is simultaneously "off" and the most
  conservative possible value — a person who never touches this setting
  gets exactly today's status quo behavior.
- **Pro:** Gating by active-slot count rather than a fixed clock time
  keeps the mechanism correct across seasons/latitudes for free, by
  reusing a concept (`magnitude_weight_i`'s active/inactive distinction)
  the design already has, rather than introducing a second notion of
  "has enough of the day happened yet".
- **Pro:** Applying the correction to the per-slot array (§3) rather than
  as a second multiplier on the aggregate sensor means there is exactly
  one place the correction happens — the day-array's shape and the
  remaining-today total are automatically consistent with each other,
  with no risk of the two drifting apart from duplicated logic.
- **Con:** This assumes today's already-observed deviation is likely to
  continue into the rest of the day, which is not always true (e.g. a
  cloud front that clears by early afternoon would leave a lingering
  under-correction for the rest of the day). This is a deliberate, simple
  projection, not a weather-aware model — exactly why the cutoff exists as
  a user-tunable clamp rather than an unclamped correction, so a user who
  finds this assumption doesn't hold well for their situation can bound
  its effect rather than only being able to switch it fully off or fully
  on.
- **Con:** Adds one more correction layer on top of shading/clipping/
  derating (ADR-001/ADR-003) and the per-slot model itself — one more
  thing to account for when a number looks "off" to a person looking at
  the sensor, though the added attributes in §3 aim to keep that
  debuggable without needing to consult ADR-004's diagnostic sensor.
