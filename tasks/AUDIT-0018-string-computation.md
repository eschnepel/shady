# Audit Task: String Computation Module (Round 2)

- **Status:** review
- **Group:** `custom_components/shady/string_computation.py`
- **Related ADRs:** [ADR-014, ADR-000 §3]
- **Source Tasks:** \[TASK-0017-string-computation-module,
  TASK-0027-module-diagram-and-docstring-accuracy\]

## Scope

Re-audits round 1's `AUDIT-0006-string-computation` FAIL (docstring false
claim). `string_computation.py` changed since round 1 (docstring-only diff per
`git diff f7fcef8 HEAD -- custom_components/shady/string_computation.py` — no
logic lines touched), so this is a targeted re-check of exactly that diff plus a
fresh confirmation of the module's runtime behavior.

## Findings — Code Logic vs. ADRs

- **Round-1 item — `predict_string_forecast` caller claim (RESOLVED, verified
  against live code, not just the diff).** `AUDIT-0006` found the module
  docstring claiming `predict_string_forecast` is called by "the coordinator's
  no-intraday-data code path," when no such call exists anywhere in
  `coordinator.py`. `TASK-0027`'s fix (visible in the diff — the docstring now
  says the function's *"only real caller today is
  `diagnostics/compare_regressions.py`"* and that `coordinator.py`'s own
  reference to it is a comment, not a call) is independently re-verified this
  round via a direct `grep -rn "predict_string_forecast"` across the entire
  `custom_components/shady/` tree: the only executable call site is
  `diagnostics/compare_regressions.py:396`
  (`string_computation.predict_string_forecast(...)`); `coordinator.py`'s sole
  mention (line 1075) is inside a docstring/comment, not a call. **PASS — the
  fixed claim is accurate, not just differently wrong.**
- No other deviations found. `orchestrate_fit`/`orchestrate_predict`'s
  delegation shape (impure boundary calls out, then delegates to
  `_fit_string`/`_predict_day_basis`/`_clamp_basis` per ADR-014 §4's carve-out)
  matches round 1's confirmed reading.

## Findings — Test Coverage vs. ADRs

- `tests/test_string_computation.py` re-run live this session: 14/14 passing
  (isolated run), consistent with round 1's count — no regression, no new gap
  introduced by the docstring-only change (expected, since no logic changed).
- Round 1 recorded this group as clean with no material coverage gap beyond what
  round 1 itself already closed via its own remediation weighting; no new gap
  found this round.

## Open Questions

None.

## Definition of Done (for Phase 8)

- N/A — no unresolved finding in this group this round.

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8 — not applicable, no fix scheduled. -->

- No Phase 8 task required for this group.
