# MVP Capabilities — Vertical Slices

Derived thematically from the ADR set (`tasks/adr-summary.md`), not from
the file layout. Ordered roughly by dependency (each later capability
tends to build on earlier ones), but capabilities with no interface
overlap can be implemented in parallel once their own dependencies are
`done` — see `tasks/INDEX.md` (created in Phase 2) for the exact graph.

Because Shady is a backend data-pipeline integration (regression math +
HA entity glue) rather than an interactive multi-page app, "end-to-end
testable/demonstrable" mostly means: a pytest suite that exercises the
capability's public contract per ADR-000 §6's zero-mocking philosophy
for pure modules, or a real-`hass`-fixture test for HA-facing modules —
each capability below is scoped so a worker can deliver and a reviewer
can verify it in isolation, without needing the rest of the system to
exist first (only its declared dependencies).

---

### 1 — Provider base architecture
**ADRs:** 012 §1, §1a
**Scope:** `providers/base.py` — the shared provider base class
(`fetch`/`identify`/`forward` contract, correct defaults) plus the two
HA-agnostic helper functions (HA-state → three-state-value mapping;
timestamp/value series-tuple assembly). No concrete provider yet.
**Demonstrable via:** unit tests instantiating a minimal dummy subclass
and asserting default behavior, plus direct tests of both helpers against
a range of state-shape inputs (numeric, "unknown", "unavailable", absent
attribute).

### 2 — Cache core: time-series store & contiguous-range accessor
**ADRs:** 007, 007a §1–§5
**Scope:** `cache.py`'s three-state (`float|None|str`) index-addressable
storage, `list_offset`, `validated` range tracking, `push`/`invalidate`,
`trim()`, `fetch_fn` injection + validate-before-read, and the
`get_time_range` accessor. Excludes `get_pinned_slot_pool` (§6, ships
with capability 15) and `get_regression_pools` (ADR-008, ships with
capability 6) — each accessor is delivered alongside its one real caller.
**Demonstrable via:** zero-mocking pytest with a trivial fake `fetch_fn`
returning canned three-state data; asserts gap-filling, push-freezing
(`not_before_index`), and both `group_by` shapes of `get_time_range`.

### 3 — Baseline forecast discovery & normalization
**ADRs:** 009
**Scope:** `providers/discovery.py` + `providers/normalize.py` — generic
attribute-shape scanning of `sensor.*`/`weather.*` entities, scoring,
sunshine/cloud-coverage normalization/inversion, canonical
`list[tuple[datetime, float]]` output.
**Demonstrable via:** real-`hass`-fixture tests with synthetic entities
of each recognized shape, asserting correct scoring/ranking and
canonical-series output.

### 4 — Temperature source provider
**ADRs:** 003b §1a, 012 §1
**Scope:** `providers/temperature.py` — resolves the config-selected
temperature source across all three tiers (module/cell sensor, ambient
sensor, weather-integration), `fetch()` per tier, `forward()` only
meaningful for the weather-integration tier.
**Demonstrable via:** real-`hass`-fixture tests, one per tier, asserting
correct entity resolution and fetch behavior; asserts `forward()` returns
`None` for non-weather tiers.

### 5 — Regression fitting pipeline
**ADRs:** 001 §2, §2a, §3, §3a; 011 §1, §2, §3
**Scope:** `regression/` package — shared `base.py` protocol,
`magnitude_weight_i`/`time_weight_i` weighting, neighbor-regime
exclusion/rescale, and all four strategies (`linear`, `kernel`, `wls2`,
`wls3`) with `fit()`/`predict()`/shared confidence definition. Operates
on already-assembled padded pools (numpy arrays) — no `cache.py`
coupling at this stage.
**Demonstrable via:** zero-mocking pytest with shared scenario fixtures
(hard shading edge, inverter clipping, sunrise/sunset near-zero, a
shading-boundary neighbor) exercised against all four strategies;
explicit invariant assertions (`0 <= predicted <= FC`).

