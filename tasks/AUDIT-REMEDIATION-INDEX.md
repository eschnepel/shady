# Audit Remediation Index — Grouping, Weighting & Task Mapping

**Status of this phase:** Planning. `AUDIT-0001` through `AUDIT-0012` are
all `review` (findings written, nothing fixed — see `tasks/AUDIT-INDEX.md`).
This file is the human-requested next step: every FAIL / PARTIAL /
Test-Coverage GAP recorded across the twelve findings files is grouped by
**type** and **impact**, given a **weight**, and mapped onto a concrete
`TASK-0021`–`TASK-0033` remediation task. Nothing has been implemented by
this planning pass — every new task below is created `todo`.

## Why group before scheduling

Twelve findings files produced ~35 distinct, independently-evidenced
items. Fixing each as its own task would mean 35 tiny review cycles, most
of them one-line text edits with no code risk; treating them all as one
task would violate this project's own "every task limited in scope"
rule and bury a Critical CI-security gap inside the same review pass as
a docstring typo. Grouping by **root cause / file cluster** (the same
principle `TASK-0018`/`TASK-0019`/`TASK-0020` already used for
AUDIT-series-adjacent findings back in 2026-09-05) keeps each task
reviewable while keeping the total task count manageable.

## Type taxonomy

| Type | Definition |
|---|---|
| **T1 — Decision-Pending Architecture Deviation** | Code and ADR text disagree, and *both* readings are defensible — a human must choose "amend the ADR" vs. "change the code" before a worker can proceed. Golden-rule escalations, not staleness. |
| **T2 — Tooling / CI Config Defect** | A build, lint, type-check, security-scan, or release-pipeline mechanism is silently not doing what it's configured to look like it does. |
| **T3 — ADR / Docs Staleness** | Code is correct and already reviewed; the *description* of it (an ADR's prose/diagram, a module docstring, README) has drifted. No behavior change, no decision — just propagate an already-made decision into text. |
| **T4 — Test-Coverage Gap** | Behavior is correct today; no test would fail if it regressed. Additive-only, no production code change. |

## Impact scale

| Impact | Meaning |
|---|---|
| **Critical** | A safety/security-relevant gate is silently not running at all. |
| **High** | An enforcement mechanism (type floor, dependency pin) is silently defeated — a real regression could land undetected. |
| **Medium** | A real architectural question is open (correctness-adjacent, or a high-visibility document is actively misleading), or a coverage gap sits on a genuinely plausible regression path. |
| **Low** | Text-only drift with no behavioral consequence, or a coverage gap on a low-probability / already-indirectly-covered regression. |

## Weighting formula

`Weight (1–10) = Impact base (Critical=9, High=7, Medium=5, Low=2)
+ blast-radius adjustment (0–2, how many other findings/files share the
same root cause or how central the affected mechanism is) − isolation
credit (0–1, fully self-contained fixes with no cross-file coordination
needed)`. This is a prioritization aid, not a formal metric — ties are
broken by cheapest-fix-first within the same weight band.

## Grouped Findings

### Group 1 — T2, Critical: CI security gate never runs

| Finding | Source | Weight |
|---|---|---|
| `codeql.yml` targets branch `"main"`, repo's real default is `master` — CodeQL never runs on push/PR, only a weekly cron | AUDIT-0012 §Test-Coverage #3 | **10** |

→ **TASK-0024**

### Group 2 — T2, High/Medium: Silently-defeated build-gate config

| Finding | Source | Weight |
|---|---|---|
| `mypy.ini`'s `python_version = "3.14"` is invalid ini syntax; mypy silently falls back to auto-detected version instead of enforcing the 3.14 floor | AUDIT-0012 Criterion 4 | **8** |
| `pytest.ini` and `pyproject.toml`'s `[tool.pytest.ini_options]` both configure pytest; `pytest.ini` silently wins, `pyproject.toml`'s `pythonpath` entry is dead — same dead-duplicate-config class `TASK-0020` already fixed once for `mypy.ini`/`[tool.mypy]` | AUDIT-0012 §Additional finding | **6** |
| `pyproject.toml`'s dev-group `"ruff"` is unpinned while `.pre-commit-config.yaml` pins a `rev` — the exact pattern that already caused one real formatting disagreement once (per `TASK-0020`'s own notes); flagged then, never scheduled | AUDIT-0012 §Additional finding | **5** |

→ **TASK-0025** (batched — same tooling-config-hygiene root cause `TASK-0020` addressed; a direct "round 3")

### Group 3 — T1, Medium/Medium-High: Pending architecture decisions

| Finding | Source | Weight |
|---|---|---|
| Fitted-model cache (`self._models`/`self._temperature_models`) lives in `coordinator.py`, not `cache.py` — contradicts ADR-007 §1 / ADR-007a §5's explicit text | AUDIT-0003 | **6** |
| Sunshine-duration baseline values are never rescaled, contradicting ADR-009 §1's explicit "only rescaled" wording (regression's scale-invariance may make this moot — human call) | AUDIT-0001 | **5** |
| Three of `sensor.py`'s nine entity classes read `coordinator.cache` directly, bypassing the coordinator-method convention the other six follow; undocumented in ADR-000 §3's diagram | AUDIT-0009 | **4** |

