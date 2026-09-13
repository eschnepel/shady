# Audit Task: Provider Package (Round 2)

- **Status:** done
- **Group:** `custom_components/shady/providers/*.py` (`base.py`,
  `discovery.py`, `normalize.py`, `temperature.py`)
- **Related ADRs:** [ADR-009, ADR-012 §1/§1a, ADR-003b §1a]
- **Source Tasks:** \[TASK-0001-provider-base-architecture,
  TASK-0003-baseline-forecast-discovery, TASK-0004-temperature-source-provider,
  TASK-0022-sunshine-duration-rescaling\]

## Scope

Re-audits round 1's `AUDIT-0001-provider-package` finding against the current
checkout. `providers/*.py` itself has **zero byte changes** since round 1's
audit commit (`git diff --stat f7fcef8 HEAD` shows no `providers/` file in the
changed set) — this group's own code carries no fresh regression risk. The
purpose of this pass is to confirm round 1's one T1 decision item was actually
closed out correctly, and to re-run the group's tests live.

## Findings — Code Logic vs. ADRs

- **Round-1 item — sunshine-duration rescaling (RESOLVED).** `AUDIT-0001` found
  ADR-009 §1's text claimed sunshine-duration baseline values are "only
  rescaled" to the baseline's expected range, while `providers/normalize.py`
  never performs that rescale. `TASK-0022` recorded the human's decision
  ("Proceed with Option A" — amend the ADR, no code change) and delivered a
  rewrite of ADR-009 §1. Confirmed current text at
  `adr/009-baseline-forecast-sourcing.md:8-10`: the sunshine-duration bullet now
  reads as a "description-only fix... it was \[determined the regression's
  scale-invariance means it\] needs no rescale step; no behavior change."
  `providers/normalize.py` itself unchanged — `git diff --stat f7fcef8 HEAD`
  confirms zero touches to this file since round 1. **PASS.**
- No new deviations found. `discover_baseline_candidates`
  (`providers/discovery.py`), `assemble_series`/`map_state_value`
  (`providers/base.py`), and `TemperatureProvider`/`TemperatureTier`
  (`providers/temperature.py`) match ADR-012 §1/§1a's `Provider` ABC shape and
  ADR-003b §1a's temperature-source hierarchy exactly as round 1 confirmed —
  re-spot-checked, no drift.

## Findings — Test Coverage vs. ADRs

- `tests/test_providers_discovery.py`, `tests/test_providers_normalize.py`,
  `tests/test_providers_base.py`, `tests/test_providers_temperature.py` — all
  present, unchanged since round 1 (not in the post-round-1 changed-file diff).
  Re-run live this session as part of the full suite: all pass (part of the
  445/445 total, see `tasks/AUDIT-INDEX.md`).
- Round 1's one acknowledged-but-not-scheduled item (a tie-break-ordering test
  for `discover_baseline_candidates` when two candidates score identically)
  remains acknowledged-not-scheduled — no change in its risk profile; the user
  still always confirms a candidate manually regardless of list order, per round
  1's own rationale in `tasks/archived/AUDIT-REMEDIATION-INDEX.md`. Coverage
  otherwise matches ADR requirements.

## Open Questions

None. No new finding in this group requires a decision.

## Definition of Done (for Phase 8)

- N/A — this audit found no unresolved FAIL/PARTIAL/GAP requiring a Phase 8 fix.
  Recorded here for the audit trail only.

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8 — not applicable, no fix scheduled. -->

- No Phase 8 task required for this group.
