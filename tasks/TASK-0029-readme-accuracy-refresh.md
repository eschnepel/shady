# Task: README Accuracy Refresh

- **Status:** todo
- **Related ADRs:** [ADR-000]
- **Dependencies:** [TASK-0016-integration-setup-entry, TASK-0018-hacs-select-rename-cleanup]

## Goal
`AUDIT-0012-tooling-release-config` found a FAIL against ADR-000 §7:
`README.md`'s "Core idea" section (points 1–8, roughly 60 lines) is a
detailed technical restatement of decision content that already lives in
ADR-001 (regression method/default), ADR-011 (smoothing radius, neighbor
exclusion), ADR-003a/003b (clipping, temperature derating), ADR-004/
ADR-013 (diagnostic mode, the `shady.select_diagnostic_slot` service),
ADR-005 (aggregate sensors), and ADR-006 (ramping/blending) — specific
numeric defaults and edge-case behavior duplicated in prose, not a
pointer. This is exactly the drift risk ADR-000 §7 exists to prevent: a
default changing in an ADR (e.g. the "25% (configurable)" neighbor-
exclusion cutoff) would need updating in two places with nothing
enforcing they stay in sync.

Separately, and more urgently visible: `README.md`'s own **Status** line
reads "Brainstorming / Concept phase" — flatly false for a codebase with
20/20 implementation tasks `done`, 419 tests passing, and (as of this
audit series) 12 audits complete. A reader landing on this README today
would reasonably conclude the project has no working code yet.

## Known Decisions
- The Status line fix is unambiguous — it must reflect the project's
  actual, current state (implementation complete, audit/remediation
  phase in progress) rather than "Brainstorming / Concept phase."
- The "Core idea" section should shrink to a short summary plus explicit
  pointers to the ADRs it currently duplicates (ADR-001, ADR-003a,
  ADR-003b, ADR-004, ADR-005, ADR-006, ADR-011) — matching the "high-
  level pointer, not a decision-rationale duplicate" standard ADR-000
  §7 itself states, and matching how this README's other sections
  (outside "Core idea") already behave, per the audit's framing.

## Open Questions for Execution
- **How much detail is "a short summary"?** The audit doesn't specify
  an exact target length, and trimming eight points of real technical
  content down to a pointer-level summary involves judgment about what's
  essential context for a first-time reader (e.g. a HACS user deciding
  whether to install this integration) versus what belongs only in the
  ADRs. If, while drafting, the worker is unsure whether a specific
  detail (e.g. a numeric default) is essential enough to keep inline vs.
  purely a duplicate to cut, err toward cutting and pointing to the ADR
  — but if a genuinely close call comes up, note it here rather than
  guessing silently.
- **Exact new Status wording** is not specified by the audit beyond
  "should reflect the project's actual, largely-complete state" — a
  reasonable default is something like "Implementation complete (20/20
  tasks done); post-implementation ADR-conformance audit in progress"
  but the worker should not invent project-status claims beyond what
  `tasks/INDEX.md`/`tasks/AUDIT-INDEX.md` actually state as of this
  task's execution — re-check both files' current state before writing
  the line, since more remediation tasks may have landed by then.

## Acceptance Criteria
- Given `README.md`'s Status line, When read after this task, Then it
  accurately reflects the project's state at the time this task is
  executed (re-checked against `tasks/INDEX.md`/`tasks/AUDIT-INDEX.md`,
  not copied verbatim from this task file's own Goal section, which may
  be stale by execution time).
- Given `README.md`'s "Core idea" section, When read after this task,
  Then it is a short summary (not a re-derivation of ADR decision
  content) with explicit pointers to ADR-001, ADR-003a, ADR-003b,
  ADR-004, ADR-005, ADR-006, and ADR-011 for the specific numeric
  defaults and edge-case behavior it no longer duplicates inline.
- Given the rest of `README.md` (installation, configuration, entity
  list, etc.), When read after this task, Then it is unchanged except
  where it already needed a switch→select correction handled by
  `TASK-0026`/`TASK-0018` — this task does not re-touch content outside
  the Status line and "Core idea" section.
- Given the full test suite, When run after this task, Then it is
  unchanged (this task touches no `.py` file).

## Estimated File / Module Footprint (hint, not a commitment)
- `README.md` only.

## Definition of Done
- Tests green (unchanged) · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, including a
  before/after line-count for the "Core idea" section so a reviewer can
  see the actual trim, not just take "shorter" on faith
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `tasks/INDEX.md`, `tasks/AUDIT-INDEX.md` → current task/audit
  completion state — the source of truth for the new Status line's
  wording, re-read at execution time, not assumed from this task file.
- `adr/001-empirical-shading-model.md`, `adr/003a-...md`,
  `adr/003b-...md`, `adr/004-...md`, `adr/005-...md`, `adr/006-...md`,
  `adr/011-...md` → the ADRs the trimmed "Core idea" section must point
  to instead of duplicating.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
