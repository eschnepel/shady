# Audit Task Index — Post-Implementation ADR Conformance Review

**Status of this phase:** Planning only. **No audit has been executed yet.**
This index and the `tasks/AUDIT-XXXX-*.md` files it lists are the output of
a grouping/planning pass over the already-`done` implementation in
`tasks/INDEX.md`. Do not treat any finding, PASS, or FAIL as having
occurred until a task's `Status` field is moved past `todo`.

## Why this phase exists

All 20 implementation tasks in `tasks/INDEX.md` are `done`. Every one of
them was reviewed individually at the time it was built (Phase 4b, one
diff at a time, against its own Task.md and its own Related ADRs). This
phase is different in kind: it re-examines the **finished, integrated**
codebase artifact-by-artifact against the **full** ADR text (not just the
slice a single task's reviewer saw), and separately asks whether the test
suite actually pins down each ADR clause, rather than only whether tests
happen to pass.

Two systematic risks this catches that per-task review structurally
cannot:
- **Drift across patches.** Several modules (`coordinator.py`,
  `diagnostics/base.py`, `regression/base.py`) were extended by 3–5 patch
  tasks each (see `tasks/INDEX.md` refinement log). Each patch was
  reviewed against its own narrow diff; nothing has yet reviewed the
  *accumulated* result against the ADR as a whole.
- **Coverage vs. passing.** A test suite can be 100% green while an ADR
  clause has no test that would actually fail if that clause's behavior
  regressed (e.g. a default value that's never asserted, an edge case
  described in prose but never constructed in a fixture).

## Grouping rationale

Groups follow the project's own module-boundary description in
`tasks/adr-summary.md` §2 (the `providers/ → yield_correction.py →
regression/ → forecast_adjust.py → string_computation.py →
aggregation.py → diagnostics/ → cache.py → coordinator.py → sensor.py/
config_flow.py/select.py/button.py → __init__.py` dependency chain),
not by implementation-task history. Tightly coupled single-file modules
(`yield_correction.py` + `forecast_adjust.py`, which call back into each
other) are combined; large single-file modules with substantial
independent ADR footprint (`cache.py`, `coordinator.py`) get their own
task despite being one file each.

| # | Group | Primary files |
|---|---|---|
| 1 | Provider Package | `providers/*.py` |
| 2 | Regression Package | `regression/*.py` |
| 3 | Cache Module | `cache.py` |
| 4 | Yield & Forecast Corrections | `yield_correction.py`, `forecast_adjust.py` |
| 5 | Coordinator | `coordinator.py` |
| 6 | String Computation Module | `string_computation.py` |
| 7 | Aggregation Module | `aggregation.py` |
| 8 | Diagnostics Package | `diagnostics/*.py` |
| 9 | HA Entity Layer | `sensor.py`, `button.py`, `select.py` |
| 10 | Config Flow & Translations | `config_flow.py`, `const.py`, `translations/*.json` |
| 11 | Integration Setup & Wiring | `__init__.py`, `services.yaml`, `manifest.json` |
| 12 | Tooling & Release Configuration | `pyproject.toml`, `mypy.ini`, `hacs.json`, `pytest.ini`, `.github/workflows/*`, `README.md`, `docs/architecture.mmd` |

This is a partition of every file under `custom_components/shady/`, every
file under `tests/`, and every ADR-relevant repo-root/tooling file — no
file belongs to two groups, and every group maps to at least one ADR.

## Audit Task Table

| Slug | Title | Status | ADRs in scope | Auditor |
|------|-------|--------|----------------|--------|
| AUDIT-0001-provider-package | Provider Package | review | ADR-009, ADR-012 §1/§1a, ADR-003b §1a | Lead Agent (inline) — PASS w/ 1 PARTIAL flagged for human |
| AUDIT-0002-regression-package | Regression Package | review | ADR-001 §2/§2a/§3/§3a, ADR-008 §1, ADR-011, ADR-000 §4 | Lead Agent (inline) — PASS, 1 real coverage gap noted |
| AUDIT-0003-cache-module | Cache Module | review | ADR-007, ADR-007a, ADR-008 §2/§3 | Lead Agent (inline) — **1 FAIL**: model cache lives in coordinator.py, not cache.py |
| AUDIT-0004-yield-forecast-corrections | Yield & Forecast Corrections | review | ADR-003a, ADR-003b, ADR-001 §2, ADR-006 §1b | Lead Agent (inline) — clean PASS, best-tested pair so far |
| AUDIT-0005-coordinator | Coordinator | review | ADR-002, ADR-012 §4, ADR-000 §5, ADR-001 §4a, ADR-003c, ADR-006 | Lead Agent (inline) — PASS, no behavioral FAIL; 2 ADR-text-staleness items flagged for human decision, 1 minor coverage gap noted |
| AUDIT-0006-string-computation | String Computation Module | review | ADR-014, ADR-000 §3/§5/§6 | Lead Agent (inline) — **1 FAIL**: module's own docstring falsely claims `coordinator.py` calls `predict_string_forecast` (it never does); 1 minor coverage gap noted; all 14 tests re-run live, 14/14 pass |
| AUDIT-0007-aggregation | Aggregation Module | review | ADR-005, ADR-006 | Lead Agent (inline) — 13/13 criteria PASS; **1 FAIL found outside checklist**: ADR-005 + ADR-000 §3 both claim a stale `aggregation --> forecast_adjust` edge that doesn't exist in code; 1 coverage gap (Ramping vs. Blending mid-ramp divergence untested); 19/19 tests re-run live |
| AUDIT-0008-diagnostics-package | Diagnostics Package | review | ADR-004, ADR-012 §1, ADR-013 §1, ADR-014, ADR-000 §3/§6 | Lead Agent (inline) — clean PASS, 10/10 criteria, 4/4 coverage; no FAIL, no gap; supersession check on TASK-0015a-patch-1 triply corroborated |
| AUDIT-0009-entity-layer | HA Entity Layer (sensor/button/select) | todo | ADR-000 §3, ADR-002 §3/§5, ADR-004 §2/§2a/§2b, ADR-005, ADR-006 | — |
| AUDIT-0010-config-flow-translations | Config Flow & Translations | todo | ADR-010, ADR-001 §1/§4a, ADR-009 §3 | — |
| AUDIT-0011-integration-setup | Integration Setup & Wiring | todo | ADR-002 §1a/§5, ADR-000 | — |
| AUDIT-0012-tooling-release-config | Tooling & Release Configuration | todo | ADR-000 §1/§2/§4/§7 | — |

No cross-group dependencies are declared: every group audits code that is
already `done`, so groups 1–12 can run in parallel, in any order, or be
assigned to different auditors simultaneously. (Contrast with `tasks/
INDEX.md`, where dependencies gate *implementation* order — that
constraint doesn't apply to read-only review of finished code.)

## The Auditor role

A new role, distinct from Worker and Reviewer:

| Role | Context | Responsibility |
|---|---|---|
| **Auditor Sub-Agent** | 1 audit task + its ADRs (full text) + its source files + its test files + `tasks/adr-summary.md` + `tasks/DEPENDENCIES.md` | Determine, with file:line evidence, whether shipped code matches ADR intent and whether the test suite would catch a regression of each ADR clause. Produces a findings report. **Makes no code changes.** |

Auditor instruction, referenced by every `AUDIT-XXXX-*.md` file below
rather than repeated in each:

```
You audit exclusively the attached AUDIT-XXXX-*.md task's declared scope.

For every item under "Audit Criteria":
- Read the cited ADR section in full (not just the one-line summary in
  adr-summary.md).
- Locate the implementing code in the listed source files.
- Mark PASS (behavior matches the ADR, cite file:line), FAIL (behavior
  contradicts or omits the ADR, cite file:line and quote the ADR
  requirement), or PARTIAL (matches in the common case, diverges in an
  edge case — describe the edge case).

For every item under "Test-Coverage Criteria":
- Locate the test(s) that would need to fail if this ADR clause's
  behavior regressed.
- Mark COVERED (name the test class/function) or GAP (no such test
  exists, or the existing test would pass even under a regression —
  explain why).

Do not modify any source file, test file, or ADR. Do not mark a task
`done` — audits close with `Status: review`, pending human read of the
findings. If you find a FAIL or a GAP, do not fix it inline: note it as
a candidate follow-up (new task or Scenario-C patch task per the main
orchestration prompt) in the findings report and let the Lead Agent
decide whether/how to schedule it.

If an ADR section is ambiguous about what correct behavior even is,
do not resolve the ambiguity yourself — report it the same way Phase 0
handles ADR contradictions: as a question for the human, not a guess.

Write your findings to `tasks/AUDIT-XXXX-<slug>-findings.md` (same slug
as your task file) and fill in the task's own "Delivered Artifacts"
block with that path.
```

## Refinement Log

| Date | Trigger | Action | Reason |
|------|---------|--------|--------|
| 2026-09-06 | Lead Agent | Created AUDIT-0001..AUDIT-0012 and this index | Human requested a post-implementation grouping + ADR/test-coverage audit pass over the completed `tasks/INDEX.md` build, without executing it yet |
| 2026-09-06 | AUDIT-0001 | Executed; Status → `review`; findings written | Human requested strictly-sequential execution of the audit tasks, one zip per task |
| 2026-09-06 | AUDIT-0002 | Executed; Status → `review`; findings written | Same |
| 2026-09-06 | AUDIT-0003 | Executed; Status → `review`; findings written; **1 FAIL found** (model cache location vs. ADR-007 §1/ADR-007a §5) | Same |
| 2026-09-06 | AUDIT-0004 | Executed; Status → `review`; findings written; clean PASS, 1 minor coverage gap noted | Same |
| 2026-09-06 | AUDIT-0005 | Executed; Status → `review`; findings written; no behavioral FAIL; **2 ADR-text-staleness items flagged** (ADR-002 §5's "two registrations" Con vs. actual single merged listener; ADR-014 §4's "all four methods delegate" claim vs. `_predict_day_basis`/`_clamp_basis`'s justified exception); 1 minor coverage gap (absence of a second `strings()`-bypassing enumeration path is untested) | Human requested strictly-sequential execution of the remaining audit tasks (5–8), one zip per task |
| 2026-09-06 | AUDIT-0006 | Executed; Status → `review`; findings written; **1 FAIL**: `string_computation.py`'s own docstring and `predict_string_forecast`'s docstring falsely claim `coordinator.py`'s no-intraday-correction path calls it — confirmed via `grep` that it never does (same underlying fact as AUDIT-0005's finding B, now pinned to the audited file itself); 1 minor coverage gap noted; all 14 existing tests re-run live during the audit, 14/14 passed | Same |
| 2026-09-06 | AUDIT-0007 | Executed; Status → `review`; findings written; 13/13 checklist criteria PASS; **1 FAIL found outside the checklist**: both ADR-005's module diagram and ADR-000 §3's canonical module graph claim a stale `aggregation --> forecast_adjust` edge that doesn't exist in code (confirmed via `grep` — zero non-stdlib imports in `aggregation.py`); 1 coverage gap (Ramping vs. Blending mid-ramp divergence is never asserted, only their `w=1` convergence); both test files re-installed pytest and re-run live, 19/19 passed | Same |
| 2026-09-06 | AUDIT-0008 | Executed; Status → `review`; findings written; 10/10 criteria PASS, 4/4 coverage criteria COVERED — no FAIL, no gap, the cleanest of the four audits run this session. Required `TASK-0015a-patch-1` supersession check triply corroborated (task file header + ADR-004 §5 second Amendment + independent `grep`/code inspection all agree). `test_diagnostics_base.py` re-run live, 22/22 passed; `test_diagnostics_compare_regressions.py` requires real `homeassistant` (not installed in sandbox), verified by manual reading instead. One tooling aside noted for AUDIT-0012 (mypy.ini `python_version` quoting bug) | Same |

## Session pause note (2026-09-06)

AUDIT-0001 through AUDIT-0008 executed and closed out this session
(0001–0004 in an earlier pass; 0005–0008 run strictly sequentially per
explicit human request, one zip per task). AUDIT-0009 (Config Flow &
Options Flow) through AUDIT-0012 (Tooling & Release Config) remain
`todo`. Continue strictly sequentially from AUDIT-0009 in a future
session — the same process each prior audit followed: read the task's
Related ADRs in full, read its Scope source/test files, fill in the
Audit/Test-Coverage Criteria tables with file:line evidence, write
`tasks/AUDIT-000N-<slug>-findings.md`, flip Status to `review`, update
this index's table and refinement log, zip, present.

**Open items carried forward for whoever resumes:**
- AUDIT-0003's FAIL (fitted-model cache lives in `coordinator.py`, not
  `cache.py`) is still awaiting a human decision — amend ADR-007 §1 /
  ADR-007a §5, or schedule a relocation patch task. Not yet resolved.
- AUDIT-0001's PARTIAL (ADR-009 §1 sunshine-duration "rescaling" wording
  vs. unscaled actual behavior) is likewise still awaiting a human
  decision.