→ **TASK-0021**, **TASK-0022**, **TASK-0023** respectively — kept as three separate tasks (not batched) because each has an independent decision, independent files, and independent human answer; batching would force one review gate to wait on three unrelated judgment calls.

### Group 4 — T3, Medium: High-visibility misleading document

| Finding | Source | Weight |
|---|---|---|
| `README.md`'s "Core idea" section duplicates decision rationale that belongs in `adr/` (violates ADR-000 §7); its own **Status** line says "Brainstorming / Concept phase" against a 20/20-tasks-done, 419-tests-green, 12-audits-complete codebase | AUDIT-0012 Criterion 6 | **5** |

→ **TASK-0029**

### Group 5 — T3, Low: Switch→select rename residue (round 3)

| Finding | Source | Weight |
|---|---|---|
| `docs/architecture.mmd` still shows the pre-2026-08-30 `switch`-based diagnostics architecture — the one file `TASK-0018`'s dedicated cleanup missed | AUDIT-0012 Criterion 7 | **3** |
| ADR-002 §1a's own decision text still says "`sensor`/`switch`/`button`" | AUDIT-0011 Criterion 5 | **3** |
| ADR-007's own module diagram also still lists `switch.py` (found incidentally, out of AUDIT-0011's declared scope, same defect) | AUDIT-0011 Criterion 5 (incidental) | **2** |

→ **TASK-0026** (batched — identical root cause and fix pattern as `TASK-0018`)

### Group 6 — T3, Low: Module-diagram / call-graph / docstring accuracy

| Finding | Source | Weight |
|---|---|---|
| ADR-005's and ADR-000 §3's module diagrams both claim an `aggregation --> forecast_adjust` edge that doesn't exist in code | AUDIT-0007 | **3** |
| ADR-000 §3's diagram draws `init --> entity_glue` (no real import behind it) and omits the real `init --> coordinator` edge | AUDIT-0011 Criterion 4 | **3** |
| ADR-002 §5 / Consequences describes two listener registrations; code has one merged listener | AUDIT-0005 finding A | **3** |
| ADR-014 §4's "all four... delegate everything to `string_computation.py`" overclaims — `_predict_day_basis`/`_clamp_basis` justifiably don't, for a documented reason the ADR text itself omits | AUDIT-0005 finding B | **3** |
| `string_computation.py`'s own module docstring and `predict_string_forecast`'s docstring falsely claim `coordinator.py`'s no-intraday path calls it — it never does (same underlying fact as the row above, viewed from the source file) | AUDIT-0006 | **4** (touches a source file's docstring, not just an ADR) |
| ADR-000 §1 names a `ci.yml` file that doesn't exist (real file: `code_checker.yml`) and states literal invocation strings that don't match how `pre-commit` actually invokes each tool | AUDIT-0012 Criterion 1 | **2** |

→ **TASK-0027** (batched — all are "the description drifted, the behavior didn't," no decisions, safe to fix together in one documentation pass; the ADR-005/ADR-002/ADR-014/string_computation items are explicitly cross-referenced to each other by their own audits)

### Group 7 — T3, Low: Missing ADR field entry

| Finding | Source | Weight |
|---|---|---|
| `baseline_manual_shape` (added by `TASK-0009-patch-1`, correctly implemented/tested/translated) was never added to ADR-010's own field list or amendment history | AUDIT-0010 Criterion 1 | **2** |

→ **TASK-0028**

### Group 8 — T4, Low/Medium: Test-coverage additions, pure/correction layer

