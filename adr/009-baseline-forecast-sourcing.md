# ADR-009 – Baseline (Unshaded) Forecast Sourcing: Generic Attribute Discovery

**Date:** 2026-08-14 **Status:** Accepted **Split from:** ADR-001 §5. Originally
part of the shading-model ADR; extracted because baseline sourcing is a
separable concern from the regression model itself, and was already being
referenced externally (ADR-003a/ADR-003b, ADR-004) as if it were its own
document. No behavior changed by this split. **Last updated:** 2026-09-15 —
weather sourcing moved from `state.attributes` to `weather.get_forecasts`/
`async_subscribe_forecast` (§1a Amendment); Forecast.Solar sourcing added via
`forecast_solar.get_forecast` polling (§1b Amendment, since that integration's
own sensors expose no forecast-shaped attribute at all any more either); §1's
sunshine-duration description-only fix (`AUDIT-0001-provider-package`): it was
always used unscaled, a regression stage that absorbs arbitrary linear scale
needs no rescale step; no behavior change. **New §1c Amendment below
(2026-09-15, `TASK-0034`):** a `forecast_solar`-shaped candidate now also
resolves a linked, recorder-backed `history_entity_id` at discovery time —
closing the "baseline side of the training pool has no real history" cold-start
bug §1a/§1b's own push-only sourcing otherwise leaves in place indefinitely
across restarts (see `shady-baseline-history-fix.md`, the bug report this
amendment implements). **Further §1c Amendment below (2026-09-17,
`TASK-0034-patch-1`):** the discovery-time resolution above could still silently
freeze at `None` forever if it lost a one-time startup race against
Forecast.Solar's own companion-sensor registration — `async_startup` now retries
it once, self-healing the persisted config entry data on success.

______________________________________________________________________

## Context

The empirical shading model (ADR-001) needs, for every configured string, an
**unshaded reference forecast** (`FC`) to compare each slot's actual yield
(`PV`) against — the whole model is a regression of `PV` on `FC` (ADR-001
§1/§2). Rather than hardcoding adapters for specific PV-forecast integrations
(Forecast.Solar, Solcast, …) — which would need updating every time a new
provider becomes popular or an existing one changes its entity shape — Shady
discovers a usable baseline generically, from whatever forecast-shaped data the
user's Home Assistant instance already exposes.

______________________________________________________________________

## Decision

### 1 — Generic attribute-shape discovery, not per-integration adapters

`providers/discovery.py` scans HA entities for **attribute shapes that look like
a forecast series**, and lets the user confirm the match — it never applies a
detected baseline silently.

Two entity domains are scanned, covering two different kinds of baseline signal:

