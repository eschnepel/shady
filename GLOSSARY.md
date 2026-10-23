# Shady

A Home Assistant integration that corrects a solar (PV) yield forecast for the
shading of one specific roof, by learning from the history of the forecast and
of the actual yield.

## Language

### Slots

**Slot**: A five-minute interval of time, always labelled and entered in the
local timezone.

**Current slot**: The slot the present moment falls in. It has not finished yet.

**Last completed slot**: The most recently finished slot. It is never the
current slot. _Avoid_: Last complete slot

**Pinned slot**: A slot a person has fixed in order to inspect it, instead of
following.

**Following**: The diagnostics' mode in which the diagnosed slot is always the
followed slot, as opposed to pinned. _Avoid_: Auto-tracking

**Followed slot**: The slot that following determines: always the last completed
slot. The forecast sensors and the intraday correction always work from it; the
diagnostics do so while following. _Avoid_: Analysed slot

**Diagnosed slot**: The slot the diagnostics analyse: the followed slot while
following, the pinned slot while pinned.

**Reference timestamp**: The instant a training window is measured from: the
followed slot for the forecast sensors, the diagnosed slot for the diagnostics.

### Days and windows

**Day**: A span of exactly 24 hours: its start is always 24 hours before its
end, regardless of daylight saving time.

**Reference day**: The day that ends at the local midnight closing the date of
the reference timestamp. The only day placed using the daylight-saving setting
of the local timezone; every earlier day lies exactly 24 hours before the next.

**Training window**: The configured number of days immediately before the
reference day. The reference day itself is not part of it. _Avoid_: Rolling
window, window (unqualified)

**Intraday window**: The configured number of most recently completed slots,
ending at the followed slot, over which the intraday correction compares actual
and forecast. Counted in slots, not days. _Avoid_: Rolling window, window
(unqualified)

**Pool**: For one slot, its samples on each day of the training window, together
with those of its neighbor slots.

**Neighbor slot**: A slot a whole number of five-minute steps before or after
another slot, crossing midnight like any other time.

### Learning and forecasting

**Recalibration**: Re-learning, from the training window, how the shading
changes the forecast.

**Recompute**: Applying what the last recalibration learned to the baseline
forecast, producing the corrected forecast.

### Strings and Effy

**String**: One PV string of the roof: the unit Shady learns a shading
correction for, identified by the entity that reports what it really produced.
Effy calls the same thing a _PV input_ and publishes its _effective series_.
_Avoid_: Array, input

**Recalculated-from sensor**: Effy's `sensor.effy_recalculated_from`, which
publishes Effy's configuration as attributes and is updated by Effy's closing
step. A person may pick it in Shady's config flow. _Avoid_: Effy source, Effy
link

**Effy's closing step**: The last write of an Effy recalculation: it updates the
recalculated-from sensor once Effy's statistics and states for that run are
final. Always written with Effy's possessive, because the term is Effy's own.

**Effy mode**: A config entry's state while a recalculated-from sensor is
picked. The strings and the training window come from that sensor, and Effy's
closing step starts Shady's slot job. _Avoid_: following (taken, see
**Following**), Effy sync, live mode

**Slot recalculation**: After Effy's closing step, Shady re-runs its pipeline
for every slot from the recalculated-from sensor's timestamp on and writes the
results to its cache and to the recorder statistics: together up to 6 slots, one
chunk per local day beyond. _Avoid_: replay, actuals refresh, recalculate
without "slot" (Effy's own verb for what Effy does)
