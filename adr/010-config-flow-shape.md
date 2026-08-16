# ADR-010 – Config Flow Shape

**Date:** 2026-08-14
**Status:** Accepted
**Split from:** ADR-001 §6. Originally part of the shading-model ADR;
extracted because it is a cross-cutting specification that collects
fields introduced by several other ADRs, and was already being
referenced externally (ADR-003, ADR-005, ADR-006) as if it were its own
document. No behavior changed by this split — see ADR-001's Revision
note.

---

## Context

Shady's config flow collects settings introduced across several ADRs:
the regression model and its granularity/smoothing/window (ADR-001
§2/§3/§4), baseline sourcing (ADR-009), yield corrections (ADR-003), and
the intraday deviation correction (ADR-006). This ADR is the single,
authoritative specification of the resulting flow's shape and step
ordering — other ADRs that add a config-flow field point here rather
than each describing their own step placement.

---

## Decision

Given ADR-001 §3 (one model per configured string) and ADR-009
(baseline sourcing), the config flow establishes global settings
**first**, before any string exists — a person configures "how Shady
should behave" once, then adds however many strings share that
behavior, rather than being asked global questions only after already
committing to a first string:

```
Step "settings" (first):
  - Global default baseline candidate (dropdown, ranked by
    providers/discovery.py per ADR-009 — covering both `sensor.*`
    PV-forecast candidates and `weather.*` sunshine-duration/
    cloud-coverage proxy candidates alike; "None of these" → manual
    entity + attribute path entry) — used by any string that does not
    override it
  - "Does this baseline already account for temperature effects itself?"
    (boolean, default false — ADR-003 §2c; presented right alongside the
    baseline candidate above, since it is a property of *that* choice)
  - Training window in days (default 28)
  - Regression method: `wls2` (default) / `linear` / `kernel` / `wls3`
    (global — applies to every configured string, see ADR-001 §2;
    chosen manually, no auto-selection based on data volume)
  - Smoothing radius in slots (default 1, global; see ADR-001 §3b — `0`
    disables temporal smoothing)
  - Neighbor-fitting cut-off (default 25%, global; see ADR-001 §3c/§3d —
    the maximum median-ratio deviation a neighbor series may have before
    being excluded from a slot's training pool; the sentinel `-1%`
    switches to always-rescale instead of exclude, per ADR-001 §3d; not
    the same field as ADR-006's intraday-correction cut-off, despite the
    similar name)
  - Default temperature source (optional; entity selector covering
    sensor.* with device_class temperature and weather.* entities;
    leave empty to disable derating correction by default for all
    strings — ADR-003 §2a)
  - Intraday deviation-correction mode: off / ramping / blending
    (default off; see ADR-006 §1)
  - Intraday deviation-correction cut-off (default 10%, applies whenever
    the mode above is not "off"; see ADR-006 §2)
  - Intraday deviation-correction rolling window, in slots (default 24 =
    2h; see ADR-006 §3)
  - Intraday deviation-correction ramp/blend duration, in slots (default
    12 = 1h; see ADR-006 §3)

Step "add_string" (repeated):
  - Name (free text, e.g. "Dach Süd")
  - Baseline candidate override (optional; same dropdown as the global
    default above; leave empty to use the global default set in
    "settings"). A string that *does* override is, by definition,
    treated as temperature-aware (ADR-003 §2c) — no separate per-string
    flag is offered, on the assumption that the realistic reason to
    override per string at all is a per-plane setup on a dedicated
    PV-forecast service (e.g. Solcast configured with one site per
    string), which is exactly the kind of provider ADR-003 §2c's flag
    is about in the first place.
  - Actual-yield entity (standard HA entity selector, sensor domain,
    power or energy device_class)
  - "Configure advanced corrections (clipping/derating) for this string?"
    (boolean, default off) → yes: "add_string_advanced", no:
    "add_another"

Step "add_string_advanced" (optional, per string):
  - Converter/inverter AC power limit (optional number, W; leave empty
    to disable clipping exclusion for this string — ADR-003 §1)
  - Temperature source override (optional; leave empty to use the global
    default; "none" disables derating for this string specifically even
    if a global default is set — ADR-003 §2a)
  - Temperature coefficient in %/°C (only shown/used if a temperature
    source — global default or override — applies to this string;
    default −0.4 — ADR-003 §2)

Step "add_another":
  - "Add another string?" (boolean) → back to "add_string" or finish
```

Note there is no latitude/longitude/elevation field: the regression
needs no astronomical calculation (ADR-001 §1), so location is not
collected anywhere in Shady's config flow.

The options flow mirrors this to allow adding/editing strings and
changing any global setting after initial setup, following the same
pattern as Effy's `EffyOptionsFlow`.

---

## Consequences

- **Pro:** Establishes every global setting before a person configures
  their first string, so string-specific questions (baseline override,
  converter limit, temperature override) are answered with the relevant
  global defaults already visible, rather than the reverse.
- **Con:** As the single place every other ADR's config-flow fields
  converge, this document has to be kept in sync whenever a future ADR
  adds or changes a field — a cost concentrated here specifically so it
  does not have to be paid by re-deriving step ordering independently in
  each of those ADRs.
