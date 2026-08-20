# ADR-012 – Provider Architecture: Shared Base Class and Cache Reuse for External Series

**Date:** 2026-08-18
**Status:** Accepted
**Amended:** 2026-08-19 — new §4 generalizes ADR-002 §4's raw-`FC` push
into a policy for any provider-backed predictor; former §4 ("Module
boundary is unchanged") renumbered to §5. See ADR-003c §7 for
temperature's own instantiation. Later the same day: §1 revised —
`providers/base.py` is now an actual base class (not a structural
protocol), with a new optional `forward(now)` method alongside `fetch`/
`identify`; §4 revised to describe one generic `coordinator.py` loop
over `forward()`-implementing providers, rather than one hand-rolled
listener per provider. No change to what gets pushed, when, or the
`not_before_index` guard — only to how the mechanism is shared across
providers.

---

## Context

Two existing decisions each independently need to read a time series from
outside Shady's own storage, off of whatever entity the user's Home
Assistant instance happens to expose it on:

- **Baseline (unshaded) forecast sourcing** (ADR-009) — full
  attribute-shape discovery and scoring across `sensor.*`/`weather.*`
  entities, because third-party PV-forecast and weather integrations
  vary widely and are not a versioned contract.
- **Temperature sourcing** (ADR-003b §1a) — a three-tier hierarchy
  (dedicated module/ambient sensor, a weather entity's `temperature`
  attribute, or none) selected directly by the user in the config flow
  (ADR-010), with no discovery or scoring step needed.

`providers/` has been named as the module containing both since ADR-000
§3's very first version (2026-07-04), including a `base.py` file — but no
ADR has ever said what `base.py` actually contains, or established that
temperature sourcing is architecturally *the same kind of thing* as
baseline sourcing rather than something bespoke living inside
`yield_correction.py`. This ADR closes that gap: it defines the shared
provider interface, confirms temperature sourcing is a second concrete
provider built on it, and — per explicit instruction during design
review — establishes that neither provider needs any cache logic beyond
what `cache.py` (ADR-007) already has.

This ADR is the **source of truth** for the shared provider architecture,
its cache integration, and — as of §4 — the generic policy for capturing
a provider's live prediction via push, once, rather than only ever
reading it reactively. ADR-009 remains the source of truth for
baseline discovery/scoring/normalization specifics; ADR-003b remains the
source of truth for which temperature sources are supported and the
cell-temperature formulas; ADR-007a remains the source of truth for
`cache.py`'s own storage/accessor design (ADR-007 remains the source of
truth for why `cache.py` exists as its own module). This document only owns the
connective tissue between them, so those three stop each carrying a
partial, independently-drifting description of "how data gets from HA
into the cache."

---

## Decision

### 1 — `providers/base.py`: one shared base class, two concrete providers

`providers/base.py` defines a base class every concrete provider
subclasses — not a structural `typing.Protocol`, but an actual base
class with overridable methods, since §4 below needs `coordinator.py` to
call one of them generically without knowing which concrete provider
it's talking to. Three methods, two calling conventions:

- **`fetch(start, end) -> list[float | None | str]`** — the on-demand,
  pull path. **Required**; the base class provides no default (a
  subclass that omits it fails to instantiate). Matches `cache.py`'s
  existing `fetch_fn` signature (ADR-007a §4) exactly, so a provider's
  `fetch` method can be wired in as a cache's `fetch_fn` directly, with
  no adapter layer in between. Invoked reactively, only when
  `cache.py`'s validation function finds a gap (ADR-007a §4) — never on
  a schedule of the provider's own.
- **`identify() -> EntityRef | None`** — **optional**; the base class
  default returns `None`. Only meaningful for a provider that performs
  discovery/scoring. A provider with nothing to discover (see §2) simply
  doesn't override it.
- **`forward(now: datetime) -> list[tuple[datetime, float]] | None`** —
  **optional**; the base class default returns `None`. This is the
  listener/push path (§4): "what does this provider currently believe
  about the future, right now" — the same shape ADR-009 §2 already
  established for baseline's canonical series, generalized to any
  provider. A provider overrides it only if its live series is
  genuinely forward-looking; one that has no forecast concept of its own
  (e.g. a plain module/cell or ambient temperature sensor, ADR-003b §1a)
  leaves the default `None` in place, and simply never participates in
  §4's push path — `coordinator.py` checks for this generically (§4),
  not per provider type.

Two concrete providers exist behind this one base class:

- **`providers/discovery.py` + `providers/normalize.py`** — the
  baseline/weather-impact provider (ADR-009). Overrides `identify()`
  with full attribute-shape scoring (ADR-009 §1/§3), `fetch()` via
  `providers/normalize.py`'s canonical-series mapping over a past range
  (ADR-009 §2), and `forward()` via that same canonical-series mapping
  over the live attribute's current forward range — one mapping
  function, two callers, past range or live range, not two separate
  implementations.
