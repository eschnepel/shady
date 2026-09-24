# Audit Task: Integration Setup & Wiring (Round 2)

- **Status:** done
- **Group:** `custom_components/shady/__init__.py`,
  `custom_components/shady/services.yaml`,
  `custom_components/shady/manifest.json`
- **Related ADRs:** [ADR-002 §1/§1a/§4, ADR-007 §4, ADR-000 §3]
- **Source Tasks:** \[TASK-0019-integration-setup-and-services,
  TASK-0026-switch-select-rename-cleanup-round-3,
  TASK-0027-module-diagram-and-docstring-accuracy,
  TASK-0033-integration-setup-coverage-and-teardown-semantics\]

## Scope

Re-audits round 1's `AUDIT-0011-integration-setup` (2 PARTIALs, 3 coverage
gaps). `__init__.py` gained a docstring-only addition since round 1
(`git diff f7fcef8 HEAD -- custom_components/shady/__init__.py` — a
teardown-asymmetry explanation, no logic change);
`services.yaml`/`manifest.json` are byte-for- byte unchanged.

## Findings — Code Logic vs. ADRs

- **Round-1 item 1 — stale `switch` reference in ADR-002 §1a (RESOLVED).**
  `AUDIT-0011` found ADR-002 §1a still listing `sensor`/`switch`/`button` as the
  forwarded platforms, when the actual, current platform set is
  `sensor`/`select`/`button` (the `switch` naming was replaced by `select`
  earlier in the project). `TASK-0026` fixed the reference — confirmed:
  `adr/002-coordinator-update-strategy.md:113-114` now reads *"forward this
  config entry's platforms (`sensor`/`select`/`button`) exactly as usual."* A
  repo-wide residue check
  (`grep -rniI "switch" custom_components docs adr hacs.json`, excluding
  legitimate UI/config uses of the word "switch" as a verb or the diagnostic
  three-state concept) finds no remaining stale platform references. **PASS.**
- **Round-1 item 2 — ADR-000 §3 diagram's `init`/`entity_glue` edges
  (RESOLVED).** `AUDIT-0011` found a false `init --> entity_glue` edge (no such
  import exists — `__init__.py` never imports `sensor.py`/`button.py`/
  `select.py` directly; Home Assistant's platform-forwarding mechanism handles
  that) and a missing real `init --> coordinator` edge. `TASK-0027` fixed both —
  confirmed: the current diagram (`adr/000-coding-standards.md:117`) shows
  `init --> coordinator` and contains no `init --> entity_glue` edge.
  Cross-checked against `__init__.py`'s actual imports
  (`grep -n "^from \." custom_components/shady/__init__.py`) — matches.
  **PASS.**
- No other deviations found in `async_setup_entry`/`async_unload_entry`'s wiring
  or `services.yaml`'s service registration shape (ADR-002 §1/§4, ADR-007 §4).

## Findings — Test Coverage vs. ADRs

- **Round-1 item 1 — malformed-config-entry setup failure (RESOLVED).**
  `AUDIT-0011` found no test exercising `async_setup_entry` with a structurally
  invalid config entry that should fail with a genuine, unhandled setup error
  (as opposed to the `ConfigEntryNotReady` retry path, which was already
  tested). `TASK-0033` added
  `test_malformed_entry_missing_required_field_propagates_unhandled` — confirmed
  present in `tests/test_init.py:469`. **PASS.**
- **Round-1 item 2 — teardown asymmetry, documented and tested (RESOLVED).**
  `AUDIT-0011` found `async_unload_entry`'s cleanup steps were fewer than
  `async_setup_entry`'s setup steps, undocumented as intentional. `TASK-0033`
  added both a docstring explanation (confirmed in the `__init__.py` diff — a
  new comment block explaining which setup-time resources have no corresponding
  teardown step and why) and test coverage for the asymmetry itself
  (`tests/test_init.py`'s unload/teardown tests, re-confirmed present).
  **PASS.**
- **Round-1 item 3 — `services.yaml`/registered-service-name symmetry
  (RESOLVED).** `AUDIT-0011` found no test proving every service declared in
  `services.yaml` is actually registered in `__init__.py` (and vice versa) — a
  drift here would silently produce either an unusable declared service or an
  undocumented registered one. `TASK-0033` added
  `test_declared_and_registered_service_names_match` — confirmed present in
  `tests/test_init.py`. **PASS.**
- No new gap found. `tests/test_init.py` re-run live this session as part of the
  full suite — passing.

## Open Questions

None.

## Definition of Done (for Phase 8)

- N/A — no unresolved finding in this group this round.

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8 — not applicable, no fix scheduled. -->

- No Phase 8 task required for this group.
