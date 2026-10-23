# ADR-017 – Slot Recalculation After Effy's Rewrite: Pure Pipeline, Per-Day As-Of Refit and Statistics Write-Back

**Date:** 2026-10-20 **Status:** Accepted — confirmed by the human on 2026-10-21
(Gate 2; it began as a draft). Decisions were taken in the `grill-with-docs`
session of 2026-10-20 (question numbers Q23–Q39 in brackets). Items the human
did not answer explicitly and that were decided with the Lead Agent's
recommendation are marked *(taken as agreed)*. **Related:** ADR-016 (Effy mode;
the trigger and the state's meaning), ADR-007a §3/§4 (`Cache`), ADR-005 (the
sensors), ADR-004/008 (the fit), Effy's ADR-021.

______________________________________________________________________

## Context

Effy rewrites *past* statistics (after a counter jump, or in a history
recalculation); raw PV sensors never do. Shady's design assumed the past never
changes: the `Cache` keeps an elapsed slot's pushed value frozen (`push` drops
indices below `not_before_index`, ADR-007a §3), the recorder compiles Shady's
own sensors' statistics from the states it sees live, and the intraday
correction advances forward only. After an Effy rewrite the cached actual
yields, Shady's own frozen forecast values and the statistics built from them
are stale. The state of the recalculated-from sensor is the earliest slot Effy's
latest run rewrote (Effy ADR-021); Effy's routine run reaches back about 20
minutes (4–5 slots), a counter jump or a history recalculation reaches further.

## Decisions

### 1. Range (Q23, Q24, Q27)

On a closing step that is **not** restored-marked (`restored_as_of`) and whose
state parses as a timestamp *t*: affected slots = newest complete slot −
slot(*t*) + 1. The start is clamped to what the cache and the recorder retain; a
*t* after the newest slot counts as one slot. A restored-marked or unparsable
state starts the normal slot job only and never a range — a restored *t* would
redo whatever Effy last did, possibly 28 days, at every reboot. **Slot
recalculation** is the glossary's name for everything below.

### 2. One invalidation, one prefetch (Q35)

One `Cache.invalidate` call per series over `[slot(t), newest]`: each string's
actual-yield entity and every series Shady itself pushed that the recalculation
rewrites (the per-string forecast sensors and the raw-forecast series), because
a frozen elapsed slot can only be re-pushed after it was invalidated. Baseline
history and temperature are not Effy's and are not invalidated. Then **one**
`get_time_range` over `[slot(t) − window_days, newest]` (clamped) for all inputs
— actuals, baseline with `allow_historical_backfill`, temperature — prefetches
the whole dataset in one go; no new `Cache` method is needed. The span before
*t* is what the per-day as-of refit of §5 reads. The prefetch is one cache job,
so the next live slot job waits behind it (on a Pi for a 28-day history run:
tens of seconds, to be measured).

### 3. Batching (Q26, Q27, Q33)

Up to **6** affected slots (a constant, not an option; Effy's routine run is 4–5
slots, so 6 is the first count that is not routine): processed together in one
batch, even across local midnight, with the live model. More than 6: one chunk
per HA local calendar day, oldest first (the first chunk starts at slot *t*, the
last ends at the newest slot; 23- and 25-hour days need no special case because
slots are timestamp-indexed). Each chunk is its own `async_run_cache_job`, so a
live slot job runs between chunks. The old rule "the normal slot job first for
more than 6" is dropped: the newest slot's pipeline is the last one.

### 4. The pipeline for one slot is pure (Q33, Q38)

The pipeline of slot *k* is the tick that produces slot *k*'s values: the
per-string intraday advance from the prefetched inputs, the per-string forecast
and the derived sensors (sums, day total, remaining today, the two integrals) as
of that tick, plus the actuals at *k*. It is refactored into functions of
(inputs, state) that return the full output — including the future slots the
tick would push — **without** writing the live cache; the live tick calls them
and commits as before, a recalculated tick commits only slot *k*'s values
(re-pushed into the invalidated, frozen slot) and its statistics. State is the
basis and `reset_at`; `active_slots_since_reset` is derived from the basis
instead of carried, so no per-slot snapshot is needed (a test proves the live
counter and the derived one agree when no tick was missed). The followed-slot
advance and the diagnostics run **once**, for the newest slot, after the last
chunk.

### 5. As-of refit per day chunk (Q34, Q35)

Each chunk of a more-than-6 range begins with a refit **as of that day**: the
training window is the *N* days before the day (*N* = `window_days`), fitted
into a **scratch** model that is never stored live (`async_refit(now)` accepts a
past `now`, but it stores the model and resets the live intraday state, so a
non-storing variant of the same fit is needed). The chunk's intraday state
starts reset at the day's start, as after the live 04:00 refit. A batch of at
most 6 slots uses the live model. After the last chunk, one normal refit as of
now runs (`async_refit`, as the 04:00 run and the button, including recompute
and intraday reset) if the range reached before today's local midnight **and**
covered more than 6 slots; a routine run touching yesterday's last slots right
after midnight never refits *(taken as agreed, Q32)*. A 28-day history run is up
to 28 as-of refits in the background; the cost on a Pi is measured, not assumed,
and exceeding the budget is escalated to the human.

