# Task: Tooling Config Hardening, Round 3

- **Status:** done
- **Related ADRs:** [ADR-000]
- **Dependencies:** [TASK-0020-release-pipeline-hardening]

## Goal

`AUDIT-0012-tooling-release-config` found three related, silently- defeated
tooling-config defects, all the same "two configs disagree, or a value is
malformed, and nobody notices until it breaks something" pattern `TASK-0020`
already fixed once for `mypy.ini`'s `[tool.mypy]` duplicate:

1. **`mypy.ini`'s `python_version = "3.14"` is invalid ini syntax.** mypy itself
   rejects it live (`Invalid python version '"3.14"' (expected format: 'x.y')`)
   and silently falls back to auto-detecting the running interpreter's version
   instead of enforcing the ADR-000 §4-Amendment-mandated 3.14 floor. If the
   CI/dev Python version ever drifted below 3.14, this pin — the one mechanism
   specifically added to catch that — would silently fail to catch it.
1. **`pytest.ini` and `pyproject.toml`'s `[tool.pytest.ini_options]` both
   configure pytest simultaneously.** pytest's own runtime output confirms
   `pytest.ini` wins and `pyproject.toml`'s section — including its `pythonpath`
   entry, which has no equivalent anywhere in `pytest.ini` — is silently,
   completely ignored. Currently harmless (no test file needs `pythonpath`-based
   imports; every test uses ADR-000 §6's file-path-loading convention instead),
   but it's the exact dead-duplicate-config risk `TASK-0020` already flagged and
   fixed for mypy.
1. **`pyproject.toml`'s dev-group `"ruff"` is unpinned** while
   `.pre-commit-config.yaml` pins the `ruff-pre-commit` hook to a specific
   `rev`. `TASK-0020` found this exact pattern had *already* caused one real
   formatting disagreement once and explicitly recommended a follow-up to pin
   one to match the other — no such follow-up was ever scheduled. Currently
   benign (both resolve to compatible versions today), but the structural gap
   remains exactly as open as `TASK-0020` left it.

## Known Decisions

- Item 1's fix is unambiguous: remove the quotes (`python_version = 3.14`, not
  `"3.14"`) — mypy's own ini format requires the bare form. No decision needed.
- Item 3's fix direction (pin the dev dependency to match the hook, vs. bump the
  hook to match a floating dev dependency) was already recommended by
  `TASK-0020` as "pin one to match the other, either direction works" — this
  task should pin the dev-group `ruff` entry to match
  `.pre-commit-config.yaml`'s current `rev` (the more conservative direction,
  matching how `TASK-0020` itself resolved the mypy duplicate: keep the more
  specific/stricter source authoritative).

## Open Questions for Execution

- **Item 2's direction is not yet decided and needs a human answer before
  implementation:** `TASK-0020` resolved the analogous `mypy.ini`/`[tool.mypy]`
  duplicate by deleting `pyproject.toml`'s section and keeping the standalone
  `mypy.ini` authoritative. For pytest, `pyproject.toml`'s section is actually
  the *more complete* one (it has `pythonpath` in addition to everything
  `pytest.ini` has) — so mirroring `TASK-0020`'s exact precedent (favor the
  standalone `.ini` file) would mean deleting the *more* complete config and
  keeping the *less* complete one. Two reasonable options:
  - **(a) Consistency with precedent:** keep `pytest.ini`, delete
    `pyproject.toml`'s `[tool.pytest.ini_options]` section entirely (losing the
    currently-unused `pythonpath` entry, which nothing needs today).
  - **(b) Consistency with content:** keep `pyproject.toml`'s (fuller) section,
    delete `pytest.ini`. Both are safe (no test currently depends on
    `pythonpath`) — this is purely a "which file should be the project's one
    canonical tool- config location going forward" preference call for the
    human.

**Decision recorded — 2026-09-08:** Option (a) — keep `pytest.ini`, delete
`pyproject.toml`'s `[tool.pytest.ini_options]` section. **Decided by:** human
(confirmed by Lead Agent).

## Acceptance Criteria

