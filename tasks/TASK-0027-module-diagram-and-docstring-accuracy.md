# Task: Module-Diagram & Docstring Call-Graph Accuracy

- **Status:** todo
- **Related ADRs:** [ADR-000, ADR-002, ADR-005, ADR-014]
- **Dependencies:** [TASK-0007-yield-corrections, TASK-0010-coordinator-recalibration-recompute-push, TASK-0017-string-computation-module]

## Goal
Five audits (`AUDIT-0005`, `AUDIT-0006`, `AUDIT-0007`, `AUDIT-0011`,
`AUDIT-0012`) each independently found the same category of issue: a
module diagram, an ADR's decision text, or a source file's own docstring
describes an earlier, already-superseded shape of the code rather than
its current, correct, already-reviewed behavior. None of these are
decisions — every one of them is "the description drifted, the behavior
didn't," and every audit explicitly recommended a text-only fix. This
task batches all five into one documentation-accuracy pass:

1. **ADR-005's and ADR-000 §3's module diagrams** both claim an
   `aggregation --> forecast_adjust` edge that does not exist in code
   (`aggregation.py` has zero imports beyond the standard library —
   the correction step happens upstream, in `coordinator.py`, before
   values ever reach `aggregation.py`'s sum functions).
2. **ADR-000 §3's diagram** draws `init --> entity_glue` (no real
   Python import behind that edge — platform forwarding is HA's own
   name-based mechanism) and omits the real `init --> coordinator`
   edge the code actually needs.
3. **ADR-002 §5 and its Consequences section** describe two independent
   listener registrations on the same baseline entity; the actual code
   registers exactly one, whose single handler does both the push and
   the conditional recompute dispatch — the opposite of what the
   Consequences text describes, and deliberately built/tested this way
   (`TestGenericProviderPushLoop.test_one_listener_per_forward_overriding_provider`).
4. **ADR-014 §4** claims "all four [coordinator] methods... delegate
   everything else to `string_computation.py`." Two of the four
   (`_predict_day_basis`/`_clamp_basis`) justifiably don't — they call
   `forecast_adjust.py` directly, because ADR-006 §1b's intraday
   correction must sit between the transform and clamp steps, a shape
   `predict_string_forecast`'s combined wrapper can't accommodate.
   `TASK-0017`'s own Acceptance Criteria already documents and justifies
   this exception; ADR-014 §4's Decision text does not.
5. **`string_computation.py`'s own module docstring and
   `predict_string_forecast`'s function docstring** make the same
   factually false claim from the source-file side: that
   `coordinator.py`'s "no intraday correction" path calls
   `predict_string_forecast`. It never does — both of `coordinator.py`'s
   paths (intraday on and off) call `reverse_transformed_forecast`/
   `clamp_output` directly; the only real caller of
   `predict_string_forecast` today is `diagnostics/compare_regressions.py`.
