# Audit Task: HA Entity Layer (Round 2)

- **Status:** review
- **Group:** `custom_components/shady/sensor.py`,
  `custom_components/shady/button.py`, `custom_components/shady/select.py`
- **Related ADRs:** \[ADR-002 §3/§5, ADR-004 §2, ADR-005 §2, ADR-006 §2, ADR-000
  §3\]
- **Source Tasks:** \[TASK-0013-shading-sensor-entities,
  TASK-0014-diagnostic-sensor-entities, TASK-0015-recalibrate-button,
  TASK-0016-diagnostic-mode-select, TASK-0023-entity-layer-cache-access-
  boundary, TASK-0032-entity-layer-config-flow-coverage-additions\]

## Scope

Re-audits round 1's `AUDIT-0009-entity-layer` (1 PARTIAL, 1 coverage gap).
`sensor.py`/`button.py`/`select.py` have zero byte changes since round 1
(confirmed via `git diff --stat f7fcef8 HEAD` — the fix for the PARTIAL below
landed in `coordinator.py`, not in the entity files themselves).

## Findings — Code Logic vs. ADRs

- **Round-1 item — direct `coordinator.cache` access from three sensor classes
  (RESOLVED).** `AUDIT-0009` found three diagnostic sensor classes in
  `sensor.py` reading `self.coordinator.cache.<method>(...)` directly instead of
  through a coordinator wrapper method, undocumented as an intentional
  exception. The human's resolution (`TASK-0023`, third option — read-only
  property, not a full wrapper-method rewrite) is confirmed live:
  `coordinator.py`'s `cache` attribute is now exposed as a `@property` returning
  the `Cache` instance without a setter (`class TestCacheAttributeIsReadOnly` in
  `tests/test_coordinator.py:399` exercises exactly this — attempting
  `coordinator.cache = ...` raises `AttributeError`). `sensor.py` itself is
  unchanged (still reads `self.coordinator.cache. get_regression_pools(...)`
  etc. directly), which is the intended outcome: the exception is now a
  documented, enforced boundary (read-only) rather than an accidental one.
  Re-confirmed the documentation lives in ADR-000 §3 alongside the exception's
  rationale, consistent with round 1's own suggested Option C framing. **PASS.**
- No other deviations found. `ShadingRecommendationSensor`, the diagnostic
  sensor family (ADR-004 §2), `RecalibrateButton` (ADR-005 §2), and
  `DiagnosticModeSelect` (ADR-006 §2, correctly `select`-based per round 1's own
  prior confirmation that the ADR-002 §1a "switch" residue was
  documentation-only) all match round 1's confirmed reading.

## Findings — Test Coverage vs. ADRs

- **Round-1 item — `unique_id` distinctness across strings (RESOLVED).**
  `AUDIT-0009` found the shared `unique_id` fixture only ever exercised a
  single-string config, so two sensors of the same kind for *different* strings
  were never proven to get distinct IDs. `TASK-0032` added a ≥2-string fixture
  test — confirmed present: `tests/test_sensor_diagnostics.py` contains a
  `unique_id`-distinctness test using a two-string configuration (grep for
  `unique_id` in the file shows the added assertions). **PASS.**
- No new gap found. Full entity-layer test files re-run live this session as
  part of the full suite — passing.

## Open Questions

None.

## Definition of Done (for Phase 8)

- N/A — no unresolved finding in this group this round.

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8 — not applicable, no fix scheduled. -->

- No Phase 8 task required for this group.
