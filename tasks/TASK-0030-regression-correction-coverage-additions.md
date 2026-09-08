# Task: Regression & Correction-Layer Test-Coverage Additions

- **Status:** done
- **Related ADRs:** [ADR-001, ADR-006, ADR-008]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0005-patch-2-unclamped-predict, TASK-0005-patch-3-consolidate-predict, TASK-0002-cache-core-time-series-store]

## Goal
Three audits (`AUDIT-0002`, `AUDIT-0004`, `AUDIT-0003`) each found a
small, additive test-coverage gap in the pure regression/correction
layer — none are behavioral defects, all are "a regression here wouldn't
be caught by today's test suite" gaps:

1. **No test in `test_regression.py` calls `predict_unclamped()` directly
   on a real strategy.** Every test in that file goes through `predict()`
   or `build_pool()`. Incidental coverage exists in a different audit
   group's test file (`test_coordinator_temperature_forecast.py`), but
   if that test were ever removed or narrowed, `test_regression.py`
   alone would not catch a strategy silently clamping inside
   `predict_unclamped`.
2. **No test in `test_forecast_adjust.py` parametrizes over all four
   real `regression/` strategy modules** — the file's stub-model fixtures
   are hand-built fakes, not the real `linear`/`wls2`/`wls3`/`kernel`
   classes, unlike `test_regression.py`'s own
   `TestEveryStrategyHandlesTheSharedFixtures` pattern.
3. **No test cross-checks `get_regression_pools`'s cell values against
   `get_pinned_slot_pool`'s single-slot read** for the same sensor/index
   as a true differential-correctness proof (both accessors share the
   underlying shadow-array read path, so this is a low-severity gap,
   but currently unverified).

## Known Decisions
- All three additions are pure, additive tests — no production code
  changes anywhere in this task.
- Each audit already recommended the exact shape of the missing test;
  this task's job is to implement what was already specified, not to
  design new test strategy.

## Open Questions for Execution
- None expected. If, while implementing item 2, the worker finds that
  parametrizing `TestUsesPredictUnclampedNotPredict`-style spy tests
  over all four real strategies requires more fixture rework than the
  audit's brief description implies, note the actual scope found here
  before expanding it unilaterally — but a straightforward
  `@pytest.mark.parametrize` over the four strategy modules, reusing
  `test_regression.py`'s existing fixture-construction helpers, is
  expected to suffice.

## Acceptance Criteria
- Given `tests/test_regression.py`, When run after this task, Then it
  contains at least one new test that calls `predict_unclamped()`
  directly on each of the four real strategies (`linear`, `wls2`,
  `wls3`, `kernel`) with a fixture engineered so the unclamped value
  would visibly differ from the clamped `predict()` output (e.g. an
  extrapolated value outside `[0, FC]`), asserting the unclamped value
  is preserved.
- Given `tests/test_forecast_adjust.py`, When run after this task, Then
  it contains at least one new test parametrized over the four real
  `regression/` strategy modules (not hand-built stubs) proving
  `adjust_forecast`/`reverse_transformed_forecast` behaves identically
  in call-pattern (calls `predict_unclamped`, never `predict`) across
  all four, mirroring `test_regression.py`'s own
  `TestEveryStrategyHandlesTheSharedFixtures` pattern.
- Given `tests/test_cache_regression_pools.py` or
  `tests/test_cache_pinned_slot_pool.py` (whichever already has the
  relevant fixtures), When run after this task, Then it contains at
  least one new differential test asserting a `get_regression_pools`
  cell value equals the corresponding `get_pinned_slot_pool` single-slot
  read for the same sensor/index.
- Given the full test suite, When run after this task, Then all
  pre-existing tests still pass unmodified, plus the new additions —
  no existing assertion changes.

## Estimated File / Module Footprint (hint, not a commitment)
- `tests/test_regression.py`
- `tests/test_forecast_adjust.py`
- `tests/test_cache_regression_pools.py` or
  `tests/test_cache_pinned_slot_pool.py`
