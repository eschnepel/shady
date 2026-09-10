# Task: ADR-010 Field Documentation Catch-Up

- **Status:** done
- **Related ADRs:** [ADR-010]
- **Dependencies:** [TASK-0009-patch-1-manual-baseline-shape]

## Goal
`AUDIT-0010-config-flow-translations` found a FAIL: `config_flow.py`'s
`baseline_manual_shape` field (added by `TASK-0009-patch-1`, correctly
implemented, tested, and translated) was never added to ADR-010's own
field list or amendment history — contradicting ADR-010's own stated Con
("this document has to be kept in sync whenever a future ADR adds or
changes a field"). The sibling `recency_decay_max` field, added by a
different patch around the same time, *did* get a proper amendment entry
(`2026-08-25`); this one was missed. This is a documentation-only gap —
no code defect.

## Known Decisions
- The field itself needs no code review — `AUDIT-0010` already confirmed
  it is correctly implemented (a type-checked `Literal` contract with
  `providers/normalize.py`), tested, and translated in both `en.json`/
  `de.json`.
- The fix is exactly one new ADR-010 amendment entry, in the same format
  as the existing `2026-08-25` `recency_decay_max` entry — no new
  format or structure needed.

## Open Questions for Execution
- **One small date-attribution choice, low-stakes:** should the new
  amendment entry be dated at `TASK-0009-patch-1`'s original completion
  date (retroactive, matching when the field actually shipped), or dated
  at this task's own completion (matching when the documentation gap was
  actually closed)? `AUDIT-0010`'s own candidate follow-up explicitly
  frames this as "the human's call." **Default to dating it at this
  task's own completion if the human has no preference** — it's more
  honest about when the ADR text itself changed, and matches how this
  project's other post-hoc documentation fixes (e.g. `TASK-0018`) are
  dated.

## Acceptance Criteria
- Given `adr/010-config-flow-shape.md`, When read after this task, Then
  it carries a new, dated Amendment entry documenting
  `baseline_manual_shape` as a "settings" step field — mirroring the
  existing `2026-08-25` `recency_decay_max` amendment's format
  (field name, step, purpose, and a one-line cross-reference to the
  patch task that added it).
- Given `tasks/adr-summary.md`, When checked after this task, Then it
  is confirmed still accurate — `AUDIT-0010` already found no existing
  `adr-summary.md` reference to this field either way, so no separate
  summary edit is expected unless this task's own read finds otherwise.
- Given the full test suite, When run after this task, Then it is
  unchanged (this task touches no `.py` file).

## Estimated File / Module Footprint (hint, not a commitment)
- `adr/010-config-flow-shape.md` only (plus a confirmation-only read of
  `tasks/adr-summary.md`, no edit expected).

## Definition of Done
- Tests green (unchanged) · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/config_flow.py` →
  `_BASELINE_SHAPES`/`baseline_manual_shape` field (`vol.Optional`,
  default `"sensor_dict"`) — (→ task:
  TASK-0009-patch-1-manual-baseline-shape) — the field this task
  documents; no code change, only citing its exact shape/default
  accurately in the new amendment text.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
- `adr/010-config-flow-shape.md` → new header amendment entry, dated
  `2026-09-10`, documenting `baseline_manual_shape` (global, default
  `"sensor_dict"`, one of `"sensor_dict"`/`"sensor_list"`/
  `"weather_sunshine"`/`"weather_cloud"`, "settings" step) as a
  `TASK-0009-patch-1-manual-baseline-shape`-introduced field — format
  mirrors the existing `2026-08-25` `recency_decay_max` entry exactly
  (field name, step, purpose, one-line cross-reference to the patch
  task). Field's exact shape/default confirmed against
  `custom_components/shady/config_flow.py`'s own `_settings_schema`/
  `_BASELINE_SHAPES`/`_DEFAULT_MANUAL_SHAPE` — no code change, citation
  only.
- **Open Question resolved:** dated the entry at this task's own
  completion (2026-09-10), per the task's own stated default ("if the
  human has no preference") — no preference was given, so the default
  applied. Not escalated, since the task itself already resolved this
  as a low-stakes default rather than a blocking decision.
- `tasks/adr-summary.md` checked (Acceptance Criteria requirement) — no
  existing reference to `baseline_manual_shape` found either way (§7
  defers to ADR-010 as "the single source of truth" for the full field
  list), so no edit made, matching this task's own stated expectation.
- `git status --short` confirms exactly `adr/010-config-flow-shape.md`
  changed — no `.py` file touched.
- No new external dependency — `tasks/DEPENDENCIES.md` unchanged.
- Verification: full suite 445/445 passed, unchanged (docs-only
  change); `mypy --config-file mypy.ini custom_components/ tests/`
  clean on 53 source files; `ruff check .` clean repo-wide; `ruff
  format --check .` shows only the same one pre-existing, unrelated,
  already-documented drift file every prior remediation task in this
  batch has also seen, untouched.
- Reviewer pass (Phase 4b, inline): all three Acceptance Criteria
  verified against the delivered diff — **PASS**.
