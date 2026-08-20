# ADR-010 – Config Flow Shape

**Date:** 2026-08-14
**Status:** Accepted
**Split from:** ADR-001 §6. Originally part of the shading-model ADR;
extracted because it is a cross-cutting specification that collects
fields introduced by several other ADRs, and was already being
referenced externally (ADR-003a/ADR-003b, ADR-005, ADR-006) as if it
were its own document. No behavior changed by this split — see ADR-001's
Revision note.
**Amended:** 2026-08-18 — added the weather forecast entity and
temperature regression method fields introduced by ADR-003c.
**2026-08-20** — added two fields ADR-003b §1a's ambient→cell uplift
formula depends on but which this document had never actually listed:
a global "ambient-to-cell max uplift" field in "settings", and a
per-string "rated DC capacity" field in "add_string_advanced". Closes a
gap where ADR-003b called the first of these "configurable" with no
matching field here, and the second had no config-flow source at all.

---

## Context

Shady's config flow collects settings introduced across several ADRs:
the regression model and its granularity/smoothing/window (ADR-001
§2/§3/§4), baseline sourcing (ADR-009), yield corrections (ADR-003a,
ADR-003b, ADR-003c), and the intraday deviation correction (ADR-006).
This ADR is the single, authoritative specification of the resulting
flow's shape and step ordering — other ADRs that add a config-flow
field point here rather than each describing their own step placement.

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
    (boolean, default false — ADR-003b §1c; presented right alongside the
    baseline candidate above, since it is a property of *that* choice)
  - Training window in days (default 28)
  - Regression method: `wls2` (default) / `linear` / `kernel` / `wls3`
    (global — applies to every configured string, see ADR-001 §2;
    chosen manually, no auto-selection based on data volume)
  - Smoothing radius in slots (default 1, global; see ADR-011 §1 — `0`
    disables temporal smoothing)
  - Neighbor-fitting cut-off, `neighbor_fitting_cutoff` (default 25%,
    global; see ADR-011 §2/§3 — the maximum median-ratio deviation a
    neighbor series may have before being excluded from a slot's training
    pool; the sentinel `-1%` switches to always-rescale instead of
    exclude, per ADR-011 §3)
  - Clipping threshold, % of inverter limit (default 98%, global; see
    ADR-003a §1 — applies to every string that has a converter/inverter AC
    power limit configured in "add_string_advanced" below; a string
    without a limit configured is never clipping-excluded, but the
    threshold fraction itself has no per-string override)
  - Default temperature source (optional; entity selector covering
    sensor.* with device_class temperature and weather.* entities;
    leave empty to disable derating correction by default for all
    strings — ADR-003b §1a)
  - Ambient-to-cell max uplift, °C (default 25; global; only relevant
    when the resolved temperature source — global default or a
    per-string override — is the ambient-sensor or weather-integration
    tier, since the module/cell-sensor tier reads cell temperature
    directly and never evaluates this formula at all; see ADR-003b §1a
    for the uplift formula this feeds)
  - Weather forecast entity for temperature prediction (optional; entity
    selector covering weather.* entities; used to forecast the expected
    module/cell or ambient temperature for the module/cell-sensor and
    ambient-sensor tiers above — see ADR-003c §3. Global, not
    per-string, and independent of the baseline candidate above even if
    that candidate also happens to be a weather.* entity. Leave empty to
    disable ADR-003c's forecast mechanism: any string using the
    module/cell or ambient temperature tier then gets no derating
    correction at all, forward or backward — see ADR-003c §5. Not shown
    or relevant if the weather-integration tier is the only temperature
    source in use, since that tier already forecasts natively)
  - Temperature regression method: `wls2` (default) / `linear` /
    `kernel` / `wls3` (global; only relevant if the field above is set —
    see ADR-003c §2. Independent of the shading-model regression method
    above: the two fit unrelated physical relationships and are not
    forced to share one method choice)
  - Intraday deviation-correction mode `intraday_correction_mode`:
    off / ramping / blending (default off; see ADR-006 §1)
  - Intraday deviation-correction cut-off, `intraday_correction_cutoff`
    (default 10%, applies whenever the mode above is not "off"; see
    ADR-006 §2)
  - Intraday deviation-correction rolling window, in slots (default 24 =
    2h; see ADR-006 §3)
  - Intraday deviation-correction ramp/blend duration, in slots (default
    12 = 1h; see ADR-006 §3)

Step "add_string" (repeated):
  - Name (free text, e.g. "Dach Süd")
  - Baseline candidate override (optional; same dropdown as the global
    default above; leave empty to use the global default set in
    "settings"). A string that *does* override is, by definition,
    treated as temperature-aware (ADR-003b §1c) — no separate per-string
    flag is offered, on the assumption that the realistic reason to
    override per string at all is a per-plane setup on a dedicated
    PV-forecast service (e.g. Solcast configured with one site per
    string), which is exactly the kind of provider ADR-003b §1c's flag
    is about in the first place.
  - Actual-yield entity (standard HA entity selector, sensor domain,
    power or energy device_class)
  - "Configure advanced corrections (clipping/derating) for this string?"
    (boolean, default off) → yes: "add_string_advanced", no:
    "add_another"

Step "add_string_advanced" (optional, per string):
  - Converter/inverter AC power limit (optional number, W; leave empty
    to disable clipping exclusion for this string — ADR-003a §1)
  - Temperature source override (optional; leave empty to use the global
    default; "none" disables derating for this string specifically even
    if a global default is set — ADR-003b §1a)
  - Temperature coefficient in %/°C (only shown/used if a temperature
    source — global default or override — applies to this string;
    default −0.4 — ADR-003b §1)
  - Rated DC capacity, Wp (optional number; only shown/used if this
    string's resolved temperature source — global default or override —
    is the ambient-sensor or weather-integration tier; not shown for the
    module/cell-sensor tier, which needs no uplift step at all. Leave
    empty to skip derating correction for this string when it would
    otherwise need this value — same skip-both-sides rule ADR-003c §5
    already applies to a missing forecast-capable predictor, applied
    here to a missing rated-capacity input instead. Used as the
    denominator in ADR-003b §1a's ambient→cell uplift formula — the
    string's own baseline series already serves as the irradiance-proxy
    numerator, but the array's own rated output has no other source in
    this design)

Step "add_another":
  - "Add another string?" (boolean) → back to "add_string" or finish
```

Note there is no latitude/longitude/elevation field anywhere in this
flow — see ADR-001 §1 for why.

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