- **`sensor.*` entities** — for a dedicated PV-forecast integration's output.
  Attribute shapes recognized:
  - dict of `{timestamp: number}` (e.g. Solcast's older attribute-based output;
    Forecast.Solar exposed its own `wh_period` this way historically, but no
    longer does — see §1b Amendment)
  - list of dicts with a timestamp-like key and a numeric value-like key (e.g.
    Solcast's `detailedForecast`)
- **`weather.*` entities** — for users without a dedicated PV-forecast
  integration. Two attribute shapes are recognized here, both proxy baselines
  ("expected yield under a clear/predicted sky") rather than a direct watt/Wh
  series, and both normalized accordingly before entering the regression:
  - sunshine-duration-like values in a weather integration's forecast attribute
    (e.g. `sunshine_duration`, common in DWD/Open-Meteo-based weather
    integrations) — already a *positive* clear-sky proxy (more sunshine ⇒ more
    expected yield), so it is used directly, unscaled. No rescale step is
    needed: ADR-001's regression is an empirical fit of `PV` against whatever
    numeric range `FC` happens to be in, and every one of that ADR's method
    choices (`linear`/`wls2`/`wls3`/ `kernel`) absorbs an arbitrary linear scale
    of its input automatically, producing an equally-good fit with different
    (still entirely valid) regression coefficients — an explicit rescale here
    would change only the *coefficients* the fit learns, not the *quality* of
    what it learns.
  - cloud-coverage-like values (e.g. `cloud_coverage`, `cloud_coverage_total`,
    common in Met.no/OpenWeatherMap-based weather integrations) — the *inverse*
    of a clear-sky proxy (more cloud ⇒ less expected yield).
    `providers/normalize.py` inverts it (e.g. `100 - cloud_coverage` for a
    percentage-scaled source) before it is treated as a baseline value;
    everything downstream of normalization (ADR-001's `regression/`, and this
    ADR's own module) only ever sees the already-inverted, positive-going series
    and has no notion that the raw source was a coverage percentage rather than
    a sunshine duration.

### 1a — Amendment (2026-09-14): weather sourcing via forecast subscription, not state attributes

HA 2024.4 removed the `forecast` state attribute from `weather.*` entities
entirely (deprecated since 2023.9) — the only way to see a weather entity's
forecast data on any current HA install is the `weather.get_forecasts` service
(request/response) or `WeatherEntity.async_subscribe_forecast` (push). §1's
`weather.*` scan above is unaffected in shape/scoring terms, only in *how* it
samples an entity: `providers/discovery.py`'s `_scan_weather_domain` now calls
`weather.get_forecasts` once per candidate (checking `supported_features` first)
instead of reading `state.attributes`, and is therefore `async` — so
`discover_baseline_candidates` (the config flow's one call site) is `async` too.
At runtime, `BaselineProvider` for a `weather_sunshine`/`weather_cloud`
resolution has no attribute left to poll on a state change; instead
`coordinator.py` subscribes to `async_subscribe_forecast` directly (ADR-012 §4a
is the source of truth for that push path) and feeds each pushed forecast into
the provider via `update_live_forecast()`. `sensor.*` sourcing (§1's two other
shapes) is untouched by this amendment — that data is still a plain state
attribute on current HA. **Always hourly:** `weather.get_forecasts` supports
three granularities (`"daily"`/`"hourly"`/`"twice_daily"`); Shady only ever
samples/subscribes to `"hourly"` — the finest one HA's forecast API offers, and
still coarser than baseline `FC`'s own 5-minute slot grid, so a coarser choice
would only throw away resolution `FC` could otherwise fill in. A `weather.*`
entity that does not advertise `FORECAST_HOURLY` support at all is therefore not
surfaced as a candidate — no fallback to `"daily"`/ `"twice_daily"` is
attempted. Since it is always `"hourly"` for a `weather_sunshine`/
`weather_cloud` candidate and never anything else, this is not a separate
config-entry field either: `BaselineCandidate.forecast_type`/
`BaselineProvider.forecast_type` are both plain properties derived from `shape`
(`shape in {"weather_sunshine", "weather_cloud"}` ⇒ `"hourly"`, else `None`) —
nothing new is stored in `const.py`'s `CONF_*` keys or the config entry's `data`
beyond `shape` itself, which already determines it. **Known limitation:** the
subscription is registered once, at coordinator construction, against whichever
weather entity the `weather` domain's entity component already knows about at
that moment; if the specific weather integration owning that entity finishes its
own setup *after* Shady's coordinator is constructed, that subscription is
silently skipped (same "entity not there yet" family of risk ADR-002 §1a's
startup safety net addresses for other cases, not yet extended to this one).

### 1b — Amendment (2026-09-14): Forecast.Solar sourcing via config-entry polling

Forecast.Solar's own sensor entities (`sensor.energy_production_today` and
similar) no longer expose any forecast-shaped attribute at all on current HA
core — its `sensor.py` platform only ever sets a plain numeric `state`, no
`extra_state_attributes`. §1's original `sensor_dict` discovery, which used to
recognize this integration's `wh_period` attribute directly, therefore can no
longer find it there (or anywhere else on that integration's entities) — this is
a stricter version of the same problem §1a's weather amendment addresses, since
Forecast.Solar offers no push/subscription equivalent either, only the
request/response `forecast_solar.get_forecast` service, itself keyed by that
integration's own **config entry**, not an entity_id.

`providers/discovery.py`'s `_scan_forecast_solar_domain` therefore looks for
Forecast.Solar's config entries directly
(`hass.config_entries. async_loaded_entries("forecast_solar")`) rather than
scanning entity attributes at all, and samples each via
`forecast_solar.get_forecast`. Since that service has no entity_id to key off
of, a `forecast_solar`-shaped `BaselineCandidate`/`BaselineProvider` stores that
config entry's own `entry_id` in the `entity_id` field every other shape uses
for a real HA entity_id — a deliberate, narrow repurposing of that field, not a
new config-entry key (same "derive, don't store separately" preference as
`forecast_type`, §1a). This does make `forecast_solar` the one shape not offered
in the config flow's manual-entry fallback (`config_flow.py`'s
`_BASELINE_SHAPES`): a config entry's own internal `entry_id` is not something a
user could reasonably type in by hand, so this shape is only ever produced by
discovery's own scan. A matched candidate is scored `5.0` — deliberately higher
than any heuristic attribute-shape match's maximum (`2.0` base + up to `2.0`
keyword bonus) — reflecting that this is a confirmed, named-integration match
rather than a guessed attribute shape.

At runtime, `coordinator.py`'s `_register_forecast_solar_polls` (ADR-012 §4b is
the source of truth for that push path) polls each such config entry hourly via
the same service call (matching §1a's "always hourly" preference, and this
integration's own typical refresh cadence) and feeds the response into the
provider via `update_live_forecast()` — the exact same mechanism §1a's weather
subscription listener already uses, just poll-triggered instead of
push-triggered. `missing_required_entities()`'s existence check is
correspondingly shape-aware: a `forecast_solar` baseline's "entity_id" is
checked via `hass.config_entries.async_get_entry(...)` rather than
`hass.states.get(...)`, since it was never a real entity_id to begin with.

### 1c — Amendment (2026-09-15): recorder-backed baseline history via a linked history entity

§1a/§1b's push-only sourcing (`_PUSH_SOURCED_SHAPES`: `weather_sunshine`,
`weather_cloud`, `forecast_solar`) has a gap neither amendment addresses:
`BaselineProvider.fetch(start, end)` for a past-dated range has no genuine
retrospective capability for any of the three — there is no queryable archive of
what a `weather.get_forecasts`/`forecast_solar.get_forecast` response said at a
past moment, only `update_live_forecast()`'s most recent snapshot, which a
past-dated `fetch()` call simply cannot answer correctly. Concretely, this means
the baseline (`FC`) side of ADR-001's training pool has **no real history source
at all** for these three shapes — it can only ever accumulate from Shady's own
future-looking `forward()` pushes as they age into the past (ADR-012 §4), a few
days at a time, and that entire accumulated history is plain in-memory
(`cache.py`, ADR-007 §1) and is wiped on every Home Assistant restart.
Actual-yield (`PV`) has no equivalent gap, because
`_fetch_actual_yield_statistics` (`coordinator.py`, ADR-012 §2) already reads
real recorder history. On any instance that restarts periodically (normal for
Home Assistant), this keeps most slots' training confidence at or near zero
indefinitely, even after months of wall-clock deployment — `regression/base.py`
`passthrough_where_no_confidence` falls back to the raw, un-corrected baseline
for any such slot, which is what every configured string was observed doing in
production (see `shady-baseline-history-fix.md`).

