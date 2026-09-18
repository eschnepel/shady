# ADR-012 – Provider Architecture: Shared Base Class and Cache Reuse for External Series

**Date:** 2026-08-18 **Status:** Accepted **Last updated:** 2026-09-15 — §4a
(weather forecast subscription push, ADR-009 §1a Amendment) and §4b
(Forecast.Solar polling push, ADR-009 §1b Amendment) added 2026-09-14; §1
(Amendment: fourth optional `Provider` method, `history_entity_id()`) and §2a
(recorder-backed history backfill via it, ADR-009 §1c Amendment, `TASK-0034`)
added below, extending §2's actual-yield recorder-read precedent to any provider
that resolves a linked history entity — generically, not only
`BaselineProvider`.

This ADR is kept current in place: §1 already describes `providers/base.py` as
an actual base class (not a structural protocol) with the optional
`forward(now)` push method alongside `fetch`/`identify`, and — as of the
Amendment above — the optional `history_entity_id()` recorder-backed-pull-path
method alongside all three; §4 already describes `coordinator.py`'s one generic
loop over `forward()`-implementing providers, and §2a (Amendment) the analogous
one for `history_entity_id()`-implementing providers; §1a's two shared helpers
(state-value mapping, series-tuple assembly) are folded into §1a/§5 directly.

______________________________________________________________________

## Context

Two existing decisions each independently need to read a time series from
outside Shady's own storage, off of whatever entity the user's Home Assistant
instance happens to expose it on:

- **Baseline (unshaded) forecast sourcing** (ADR-009) — full attribute-shape
  discovery and scoring across `sensor.*`/`weather.*` entities, because
  third-party PV-forecast and weather integrations vary widely and are not a
  versioned contract.
- **Temperature sourcing** (ADR-003b §1a) — a three-tier hierarchy (dedicated
  module/ambient sensor, a weather entity's `temperature` attribute, or none)
  selected directly by the user in the config flow (ADR-010), with no discovery
  or scoring step needed.

`providers/` has been named as the module containing both since ADR-000 §3's
very first version (2026-07-04), including a `base.py` file — but no ADR has
ever said what `base.py` actually contains, or established that temperature
sourcing is architecturally *the same kind of thing* as baseline sourcing rather
than something bespoke living inside `yield_correction.py`. This ADR closes that
gap: it defines the shared provider interface, confirms temperature sourcing is
a second concrete provider built on it, and — per explicit instruction during
design review — establishes that neither provider needs any cache logic beyond
what `cache.py` (ADR-007) already has.

This ADR is the **source of truth** for the shared provider architecture, its
cache integration, and — as of §4 — the generic policy for capturing a
provider's live prediction via push, once, rather than only ever reading it
reactively. ADR-009 remains the source of truth for baseline
discovery/scoring/normalization specifics; ADR-003b remains the source of truth
for which temperature sources are supported and the cell-temperature formulas;
ADR-007a remains the source of truth for `cache.py`'s own storage/accessor
design (ADR-007 remains the source of truth for why `cache.py` exists as its own
module). This document only owns the connective tissue between them, so those
three stop each carrying a partial, independently-drifting description of "how
data gets from HA into the cache."

______________________________________________________________________

## Decision

### 1 — `providers/base.py`: one shared base class, two concrete providers

`providers/base.py` defines a base class every concrete provider subclasses —
not a structural `typing.Protocol`, but an actual base class with overridable
methods, since §4 below (and §2a, Amendment) need `coordinator.py` to call one
of them generically without knowing which concrete provider it's talking to.
Four methods, two calling conventions:

- **`fetch(start, end) -> list[float | None | str]`** — the on-demand, pull
  path. **Required**; the base class provides no default (a subclass that omits
  it fails to instantiate). Matches `cache.py`'s existing `fetch_fn` signature
  (ADR-007a §4) exactly, so a provider's `fetch` method can be wired in as a
  cache's `fetch_fn` directly, with no adapter layer in between. Invoked
  reactively, only when `cache.py`'s validation function finds a gap (ADR-007a
  §4) — never on a schedule of the provider's own.
