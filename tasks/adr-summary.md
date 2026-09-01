# ADR Summary — Architectural Ground Truth for Shady

**Project:** Shady — a Home Assistant custom integration (`custom_components/shady`)
that adjusts an existing PV yield forecast for local shading, learned
empirically (no horizon-profile input, no sun-geometry calculation).
**Source of truth:** `adr/INDEX.md` lists every ADR and its status. This
file is a condensed, implementation-facing digest — when in doubt, the
ADR text wins. All 17 ADRs are `Accepted` except ADR-003, which is
`Superseded` (split into ADR-003a/ADR-003b, content fully absorbed).
**Current repo state:** brainstorming-phase skeleton only —
`custom_components/shady/__init__.py`, `const.py`, `manifest.json`,
`translations/{en,de}.json` exist as placeholders with TODOs; no other
module exists yet. `tests/__init__.py` is empty.

---

## 1 — Tech stack & tooling

- **Language:** Python ≥3.14 (repo), mypy target 3.14 — raised from
  ≥3.11/3.12 by ADR-000 Amendment (2026-08-22), which is the required
  minimum since HA 2026.3.x. Home Assistant custom integration, `iot_class:
  local_polling`, HACS-packaged (`hacs.json` `homeassistant` minimum
  raised to `2026.3` for the same reason).
- **Numeric backend:** `numpy>=1.26.0`, declared in `manifest.json`
  `requirements` and `pyproject.toml` — batched (never naive per-slot)
  across all four `regression/` strategies, both `fit()` and `predict()`
  (ADR-008). Benchmarked on the real target platform (Raspberry Pi 5),
  not just dev x86. **Every `numpy.ndarray`-valued type is written
  `numpy.typing.NDArray[np.float64]`, never a bare `np.ndarray`** —
  ADR-000 §4 Amendment (2026-08-22); TASK-0005/TASK-0007 retrofitted via
  patch tasks (Scenario C), every task from TASK-0006 on uses it from
  the outset.
- **Config-flow validation:** `voluptuous` (dev dependency; standard HA
  pattern).
- **Gate (CI, `ADR-000 §1`):** `ruff format`, `ruff check`, `mypy --strict`
  (`mypy.ini`, `--config-file mypy.ini`), `pytest` — all four must pass
  with zero errors. `mypy --strict`: every function/method fully
  annotated, including private helpers and `-> None`.
