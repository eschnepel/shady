# Task: Release Pipeline & Tooling-Config Hardening

- **Status:** done
- **Related ADRs:** [ADR-000]
- **Dependencies:** []

## Goal

A review of `.github/workflows/release.yml` and its supporting config found
three independent gaps, none requiring a new architecture decision (ADR-000
already establishes `mypy.ini` as the single authoritative mypy config, and
already establishes the tooling this project's own CI is supposed to run — these
are gaps against that existing decision, not new ones):

1. `pyproject.toml` carries its own `[tool.mypy]` section — `mypy_path = "."`,
   `no_namespace_packages = true`, no `strict = True` at all — that directly
   contradicts `mypy.ini` (`mypy_path = custom_components`, `strict = True`,
   per-file `warn_unused_ignores` overrides). Verified empirically that
   `mypy.ini` currently wins (mypy's own precedence, both files present, invoked
   from repo root with no `--config-file`) — not a live break today — but it is
   dead, misleading config that would silently start running mypy non-strict if
   `mypy.ini` were ever renamed/removed without anyone noticing.
1. `release.yml`'s "Update manifest.json version and requirements" step only
   ever updates `.version` — `.requirements` (currently `["numpy>=1.26.0"]`) is
   never synced from anywhere at release time, so if `pyproject.toml`'s own
   numpy version bound ever changes, the released HA integration's requirement
   pin silently drifts out of sync with what the code was actually built/tested
   against.
1. `release.yml` triggers purely on `push: tags: "v*"` and never runs this
   project's own tests/mypy/ruff gate (`.github/workflows/code_checker.yml`'s
   checks) against the tagged commit before publishing — nothing stops a red
   build from being tag-released.

## Acceptance Criteria

- Given `pyproject.toml`, When read after this task, Then it has no
  `[tool.mypy]` section at all — `mypy.ini` remains the single, unambiguous
  config, with nothing left to silently fall back to.
- Given `pyproject.toml`'s `[project.dependencies]` (or equivalent) and
  `custom_components/shady/manifest.json`'s `"requirements"` array, When a
  release is built (tag push), Then the release workflow derives
  `manifest.json`'s `numpy` requirement from `pyproject.toml`'s own declared
  dependency at build time, rather than trusting a hand-maintained duplicate —
  so the two cannot silently drift again. Rename the step so its name matches
  what it now actually does.
- Given a tag pushed to a commit whose tests/mypy/ruff would fail, When that tag
  is pushed, Then `release.yml` runs those same checks itself (as a job gating
  the existing release job via `needs:`, self-contained within `release.yml`
  rather than depending on a separate workflow's run having already completed
  for that exact ref — tag pushes and `code_checker.yml`'s own triggers are not
  guaranteed to correlate cleanly) and does not proceed to build/publish a
  release if they fail.
- Given the full local gate (`pytest`,
  `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .`), When run after this task, Then all four stay
  green/clean exactly as before this task (this task changes no application
  code, only `pyproject.toml` and `.github/workflows/release.yml`) — the two
  pre-existing, unrelated `ruff format` drift files noted in `tasks/INDEX.md`'s
  refinement log are unaffected either way.
- `release.yml` cannot be executed end-to-end outside GitHub's own Actions
  runner (no tag-push trigger available in this environment), so this task's own
  verification is necessarily a careful manual read of the resulting YAML plus,
  where practical, running the equivalent shell/`jq` logic locally against this
  repo's real `pyproject.toml`/`manifest.json` to confirm the derived
  requirement string is correct — record exactly what was and wasn't runnable in
  Delivered Artifacts.

## Estimated File / Module Footprint (hint, not a commitment)

- `pyproject.toml` (remove `[tool.mypy]`)
- `.github/workflows/release.yml` (requirements-sync step, new gating `needs:`
  job)
- No `.py` files

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, including which parts of
  this task could and could not be verified without a real GitHub Actions run
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected — `jq` is already used by the existing workflow)

## Consumed Interfaces

- `pyproject.toml`'s own `[project]` dependency declaration (pre-existing) — the
  source of truth this task's release-step fix reads `numpy`'s version bound
  from.
- `custom_components/shady/manifest.json` (pre-existing) — the file the
  corrected step writes back into, same as the existing version-bump step
  already does via `jq`.

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->

- `pyproject.toml` → `[tool.mypy]` section removed entirely (was:
  `python_version`, `mypy_path = "."`, `no_namespace_packages = true`,
  `ignore_missing_imports = true`, `warn_unused_ignores = true` — none of it
  agreeing with `mypy.ini`, and none of it now reachable). `[tool.ruff]`'s
  adjacent comment (which explicitly compared `requires-python` against
  `[tool.mypy] python_version`) updated to stop referencing the now-removed
  section — it now compares against `requires-python` alone, since `mypy.ini`
  (the real, live config) never set `python_version` explicitly in the first
  place (mypy infers it from the running interpreter, already 3.14 via `uv`'s
  managed venv). No other section of `pyproject.toml` touched.
