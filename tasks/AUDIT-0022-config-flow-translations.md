# Audit Task: Config Flow & Translations (Round 2)

- **Status:** done
- **Group:** `custom_components/shady/config_flow.py`,
  `custom_components/shady/const.py`,
  `custom_components/shady/translations/en.json`,
  `custom_components/shady/translations/de.json`
- **Related ADRs:** [ADR-010, ADR-001 §1/§4a, ADR-009 §3]
- **Source Tasks:** \[TASK-0018-config-flow-and-options,
  TASK-0028-adr010-field-documentation-catchup,
  TASK-0032-entity-layer-config-flow-coverage-additions\]

## Scope

Re-audits round 1's `AUDIT-0010-config-flow-translations` (1 FAIL, 2 coverage
gaps). `config_flow.py`/`const.py`/`translations/*.json` have zero byte changes
since round 1 (confirmed via `git diff --stat f7fcef8 HEAD` — the fix for the
FAIL below is documentation-only, landing in `adr/010-config-flow- shape.md`,
not in these source files).

## Findings — Code Logic vs. ADRs

- **Round-1 item — `baseline_manual_shape` undocumented in ADR-010 (RESOLVED).**
  `AUDIT-0010` found the config-flow schema field `baseline_ manual_shape`
  implemented and tested in `config_flow.py` but absent from ADR-010's own
  field-by-field schema documentation. `TASK-0028` added it — confirmed:
  `grep -n "baseline_manual_shape" adr/010-config-flow-shape.md` returns matches
  documenting the field (name, purpose, allowed values, default), consistent
  with every other documented field in that ADR. **PASS.**
- No other deviations found. The multi-step flow shape, options-flow parity, and
  per-string schema construction (ADR-010, ADR-001 §1/§4a, ADR-009 §3) all match
  round 1's confirmed reading.

## Findings — Test Coverage vs. ADRs

- **Round-1 item 1 — en/de translation key-set equality (RESOLVED).**
  `AUDIT-0010` found no test asserting `en.json` and `de.json` declare exactly
  the same set of keys (a silent key drop in one locale would previously go
  undetected). `TASK-0032` added it — confirmed: `tests/test_translations.py`
  contains a key-set-equality test between the two locale files (grep for a
  `test.*key` pattern in the file shows the added assertion). **PASS.**
- **Round-1 item 2 — `baseline_manual_shape` round-trip through the real
  normalizer (RESOLVED).** `AUDIT-0010` found the field accepted by the schema
  but never round-tripped through `providers/normalize.py`'s actual parser in a
  test — only through hand-constructed stand-ins. `TASK-0032` added a test that
  selects a manual shape through the real config-flow schema and confirms it
  parses correctly through the real normalizer — confirmed present in
  `tests/test_config_flow.py` (grep for a `test.*(manual|normalize|shape)`
  pattern shows the added test). **PASS.**
- No new gap found. Full config-flow/translations test files re-run live this
  session as part of the full suite — passing.

## Open Questions

None.

## Definition of Done (for Phase 8)

- N/A — no unresolved finding in this group this round.

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8 — not applicable, no fix scheduled. -->

- No Phase 8 task required for this group.