6. **ADR-000 §1** names a CI file, `ci.yml`, that doesn't exist (the
   real file is `code_checker.yml`) and states literal tool-invocation
   strings that don't match how `pre-commit`'s hooks actually invoke
   each tool (different flags/paths than what's documented). The
   *effect* ADR-000 §1 requires is genuinely delivered; the filename
   and invocation strings are stale.

## Known Decisions
- Every item above is a text/docstring correction with the correct
  target state already established by the audit that found it — no
  worker judgment call is needed on *what* the correct description is,
  only on matching each audit's own precise wording.
- No production code changes anywhere in this task. Item 5's fix touches
  a `.py` file, but only its docstrings — no logic, no test-visible
  behavior change.
- Items 3 and 4 are explicitly cross-referenced by their own audits as
  "should be resolved together" (`AUDIT-0005`'s finding B and
  `AUDIT-0006`'s FAIL describe the same underlying fact from two ends of
  the same call graph) — keep them in the same commit/review pass for
  that reason, not split further.

## Open Questions for Execution
- None expected for items 1, 2, 3, 5, and 6 — each audit already
  specifies the corrected text precisely enough to apply directly.
- **Item 4 has one open wording question:** ADR-014 §4 needs a new
  carve-out sentence for `_predict_day_basis`/`_clamp_basis`. `TASK-0017`'s
  own Acceptance Criteria already contains publishable-quality wording
  for this — the worker should reuse that wording (adapted from a task
  file's "Acceptance Criteria" register into an ADR's "Decision" register)
  rather than drafting new prose from scratch. If the exact phrasing
  needs a human's stylistic sign-off before landing in an Accepted ADR,
  flag the drafted paragraph here before committing.

## Acceptance Criteria
- Given ADR-005's module diagram and ADR-000 §3's canonical module
  graph, When read after this task, Then neither shows an
  `aggregation --> forecast_adjust` edge.
- Given ADR-000 §3's module diagram, When read after this task, Then it
  shows `init --> coordinator` and no longer implies `init -->
  entity_glue` is a real Python import edge (either remove it or
  annotate it as the non-import platform-forwarding relationship it
  actually is).
- Given ADR-002 §5 and its Consequences section, When read after this
  task, Then both describe the actual single merged provider listener
  (push + conditional recompute in one callback), not "two
  registrations."
- Given ADR-014 §4, When read after this task, Then its Decision text
  explicitly carves out `_predict_day_basis`/`_clamp_basis` with the
  intraday-ordering rationale, rather than claiming all four methods
  delegate uniformly.
- Given `string_computation.py`'s module docstring and
  `predict_string_forecast`'s function docstring, When read after this
  task, Then neither claims `coordinator.py`'s no-intraday-correction
  path calls `predict_string_forecast` — the accurate statement (both
  of `coordinator.py`'s paths call `forecast_adjust.py` directly; only
  `diagnostics/compare_regressions.py` calls `predict_string_forecast`)
  replaces it.
- Given ADR-000 §1, When read after this task, Then it names
  `code_checker.yml` (not `ci.yml`) and its Invocation column reflects
  that the three tools run indirectly through `pre-commit`'s hook
  definitions, not as direct top-level CI steps with the literal
  strings currently documented.
- Given `tasks/adr-summary.md`, When checked after this task, Then it
  is still accurate against every amended ADR above (update if any of
  the six corrections changes something `adr-summary.md` itself states).
- Given the full test suite, When run after this task, Then it is
  unchanged for items 1–4 and 6 (no `.py` file touched), and for item
  5, `tests/test_string_computation.py`'s existing 14 tests still pass
  unmodified (docstring-only change, no assertion depends on docstring
  content).

## Estimated File / Module Footprint (hint, not a commitment)
- `adr/005-aggregate-sum-and-integral-sensors.md`
- `adr/000-coding-standards.md` (§1 and §3)
- `adr/002-coordinator-update-strategy.md` (§5 and Consequences)
- `adr/014-string-computation-module.md` (§4)
- `custom_components/shady/string_computation.py` (docstrings only)
- `tasks/adr-summary.md`
- No test file.

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, itemized by which
  of the six findings each edit closes
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/aggregation.py` → confirmed zero non-stdlib
  imports — (→ task: TASK-0007-yield-corrections... actually
  TASK-0012/TASK-0013 deliver `aggregation.py`'s intraday functions;
  cite the file itself as the source of truth) — the evidence for
  finding 1.
- `custom_components/shady/coordinator.py` → `_register_provider_listeners`,
  `_predict_day_basis`, `_clamp_basis` — (→ task:
  TASK-0010-coordinator-recalibration-recompute-push) — the evidence
  for findings 2, 3, and 4.
- `custom_components/shady/string_computation.py` → module docstring,
  `predict_string_forecast` — (→ task: TASK-0017-string-computation-module)
  — the file finding 5 corrects.
- `custom_components/shady/__init__.py` → confirmed import list (`const`,
  `coordinator` only) — (→ task: TASK-0016-integration-setup-entry) —
  the evidence for finding 2's `init --> coordinator` edge.
- `.pre-commit-config.yaml`, `.github/workflows/code_checker.yml` —
  pre-existing tooling config — the evidence for finding 6.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
