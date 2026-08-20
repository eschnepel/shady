# ADR-012 – Provider Architecture: Shared Base Class and Cache Reuse for External Series

**Date:** 2026-08-18
**Status:** Accepted

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

This ADR is the **source of truth** for the shared provider architecture
and its cache integration. ADR-009 remains the source of truth for
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

### 1 — `providers/base.py`: one shared protocol, two concrete providers

`providers/base.py` defines a minimal protocol every concrete provider
implements:

- `fetch(start, end) -> list[float | None | str]` — matches
  `cache.py`'s existing `fetch_fn` signature (ADR-007a §4) exactly, so a
  provider's `fetch` method can be wired in as a cache's `fetch_fn`
  directly, with no adapter layer in between.
- `identify() -> EntityRef | None` — optional; only meaningful for a
  provider that performs discovery/scoring. A provider with nothing to
  discover (see §2) simply doesn't implement it.

Two concrete providers exist behind this one protocol:

- **`providers/discovery.py` + `providers/normalize.py`** — the
  baseline/weather-impact provider (ADR-009). Implements `identify()`
  with full attribute-shape scoring (ADR-009 §1/§3) and `fetch()` via
  `providers/normalize.py`'s canonical-series mapping (ADR-009 §2).
- **`providers/temperature.py`** — the temperature provider (ADR-003b
  §1a). Its `identify()` is trivial: whichever entity the config flow
  (ADR-010) selected directly, with no ranking step, exactly as ADR-003b
  §1a already specifies ("no attribute-shape scoring is needed here").
  Its `fetch()` branches by source tier: a plain sensor's own recorded
  history for the dedicated module/ambient case, or a `weather.*`
  entity's `forecast` attribute for the prediction-time case (ADR-003b
  §1b).

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

### 4 — Module boundary is unchanged

`providers/temperature.py` reads `hass.states` directly to resolve its
config-flow-selected entity, under the same rule ADR-009 §4 already
establishes for `providers/discovery.py`: reads only, no writes, no
reaching into another integration's coordinator or `hass.data`.
`providers/base.py` itself needs none of that — it is just the shared
protocol definition, and stays in the zero-mocking pure tier (ADR-000
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
