# Audit Task: Integration Setup & Wiring

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** \[ADR-002 §1a, ADR-002 §5, ADR-000 §1, ADR-000 §3, ADR-000
  §8\]
- **Dependencies:** [] (TASK-0016 is `done`; TASK-0018 touched
  `manifest.json`-adjacent tooling)
- **Origin:** TASK-0016-integration-setup-entry — the final module in the
  dependency chain (`__init__.py`), wiring together every other module built by
  TASK-0001 through TASK-0015b

## Goal

Verify `__init__.py` correctly wires every platform (sensor, button, select) and
honors the startup-ordering guard ADR-002 §1a requires, now that it's the
integration point for the entire dependency graph — this is the one file where a
wiring mistake in any earlier module would surface as a setup-time failure.

## Scope — Source Files

- `custom_components/shady/__init__.py`
- `custom_components/shady/services.yaml`
- `custom_components/shady/manifest.json`

## Scope — Test Files

- `tests/test_init.py`

## Out of Scope

- The platforms' own internal correctness (sensor/button/select — covered by
  AUDIT-0009) — this audit only checks that `__init__.py` registers/forwards to
  them correctly.
- The coordinator's own startup-ordering guard logic (covered by AUDIT-0005) —
  this audit checks that `__init__.py` calls into it at the right point in
  `async_setup_entry`, not the guard's internals.

## Audit Criteria

- [ADR-002 §1a] Does `async_setup_entry` sequence coordinator creation, first
  refresh, and platform forwarding in an order that actually avoids the
  "entities may not exist yet" race the ADR describes — is there a concrete
  ordering guarantee (e.g. `await` before platform setup), not an assumption
  that HA's own scheduler happens to work out?
- [ADR-002 §5] Does `__init__.py`'s module responsibility match what §5 assigns
  to the top-level integration entry point specifically (distinct from
  `coordinator.py`'s own §5 responsibilities, audited separately in AUDIT-0005)
  — i.e. does `__init__.py` limit itself to setup/teardown/service registration,
  with no business logic?
- [ADR-000 §1] Is `manifest.json` internally consistent with `pyproject.toml`'s
  declared dependencies (cross-ref AUDIT-0012) — same `numpy` version floor, no
  dependency declared in one but not the other?
- [ADR-000 §3] Does `__init__.py` sit at the correct top of the dependency chain
  — does it import from `sensor.py`/`config_flow.py`/ `select.py`/`button.py`
  (the layer directly below it per the module- boundary doc) without reaching
  *past* them into `coordinator.py` internals or `cache.py` directly, which
  would violate the layering?
- [ADR-000 §8] Does error handling in `async_setup_entry` (e.g. a provider
  discovery failure, a malformed config entry) follow the ADR's documented
  error-handling convention, rather than a bare `except Exception` swallowing
  setup failures silently?
- Does `services.yaml` register exactly the services `__init__.py` actually
  implements (per TASK-0016's Delivered Artifacts note about "HA service-picker"
  support) — confirm no service listed in the YAML is unimplemented, and no
  implemented service is missing from the YAML.

## Test-Coverage Criteria

- Is there a test simulating the startup-ordering race itself (ADR-002 §1a) —
  entities genuinely not yet existing when a coordinator update fires — or does
  `tests/test_init.py` only cover the already-settled case (per TASK-0016's own
  note that it "extends `tests/test_button. py`'s" fixtures — confirm this
  extension actually reaches the race condition, not just reuses fixtures for an
  unrelated assertion)?
- Is there a test asserting `async_unload_entry` (or equivalent teardown)
  correctly reverses everything `async_setup_entry` registered — every platform
  unloaded, every service unregistered — or is teardown untested?
- Is there a test for a provider-discovery failure at setup time (ADR-000 §8)
  asserting the integration fails setup gracefully (a `ConfigEntryNotReady` or
  equivalent) rather than raising an unhandled exception?
- Is there a test proving every service in `services.yaml` has a corresponding
  registered handler, and vice versa (the registration symmetry check above,
  expressed as an executable test rather than manual inspection)?

## Consumed Context (attached to the auditor)

- `tasks/adr-summary.md`
- `adr/002-coordinator-update-strategy.md` §§1a, 5
- `adr/000-coding-standards.md` §§1, 3, 8
- All files listed under Scope above
- `tasks/TASK-0016-*.md`
- `tasks/DEPENDENCIES.md`

## Definition of Done

- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering test
  named, or GAP explained.
- Findings written to `tasks/AUDIT-0011-integration-setup-findings.md`.
- No code changes made.

## Delivered Artifacts

<!-- Filled by the Auditor AFTER the audit runs. Empty until then. -->

- `tasks/AUDIT-0011-integration-setup-findings.md` — no behavioral FAIL;
  startup-ordering logic (ADR-002 §1a) matches the ADR's three-step decision
  tree closely, no silent exception swallowing. **2 PARTIALs**, both
  documentation staleness: ADR-002 §1a's own text still names the removed
  `switch` platform; ADR-000 §3's diagram draws `init --> entity_glue` (no real
  import behind it) and omits the real `init --> coordinator` construction-time
  import. **3 coverage GAPs**: no test for a genuine setup-time failure
  (malformed entry/discovery exception); service-unregistration half of teardown
  untested; no executable `services.yaml`-vs-registered-handlers check. 13/13
  tests re-run live.
