# ADR-002 – Coordinator Update Strategy: Recalibration vs. Forecast Recompute

**Date:** 2026-07-04
**Status:** Accepted
**Amended:** 2026-07-05 — §3 and §4 updated to reflect the introduction
of `cache.py` (ADR-007) and to cross-reference ADR-005's whole-day
aggregate sensor.
**2026-08-19** — new §4: raw baseline `FC` is now also pushed into
`cache.py` on every baseline update, alongside the corrected forecast;
former §4 ("Resulting module responsibilities") renumbered to §5 and its
`coordinator.py` bullet updated accordingly. See ADR-007a §2/§3 for the
cache-side mechanics and ADR-001 §2 for the updated "Training-time `FC`"
definition this enables. Later the same day, §4's rationale was
generalized into ADR-012 §4 as a policy for any forecast-shaped
provider (temperature included, ADR-003c §7); §4 here was trimmed to
this document's own instantiation of that policy, no behavioral change.
Later still, §4 was trimmed further once ADR-012 §1 gained a `forward()`
provider method and §4's `coordinator.py` loop became fully generic —
this document no longer describes its own listener or push call, only
that baseline's `forward()` reuses ADR-009 §2's canonical-series mapping;
§5's `coordinator.py` bullet updated to match.
**2026-08-23** — new §1a: the original "startup safety net" (§1) only
ever addressed *staleness* (no model fitted yet / last fit >24h old); it
said nothing about a config entry's referenced entities not existing yet
at `async_setup_entry` time because the integration(s) that provide them
haven't loaded yet — a real Home Assistant boot-ordering race with no
prior ADR coverage anywhere in the project. Human-directed amendment,
discovered by the Lead Agent while gathering TASK-0010's Consumed
Interfaces (Phase 3, before any coordinator.py code existed).

---

## Context

ADR-001 established a per-string, per-5-minute-slot model architecture
(§3/§3a): up to `num_strings × 288` independent regression models, each
fitted on a rolling window of history (default 28 days). This raises a
question ADR-001 deliberately left open: **when** does the coordinator
actually (a) refit those models, and (b) recompute the adjusted-forecast
values the user sees?

These are two genuinely different operations with very different cost and
urgency, and conflating them would be wrong in either direction:

- **Refitting** a slot's model means re-running the chosen regression
  strategy (ADR-001 §2) over up to `window_days` samples, for every slot of
  every string. It needs a full day's recorder statistics to be settled
  (so "yesterday" is complete) before it can meaningfully include that day
  — refitting continuously through the day would mostly redo the same
  work with one more/fewer partial-day sample.
- **Recomputing the forecast output** means applying the *already-fitted*
  per-slot factors to whatever the baseline provider's current today/
  tomorrow series says. This is cheap (a lookup + multiplication per
  baseline data point) and should react promptly whenever the baseline
  changes — a PV-forecast or weather integration typically refreshes its
  own forecast every 30–60 minutes as new weather data arrives, and Shady's
  output should reflect that promptly rather than staying stale until the
  next model refit.

---

## Decision

### 1 — Model recalibration: at local midnight, or on manual button press

All configured strings' slot models (ADR-001 §3a) are refitted together,
using **only recorder data up to and including yesterday** — never any
partial data from the day the refit actually runs on, regardless of which
of the two triggers below fired it. This keeps every fit's training set
exactly `window_days` worth of *complete* days (ADR-001 §4); an in-progress
day would otherwise contribute a slot-count that varies by time of day,
subtly biasing whichever slots happen to have already occurred by the time
a fit runs.

Refitting `num_strings × up to 288` slot models is the expensive operation
in this integration (ADR-001 §3a already accepts many small per-slot fits
as cheap *individually*, but the full sweep across every slot of every
string adds up). Because of that cost, exactly two things trigger a refit
— nothing else:

1. **Scheduled, once daily**, via `async_track_time_change(hass, ...,
   hour=0, minute=1, second=0)` — one minute past midnight, giving the
   recorder a moment to settle the previous day's `23:55` slot first.