- AUDIT-0005's two ADR-text-staleness items (ADR-002 §5's "two
  registrations" Con vs. the actual single merged provider listener;
  ADR-014 §4's "all four methods delegate to `string_computation.py`"
  claim vs. `_predict_day_basis`/`_clamp_basis`'s justified but
  ADR-undocumented exception) are likewise awaiting a human decision on
  whether/how to amend ADR-002 and ADR-014.
- AUDIT-0006's FAIL (`string_computation.py`'s own docstring and
  `predict_string_forecast`'s docstring falsely claim `coordinator.py`'s
  no-intraday-correction path calls it) is the same underlying fact as
  the ADR-014 §4 item above, viewed from the module's own
  self-description — both should be corrected together.
- AUDIT-0007's FAIL (both ADR-005's module diagram and ADR-000 §3's
  canonical module graph claim a stale `aggregation --> forecast_adjust`
  edge that doesn't exist in code) needs an ADR-diagram correction —
  no code change needed.
- AUDIT-0008 was the one clean pass this session — no FAIL, no
  coverage gap. Nothing carried forward from it except the incidental
  `mypy.ini` `python_version = "3.14"` quoting bug noted for AUDIT-0012.
- Six ADR-text/diagram corrections are now queued across AUDIT-0005
  through AUDIT-0007's findings; the human may want to batch them into
  one amendment pass across ADR-002, ADR-005, ADR-000, and ADR-014
  rather than four separate edits, since several describe the same
  underlying fact from different angles.
- AUDIT-0012 (Tooling & Release Config) now has two small incidental
  items waiting for it: the `mypy.ini` quoting bug above, plus whatever
  else that audit's own checklist covers.

## Next steps (not executed)

1. Human reviews this grouping and the 12 task files for completeness —
   equivalent to a Gate before any auditor runs.
2. Once approved, each `AUDIT-XXXX-*.md`'s Status moves `todo` →
   `in-progress` as an auditor is assigned; findings land in
   `tasks/AUDIT-XXXX-<slug>-findings.md`; Status moves to `review`.
3. Any FAIL/GAP found becomes a candidate new task or Scenario-C patch
   task against the relevant `TASK-00XX`, scheduled through the normal
   Phase 6 refinement process — **not** fixed silently during the audit.
