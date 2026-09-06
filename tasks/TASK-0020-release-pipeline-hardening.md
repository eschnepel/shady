# Task: Release Pipeline & Tooling-Config Hardening

- **Status:** todo
- **Related ADRs:** [ADR-000]
- **Dependencies:** []

## Goal
A review of `.github/workflows/release.yml` and its supporting config
found three independent gaps, none requiring a new architecture
decision (ADR-000 already establishes `mypy.ini` as the single
authoritative mypy config, and already establishes the tooling this
project's own CI is supposed to run — these are gaps against that
existing decision, not new ones):

1. `pyproject.toml` carries its own `[tool.mypy]` section — `mypy_path
   = "."`, `no_namespace_packages = true`, no `strict = True` at all —
   that directly contradicts `mypy.ini` (`mypy_path = custom_components`,
   `strict = True`, per-file `warn_unused_ignores` overrides). Verified
   empirically that `mypy.ini` currently wins (mypy's own precedence,
   both files present, invoked from repo root with no `--config-file`)
   — not a live break today — but it is dead, misleading config that
   would silently start running mypy non-strict if `mypy.ini` were ever
   renamed/removed without anyone noticing.
2. `release.yml`'s "Update manifest.json version and requirements" step
   only ever updates `.version` — `.requirements` (currently
   `["numpy>=1.26.0"]`) is never synced from anywhere at release time,
   so if `pyproject.toml`'s own numpy version bound ever changes, the
   released HA integration's requirement pin silently drifts out of
   sync with what the code was actually built/tested against.
3. `release.yml` triggers purely on `push: tags: "v*"` and never runs
   this project's own tests/mypy/ruff gate (`.github/workflows/code_checker.yml`'s
   checks) against the tagged commit before publishing — nothing stops
   a red build from being tag-released.

## Acceptance Criteria
- Given `pyproject.toml`, When read after this task, Then it has no
  `[tool.mypy]` section at all — `mypy.ini` remains the single,
  unambiguous config, with nothing left to silently fall back to.
- Given `pyproject.toml`'s `[project.dependencies]` (or equivalent) and
  `custom_components/shady/manifest.json`'s `"requirements"` array, When
  a release is built (tag push), Then the release workflow derives
  `manifest.json`'s `numpy` requirement from `pyproject.toml`'s own
  declared dependency at build time, rather than trusting a
  hand-maintained duplicate — so the two cannot silently drift again.
  Rename the step so its name matches what it now actually does.
- Given a tag pushed to a commit whose tests/mypy/ruff would fail, When
  that tag is pushed, Then `release.yml` runs those same checks itself
  (as a job gating the existing release job via `needs:`, self-contained
  within `release.yml` rather than depending on a separate workflow's
  run having already completed for that exact ref — tag pushes and
  `code_checker.yml`'s own triggers are not guaranteed to correlate
  cleanly) and does not proceed to build/publish a release if they fail.
- Given the full local gate (`pytest`, `mypy --config-file mypy.ini
  custom_components/ tests/`, `ruff check .`, `ruff format --check .`),
  When run after this task, Then all four stay green/clean exactly as
  before this task (this task changes no application code, only
  `pyproject.toml` and `.github/workflows/release.yml`) — the two
  pre-existing, unrelated `ruff format` drift files noted in
  `tasks/INDEX.md`'s refinement log are unaffected either way.
- `release.yml` cannot be executed end-to-end outside GitHub's own
  Actions runner (no tag-push trigger available in this environment),
  so this task's own verification is necessarily a careful manual read
  of the resulting YAML plus, where practical, running the equivalent
  shell/`jq` logic locally against this repo's real
  `pyproject.toml`/`manifest.json` to confirm the derived requirement
  string is correct — record exactly what was and wasn't runnable in
  Delivered Artifacts.

## Estimated File / Module Footprint (hint, not a commitment)
- `pyproject.toml` (remove `[tool.mypy]`)
- `.github/workflows/release.yml` (requirements-sync step, new
  gating `needs:` job)
- No `.py` files

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, including which
  parts of this task could and could not be verified without a real
  GitHub Actions run
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected — `jq` is already used by the existing workflow)

## Consumed Interfaces
- `pyproject.toml`'s own `[project]` dependency declaration
  (pre-existing) — the source of truth this task's release-step fix
  reads `numpy`'s version bound from.
- `custom_components/shady/manifest.json` (pre-existing) — the file the
  corrected step writes back into, same as the existing version-bump
  step already does via `jq`.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