- **`providers/temperature.py`** — the temperature provider (ADR-003b
  §1a). Its `identify()` is trivial: whichever entity the config flow
  (ADR-010) selected directly, with no ranking step, exactly as ADR-003b
  §1a already specifies ("no attribute-shape scoring is needed here").
  Its `fetch()` branches by source tier: a plain sensor's own recorded
  history for the dedicated module/ambient case, or a `weather.*`
  entity's `forecast` attribute for the prediction-time case (ADR-003b
  §1b). Its `forward()` is meaningful **only** when the instance is
  resolved against a `weather.*` entity — the module/cell and ambient
  tiers leave the base class's `None` default in place, exactly as
  ADR-003c's Context already establishes ("plain live sensors with no
  forecasting concept of their own"). ADR-003c §3's predictor field
  resolves to a second instance of this same class, one whose `forward()`
  is always meaningful because it is only ever pointed at a `weather.*`
  entity in the first place.

### 2 — Not every external entity needs a provider

Actual-yield (`PV`) does **not** get a provider. It is a plain,
already-identified entity the user selects directly in the config flow
(ADR-010) — there is no shape to detect and no source-tier branching to
apply, so `coordinator.py` wires its `entity_id` straight into
`cache.py`'s generic `fetch_fn` (backed by `statistics_during_period`,
ADR-007a §4) with no provider-layer involvement at all. (An earlier,
looser description of this data flow — ADR-003 §3, before its 2026-08-18
split — grouped actual-yield under the same "providers/" bullet as
baseline; that was imprecise and is corrected here.) The dividing line
this ADR draws: a provider exists only where there is discovery/scoring
to do (baseline) or more than one source tier with different fetch logic
to pick between (temperature). Anything simpler is just an `entity_id`
config value.

### 3 — Cache reuse: no new cache concept

Temperature series reuse `cache.py`'s existing time-series storage and
`get_time_range` accessor (ADR-007a §1/§2/§5) exactly as baseline and
actual-yield already do — additional `sensor_id` entries in the same
`values`/`validated` dicts, nothing about `cache.py`'s internal design
changes. ADR-003c's learned per-slot temperature forecast reuses this
same accessor for both its predictor and target series, and reuses
ADR-008's batched pool accessor for the fit itself — the pattern below
extends the same way it already did before that ADR existed.

