# ADR-009 – Baseline (Unshaded) Forecast Sourcing: Generic Attribute Discovery

**Date:** 2026-08-14
**Status:** Accepted
**Split from:** ADR-001 §5. Originally part of the shading-model ADR;
extracted because baseline sourcing is a separable concern from the
regression model itself, and was already being referenced externally
(ADR-003, ADR-004) as if it were its own document. No behavior changed
by this split — see ADR-001's Revision note.

---

## Context

The empirical shading model (ADR-001) needs, for every configured
string, an **unshaded reference forecast** (`FC`) to compare each
slot's actual yield (`PV`) against — the whole model is a regression of
`PV` on `FC` (ADR-001 §1/§2). Rather than hardcoding adapters for
specific PV-forecast integrations (Forecast.Solar, Solcast, …) — which
would need updating every time a new provider becomes popular or an
existing one changes its entity shape — Shady discovers a usable
baseline generically, from whatever forecast-shaped data the user's
Home Assistant instance already exposes.

---

## Decision

### 1 — Generic attribute-shape discovery, not per-integration adapters

`providers/discovery.py` scans HA entities for **attribute shapes that
look like a forecast series**, and lets the user confirm the match — it
never applies a detected baseline silently.

Two entity domains are scanned, covering two different kinds of baseline
signal:

- **`sensor.*` entities** — for a dedicated PV-forecast integration's
  output. Attribute shapes recognized:
  - dict of `{timestamp: number}` (e.g. Forecast.Solar's `wh_period`)
  - list of dicts with a timestamp-like key and a numeric value-like key
    (e.g. Solcast's `detailedForecast`)
- **`weather.*` entities** — for users without a dedicated PV-forecast
  integration. Two attribute shapes are recognized here, both proxy
  baselines ("expected yield under a clear/predicted sky") rather than a
  direct watt/Wh series, and both normalized accordingly before entering
  the regression:
  - sunshine-duration-like values in a weather integration's forecast
    attribute (e.g. `sunshine_duration`, common in DWD/Open-Meteo-based
    weather integrations) — already a *positive* clear-sky proxy (more
    sunshine ⇒ more expected yield), so it is used directly, only rescaled
    to the baseline's expected numeric range.
  - cloud-coverage-like values (e.g. `cloud_coverage`,
    `cloud_coverage_total`, common in Met.no/OpenWeatherMap-based weather
    integrations) — the *inverse* of a clear-sky proxy (more cloud ⇒ less
    expected yield). `providers/normalize.py` inverts it (e.g.
    `100 - cloud_coverage` for a percentage-scaled source) before it is
    treated as a baseline value; everything downstream of normalization
    (ADR-001's `regression/`, and this ADR's own module) only ever sees
    the already-inverted, positive-going series and has no notion that
    the raw source was a coverage percentage rather than a sunshine
    duration.

### 2 — Normalization onto one canonical series

`providers/normalize.py` maps both `sensor.*` shapes and both
`weather.*` shapes above, via a small table of known key-name aliases
(timestamp keys: `datetime`, `start`, `period_start`, `time`; value
keys: `wh`, `pv_estimate`, `power`, `value`, `energy`,
`sunshine_duration`, `cloud_coverage`), onto one canonical
`list[tuple[datetime, float]]` series that any strategy in
`regression/` and `forecast_adjust.py` consume without caring which
integration, domain, or (for the weather case) polarity the source data
came in.

### 3 — Candidates are scored, not auto-selected

An attribute name containing "forecast"/"pv"/"sunshine"/"cloud",
parseable ISO8601 timestamps, and plausible-unit numeric values all
raise the score; the config flow (ADR-010) presents the ranked
candidates and always offers a manual entity+attribute fallback, since
third-party attribute shapes are not a versioned contract (the same
caution Effy's ADR-003 raises about recorder internals applies here to
other integrations' attributes). A candidate matched on `cloud_coverage`
is labeled distinctly from one matched on `sunshine_duration` in the
presented list (e.g. "cloud coverage (inverted)" vs. "sunshine
duration") so a person confirming the match can tell which normalization
was applied, rather than the two proxy kinds being presented
identically.

### 4 — Module boundary: `providers/` reads `hass.states` directly

`providers/` is explicitly the one module allowed to read `hass.states`
directly among the "pure-ish" layer (see the module diagram in ADR-000
§3) — it still never writes state and never reaches into another
integration's internal coordinator or `hass.data`, only its public
entity state/attributes.

### 5 — Global default, per-string override

The discovery-and-scoring process above runs once to establish a
**global default** baseline candidate, set up before any string is
configured (ADR-010) — the common case being one PV-forecast service
for the whole installation. Any individual string can still override
this with its own baseline candidate (e.g. a per-plane Solcast site for
that specific string's orientation) if configured; if it does not, it
uses the global default. This mirrors the same global-with-override
shape already used for the temperature source (ADR-003 §2a).

---

## Consequences

- **Pro:** Works with whatever PV-forecast or weather integration the
  user already has, without per-integration adapter code to maintain.
- **Con:** Attribute-shape discovery is inherently heuristic and reads
  data across an unversioned surface (other integrations' attributes).
  Mitigated by always requiring user confirmation and offering a manual
  fallback, but a future HA core or integration update could still
  change an attribute's shape without notice, same caveat as Effy's
  ADR-003.
