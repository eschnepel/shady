# Task: CodeQL Branch-Target Fix

- **Status:** todo
- **Related ADRs:** [ADR-000]
- **Dependencies:** []

## Goal
`AUDIT-0012-tooling-release-config` found a live, confirmed Test-Coverage
FAIL: `.github/workflows/codeql.yml`'s `push`/`pull_request` triggers
both target `branches: ["main"]`, but this repository's actual default
branch — confirmed directly against the remote via `git ls-remote
--symref origin HEAD` → `ref: refs/heads/master` — is `master`. No
`main` branch exists anywhere in the remote's branch list (`master`,
`initial_code`, `initialcode` only). Because both triggers target a
branch that does not exist, **CodeQL never runs on an actual push or
pull request** — only via its own weekly cron
(`schedule: - cron: "3 0 * * 6"`), meaning a vulnerable pattern could
merge and go undetected for up to a week, never gated in front of a
merge the way `code_checker.yml`'s per-push/PR triggers are. This is the
highest-weighted finding across all twelve audits: a security-scanning
gate has been silently non-functional for every push/PR in this
project's history.

## Known Decisions
- The fix is a one-line-per-trigger branch-name correction — there is
  no code behavior at stake, and the audit's own recommendation
  (`branches: ["master"]`) is the obviously correct default absent a
  reason to prefer something else.
- This is not blocked on any other task — it is fully independent of
  every other TASK-0021–0033 remediation item.

## Open Questions for Execution
- **Primary choice, low-stakes but the human should still confirm
  rather than have it assumed:** should the fix be (a) change
  `branches: ["main"]` to `branches: ["master"]` in both triggers, or
  (b) drop the branch filter entirely so CodeQL runs on every branch's
  push/PR, or (c) treat this as a signal that the repo's default branch
  should finally be renamed to `main` (a GitHub-side rename, not a
  workflow-file edit) to match the increasingly common convention,
  updating the workflow to match afterward? Options (a) and (b) are
  both small, low-risk workflow-file-only changes; option (c) is a
  repo-configuration change outside this task's normal file footprint
  and would need to be confirmed as in-scope before a worker touches
  anything beyond the YAML file. **Default to (a) if the human has no
  preference** — it's the minimal, lowest-risk fix and matches what the
  audit itself recommended.

## Acceptance Criteria
- Given `.github/workflows/codeql.yml`, When read after this task,
  Then both the `push` and `pull_request` triggers' `branches:` list
  target the repository's actual default branch (per the human's
  chosen option above), or the branch filter is removed entirely if
  option (b) was chosen.
- Given a fresh clone of the repository after this task, When
  `git ls-remote --symref origin HEAD` and `codeql.yml`'s trigger
  branches are compared, Then they agree (or, for option (b), no
  comparison is needed since no filter exists).
- Given the weekly `schedule` trigger, When this task is done, Then it
  remains unchanged — this task fixes the push/PR triggers only, the
  cron schedule was never broken.
- Given the full test suite, When run after this task, Then it is
  unchanged (this task touches no `.py`/test file).

## Estimated File / Module Footprint (hint, not a commitment)
- `.github/workflows/codeql.yml` only.

## Definition of Done
- Tests green (unchanged — no test file touched) · docs updated (none
  needed — this is not an ADR-governed file) · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `.github/workflows/codeql.yml` (repo root, `.github/workflows/`) —
  no prior task delivered this file as a tracked artifact; it predates
  the task-based workflow (same category as `code_checker.yml`,
  `.pre-commit-config.yaml`).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