This amendment gives the **`forecast_solar`** shape — and only that shape, see
below — a genuine, recorder-backed history source: at discovery time,
`providers/discovery.py`'s `_scan_forecast_solar_domain` additionally resolves
that Forecast.Solar config entry's own companion `sensor.py`-platform "Estimated
power production - now" entity (a continuously-sampled, already-recorder-backed
reading of the *same underlying model* the `forecast_solar`-shaped candidate
itself estimates, just read live rather than forecast) and attaches its current
`entity_id` to the candidate as a new field, `history_entity_id: str | None`.
Resolution is via the entity registry's own
`(config_entry_id, domain, translation_key)` index — every entity belonging to
the config entry is listed via `async_entries_for_config_entry`, then narrowed
to the one `sensor`-domain entry whose `translation_key` equals
`"power_production_now"` — never by composing a guessed `unique_id`, and never
by string-matching or guessing an `entity_id` a user is free to rename. This
sensor's real-world `entity_id` carries no config-entry-scoping prefix or suffix
of any kind (confirmed against a live deployment — it is simply
`sensor.power_production_now`), which is exactly why a composed-`unique_id`
lookup was rejected in favor of `translation_key`: a stable, code-defined
identifier that survives an `entity_id` rename the same way `unique_id` would,
without requiring any assumption about `unique_id`'s own format. `None` (never
an error) if the registry is unavailable or no matching entry exists yet (a
startup-ordering race in the same family ADR-002 §1a already catches for other
entities, just not blocking here — see below). `BaselineCandidate` carries the
resolved value as a new field, `history_entity_id: str | None`, and it flows
into the confirmed config entry's data alongside `entity_id`/
`attribute`/`shape` (new `const.py` keys `CONF_BASELINE_HISTORY_ENTITY_ID`/
`CONF_STRING_BASELINE_HISTORY_ENTITY_ID`, config_flow.py's
`_normalize_ settings`/`_build_current_string`) — not re-derived at coordinator
construction, which deliberately does no `hass` access at all (ADR-002 §1a:
"this must work even before any referenced entity exists yet").

