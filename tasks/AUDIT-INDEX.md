# Audit Task Index — Round 2 (Post-Remediation ADR Conformance Review)

**Status of this phase:** Phase 7 (audit generation) and Phase 8 (remediation)
both complete, 2026-09-12. Executed inline throughout (Lead Agent acting as
Auditor/Worker/Reviewer — no sub-agents available in this environment; see the
main orchestration prompt's "If you are unable to use subagents... work strictly
sequentially" clause). Findings below are real, evidence-based (file:line
citations, live `pytest`/`mypy`/`ruff` runs), not placeholders. Of the 12
round-2 audit groups, 4 had a scheduled fix (`AUDIT-0016`, `AUDIT-0017`,
`AUDIT-0020`, `AUDIT-0024`) — all now `done`; the other 8 needed none and are
closed as clean. Every finding had exactly one reasonable fix (no Open
Questions), so Phase 8 required no live human decisions. Full toolchain
re-verified green after every change: 446/446 tests (445 + 1 new coverage test),
`mypy --strict` clean, `ruff check`/`ruff format --check` clean.

## Why a round 2

`tasks/archived/AUDIT-0001` through `AUDIT-0012` (round 1, 2026-09-06/08) found
~35 items across the then-complete 20-capability build.
`tasks/archived/ AUDIT-REMEDIATION-INDEX.md` grouped every one of them into
`TASK-0021` through `TASK-0033`, all now `done` (see `tasks/archived/INDEX.md`'s
refinement log, closed 2026-09-10). Per that log's own closing note: *"Any
further work on this project (new features, new ADRs, a fresh audit pass) starts
a new planning cycle... rather than continuing this remediation batch."* This is
that fresh pass.

Round 1's own stated rationale for auditing at all — **drift across patches**
and **coverage vs. passing** — applies with extra force here, because the
remediation batch itself touched `cache.py`, `coordinator.py`,
`string_computation.py`, `__init__.py`, and effectively every `adr/*.md` file
(13 fix tasks plus a follow-on `Cleanup ADR NNN` documentation pass per file,
then a repo-wide `mdformat` reflow). Each of those was reviewed individually
against its own task file (Phase 4b) — nothing has yet re-examined the
**accumulated, integrated** result the way round 1 examined the original 20-task
build.

## What round 2 actually did

Rather than re-deriving all ~35 original criteria from zero, this pass:

1. **Re-verified every round-1 FAIL/PARTIAL is genuinely fixed in the current
   checkout** — not just claimed in a task's `Delivered Artifacts` block. Done
   by grep/`view`-ing the actual current source and ADR text (e.g. confirming
   `cache.py` really does now expose `get_model`/`set_model`/
   `invalidate_models` and `coordinator.py` really no longer holds
   `self._models` as a raw dict; confirming `mypy.ini`'s `python_version = 3.14`
   is now valid, unquoted, ini syntax and `mypy --strict` is actually clean;
   confirming `codeql.yml` targets `master`, the real default branch).
1. **Re-ran the full toolchain live** in this sandbox: `pytest` (445/445
   passed), `mypy --config-file mypy.ini custom_components/ tests/` (clean, 53
   files), `ruff check .` (clean), `ruff format --check .` (154 files already
   formatted, zero drift — the one pre-existing drift file round 1 tolerated is
   gone).
1. **Diffed the actual bytes changed** since round 1 closed
   (`git diff --stat f7fcef8 HEAD`, `f7fcef8` = the last round-1 audit commit)
   to scope where fresh code-level review is warranted versus where a file is
   untouched since round 1 already cleared it. Only `__init__.py`, `cache.py`,
   `coordinator.py`, and `string_computation.py` changed at the `.py` level;
   every ADR file was also touched (remediation amendments, later folded into
   main prose by a `Cleanup ADR NNN` pass, then `mdformat`-reflowed — confirmed
   content-preserving by spot-checking ADR-007/007a/009/000/002 against their
   pre-cleanup amendment text).