- No production `.py` file.

## Definition of Done
- Tests green · docs updated (none needed — test-only) · no open ADR
  conflicts
- `Delivered Artifacts` block completed and accurate, listing the exact
  new test names added per file
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/regression/base.py` → `FittedModel.predict`,
  `FittedModel.predict_unclamped` — (→ task: TASK-0005-patch-2,
  TASK-0005-patch-3) — the exact methods the new tests exercise.
- `custom_components/shady/forecast_adjust.py` →
  `reverse_transformed_forecast`, `adjust_forecast` — (→ task:
  TASK-0008-forecast-adjustment) — the functions item 2's new
  parametrized test targets.
- `custom_components/shady/cache.py` → `get_regression_pools`,
  `get_pinned_slot_pool` — (→ task: TASK-0002, TASK-0006) — the two
  accessors item 3's differential test compares.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
- `tests/test_regression.py` → new `TestPredictUnclampedPreservesRawValue`
  class, one test:
  `test_unclamped_differs_from_clamped_at_zero_query_fc` — fits all
  four real strategies (`linear`, `wls2`, `wls3`, `kernel`) on the
  existing `_clipping_ceiling_pool()` fixture, calls
  `predict_unclamped()` directly at query `FC=0.0` (where `predict()`'s
  own `clamp_to_forecast` always clips to exactly `[0, 0]`), and asserts
  the raw value differs from the clamped one, is finite, and that
  confidence is untouched by clamping either way.
- `tests/test_forecast_adjust.py` → four new module-level loads
  (`linear_mod`, `wls2_mod`, `wls3_mod`, `kernel_mod`, exposed as
  `ALL_STRATEGIES`) alongside the existing stub-based ones; new
  `_real_strategy_pool()` helper (a small, seeded, real `build_pool()`
  fixture); new `pytest` import (needed for the parametrize decorator);
  new `TestRealStrategiesCallPredictUnclampedNotPredict` class,
  parametrized over all four real strategies, one test:
  `test_reverse_transform_uses_the_real_raw_prediction` — proves
  `reverse_transformed_forecast` matches a `predict_unclamped`-based
  computation and diverges from the wrong, `predict()`-based one, using
  the same `FC=0` divergence mechanism as the `test_regression.py`
  addition above.
- `tests/test_cache_pinned_slot_pool.py` → new
  `TestMatchesGetRegressionPoolsCenterColumnForSameSensorAndSlot` class,
  two tests: `test_pinned_single_slot_matches_regression_pools_center_column`
  and `test_matches_across_several_sensors_and_slots` — cross-checks
  `get_pinned_slot_pool`'s single-slot read against
  `get_regression_pools(smoothing_radius=0)`'s center column for the
  same sensor/slot, using `pin_reference(D)` +
  `get_regression_pools(reference=D+1 day)` to align both accessors'
  independently-computed windows to the identical calendar range
  (`get_pinned_slot_pool`'s window ends *at* its anchor;
  `get_regression_pools`'s ends the day *before* its `reference`).
  Reuses this file's existing `_index_valued_fetch_fn`/`_midnight`
  helpers, no new fixture machinery needed.
- No production `.py` file touched — `git diff --stat` confirms exactly
  the three test files above, matching the Estimated Footprint.
- External dependencies added: none. `tasks/DEPENDENCIES.md` unchanged.
- Full local gate after this task: `pytest` 426/426 passed (419 + 7 new:
  1 + 4-parametrized + 2); `mypy --config-file mypy.ini
  custom_components/ tests/` clean on 53 source files; `ruff check .`
  clean repo-wide; `ruff format --check .` shows only the one
  pre-existing, unrelated, already-documented drift file
  (`adr/004-diagnostics-select-and-scatter-sensor.md`'s embedded code
  block), untouched, out of scope — `ruff format` was applied to all
  three edited test files during this task to keep them clean under the
  now-pinned `ruff==0.16.4` (`TASK-0025`).
