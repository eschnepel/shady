# Task: Intraday Ramping-vs-Blending Divergence Test

- **Status:** todo
- **Related ADRs:** [ADR-006]
- **Dependencies:** [TASK-0013-intraday-deviation-correction]

## Goal
`AUDIT-0007-aggregation` found a Test-Coverage GAP:
`TestBlendingConvergesToRampingSteadyState` proves Ramping and Blending
**converge** to the identical value once `w_blend` reaches `1` — a real
and valuable regression guard, but it's the one point in the ramp where
the two modes are *supposed* to agree, not where they differ. No test
computes both modes' outputs at a **partial** ramp weight (e.g. `w=0.3`,
immediately after a provider update) and asserts they diverge — which
they structurally must: Ramping's `new_value *
intraday_correction_factor(..., ramp_weight=0.3, ...)` ignores any prior
value entirely, while Blending's `crossfade(old_prediction, new_prediction,
0.3)` is still mostly `old_prediction`. A regression that accidentally
made `coordinator.py` call `crossfade` even under Ramping mode (or
vice-versa) would not be caught by any existing test.

## Known Decisions
- This is a pure, additive test in `tests/test_aggregation_intraday.py`
  — no production code change.
- The audit's own recommended shape ("same shape as the existing
  convergence test, but asserting `!=` at e.g. `ramp_weight=0.3` instead
  of `==` at `w=1`, using data already set up in the existing convergence
  test") is sufficient specification — no new design needed.

## Open Questions for Execution
- None expected.

## Acceptance Criteria
- Given `tests/test_aggregation_intraday.py`, When run after this task,
  Then it contains a new test (e.g.
  `TestRampingVsBlendingDivergeMidRamp`) that computes both Ramping's
  and Blending's outputs from the same old/new prediction pair at a
  partial ramp weight (not `0` or `ramp_slots`) and asserts they are
  numerically different — reusing the existing
  `TestBlendingConvergesToRampingSteadyState` fixture's setup where
  practical, for consistency with the existing convergence test.
- Given the existing `TestBlendingConvergesToRampingSteadyState` test,
  When run after this task, Then it is unchanged — this task adds a
  sibling test, it does not modify the convergence proof.
- Given the full test suite, When run after this task, Then all
  pre-existing tests still pass unmodified, plus the new addition.

## Estimated File / Module Footprint (hint, not a commitment)
- `tests/test_aggregation_intraday.py` only. No production `.py` file.

## Definition of Done
- Tests green · docs updated (none needed — test-only) · no open ADR
  conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/aggregation.py` → `ramp_weight`,
  `intraday_correction_factor`, `crossfade` — (→ task:
  TASK-0013-intraday-deviation-correction) — the three functions the new
  test exercises.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