`BaselineProvider` carries the resolved value through to the running coordinator
not as a bespoke field of its own, but by overriding a new, generic, optional
`Provider` base-class method, `history_entity_id() -> str | None` (ADR-012 §1
Amendment) — the same opt-in shape `identify()`/`forward()` already have there.
This is a deliberate genericity choice, not an implementation detail: it means
`coordinator.py`'s dispatch (below) checks every provider the same way, with no
`isinstance(provider, BaselineProvider)` branch, so a future provider unrelated
to baseline sourcing that resolves its own linked history entity picks up the
same recorder-backfill path for free — see ADR-012 §2a's own rationale for why
this lives on the base class rather than on `BaselineProvider` specifically.

ADR-012 §2a (Amendment, same date) is the source of truth for what
`coordinator.py` actually does with a resolved `history_entity_id()`: query it
via `statistics_during_period`, the same recorder-backed pattern §2 already
established for actual-yield, dispatched from `_fetch_fn` — generically, for
whichever provider is registered, never inside a `Provider` subclass itself,
preserving §4 below's module boundary (a provider reads `hass.states`/
`hass.config_entries`/`hass.services`/the entity registry; recorder access stays
`coordinator.py`'s alone, per ADR-000 §3/ADR-012 §2).

**Why only `forecast_solar`, not every `_PUSH_SOURCED_SHAPES` member or every
`sensor_dict`/`sensor_list` candidate too:** a linked history entity is only
safe to feed into the same training pool as the candidate's own forecast values
if it demonstrably represents the *same physical quantity, continuously sampled*
— otherwise the "history" is actively misleading, not merely absent.
Forecast.Solar's own `power_production_now` sensor passes this bar cleanly (the
same underlying production model, sampled continuously, on the very same config
entry). Nothing else currently does, without a per-integration check this
amendment deliberately does not attempt to write:

- `weather_sunshine`/`weather_cloud` — no single-entity history proxy exists for
  either; both are already synthesized from a weather service's forecast
  response, not a plain recorded reading. Left out of scope, same as §1a's own
  Known Limitation already accepts for the subscription path itself.
- `sensor_dict`/`sensor_list` (e.g. Solcast-style) — the main entity's own live
  state is frequently a *different* quantity than the forecast attribute (a
  daily total vs. an instantaneous per-slot value is the common case) — wiring
  this up generically, without a per-integration check, would silently corrupt
  the training pool with mismatched-quantity "history" rather than leave it
  correctly empty. `history_entity_id` stays unset (`None`) for both shapes;
  `_build_candidate` (the shared scoring path both use) never sets it. A future
  integration-specific check remains open for a later amendment, not ruled out —
  just not attempted here (`shady-baseline-history-fix.md`'s own explicit scope
  boundary).

Because only `forecast_solar` is ever linked, and that shape's score is already
the fixed, above-heuristic `_FORECAST_SOLAR_SCORE` (§1b) rather than a
keyword-summed one, §3's general principle ("a candidate with real history
should outrank a forecast-only one of otherwise equal standing") is satisfied by
that existing fixed score, not by a new score-summing mechanism between a
candidate and its linked history entity — there is no second, independently
heuristic-scored candidate to sum against for the one shape this amendment
actually links, so no such mechanism was built.