### 6 — Cache: batched regression-pool accessor
**ADRs:** 008
**Scope:** extends `cache.py` (capability 2's delivered class) with the
`float64` shadow array (NaN-for-gap, kept in sync on push/invalidate)
and `get_regression_pools(sensor_ids, smoothing_radius) -> dict[sensor_id,
np.ndarray]`.
**Demonstrable via:** zero-mocking pytest asserting the shadow array
stays in sync with the three-state list, correct padded/masked shape,
and that `get_time_range`/existing accessors are unaffected.

### 7 — Optional yield corrections
**ADRs:** 003a, 003b §1, §1a, §1b, §1c
**Scope:** `yield_correction.py` — inverter clipping-exclusion
(training-time sample exclusion), temperature derating forward transform
(25°C normalization) and reverse transform, the ambient→cell uplift
formula, and the provider-already-corrects skip flag. No-op when
unconfigured. Pure functions of numbers in, numbers out — the *value* of
`cell_temperature` is supplied by the caller (capability 4's provider is
a dependency only for realistic integration, not for this module's own
unit tests).
**Demonstrable via:** zero-mocking pytest — exclusion behavior at/above
threshold, forward/reverse round-trip correctness, uplift formula at
boundary conditions (zero/full baseline), skip-flag behavior.

### 8 — Forecast adjustment
**ADRs:** 001 §2 (clamp), 003a §1a, 003b §1b (call site), 006 §1b
(ordering)
**Scope:** `forecast_adjust.py` — applies a string's fitted per-slot
model to its raw baseline series, calls back into `yield_correction.py`'s
reverse transform, applies the final `[0, FC]`/inverter-limit output
clamp exactly once, last.
**Demonstrable via:** zero-mocking pytest asserting correct ordering
(reverse-transform → clamp) and clamp correctness with/without an
inverter limit configured.

### 9 — Config flow
**ADRs:** 010
**Scope:** `config_flow.py` — `ShadyConfigFlow`'s `settings` →
`add_string` → `add_string_advanced` → `add_another` step sequence with
every field ADR-010 specifies, correct defaults, and `ShadyOptionsFlow`
mirroring it for post-setup edits.
**Demonstrable via:** real-`hass`-fixture flow tests stepping through
each path (with/without advanced step, multiple strings) asserting the
resulting config-entry data shape.

### 10 — Coordinator: recalibration, recompute & provider push
**ADRs:** 002, 012 §4
**Scope:** `coordinator.py` — the four core triggers (midnight+1min
recalibration, button-triggered recalibration, baseline-update-triggered
recompute, the generic provider-push loop over every `forward()`-
implementing provider instance), the up-to-yesterday training cutoff,
and startup safety net. Ties together capabilities 1–8 as its pure-layer
dependencies.
**Demonstrable via:** real-`hass`-fixture tests using fake time
advancement/manual trigger calls, asserting the right pure-layer calls
fire on each trigger and that cache pushes carry the correct
`not_before_index` guard.

### 11 — Corrected forecast sensor & manual recalculation
**ADRs:** 002 §3, §5; entity-glue portions of 000 §3
**Scope:** `sensor.py`'s `ShadyForecastSensor` (today+tomorrow horizon,
reads coordinator state), `button.py`'s `ShadyRecalculateButton`,
`__init__.py` wiring (`async_setup_entry`/`async_unload_entry`,
`PLATFORMS`). **This is the first fully end-to-end demonstrable
capability** — a config entry can be set up and produce a real corrected
forecast sensor.
**Demonstrable via:** real-`hass`-fixture integration test: set up a
config entry with one string, seed fake recorder/provider data, assert
`ShadyForecastSensor` exposes a plausible corrected value.

### 12 — Cross-string aggregate sensors
**ADRs:** 005
**Scope:** the six config-entry-level sensors (`ShadyPvSumSensor`,
`ShadyFcSumSensor`, `ShadyFcDaySumSensor`, `ShadyFcRemainingTodaySensor`,
`ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor`), the
trapezoidal energy-increment pure function in `aggregation.py`, the
midnight-reset trigger, and restart-persisted totals with
`last_reset_date` idempotency.
**Demonstrable via:** zero-mocking pytest for the pure aggregation math;
real-`hass`-fixture test for restart-persistence/reset idempotency across
the `[00:00, 00:01)` window.

### 13 — Intraday deviation correction
**ADRs:** 006
**Scope:** `ramp_weight`, `intraday_correction_factor`, `crossfade`
pure functions in `aggregation.py`; coordinator-side per-string
ramp/crossfade state in `cache.py`; the three-state config field wired
into `ShadyForecastSensor`'s pipeline ahead of capability 8's final
clamp, plus its transparency attributes.
**Demonstrable via:** zero-mocking pytest for the three pure functions
(ramp-in shape, clamp behavior, crossfade convergence-to-Ramping-
steady-state); real-`hass`-fixture test for a simulated provider update
under each of the three modes.

### 14 — Temperature-forecast learned model
**ADRs:** 003c
**Scope:** the cell/ambient-tier per-slot temperature forecasting model
— reuses capability 5's `regression/` strategies (fit mechanics only, no
`magnitude_weight_i`/ADR-011 smoothing) and capability 6's pool
accessor, trained against the dedicated weather-forecast-entity config
field, feeding capability 7's reverse-transform with a real forecast
instead of a missing value.
**Demonstrable via:** zero-mocking pytest for the per-slot fit/predict
using the shared regression strategies with the temperature-specific
weighting (no magnitude downweight); asserts the skip-both-sides rule
when no forecast-capable entity is configured.

### 15 — Diagnostics: select-based diagnostic modes & scatter/accuracy sensors
**ADRs:** 004 (Amendment 2026-08-30), 007a §6, 013 (Proposed, not scheduled)
**Scope:** `cache.py`'s `get_pinned_slot_pool` + `pinned_reference`
scalar (`pin_reference`/`clear_reference`), `select.py`'s
`ShadyDiagnosticModeSelect` (replacing the original `ShadyDiagnosticsSwitch`),
`diagnostics/`'s `DiagnosticMode` base class and `CompareRegressionsMode`
(the one concrete mode in scope), `sensor.py`'s one generic
`ShadyDiagnosticsSensor` class (no dedicated sum-sensor class, ADR-004
§5 2026-09-03), the accuracy pure function in
`aggregation.py` (unchanged, mode-independent), and the
`shady.select_diagnostic_slot` service registered in `__init__.py`. Split
into two tasks (base architecture, then the concrete mode + entities) —
see `tasks/INDEX.md`'s refinement log.
**Demonstrable via:** zero-mocking pytest for `get_pinned_slot_pool`'s
anchor resolution, the accuracy calculation, and the `DiagnosticMode`
base class's contract in isolation; real-`hass`-fixture test for the
select gating, auto-tracking vs. pinned-slot service call, and
future-pin partial-data shape.

---

## Explicitly out of scope for this capability set

Per `tasks/adr-summary.md` §9 — no capability implements astronomical/
sun-geometry calculation, per-integration baseline adapters, a
naive-persistence temperature fallback, a hard minimum-sample intraday
gate, recorder-statistics writing, or per-string overrides of
global-only settings.
