# Findings: AUDIT-0012 — Tooling & Release Configuration

**Auditor:** Lead Agent (inline, single-pass) **Date:** 2026-09-08 **Verdict:**
No config change was made to any file — read-only audit, live CI tools actually
installed and run against this exact checkout to verify claims empirically
rather than only reading YAML/TOML by eye. Core gates (`ruff check`,
`ruff format`, `mypy --strict`, `pytest`) all genuinely enforce what ADR-000
requires, no `continue-on-error` anywhere, no bare `# type: ignore`, no global
`disable_error_code`, `hacs.json`/`PLATFORMS` fully agree
post-`switch`→`select`. **2 FAILs**: `mypy.ini`'s `python_version = "3.14"` is
invalid ini syntax — mypy itself rejects it and silently falls back to
auto-detecting the interpreter's version instead of enforcing the ADR-000
§4-Amendment-mandated 3.14 floor; and `docs/architecture.mmd` still describes
the pre-2026-08-30 `switch`-based diagnostics architecture — confirmed (by
repo-wide grep) to be the *only* file outside `tasks/`/`adr/` still saying
"switch," meaning `TASK-0018`'s dedicated switch→select cleanup task missed this
exact file entirely. **1 FAIL found outside the checklist, mirroring the pattern
of prior audits**: `pytest.ini` and `pyproject.toml`'s
`[tool.pytest.ini_options]` both configure pytest simultaneously — pytest's own
runtime output confirms `pytest.ini` wins and the `pyproject.toml` section,
including its `pythonpath` entry, is silently, completely ignored — the exact
class of dead/misleading duplicate config `TASK-0020` already fixed once for
`mypy.ini` vs. `pyproject.toml [tool.mypy]`, recurring unaddressed in a sibling
tool. README.md badly fails the "high-level pointer, not a decision-rationale
duplicate" standard, and its own **Status** line ("Brainstorming / Concept
phase") flatly contradicts a 20/20-tasks-done, 419-tests-green,
11-of-12-audits-complete codebase. **1 real Test-Coverage GAP found and
confirmed live, more serious than hypothetical**: `codeql.yml`'s
`push`/`pull_request` triggers both target `branches: ["main"]`, but this
repository's actual default branch — confirmed via direct
`git ls-remote --symref` query, not inference — is `master`; no `main` branch
exists at all. CodeQL therefore never runs on an actual push or pull request,
only via its weekly cron. One Test-Coverage criterion resolved in the *opposite*
direction from what a literal reading of the config would suggest:
`extend-select = ["E", "F"]` **does** catch a deliberately introduced
`except Exception:` (via `BLE001`/`S110`), confirmed three times including
against a live, near-identical copy of a real source file — worth flagging
explicitly since `["E", "F"]` alone reads as if it wouldn't.

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | [ADR-000 §1] `.github/workflows/code_checker.yml` runs all four gates and fails the build if any fails, none present-but-non-blocking | PASS, with two documentation-drift notes | `grep -n "continue-on-error" .github/workflows/*.yml` → zero matches anywhere — confirmed no silently-defeated gate. `code_checker.yml:32-33` runs `uv run pre-commit run --all-files --show-diff-on-failure --color=always` (a normal, unguarded step — its non-zero exit fails the job), then `:34-35` runs `uv run pytest` separately. `.pre-commit-config.yaml:6-11` wires `ruff` (id `ruff`, `args: [--fix, --exit-non-zero-on-fix]` → this is `ruff check --fix --exit-non-zero-on-fix`; per ruff's own documented default exit behavior, it exits non-zero both when a fix was applied *and* when any violation remains after fixing, so it genuinely gates) and `ruff-format` (default entry, no `--check` flag — but pre-commit's own wrapper treats "hook modified a file" as a failure, so an unformatted file still fails the run even without an explicit `--check`). `:12-21`'s local `mypy` hook runs `uv run mypy custom_components/shady tests` (`:16-17`, no explicit `--config-file mypy.ini`) — verified this still resolves `mypy.ini` correctly via mypy's own cwd-based auto-discovery (pre-commit hooks run from repo root by default; live-verified in this audit by running the equivalent command from `/home/claude/shady` and observing `mypy.ini`'s own settings — including its per-file `warn_unused_ignores` overrides — take effect). All three tools functionally gate the build; **two things ADR-000 §1 states don't literally match**: it says these gates "run via `.github/workflows/ci.yml`" (`000-coding-standards.md:91`) — no such file exists (`ls .github/workflows/ci.yml` → No such file or directory; the real file is `code_checker.yml`) — and its Invocation column lists `mypy custom_components/shady tests --config-file mypy.ini` / `ruff format custom_components/` / `ruff check custom_components/` as if these were run as direct top-level CI steps, when in fact all three are invoked indirectly through `pre-commit`'s own hook definitions with different flags/paths than literally stated. The *effect* ADR-000 §1 requires is genuinely delivered; the *filename* and *literal invocation strings* it documents are stale. |
| 2 | [ADR-000 §2] `mypy.ini`'s per-file `warn_unused_ignores = False` list contains exactly `config_flow`, `sensor`, `coordinator`, `select`, `button`, no others | PASS | `mypy.ini:16-32`: five `[mypy-shady.X]` sections, exactly `config_flow` (`:16`), `sensor` (`:19`), `coordinator` (`:22`), `select` (`:28`), `button` (`:31`) — each with `warn_unused_ignores = False` and nothing else, no stray sixth module, no pure-tier module (e.g. `cache`, `aggregation`, `string_computation`) present. Matches ADR-000 §2's own stated list exactly ("`config_flow.py`, `sensor.py`, `coordinator.py`, `select.py` ..., and `button.py`", `000-coding-standards.md:104-106`). |
| 3 | [ADR-000 §2] Zero bare `# type: ignore` anywhere the config touches; zero global `disable_error_code` | PASS | `grep -rn "# type: ignore" custom_components/ \| grep -v "# type: ignore\["` → zero matches — every suppression in the codebase carries an explicit error code, none bare. `grep -rn "disable_error_code" mypy.ini pyproject.toml` → the only hit is `mypy.ini:15`, which is the explanatory comment itself ("never a global `disable_error_code`") — not an actual usage. |
| 4 | [ADR-000 §4 / 2026-08-22 Amendment] Python ≥3.14 declared consistently in every version-floor location (`requires-python`, `mypy.ini`'s `python_version`, `hacs.json`'s `homeassistant` minimum) | **FAIL** (functional; textually present) | Textually, all three say 3.14-equivalent: `pyproject.toml:10` `requires-python = ">=3.14"`; `mypy.ini:2` `python_version = "3.14"`; `hacs.json`'s `"homeassistant": "2026.3"`. **But `mypy.ini:2`'s value is quoted**, which is invalid syntax for mypy's ini-format config — live-verified by running `python3 -m mypy --config-file mypy.ini custom_components/shady tests` from the repo root: mypy itself prints `mypy.ini: [mypy]: python_version: Invalid python version '"3.14"' (expected format: 'x.y')` as its very first line, then silently proceeds using the running interpreter's own version instead (confirmed by removing only the quotes in a scratch copy — `sed 's/python_version = "3.14"/python_version = 3.14/'` — which makes the config-error line disappear while every other output line stays byte-identical). This exit code is currently `1` regardless, but *only* because of two unrelated pre-existing errors this audit also had to isolate and rule out (see Test-Environment Note below) — with those absent, this run would exit `0` **despite the version pin being completely non-functional**. The practical risk: if the CI/dev Python version ever drifted below 3.14 for any reason, `mypy.ini`'s pin — the one mechanism ADR-000 §4's Amendment specifically added to enforce the floor — would silently fail to catch it, because mypy already discards this setting today as unparseable. |
| 5 | \[ADR-000 §4 Amendment, ruff `target-version` note\] `pyproject.toml`'s `target-version = "py313"` pin (deliberately below `requires-python`'s 3.14) is still a live, commented, deliberate choice, not silent drift | PASS | `pyproject.toml:40-57`: the full, detailed, dated rationale comment (PEP 758's optional-parens-in-multi-exception-`except` change, and why `ruff format` must still emit the parenthesized form) is present verbatim and `target-version = "py313"` (`:57`) is still explicitly set — not removed, not silently matching `requires-python`. `TASK-0020`'s own Delivered Artifacts confirm this comment was deliberately *updated* (not left stale) when that task removed `pyproject.toml`'s separate `[tool.mypy]` section, specifically to stop cross-referencing the section being deleted — i.e., this rationale has actively been kept in sync at least once already, not merely inherited unread. |
| 6 | [ADR-000 §7] `README.md` stays a high-level pointer to the ADRs, not a duplicate of decision rationale that belongs in `adr/` | **FAIL** | `README.md`'s "Core idea" section (points 1–8, roughly 60 lines) is a detailed technical restatement of decision content that already lives in ADR-001 (empirical per-slot regression, `wls2` default vs. `linear`/`kernel`/`wls3`), ADR-011 (smoothing radius, the 25%-deviation neighbor-exclusion/rescale cutoff and its `-1%` special value), ADR-003a/003b (clipping exclusion, temperature derating, the double-counting flag), ADR-004/ADR-013 (diagnostic mode, `shady.select_diagnostic_slot` service, scatter-chart caching), ADR-005 (aggregate/integral sensors), and ADR-006 (ramping vs. blending, their default durations and cutoff) — specific numeric defaults and edge-case behavior, not a pointer. This is exactly the drift risk §7 exists to prevent: e.g. point 3's "25% (configurable)" / "cutoff value `-1%`" language would need to be updated in *two* places (here and ADR-011) if that default ever changed, with nothing to enforce they'd be updated together. **Related, not explicitly asked but directly relevant to this same criterion's spirit:** `README.md:3`'s own **Status** line reads `**Status:** Brainstorming / Concept phase` — flatly false for a codebase with 20/20 implementation tasks `done`, 419 tests passing live (this audit's own count, `pytest --collect-only`), and 11 of this audit series' own 12 groups already reviewed. A reader landing on this README today would reasonably conclude the project doesn't have working code yet. |
| 7 | [ADR-000 §9] `docs/architecture.mmd` is genuine Mermaid (not ASCII art), and reflects the *current* module chain rather than an earlier architecture | **PARTIAL → FAIL on currency** (PASS on format) | Format: genuine Mermaid, `flowchart TB` (`architecture.mmd:1`) with proper node/subgraph/edge syntax throughout — not hand-drawn ASCII, satisfies §9's explicit preference. Currency: **fails** — `architecture.mmd:30-31` still reads `subgraph Diag["Diagnostics (optional, via switch)"]` / `SWITCH([Switch: diagnostics<br/>default off])`, describing the architecture from *before* ADR-004's 2026-08-30 amendment replaced `switch.py`/`ShadyDiagnosticsSwitch` with `select.py`/`ShadyDiagnosticModeSelect`. Confirmed via `grep -rln "switch" --include="*.mmd" --include="*.md" --include="*.json" --include="*.yml" --include="*.ini" --include="*.toml" .` (excluding `tasks/`/`adr/`, which legitimately discuss the rename's own history) that **`docs/architecture.mmd` is the only remaining file in the entire repository still referencing "switch."** This is a direct miss by `TASK-0018-hacs-select-rename-cleanup`, whose own Goal section explicitly says "Three non-code files were never updated for the same rename" and names exactly `hacs.json`, `mypy.ini`, `README.md` — never `docs/architecture.mmd`, a fourth file in the identical situation that the task's own framing ("finishes propagating [the rename] to files outside `custom_components/` and `tests/`") should have caught but didn't. |
| 8 | `hacs.json`'s `domains` list matches every platform actually registered in `__init__.py`; `"switch"` fully removed from both, not just one | PASS | `hacs.json`: `"domains": ["sensor", "select", "button"]`. `custom_components/shady/__init__.py:65`: `PLATFORMS = ["sensor", "select", "button"]`. Identical, in the same order, zero `"switch"` residue in either file — cross-checked against AUDIT-0011's own confirmation that `__init__.py` uses this exact `PLATFORMS` constant for both forwarding and unloading (`:100,109,131`). |
| 9 | `.github/workflows/release.yml` produces a release artifact matching `hacs.json`'s `zip_release`/`filename` expectations (`shady.zip`) | PASS | `release.yml`'s "Build release ZIP" step: `cd shady/custom_components/shady && zip -r ../../../shady.zip .` — three levels up from `custom_components/shady` lands at the Actions runner's workspace root (one level above the `shady` checkout, since checkout used `path: shady`), producing a file literally named `shady.zip` there; the following "Create GitHub Release" step's `files: shady.zip` (working directory defaulting to that same workspace root) matches. `hacs.json`'s `"zip_release": true` / `"filename": "shady.zip"` agree exactly. |
| 10 | `pyproject.toml`'s `dependencies`/`dependency-groups` stay in sync with `tasks/DEPENDENCIES.md` — no undeclared runtime dependency | PASS | `tasks/DEPENDENCIES.md` lists exactly two entries: `numpy 1.26.0 (lower bound)`, cross-referenced against `pyproject.toml:13-15`'s `dependencies = ["numpy>=1.26.0"]` — identical bound; and `voluptuous (dev dependency, already declared)`, explicitly framed as dev-only (HA supplies it at runtime) and correctly present only in `pyproject.toml:27-35`'s `[dependency-groups] dev` list (`:34`), not in `[project.dependencies]` — matches its own documented framing exactly. The other five dev-group entries (`mypy`, `pre-commit`, `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`) are tooling the project's own workers/CI use, not libraries application code imports, so they fall outside `DEPENDENCIES.md`'s stated purpose (tracking libraries *source code* depends on) — no undeclared-dependency gap. |

### Test-Environment note (isolating a false lead)

Before reaching the "clean" `mypy` result cited in Criterion 4 above, this
audit's first `mypy` run (with only `mypy`+`numpy` installed, not the full dev
group) reported two additional `untyped-decorator` errors on
`tests/test_diagnostics_base.py:193` and `tests/test_coordinator_intraday.py:79`
— both on `@pytest.mark.parametrize` lines. Isolated by installing the actual
declared dev dependencies (`pytest`, `pytest-asyncio`, `pytest-cov`,
`voluptuous`) and re-running: both errors disappeared
(`Success: no issues found in 53 source files`) — confirming they were an
artifact of this sandbox initially missing `pytest` itself (which
`uv sync --group dev` always installs in real CI), not a real project defect.
Recorded here so this false lead isn't re-investigated by a future audit; it
does **not** contradict `tasks/adr-summary.md`'s "mypy --strict clean" claim.