### 6. Statistics write-back (Q37, Q38; recommendations taken as agreed)

Only in Effy mode (only there does a range exist), Shady writes recorder
statistics, short-term and long-term, for the slots it recalculated — its first
statistics writer (the recorder otherwise compiles them from live states).
Effy's `history.py` is the pattern; nothing is imported from it.

- **Which sensors:** every sensor with a state class — the per-string forecast
  sensors, PV sum and forecast sum (`MEASUREMENT`: mean, min, max), the day
  total and remaining today (`TOTAL`) and the two energy integrals
  (`TOTAL_INCREASING`): `state` and `sum`, §7. The diagnostics sensor has no
  state class and is not written.
- **Short-term rows** (5 minutes) for every recalculated slot **inside** the
  recorder's retention only (`keep_days` of the recorder instance, read to skip
  rows that the next purge would delete — not to warn, §9).
- **Long-term rows** (hourly) for every completed hour the range touched. An
  edge hour only partly recalculated is completed from the existing short-term
  rows of its untouched slots; if those are beyond retention the hour is left as
  it is. The hour in progress is not written (the recorder compiles it).
- Statistic IDs are the sensors' entity IDs; Home Assistant's own metadata
  semantics (`has_mean`, `has_sum`, unit) are verified by the worker.

### 7. Cumulative sensors (Q38)

One anchor per cumulative sensor and table recovers `sum` and `state`: the
short-term row of slot *t* − 1 for the short-term rewrite, and the last
long-term row before the first touched hour for the hourly one (two reads per
sensor; if slot *t* − 1 is beyond short-term retention only the hourly anchor is
used). From the anchor each recalculated slot's `state` comes from §4's output
and `sum` is carried forward by Home Assistant's rule for the sensor's class (a
`TOTAL_INCREASING` decrease is a reset). The two integrals are running
accumulators (`cache.energy_total`, advanced on state changes and restored after
a restart), not derived from series: the recalculation re-integrates slot by
slot from the anchor and then **sets the accumulator to the final value** (a new
`Cache` setter), so the next live compile sees no jump — a stale accumulator
would otherwise be read as a reset and produce a spike.

### 8. Overlap (Q25)

One dirty range. A new closing step invalidates its range at once (§2) and
re-plans the chunks that have not started; a running chunk finishes. Shutdown
cancels queued chunks.

### 9. Recorder retention (Q30, Q31, and the human's numbers)

Shady trains on the recorder's 5-minute statistics, and the real limit for them
is the configured `purge_keep_days` — Effy's README and code (which reads the
live value) are right; Shady's earlier README sentence ("a fixed 10 days,
separate from `purge_keep_days`") is wrong and is corrected by `TASK-0047a`.
With the training window *N* days (in Effy mode Effy's `max_history_days`):

- **Minimum:** `purge_keep_days` = *N* + 1 — the newest refit reads the *N*
  whole days before today plus today's running day.
- **Optimal:** 2 × *N* — §5's as-of refit of the oldest recalculated day needs
  *N* days before *that* day (the same reason applies to pinned diagnostics).

Documentation only: Shady does not warn about too-short retention (the retention
value read in §6 only decides which short-term rows are worth writing). Both
numbers go into the README, in the Requirements section and in the Effy-mode
section.

## Consequences

- A pure pipeline, a scratch fit, a statistics writer and `Cache` setters are
  the biggest change in the Effy line; it is its own task (`TASK-0047c`) behind
  `TASK-0047b`.
- Shady writes recorder statistics for the first time; every future change of a
  sensor's value definition must keep §4's pure output and the statistics writer
  consistent.
- The prefetch holds the cache lock for its duration; chunks let live jobs
  interleave.
- A history run costs up to *N* as-of refits; routine closing steps cost one
  batch of 4–5 pure ticks and one statistics write per sensor.
- The statistics of the recalculated slots replace what the recorder compiled
  from live states; the live sensor states themselves are not rewritten.
- Retention below 2 × *N* means the oldest days of a history run cannot be refit
  as of their day; the README says so.

## Alternatives rejected

- **Re-read only, no recalculation (the earlier "actuals refresh").** Leaves
  Shady's own frozen values and statistics stale.
- **Re-running the live slot job per past slot.** It mutates live state; the
  pure pipeline is the same work without that.
- **One current model for all recalculated slots.** Cheaper, but the history
  would not be what a refit on the corrected data of that day gives, and the 2×
  retention would be pointless.
- **Refit whenever yesterday is touched.** Fires about three times every night,
  because Effy's routine window then reaches yesterday's last slots; the
  more-than-6-slots condition removes that.
- **Statistics for `MEASUREMENT` sensors only.** The human chose the cumulative
  ones too, which is what the Energy dashboard reads.
- **Per-slot snapshots of the intraday state.** Derivable from the basis, no
  storage.
- **A Repairs warning for too-short retention.** A new coupling to the recorder
  configuration; a later task if wanted.
