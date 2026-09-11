# Audit Task: HA Entity Layer (sensor / button / select)

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** \[ADR-000 §3, ADR-002 §3, ADR-002 §5, ADR-004 §1, ADR-004
  §2, ADR-004 §2a, ADR-004 §2b, ADR-005 §1, ADR-005 §2, ADR-005 §3, ADR-005 §4,
  ADR-005 §5, ADR-005 §6, ADR-006 §4, ADR-013 §1\]
- **Dependencies:** [] (TASK-0011, TASK-0012, TASK-0013, TASK-0015b, TASK-0018
  are `done`)
- **Origin:** `sensor.py` was extended by four separate tasks (TASK-0011 base,
  TASK-0012 aggregates, TASK-0013 intraday attributes, TASK-0015b diagnostics
  sensors); `select.py` replaced a planned `switch.py` mid-project (ADR-004's
  2026-08-30 amendment, TASK-0018-hacs-select-rename-cleanup)

## Goal

Verify the entity layer stays a **thin, HA-facing presentation layer** over
`coordinator.py`/`aggregation.py`/`diagnostics/` — per ADR-000 §3's
module-boundary rule that these modules sit at the top of the dependency chain
and nothing below them should import from here — and that the switch→select
rename (ADR-004's amendment) left no naming or behavioral residue.

## Scope — Source Files

- `custom_components/shady/sensor.py`
- `custom_components/shady/button.py`
- `custom_components/shady/select.py`

## Scope — Test Files

- `tests/test_sensor_forecast.py`
- `tests/test_sensor_aggregates.py`
- `tests/test_sensor_diagnostics.py`
- `tests/test_button.py`
- `tests/test_select.py`

## Out of Scope

- The actual forecast/aggregate/diagnostic computation these entities display
  (covered by AUDIT-0005, AUDIT-0007, AUDIT-0008 respectively) — this audit only
  checks that entities read and expose that computation correctly, not that the
  computation itself is correct.
- `config_flow.py`/`const.py` (covered by AUDIT-0010).

## Audit Criteria

- [ADR-000 §3] Do `sensor.py`, `button.py`, `select.py` contain **no** business
  logic beyond thin read/format/expose — i.e. is every nontrivial computation
  delegated to `coordinator.py`/`aggregation.py`/ `diagnostics/`, with nothing
  here that a unit test would need to zero-mock a numeric edge case for?
- [ADR-002 §3] Does the forecast sensor expose exactly the documented horizon
  (today-remaining + tomorrow), matching what AUDIT-0005 will separately confirm
  the coordinator computes — flag (don't resolve) any mismatch between what the
  sensor exposes and what §3 specifies.
- [ADR-002 §5] Does the manual-recalculation button call the exact coordinator
  entry point ADR-002 §5 assigns to manual triggers, with no duplicate/parallel
  recalibration path defined inside `button.py` itself?
- [ADR-004 §1, amended 2026-08-30] Is the diagnostic-mode picker implemented as
  a `select.py` entity (not a `switch.py` boolean), and is its default value
  "off" as the amendment specifies?
- [ADR-004 §2] Is there one scatter-series sensor entity per configured string,
  with entity unique-IDs that can't collide across strings?
- [ADR-004 §2a] Does the manual-slot-selection-via-timestamp surface (if
  entity-exposed, e.g. as a service call or attribute) match what §2a specifies?
- [ADR-004 §2b, amended 2026-09-03] Does the summed-diagnostics-sensor entity
  match the **revised** 2026-09-03 behavior, not the original?
- [ADR-005 §1–§6] Do the six aggregate sensor entities (`ShadyPvSumSensor`,
  `ShadyFcSumSensor`, `ShadyFcDaySumSensor`, `ShadyFcRemainingTodaySensor`,
  `ShadyPvEnergyIntegralSensor`, `ShadyFcEnergyIntegralSensor`) exist with
  exactly these responsibilities, each backed by the corresponding
  `aggregation.py` function (no entity computing its own aggregate inline)?
- [ADR-006 §4, cross-ref] Does the forecast sensor's `extra_state_attributes`
  expose the four intraday transparency attributes documented in TASK-0013's
  Delivered Artifacts (`values_raw`, plus the scalar keys from
  `coordinator. intraday_attributes`) — confirm all four are present, not a
  subset?
- [ADR-013 §1, cross-ref, Proposed] Confirm no entity in this layer exposes
  ADR-013's whole-day comparison modes (not yet scheduled — same check as
  AUDIT-0008, from the entity side).
- **Rename residue check:** grep this layer and its tests for any remaining
  `switch`-named identifier, string literal, or docstring reference that should
  have become `select` per TASK-0018's cleanup — confirm zero remain.

## Test-Coverage Criteria

- Is there a test that would fail if `sensor.py`/`button.py`/`select.py` started
  computing a value itself instead of reading it from
  `coordinator`/`aggregation`/`diagnostics` — e.g. a test that mocks the
  upstream source and asserts the entity returns exactly that mocked value,
  proving no independent computation happens?
- Is there a test for each of the six ADR-005 aggregate sensors asserting its
  `unique_id`/`device_class`/`unit_of_measurement` match what a PV-forecast HA
  integration's conventions require (if the ADR specifies these) — or is
  entity-metadata correctness untested?
- Is there a test proving all four intraday attributes (ADR-006 §4) are present
  on the forecast sensor simultaneously, not just that each can individually be
  asserted in isolation across different tests?
- Is there a test asserting entity uniqueness across multiple configured strings
  for the per-string scatter sensor (ADR-004 §2) — i.e. two strings' sensors
  have different `unique_id`s, constructed from a fixture with ≥2 strings, not
  just a single-string fixture?
- Does `tests/test_select.py` exist and cover `select.py`'s full option set
  (every `DiagnosticMode` subclass selectable, including `compare_regressions`),
  or only the default/off state?

## Consumed Context (attached to the auditor)

- `tasks/adr-summary.md`
- `adr/000-coding-standards.md` §3
- `adr/002-coordinator-update-strategy.md` §§3, 5
- `adr/004-diagnostics-select-and-scatter-sensor.md` §§1, 2, 2a, 2b (including
  their amendments)
- `adr/005-aggregate-sum-and-integral-sensors.md` (full text)
- `adr/006-intraday-deviation-correction.md` §4 (cross-ref only)
- `adr/013-whole-day-diagnostic-modes.md` §1 (cross-ref only)
- All files listed under Scope above
- `tasks/TASK-0011-*.md`, `tasks/TASK-0012-*.md`, `tasks/TASK-0013-*.md`,
  `tasks/TASK-0015b-*.md`, `tasks/TASK-0018-*.md`
- `tasks/DEPENDENCIES.md`

## Definition of Done

- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering test
  named, or GAP explained.
- Findings written to `tasks/AUDIT-0009-entity-layer-findings.md`.
- No code changes made.

## Delivered Artifacts

<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->

- `tasks/AUDIT-0009-entity-layer-findings.md` — no FAIL; 1 PARTIAL (ADR-000 §3
  module-boundary: `sensor.py` reaches into `coordinator.cache` directly for 3
  of 9 sensor classes, task-time reviewed but undocumented in ADR-000 §3's own
  diagram/text); 1 coverage GAP (no ≥2-string `unique_id`-distinctness test in
  this layer's own test files); all 40 tests across the 5 Scope Test Files
  re-run live, 40/40 passed.
