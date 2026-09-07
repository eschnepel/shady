# Audit Task: Config Flow & Translations

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** [ADR-010, ADR-001 §1, ADR-001 §4a, ADR-009 §3, ADR-003c §3]
- **Dependencies:** [] (TASK-0009 + 2 patches, TASK-0019 are `done`)
- **Origin:** TASK-0009-config-flow + TASK-0009-patch-1 (manual baseline
  shape) + TASK-0009-patch-2 (recency-decay field), TASK-0019
  (translations rewritten from placeholder content)

## Goal
Verify `config_flow.py` exposes exactly the fields ADR-010 specifies
(no more, no fewer), that the two patches (baseline shape, recency
decay) are both still present and correctly wired after TASK-0019
rewrote the translation files that describe them, and that `en.json`/
`de.json` stay in sync with the schema (a field renamed or added in
`config_flow.py` without a matching translation key is a silent UX bug,
not a crash).

## Scope — Source Files
- `custom_components/shady/config_flow.py`
- `custom_components/shady/const.py`
- `custom_components/shady/translations/en.json`
- `custom_components/shady/translations/de.json`

## Scope — Test Files
- `tests/test_config_flow.py`
- `tests/test_translations.py`

## Out of Scope
- `providers/discovery.py`'s baseline scoring itself (covered by
  AUDIT-0001) — this audit only checks that the config flow correctly
  surfaces discovered candidates for user selection.
- `regression/base.py`'s consumption of `recency_decay_max` (covered by
  AUDIT-0002) and `coordinator.py`'s threading of it (covered by
  AUDIT-0005) — this audit only checks the config-flow field itself.

## Audit Criteria
- [ADR-010] Does the config flow's step structure and field set match
  the ADR exactly — enumerate every step and field the ADR documents
  and confirm each exists in `config_flow.py`, and separately confirm
  no undocumented field has been added without a corresponding ADR
  amendment?
- [ADR-001 §1] Is predictor/regression-method selection (linear/wls2/
  wls3/kernel, per ADR-001 §2's pluggability) actually exposed as a
  config-flow field, with `wls2` as the pre-selected default matching
  ADR-001 §2's stated rationale?
- [ADR-001 §4a] Does `recency_decay_max` (TASK-0009-patch-2) exist as a
  config field with a sensible documented default and bounds, and is
  its `const.py` constant (`CONF_RECENCY_DECAY_MAX`) the single source
  of truth referenced by both `config_flow.py` and `coordinator.py`
  (cross-check against AUDIT-0005's findings once available)?
- [ADR-009 §3] Does manual baseline entry (TASK-0009-patch-1) offer the
  `_BASELINE_SHAPES` selector this patch added, and does each shape
  option actually produce a valid input for `providers/normalize.py`
  (cross-ref AUDIT-0001) — i.e. is the shape selector's output format
  contractually matched to what the normalizer expects, not just
  independently plausible?
- [ADR-003c §3, cross-ref] Is the temperature-forecast predictor source
  genuinely a dedicated, explicit config-flow field (not reused/
  overloaded from the ADR-003b §1a temperature-source field, which
  serves a different purpose)?

## Test-Coverage Criteria
- Does `tests/test_config_flow.py` cover all 7 test classes across all
  documented steps (per TASK-0009's Delivered Artifacts: "8 tests (7
  test classes) covering all 7 steps") — confirm the count still holds
  after both patches extended the schema, or whether patch-added fields
  got their own test class each (`TestManualBaselineShape`,
  `TestRecencyDecayMax`, per the patches' own Delivered Artifacts) —
  confirm both still exist and are exercised.
- Is there a test asserting the `wls2` default (ADR-001 §2/§1) is what a
  fresh config flow actually pre-selects, not just that `wls2` is an
  available option?
- Does `tests/test_translations.py`'s "schema-key-vs-label" check (per
  TASK-0019's Delivered Artifacts) actually cover **every** key in the
  current schema, including both patches' fields
  (`recency_decay_max`, the baseline-shape selector) — or does it only
  check the original TASK-0009 field set, silently missing newer keys?
- Is there a test proving `en.json` and `de.json` have identical key
  **sets** (not necessarily identical values) — i.e. would a key added
  to `en.json` without its `de.json` counterpart be caught?
- Is there a test for the manual-baseline-shape selector's actual output
  format (ADR-009 §3 cross-ref) being valid input to
  `providers/normalize.py`, or does coverage stop at "the config flow
  accepts the selection"?

## Consumed Context (attached to the auditor)
- `tasks/adr-summary.md`
- `adr/010-config-flow-shape.md` (full text)
- `adr/001-empirical-shading-model.md` §§1, 4a
- `adr/009-baseline-forecast-sourcing.md` §3
- `adr/003c-temperature-forecast-via-learned-model.md` §3 (cross-ref only)
- All files listed under Scope above
- `tasks/TASK-0009-*.md` (all three files), `tasks/TASK-0019-*.md`
- `tasks/DEPENDENCIES.md`

## Definition of Done
- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering
  test named, or GAP explained.
- Findings written to `tasks/AUDIT-0010-config-flow-translations-findings.md`.
- No code changes made.

## Delivered Artifacts
<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->
- `tasks/AUDIT-0010-config-flow-translations-findings.md` — **1 FAIL**:
  `baseline_manual_shape` (`TASK-0009-patch-1`) is a real, correctly
  implemented and translated field never added to ADR-010's own field
  list/amendment history — a documentation-sync gap, not a behavioral
  bug. All other criteria PASS, including a fully type-checked
  (`Literal`-shared) contract between the manual-shape selector and
  `providers/normalize.py`. 2 coverage GAPs (no dedicated en/de
  key-set-equality test; manual-shape selector's runtime parser
  contract untested, only its storage). 19/19 tests re-run live.