**Superseded by ADR-003c (2026-08-18):** the paragraph that originally
followed here described implementing ADR-003b §1b's now-superseded
naive-persistence fallback ("hold the most recently known reading
constant for every future slot") as ordinary post-processing over this
same accessor, with no new cache mechanism. That fallback no longer
exists — ADR-003c §5 replaced it with either a genuine learned forecast
or no correction at all, for the reasons given there. The point this
paragraph existed to make — that whatever temperature-adjacent behavior
is needed, `cache.py` itself does not need to change to support it — is
still correct, and is reaffirmed by ADR-003c's own reuse of this same
accessor for its predictor and target series above, and its reuse of
ADR-008's pool accessor for the fit.

### 4 — Push: capturing a live prediction once, generically

Every provider's `fetch(start, end)` (§1) is a **pull** interface — read
reactively, when `cache.py`'s validation function (ADR-007a §4) finds a
gap. For a provider whose live series is genuinely forward-looking (a
forecast, not a plain current reading), pull-only coverage has a real
gap of its own: the entity's `forecast`-shaped attribute is a snapshot
of current beliefs about the future, not a queryable historical archive
of what was believed at each past moment, so a past-dated `fetch()` call
has no correct answer to give once a slot has elapsed and the attribute
has moved on. ADR-002 §4 works through this for the baseline provider in
full; this section states the same policy generically, so temperature
(and any future forecast-shaped provider) does not need to re-derive it —
and, since §1's `forward()` method, mechanically does not need to
re-implement it either:

**`coordinator.py` runs one generic loop, not one bespoke listener per
provider.** For every provider instance a config entry has actually
resolved (§1's two today, more later), it checks whether `forward()`
returns non-`None` for that instance — if so, it registers a listener on
that provider's `identify()`-resolved entity; if `forward()`'s default
`None` was left in place (a provider with no forecast concept, e.g. a
plain temperature sensor), no listener is registered, because there
would be nothing to push. Every registered listener's firing does the
same three things, regardless of which provider fired: call that
provider's `forward(now)` to get its currently-known series, convert it
to `cache.py`'s absolute-index scheme (ADR-007a §1), and `push(sensor_id,
dict[index, value])` (ADR-007a §3) with the same `not_before_index`
guard every time — one implementation in `coordinator.py`, not one per
provider. A slot's pushed value is frozen the instant it elapses — never
rewritten by a later push, and never re-derived from a query once
written — for the same reason ADR-002 §4 gives for `FC`: the pushed
value already *is* the training-time record of what was predicted, and
recorder query remains only the backfill/gap path for whatever push
never reached (ADR-007a §4).

**This is independent of whether the same event also triggers a full
forecast recompute.** Whether a given provider's update fires ADR-002
§1/§2's recalibration or recompute triggers is that document's decision
alone, scoped to what actually feeds the corrected-forecast output
today; this section only establishes that the provider's own raw series
gets captured either way, regardless of what else that update does or
does not trigger.

**Two provider-backed predictors exist today** — baseline `FC` (ADR-002
§4) and temperature (ADR-003c §7) — each documenting its own concrete
`sensor_id` and any provider-specific detail worth calling out, but
neither hand-rolling its own listener or push call anymore: both are
just a `forward()` override picked up by the one generic loop above.
`providers/normalize.py`'s cloud-coverage- and sunshine-duration-derived
proxy series (ADR-009 §2) are **not** a third case requiring separate
handling: they are already folded onto `FC`'s one canonical series
before this point (ADR-009 §2), so they inherit `FC`'s `forward()`
override, and its push route, automatically — with no distinct
`sensor_id` or trigger of their own. A future third provider (e.g. a
humidity or irradiance predictor, should one ever be added) picks this
up for free the moment it overrides `forward()` — no new coordinator
code, and no new ADR needed to wire it in.

### 5 — Module boundary is unchanged

`providers/temperature.py` reads `hass.states` directly to resolve its
config-flow-selected entity, under the same rule ADR-009 §4 already
establishes for `providers/discovery.py`: reads only, no writes, no
reaching into another integration's coordinator or `hass.data`.
`providers/base.py` itself needs none of that — it is just the shared
base class definition, and stays in the zero-mocking pure tier (ADR-000
§6) alongside `providers/normalize.py`.

---

## Consequences

- **Pro:** `providers/base.py` — named in ADR-000 §3's module list since
  the project's first day but never specified — now has an actual,
  documented purpose.
- **Pro:** Temperature sourcing reuses `cache.py`'s existing storage,
  validation, and accessor machinery entirely; no second cache
  mechanism, no second fetch path, no new persisted state.
- **Pro:** The global-default-plus-per-string-override cardinality
  already established for baseline (ADR-009 §5) applies to temperature
  providers unchanged — one global default provider instance, plus zero
  or more per-string override instances — rather than inventing a
  second shape for the same pattern.
- **Con:** `providers/` now holds two concrete providers of meaningfully
  different complexity (full discovery/scoring vs. a plain selector)
  behind one shared interface. A reader of `providers/` needs to check
  which concrete provider they're looking at rather than assuming
  uniform behavior across the package.
- **Con:** Like ADR-009's baseline discovery, `providers/temperature.py`
  reads another integration's attribute shape (a weather entity's
  `forecast` attribute) across an unversioned surface. Same caveat
  ADR-009's own Consequences already accept, now shared by a second
  provider — mitigated the same way, by never silently trusting the
  shape (§1a's tier selection is explicit, not inferred).
- **Pro:** §4's generic push policy, now backed by an actual `forward()`
  override rather than only being described in prose, means a third
  forecast-shaped provider, if one is ever added, inherits "capture the
  prediction once, at the moment it's known" for free — literally: it
  gets picked up by `coordinator.py`'s one generic loop the moment it
  overrides `forward()`, with no new coordinator code and no new ADR
  needed to wire it in, not just a documented convention to follow by
  hand the way ADR-002 §4 originally had to establish for `FC`.
- **Pro:** One `coordinator.py` implementation of "listen, call
  `forward()`, push" serves every provider, present and future, instead
  of one hand-rolled listener per provider — the version of §4 this ADR
  originally shipped with described the *policy* generically but still
  left each instantiation (ADR-002 §4, ADR-003c §7) writing its own
  listener and push call; §1's `forward()` method closes that gap
  between "generic in prose" and "generic in code."
- **Con:** `forward()`'s optionality is a runtime signal (returns `None`
  if not overridden), not an enforced one — a provider author who forgets
  to override it for a genuinely forecast-shaped source fails silently
  (no listener registered, no error raised) rather than being caught at
  review time the way a missing required `fetch()` override would be
  (§1). Mitigated by there being exactly two providers to get right
  today, not a large surface where this could hide.
- **Con:** §4 adds a second class of listener to `coordinator.py` —
  provider-update listeners that only push and do not necessarily
  participate in ADR-002's recompute triggers — alongside the
  recompute-triggering baseline listener that already existed. Two
  listener *kinds* to keep straight (recompute-triggering vs.
  push-only) is more than the single kind that existed before this
  policy, though both use the identical `push` call underneath (ADR-007a
  §3).
