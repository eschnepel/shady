# Audit Task: Tooling & Release Configuration (Round 2)

- **Status:** review
- **Group:** `pyproject.toml`, `mypy.ini`, `pytest.ini`, `hacs.json`,
  `.pre-commit-config.yaml`, `.github/workflows/*`, `README.md`,
  `docs/architecture.mmd`
- **Related ADRs:** [ADR-000 §1/§2/§4/§7, ADR-013 §2]
- **Source Tasks:** \[TASK-0020-tooling-and-release-config,
  TASK-0024-codeql-branch-target-fix,
  TASK-0025-tooling-config-hardening-round-3,
  TASK-0026-switch-select-rename-cleanup-round-3,
  TASK-0027-module-diagram-and-docstring-accuracy\]

## Scope

Re-audits round 1's `AUDIT-0012-tooling-release-config` (2 FAILs, 1 FAIL outside
checklist, 1 Test-Coverage FAIL, 2 acknowledged-not-scheduled coverage gaps) —
round 1's heaviest-finding group. Every FAIL below is re-verified this round by
actually running the tool in question live in this sandbox, not by re-reading
the fix task's claims.

## Findings — Code Logic vs. ADRs

- **Round-1 item 1 — `mypy.ini` invalid syntax (RESOLVED, live-verified).**
  `AUDIT-0012` found `python_version = "3.14"` (quoted) in `mypy.ini`, which
  `configparser`/`mypy`'s own ini-reader rejects as a version string in some
  mypy releases, silently degrading strict-mode checking rather than failing
  loudly. Current file has `python_version = 3.14` (unquoted). Live-verified
  this session:
  `python3 -m mypy --config-file mypy.ini custom_components/ tests/` →
  `Success: no issues found in 53 source files`, zero warnings about the config
  itself. **PASS.**
- **Round-1 item 2 — `docs/architecture.mmd` stale `switch` diagram (RESOLVED,
  live-verified).** Re-read the full current file this session: it shows a
  `SELECT` node for the diagnostic-mode selector, no `SWITCH` node anywhere.
  **PASS.**
- **Round-1 item 3 (outside checklist) — duplicate pytest configuration
  (RESOLVED, live-verified).** `AUDIT-0012` found both `pytest.ini` and a
  `[tool.pytest.ini_options]` block in `pyproject.toml`, an ambiguous
  dual-source-of-truth pytest respects unpredictably depending on invocation
  directory. Current `pyproject.toml` has no `[tool.pytest.ini_options]` section
  (`grep -n "tool.pytest" pyproject.toml` — no match); `pytest.ini` is the sole
  config. Live-verified: `python3 -m pytest -q` from the repo root this session
  ran cleanly against `pytest.ini`'s settings (445/445 passed, no config-source
  warnings). **PASS.**
- No other deviations found in `.pre-commit-config.yaml` or `hacs.json`'s
  structure (ADR-000 §1/§7).
- **NEW FINDING — `README.md`'s own Status line is stale.** The README's
  top-of-file status line currently reads: *"Status: Implementation complete
  (20/20 core tasks); post-implementation ADR-conformance audit and remediation
  in progress (9/13 remediation tasks done)."* This was accurate mid-remediation
  but was never updated after the remediation batch actually finished —
  `tasks/archived/INDEX.md`'s own refinement log and
  `tasks/ archived/AUDIT-REMEDIATION-INDEX.md` both confirm all 13 remediation
  tasks (`TASK-0021` through `TASK-0033`) reached `done`, closed 2026-09-10. The
  README was never touched again after that point (not in the post-round-1
  changed-file diff at all), so it still shows the in-progress count. **Proposed
  fix (single reasonable path):** update the status line to reflect the actual
  current state — round-1 remediation complete (13/13), and (once this round-2
  audit is presented) a second ADR-conformance audit pass in/awaiting review,
  mirroring the same "in progress (n/m done)" phrasing this line already uses so
  it doesn't go stale in the same way after round 2 either.

## Findings — Test Coverage vs. ADRs

- **Round-1 item — `codeql.yml` wrong branch target (RESOLVED, live-
  verified).** `AUDIT-0012` found `.github/workflows/codeql.yml` scanning a
  branch (`main`) that isn't the repository's actual default branch, so the CI
  security scan silently never ran on real merges. Current file targets
  `master`. Live-verified this session: `git remote show origin` confirms
  `master` is genuinely the repository's default (`HEAD branch: master`).
  **PASS.**
- **Round-1 acknowledged item 1 — bare `ndarray` typing (unchanged, still
  acknowledged-not-scheduled).** Round 1 judged introducing full `numpy`
  stub-based generic typing project-wide too large relative to its value at the
  time; not re-opened, no change in risk profile this round.
- **Round-1 acknowledged item 2 — `architecture.mmd` CI sync (unchanged, still
  acknowledged-not-scheduled).** Round 1 judged a CI check that fails the build
  when `architecture.mmd` drifts from the real import graph as worth deferring;
  **this round's own findings (`AUDIT-0016`, `AUDIT-0017`, `AUDIT-0020`) are a
  direct, concrete illustration of exactly the drift this deferred check would
  have caught automatically.** Not re-scored as a hard requirement here (round
  1's own acknowledgment stands, and Phase 7 doesn't mandate accepting a
  deferred item just because it would have helped), but worth surfacing to the
  human alongside the other findings as evidence the trade-off deserves a second
  look now that there's a concrete cost data point.
- Full toolchain re-run live this session, all clean: `pytest` 445/445,
  `mypy --strict` 53 files clean, `ruff check` clean, `ruff format --check` 154
  files already formatted (zero drift).

## Open Questions

None — the README fix has exactly one reasonable resolution. (The
`architecture.mmd` CI-sync deferral note above is a suggestion for the human's
attention, not a finding requiring a choice between fix options.)

## Definition of Done (for Phase 8)

- `README.md`'s Status line reflects that round-1 remediation is complete
  (13/13) and that a round-2 audit has occurred
- No test/code change expected (documentation-only fix)
- `Delivered Artifacts` block below completed and accurate

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8. -->
