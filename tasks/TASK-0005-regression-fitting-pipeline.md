# Task: Regression Fitting Pipeline

- **Status:** done
- **Related ADRs:** [ADR-001 §2, ADR-001 §2a, ADR-001 §3, ADR-001 §3a, ADR-011 §1, ADR-011 §2, ADR-011 §3, ADR-008 §1]
- **Dependencies:** []

## Goal
Implement the `regression/` package: the shared `base.py` protocol
(`fit(samples) -> FittedModel`, `predict(fc) -> (adjusted_forecast,
confidence)`), sample weighting (`magnitude_weight_i`, `time_weight_i`),
neighbor-regime exclusion/rescale, and all four pluggable strategies
(`linear`, `kernel`, `wls2`, `wls3`) — operating on already-assembled,
padded `numpy` pool arrays (batched per ADR-008 §1, never naive
per-slot). No `cache.py` coupling — pools are passed in.

## Acceptance Criteria
- Given a shared scenario fixture with a hard shading edge crossing
  mid-window, When each of the four strategies fits and predicts on it,
  Then every strategy's output satisfies `0 <= predicted <= FC` for
  every sample (ADR-000 §6 invariant).
- Given a scenario with samples at or above a clipping-style ceiling,
  When `wls2`/`wls3` predict at an out-of-training-range `FC`, Then the
  output still respects the same clamp invariant (extrapolation safety,
  ADR-001 §2).
- Given a pool with near-zero-`FC` samples (sunrise/sunset), When weights
  are computed, Then `magnitude_weight_i` smoothly approaches (but is
  only exactly `0` at) `FC_i == 0` — continuous, not a hard cutoff
  (ADR-001 §2).
- Given a center slot and a neighbor slot whose median `PV/FC` ratio
  deviates beyond `neighbor_fitting_cutoff` (default 0.25), When the pool
  is built, Then that neighbor's entire series is hard-excluded
  (`time_weight_i` forced to 0), not merely downweighted (ADR-011 §2).
- Given `neighbor_fitting_cutoff = -1%` (the rescale sentinel), When the
  same deviating neighbor is processed, Then it is rescaled to the center
  slot's median and retained, not excluded (ADR-011 §3).
