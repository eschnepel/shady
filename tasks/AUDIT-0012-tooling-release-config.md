# Audit Task: Tooling & Release Configuration

- **Status:** todo
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** [ADR-000 §1, ADR-000 §2, ADR-000 §4, ADR-000 §4 Amendment (2026-08-22), ADR-000 §7, ADR-000 §9]
- **Dependencies:** [] (TASK-0018, TASK-0020 are `done`)
- **Origin:** TASK-0018-hacs-select-rename-cleanup,
  TASK-0020-release-pipeline-hardening — the only two tasks in the
  project whose Delivered Artifacts are entirely non-`custom_components`
  files

## Goal
This group has **no dedicated pytest test file** — its correctness is
enforced by CI itself (`ruff format`, `ruff check`, `mypy --strict`,
`pytest`, plus GitHub Actions workflows), not by application-level
tests. Verify the tooling config actually enforces what ADR-000
requires, and — since there's no test file to check for coverage gaps —
verify instead that the CI *pipeline* itself would actually catch a
regression in each ADR-000 requirement (the equivalent question, one
level up).

## Scope — Source Files
- `pyproject.toml`
- `mypy.ini`
- `pytest.ini`
- `hacs.json`
- `.github/workflows/release.yml`
- `.github/workflows/code_checker.yml`
- `.github/workflows/codeql.yml`
- `.github/workflows/rebase.yml`
- `.github/dependabot.yml`
- `README.md`
- `docs/architecture.mmd`

## Scope — Test Files
- None dedicated. This audit's "Test-Coverage Criteria" section below
  asks about CI-pipeline coverage instead of pytest coverage — treat
  `.github/workflows/code_checker.yml` as the artifact under test.

## Out of Scope
- Any `custom_components/` source file's actual `mypy --strict`/`ruff`
  compliance (that's a per-file CI outcome, re-checked by every other
  audit group implicitly when they note NDArray typing, etc.) — this
  audit checks the *configuration* that would enforce it, not whether
  every file currently passes (assume `tasks/adr-summary.md`'s claim of
  "414/414 tests passing, mypy --strict/ruff clean" as of 2026-09-05 is
  accurate, and re-verify only if another audit group reports a FAIL
  that implies otherwise).

## Audit Criteria
- [ADR-000 §1] Does `.github/workflows/code_checker.yml` actually run
  all four gates (`ruff format --check`, `ruff check`, `mypy --strict
  --config-file mypy.ini`, `pytest`) and fail the build if any one of
  them fails — confirm none is present-but-non-blocking (e.g. a
  `continue-on-error: true` that would silently defeat the gate)?
- [ADR-000 §2] Does `mypy.ini`'s per-file `warn_unused_ignores = False`
  list contain **exactly** the HA-facing modules (`config_flow`,
  `sensor`, `coordinator`, `select`, `button`) and no others — is there
  a stray suppression on a pure module that shouldn't need it, which
  would mask a real typing regression there?
- [ADR-000 §2] Is there zero use of a global `disable_error_code` or a
  bare `# type: ignore` anywhere the config touches (the ADR's explicit
  "never a global disable, never a bare ignore" rule) — this requires
  grepping the actual source for `# type: ignore` occurrences, not just
  reading `mypy.ini`.
- [ADR-000 §4 / its 2026-08-22 Amendment] Does `pyproject.toml`/
  `mypy.ini` declare Python ≥3.14 consistently in every place a version
  floor is stated (`requires-python`, `mypy.ini`'s `python_version`,
  `hacs.json`'s `homeassistant` minimum) — confirm no file was missed
  when the floor was raised?
- [ADR-000 §4 Amendment, `ruff` `target-version` note] Does
  `pyproject.toml`'s documented rationale for pinning `ruff`'s
  `target-version = "py313"` **below** `requires-python`'s 3.14 still
  hold — i.e. is this still a deliberate, commented choice and not
  something that silently drifted or was "fixed" by removing the
  comment without resolving the underlying tension?
- [ADR-000 §7] Does `README.md` stay a high-level pointer to the ADRs
  (not duplicating decision rationale that belongs in `adr/`) — spot-
  check for any section of `README.md` that restates ADR content in
  enough detail that the two could drift out of sync?
- [ADR-000 §9] Is `docs/architecture.mmd` a genuine Mermaid diagram
  (not ASCII art, per the ADR's explicit preference), and does it
  actually reflect the **current** module chain (cross-ref
  `tasks/adr-summary.md` §2's dependency chain) rather than an earlier
  version of the architecture predating, e.g., ADR-014's relocation?
- Does `hacs.json`'s `domains` list (`["sensor", "select", "button"]`)
  match every platform actually registered in `__init__.py` (cross-ref
  AUDIT-0011) — confirm no platform was added to one and not the other,
  and specifically confirm `"switch"` was fully removed here too as
  part of TASK-0018's rename cleanup, not just from `mypy.ini`.
- Does `.github/workflows/release.yml` (hardened by TASK-0020) produce
  a release artifact matching `hacs.json`'s `zip_release`/`filename`
  expectations (`shady.zip`)?
- Does `pyproject.toml`'s `dependencies`/`dependency-groups` list stay
  in sync with `tasks/DEPENDENCIES.md` — is every library `tasks/
  DEPENDENCIES.md` says is "already bundled" or "added by task X"
  correctly reflected here with no undeclared runtime dependency?

## Test-Coverage Criteria (CI-pipeline coverage, not pytest coverage)
- Would a deliberately introduced `NDArray[np.float64]` → bare
  `np.ndarray` regression anywhere in `custom_components/` actually be
  caught by the current `mypy.ini` config, or does a suppression
  somewhere blanket-cover the file it would appear in?
- Would a deliberately introduced bare `except Exception:` (violating
  ADR-000 §8) be caught by `ruff check`'s current `extend-select`
  rules (`["E", "F"]`) — do these rule sets actually include a check
  for broad exception handling, or would this class of violation pass
  CI silently?
- Would `codeql.yml` actually run on every PR that touches
  `custom_components/`, or only on a schedule/push-to-main that could
  let a vulnerable pattern merge before being caught?
- Is there any gate at all for `docs/architecture.mmd` staying in sync
  with the actual module chain (the ADR-000 §9 criterion above) — or is
  this entirely manually maintained with no CI check, meaning drift
  would never be caught automatically? (If so, this is this audit's
  clearest GAP finding — note it explicitly.)
- Does `dependabot.yml` cover both the Python dependency ecosystem
  (`pyproject.toml`) and the GitHub Actions ecosystem (the workflow
  files themselves), or only one?

## Consumed Context (attached to the auditor)
- `tasks/adr-summary.md`
- `adr/000-coding-standards.md` (full text)
- All files listed under Scope above
- `tasks/TASK-0018-*.md`, `tasks/TASK-0020-*.md`
- `tasks/DEPENDENCIES.md`

## Definition of Done
- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP, explicitly framed
  as CI-pipeline coverage rather than pytest coverage.
- Findings written to `tasks/AUDIT-0012-tooling-release-config-findings.md`.
- No code changes made.

## Delivered Artifacts
<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->
