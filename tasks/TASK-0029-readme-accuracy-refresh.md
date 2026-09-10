# Task: README Accuracy Refresh

- **Status:** done
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
- **Scope deviation from this task's own Acceptance Criteria — recorded
  explicitly, not silently:** the human redirected scope mid-task, past
  what this task file's own third Acceptance Criterion allows ("the rest
  of `README.md`... unchanged... this task does not re-touch content
  outside the Status line and 'Core idea' section"). The human's
  instruction: "The Readme should be rewritten anyway to match the
  target audience (HomeAssistant Users)... Also important is the
  relation to the Effy project." Per this project's own golden rule
  (human decisions govern; the Lead Agent's job is to execute them
  accurately, not to hold a pre-written task file's narrower criteria
  against an explicit, better-informed instruction that supersedes it),
  the full file was rewritten, not just the two sections originally
  scoped. A **chat-local proposal draft** was produced and reviewed
  first, specifically because the scope had grown past a mechanical
  trim into real content/tone decisions worth a human pass before
  touching the repo — the human then rewrote the "Relationship to Effy"
  and "Requirements" sections themselves in that review round (revealing
  a real fact the Lead Agent could not have sourced independently: Effy
  is a battery-management-system integration, and its per-string output
  sensors are a valid literal input source for Shady, not just a
  shared-conventions sibling as the Lead Agent had initially guessed
  from ADR text alone), and the Lead Agent proof-read/polished that
  wording (fixed a typo, an adverb, doubled-nested parentheses, hyphen/
  em-dash inconsistency, and verified one technical claim — HA's
  short-term-statistics 10-day purge being a separate, currently
  non-configurable mechanism from `purge_keep_days` — against a live
  web search before asserting it, per this project's "verify, don't
  invent" standard) before it was folded into the final file.
- **Still fully satisfied, from the original Acceptance Criteria:**
  Status line is accurate, re-checked against `tasks/INDEX.md` at
  execution time (not copied from this task file's own Goal section,
  which was already stale by the time this task ran — 9/13 remediation
  tasks were done by then, not 0): "Implementation complete (20/20 core
  tasks); post-implementation ADR-conformance audit and remediation in
  progress (9/13 remediation tasks done)." The old "Core idea" section's
  duplicated-ADR-content problem is fully resolved — its successor
  content (retitled "Why this exists" + "How it works, in plain terms",
  since the full rewrite restructured section boundaries) is a short,
  plain-language summary with no ADR-derived numeric defaults or
  edge-case specifics duplicated inline (the 25% neighbor-exclusion
  cutoff, 28-day window default, 12-slot ramp duration, and similar
  specifics are gone from the main flow — described qualitatively
  instead, e.g. "a rolling recent window (a few weeks by default)").
  Before/after line count for that section: **84 lines → 40 lines**
  (`git show HEAD~1:README.md`'s old `## Core idea` section through its
  next `## ` heading vs. the new file's `## How it works, in plain
  terms` section span). Full test suite unchanged, confirmed by re-run
  (touches no `.py` file).
- **Explicit ADR pointers:** kept, but relocated to a new "For
  contributors" section at the end rather than inline after "Core idea"
  — `adr/INDEX.md`, `adr/000-coding-standards.md`, and
  `docs/architecture.mmd` (all three link targets verified to exist on
  disk before committing). Did **not** keep the original per-topic
  pointer list naming ADR-001/003a/003b/004/005/006/011 individually
  inline — the human's redirected brief was explicit that a HA-user
  audience "should not need to dive into the ADRs to get the intent of
  the project," so the rewritten body itself carries the necessary
  intent in plain language, and the ADR pointer is now a single,
  general "read here for the detailed rationale" doorway rather than a
  per-paragraph citation list — judged the better fit for the stated
  audience than preserving the original per-ADR mapping verbatim.
- **New content beyond the original scope** (all human-directed, not
  independently added): a "Requirements" section (recorder short-term-
  statistics history, the 10-day-purge-vs-training-window gotcha, an
  existing baseline forecast/weather integration), an "Installation
  (HACS)" section, a "Configuration" section describing the actual
  three-step config-flow shape (verified against
  `custom_components/shady/translations/en.json` and `hacs.json`
  directly, not assumed), and an "Entities created" section (verified
  against the actual class list in `sensor.py`/`select.py`/`button.py`
  — 8 sensor classes, 1 select, 1 button — described by behavior/count
  rather than by internal class name, appropriate for the audience).
- **Deliberately dropped:** the stale "Open questions for further
  brainstorming" section (one leftover item, "validate the smoothing-
  radius default against real data") — flagged to the human in the
  reviewed proposal as not fitting a user-facing README and suggested
  as a candidate for ADR-011 instead if still wanted; no objection or
  follow-up request came back in review, so it stays dropped, on record
  here rather than silently vanished.
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged.
- `git status --short` confirms exactly `README.md` changed (148
  insertions, 109 deletions — `git diff --stat`). Full test suite:
  445/445 passed, unchanged from the TASK-0023 baseline, as required for
  a docs-only change touching no `.py` file. `mypy --config-file
  mypy.ini custom_components/ tests/` clean on 53 source files. `ruff
  check .` clean repo-wide. `ruff format --check .` shows only the one
  pre-existing, unrelated, already-documented drift file, untouched.