- Given confidence is computed for the same pool across all four
  strategies, When compared, Then confidence is identical regardless of
  which strategy produced the point estimate (ADR-001 §2 — confidence is
  method-independent, pool-weight-sum only).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/regression/__init__.py`
- `custom_components/shady/regression/base.py`
- `custom_components/shady/regression/linear.py`
- `custom_components/shady/regression/kernel.py`
- `custom_components/shady/regression/wls2.py`
- `custom_components/shady/regression/wls3.py`
- `tests/test_regression_*.py` (shared scenario fixtures across all four)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- `numpy>=1.26.0` used per ADR-008 §1 (already declared in
  `manifest.json`/`pyproject.toml` — confirm, don't re-add)
- Zero-mocking test suite (ADR-000 §6), shared scenario fixtures reused
  across all four strategies rather than bespoke data per strategy.

## Consumed Interfaces
<!-- None — this task has no dependencies. -->

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- **Scope note on the module dependency diagram (ADR-000 §3):** the
  diagram shows a direct `regression --> yield_correction` edge. This
  task does **not** implement that edge — `regression/base.py` never
  imports `yield_correction.py`. Per this task's own Goal ("No cache.py
  coupling — pools are passed in"), the same principle was extended to
  `yield_correction.py`: `build_pool`'s `fc_by_offset`/`pv_by_offset`
  inputs are assumed **already** yield-corrected (clipping-excluded,
  temperature-derated) by whoever assembles them. TASK-0008
  (`forecast_adjustment`, which already depends on both this task and
  TASK-0007) or TASK-0010 (`coordinator`) is where that actual wiring
  must land. Flagging this now so the Lead Agent/next worker doesn't
  assume it's already done.
- **Input contract for `build_pool`** (this task's own design decision —
  `cache.py`'s `get_regression_pools`, ADR-008 §2, doesn't exist yet):
  `fc_by_offset`/`pv_by_offset: dict[int, np.ndarray]`, keyed by neighbor
  offset (`0` = target slot, `-radius..+radius` = neighbors), each value
  shape `(n_slots, window_days)`, **pre-aligned** so row `s` means the
  same target slot `s` across every offset (388-slot wraparound already
  resolved by the caller). `NaN` marks pad/invalid, matching ADR-008
  §2's shadow-array convention. **TASK-0006, when it implements
  `get_regression_pools`, must produce (or adapt to) this exact shape.**
- `custom_components/shady/regression/__init__.py` → empty package marker.
- `custom_components/shady/regression/base.py`:
  - `RESCALE_SENTINEL: float = -0.01` — the ADR-011 §3 sentinel value.
  - `SamplePool` — frozen dataclass: `fc`, `pv`, `weight`
    (`np.ndarray`, shape `(n_slots, pool_width)`, NaN-free/"safe" — a
    pad/invalid/excluded position is `0.0` in `fc`/`pv` and `weight`),
    `confidence` (`np.ndarray`, shape `(n_slots,)`, `= weight.sum(axis=1)`,
    computed once, shared verbatim by every strategy).
  - `FittedModel` — `typing.Protocol` with
    `predict(fc: np.ndarray) -> tuple[np.ndarray, np.ndarray]` (returns
    `(adjusted_forecast, confidence)`, both shape `(n_slots,)`). Every
    strategy's concrete `FittedModel` dataclass implements this.
  - `clamp_to_forecast(adjusted: np.ndarray, fc: np.ndarray) -> np.ndarray`
    — the shared `[0, FC]` clamp (ADR-001 §2), applied unconditionally
    by every strategy's `predict()`, including under extrapolation.
  - `passthrough_where_no_confidence(adjusted, fc, confidence) -> np.ndarray`
    — cold-start fallback: where `confidence <= 0`, returns `fc`
    unmodified instead of a numerically-arbitrary regularized-fit value.
  - `build_pool(fc_by_offset: Mapping[int, np.ndarray], pv_by_offset: Mapping[int, np.ndarray], smoothing_radius: int, neighbor_fitting_cutoff: float) -> SamplePool`
    — the shared pool-construction logic (ADR-001 §2's
    `magnitude_weight_i`, ADR-011 §1's `time_weight_i`, §2's hard
    exclusion, §3's rescale via `neighbor_fitting_cutoff ==
    RESCALE_SENTINEL`). **Column layout of the returned pool:** offsets
    concatenated in ascending order (`-radius, ..., 0, ..., +radius`),
    each contributing exactly `window_days` columns — e.g. for
    `radius=1`: columns `[0:window_days]` = offset `-1`,
    `[window_days:2*window_days]` = offset `0`,
    `[2*window_days:3*window_days]` = offset `+1`. **This exact layout
    is now load-bearing** for anything that wants to inspect a specific
    neighbor's contribution after the fact (as this task's own tests do).
  - **`magnitude_weight_i` formula (this task's own design decision, not
    numerically specified by ADR-001 §2):** `FC_i / row_max(valid FC in
    that offset's block)` — scale-invariant, exactly `0` only at
    `FC_i == 0`, no installation-specific constant needed.
  - `fit_weighted_polynomial(pool: SamplePool, degree: int) -> np.ndarray`
    — the shared batched WLS solve (ADR-008 §1): one `numpy.linalg.solve`
    call for the whole batch, ridge-regularized (`1e-8` on the diagonal)
    for numerical stability on zero-weight rows. Returns coefficients,
    shape `(n_slots, degree+1)`, lowest power first. **Note for anyone
    extending this:** `numpy>=2.0`'s `linalg.solve` requires an explicit
    trailing `K` dimension on `b` for batched (non-1-D) use — it no
    longer implicitly treats a `(..., M)` array as a stack of vectors
    the way pre-2.0 numpy did. This function already handles it; don't
    revert to a bare `(n_slots, M)`-shaped `b`.
  - `evaluate_polynomial(coefficients: np.ndarray, fc: np.ndarray) -> np.ndarray`
    — batched polynomial evaluation, shared by `linear`/`wls2`/`wls3`'s
    `predict()`.
- `custom_components/shady/regression/linear.py` → `DEGREE = 1`,
  `LinearFittedModel` (`coefficients: np.ndarray` shape `(n_slots, 2)`,
  `confidence: np.ndarray`), `fit(pool: SamplePool) -> LinearFittedModel`.
- `custom_components/shady/regression/wls2.py` → `DEGREE = 2`,
  `Wls2FittedModel` (coefficients shape `(n_slots, 3)`),
  `fit(pool: SamplePool) -> Wls2FittedModel`. **Default strategy** per
  ADR-001 §2 (the default is a config-flow concern, ADR-010 — not
  encoded here).
- `custom_components/shady/regression/wls3.py` → `DEGREE = 3`,
  `Wls3FittedModel` (coefficients shape `(n_slots, 4)`),
  `fit(pool: SamplePool) -> Wls3FittedModel`.
- `custom_components/shady/regression/kernel.py`:
  - `KernelFittedModel` — retains `fc_pool`/`pv_pool`/`weight_pool`/
    `confidence`/`bandwidth` (all `np.ndarray`); `predict()` recomputes a
    Gaussian-kernel-weighted average on every call (ADR-008 §2: `fit()`
    caches these arrays once, `predict()` is the hot path and never
    re-touches the time-series cache).
  - `fit(pool: SamplePool) -> KernelFittedModel`.
  - **Kernel bandwidth formula (this task's own design decision, not
    specified by ADR-001 §2):** per-slot pool-weighted standard
    deviation of that slot's valid `FC_i`, floored at
    `max(1% of that slot's own max FC, 1e-6)`. Treat as an
    implementation detail, not a frozen contract — only the shared
    `predict(fc) -> (adjusted, confidence)` interface is load-bearing
    for callers.
- `tests/test_regression.py` → 16 zero-mocking tests (9 test classes,
  one parametrized across all 4 strategies) covering all 6 acceptance
  criteria plus 2 additional scenarios (cold-start passthrough,
  `smoothing_radius=0` reproducing independent-slots behavior). Three
  shared scenario-fixture functions (`_hard_shading_edge_pool`,
  `_clipping_ceiling_pool`, `_deviating_neighbor_pool`) are reused across
  strategies per ADR-000 §6's testing philosophy, not bespoke per
  strategy.
- External dependencies added: none — `numpy>=1.26.0` was already
  declared (manifest.json, pyproject.toml, DEPENDENCIES.md) before this
  task began; confirmed, not re-added.
- Gates: `ruff format`, `ruff check`, `mypy --config-file mypy.ini`
  (strict), `pytest` all pass with zero errors/warnings. Full `tests/`
  suite (39 tests total, all of Wave 1 so far) passes with no
  cross-file interference.