- **`identify() -> EntityRef | None`** — **optional**; the base class default
  returns `None`. Only meaningful for a provider that performs
  discovery/scoring. A provider with nothing to discover (see §2) simply doesn't
  override it.
- **`forward(now: datetime) -> list[tuple[datetime, float]] | None`** —
  **optional**; the base class default returns `None`. This is the listener/push
  path (§4): "what does this provider currently believe about the future, right
  now" — the same shape ADR-009 §2 already established for baseline's canonical
  series, generalized to any provider. A provider overrides it only if its live
  series is genuinely forward-looking; one that has no forecast concept of its
  own (e.g. a plain module/cell or ambient temperature sensor, ADR-003b §1a)
  leaves the default `None` in place, and simply never participates in §4's push
  path — `coordinator.py` checks for this generically (§4), not per provider
  type.
- **`history_entity_id() -> str | None`** — **optional** (Amendment, 2026-09-15,
  `TASK-0034`); the base class default returns `None`. The pull-path counterpart
  to `forward()`'s push-path pattern above: "does this provider have a separate,
  ordinary HA entity whose own recorder history is a safe stand-in for a
  past-dated `fetch()` call this provider's own `fetch()` cannot genuinely
  answer" (ADR-009 §1c). A provider overrides it only if it has identified
  exactly such an entity; one that doesn't (every provider today except a
  `forecast_solar`-shaped `BaselineProvider` instance whose companion sensor was
  resolved) leaves the default `None` in place and simply never participates in
  §2a's recorder-backfill path — `coordinator.py` checks for this generically
  (§2a), not per provider type, the same way §4 already does for `forward()`.

Two concrete providers exist behind this one base class:

- **`providers/discovery.py` + `providers/normalize.py`** — the
  baseline/weather-impact provider (ADR-009). Overrides `identify()` with full
  attribute-shape scoring (ADR-009 §1/§3), `fetch()` via
  `providers/normalize.py`'s canonical-series mapping over a past range (ADR-009
  §2), and `forward()` via that same canonical-series mapping over the live
  attribute's current forward range — one mapping function, two callers, past
  range or live range, not two separate implementations. Overrides
  `history_entity_id()` (Amendment) only for a `forecast_solar`-shaped instance
  whose companion sensor was resolved at discovery time (ADR-009 §1c) — every
  other shape/instance leaves the base class's `None` default in place.