## Test-Coverage Criteria (CI-pipeline coverage, not pytest coverage)

| # | Criterion | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | Would a deliberate `NDArray[np.float64]` → bare `np.ndarray` regression be caught by the current `mypy.ini` config? | **GAP** (self-acknowledged in the ADR text itself) | Live-verified: a standalone scratch file with `def foo(x: np.ndarray) -> np.ndarray: return x * 2` under `mypy --strict` reports `Success: no issues found` — a bare `np.ndarray` type-checks cleanly, exactly as ADR-000 §4 itself already states ("a bare `np.ndarray` type-checks cleanly... so it is a project convention, applied uniformly, rather than a gate the tooling already enforces on its own," `000-coding-standards.md:229-232`). This audit's contribution is confirming that self-description is accurate rather than aspirational — it is not a new finding, but formal confirmation of a documented, already-known gap. |
| 2 | Would a deliberate bare `except Exception:` (violating ADR-000 §8) be caught by `ruff check`'s current `extend-select = ["E", "F"]`? | **COVERED** — worth flagging, since a literal reading of the config suggests otherwise | Tested three times with increasing rigor, all consistent: (1) a synthetic file under a scratch `pyproject.toml` with exactly `extend-select = ["E", "F"]`; (2) the same, re-run to rule out a fluke; (3) most rigorously, a full copy of the real `coordinator.py` with an injected `except Exception: pass` function, checked with the real repo's own `pyproject.toml` via `ruff check --config pyproject.toml`. All three flag it — `BLE001` ("Do not catch blind exception: `Exception`") and `S110` ("`try`-`except`-`pass` detected") — exit code 1. This is because the installed `ruff` (0.16.6, closely matching `.pre-commit-config.yaml`'s pinned `v0.16.4`) already enables the `S` (flake8-bandit) and `BLE` (flake8-blind-except) rule categories as part of its own baseline default set, independent of the `E`/`F` entries in `extend-select` — confirmed via `--show-settings`, which lists dozens of rule-category prefixes as enabled even under `--isolated` with no config at all. A maintainer reading only `pyproject.toml:60`'s `extend-select = ["E", "F"]` would reasonably (but incorrectly) conclude broad-exception-catching isn't linted; it is. |
| 3 | Would `codeql.yml` actually run on every PR that touches `custom_components/`, or only on a schedule/push-to-main that could let a vulnerable pattern merge before being caught? | **FAIL / GAP — confirmed live, not hypothetical** | `codeql.yml:4-7`: `push: branches: ["main"]` and `pull_request: branches: ["main"]`. This repository's actual default branch was confirmed directly against the remote (not inferred from a local clone) via `git ls-remote --symref origin HEAD` → `ref: refs/heads/master`; `git branch -a` on the fresh clone additionally shows no `main` branch exists anywhere in the remote's branch list at all (`master`, `initial_code`, `initialcode` only). Because both triggers target a branch that does not exist, **CodeQL never runs on an actual push or pull request** — only via its own `schedule: - cron: "3 0 * * 6"` (`:8-9`), i.e. up to a week's delay, and never gated in front of a merge the way `code_checker.yml`'s per-push/PR triggers are. This is precisely the scenario the criterion asks about, not a marginal edge case. |
| 4 | Is there any CI gate for `docs/architecture.mmd` staying in sync with the actual module chain, or is it entirely manually maintained with no check? | **GAP — and demonstrated, not just asserted** | `grep -rln "architecture.mmd" .github/workflows/ .pre-commit-config.yaml` → zero matches; nothing in the pipeline reads, lints, or diffs this file against source. Unlike the other hypothetical Test-Coverage gaps in this audit set, this one is not merely theoretical: Audit Criterion 7 above already found the file has, in fact, drifted (the `switch` vs. `select` staleness), and stayed drifted through at least one dedicated cleanup task (`TASK-0018`) and eleven completed sibling audits without being caught — because nothing automated ever checks it. |
| 5 | Does `dependabot.yml` cover both the Python dependency ecosystem and the GitHub Actions ecosystem? | PASS | `.github/dependabot.yml`: two `updates` entries — `package-ecosystem: "github-actions"` (weekly) and `package-ecosystem: pip` (daily) — both targeting `directory: "/"`, both configured. |

## Additional finding outside the checklist

**`pytest.ini` and `pyproject.toml`'s `[tool.pytest.ini_options]` both configure
pytest simultaneously, and pytest silently picks only one.** `pytest.ini` (root)
sets `asyncio_mode = auto` / `testpaths = tests`; `pyproject.toml:64-67`'s
`[tool.pytest.ini_options]` sets `testpaths = ["tests"]`,
`asyncio_mode = "auto"`, **and** `pythonpath = ["custom_components"]` — a
setting `pytest.ini` does not have an equivalent for at all. Running
`pytest --collect-only -v` from the repo root prints pytest's own explicit
warning as its second line:
`configfile: pytest.ini (WARNING: ignoring pytest config in pyproject.toml!)` —
confirming `pyproject.toml`'s entire pytest section, `pythonpath` included, is
dead configuration, never applied. This is currently harmless only because no
test file actually needs `pythonpath`-based imports:
`grep -l "^from shady\|^import shady" tests/*.py` returns nothing — every test
uses ADR-000 §6's direct file-path-loading convention instead, which was
specifically designed to avoid needing a `pythonpath` entry in the first place.
But structurally this is the exact same "two config files disagree, one wins
silently, nobody would notice until it broke something" pattern `TASK-0020`
explicitly identified and fixed for `mypy.ini` vs. `pyproject.toml [tool.mypy]`
(that task's own Goal section calls the duplicate "dead, misleading config that
would silently start running mypy non-strict if `mypy.ini` were ever
renamed/removed without anyone noticing") — the pytest equivalent of that same
risk was never addressed and still exists today, one config generation later.

**Residual, still-open item from `TASK-0020`'s own Delivered Artifacts,
re-tested live here:** `pyproject.toml:33`'s dev-dependency group still lists a
bare, unpinned `"ruff"`, while `.pre-commit-config.yaml:7` pins the
`ruff-pre-commit` hook to a specific `rev` (`v0.16.4`). `TASK-0020` explicitly
found this exact pattern had *already* caused one real formatting disagreement
(an old `rev: v0.6.2` vs. a newer resolved `ruff`) and recommended a follow-up
task to either pin the dev dependency or otherwise keep the two in sync — no
such follow-up task exists anywhere in `tasks/INDEX.md` (`TASK-0020` remains the
highest-numbered task). Re-tested today: currently benign — `pip`'s unpinned
resolution (`ruff` 0.16.6) and the pinned hook (`v0.16.4`) agree on formatting
for every file in this repo right now
(`ruff format --check custom_components/ tests/` → `53 files already formatted`,
zero drift) — but the structural gap `TASK-0020` flagged and left open is still
exactly as open as it was then.

## Live verification commands run during this audit

```
$ python3 -m mypy --config-file mypy.ini custom_components/shady tests
mypy.ini: [mypy]: python_version: Invalid python version '"3.14"' (expected format: 'x.y')
Success: no issues found in 53 source files

$ python3 -m ruff check custom_components/ tests/
All checks passed!

$ python3 -m ruff format --check custom_components/ tests/
53 files already formatted

$ python3 -m pytest --collect-only -v | head -5
configfile: pytest.ini (WARNING: ignoring pytest config in pyproject.toml!)
419 tests collected in 0.33s

$ git ls-remote --symref origin HEAD
ref: refs/heads/master  HEAD
```

No test file required `homeassistant` to be installed for this audit's own
checks (tooling/config only, no application-behavior assertions), consistent
with AUDIT-0008/AUDIT-0009/AUDIT-0011's prior notes that `homeassistant` itself
is never a declared dependency anywhere in this project.

## Candidate Follow-Ups (not created — proposed only)

1. **Criterion 4's FAIL:** unquote `mypy.ini:2` (`python_version = 3.14`, no
   quotes) — a one-line fix restoring the ADR-000 §4-Amendment-mandated floor to
   actual enforcement. Trivial, high-value, zero risk.
1. **Criterion 7's FAIL:** update `docs/architecture.mmd:30-31` to describe the
   select-entity architecture (`Diagnostics (optional, via select entity)` / a
   `SELECT` node in place of `SWITCH`), closing the fourth file `TASK-0018`
   missed.
1. **Criterion 6's FAIL:** trim `README.md`'s "Core idea" section to a short
   summary + explicit pointers to ADR-001/003a/003b/004/005/006/011 for the
   numeric defaults and edge-case behavior currently duplicated in prose;
   separately correct `README.md:3`'s stale "Brainstorming / Concept phase"
   status line to reflect the project's actual, largely- complete state.
1. **Additional finding (pytest.ini):** remove `pytest.ini` and consolidate its
   two settings into `pyproject.toml`'s already-more- complete
   `[tool.pytest.ini_options]` (which already has both plus the otherwise-dead
   `pythonpath` entry) — mirroring exactly how `TASK-0020` resolved the
   analogous `mypy.ini`/`[tool.mypy]` duplication, in the opposite direction
   (keep the single-purpose `.ini` file there; keep the `pyproject.toml` section
   here — either direction works, the point is picking one).
1. **Test-Coverage Criterion 3's FAIL:** change `codeql.yml:5,7`'s
   `branches: ["main"]` to `branches: ["master"]` (or drop the branch filter
   entirely, if CodeQL is meant to run on every branch) so the push/pull_request
   triggers actually fire against this repository's real default branch.
1. **Test-Coverage Criterion 4's GAP:** no automated check is proposed here
   beyond what Follow-Up 2 already fixes manually — a lightweight option would
   be a pre-commit/CI step that greps `docs/architecture.mmd` for known-stale
   terms (e.g. `\bswitch\b`) the same way this audit did, though a truly
   structural sync check would require parsing the Mermaid graph against actual
   `import` statements, likely more effort than the diagram's own churn rate
   justifies.
1. **`ruff` dev-dependency pin (residual from `TASK-0020`):** pin
   `pyproject.toml:33`'s `"ruff"` entry to match `.pre-commit-config.yaml:7`'s
   `rev` (or vice versa), closing the follow-up `TASK-0020` recommended but that
   was never scheduled.

## Delivered Artifacts (for the task file)

- `tasks/AUDIT-0012-tooling-release-config-findings.md` (this file)
