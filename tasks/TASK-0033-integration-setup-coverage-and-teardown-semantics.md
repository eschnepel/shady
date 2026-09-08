# Task: Integration-Setup Test-Coverage & Teardown-Semantics

- **Status:** todo
- **Related ADRs:** [ADR-002, ADR-000]
- **Dependencies:** [TASK-0016-integration-setup-entry]

## Goal
`AUDIT-0011-integration-setup` found three related Test-Coverage GAPs,
one of which also carries an undocumented design asymmetry worth writing
down alongside its test:

1. **No test for a genuine (non-`ConfigEntryNotReady`) setup-time
   failure**, e.g. a malformed config entry or an unexpected exception
   during `ShadyCoordinator(hass, entry)` construction. The code's own
   structure (zero `try`/`except` in `__init__.py`) means such an
   exception would propagate naturally to Home Assistant's own loader —
   the architecturally correct behavior per ADR-000 §8 — but nothing in
   the test suite exercises or demonstrates this path; it's inferred
   from the absence of exception-swallowing code, not demonstrated.
2. **`async_unload_entry` deliberately never unregisters the
   domain-wide `select_diagnostic_slot` service** on a single config
   entry's unload — a defensible design (the service is registered once
   per HA instance, not once per entry; removing it on one entry's
   unload could break other still-loaded entries relying on it) — but
   this asymmetry is neither documented in `__init__.py`'s own docstring
   nor exercised by any test either direction.
3. **No executable test cross-checks `services.yaml` against the
   actually-registered service handlers** — the one-service-declared/
   one-service-implemented symmetry was verified by the audit through
   direct manual reading of both files; nothing automates it, unlike
   `test_translations.py`'s own dynamic-introspection pattern for the
   analogous en/de-vs-schema check.

## Known Decisions
- Item 1 and item 3 are pure, additive tests — no production code
  change.
- Item 2's *design* (service stays registered across a single entry's
  unload) is already decided and correct per the audit's own assessment
  — no code change to the behavior itself. This task closes the gap by
  adding **both** a docstring note explaining the asymmetry **and** a
  test verifying it (the audit's own candidate follow-up offered either
  one as sufficient; this task does both since they're cheap together
  and reinforce each other).

## Open Questions for Execution
- None expected. If, while writing item 1's test, the worker finds that
  triggering a genuine construction-time exception requires more
  invasive changes to the existing `hass`/`ConfigEntry` stub convention
  than expected (e.g. the stub doesn't currently support injecting a
  raising provider-discovery call), note the actual blocker here — the
  audit's own framing ("make `ShadyCoordinator.__init__` or a call it
  makes during construction raise a plain exception for a malformed
  config entry") implies this should be achievable with the existing
  stub harness, but confirm before expanding the harness itself.

## Acceptance Criteria
- Given `tests/test_init.py`, When run after this task, Then it
  contains a new test that makes `ShadyCoordinator.__init__` (or a call
  it makes during construction) raise a plain exception for a malformed
  config entry, and asserts `async_setup_entry` lets it propagate
  unhandled (not swallowed, not converted into a different exception
  type).
- Given `custom_components/shady/__init__.py`'s own module docstring,
  When read after this task, Then it documents why
  `async_unload_entry` deliberately does not unregister the domain-wide
  service on a single entry's unload.
- Given `tests/test_init.py`, When run after this task, Then it also
  contains a new test asserting `hass.services.has_service(DOMAIN,
  SERVICE_SELECT_DIAGNOSTIC_SLOT)` stays `True` after unloading one of
  two loaded config entries (service persists for the remaining entry,
  matching the domain-wide design documented above).
- Given `tests/test_init.py` (or a new `tests/test_services_yaml.py`,
  the worker's choice, matching whichever is more consistent with this
  file's existing organization), When run after this task, Then it
  contains a new test that loads `services.yaml`, extracts its
  top-level service names, and cross-checks them against
  `hass.services.has_service(DOMAIN, ...)` after `_register_services`
  runs — the executable version of the manual check the audit performed
  by hand, mirroring `test_translations.py`'s dynamic-introspection
  pattern.
- Given the full test suite, When run after this task, Then all
  pre-existing tests still pass unmodified, plus the new additions.

## Estimated File / Module Footprint (hint, not a commitment)
- `tests/test_init.py` (or a new `tests/test_services_yaml.py`)
- `custom_components/shady/__init__.py` (docstring only — no logic
  change)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, listing the exact
  new test names added
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/__init__.py` → `async_setup_entry`,
  `async_unload_entry`, `SERVICE_SELECT_DIAGNOSTIC_SLOT`,
  `_register_services` — (→ task: TASK-0016-integration-setup-entry) —
  the functions/constants all three new tests exercise.
- `custom_components/shady/services.yaml` — (→ task: TASK-0016) — the
  file item 3's new test parses and cross-checks.
- `custom_components/shady/coordinator.py` → `ShadyCoordinator.__init__`
  — (→ task: TASK-0010-coordinator-recalibration-recompute-push) — the
  constructor item 1's new test makes raise.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
