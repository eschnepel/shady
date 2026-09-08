# Task: Sunshine-Duration Rescaling — Decision & Fix

- **Status:** todo
- **Related ADRs:** [ADR-009]
- **Dependencies:** [TASK-0003-baseline-forecast-discovery]

## Goal
`AUDIT-0001-provider-package` found a PARTIAL: ADR-009 §1 states
sunshine-duration values are "used directly, only rescaled to the
baseline's expected numeric range." The shipped code does not rescale
this value at all — `normalize_candidate_series`'s `"weather_sunshine"`
branch calls `resolve_list_series(raw, value_key_hint=SUNSHINE_DURATION_KEY)`
with no scaling step, unlike the neighboring `"weather_cloud"` branch
two lines below it, which explicitly calls `invert_cloud_coverage`. A
test (`tests/test_providers_normalize.py::test_weather_sunshine_shape_not_inverted`)
confirms this is deliberate current behavior, not an oversight — but no
ADR amendment records it as a deliberate simplification.

The audit itself notes this may not be a bug: since ADR-001's regression
is an empirical fit of `PV` against whatever numeric range `FC` happens
to be in, a linear/wls2/wls3/kernel model absorbs an arbitrary linear
scale automatically, so an un-rescaled sunshine-duration value may
produce an equally-good fit — just with different (still valid)
regression coefficients. This is exactly the kind of judgment call the
golden rule reserves for a human, not a worker.

## Known Decisions
- The current code's behavior is stable and tested — this is not an
  emergency fix; there is no reported forecast-quality complaint tied to
  this gap. The task exists to close the ADR-vs-code discrepancy the
  audit found, however it's resolved.
- Whichever path is chosen, `TASK-0003`'s own `Delivered Artifacts`
  block stays unedited — Option B (below) is a Scenario-C patch against
  it, not a reopening.

## Open Questions for Execution
**This task cannot start implementation until the human picks one of
the following two paths.**

- **Option A — Amend ADR-009 §1 to drop the rescale claim.** Record the
  rationale already sketched above (regression model absorbs an
  arbitrary linear scale) as the amendment's reasoning. No code change.
- **Option B — Add the missing rescale step.** Implement an actual
  rescale in `normalize_candidate_series`'s `"weather_sunshine"` branch,
  matching whatever numeric range ADR-009 §1 intends by "the baseline's
  expected numeric range" — **this sub-question is itself open and
  needs the human's answer if Option B is chosen**: rescale to what
  range, and by what method (e.g. min-max to `[0, FC_typical_max]`,
  or a fixed known sunshine-duration-to-power heuristic)? ADR-009 §1's
  current text does not specify a formula, only that scaling should
  happen — a worker must not invent one.
- A third, hybrid possibility worth naming even though not explicitly
  offered by the audit: keep the code unscaled (matches today's tested
  behavior, zero regression risk) but strengthen ADR-009 §1's wording
  from "only rescaled" to something conditionally correct if a future
  provider genuinely needs it — the human may prefer this framing over
  a flat "drop the claim." Surface this as a third option if the human
  seems undecided between A and B.

## Decision
Proceed with Option A.

## Acceptance Criteria
- Given the human's decision recorded in this task's own `Open
  Questions` section, When implementation begins, Then the worker
  proceeds only along the recorded path.
- **Option A only:** Given `adr/009-baseline-forecast-sourcing.md`, When
  read after this task, Then it carries a new, dated Amendment block
  removing or qualifying the "only rescaled" claim with the recorded
  rationale, and `tasks/adr-summary.md` is updated to match. No `.py`
  file changes; full test suite unchanged (unmodified pass count).
- **Option B only:** Given `providers/normalize.py`'s
  `normalize_candidate_series`, When called with a `"weather_sunshine"`
  candidate, Then the returned series is rescaled per the human-specified
  formula (not invented by the worker), and
  `tests/test_providers_normalize.py::test_weather_sunshine_shape_not_inverted`
  is either updated to assert the new scaled behavior (if its old
  assertion becomes false) or a new sibling test is added — the old
  test's name/intent (proving the shape is *not inverted*, as opposed
  to *not scaled*) should be preserved distinctly from any new
  scaling-specific test.

## Estimated File / Module Footprint (hint, not a commitment)
- **Option A:** `adr/009-baseline-forecast-sourcing.md`,
  `tasks/adr-summary.md` — no `.py` file.
- **Option B:** `custom_components/shady/providers/normalize.py`,
  `tests/test_providers_normalize.py`.

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, stating which
  option was chosen and, for Option B, the exact rescale formula used
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/providers/normalize.py` →
  `normalize_candidate_series`, `resolve_list_series`,
  `invert_cloud_coverage` — (→ task: TASK-0003) — the exact function and
  its neighboring `"weather_cloud"` branch Option B must mirror the
  style of, if chosen.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