**Not a required entity.** A `forecast_solar` baseline's
`missing_required_ entities()`/`_baseline_missing()` check (ADR-002 §1a) is
unchanged by this amendment and stays keyed to the config entry's own
`ConfigEntryState.LOADED` check, exactly as ADR-002 §1a already documents — a
not-yet-resolved `history_entity_id` (the companion sensor entity not registered
yet, a narrower race than the config entry itself loading) degrades to "no
recorder backfill available this cycle," the same graceful, non-blocking
degradation an ordinary recorder-retention shortfall already produces (see
Acceptance Criterion 4 in `shady-baseline-history-fix.md`), not a setup failure
to retry over.

**Further Amendment (2026-09-17, §1c): a discovery-time `None` no longer stays
`None` forever.** A real-world gap surfaced in the paragraph just above: "not a
setup failure to retry over" was true as far as it went, but nothing ever _did_
retry it, and the one place this resolution result gets produced —
`config_flow.py`, at setup/options-flow submission time — is also the one place
it gets **persisted**, into this config entry's own stored data
(`CONF_BASELINE_HISTORY_ENTITY_ID`/`CONF_STRING_BASELINE_HISTORY_ENTITY_ID`).
`coordinator.py`'s `__init__` never touches `hass` at all (ADR-002 §1a), so it
just reads that stored value back, verbatim, on every subsequent restart. If
Forecast.Solar's companion sensor genuinely wasn't registered yet at that one
past moment, the persisted `None` is what every future restart inherits —
regardless of the sensor now existing, fully registered, with a full recorder
history, by the time any later restart's discovery would have found it. A real
deployment hit exactly this: `discover_baseline_candidates` correctly matched
the shape at flow-submission time, but the one-time race left
`history_entity_id` frozen at `None`, and every startup since silently fell
through to the ordinary live-value `fetch()` path — "no historical data," even
though the entity plainly had some (`TASK-0034-patch-1`).

The fix is a one-shot, best-effort retry at `async_startup` — `coordinator.py`'s
`_resolve_stale_forecast_solar_history_entities`, called immediately before
`_backfill_elapsed_today_slots` so a same-session recovery already unblocks that
same run's own backfill, not just the next restart's. `async_startup` is the
first point after construction with both `hass` access and ADR-002 §1a's own
readiness gate (`missing_required_entities()`) already passed, mirroring
`_refresh_forecast_solar_providers`'s existing "awaited, non-racy retry" pattern
for the *forward* forecast — this amendment gives the *history* entity the same
treatment, not a new pattern. For every `forecast_solar`-shaped provider whose
`history_entity_id()` is still `None`, it re-runs the identical
`resolve_forecast_solar_history_entity` lookup (now a public function — see
below); a successful retry updates the live `BaselineProvider` in place
(`set_history_entity_id`) **and** self-heals the persisted config entry data via
one `hass.config_entries.async_update_entry` call covering every provider
resolved that pass, so future restarts no longer need to retry it at all. A
still-failed retry changes nothing and is silently left for the next restart
(ADR-000 §8) — never an error, and logged no louder than debug, since the
condition is expected to resolve itself given enough restarts and isn't
actionable by the user in the moment.

`resolve_forecast_solar_history_entity` (`providers/discovery.py`) is now public
rather than `_`-prefixed — it has a second, legitimate cross-module caller
(`coordinator.py`) as of this amendment, and duplicating its lookup logic there,
or routing through the much heavier `discover_baseline_candidates` just to
re-resolve one already-known config entry, would both violate the "no
second/bespoke path" principle `tasks/adr-summary.md`'s exclusions already apply
to recorder access. This does **not** change §4's module-boundary reasoning
below — `coordinator.py` was already the module with `hass`-access timing gated
by ADR-002 §1a; it is simply now the caller of an existing, unchanged read-only
entity-registry lookup, not a new one.

### 2 — Normalization onto one canonical series

