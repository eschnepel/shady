# Shady – Shading-Adjusted PV Forecast

**Status:** Brainstorming / Concept phase

Shady is a Home Assistant integration that adjusts an existing PV yield
forecast (e.g. from Forecast.Solar or Solcast) for local shading — caused
by a tree, a neighboring building, or other horizon obstructions that
generic forecast services don't know about.

The project adopts the engineering conventions of
[Effy](https://github.com/eschnepel/effy) (see [`adr/000-coding-standards.md`](adr/000-coding-standards.md))
as a shared foundation for both integrations.

## Core idea (see ADR-001 for details)

No manually maintained horizon profile, no sun-position calculation.
**Validated by an earlier proof-of-concept:** Shady learns shading purely
empirically from the relationship between the raw PV forecast value and
the real historical yield — per slot, directly against the forecast
value, not against time or sun position:

1. First, a **default baseline** (unshaded forecast) is automatically
   detected globally — either from a PV-forecast integration (e.g.
   Forecast.Solar, Solcast) or, if none is available, from the sunshine-
   duration or cloud-coverage forecast of a weather integration (the
   latter is inverted, since more cloud cover means lower yield, not
   higher) — before any string is even set up. Any string can optionally
   override this baseline with its own (e.g. one Solcast site per roof
   orientation); such an override automatically counts as
   "temperature-aware" (see point 4), with no separate question asked.
   Some providers only publish hourly or half-hourly values — Shady
   distributes these across the finer 5-minute slots.
2. Per string **and** per 5-minute slot of the day (`00:00`, `00:05`, …,
   `23:55` — the same grid as HA's recorder statistics), a dedicated
   regression model is trained: `PV ≈ f(FC)` — actual yield as a function
   of the raw forecast value, over the last 28 days of that same slot.
   The default method is `wls2` (captures the physically plausible
   curvature caused by the diffuse/direct-light split under shading,
   without `wls3`'s extrapolation risk); `linear` (validated in the PoC),
   `kernel`, and `wls3` are available as options.
3. A global smoothing radius (default: 1 neighboring slot) prevents hard
   jumps between adjacent slots — except at a shading boundary: if a
   neighbor series' median deviates by more than 25% (configurable) from
   the center slot's median, the entire neighbor series is excluded from
   that slot's training instead of pulling the prediction in the wrong
   direction. Alternatively (cutoff value `-1%`), the neighbor series is
   rescaled to the center slot's median instead of being excluded, and
   stays usable — weather- and time-distance weighting continue to apply
   unchanged.
4. A rolling 28-day window (configurable) keeps the model close to the
   current situation (e.g. a tree losing its leaves). Optional, per
   string: inverter/converter clipping samples are excluded from
   training *and* the corrected output is additionally capped at the
   limit; temperature derating is removed before the regression and
   added back at prediction time — both are disabled by default until
   explicitly configured. An additional global flag (one FC data
   provider per config entry) determines whether that provider (e.g.
   Solcast) already accounts for the temperature coefficient itself — if
   so, Shady's own temperature correction is skipped for every string, to
   avoid double-counting. A string with its own baseline override (point
   1) is always automatically treated as temperature-aware, regardless of
   the global flag.
5. Result: an adjusted forecast sensor per string (today + tomorrow),
   with a confidence aggregated to a daily total (`FC`-weighted across all
   of the day's slots — a single slot's confidence is not very meaningful
   on its own).
6. Optional (diagnostics switch, default off): a scatter-chart sensor per
   string comparing all four regression methods directly on the string's
   own historical data, pre-shaped for ApexCharts — including a hit rate
   per method (as a number in the `accuracy` attribute and directly in
   the series name, e.g. "wls2 (96%)"). By default the last complete slot
   is always shown; the `shady.select_diagnostic_slot` service (timestamp
   parameter) can instead select a specific, already-elapsed slot, e.g.
   to investigate a concrete event. The historical slot data is cached
   (updated only on recalibration or system start), so neither the
   5-minute update nor manual slot selection triggers repeated recorder
   queries.
7. Additionally, summed across all strings: actual yield now, corrected
   forecast now, corrected forecast for the whole day (a 288-value
   array), remaining-day forecast, and two integral sensors (actual
   energy and corrected-forecast energy, both resetting at midnight) for
   a direct actual-vs-forecast comparison in kWh over the course of the
   day.
8. Optional, **per string**: the remaining-day forecast reacts to the
   actual-vs-forecast deviation observed over the last 2 hours (read
   directly from recorder history, once at least 12 active slots exist in
   that window), bounded by a configurable cutoff (default `0` =
   disabled). Per string, because e.g. snow under a shaded string melts
   later than under an unshaded one — an aggregated value would blend the
   two. After every provider forecast update, there is also a one-hour
   linear crossfade between the old and new FC value, so weather-model
   updates don't appear as a jump on the dashboard.

## Open questions for further brainstorming

- Validate the smoothing-radius default (§3b) against real data.

## Structure

See [`docs/architecture.mmd`](docs/architecture.mmd) for a Mermaid
dependency diagram of the processing steps (string and aggregate level
combined).

See [`adr/000-coding-standards.md`](adr/000-coding-standards.md) for the
module boundaries.

| ADR | Title |
|---|---|
| [000](adr/000-coding-standards.md) | Code Quality Standards, Programming Style & Core Concepts |
| [001](adr/001-empirical-shading-model.md) | Empirical, Forecast-Value-Based Shading Model — predictor, regression method, granularity, smoothing, rolling window |
| [002](adr/002-coordinator-update-strategy.md) | Coordinator Update Strategy: Recalibration vs. Forecast Recompute |
| [003](adr/003-yield-corrections-clipping-derating.md) | Optional Per-String Yield Corrections: Clipping and Derating |
| [004](adr/004-diagnostics-switch-and-scatter-sensor.md) | Diagnostics: Enable Switch and Scatter-Series Sensors (Per-String and Summed) |
| [005](adr/005-aggregate-sum-and-integral-sensors.md) | Cross-String Aggregate Sensors: Sums and Daily Integrals |
| [006](adr/006-intraday-deviation-correction.md) | Intraday Deviation Correction for the Remaining-Today Forecast |
| [007](adr/007-coordinator-cache-split.md) | Splitting the Coordinator: A Dedicated Cache Module |
| [008](adr/008-numpy-backend-and-cache-array-accessor.md) | Numeric Backend for `regression/`, and a Batched Cache Accessor |
| [009](adr/009-baseline-forecast-sourcing.md) | Baseline (Unshaded) Forecast Sourcing: Generic Attribute Discovery *(split from ADR-001 §5)* |
| [010](adr/010-config-flow-shape.md) | Config Flow Shape *(split from ADR-001 §6)* |

Further ADRs (011 onward) will be added as brainstorming continues.