1. **Traced the real internal import graph** (`grep` across every
   `custom_components/shady/**/*.py` for `from .`/`from ..`/`import .`) and
   diffed it against ADR-000 §3's own Mermaid diagram and prose, module by
   module — this is what round 1's own equivalent pass (AUDIT-0005/0007/0011)
   already used to catch the `aggregation --> forecast_adjust` and
   `init --> entity_glue` staleness; doing it exhaustively this time (every
   node, not just the ones an individual group's audit happened to touch)
   surfaced several more edges round 1 did not catch.
1. **Read the remediation-added test files/classes** named in
   `TASK-0021`/`0023`/`0030`–`0033`'s own `Delivered Artifacts` blocks and
   confirmed they exist with the claimed names and actually exercise the claimed
   behavior (not just that the suite is green).

## Grouping

Unchanged from round 1 — the same twelve groups still cleanly partition the
codebase (no new top-level module was added; `custom_components/shady/`'s
directory structure is identical to round 1). Findings are attached to the group
whose own file(s) most directly caused a discrepancy; where one discrepancy
touches two groups' files (an import edge between module A and module B), the
full write-up lives in whichever group's own file text originates the wrong
claim, with a one-line cross-reference in the other group's audit file — the
same convention `TASK-0027`'s own remediation used (and round 1's
AUDIT-0005/0006 cross-referenced each other) — to avoid duplicating the same
finding twice.

| # | Group | Primary files | Round-1 audit | Round-2 audit |
| -- | -- | -- | -- | -- |
| 1 | Provider Package | `providers/*.py` | AUDIT-0001 | AUDIT-0013 |
| 2 | Regression Package | `regression/*.py` | AUDIT-0002 | AUDIT-0014 |
| 3 | Cache Module | `cache.py` | AUDIT-0003 | AUDIT-0015 |
| 4 | Yield & Forecast Corrections | `yield_correction.py`, `forecast_adjust.py` | AUDIT-0004 | AUDIT-0016 |
| 5 | Coordinator | `coordinator.py` | AUDIT-0005 | AUDIT-0017 |
| 6 | String Computation Module | `string_computation.py` | AUDIT-0006 | AUDIT-0018 |
| 7 | Aggregation Module | `aggregation.py` | AUDIT-0007 | AUDIT-0019 |
| 8 | Diagnostics Package | `diagnostics/*.py` | AUDIT-0008 | AUDIT-0020 |
| 9 | HA Entity Layer | `sensor.py`, `button.py`, `select.py` | AUDIT-0009 | AUDIT-0021 |
| 10 | Config Flow & Translations | `config_flow.py`, `const.py`, `translations/*.json` | AUDIT-0010 | AUDIT-0022 |
| 11 | Integration Setup & Wiring | `__init__.py`, `services.yaml`, `manifest.json` | AUDIT-0011 | AUDIT-0023 |
| 12 | Tooling & Release Configuration | `pyproject.toml`, `mypy.ini`, `hacs.json`, `pytest.ini`, `.github/workflows/*`, `README.md`, `docs/architecture.mmd` | AUDIT-0012 | AUDIT-0024 |

## Audit Task Table