- **HA-stub gap handling (`ADR-000 §2`):** untyped HA base classes cause
  `misc`/`untyped-decorator` mypy noise. Suppressed **per-file** via
  `mypy.ini` (`warn_unused_ignores = False` on exactly the HA-facing
  modules: `config_flow`, `sensor`, `coordinator`, `select`, `button` —
  `select.py` replaces `switch.py` as of ADR-004's 2026-08-30 amendment)
  plus targeted `# type: ignore[<code>]` on the *exact* flagged line
  (class statement for `misc`, the `@callback` line itself for
  `untyped-decorator`). Never a bare `# type: ignore`, never a global
  `disable_error_code`.

## 2 — Module boundaries & dependency direction (`ADR-000 §3`, updated by ADR-003b/007/012)

Dependencies point **upward only** (pure logic never imports HA-facing
code or `homeassistant.*`, except `providers/discovery.py` and
`providers/temperature.py`, which read `hass.states` only — no writes):

```
providers/ (discovery.py, normalize.py, base.py, temperature.py)
  → yield_correction.py
    → regression/ (base.py, kernel.py, linear.py, wls2.py, wls3.py)
      → forecast_adjust.py  -- (reverse edge back into yield_correction.py, ADR-003b §1b)
        → string_computation.py  -- also reads regression/, forecast_adjust.py, yield_correction.py directly (ADR-014)
          → aggregation.py
            → diagnostics/ (base.py, compare_regressions.py)  -- also reads string_computation.py directly (ADR-014); as of 2026-09-01, also holds a TYPE_CHECKING-only construction-time reference BACK to coordinator.py (ADR-004 §5) -- diagnostics/ is no longer in the zero-mocking tier
            → cache.py
              → coordinator.py  -- reads diagnostics/ via a per-instance mode registry (ADR-004 §5); no longer does fit/predict computation itself (ADR-014); passes itself into each DiagnosticMode at construction (ADR-004 §5, 2026-09-01)
                → sensor.py / config_flow.py / select.py / button.py
                  → __init__.py
```

- **`providers/`** — `discovery.py`+`normalize.py`: baseline (unshaded FC)
  discovery/scoring/normalization (ADR-009). `base.py`: shared provider
  base class + two HA-agnostic helpers (ADR-012 §1/§1a). `temperature.py`:
  temperature-source resolution (ADR-003b §1a, ADR-012). Pure-ish tier;
  zero-mocking tested except `discovery.py`/`temperature.py` (real `hass`
  fixture).
- **`yield_correction.py`** — optional per-string clipping exclusion
  (ADR-003a) + temperature derating (ADR-003b), no-op if unconfigured.
  Called forward (training prep) by `regression/` callers and in reverse
  (prediction finishing) by `forecast_adjust.py`.
- **`regression/`** — pluggable per-string, per-5-min-slot strategy:
  `linear`/`kernel`/`wls2` (default)/`wls3`. Shared `base.py` protocol:
  `fit(samples) -> FittedModel`, `predict(fc) -> (adjusted_forecast, confidence)`.
  Also reused unchanged for ADR-003c's learned temperature-forecast model.
- **`forecast_adjust.py`** — applies a string's fitted per-slot model to
  its raw baseline series; calls back into `yield_correction.py`'s reverse
  transform.
- **`string_computation.py`** (new 2026-08-31, ADR-014) — pure, shared
  per-string fit/predict computation, extracted from `coordinator.py`:
  `REGRESSION_STRATEGIES` registry, `apply_training_corrections`
  (clipping + temperature derating, per offset), `fit_string_model`
  (build-pool + strategy fit), `predict_string_forecast`
  (reverse-transform + final clamp, in that order). Slot-count-agnostic
  — serves both `coordinator.py`'s 288-slot sweep and `diagnostics/`'s
  single diagnosed slot with the same functions, no branch needed.
- **`aggregation.py`** — pure cross-string sums, day arrays, trapezoidal
  energy-increment calc, diagnostic accuracy calc (mode-independent,
  called by `diagnostics/`, ADR-004 §5), intraday-correction math
  (ADR-005, ADR-006 §5).
- **`diagnostics/`** (`base.py`, `compare_regressions.py`, new
  2026-08-30) — `DiagnosticMode` base class (mirrors `providers/base.py`'s
  `Provider` ABC, ADR-012 §1) + one concrete mode, `CompareRegressionsMode`
  (ADR-004 §1/§2/§2a/§2b/§4, moved here verbatim from the original inline
  design). `compute()` (required) shapes the sensor payload; `extra_fit()`
  (optional, default `None`) does whatever extra per-slot fitting the mode
  needs, via `string_computation.py` directly (ADR-014). Also declares
  `fit_cadence()`/`compute_cadence()` (required, `"daily" | "hourly" |
  "slot"` — ADR-004 §5, 2026-09-01). **As of the 2026-09-01 amendment, no
  longer pure:** every `DiagnosticMode` is constructed with the owning
  `ShadyCoordinator` (`self._coordinator`), and reaches its public
  interface directly (`cache`, `strings()`, …) for whatever a mode needs —
  `coordinator.py` no longer pre-builds a mode's full input context, only
  persists whatever `extra_fit()` returns. Still reuses `aggregation.py`'s
  accuracy function unmodified — see ADR-013 (Proposed, not scheduled) for
  two further modes sketched to confirm this base class doesn't need to
  change again for a whole-day scope (ADR-013's own 2026-09-01 note
  confirms the cadence-getter/coordinator-access change doesn't affect
  that conclusion).
- **`cache.py`** — pure, no `hass` import, injected `fetch_fn`. Index-
  addressable time-series store (generic over `sensor_id`) + simple
  dict stores (model cache, ramp state) + 2 restart-persisted integral
  totals. See §5 below.
- **`coordinator.py`** — the only module that imports `cache.py`.
  Registers all scheduling triggers + one generic push listener per
  `forward()`-implementing provider; reads raw data from `cache.py`/
  `providers/` and hands off to `string_computation.py` (ADR-014) for
  the actual fit/correction/predict computation — no longer performs
  that computation itself as of ADR-014 (previously
  `_apply_training_corrections` + inlined build-pool/fit/
  reverse-transform sequences); pushes results to sensors. Exposes
  `missing_required_entities()` for `__init__.py`'s startup-ordering
  guard (ADR-002 §1a). Also holds `_diagnostic_modes` (mirrors
  `string_computation.py`'s `REGRESSION_STRATEGIES` dict in shape, but is
  a **per-instance** attribute built in `__init__` as of the 2026-09-01
  amendment — each `DiagnosticMode` is now constructed with `self`, so a
  module-level constant no longer works), dispatching to the select-chosen
  `DiagnosticMode`'s `extra_fit()` at the recalibration trigger and
  caching whatever it returns (ADR-004 §5).
- **`sensor.py`/`config_flow.py`/`select.py`/`button.py`** — thin HA
  entity glue, all classes prefixed `Shady`. `select.py`'s
  `ShadyDiagnosticModeSelect` replaces the original `switch.py` as of
  ADR-004's 2026-08-30 amendment.
- **`__init__.py`** — wires platforms + coordinator into `hass.data`;
  registers the `shady.select_diagnostic_slot` service; owns the
  startup-ordering guard (ADR-002 §1a, TASK-0016) — `ConfigEntryNotReady`
  + `async_at_started` + a bounded `async_schedule_reload` bridge for a
  config entry whose referenced entities haven't loaded yet.

**Testing (`ADR-000 §6`):** every module in `providers/base.py`,
`providers/normalize.py`, `yield_correction.py`, `regression/`,
`forecast_adjust.py`, `aggregation.py`, `cache.py` — zero mocking, no
`unittest.mock`, no fake `hass`. Loaded via direct file-path import
(`importlib.util.spec_from_file_location`), **not** package import, to
avoid pulling in `homeassistant.*` via `__init__.py`. Dynamically-loaded
class names used as type annotations need a `TYPE_CHECKING`-only static
import mirroring the runtime path. **`diagnostics/` (`base.py`,
`compare_regressions.py`) left this tier on 2026-09-01** (ADR-004 §5,
second Amendment) once `DiagnosticMode` gained a required, construction-
time `ShadyCoordinator` reference — it's now tested the same way
`coordinator.py` itself is: the hand-written, real (non-`Mock`)
`homeassistant` stub convention (TASK-0009), not zero-mocking. Invariant
checks (e.g. `0 <=
corrected_output <= min(FC, inverter_limit)`) asserted explicitly, every
scenario. `providers/discovery.py` and `providers/temperature.py` are the
only pure-tier exceptions — tested against a real `hass` fixture.

## 3 — Core domain model (ADR-001, ADR-002, ADR-011)

- **Predictor space:** raw baseline forecast value `FC_i` (Watts) per
  5-min slot; target `PV_i` (actual yield). No sun-geometry, no lat/long.
- **Granularity:** one regression model per **configured string** ×
  per **5-minute-of-day slot** (288 slots/day, matches recorder grid).
  Global regression-method choice (`linear`/`kernel`/`wls2` default/
  `wls3`), same for every string.
- **Confidence:** normalized sum of sample weights in a slot's pool
  (`Σ magnitude_weight_i · time_weight_i · recency_weight_i`) — method-
  independent. Daily exposed confidence = `FC_i`-weighted average across
  a day's slots.
- **Rolling training window:** default 28 days (`window_days`,
  config-flow), re-fit nightly.
- **Recency weighting within the window (ADR-001 §4a):** each training
  day additionally weighted by `recency_weight_i = 1 -
  (day_age_i/(window_days-1)) · recency_decay_max` — `1.0` at the most
  recent day (yesterday, the window's effective date), down to `1 -
  recency_decay_max` at the oldest day; `recency_decay_max` default
  `0.5` (50%, global, config-flow), `0` disables it. Lets the fit adapt
  faster to a changing regime (e.g. a falling-leaves autumn) within the
  existing window, without shrinking `window_days` itself.
- **Output clamp:** predicted value clamped to `[0, FC]`, or
  `[0, min(FC, inverter_limit)]` if clipping-exclusion configured — this
  is the **final** step of the per-slot pipeline, applied exactly once,
  after ADR-006's intraday correction.
- **Temporal smoothing (ADR-011 §1):** each slot's pool widened with
  ±`smoothing_radius` (default 1) neighbor slots, weighted by
  `time_weight_i = 1 - distance_i/(smoothing_radius+1)`.
- **Neighbor-regime exclusion (ADR-011 §2/§3):** a neighbor slot whose
  median `PV/FC` ratio deviates from the center slot's by more than
  `neighbor_fitting_cutoff` (default 25%, global) is hard-excluded from
  that slot's pool — OR, if the cutoff is set to the sentinel `-1%`,
  every neighbor is instead rescaled (never excluded) to the center's
  median.
- **Coordinator triggers (ADR-002):** (1) full model recalibration —
  midnight+1min or manual button, using only complete-day data through
  yesterday; (2) forecast recompute — on recalibration completion AND on
  every baseline-provider update (no debounce); (3) forecast horizon =
  remainder of today + tomorrow (if published).
- **Startup ordering (ADR-002 §1a):** a config entry's referenced
  entities may not exist yet at `async_setup_entry` (HA boot-ordering
  race, no relative-load-order guarantee between custom components).
  Required entities (per-string actual-yield; per-string resolved
  baseline, if configured) missing while `hass.is_running` →
  `ConfigEntryNotReady` (HA's own backoff retry). Missing while HA is
  still starting → defer the startup fit via `async_at_started`, and if
  still missing once that fires, log + `async_schedule_reload` once to
  rejoin the `ConfigEntryNotReady` path. Optional correction-tier
  entities (temperature source, weather forecast entity) are never
  required — ADR-003b/ADR-003c's existing graceful degradation already
  covers "not loaded yet" the same as "genuinely unset."

## 4 — Optional per-string corrections (ADR-003a, ADR-003b, ADR-003c)

- **Inverter clipping exclusion (ADR-003a):** if a string has an inverter
  AC power limit configured, samples ≥ a global threshold fraction
  (default 98%) of that limit are **excluded** (not downweighted) from
  training, and the same limit becomes a second, tighter output clamp.
  No-op if unconfigured.
- **Temperature derating (ADR-003b):** if configured, actual-yield
  samples are corrected to 25°C-equivalent *before* the ratio is formed
  (forward transform), and the model's prediction is reverse-transformed
  back to the target slot's expected temperature at prediction time.
  Temperature source is a 3-tier hierarchy: per-string module/cell
  sensor (best) → global ambient sensor (uplifted via a formula using
  `FC` as an irradiance proxy) → `weather.*` current temperature
  (same uplift). A global flag (`ADR-003b §1c`, default `false`) skips
  this entire correction if the baseline provider (e.g. Solcast) already
  models temperature internally — avoids double-counting. A per-string
  baseline override is *always* assumed temperature-aware, no separate
  flag.
- **Temperature forecast for reverse transform (ADR-003c):** the
  weather-integration tier uses its native forecast. The cell/ambient
  tiers (no native forecast) get a **learned per-slot model** (same
  288-slot machinery as ADR-001, reusing `regression/`, default `wls2`,
  its own global method setting), trained against a dedicated global
  "weather forecast entity for temperature prediction" config field. If
  that field is unset, derating is skipped **entirely** (forward AND
  reverse together) for cell/ambient-tier strings — no naive-persistence
  fallback (that was superseded).

## 5 — `cache.py` design (ADR-007, ADR-007a, ADR-008)

Owns 5 independent caches, only ever called by `coordinator.py`:
1. Per-string/per-slot fitted-model cache (dict).
2. Per-string whole-day snapshot array (time-series shaped).
3. Two restart-persisted energy-integral running totals (ADR-005 §5/§6)
   — the *only* restart-persisted cache; carries `last_reset_date` for
   idempotent midnight reset.
4. Short-lived per-string ramp/crossfade state (dict, ADR-006 §1b) — not
   restart-persisted, discarded once a ramp/blend completes.
5. Historical two-series pool cache (time-series shaped), generic over
   any `sensor_id` pair — backs regression training, diagnostics, and
   (ADR-003c) the temperature-forecast model's own predictor/target pair.

**Time-series storage (ADR-007a §1):** `values: dict[sensor_id,
list[float | None | str]]` — three-state (`float`=known,
`None`=not-yet-fetched/invalidated, `str`=stable "unavailable"). Index =
absolute position from a fixed epoch (`(timestamp-epoch)//5min`), with a
`list_offset` map — not re-based to 0 each rollover. `cache.trim()` is
one explicit call (at recalibration, not implicit).

**Validated-range tracking (§2):** `(from_index, to_index)` per sensor.
`to_index=None` = actively pushed by Shady (e.g. `ShadyForecastSensor`).
Actual-yield = pure query, concrete `to_index`. **Provider-backed
predictors** (baseline FC, temperature) are hybrid: elapsed portion
query-bounded, not-yet-elapsed portion push-extended.

**Writing (§3):** `push(sensor_id, dict[index, value])` (bulk, never
one-at-a-time) with a `not_before_index` guard that silently drops
writes to already-elapsed indices — freezes history. `invalidate(...)`
resets a range to `None`.

**Fetch injection (§4):** `cache.py` takes `fetch_fn: Callable[[sensor_id,
start, end], list[float|None|str]]` as a constructor param — never
imports the recorder API itself. Validation batches sensors sharing an
identical missing range into one `fetch_fn` call.

**Three accessors, each sized to its one caller (ADR-008 §3):**
- `get_time_range(sensor_ids, start, end, on_invalid="skip"|"raw"|float=0.0, group_by="sensor"|"slot")` — contiguous ranges (day arrays, trailing windows). `ADR-007a §5`.
- `get_pinned_slot_pool(sensor_ids, slot_of_day, on_invalid="skip"|"raw"|float="skip") -> dict[sensor_id, list[float]]` — one slot across many days, pin-aware via cache-wide scalar `pinned_reference: date|None` (`pin_reference()`/`clear_reference()`). `ADR-007a §6`.
- `get_regression_pools(sensor_ids, smoothing_radius) -> dict[sensor_id, NDArray[np.float64]]` — full 288-slot sweep, batched `numpy`, shape `(288, window_days×(2×radius+1))`. Backed by a shadow `float64` array (NaN = gap) kept in sync with the three-state list on every push/invalidate. `ADR-008 §2`.

**Provider architecture (ADR-012):** `providers/base.py` defines a real
base class (not `Protocol`) with `fetch(start,end)` (required, pull),
`identify()` (optional, discovery), `forward(now)` (optional, push path —
returns the provider's current forward-looking belief). `coordinator.py`
runs **one generic loop**: for every provider whose `forward()` is
overridden, register a listener that calls `forward(now)`, converts to
cache's index scheme, and `push(...)`. Two concrete providers today:
baseline (discovery+normalize) and temperature; PV (actual yield) needs
**no provider** — it's a plain user-selected `entity_id` wired directly
into `cache.py`'s `fetch_fn`.

## 6 — Sensors & entities

- **`ShadyForecastSensor`** (per string) — corrected today+tomorrow
  forecast; attributes for intraday-correction transparency
  (`intraday_ratio`, `intraday_state`, `intraday_ramp_weight`,
  `values_raw`, `intraday_blend_active`) when ADR-006 active.
- **`ShadyDiagnosticModeSelect`** (one/entry, default `"off"`, ADR-004 §1,
  replacing the original `ShadyDiagnosticsSwitch` as of the 2026-08-30
  amendment) gates all diagnostics via a dropdown (`const.py`'s
  `DIAGNOSTIC_MODES`, today `"off"`/`"compare_regressions"`); while
  `"off"`, diagnostics sensors report `disabled`, zero extra fitting
  cost. Selecting a mode dispatches to a `DiagnosticMode` subclass
  (`diagnostics/`, ADR-004 §5) via `coordinator.py`'s `_diagnostic_modes`
  registry (per-instance as of the 2026-09-01 amendment) — adding a
  future mode (see ADR-013, Proposed, not scheduled) is a new option +
  subclass, not a rework of this entity.
- **`ShadyDiagnosticsSensor`** (per string, ADR-004 §2) — ApexCharts-
  shaped `series` (slot-pool scatter + 4 methods' selected-prediction
  points + actual point) and plain-float `accuracy` dict, built by
  calling the active `DiagnosticMode`'s `compute()` (today, always
  `CompareRegressionsMode`) and setting `state`/`attributes` from its
  returned `DiagnosticResult` directly. Diagnosed slot defaults to "last
  complete slot"; overridable via the `shady.select_diagnostic_slot`
  service (not entity-targeted — one diagnosed-slot state per **config
  entry**).
- **`ShadyDiagnosticsSumSensor`** (one/entry, ADR-004 §2b) — pointwise
  cross-string sum of the above.
- **6 aggregate sensors** (one/entry, ADR-005): `ShadyPvSumSensor`,
  `ShadyFcSumSensor`, `ShadyFcDaySumSensor` (288-value day array + energy
  state), `ShadyFcRemainingTodaySensor`, `ShadyPvEnergyIntegralSensor`
  (restart-persisted, midnight reset), `ShadyFcEnergyIntegralSensor`
  (same).
- **`ShadyRecalculateButton`** (ADR-002 §1) — manual recalibration
  trigger, same code path as the midnight schedule.
- **`ShadyConfigFlow` / `ShadyOptionsFlow`** (ADR-010) — see §7.

## 7 — Config flow shape (`ADR-010` is the single source of truth)

Three-step flow: **`settings`** (global, first) → **`add_string`**
(repeated: name, optional baseline override, actual-yield entity,
"configure advanced?") → optional **`add_string_advanced`** (per string:
inverter limit, temperature-source override, temp coefficient, rated DC
capacity) → **`add_another`** loop. Full field list lives in ADR-010;
key global defaults: `window_days=28`, `regression_method=wls2`,
`smoothing_radius=1`, `neighbor_fitting_cutoff=0.25`,
`recency_decay_max=0.5`, `clipping_threshold=0.98`, `max_uplift_c=25`,
`temperature_regression_method=wls2`, `intraday_correction_mode=off`,
`intraday_correction_cutoff=0.10`, `window_slots=24`, `ramp_slots=12`.
**No latitude/longitude/elevation field anywhere.** Options flow mirrors
this for post-setup editing.

## 8 — Intraday deviation correction (ADR-006)

Per-string (never on aggregate sensors), 3-state config field:
`off`(default)/`ramping`/`blending`. Trailing-window ratio
`pv_energy_window/fc_energy_window` (`window_slots`, default 24 = 2h),
clamped to `[1±intraday_correction_cutoff]` (default 0.10), ramped in
linearly over `ramp_slots` active slots (default 12 = 1h) from a reset
point (first active slot of day, or a provider update). **Ramping**
resets to `w=0` on every provider update (visible dip). **Blending**
crossfades old (frozen) vs. new (freshly ramping) prediction instead —
same steady state, no dip. Ordering is canonical: correction → **one**
final output clamp (`ADR-001 §2`/`ADR-003a §1a`), never clamped
mid-pipeline or per crossfade side.

## 8a — Drafted but not scheduled

- **Whole-day diagnostic modes** (comparing regression methods, or
  comparing providers, across all 288 slots of a day rather than one —
  ADR-013, `Status: Proposed`) are sketched only, to confirm ADR-004's
  `DiagnosticMode` base class doesn't need revisiting later. No task
  exists for either; unlike §9 below, this is not a permanent rejection —
  either may be scheduled in a future planning pass.

## 9 — Explicit exclusions (never implement these)

- **No** `sun_geometry.py` module, no astronomical calculation, no
  lat/long/elevation config field anywhere (ADR-001 §1).
- **No** per-integration baseline adapters (Forecast.Solar/Solcast-
  specific code) — generic attribute-shape discovery only (ADR-009).
- **No** naive-persistence fallback for temperature forecasting — fully
  superseded by ADR-003c's learned model; if no forecast-capable weather
  entity exists, the correction is skipped entirely, not degraded.
- **No** hard minimum-sample gate for intraday correction — superseded
  in-place by the smooth ramp (ADR-006 revision note).
- **No** debounce on baseline-update-triggered recompute (deliberate
  simplification, ADR-002 §2).
- **No** recorder-statistics *writing* — Shady only ever reads recorder
  history; it has no `async_import_statistics`-style write path (unlike
  the sibling project Effy).
- **No** per-string override of the global regression method, smoothing
  radius, clipping threshold, or intraday cutoff — these are always
  global.
- **No** naive per-slot `numpy` calls in `regression/` — explicitly
  rejected by benchmark (ADR-008 §1); batched only.
- **No** second/bespoke recorder-read path outside `cache.py`'s injected
  `fetch_fn` — `coordinator.py` never calls `statistics_during_period`
  directly.

## 10 — Non-functional requirements

- **Target hardware:** must perform acceptably on Raspberry Pi 5 (ADR-008
  explicitly re-benchmarked there, not just x86 dev machines).
- **Restart tolerance:** only the 2 energy-integral totals need exact
  restart persistence; everything else safely rebuilds (accepted gap).
- **No blanket type-ignore / no blanket mocking** — suppression and test
  strategy are both per-file/per-module, never global.
- **ADR-driven rationale, not inline essays** (`ADR-000 §7`) —
  non-obvious *why* goes in an ADR, referenced by number from code
  comments; module docstrings stay to 1–3 sentences.
- **`adr/INDEX.md`** must be kept in sync with any ADR structural change
  in the same commit (mandatory, `ADR-000 §7`) — relevant if any task
  discovers an ADR gap requiring an amendment.