- Given `mypy.ini`, When read after this task, Then `python_version = 3.14` (no
  quotes), and `mypy --config-file mypy.ini custom_components/ tests/` no longer
  prints the "Invalid python version" warning.
- Given the pytest config duplication, When resolved per the human's chosen
  direction above, Then exactly one of `pytest.ini` / `pyproject.toml`'s
  `[tool.pytest.ini_options]` exists, and running `pytest --collect-only -v`
  from the repo root no longer prints the "WARNING: ignoring pytest config in
  pyproject.toml!" line (or its mirror, if the other direction was chosen) — and
  still collects all 419 tests unchanged.
- Given `pyproject.toml`'s dev-group `ruff` entry, When read after this task,
  Then it is pinned to the exact version `.pre-commit-config.yaml`'s
  `ruff-pre-commit` hook's `rev` resolves to (matching, not merely
  compatible-with).
- Given the full test suite,
  `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`, and
  `ruff format --check .`, When run after this task, Then all remain green/clean
  (aside from the two pre-existing, unrelated drift files already on record in
  `tasks/INDEX.md`'s refinement log).

## Estimated File / Module Footprint (hint, not a commitment)

- `mypy.ini`
- `pytest.ini` and/or `pyproject.toml` (one deleted, per the human's chosen
  direction)
- `pyproject.toml`'s `[dependency-groups] dev` `ruff` entry

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, stating which
  pytest-config direction was chosen and the exact `ruff` version pinned
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected — this only pins an existing dev dependency's version)

## Consumed Interfaces

- `mypy.ini` — no prior task delivered this as a tracked artifact (pre-existing
  tooling config, same category `TASK-0020` touched).
- `pytest.ini`, `pyproject.toml` `[tool.pytest.ini_options]` — pre-existing
  tooling config.
- `.pre-commit-config.yaml` → `ruff-pre-commit` hook's pinned `rev` — (→ task:
  TASK-0020) — the version this task's `ruff` dev-dependency pin must match
  exactly.

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->

- `mypy.ini` → `python_version = 3.14` (unquoted; was `"3.14"`, invalid ini
  syntax mypy silently ignored).
  `mypy --config-file mypy.ini custom_components/ tests/` now runs clean with no
  "Invalid python version" warning, still
  `Success: no issues found in 53 source files`.
- `pyproject.toml` → `[tool.pytest.ini_options]` section deleted outright
  (pytest-config direction chosen: **(a) consistency with precedent** —
  `pytest.ini` is the project's one canonical pytest config, matching how
  `TASK-0020` resolved the analogous `mypy.ini`/`[tool.mypy]` duplicate).
  `pytest --collect-only -v` now reports `configfile: pytest.ini` with no
  "WARNING: ignoring pytest config in pyproject.toml!" line; still
  collects/passes all 419 tests unchanged. The
  `pythonpath = ["custom_components"]` entry that only existed in the deleted
  section is gone — confirmed nothing depended on it (every test already uses
  ADR-000 §6's file-path-loading convention, not `pythonpath`-based imports).
- `pyproject.toml` → `[dependency-groups] dev`'s `"ruff"` entry pinned to
  `"ruff==0.16.4"`, matching `.pre-commit-config.yaml`'s `ruff-pre-commit` hook
  `rev: v0.16.4` exactly (verified: `ruff --version` → `ruff 0.16.4` after
  `pip install ruff==0.16.4`).
- External dependencies added: none — this only pins an already-declared dev
  dependency's version. `tasks/DEPENDENCIES.md` unchanged.
- Full local gate after this task: `pytest` 419/419 passed;
  `mypy --config-file mypy.ini custom_components/ tests/` clean on 53 source
  files; `ruff check .` clean repo-wide; `ruff format --check .` shows only the
  one pre-existing, unrelated, already-documented drift file
  (`adr/004-diagnostics-select-and-scatter-sensor.md`'s embedded code block —
  `tests/test_regression.py`, the other drift file on record in
  `tasks/INDEX.md`'s refinement log, is no longer drifted as of this check),
  untouched, out of scope. `git diff --stat` confirms exactly `mypy.ini` and
  `pyproject.toml` changed — matches the Estimated Footprint.