2. **On demand, via a diagnostic button entity** (`ShadyRecalculateButton`,
   mirroring Effy's `EffyRecalculateButton` in `button.py`) — e.g. after
   the user changes a config option, or simply wants an up-to-date model
   without waiting for the next scheduled run. A button press runs exactly
   the same refit routine as the midnight schedule, including the
   up-to-yesterday cutoff above — pressing the button at 14:00 does not
   pull in today's partial data any more than the midnight run would.

In particular, a baseline-provider update during the day never triggers a
refit by itself (only a forecast recompute, see §2) — that would mean
paying the full-sweep cost every time any provider happens to refresh,
which is neither necessary (the models don't need to change intra-day)
nor affordable at the stated cost.

**Startup safety net:** if, at `async_setup_entry`, no model has been
fitted yet for a config entry (first-ever setup) or the last successful
fit is more than 24h old (e.g. Home Assistant was offline through a
scheduled midnight run), the coordinator runs a fit immediately on
startup, in addition to the daily schedule and the button. This mirrors
Effy's ADR-006 observation that a restart naturally replays initial state
and should trigger the equivalent of a first calculation, rather than
leaving a config entry without any model until the next scheduled time.

### 1a — Startup ordering: a config entry's entities may not exist yet

The startup safety net above assumes the entities a config entry
references (each string's actual-yield entity; each string's resolved
baseline entity, global default or override) already exist in
`hass.states` by the time it runs. On a full Home Assistant restart that
assumption can be false: Shady's `async_setup_entry` may run before the
integration(s) that provide those entities have finished their own
setup — nothing orders custom-component setup relative to each other by
default. Discovered by the human, mid-Phase-3, before `coordinator.py`
or `__init__.py` had any code; recorded here rather than guessed at.

**Decision:** at `async_setup_entry` (`__init__.py`, TASK-0016):

1. If `hass.is_running` is already `True` — a config-entry reload, or
   Shady happens to set up after Home Assistant finished starting —
   check the config entry's required entities (defined below) against
   `hass.states.get(entity_id) is not None` right away. If any are
   missing, raise `homeassistant.exceptions.ConfigEntryNotReady`. Home
   Assistant's own config-entry loader catches this and retries
   `async_setup_entry` automatically with its own exponential backoff —
   no bespoke timer or retry loop needed on Shady's side.
2. If `hass.is_running` is `False` (Home Assistant is still in its own
   startup phase) — it is *expected and normal* for dependency
   entities to not exist yet, so do **not** raise `ConfigEntryNotReady`
   here (that would just be noisy, guaranteed-to-fail churn during
   every boot). Instead: build `hass.data` and forward this config
   entry's platforms (`sensor`/`switch`/`button`) exactly as usual —
   Shady's own entities register on the normal schedule regardless of
   whether its *referenced* entities exist yet — but defer the
   coordinator's startup-safety-net fit (§1 above) via
   `homeassistant.helpers.start.async_at_started(hass, callback)`,
   which fires once Home Assistant reports fully started (or
   immediately, if it already has, by the time the registration runs).
   `async_setup_entry` must not itself block on that event — Shady's
   own setup is part of what Home Assistant is waiting to finish before
   it can report "started," so awaiting the event directly here risks
   delaying that transition for the whole system, not just Shady.
3. When the deferred callback from (2) runs, repeat (1)'s same
   required-entity check. If entities are still missing at that point
   (their owning integration is unusually slow, or genuinely broken),
   `ConfigEntryNotReady` can no longer be raised — `async_setup_entry`
   already returned. Log a warning and call
   `hass.config_entries.async_schedule_reload(entry.entry_id)` after a
   short delay instead, which re-runs `async_setup_entry` from the top;
   since `hass.is_running` is `True` by then, that re-run lands on (1)
   directly, rejoining the standard `ConfigEntryNotReady`-and-backoff
   path rather than needing a second, bespoke retry mechanism.

**Which entities are "required"** (block setup per the above) vs. left
to degrade gracefully: a string's actual-yield entity (always
configured, ADR-010) and a string's resolved baseline entity (global
default or override) *if one is configured at all* — leaving baseline
unset via config-flow manual entry is legitimate (TASK-0009) and is not
an error to retry over. Optional correction-tier entities — a string's
temperature-source override, the global default temperature source, the
weather forecast-temperature entity — are **not** required: ADR-003b/
ADR-003c already define graceful degradation (skip correction, or fall
through a tier) for these being absent or unavailable, and that same
handling covers "not loaded yet" just as well as "genuinely unset" —
retrying setup over an optional entity would be paying the reboot-delay
cost for no benefit.