| Slug | Title | Status | Round-1 items re-verified | New findings this round | Auditor |
| -- | -- | -- | -- | -- | -- |
| AUDIT-0013-provider-package | Provider Package | done | 1 T1 decision (sunshine rescaling) — confirmed fixed | none | Lead Agent (inline) |
| AUDIT-0014-regression-package | Regression Package | done | 1 coverage gap (`predict_unclamped`) — confirmed fixed | 1 cross-ref (false diagram edge, primary write-up in AUDIT-0016) | Lead Agent (inline) |
| AUDIT-0015-cache-module | Cache Module | done | 1 FAIL (model cache location) — confirmed fixed | 1 cross-ref each (invalidate-on-failure coverage gap, primary in AUDIT-0017; false `cache --> aggregation` edge, primary in AUDIT-0017; missing `diagnostics --> cache` edge, primary in AUDIT-0020) | Lead Agent (inline) |
| AUDIT-0016-yield-forecast-corrections | Yield & Forecast Corrections | done | 1 minor coverage gap (4-strategy parametrization) — confirmed fixed | **1 FAIL fixed**: ADR-000 §3 diagram/prose — 2 false edges removed + false forward-caller claim corrected (also fixed the same claim in `tasks/adr-summary.md`; discovered and fixed 2 additional missing real edges, `coordinator --> providers` / `entity_glue --> providers`, exposed by removing the false edge) | Lead Agent (inline) |
| AUDIT-0017-coordinator | Coordinator | done | 2 ADR-text-staleness items (single merged listener; ADR-014 overclaim) — confirmed fixed; 1 acknowledged-not-scheduled gap — unchanged, still acknowledged | **1 FAIL fixed** (false `cache --> aggregation` edge → `coordinator --> aggregation`) + **1 coverage gap closed** (new `tests/test_coordinator.py::TestRefitInvalidatesStaleModelOnSubsequentFailure`, sanity-checked against a deliberately broken `coordinator.py`) | Lead Agent (inline) |
| AUDIT-0018-string-computation | String Computation Module | done | 1 FAIL (docstring false-claim) — confirmed fixed; 1 minor coverage gap — unchanged, low priority, not previously scheduled | none | Lead Agent (inline) |
| AUDIT-0019-aggregation | Aggregation Module | done | 1 FAIL outside checklist (stale `aggregation --> forecast_adjust` edge) — confirmed fixed; 1 coverage gap (Ramping/Blending divergence) — confirmed fixed | 1 cross-ref (false `cache --> aggregation` edge, fixed under AUDIT-0017) | Lead Agent (inline) |
| AUDIT-0020-diagnostics-package | Diagnostics Package | done | clean in round 1 (no FAIL, no gap) | **1 FAIL fixed**: added missing `diagnostics --> cache` diagram edge; corrected the false "coordinator.py is the only module that imports cache.py" claim in ADR-000 and `tasks/adr-summary.md` | Lead Agent (inline) |
| AUDIT-0021-entity-layer | HA Entity Layer | done | 1 PARTIAL (3 sensor classes bypass coordinator wrapper methods) — confirmed fixed (documented + `cache` made read-only); 1 coverage gap (`unique_id` distinctness) — confirmed fixed | none | Lead Agent (inline) |
| AUDIT-0022-config-flow-translations | Config Flow & Translations | done | 1 FAIL (`baseline_manual_shape` undocumented) — confirmed fixed; 2 coverage gaps (en/de key-set equality; manual-shape round-trip) — confirmed fixed | none | Lead Agent (inline) |
| AUDIT-0023-integration-setup | Integration Setup & Wiring | done | 2 PARTIALs (stale `switch` reference; diagram edges) — confirmed fixed; 3 coverage gaps (setup failure; teardown asymmetry; services.yaml symmetry) — confirmed fixed | none | Lead Agent (inline) |
| AUDIT-0024-tooling-release-config | Tooling & Release Configuration | done | 2 FAILs (`mypy.ini` syntax; `architecture.mmd` staleness) + 1 FAIL outside checklist (pytest config dupe) + 1 Test-Coverage FAIL (`codeql.yml` branch) — all confirmed fixed, live-verified; 2 coverage gaps — unchanged, both explicitly acknowledged-not-scheduled by round 1's own assessment | **1 FAIL fixed**: `README.md`'s Status line updated to reflect both rounds complete (13/13 + 4/4) | Lead Agent (inline) |

No cross-group dependencies: every group audits code that is already `done` and
stable, so groups 13–24 could run in parallel or any order — same as round

1. All 6 substantive new findings (1 in AUDIT-0016, 2 in AUDIT-0017, 1 in
   AUDIT-0020, 1 in AUDIT-0024, plus the coverage gap counted separately in
   AUDIT-0017) are **T3/T4-class** in round 1's own taxonomy
   (`AUDIT-REMEDIATION- INDEX.md`): documentation/diagram staleness or additive
   test coverage. None is a T1 (decision-pending) or T2 (tooling/CI defect) —
   every one has exactly one reasonable fix, so none carries an Open Question
   into Phase 8.

## The Auditor role

Unchanged from round 1 — see `tasks/archived/AUDIT-INDEX.md`'s "The Auditor
role" section for the full instruction text this pass followed.

## Refinement Log

