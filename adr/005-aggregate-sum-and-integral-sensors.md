# ADR-005 – Cross-String Aggregate Sensors: Sums and Daily Integrals

**Date:** 2026-07-05
**Status:** Accepted

---

## Context

Every sensor defined so far (ADR-001–ADR-004) lives at the **per-string**
level. A person with several configured strings has no single number for
"how much is the whole system producing right now" or "how much energy
has the whole system produced today", and no way to compare a whole-day
shape of corrected forecast against actual production without manually
summing per-string entities in a dashboard template. This ADR adds a
small set of **config-entry-level** sensors that aggregate across all of
a config entry's configured strings.

---

## Decision

Six new sensors, all at the config-entry level (one of each per config
entry, not per string):

### 1 — `ShadyPvSumSensor` — current actual yield, summed across strings

Sums the **current state** of every configured string's actual-yield
entity (ADR-001 §6). Unlike every other sensor in this ADR, this one has
nothing to do with the regression models or the coordinator's fit/recompute
cycle (ADR-002) — it is a plain state-tracking aggregate, updating
whenever *any* tracked actual-yield entity changes, independent of
baseline updates or recalibration. State: current summed power (W).

### 2 — `ShadyFcSumSensor` — current corrected forecast, summed across strings

Sums every configured string's **corrected forecast for the current
slot** (ADR-001 §2, after the clamps in ADR-001 §2 and, where configured,
ADR-003 §1a). Updates on the same trigger as the per-string
corrected-forecast sensors (ADR-002 §2 — model update or baseline update),
not independently. State: current summed corrected power (W).

### 3 — `ShadyFcDaySumSensor` — corrected forecast, summed across strings, whole day