`providers/normalize.py` maps both `sensor.*` shapes, both `weather.*` shapes,
and `forecast_solar` above onto one canonical `list[tuple[datetime, float]]`
series that any strategy in `regression/` and `forecast_adjust.py` consume
without caring which integration, domain, or (for the weather case) polarity the
source data came in. The `sensor.*`/`weather.*` shapes go via a small table of
known key-name aliases (timestamp keys: `datetime`, `start`, `period_start`,
`time`; value keys: `wh`, `pv_estimate`, `power`, `value`, `energy`,
`sunshine_duration`, `cloud_coverage`); `forecast_solar` (§1b Amendment) instead
reads its response's own fixed `wh_period` key directly — that service's
response shape is a stable, internally-defined contract, not a third-party
attribute needing alias-guessing.

### 3 — Candidates are scored, not auto-selected

An attribute name containing "forecast"/"pv"/"sunshine"/"cloud", parseable
ISO8601 timestamps, and plausible-unit numeric values all raise the score; the
config flow (ADR-010) presents the ranked candidates and always offers a manual
entity+attribute fallback, since third-party attribute shapes are not a
versioned contract (the same caution Effy's ADR-003 raises about recorder
internals applies here to other integrations' attributes). A candidate matched
on `cloud_coverage` is labeled distinctly from one matched on
`sunshine_duration` in the presented list (e.g. "cloud coverage (inverted)" vs.
"sunshine duration") so a person confirming the match can tell which
normalization was applied, rather than the two proxy kinds being presented
identically.

### 4 — Module boundary: `providers/` reads `hass.states` directly

`providers/` is explicitly the one module allowed to read `hass.states` directly
among the "pure-ish" layer (see the module diagram in ADR-000 §3) — it still
never writes state and never reaches into another integration's internal
coordinator or `hass.data`, only its public entity state/attributes.
`providers/discovery.py` is one of two concrete providers this rule applies to;
see ADR-012 §5 for the module boundary as it applies to `providers/` as a whole,
including the temperature provider this ADR does not otherwise discuss.
**Amendment (2026-09-15, §1c):** this now also covers a read-only entity
registry lookup (`homeassistant.helpers.entity_registry.async_get`/
`async_entries_for_config_entry`) — used solely to resolve a `forecast_solar`
candidate's `history_entity_id`, never to read or write any other integration's
registry entries beyond that one lookup. Same public, core-level-registry
justification ADR-012 §4a/§4b already accept for
`hass.data[weather.const.DATA_COMPONENT]`/
`hass.config_entries`/`hass.services`: a core HA registry, not "another
integration's internal coordinator." Recorder access itself is **not** added to
this module's boundary — that stays `coordinator.py`'s alone (ADR-012 §2a).
**Amendment (2026-09-19, `TASK-0036`):** `_sample_weather_forecast`/
`_sample_forecast_solar` (§1a/§1b above) now route their
`weather.get_forecasts`/`forecast_solar.get_forecast` calls through `cache.py`'s
`ServiceResponseCache` (ADR-007 §1a, ADR-000 §3's new `providers --> cache`
edge) — the same restart-persisted last-good-response fallback
`coordinator.py`'s own Forecast.Solar poll uses (ADR-012 §4b), so a transient
failure no longer drops an otherwise-valid candidate off discovery. This is the
one addition to this module's boundary beyond `hass.states`/
`hass.services`/`hass.config_entries`/the entity registry — a narrow,
`hass`-free import of one class, not a new HA surface.

### 5 — Global default, per-string override

The discovery-and-scoring process above runs once to establish a **global
default** baseline candidate, set up before any string is configured (ADR-010) —
the common case being one PV-forecast service for the whole installation. Any
individual string can still override this with its own baseline candidate (e.g.
a per-plane Solcast site for that specific string's orientation) if configured;
if it does not, it uses the global default. This mirrors the same
global-with-override shape already used for the temperature source (ADR-003b
§1a) — see ADR-012 §1, which is the source of truth for the shared `providers/`
base class both this discovery/normalize pair and the temperature provider
subclass.

______________________________________________________________________

## Consequences

- **Pro:** Works with whatever PV-forecast or weather integration the user
  already has, without per-integration adapter code to maintain.
- **Con:** Attribute-shape discovery is inherently heuristic and reads data
  across an unversioned surface (other integrations' attributes). Mitigated by
  always requiring user confirmation and offering a manual fallback, but a
  future HA core or integration update could still change an attribute's shape
  without notice, same caveat as Effy's ADR-003.