- `.github/workflows/release.yml` → two changes:
  1. New `test` job: checks out to `shady/` (matching `release`'s own checkout
     path), sets up Python 3.14 + `uv`, caches `pre-commit`, runs
     `uv sync --group dev` then
     `uv run pre-commit run --all-files --show-diff-on-failure --color=always`
     then `uv run pytest` — a self-contained duplicate of `code_checker.yml`'s
     own `validate` job (deliberately not a `needs:`-dependency on that *other*
     workflow's run, since a tag push and `code_checker.yml`'s own triggers
     aren't guaranteed to correlate to one already-finished run for that exact
     ref, per the task's own Acceptance Criteria). One deliberate simplification
     versus `code_checker.yml`: a single fixed Python version (3.14, matching
     `requires-python`) rather than that file's one-entry version matrix — this
     is a one-shot release gate, not the project's own canonical multi-version
     CI job, so the extra matrix machinery wasn't reproduced.
  1. `release` job gains `needs: test`. Its manifest-update step (renamed from
     "Update manifest.json version and requirements" to "Update manifest.json
     version and sync numpy requirement from pyproject.toml") now also derives
     `manifest.json`'s `"requirements"` entry from `pyproject.toml`'s own
     `[project] dependencies` array at build time via `awk`+`grep`+`jq` (scoped
     specifically to the `dependencies = [ ... ]` block so a stray "numpy"
     mention elsewhere in the file couldn't be misread; fails the step with
     `::error::` if no `numpy*` entry is found there) instead of trusting the
     two to stay in sync by hand. No new tool introduced — `jq` was already used
     by this step; `awk`/`grep` are already used elsewhere in this project's own
     dev tooling.
- No new external dependency — `tasks/DEPENDENCIES.md` unchanged.
- **What could and couldn't be verified (per this task's own Acceptance Criteria
  — `release.yml` can't run end-to-end outside a real GitHub Actions tag
  push):**
  - Verified for real: the exact `awk`/`grep`/`jq` pipeline from the
    manifest-update step, run against this repo's actual
    `pyproject.toml`/`manifest.json` (copied to a scratch directory, not the
    working tree) with `GITHUB_REF_NAME=v0.2.0` — produced a valid-JSON
    `manifest.json` with `"version": "0.2.0"` and
    `"requirements": ["numpy>=1.26.0"]`, matching `pyproject.toml`'s real
    dependency string exactly.
  - Verified for real, not just read: actually ran
    `uv run pre-commit run --all-files` and `uv run pytest` locally (this
    sandbox has network access to `github.com`, which is where `pre-commit`
    fetches its hook environments from) — both are exactly what the new `test`
    job's last two steps run, so this is a faithful, non-simulated dry run of
    that job's actual pass/fail logic, not just a YAML read. `pytest`: 419/419.
    The four AC-named local gate commands (`pytest`,
    `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
    `ruff format --check .`) all still green/clean, identical to the state
    before this task (same two pre-existing, already-documented drift files,
    unaffected).
  - Not verifiable here at all: the `actions/checkout`, `actions/setup- python`,
    `astral-sh/setup-uv`, `actions/cache`, and `softprops/ action-gh-release`
    steps themselves, and the real multi-job `needs:` scheduling/gating behavior
    — these require GitHub's own Actions runner. Read carefully by hand instead
    (job names, `needs:` wiring, `working-directory:` on every step that must
    run inside the `shady/` checkout path) and validated as syntactically
    correct YAML (parsed with `PyYAML`, confirmed `jobs: [test, release]` and
    `release.needs == "test"`).
  - **New finding surfaced by actually running `pre-commit run --all-files` (not
    by anything in this task's own stated scope) — reported here, not silently
    fixed:** `.pre-commit-config.yaml` pins `ruff-format`'s hook to
    `rev: v0.6.2`, while `pyproject.toml`'s `dev` dependency group lists a bare,
    unpinned `"ruff"`, which `uv sync` currently resolves to `0.16.4` — a much
    newer version with a different preferred wrapping style for multi-line
    `assert x, (msg)` statements. The two `ruff` versions disagree on how to
    format at least one real construct in this codebase. This was invisible
    until `TASK-0019`'s new `tests/test_translations.py` happened to contain
    that exact construct — the pinned, older hook then reformatted it in place,
    which the newer, unpinned `ruff format --check .` (the command this task's
    own Acceptance Criteria — and every prior task's Definition of Done —
    actually gates on) immediately flagged right back as non-conforming. **This
    means `code_checker.yml`'s existing `pre-commit` step and this task's new
    `release.yml` `test` job would, right now, on this exact commit, both
    flag/reformat that one file** — a real, live, already-present gap, not a
    hypothetical one, first exposed (not caused) by this verification. This sat
    outside every one of this task's four stated Acceptance Criteria (all of
    which name `ruff format --check .` specifically, which stayed green
    throughout), so it was not silently fixed here — doing so means a real
    trade-off decision (pin `ruff`'s dev-dependency version to match the old
    pre-commit hook, or bump the pre-commit hook's `rev` to track the current
    `ruff` and re-verify formatting repo-wide either way) that deserves the
    human's call, the same way the three gaps this task itself was born from
    were surfaced first and fixed only after confirmation. Recommend a small
    follow-up task once a direction is chosen.
  - **Self-caught process note, not a code defect:** the exploratory
    `pre-commit run --all-files` invocation above, run only to verify this
    task's own new job, side-effected a real in-place reformat of the
    already-`done`, already-committed `tests/test_translations.py` (pre-commit's
    `ruff-format` hook rewrites non-conforming files rather than just reporting
    them, unlike `ruff format --check`). Caught immediately by re-running the
    AC's own four gate commands right after and noticing a third file newly
    appear in the `ruff format --check .` drift list; reverted via
    `git checkout --` before proceeding, restoring `tests/test_translations.py`
    to its exact `TASK-0019` state — confirmed by `git status`/`git diff`
    showing only `pyproject.toml` and `.github/workflows/release.yml` touched by
    this task, and by re-running all four gate commands one more time afterward
    to confirm the pre-existing-only drift state held.
