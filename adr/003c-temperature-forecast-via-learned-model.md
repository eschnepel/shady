# ADR-003c – Temperature Derating: Forecasting the Target-Slot Temperature via a Learned Per-Slot Model

**Date:** 2026-08-18
**Status:** Accepted
**Amends:** ADR-003b §1a/§1b (temperature source hierarchy and the
prediction-time reverse transform), ADR-012 §3 (the naive-persistence
fallback it specified is superseded here — see ADR-012's own amendment
note), and ADR-010 (adds the "weather forecast entity for temperature
prediction" field to the config flow's "settings" step — see §3 below).
**Amended:** 2026-08-19 — new §7: this predictor's historical samples
are now also captured via push, on its own listener, per ADR-012 §4's
generic policy — no behavior change to §4's prediction-time read or to
ADR-002's recompute triggers. Later the same day, §7 trimmed further:
once ADR-012 §1 gained a `forward()` provider method, §7 no longer
describes its own listener or push call, only that this predictor's
`forward()` maps the live `forecast` attribute onto ADR-009 §2's
canonical series shape.

---

## Context

ADR-003b §1b's reverse transform needs a genuine *forecast* of
`target_cell_temperature` for a future slot, not merely a current
reading. Of the three sources in ADR-003b §1a's hierarchy, only the
**weather-integration** tier has native forecast capability (a
`weather.*` entity's own `forecast` attribute). The **module/cell
sensor** and **ambient sensor** tiers are, by design, plain live sensors
with no forecasting concept of their own — as originally accepted, both
fell back to a naive persistence assumption (ADR-012 §3: hold the last
known reading constant across every future slot), a real but
deliberately crude approximation, weakest exactly when the prediction
horizon is longest.

Both of these tiers *do* have something better available: a historical
relationship between the reading they measure (cell or ambient
temperature) and a genuinely forecastable quantity — outdoor/weather
temperature — that Shady already has the machinery to learn. This is the
same shape of problem ADR-001 already solves for shading: a per-slot
relationship, learned from a rolling window of historical pairs, applied
to a live/forecast predictor value to produce a prediction. This ADR
reuses that machinery for temperature instead of building a second one.

---

## Decision

### 1 — Scope: cell and ambient tiers only

This document applies to the module/cell-sensor and ambient-sensor tiers
of ADR-003b §1a. The weather-integration tier is unaffected — it
continues using its own `forecast` attribute directly, exactly as
ADR-003b §1b already specifies; it has no need for a learned model since
it already forecasts.

### 2 — One learned model per 5-minute-of-day slot, same grid as ADR-001

For each of the two applicable tiers, Shady trains one independent model
per slot — the same 288-slots-per-day grid ADR-001 §3 already
partitions PV models on, over the same rolling window
(`window_days`, ADR-001 §4 — no separate window setting for this model):

```
predicted_temp_slot = g_slot(weather_forecast_temp)
```

- **Predictor (`X`)** — historical readings of a forecast-capable
  temperature source. See §3 for which entity this is.
- **Target (`Y`)** — the tier's own sensor: the cell/module sensor's
  history (cell tier) or the ambient sensor's history (ambient tier).
  Already flows through `cache.py` unchanged (ADR-012 §3).
- **Fit** — reuses `regression/`'s existing pluggable strategies
  (`linear`/`kernel`/`wls2`/`wls3`, ADR-001 §2) for the curve-fitting
  mechanics only. Default method is `wls2`, selected via a new **global**
  config-flow option (ADR-010) — separate from ADR-001 §2's own
  regression-method field, since the shading model and this temperature
  model fit different physical relationships and are not forced to share
  one method choice.
- **Not reused:** ADR-001 §2's `magnitude_weight_i` downweighting of
  near-zero-forecast samples. That mechanism exists because near-zero
  solar irradiance is a genuinely degenerate case for the shading ratio;
  temperature has no equivalent degeneracy near any particular value, so
  applying it here would downweight ordinary, perfectly informative cold
  readings for no reason. This model uses `regression/`'s strategies for
  their fitting mechanics only, not their PV-specific sample-validity
  assumptions.
- **Not reused (for now):** ADR-011's temporal smoothing and
  neighbor-regime exclusion. Those exist to prevent hard jumps at a
  *shading* boundary specifically; whether an analogous smoothing would
  help a temperature curve is a real question, but it is a separate one.
  This document does not extend ADR-011 to the temperature model — left
  as a candidate future ADR if slot-to-slot discontinuities prove to be a
  problem in practice.

### 3 — Predictor source: a dedicated, explicit config-flow field

The predictor requires a forecast-capable `weather.*` entity. This is a
new, explicit, **global** config-flow field — a **weather forecast
entity for temperature prediction** — rather than being inferred
opportunistically from whichever entity happens to already be configured
for something else:

- **Global, not per-string** — like the temperature source default
  (ADR-003b §1a), the regression method (ADR-001 §2), and the smoothing
  radius (ADR-011 §1): outdoor weather-forecast temperature is a
  property-wide value, not something that varies string to string, so
  one setting for the whole config entry is the right scope, not a
  per-string override.
- **Independent of the baseline FC provider.** An earlier version of
  this decision reused the baseline provider's own entity when it
  happened to be `weather.*` domain, to avoid a second field. That was
  rejected: it made a string's actual temperature-forecast coverage
  depend on which baseline provider happened to be configured, in a way
  invisible from the temperature-source config field itself — exactly
  the diagnosability gap flagged as an open Con in this document's first
  version. An explicit field means a user (or a future diagnostics
  sensor) can answer "is forecast-based derating active for this
  string?" by reading one setting, not by cross-referencing which
  baseline provider resolved to what.
- **Optional; leave empty to disable this mechanism.** If unset, §5's
  no-predictor rule applies to the cell and ambient tiers exactly as if
  no forecast-capable entity existed anywhere — the field's presence or
  absence *is* the answer to whether ADR-003c's forecast mechanism is
  active, with nothing else to check.
- **Entity selection, not discovery.** As with ADR-003b §1a's existing
  temperature-source field, no attribute-shape scoring is needed: a
  plain entity selector filtered to `weather.*` domain is sufficient
  (ADR-003b §1a's own reasoning for why `weather.*`'s `temperature`
  attribute needs no discovery step applies unchanged here).

This is a provider in ADR-012 §1's sense (`fetch(start, end)` matching
`cache.py`'s `fetch_fn` shape) — its `identify()` is trivial, resolving
directly to whatever entity this field names, with no scoring and no
dependency on ADR-009's baseline discovery. It sits alongside
`providers/temperature.py` as a small, independent provider; no new
module is needed for it.

### 4 — Applying the prediction

At prediction time, the weather entity's own `forecast` attribute value
for the target slot's timestamp is fed into that slot's fitted
`g_slot`, producing `predicted_temp` for a future slot the model has
never seen a live reading for yet.

- **Cell/module tier:** `predicted_temp` is used directly as
  `target_cell_temperature` in ADR-003b §1b's reverse formula — no
  uplift step. The model was trained against actual cell-sensor
  readings, so its output is cell-equivalent by construction; applying
  ADR-003b §1a's ambient→cell uplift formula on top would be a category
  error — uplifting a value that is already a cell-temperature estimate.
- **Ambient tier:** `predicted_temp` is ambient-equivalent (trained
  against ambient-sensor readings) and is passed through ADR-003b §1a's
  existing uplift formula unchanged, exactly as a live ambient reading
  would have been.

### 5 — No predictor, no correction — forward and backward together

If no weather forecast entity is configured in §3's dedicated field —
or a string uses the cell or ambient tier while that field is left empty
— temperature derating is **not** attempted in any degraded form for
that string. Both ADR-003b §1 (forward, training-time normalization) and
ADR-003b §1b (reverse, prediction-time transform) are skipped — not only
the reverse step. This replaces the previously-accepted naive-persistence
fallback (ADR-012 §3) entirely for this correction: a training-time-only
correction with no matching prediction-time reversal is exactly the
"new, opposite bias" ADR-003b §1b's own Context already warns against
introducing, so it is not an acceptable degraded mode — no correction at
all is preferable to one applied on only one side of the round-trip.

### 6 — Cache and pool reuse: no new storage

Both the predictor series and the target series are ordinary time
series, read through `cache.py`'s existing `get_time_range` accessor
(ADR-007a §5 / ADR-012 §3) — additional `sensor_id` values, nothing
about `cache.py` changes. The predictor's training-vs-prediction duality
(historical reading for fitting, `forecast` attribute for prediction) is
the same shape ADR-001 §2 already documents for `FC` itself
("Training-time `FC`" vs. "Prediction-time `FC`") — reused unchanged,
not a new pattern, including how that duality is now sourced: see §7.

The batched, padded pool needed for the actual per-slot fit reuses
ADR-008's `get_regression_pools` accessor as-is — confirmed, not merely
assumed: its signature (`sensor_ids: list[str]` in,
`dict[sensor_id, np.ndarray]` out, ADR-008 §2) is already generic over
any set of sensor IDs, and ADR-008 itself states the PV-specific
weighting (`magnitude_weight_i`, time/neighbor-distance) is computed
separately in `regression/base.py`, not inside the accessor. No
signature change, no rename, no second accessor.

### 7 — Predictor push: this document's instance of ADR-012 §4's generic policy

§6 calls the predictor's training-vs-prediction duality "the same shape"
as `FC`'s. That now extends to *how* training-time samples are
captured, not just how they are later read: this predictor's
`providers/temperature.py` instance (§3) overrides `forward(now)`
(ADR-012 §1) by mapping the weather entity's live `forecast` attribute
onto the same canonical `list[tuple[datetime, float]]` shape ADR-009 §2
established for baseline — the second, independent case ADR-012 §4
named when it generalized `FC`'s push into a policy, not a new mechanism
invented here.

Nothing else needs stating: ADR-012 §4's one generic `coordinator.py`
loop finds this override, registers a listener on §3's weather entity,
and pushes on every update, using the same `push(sensor_id, dict[index,
value])` call and `not_before_index` guard as every other provider — no
temperature-specific listener or push call lives in this document. A
slot's predictor value is frozen the moment it elapses, for the
identical reason ADR-012 §4 gives generically: a `forecast` attribute is
a snapshot of current belief, not a queryable record of what it believed
at a past moment, so recorder query (ADR-007a §4) remains only the
backfill/gap path — the 28 days predating a string's first
temperature-model fit, or a gap from downtime — not the primary source
of training-time predictor samples going forward.

This provider's listener firing does **not**, by itself, trigger ADR-002
§1/§2's recalibration or recompute — per ADR-012 §4, push and recompute
are independent concerns, and this document does not change ADR-002's
triggers. §4's prediction-time read (the live `forecast` attribute value
fed into `g_slot`) still happens at whatever moment ADR-002 §2's own
trigger fires, unaffected by this section; §7 only governs how that same
predictor's *historical* samples end up already sitting in `cache.py` by
the time the next recalibration wants them.

---

## Consequences

- **Pro:** Replaces a deliberately crude approximation (flat persistence
  of a single stale reading) with an actual learned forecast, for the
  two tiers most likely to be configured (a dedicated sensor is more
  common than a weather-integration-only setup for the *source* of
  truth, even though it lacks native forecasting).
- **Pro:** The predictor is an explicit, dedicated setting (§3) — whether
  forecast-based derating is active for a string's cell/ambient tier is
  answered by one config-flow field, not by cross-referencing which
  baseline provider happens to be configured.
- **Pro:** Reuses `regression/`, `cache.py`, and the FC-style
  training-vs-prediction duality wholesale — no new cache mechanism, no
  new model-fitting code path, no new persisted state.
- **Pro:** §5's "no correction without a real forecast" rule removes a
  known, previously-accepted source of systematic error (persistence
  degrading with prediction horizon) rather than merely documenting it
  as an accepted limitation.
- **Con:** §5 means a string using the cell or ambient tier, with a
  `sensor.*`-only baseline and no weather-integration entity configured
  anywhere, loses temperature derating entirely rather than getting a
  degraded version of it — a regression in coverage compared to the
  previously-accepted persistence fallback, traded for correctness.
- **Con:** Reusing `regression/`'s strategies for a second, unrelated
  physical relationship (temperature, not shading) means a future reader
  has to keep straight that `wls2`'s curvature behavior was chosen and
  validated for the shading model (ADR-001 §2); its suitability for a
  temperature curve is a separate, not-yet-validated assumption, and the
  default here is not evidence it also fits this problem well.
- **Con:** The explicit field (§3) is one more setting in an already
  long advanced config-flow step, and — unlike the baseline-reuse
  approach it replaced — requires the user to point it at a
  forecast-capable `weather.*` entity themselves even if one is already
  configured elsewhere in their Home Assistant instance for another
  purpose (e.g. as the baseline FC provider). Traded deliberately for
  the explicitness described above.
- **Pro:** §7's push means this predictor's training-time samples no
  longer depend on reconstructing a past belief from a `weather.*`
  entity's live `forecast` attribute after the fact — the same fix
  ADR-002 §4 gives `FC`, now covering the second of the two providers
  that actually need it.
- **Con:** §7's `forward()` override means ADR-012 §4's generic loop
  registers a second coordinator listener (the weather-prediction
  entity) that exists purely to push and does not participate in
  ADR-002's recompute triggers — one more listener kind for a future
  reader of `coordinator.py` to keep straight from the recompute-
  triggering baseline one, mirroring the identical trade-off ADR-012 §4
  already accepts generically.