The sum, **per slot**, of every configured string's corrected forecast for
*every one of today's 288 slots* — including already-past ones. Each
string's own corrected values are pushed into `cache.py` as they are
computed (ADR-007 §1c — `ShadyForecastSensor`'s series has `to_index =
None`, per ADR-007 §1b, since Shady calculates and pushes it rather than
querying it back), which is what makes past slots still available here
without a second recomputation path (ADR-002 §3). `coordinator.py` builds
this sensor's two array attributes with one call to `cache.py`'s
`get_time_range(string_forecast_sensor_ids, start=00:00, end=23:55,
group_by="slot")` (ADR-007 §1e) — `group_by="slot"` returns one dict per
slot, `{sensor_id: value, ...}`, exactly the shape needed to sum every
string's value at each slot directly, with no separate transpose step:

- `slot_timestamps`: 288 ISO-8601 timestamps, `00:00` through `23:55` of
  the current day.
- `slot_values`: 288 numbers, the cross-string summed corrected power (W)
  for each corresponding timestamp.

The sensor's own **state** is the total daily energy this implies — not a
sum of Watts (which is not itself a meaningful quantity), but `Σ (P_i ×
5/60) ` in Wh, i.e. each slot's power multiplied by its 5-minute duration
in hours before summing. This is the one place in the design so far where
a slot-power-to-slot-energy conversion is needed, and it happens only
here (ADR-001's regression itself always operates on power values per
slot; ADR-005 is where those get integrated into an energy total). The
future portion of `slot_values` (entries not yet past) is where an
optional intraday deviation correction is applied — see ADR-006, which
amends this sensor's array directly rather than any sensor downstream of
it.

### 4 — `ShadyFcRemainingTodaySensor` — expected remaining energy today

The same energy calculation as §3's state, but summing only the slots
from `slot_timestamps` that are still in the future relative to "now" —
i.e. `Σ (P_i × 5/60)` over `slot_values[i]` where `slot_timestamps[i] >=
now`. Reuses §3's cached array rather than recomputing anything; this is
pure post-processing of already-available data, with no correction logic
of its own — if §3's array carries an intraday correction (ADR-006), this
sensor's total reflects it automatically, simply by summing whatever §3
currently holds. State: expected remaining energy today (Wh).

### 5 — `ShadyPvEnergyIntegralSensor` — actual energy today, reset at midnight

A running Riemann-sum integral of §1's power sensor over time (the same
kind of calculation as Home Assistant's built-in Integration helper),
accumulating actual energy produced since midnight. State: cumulative
energy today (Wh), monotonically increasing through the day.

### 6 — `ShadyFcEnergyIntegralSensor` — corrected-forecast energy today, reset at midnight

The same integral treatment as §5, but accumulating §2's corrected
forecast power sensor instead of the actual-yield sum — giving a running
"what the corrected forecast implied should have accumulated by now"
total, directly comparable against §5's actual figure at any point in the
day.

### Implementation notes shared by §5/§6

- **The area-under-the-curve math is a pure function** (`aggregation.py`,
  see the module diagram below): given a previous `(timestamp, power)`
  sample and a new one, compute the trapezoidal energy increment between
  them. This is unit-tested with zero mocking like the rest of the pure
  layer (ADR-000 §6).
- **The running total itself is stateful, and lives in `cache.py`
  (ADR-007) — the one cache instance there that is wired to Home
  Assistant's restore-state mechanism**, since losing it mid-day would
  visibly wrong-foot the sensor (unlike most of `cache.py`'s other
  caches, which are safely rebuildable and so are not restart-persisted).
  `coordinator.py` reads the current total from `cache.py`, adds the
  pure-function increment on every update of the relevant source sum (§1
  or §2 respectively), writes the new total back to `cache.py`, and
  pushes it to the corresponding sensor. `sensor.py`'s
  `ShadyPvEnergyIntegralSensor`/`ShadyFcEnergyIntegralSensor` stay thin —
  they read and display whatever `coordinator.py` last pushed, the same
  relationship every other sensor in this design has to the coordinator.
- **Reset at midnight, not `00:01`.** Unlike ADR-002 §1's recalibration
  schedule (deliberately offset by one minute to let the recorder settle
  the previous day's last slot), a meter-style reset has no such
  settling concern — it should zero out right at the day boundary. This
  is a fourth, independent schedule `coordinator.py` registers alongside
  ADR-002 §1's recalibration schedule and ADR-006 §1's 5-minute
  recorder-poll schedule — `async_track_time_change(hass, ..., hour=0,
  minute=0, second=0)` — deliberately not reusing either of those
  triggers despite all being "periodic coordinator things", and on
  firing, tells `cache.py` to zero the relevant total.

### Module: a new pure aggregation layer

```
forecast_adjust.py     (per-string corrected forecast, unchanged)
       ↑
aggregation.py          (pure logic: cross-string sums for §1/§2/§3/§4;
                         trapezoidal energy-increment calculation for
                         §5/§6; no HA imports, no per-string knowledge of
                         *which* string a value came from — only lists of
                         numbers in, one number or array out)
       ↑
cache.py                (pure logic, ADR-007: stores §5/§6's running
                         totals — restart-persisted, unlike most of this
                         module's other caches — alongside the model
                         cache, day-snapshot array, ramp state, and
                         diagnostic pool cache from other ADRs)
       ↑
coordinator.py          (calls aggregation.py for all six sensors; reads/
                         writes §5/§6's totals via cache.py; registers
                         the midnight-reset schedule above alongside its
                         other three triggers — one orchestrator, not a
                         second one living inside sensor.py)
       ↑
sensor.py               (six thin HA entity classes that read and display
                         whatever coordinator.py last computed — no
                         business logic, no owned state, matching every
                         other sensor in this design)
```

---

## Consequences

- **Pro:** A person with multiple strings gets one number for "the whole
  system, right now" and "the whole system, today" without building
  dashboard-side sum templates themselves.
- **Pro:** §5/§6 side by side give a direct, running actual-vs-corrected-
  forecast comparison in energy terms throughout the day, which is a more
  intuitive way to judge forecast quality than comparing instantaneous
  power at any single moment.
- **Pro:** Reusing §3's cached array for §4 (remaining-today) means no
  second data-retention mechanism is needed for a very similar sensor.
- **Con:** §3's array relies on `cache.py` (ADR-007) having accumulated
  each slot's value by push as the day progressed — its own in-memory
  validated range is *not* restart-persisted (only §5/§6's integral
  totals are, per ADR-007 §1). This is not a permanent data loss, since
  `ShadyForecastSensor` is an ordinary HA entity and the recorder already
  keeps its own history of every value that was ever pushed to it — but
  it does mean a restart mid-day triggers ADR-007 §1d's full-history
  catch-up query for that sensor (recovering exactly what was pushed
  before the restart from the recorder) rather than the cheaper
  incremental-tail path a sensor that had stayed running would have used.
- **Con:** §5/§6's persisted running totals mean Shady is now responsible
  for correct restore-state behavior around restarts and the midnight
  reset boundary (e.g. a restart *during* the reset window needs to not
  double-reset or skip a reset) — the same category of edge case Home
  Assistant's own Integration helper has already had to solve, being
  reimplemented here rather than reused, because Shady needs it wired to
  its own specific midnight trigger rather than a generically-configured
  helper entity.
- **Con:** `ShadyFcDaySumSensor`'s two 288-element array attributes are,
  like ADR-004's `series` attribute, a de-facto public contract once a
  dashboard is built against `slot_timestamps`/`slot_values` — same
  stability caveat as ADR-004's Consequences.
