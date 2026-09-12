# Shady – Shading-Adjusted PV Forecast

**Status:** Implementation complete (20/20 core tasks); two rounds of
post-implementation ADR-conformance audit and remediation complete — round 1
(13/13 remediation tasks, closed 2026-09-10) and round 2 (4/4 remediation tasks,
closed 2026-09-12; 8 of the 12 round-2 audit groups needed no fix at all). See
`tasks/AUDIT-INDEX.md` for the full round-2 findings and `tasks/archived/` for
round 1.

Shady is a Home Assistant integration that corrects an existing solar (PV) yield
forecast — from Forecast.Solar, Solcast, or a weather integration — for **your
specific roof's shading**: a tree, a chimney, a neighboring building, anything a
generic forecast service has no way to know about.

## Why this exists

Every PV forecast integration predicts what a panel *would* produce under open
sky. If part of your array is shaded at certain times of day, the forecast is
systematically wrong for that string — too high, at predictable times — and
nothing in the forecast service itself can fix that, because it has no idea your
shading exists.

The usual fix is a manually maintained horizon profile: you measure or estimate
the angles of whatever blocks the sun, enter them by hand, and hope you got it
right (and remember to update it when the tree grows). Shady takes a different
approach.

## How it works, in plain terms

Shady doesn't model your horizon at all. Instead, it watches what actually
happens: for each of your strings, it compares the forecast against the real
recorded yield, slot by slot through the day, over a rolling recent window (a
few weeks by default). Wherever your shading consistently pulls actual yield
below (or above) the raw forecast at a given time of day, Shady learns that
pattern automatically — no measurement, no sun-position math, no manual profile
to maintain or update as trees grow or seasons change.

Concretely:

- **A baseline forecast** is auto-detected — normally your existing PV-forecast
  integration, or, if you don't have one, sunshine-duration or cloud-coverage
  data from your weather integration, used as a stand-in.
- **One model per string, per time-of-day slot** learns the relationship between
  that baseline and your real, historical yield — refit daily, so it stays
  current as shading and seasons change.
- **Neighboring time slots smooth each other out**, except right at a shading
  edge (e.g. the moment a tree's shadow moves off a panel), which Shady detects
  and treats separately rather than blurring into a soft transition that isn't
  really there.
- **Optional corrections** for two other things that look like shading in the
  data but aren't: inverter/converter clipping (the inverter simply can't output
  more, regardless of sunlight) and temperature derating (panels lose efficiency
  as they heat up). Both are off by default and only apply if you configure the
  relevant details for a string.
- **Optional intraday adjustment**: if actual yield is currently running above
  or below what today's forecast predicted, the *remaining* part of today's
  forecast can smoothly react to that — useful for things like snow melting off
  a shaded panel later than an unshaded one.

The result is a per-string forecast sensor (today + tomorrow) that gets more
accurate the longer Shady has been watching your specific installation — plus
whole-property aggregate sensors, and an optional diagnostic view for anyone who
wants to see the model's own accuracy for themselves.

## Relationship to [Effy](https://github.com/eschnepel/effy)

Shady is a sibling project to Effy, by the same author. Effy isn't required, but
the two are designed to complement each other, each handling its own part of the
picture.

They solve different problems, though. Effy takes an *already-known* efficiency
loss — the gap between a battery management system's output (to the house grid)
and its input (raw PV strings) — and distributes it across the BMS's input
sensors: an accounting problem. Shady's job is the comparison Effy doesn't do at
all: PV forecast vs. real yield, learning a correction from the gap. If you run
Effy, its per-string output sensors are a valid, ready-made "actual yield" input
for Shady — just as valid as pointing Shady at your raw PV sensors directly.

## Requirements

- A Home Assistant instance with recorder history enabled for your actual-yield
  sensor(s) — either raw PV sensors or, if you run it, Effy's output sensors.
  Shady trains against recorder short-term statistics (the 5-minute resolution
  data), so it needs some history to learn from; accuracy improves over the
  first few weeks as that history builds up.
- Home Assistant purges short-term statistics after 10 days by default — a fixed
  Home Assistant behavior, separate from the general `purge_keep_days` history
  setting, and not something Home Assistant currently exposes a dedicated toggle
  for. If Shady's training window (28 days by default, configurable) is longer
  than what your recorder actually retains at 5-minute resolution, training data
  will always be incomplete. Worth checking your recorder setup against Shady's
  configured window if you want the full benefit.
- An existing PV-forecast integration (Forecast.Solar, Solcast, or similar)
  **or** a weather integration that publishes sunshine-duration or
  cloud-coverage forecasts, to serve as the baseline Shady corrects.

## Installation (HACS)

1. In HACS, add this repository as a custom repository (category: Integration).
1. Install "Shady" and restart Home Assistant.
1. Go to **Settings → Devices & Services → Add Integration**, search for
   "Shady", and follow the setup flow.

## Configuration

Setup is entirely through the Home Assistant UI — no YAML:

1. **Global settings** — baseline forecast source, training window, regression
   method, and other defaults that apply to every string (all changeable later
   from the integration's Options).
1. **Add a string** — one PV string per step: its actual-yield sensor, an
   optional per-string baseline override, and optional advanced corrections
   (clipping, temperature derating) if you want them for that string.
1. Repeat step 2 for each string, then finish setup.

Every setting has a sensible default; you can start with just your strings'
actual-yield sensors and refine from there.

## Entities created

- **A forecast sensor per string** — corrected forecast for today and tomorrow,
  with a confidence attribute.
- **Six whole-property aggregate sensors** — current actual yield, current
  corrected forecast, today's full corrected-forecast profile, remaining-day
  forecast, and two energy-integral sensors (actual vs. forecast, in kWh,
  resetting daily) for a direct day-level comparison.
- **An optional diagnostic mode** (a select entity, off by default) that adds a
  per-string chart sensor comparing regression methods against your own
  historical data, including each method's own hit rate — for anyone curious how
  well the model is actually doing.
- **A recalculate button**, for triggering an immediate refit outside the normal
  daily schedule.

## For contributors

Shady's design decisions are recorded as Architecture Decision Records, not in
this README:

- [`adr/INDEX.md`](adr/INDEX.md) — the full ADR list, status, and how they
  relate to one another.
- [`adr/000-coding-standards.md`](adr/000-coding-standards.md) — coding
  standards and module boundaries (shared with Effy).
- [`docs/architecture.mmd`](docs/architecture.mmd) — a Mermaid dependency
  diagram of the processing pipeline.