- **`providers/temperature.py`** — the temperature provider (ADR-003b §1a). Its
  `identify()` is trivial: whichever entity the config flow (ADR-010) selected
  directly, with no ranking step, exactly as ADR-003b §1a already specifies ("no
  attribute-shape scoring is needed here"). Its `fetch()` branches by source
  tier: a plain sensor's own recorded history for the dedicated module/ambient
  case, or a `weather.*` entity's `forecast` attribute for the prediction-time
  case (ADR-003b §1b). Its `forward()` is meaningful **only** when the instance
  is resolved against a `weather.*` entity — the module/cell and ambient tiers
  leave the base class's `None` default in place, exactly as ADR-003c's Context
  already establishes ("plain live sensors with no forecasting concept of their
  own"). ADR-003c §3's predictor field resolves to a second instance of this
  same class, one whose `forward()` is always meaningful because it is only ever
  pointed at a `weather.*` entity in the first place.

### 1a — Two shared helpers in `providers/base.py`, not reimplemented per provider

Both concrete providers' `fetch()`/`forward()` implementations independently
need two pieces of plumbing that have nothing to do with *which* provider is
asking, and were at risk of being written twice (once for baseline, once for
temperature) with no ADR saying they should be the same code. Both now live as
plain functions on `providers/base.py` itself, called by both concrete providers
rather than reimplemented in each:

- **State-value mapping** — translating whatever a `hass.states` read for a
  given entity/attribute actually returns (a numeric value; an HA "unknown"
  state; an HA "unavailable" state; an attribute that is simply absent) into
  exactly one of `cache.py`'s three storage states — `float`, `None`, or `str`
  (ADR-007a §1). This is the same translation both `providers/discovery.py` (via
  `providers/normalize.py`) and `providers/temperature.py` need to perform
  before a value is fit to hand to `cache.py`'s `fetch_fn`/`push` (this
  document's `fetch()`/`forward()` contracts, §1 above), and neither provider
  has any provider-specific reason to handle it differently — an "unavailable"
  reading means the same thing to `cache.py` regardless of which entity produced
  it.
- **Series-tuple assembly** — given a set of already-resolved timestamp/value
  pairs (dict entries or list-of-dicts, whichever the source shape turns out to
  be), zipping them into the canonical `list[tuple[datetime, float]]` shape
  ADR-009 §2 established for baseline's normalized series. This is deliberately
  scoped to the low-level assembly step only, **not** the
  alias-guessing/candidate-scoring logic around it — `providers/normalize.py`
  still owns the key-name alias table and scoring (ADR-009 §1/§2/§3) and simply
  calls into this helper once it has already resolved which keys to read;
  `providers/temperature.py` calls the same helper directly, since it never has
  ambiguous keys to resolve in the first place (ADR-003b §1a: "a plain entity
  selector... is sufficient, with no candidate-ranking step"). Sharing this one
  small primitive does not pull temperature into `normalize.py`'s scoring
  machinery, and does not require `normalize.py`'s alias table to grow a
  temperature-specific entry it would otherwise have no reason to carry.

Both helpers are pure functions of their inputs — no `hass` access, no
provider-specific branching inside either one — so they stay in the zero-mocking
pure tier alongside the rest of `providers/base.py` (ADR-000 §6).

### 2 — Not every external entity needs a provider

Actual-yield (`PV`) does **not** get a provider. It is a plain,
already-identified entity the user selects directly in the config flow (ADR-010)
— there is no shape to detect and no source-tier branching to apply, so
`coordinator.py` wires its `entity_id` straight into `cache.py`'s generic
`fetch_fn` (backed by `statistics_during_period`, ADR-007a §4) with no
provider-layer involvement at all. (An earlier, looser description of this data
flow — ADR-003 §3, before its 2026-08-18 split — grouped actual-yield under the
same "providers/" bullet as baseline; that was imprecise and is corrected here.)
The dividing line this ADR draws: a provider exists only where there is
discovery/scoring to do (baseline) or more than one source tier with different
fetch logic to pick between (temperature). Anything simpler is just an
`entity_id` config value.

### 2a — Amendment (2026-09-15): recorder-backed baseline history backfill via a linked entity

§2 draws a clean line for actual-yield: no discovery/scoring to do, so
`coordinator.py` wires its `entity_id` straight into `cache.py`'s `fetch_fn`,
backed by `statistics_during_period`, with no provider-layer involvement.
Baseline sourcing needs the opposite — full discovery/scoring — which is exactly
why it has a `Provider` at all; but that does not mean a baseline provider's
`fetch()` is always the right thing to call for a past-dated range. ADR-009 §1c
(Amendment, same date) establishes that a `forecast_solar`-shaped
`BaselineCandidate`/`BaselineProvider` may carry a linked, recorder-backed
history entity — this section is the source of truth for what `coordinator.py`
does with one once resolved.

Rather than a `BaselineProvider`-specific field, this is a fourth, generic,
optional method on `Provider` itself (§1 Amendment, same date):
`history_entity_id() -> str | None`, base-class default `None`, the same opt-in
shape `identify()`/`forward()` already established there. `_fetch_fn` (ADR-007a
§4) checks it **generically**, for whichever provider (if any) is registered for
the `sensor_id` being fetched — no `isinstance` check against `BaselineProvider`
or any other concrete subclass:

```python
provider = self._entity_providers.get(sensor_id)
if provider is not None:
    history_entity_id = provider.history_entity_id()
    if history_entity_id is not None:
        return self._fetch_provider_history_statistics(history_entity_id, start, end)
    return provider.fetch(start, end)
```

— called **instead of** `provider.fetch()` for that call, not layered as a
fallback under it: for the one shape this currently ever returns non-`None` for
(`forecast_solar`, a `_PUSH_SOURCED_SHAPES` member, §4b), `fetch()`'s own
`_read_raw_attribute()` has no genuine retrospective capability for a past-dated
range anyway (ADR-009 §1c), so there is nothing worth falling back to.
`forward()` — the live/push path §4b already established — is entirely
unaffected: `history_entity_id()` only ever changes which past-dated `fetch()`
call `_fetch_fn` routes to, never the live series `forward()` reads and pushes.

`coordinator.py` gains a second recorder-backed fetch method,
`_fetch_provider_history_statistics`, deliberately **mirroring** — not sharing,
extending, or otherwise modifying — the existing
`_fetch_actual_ yield_statistics` (§2, ADR-007a §4): the same
`statistics_during_period` call, the same `_STATISTICS_PERIOD`/`{"mean"}`
arguments, the same `by_start.get(start + i * SLOT_DURATION)` slot-mapping. The
one difference is which `entity_id` it queries: the linked history entity, never
`sensor_id` itself (a `forecast_solar` baseline's own `sensor_id` is a config
entry id with no recorder history of its own — ADR-009 §1b). Named generically
(not `_fetch_baseline_statistics`) because the dispatch above is generic too — a
future provider unrelated to baseline sourcing that overrides
`history_entity_id()` reuses this same method, not a copy of it.

**Why this generic hook lives on `Provider` and its dispatch lives in
`coordinator.py`, never inside a concrete provider's own `fetch()`:** two
separate boundary questions, both settled the same way §4's `forward()` already
settled them for the push path. First, genericity: putting a `history_entity_id`
field only on `BaselineProvider` would mean every future provider wanting this
(another PV-forecast shape, a weather-history proxy) re-implements its own
version of the `_fetch_fn` dispatch check above, one `isinstance` branch at a
time — exactly the coordinator-code-per-provider coupling §4's own Consequences
already rejected for the push path ("no new coordinator code" is the explicit
design goal there; the same goal applies here). Second, module boundary:
recorder access is a categorically heavier, blocking-I/O concern this project
has consistently kept inside `coordinator.py` alone (its own module docstring:
"the only module that imports `cache.py`"; §2 above: actual yield's recorder
read has "no provider-layer involvement at all"). A `Provider` subclass reads
`hass.states`/`hass.config_entries`/ `hass.services`/the entity registry
(ADR-009 §4-Amendment) — all in-memory, non-blocking surfaces — and stops there;
`statistics_during_period` needs the recorder's own dedicated executor
(`coordinator.py`'s module docstring, "Recorder access runs off the event
loop"), which is `coordinator.py`'s concern to dispatch, not a `Provider`'s to
reach for on its own. `history_entity_id()` only ever hands back an entity_id
string — routing what happens with it entirely through `_fetch_fn` keeps that
boundary intact for every provider, present and future, not just this one.

**Not a required entity, not part of `missing_required_entities()`.** See
ADR-009 §1c's own closing paragraph — a `history_entity_id()` that is not yet
resolvable degrades to "no recorder backfill this cycle," not a setup-blocking
condition; `_baseline_missing`/`missing_required_entities()` (ADR-002 §1a) are
unchanged by this amendment.

### 3 — Cache reuse: no new cache concept

Temperature series reuse `cache.py`'s existing time-series storage and
`get_time_range` accessor (ADR-007a §1/§2/§5) exactly as baseline and
actual-yield already do — additional `sensor_id` entries in the same
`values`/`validated` dicts, nothing about `cache.py`'s internal design changes.
ADR-003c's learned per-slot temperature forecast reuses this same accessor for
both its predictor and target series, and reuses ADR-008's batched pool accessor
for the fit itself — the pattern below extends the same way it already did
before that ADR existed.

**Superseded by ADR-003c (2026-08-18):** the paragraph that originally followed
here described implementing ADR-003b §1b's now-superseded naive-persistence
fallback ("hold the most recently known reading constant for every future slot")
as ordinary post-processing over this same accessor, with no new cache
mechanism. That fallback no longer exists — ADR-003c §5 replaced it with either
a genuine learned forecast or no correction at all, for the reasons given there.
The point this paragraph existed to make — that whatever temperature-adjacent
behavior is needed, `cache.py` itself does not need to change to support it — is
still correct, and is reaffirmed by ADR-003c's own reuse of this same accessor
for its predictor and target series above, and its reuse of ADR-008's pool
accessor for the fit.

### 4 — Push: capturing a live prediction once, generically

Every provider's `fetch(start, end)` (§1) is a **pull** interface — read
reactively, when `cache.py`'s validation function (ADR-007a §4) finds a gap. For
a provider whose live series is genuinely forward-looking (a forecast, not a
plain current reading), pull-only coverage has a real gap of its own: the
entity's `forecast`-shaped attribute is a snapshot of current beliefs about the
future, not a queryable historical archive of what was believed at each past
moment, so a past-dated `fetch()` call has no correct answer to give once a slot
has elapsed and the attribute has moved on. ADR-002 §4 works through this for
the baseline provider in full; this section states the same policy generically,
so temperature (and any future forecast-shaped provider) does not need to
re-derive it — and, since §1's `forward()` method, mechanically does not need to
re-implement it either:

**`coordinator.py` runs one generic loop, not one bespoke listener per
provider.** For every provider instance a config entry has actually resolved
(§1's two today, more later), it checks whether `forward()` returns non-`None`
for that instance — if so, it registers a listener on that provider's
`identify()`-resolved entity; if `forward()`'s default `None` was left in place
(a provider with no forecast concept, e.g. a plain temperature sensor), no
listener is registered, because there would be nothing to push. Every registered
listener's firing does the same three things, regardless of which provider
fired: call that provider's `forward(now)` to get its currently-known series,
convert it to `cache.py`'s absolute-index scheme (ADR-007a §1), and
`push(sensor_id, dict[index, value])` (ADR-007a §3) with the same
`not_before_index` guard every time — one implementation in `coordinator.py`,
not one per provider. A slot's pushed value is frozen the instant it elapses —
never rewritten by a later push, and never re-derived from a query once written
— for the same reason ADR-002 §4 gives for `FC`: the pushed value already *is*
the training-time record of what was predicted, and recorder query remains only
the backfill/gap path for whatever push never reached (ADR-007a §4).

**This is independent of whether the same event also triggers a full forecast
recompute.** Whether a given provider's update fires ADR-002 §1/§2's
recalibration or recompute triggers is that document's decision alone, scoped to
what actually feeds the corrected-forecast output today; this section only
establishes that the provider's own raw series gets captured either way,
regardless of what else that update does or does not trigger.

**Two provider-backed predictors exist today** — baseline `FC` (ADR-002 §4) and
temperature (ADR-003c §7) — each documenting its own concrete `sensor_id` and
any provider-specific detail worth calling out, but neither hand-rolling its own
listener or push call anymore: both are just a `forward()` override picked up by
the one generic loop above. `providers/normalize.py`'s cloud-coverage- and
sunshine-duration-derived proxy series (ADR-009 §2) are **not** a third case
requiring separate handling: they are already folded onto `FC`'s one canonical
series before this point (ADR-009 §2), so they inherit `FC`'s `forward()`
override, and its push route, automatically — with no distinct `sensor_id` or
trigger of their own. A future third provider (e.g. a humidity or irradiance
predictor, should one ever be added) picks this up for free the moment it
overrides `forward()` — no new coordinator code, and no new ADR needed to wire
it in.

### 4a — Amendment (2026-09-14): weather forecast subscription push

The generic loop in §4 above still applies to every provider whose live series
comes from re-reading a `state.attributes` value on a state-changed event. A
`weather_sunshine`/`weather_cloud` `BaselineProvider` resolution (ADR-009 §1a
Amendment) no longer has an attribute to re-read at all — HA 2024.4 removed it —
so it needs a second, structurally different registration: `coordinator.py`'s
`_register_weather_forecast_subscriptions` looks up the `weather` domain's own
entity component (`hass.data[weather.const. DATA_COMPONENT]`, the same public
data key HA's own frontend websocket API uses for this) and calls
`entity.async_subscribe_forecast(forecast_type, listener)` for each such
provider. The listener records the pushed forecast on the provider
(`update_live_forecast()`) and then reuses the exact same "push to cache, maybe
recompute" tail as the §4 state-change path (`_handle_provider_update`) — only
*how* a fresh series arrives differs between the two registrations, not what
happens once it has. A provider with no `forecast_type` (every other provider
today) is entirely unaffected and keeps using the plain §4 path only.

### 4b — Amendment (2026-09-14): Forecast.Solar polling push

A `forecast_solar`-shaped `BaselineProvider` resolution (ADR-009 §1b Amendment)
has neither a state attribute to re-read (§4) nor a push subscription to
register (§4a) — Forecast.Solar exposes its forecast only via the
request/response `forecast_solar.get_forecast` service, with no subscription
equivalent. `coordinator.py`'s `_register_forecast_solar_polls` therefore
registers a third kind of update source: a plain `async_track_time_interval`
poll, once per hour per such provider (identified via the
`BaselineProvider.shape` property added for this purpose), each firing an
awaited `hass.services.async_call("forecast_solar", "get_forecast", ...)`. The
result is fed into the same `update_live_forecast()` /
`_handle_provider_ update` tail §4a's subscription listener already uses — the
third variation on this ADR's running theme (§4's own closing note: "no new
coordinator code... the moment it overrides `forward()`") is genuinely a new
registration mechanism, since Forecast.Solar's sourcing has no entity or
subscription to hang a listener off of at all, only a config entry ID to poll
against (`entity_id` for this one shape holds that config entry's own
`entry_id`, per ADR-009 §1b). `missing_required_entities()` is the one other
coordinator method that had to become shape-aware as a result, for the same
reason.

### 5 — Module boundary is unchanged

`providers/temperature.py` reads `hass.states` directly to resolve its
config-flow-selected entity, under the same rule ADR-009 §4 already establishes
for `providers/discovery.py`: reads only, no writes, no reaching into another
integration's coordinator or `hass.data`. `providers/base.py` itself needs none
of that — it holds the shared base class definition plus §1a's two small,
HA-agnostic helpers, and stays in the zero-mocking pure tier (ADR-000 §6)
alongside `providers/normalize.py`. §4a's
`hass.data[weather.const. DATA_COMPONENT]` lookup, and §4b's
`hass.config_entries`/`hass.services` calls, are not exceptions to this rule
either: all three are public, core-level HA surfaces — the `weather` domain's
own entity-component registry, the config entry manager, and the service-call
dispatcher respectively — not any specific integration's private internals.
§2a's (Amendment) entity registry lookup (`providers/discovery.py`, ADR-009 §1c)
is the same kind of core-level, read-only surface, for the same reason — and,
unlike §4a/§4b, has no recorder-access counterpart of its own:
`_fetch_provider_history_statistics` (§2a) stays in `coordinator.py`, the one
place recorder access has ever lived in this design (§2).

______________________________________________________________________

## Consequences

- **Pro:** `providers/base.py` — named in ADR-000 §3's module list since the
  project's first day but never specified — now has an actual, documented
  purpose.
- **Pro:** Temperature sourcing reuses `cache.py`'s existing storage,
  validation, and accessor machinery entirely; no second cache mechanism, no
  second fetch path, no new persisted state.
- **Pro:** The global-default-plus-per-string-override cardinality already
  established for baseline (ADR-009 §5) applies to temperature providers
  unchanged — one global default provider instance, plus zero or more per-string
  override instances — rather than inventing a second shape for the same
  pattern.
- **Con:** `providers/` now holds two concrete providers of meaningfully
  different complexity (full discovery/scoring vs. a plain selector) behind one
  shared interface. A reader of `providers/` needs to check which concrete
  provider they're looking at rather than assuming uniform behavior across the
  package.
- **Pro:** §1a's two shared helpers remove what would otherwise be two
  independent reimplementations of the same HA-state-to-cache-value translation
  and the same timestamp/value tuple assembly — a bug fixed or a new HA state
  variant handled in either helper benefits both providers at once, the same
  payoff ADR-007a §1's Consequences already claims for `cache.py`'s own shared
  time-series design.
- **Con:** Like ADR-009's baseline discovery, `providers/temperature.py` reads
  another integration's attribute shape (a weather entity's `forecast`
  attribute) across an unversioned surface. Same caveat ADR-009's own
  Consequences already accept, now shared by a second provider — mitigated the
  same way, by never silently trusting the shape (§1a's tier selection is
  explicit, not inferred).
- **Pro:** §4's generic push policy, now backed by an actual `forward()`
  override rather than only being described in prose, means a third
  forecast-shaped provider, if one is ever added, inherits "capture the
  prediction once, at the moment it's known" for free — literally: it gets
  picked up by `coordinator.py`'s one generic loop the moment it overrides
  `forward()`, with no new coordinator code and no new ADR needed to wire it in,
  not just a documented convention to follow by hand the way ADR-002 §4
  originally had to establish for `FC`.
- **Pro:** One `coordinator.py` implementation of "listen, call `forward()`,
  push" serves every provider, present and future, instead of one hand-rolled
  listener per provider — the version of §4 this ADR originally shipped with
  described the *policy* generically but still left each instantiation (ADR-002
  §4, ADR-003c §7) writing its own listener and push call; §1's `forward()`
  method closes that gap between "generic in prose" and "generic in code."
- **Con:** `forward()`'s optionality is a runtime signal (returns `None` if not
  overridden), not an enforced one — a provider author who forgets to override
  it for a genuinely forecast-shaped source fails silently (no listener
  registered, no error raised) rather than being caught at review time the way a
  missing required `fetch()` override would be (§1). Mitigated by there being
  exactly two providers to get right today, not a large surface where this could
  hide.
- **Con:** §4 adds a second class of listener to `coordinator.py` —
  provider-update listeners that only push and do not necessarily participate in
  ADR-002's recompute triggers — alongside the recompute-triggering baseline
  listener that already existed. Two listener *kinds* to keep straight
  (recompute-triggering vs. push-only) is more than the single kind that existed
  before this policy, though both use the identical `push` call underneath
  (ADR-007a §3).
- **Pro (Amendment, 2026-09-15):** §2a's generic `history_entity_id()` hook
  gives the recorder-backfill fix this amendment ships (ADR-009 §1c) the exact
  same "free for future providers" property §4's `forward()` already has for the
  push path — the design choice this amendment was made specifically to get,
  over the narrower alternative of a `BaselineProvider`-only field plus an
  `isinstance` check in `_fetch_fn`. A weather-history proxy or another
  PV-forecast shape added later needs only to override `history_entity_id()`; no
  `coordinator.py` change, no new `isinstance` branch, no new ADR needed to wire
  it in.
- **Con (Amendment, 2026-09-15):** `history_entity_id()`'s optionality is the
  same runtime-signal tradeoff §4's Consequences already accept for `forward()`
  — a provider author who resolves a genuinely valid history entity but forgets
  to override this method fails silently (no recorder backfill, still
  correct-if-slow behavior via `fetch()`) rather than being caught at review
  time. Mitigated the same way: exactly one provider (`BaselineProvider`, and
  only its `forecast_solar` shape) overrides it today, not a large surface where
  this could hide.