| Date | Trigger | Action | Reason |
| -- | -- | -- | -- |
| 2026-09-11 | Human ("Start a new phase 7 audit. Task and Audit task numbering follow archived ones.") | Cloned `initialcode` branch; confirmed all prior work (`TASK-0001`–`0033`, `AUDIT-0001`–`0012`) is `done`/archived; created this index plus `AUDIT-0013`–`AUDIT-0024`, continuing numbering from the archived series | Human-requested fresh Phase 7 audit pass over the post-remediation codebase |
| 2026-09-11 | Lead Agent | Installed `mypy`/`pytest`/`pytest-asyncio`/`pytest-cov`/`ruff==0.16.4`/`voluptuous`/`numpy` in sandbox; ran full suite (445/445 passed), `mypy --strict` (clean), `ruff check`/`ruff format --check` (both clean) | Live-verify round-1's FAILs are genuinely fixed, not just claimed, before writing round-2 findings |
| 2026-09-11 | Lead Agent | Traced the complete internal import graph via `grep` across every `custom_components/shady/**/*.py` and diffed it against ADR-000 §3's Mermaid diagram + prose | Systematic check the same class of finding (`aggregation --> forecast_adjust`) round 1 only caught incidentally, per-group |
| 2026-09-11 | Lead Agent | Generated `AUDIT-0013`–`AUDIT-0024` findings; no code/test/ADR file modified | Phase 7 rule 6 — audits are generated, not executed, during this phase |
| 2026-09-12 | Human ("Start a new phase 8.") | Resumed session against the `initialcode` branch; re-verified all 12 round-2 audit tasks and re-ran the full toolchain (445/445 tests, mypy --strict clean, ruff clean) before touching anything | Phase 8 trigger — proceed with the audit tasks from Phase 7 |
| 2026-09-12 | Lead Agent | Processed `AUDIT-0017-coordinator`: fixed the false `cache --> aggregation` diagram edge (→ `coordinator --> aggregation`); added `tests/test_coordinator.py::TestRefitInvalidatesStaleModelOnSubsequentFailure`, sanity-checked by temporarily disabling `invalidate_models()` and confirming the test fails, then restoring the file. Status → `done`. | Open Questions: none — single reasonable fix per the audit task's own Definition of Done; no live decision needed |
| 2026-09-12 | Lead Agent | Processed `AUDIT-0016-yield-forecast-corrections`: removed 2 false diagram edges (`yield_correction --> providers`, `regression --> yield_correction`); corrected the `yield_correction.py` forward-caller prose (`regression/` → `string_computation.py`) in both `adr/000-coding-standards.md` and `tasks/adr-summary.md`. Status → `done`. | same — no Open Questions |
| 2026-09-12 | Lead Agent | Scenario-B-style discovery mid-fix: removing the false `yield_correction --> providers` edge left the `providers` node with zero edges, though `coordinator.py` and `config_flow.py` (`entity_glue`) both really import it. Added the two real missing edges (`coordinator --> providers`, `entity_glue --> providers`) as part of the same `AUDIT-0016` fix rather than leaving the diagram newly wrong in a different way | Diagram accuracy is `AUDIT-0016`'s own stated goal; the gap was a direct side effect of that task's own edit, not unrelated scope |
| 2026-09-12 | Lead Agent | Processed `AUDIT-0020-diagnostics-package`: added the missing `diagnostics --> cache` diagram edge; corrected the false "coordinator.py is the only module that imports cache.py" claim in `adr/000-coding-standards.md` and `tasks/adr-summary.md`, narrowed to the accurate claim (only module holding a `Cache` instance / calling its methods). Status → `done`. | same — no Open Questions |
| 2026-09-12 | Lead Agent | Processed `AUDIT-0024-tooling-release-config`: updated `README.md`'s stale "9/13 remediation tasks done" status line to reflect both rounds complete (13/13 round 1, 4/4 round 2). Status → `done`. | same — no Open Questions |
| 2026-09-12 | Lead Agent | Closed the remaining 8 round-2 audit tasks (`AUDIT-0013`/`0014`/`0015`/`0018`/`0019`/`0021`/`0022`/`0023`) from `review` → `done`; each had "no independent fix scheduled" in its own Definition of Done (either clean, or its one live finding's fix is tracked and delivered under a cross-referenced sibling task) | Close the audit trail — nothing left pending for any round-2 group |