| Finding | Source | Weight |
|---|---|---|
| No test in `test_regression.py` calls `predict_unclamped()` directly on a real strategy (only incidental coverage in a different audit group's test file) | AUDIT-0002 §Test-Coverage #5 | **4** |
| No test in `test_forecast_adjust.py` parametrizes over all four real `regression/` strategies (only hand-built stub models) | AUDIT-0004 §Test-Coverage #5 | **3** |
| No differential test cross-checks `get_regression_pools`'s cell values against `get_pinned_slot_pool`'s single-slot read for the same sensor/index | AUDIT-0003 §Test-Coverage #6 | **2** |

→ **TASK-0030**

### Group 9 — T4, Low: Intraday divergence coverage

| Finding | Source | Weight |
|---|---|---|
| Ramping's and Blending's outputs are never asserted as genuinely *different* mid-ramp — only their convergence at `w=1` is tested; a regression that swapped which mode calls `crossfade` would slip through | AUDIT-0007 §Test-Coverage #4 | **3** |

→ **TASK-0031**

### Group 10 — T4, Low/Medium: Entity-layer & config-flow coverage

| Finding | Source | Weight |
|---|---|---|
| No test asserts `unique_id` distinctness with a real ≥2-string fixture in the entity layer's own test files | AUDIT-0009 §Test-Coverage #4 | **4** |
| No test compares `en.json`/`de.json` key **sets** directly (only per-language schema-key coverage) | AUDIT-0010 §Test-Coverage #4 | **3** |
| No test proves the manual-baseline-shape selector's stored output is valid input to `providers/normalize.py` — coverage stops at "the flow stores it" | AUDIT-0010 §Test-Coverage #5 | **3** |

→ **TASK-0032**

### Group 11 — T4, Low/Medium: Integration-setup coverage & undocumented teardown asymmetry

| Finding | Source | Weight |
|---|---|---|
| No test for a genuine (non-`ConfigEntryNotReady`) setup-time failure, e.g. a malformed config entry | AUDIT-0011 §Test-Coverage #3 | **4** |
| `async_unload_entry` deliberately never unregisters the domain-wide service on a single entry's unload — a defensible design, but neither documented nor tested either way | AUDIT-0011 §Test-Coverage #2 | **3** |
| No executable test cross-checks `services.yaml` against actually-registered service handlers (only this audit's manual check) | AUDIT-0011 §Test-Coverage #4 | **3** |

→ **TASK-0033**

## Items acknowledged but not scheduled

Two low-value, structurally-hard-to-test items are recorded here rather
than given a task, matching each audit's own "optional, low priority"
framing — creating a task for these would cost more review attention
than the residual risk justifies:

- A tie-break ordering test for `discover_baseline_candidates` when two
  candidates score identically (AUDIT-0001 §Test-Coverage #2) — cosmetic,
  the user always confirms a candidate manually regardless of list order.
- "Duplication regression" tests proving `providers/`,
  `string_computation.py`, and `coordinator.py` *delegate* rather than
  *reimplement* (AUDIT-0001 #1, AUDIT-0005 #4, AUDIT-0006 #1) — an
  absence-of-a-second-implementation property isn't naturally
  unit-testable; static `grep` at audit time is the practical substitute
  and was already performed three times.
- The bare-`np.ndarray`-typechecks-cleanly gap (AUDIT-0012 §Test-Coverage
  #1) is self-acknowledged already in ADR-000 §4's own text as a
  convention enforced by review, not tooling — no fix is proposed by the
  audit itself.
- A CI check keeping `docs/architecture.mmd` in sync with the real
  module graph (AUDIT-0012 §Test-Coverage #4) — `TASK-0027` fixes the
  current drift; a structural sync-checker was judged more effort than
  the diagram's churn rate justifies, per the audit's own assessment.

## Weight summary (highest first)

| Weight | Task | Type | Title |
|---|---|---|---|
| 10 | TASK-0024 | T2 | CodeQL branch-target fix |
| 8 | TASK-0025 | T2 | Tooling config hardening, round 3 |
| 6 | TASK-0021 | T1 | Fitted-model cache location — decision & fix |
| 5 | TASK-0022 | T1 | Sunshine-duration rescaling — decision & fix |
| 5 | TASK-0029 | T3 | README accuracy refresh |
| 4 | TASK-0023 | T1 | Entity-layer cache-access boundary — decision & fix |
| 4 | TASK-0027 | T3 | Module-diagram & docstring call-graph accuracy |
| 4 | TASK-0030 | T4 | Regression & correction-layer coverage additions |
| 4 | TASK-0032 | T4 | Entity-layer & config-flow coverage additions |
| 4 | TASK-0033 | T4 | Integration-setup coverage & teardown-semantics |
| 3 | TASK-0026 | T3 | Finish switch→select rename, round 3 |
| 3 | TASK-0031 | T4 | Intraday Ramping-vs-Blending divergence test |
| 2 | TASK-0028 | T3 | ADR-010 field documentation catch-up |

## Suggested execution order

Not a hard dependency chain (see each task's own `Dependencies` field
for the real constraints) — but a sensible order given the weights and
the project's own "strictly sequential, one zip per task" working
pattern when no sub-agents are available:

1. **TASK-0024** (Critical, trivial fix, zero ambiguity once the branch
   question is answered)
2. **TASK-0025** (High, tooling-only, no ADR/decision blocking)
3. **TASK-0021, TASK-0022, TASK-0023** (the three decision-pending
   items — front-load these since they need human input; the answer
   may also inform wording choices in TASK-0027)
4. **TASK-0029, TASK-0026, TASK-0027, TASK-0028** (documentation-only,
   safe to batch/parallelize once 0021–0023's decisions are known)
5. **TASK-0030, TASK-0031, TASK-0032, TASK-0033** (additive test
   coverage, lowest risk, can run anytime — deprioritized only because
   they add no new guarantee about *today's* known gaps, just guard
   against future regressions)

## Refinement Log

| Date | Trigger | Action | Reason |
|------|---------|--------|--------|
| 2026-09-08 | Lead Agent, human request ("group issues by impact and type, weight and create tasks for changing") | Created this index plus `TASK-0021` through `TASK-0033`, grouping all findings from `AUDIT-0001`–`AUDIT-0012` by type/impact/weight | Closes the audit series' own stated "Next steps": every recorded FAIL/PARTIAL/GAP is now either scheduled as a task or explicitly acknowledged-not-scheduled with rationale, per the human's request for a grouped, weighted remediation plan |
