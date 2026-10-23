# Task: `wls2`/`wls3` Genuinely Raising `LinAlgError: Singular Matrix` for Real-Scale, Low-Variety `FC` (Diagnostic "selected" Series Still Missing After `TASK-0037`)

- **Status:** done
- **Related ADRs:** [ADR-008 §1 (Amendment 2026-09-22)]
- **Dependencies:** [TASK-0037-pinned-slot-pool-not-yet-elapsed-freeze]

## Goal

Downstream follow-up (human, live in chat, after deploying `TASK-0037` and
restarting): the diagnostic scatter sensors'
`"selected {method}"`/`"selected actual"` series entries still did not appear —
`TASK-0037`'s fix (a not-yet- elapsed slot no longer being permanently frozen at
`None`) proved necessary but not sufficient.

Root-caused by direct reproduction (not a log-based diagnosis this round): a
small, realistic test scenario — three training days, every one reporting the
exact same `FC`/`PV` (500.0), the same shape as an ordinary short-history or
low-`FC`-variety slot — made `wls3.fit()` raise
`numpy.linalg.LinAlgError: Singular matrix` for real, uncaught, while adding
test coverage for `TASK-0037`'s own per-string isolation. Two compounding
problems, not one:

1. `regression/base.py`'s `fit_weighted_polynomial` added a **fixed** ridge term
   (`_RIDGE_EPSILON = 1e-8`) to its batched normal-equations matrix purely to
   avoid an exactly-singular cold-start (all-zero-weight) case. That fixed
   constant is negligible, and therefore ineffective, once `wls2`/`wls3`'s own
   `FC²`/`FC³` design columns push the matrix's own entries well past `O(1)` for
   any ordinary real-world `FC` (hundreds of watts, cubed — `~1e14-1e16`). At
   that scale, a training window with little `FC` variety (a short history
   window, or a slot where `FC` rarely varies — plausible, not pathological) is
   genuinely rank-deficient, and the ridge does nothing to rescue it —
   `np.linalg.solve` raises for real.
1. Both `coordinator.py`'s `_diagnostics_tick_sync` and
   `diagnostics/compare_regressions.py`'s `extra_fit()` had **no** try/except at
   all around this fitting call — unlike `_refit_sync`'s own per-string
   isolation (ADR-000 §8) — so the exception from (1) propagated uncaught,
   silently preventing every string's (not just the degenerate one's)
   predictions from ever being cached, repeating on every single tick for as
   long as the underlying condition (real, ordinary data) persisted.

## Acceptance Criteria

- Given a batched normal-equations solve (`fit_weighted_polynomial`) whose
  matrix entries are large in magnitude (real-world `FC` values raised to
  `wls2`/`wls3`'s own powers), when the underlying training data has little `FC`
  variety, then the fit still succeeds — the ridge term is scaled to each slot's
  own matrix magnitude, not a bare constant.
- Given the original cold-start case the fixed ridge was written for (an
  all-zero-weight row), then it is regularized identically to before — the
  scaled ridge falls back to exactly the original constant for a
  near-zero-magnitude matrix.
- Given one string's `extra_fit()` body raises for any reason, when
  `extra_fit()` runs, then it is logged (`ADR-000 §8`) and that one string is
  left unmodeled for the tick — every other string's predictions still get
  cached, mirroring `_refit_sync`'s own per-string isolation.
- Given `mode.extra_fit()` or `mode.compute()` raises for any reason, when
  `_diagnostics_tick_sync` runs, then it does not propagate — it is logged and
  swallowed, leaving the previously cached result (if any) in place rather than
  crashing the tick or repeating an unhandled exception indefinitely.
- The full test suite passes, including new coverage reproducing the original
  `LinAlgError` scenario directly (a collinear, real-scale `FC` pool) and
  proving both new try/except layers actually swallow an injected exception
  without losing the other string's/tick's own result.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/regression/base.py` — `fit_weighted_polynomial`, new
  `_ridge_term` helper
- `custom_components/shady/coordinator.py` — `_diagnostics_tick_sync`
- `custom_components/shady/diagnostics/compare_regressions.py` — `extra_fit`
- `tests/test_regression.py`, `tests/test_coordinator.py`,
  `tests/test_diagnostics_compare_regressions.py` — new coverage
- `adr/008-numpy-backend-and-cache-array-accessor.md` — §1 amended

## Definition of Done

- Tests green (full suite: 645 passed) · `tasks/adr-summary.md` updated ·
  ADR-008 §1 amended · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- `mypy`/`ruff check`/`ruff format --check` clean on every edited file
- No new external dependencies

## Consumed Interfaces

- `SamplePool`/`fit_weighted_polynomial`
  (`custom_components/shady/regression/base.py`) — the batched fit this task's
  ridge fix protects (→ ADR-008 §1)
- `DiagnosticMode.extra_fit`/`compute`
  (`custom_components/shady/diagnostics/base.py`) — the two calls
  `_diagnostics_tick_sync` now guards (→ ADR-004 §5)

## Delivered Artifacts

- `custom_components/shady/regression/base.py` — new
  `_ridge_term(xt_w_x, degree)` helper: scales the ridge to
  `max(mean_diagonal, 1.0) * _RIDGE_EPSILON` per slot, replacing the bare
  `np.eye(degree + 1) * _RIDGE_EPSILON` constant `fit_weighted_polynomial` used
  inline before.
- `custom_components/shady/diagnostics/compare_regressions.py` — `extra_fit()`'s
  per-string loop body wrapped in `try`/`except Exception`, logged via a new
  module-level `_LOGGER` and left unmodeled on failure, not aborting the
  remaining strings; also added a temporary `_DIAGNOSTIC_LOG`-gated log line in
  `_selected_value` for live troubleshooting.
- `custom_components/shady/coordinator.py` — `_diagnostics_tick_sync`'s
  `mode.extra_fit()`/`mode.compute()` calls each wrapped in
  `try`/`except Exception`, logged via `_LOGGER.exception` and swallowed
  (falling back to `None`/the previously cached result respectively) rather than
  propagating.
- `tests/test_regression.py` — new
  `TestRidgeRegularizationHandlesLargeMagnitudeCollinearData`: reproduces the
  original `LinAlgError` directly (identical `FC` across every training day, all
  four strategies) and confirms the cold-start all-zero-weight case is still
  regularized identically to before.
- `tests/test_coordinator.py` — new
  `TestDiagnosticsTickSyncSwallowsModeExceptions`: an injected exception from
  `extra_fit()`/`compute()` does not propagate and does not block the other
  method/the previously cached result.
- `tests/test_diagnostics_compare_regressions.py` — new
  `TestExtraFitPerStringIsolation`: one string's `_predict_all_methods` raising
  does not prevent the other string's prediction from being cached.
- `adr/008-numpy-backend-and-cache-array-accessor.md` — §1 amended with the
  "Batching's shared-failure edge" note; header "Last updated" bumped.
- `tasks/adr-summary.md` — `regression/`'s summarized description updated to
  mention the scaled ridge.
- No external dependencies added.
