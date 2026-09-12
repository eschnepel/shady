# Audit Task: Yield & Forecast Corrections (Round 2)

- **Status:** done
- **Group:** `custom_components/shady/yield_correction.py`,
  `custom_components/shady/forecast_adjust.py`
- **Related ADRs:** [ADR-003a, ADR-003b, ADR-001 §2, ADR-006 §1b, ADR-000 §3]
- **Source Tasks:** \[TASK-0007-yield-corrections,
  TASK-0007-patch-1-ndarray-typing, TASK-0008-forecast-adjustment,
  TASK-0030-regression-correction-coverage-additions\]

## Scope

Re-audits round 1's `AUDIT-0004-yield-forecast-corrections` (clean pass, one
minor coverage gap) and performs a fresh exhaustive trace of
`yield_ correction.py`'s real import graph against ADR-000 §3's diagram and
prose — this is the primary write-up for a discrepancy found while
cross-checking every node in that diagram (see `tasks/AUDIT-INDEX.md` §"What
round 2 actually did," step 4).

## Findings — Code Logic vs. ADRs

- **NEW FINDING — ADR-000 §3's diagram and prose misdescribe
  `yield_correction.py`'s real callers.** Two problems, same root cause:

  1. **False edge in the Mermaid diagram** (`adr/000-coding-standards.md:104`):
     `yield_correction --> providers`. This implies `yield_correction.py`
     imports something from `providers/`. It does not — `yield_correction.py`
     has **zero** internal (`from .` / `from ..` / `import .`) imports at all,
     confirmed via direct `grep` of the file. Nothing that imports
     `yield_correction.py` (`string_computation.py`, `coordinator.py`,
     `forecast_adjust.py`) is `providers/` either, so this edge does not
     correspond to any real relationship in either direction.
  1. **False edge and stale prose** (`adr/000-coding-standards.md:105` and
     `:133-134`): the diagram draws `regression --> yield_correction`, and the
     accompanying bullet states *"Used at two points in the pipeline...
     `regression/` calls it forward to prepare training data, and
     `forecast_adjust.py` calls back into it in reverse."* Neither half of
     "regression/ calls it forward" is true today: a `grep` across all five
     `regression/*.py` files shows none of them import `yield_correction.py`,
     and the reverse (`yield_correction.py` importing `regression/`) is also
     false per finding 1's own check. The actual current caller that prepares
     training data by calling into both `regression/` *and*
     `yield_correction.py` is `string_computation.py`
     (`string_computation.py:54-56`:
     `from .regression import kernel, linear, wls2, wls3`;
     `from .yield_correction import derate_actual_to_reference, exclude_clipped, uplift_ambient_to_cell`)
     — already correctly captured by the diagram's separate
     `string_computation --> yield_correction` and
     `string_computation --> regression` edges
     (`adr/000-coding- standards.md:107,109`), which are accurate and don't need
     to change. The "regression/ calls it forward" half of the prose is simply
     describing an architecture that predates `TASK-0017`'s
     `string_computation.py` extraction and was never updated — the same class
     of drift round 1's `AUDIT-0005`/`AUDIT-0006`/`AUDIT-0007` already found and
     `TASK-0027` partially fixed, but these two specific edges were not among
     the six findings `TASK-0027` addressed (confirmed against its own
     `Delivered Artifacts` block in
     `tasks/archived/TASK-0027-module-diagram-and- docstring-accuracy.md` —
     findings 1–6 there cover different edges).

  **The reverse edge that *is* real and correctly documented:**
  `forecast_adjust --> regression` (true: `forecast_adjust.py:45` imports
  `.regression.base`) and the dashed
  `forecast_adjust -.->|"reverse transform, ADR-003b §1b/§2"| yield_correction`
  edge (true: `forecast_adjust.py:46` imports `.yield_correction`) are both
  accurate and unaffected by this finding.

  **Proposed fix (single reasonable path, no Open Question):** delete the two
  false edges (`yield_correction --> providers`,
  `regression --> yield_correction`) from the diagram; rewrite the
  `yield_correction.py` bullet's "regression/ calls it forward to prepare
  training data" clause to name `string_computation.py` instead, matching the
  bullet's own already-correct forward reference to `forecast_adjust.py` calling
  back in reverse.

- No other deviations found. `apply_derate_to_prediction`/
  `derate_actual_to_reference`/`uplift_ambient_to_cell`/`exclude_clipped`
  (ADR-003a/ADR-003b) and `adjust_forecast`/`reverse_transformed_forecast`/
  `clamp_output` (ADR-001 §2, ADR-006 §1b) all match round 1's confirmed reading
  — both files unchanged at the byte level since round 1
  (`git diff --stat f7fcef8 HEAD` shows neither file in the changed set).

## Findings — Test Coverage vs. ADRs

- **Round-1 item — 4-strategy parametrization (RESOLVED).** `AUDIT-0004` found
  `tests/test_forecast_adjust.py` only exercised hand-built stub models, never a
  real `regression/` strategy end-to-end. `TASK-0030` added parametrized
  coverage — confirmed: `tests/test_forecast_adjust.py:59-63` loads all four
  real strategy modules into `ALL_STRATEGIES`, and line 273 parametrizes a test
  over them (`@pytest.mark.parametrize("strategy", ALL_STRATEGIES, ...)`).
  **PASS.**
- Both files' test suites re-run live this session as part of the full suite —
  passing.

## Open Questions

None — the diagram/prose fix above has exactly one reasonable resolution.

## Definition of Done (for Phase 8)

- `adr/000-coding-standards.md`'s §3 Mermaid diagram no longer contains the
  `yield_correction --> providers` or `regression --> yield_correction` edges
- The `yield_correction.py` bullet's prose names `string_computation.py`, not
  `regression/`, as the module that calls it forward to prepare training data
- `tasks/adr-summary.md` checked for the same stale claim and corrected if
  present
- Full test suite still green; no `.py` file expected to change (documentation-
  only fix)
- `Delivered Artifacts` block below completed and accurate

## Delivered Artifacts

- `adr/000-coding-standards.md` §3 Mermaid diagram — deleted the false
  `yield_correction --> providers` and `regression --> yield_correction` edges.
- `adr/000-coding-standards.md`'s `yield_correction.py` bullet — rewritten to
  name `string_computation.py`, not `regression/`, as the module that calls it
  forward to prepare training data; added "has no internal imports of its own"
  for clarity, matching the now-empty edge list pointing away from that node.
- **Scope note (discovered during implementation, not in the original
  finding):** deleting `yield_correction --> providers` left the `providers`
  node with zero edges in the diagram — but `coordinator.py`
  (`from .providers.base import Provider`, etc., line 169) and `config_flow.py`
  (part of the `entity_glue` node;
  `from .providers.discovery import BaselineCandidate, discover_baseline_candidates`,
  line 69) both really do import it at runtime (confirmed via `grep`, excluding
  one `TYPE_CHECKING`-only import in `coordinator.py` that doesn't count as a
  real edge, consistent with how the diagram already treats other
  `TYPE_CHECKING`-only relationships as dashed). Left uncorrected, the fix would
  have silently traded one inaccuracy (a false edge) for another (an orphaned
  node implying nothing imports `providers/`) as a direct side effect of this
  task's own edit — same file, same diagram, no separate decision needed. Added
  the two real edges: `coordinator --> providers` and
  `entity_glue --> providers`.
- `tasks/adr-summary.md` — checked and corrected the same stale claim ("Called
  forward (training prep) by `regression/` callers" → `string_computation.py`),
  per this task's own Definition of Done. Did not restructure the file's
  separate linear pipeline-order diagram (§2): that notation is an
  already-annotated simplification of the real import DAG (its own inline "--
  also reads X directly" footnotes acknowledge it isn't a literal 1:1 edge
  list), and the specific prose claim mirrored from ADR-000 is the one this
  task's DoD calls out — reworking the chain notation itself would be a
  separate, broader documentation task.
- No `.py` file changed; no external dependencies added.
- Full suite re-run after the change: 446/446 passed, `mypy --strict` clean (53
  files), `ruff check`/`ruff format --check` clean.