`coordinator.py` exposes the check itself (`missing_required_entities()`)
rather than `__init__.py` re-deriving per-string entity IDs a second
time — `__init__.py` only decides *when* to call it and what to do with
`ConfigEntryNotReady`/`async_at_started`/`async_schedule_reload`.

### 2 — Forecast recompute: on model update, and on every baseline update

The adjusted-forecast output — for the **future slots only** covered by
§3's today/tomorrow horizon — is recomputed and pushed to each string's
`ShadyForecastSensor`, following the shared-coordinator/subscriber
pattern from Effy's ADR-006 Option C, whenever either of two things
happens:

1. **A model recalibration completes** (§1, from either trigger) — the
   newly-fitted factors are applied to whatever baseline data is currently
   cached.
2. **A configured baseline entity (ADR-009) publishes new today/
   tomorrow data** — the coordinator has a listener on every string's
   baseline entity; each update re-applies the *current* (last-fitted, not
   necessarily just-refit) per-slot models to the new baseline series and
   pushes the result.

This is the cheap operation in the system — a lookup-and-multiply per
baseline data point against an already-fitted model, not a refit — which
is precisely why it can afford to run on every baseline update without
the cost concern that limits §1 to exactly two triggers.

No debounce delay is applied by default: unlike Effy's high-frequency
power/energy sensors (ADR-006's original motivation for debouncing),
baseline forecast/weather entities update at most every 30–60 minutes and
are not expected to burst multiple updates within a short window. This
can be revisited (adding the same debounce mechanism as Effy's coordinator)
if a specific provider is found to emit bursts of updates in practice.

### 3 — Forecast horizon: today (remaining) + tomorrow

Each recompute produces adjusted values for:

- the **remainder of today** — from the next upcoming slot after "now"
  through `23:55`, and
- **all of tomorrow** — `00:00` through `23:55`, if and only if the
  baseline provider's data reaches that far.

This mirrors the today/tomorrow shape most PV-forecast integrations
already expose (e.g. `energy_production_today` /
`energy_production_tomorrow`-style sensors), so Shady's output slots
naturally into dashboards built around that convention. Slots already in
the past (earlier today) are not *recomputed* — Shady adjusts a
forward-looking forecast, not a historical record, and does not write
recorder statistics the way Effy does (out of scope for this integration;
see the open question in the README).

**"Not recomputed" does not mean "not retained".** ADR-005's whole-day
aggregate sensor needs every slot's corrected value for the *entire*
current day, including ones already past by the time anyone looks at the
sensor — and a baseline provider's own live attributes typically stop
covering an hour once it has elapsed, so that data cannot be
reconstructed later from the source. The coordinator therefore **pushes**
each string's corrected value into `cache.py` (ADR-007a §3) at the moment
it is first computed (i.e. while it was still a future slot, per the
normal §2 recompute trigger) — `ShadyForecastSensor`'s series has
`to_index = None` in `cache.py`'s validated-range tracking (ADR-007a §2),
meaning it is populated by push, never by query, and a past entry is
simply never touched again once written. This is a passive cache, not a
second recomputation path — it changes nothing about which slots
actively get *new* predictions (still only "remainder of today +
tomorrow", as above), only about not discarding a value Shady already
computed.

If the baseline provider has not yet published tomorrow's data at the
time of a recompute (e.g. some providers only publish the next day's
forecast later in the evening), Shady simply outputs whatever horizon is
currently available — this is not an error condition, and the missing
period is filled in on the next baseline update.

### 4 — Retaining raw baseline `FC` via push: this document's instance of ADR-012 §4's generic policy

**§2/§3 above establish how the *corrected* forecast reaches `cache.py`.
The *raw* baseline `FC` value each of those corrections started from
gets the same treatment, automatically, because the baseline provider
(`providers/discovery.py` + `providers/normalize.py`) overrides
`forward()` (ADR-012 §1):** its `forward(now)` is backed by the exact
same canonical-series mapping (ADR-009 §2) that already backs its
`fetch()`, just given the live attribute's current forward range instead
of a past one. ADR-012 §4's one generic `coordinator.py` loop picks this
up without any FC-specific listener or push call living in this
document — the loop, the `push(sensor_id, dict[index, value])` call, and
the `not_before_index` guard are all specified once, in ADR-012 §4, not
re-derived here.

What is specific to `FC`: the `sensor_id` pushed to is each string's
resolved baseline entity (ADR-009 §1/§5), and the reason this matters is
recalibration's training pool (ADR-001 §2, ADR-011 §1), which wants
*what the forecast said when the slot was still in the future*. A pushed
value already *is* that, frozen the moment it elapses, with no
reconstruction needed once the slot has passed — recorder query
(ADR-007a §4) remains only the fallback for whatever a config entry's
push history doesn't cover (pre-install data, downtime gaps), exercised
far less often in practice for exactly the window (recent history) a
rolling 28-day training window (ADR-001 §4) draws most of its samples
from.

### 5 — Resulting module responsibilities

- `coordinator.py` owns: the daily recalibration schedule and
  up-to-yesterday cutoff (§1); listeners on every configured baseline
  entity, driving recompute (§2); pushing recomputed results to each
  string's `ShadyForecastSensor` (§3). Raw baseline `FC` (§4) is *not* a
  separate `coordinator.py`-owned responsibility in its own right — it
  falls out of ADR-012 §4's one generic provider-push loop, which
  `coordinator.py` also runs, independently of the recompute listener
  above. The per-string, per-slot fitted-model cache itself lives in
  `cache.py` (ADR-007) — `coordinator.py` reads/writes it but does not
  own its storage. `coordinator.py` exposes the refit routine as a
  single public method so both the midnight schedule and the button (§1)
  call the exact same code path.
- `button.py` adds one diagnostic `ShadyRecalculateButton` per config
  entry (mirroring Effy's `EffyRecalculateButton`), whose `async_press`
  simply calls the coordinator's refit method and logs/swallows exceptions
  per ADR-000 §8.
- `forecast_adjust.py` stays a pure function: given a baseline series (any
  length/horizon) and a slot → model lookup, it returns the adjusted
  series. It has no opinion on *when* it is called or *how far* the input
  series reaches — §3's today/tomorrow windowing is the coordinator's
  concern (it decides what slice of the baseline to pass in), not
  `forecast_adjust.py`'s.

---

## Consequences

- **Pro:** Refit cost is bounded and predictable — at most once per day
  per config entry on the schedule, plus whatever the user explicitly asks
  for via the button, regardless of how often the baseline provider
  updates.
- **Pro:** The manual button (§1) gives the user an explicit, low-surprise
  way to force a refit (e.g. right after changing which entities are
  configured) without needing to understand or wait for the schedule —
  same UX Effy already establishes for its own recalculation button.
- **Pro:** The user-visible forecast still reacts promptly (within one
  event loop cycle, same as Effy's Option A/C) to new weather/forecast
  data, without waiting for the next midnight refit.
- **Pro:** Today/tomorrow output matches the shape of existing PV-forecast
  integrations, so it drops into the same dashboard cards/automations
  users already have.
- **Con:** If the daily midnight run is missed for more than one day in a
  row (e.g. multi-day HA outage), models only catch up gradually via the
  startup safety net firing once, then resuming the normal daily schedule
  — there is no "catch-up" logic to backfill multiple missed days at once,
  since the rolling window (ADR-001 §4) only ever looks at the most recent
  `window_days` of recorder history regardless of when it is run.
- **Con:** No debounce on baseline-update-triggered recomputes (§2) is a
  deliberate simplification that assumes low-frequency baseline updates;
  this is a documented assumption, not a proven one, and may need revisiting
  per-provider.
- **Pro:** §4's raw-`FC` push means recalibration's training pool no
  longer depends on being able to reconstruct a past prediction from a
  provider's live attribute after the fact — a reconstruction the
  attribute itself cannot support (§4) — since the value was captured
  and frozen the moment it was known, the same way the corrected
  forecast already is.
- **Con:** §4's push, via ADR-012 §4's generic loop, is a second,
  independent listener on the same baseline entity §2 already listens
  to for recompute — two registrations on one entity rather than one
  callback doing both, so a reader has to know these are deliberately
  separate concerns (ADR-012 §4) rather than assume one listener implies
  one effect.
- **Neutral:** Because recalibration and forecast recompute are decoupled,
  there is a window (up to 24h, between refits) where the forecast output
  is being produced by a model that is up to a day "older" than the
  latest recorder history — this is intentional (§1) and not a bug.
