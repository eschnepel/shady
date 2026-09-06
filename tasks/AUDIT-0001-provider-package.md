# Audit Task: Provider Package

- **Status:** review
- **Type:** Code/ADR Conformance Audit (read-only — no implementation)
- **Related ADRs:** [ADR-012 §1, ADR-012 §1a, ADR-012 §2, ADR-012 §3, ADR-009 §1, ADR-009 §2, ADR-009 §3, ADR-009 §4, ADR-009 §5, ADR-003b §1a]
- **Dependencies:** [] (TASK-0001, TASK-0003, TASK-0004 are `done`; this audit has no execution-order dependency on other audit tasks)
- **Origin:** built by TASK-0001-provider-base-architecture, TASK-0003-baseline-forecast-discovery, TASK-0004-temperature-source-provider (all `done`)

## Goal
Verify that `providers/` still matches ADR-012's shared-base-class
architecture and ADR-009's baseline-discovery decision now that three
separate tasks (base class, baseline discovery, temperature source) have
all landed in the same package, and that the test suite would actually
catch a regression in each documented behavior.

## Scope — Source Files
- `custom_components/shady/providers/__init__.py`
- `custom_components/shady/providers/base.py`
- `custom_components/shady/providers/discovery.py`
- `custom_components/shady/providers/normalize.py`
- `custom_components/shady/providers/temperature.py`

## Scope — Test Files
- `tests/test_providers_base.py`
- `tests/test_providers_discovery.py`
- `tests/test_providers_normalize.py`
- `tests/test_providers_temperature.py`

## Out of Scope
- `yield_correction.py`'s consumption of `providers/temperature.py`'s
  output (covered by AUDIT-0004).
- `coordinator.py`'s push-back into providers (ADR-012 §4) — covered by
  AUDIT-0005 (coordinator owns the push call site; this audit only
  checks the receiving surface in `providers/base.py`).

## Audit Criteria
- [ADR-012 §1] Is there exactly one shared base class in `providers/base.py`
  that both the baseline-discovery and temperature-source providers
  build on top of, rather than each reimplementing common logic?
- [ADR-012 §1a] Are the two documented shared helpers in `providers/
  base.py` (not reimplemented per concrete provider) actually used by
  both `discovery.py` and `temperature.py`, not duplicated locally in
  either?
- [ADR-012 §2] For any external entity that does *not* need a provider,
  does the code actually skip the provider abstraction rather than
  forcing everything through it?
- [ADR-012 §3] Does cache reuse for provider-sourced series route through
  the existing cache concept (see AUDIT-0003) rather than inventing a
  parallel storage mechanism inside `providers/`?
- [ADR-009 §1] Does `discovery.py` perform generic attribute-shape
  discovery (inspecting entity attributes for a recognizable
  forecast-series shape) rather than hardcoding per-integration adapters
  (e.g. no `if entity_id.startswith("forecast_solar")`-style branching)?
- [ADR-009 §2] Does `normalize.py` reduce every discovered candidate onto
  one canonical series representation before it reaches the rest of the
  pipeline?
- [ADR-009 §3] Are discovered candidates scored rather than
  auto-selected — i.e. is there a scoring function, and is the highest
  score chosen deterministically rather than "first match wins"?
- [ADR-009 §4] Do `discovery.py` and `temperature.py` read `hass.states`
  directly (the documented module-boundary exception for this package),
  while `normalize.py`/`base.py` stay HA-agnostic?
- [ADR-009 §5] Is there a genuine global-default-with-per-string-override
  mechanism, and does a per-string override actually take precedence
  over the global default in the code path (not just in a docstring)?
- [ADR-003b §1a] Does `temperature.py` implement the documented
  temperature-source hierarchy (multiple candidate sensor kinds tried in
  a defined order) rather than a single fixed sensor type?

## Test-Coverage Criteria
- Is there a test that fails if the shared base class's helpers (ADR-012
  §1a) were duplicated inline in `discovery.py` or `temperature.py`
  instead of called from `base.py`?
- Is there a test that constructs a *tied* or *near-tied* scoring
  scenario (ADR-009 §3) and asserts a specific, deterministic winner —
  or would a nondeterministic tie-break still pass?
- Is there a test asserting per-string override actually overrides the
  global default (ADR-009 §5), not just that both can be configured
  independently?
- Is there a test for `temperature.py`'s full hierarchy fallback path
  (ADR-003b §1a) — i.e. first-choice sensor kind absent, second-choice
  present — or only the first-choice-present happy path?
- Is there a test proving `discovery.py`/`temperature.py` read
  `hass.states` (ADR-009 §4) via a real `hass` fixture, and a separate
  test proving `normalize.py`/`base.py` need no `hass` fixture at all
  (the zero-mocking-tier boundary)?

## Consumed Context (attached to the auditor)
- `tasks/adr-summary.md`
- `adr/012-provider-architecture.md` (full text)
- `adr/009-baseline-forecast-sourcing.md` (full text)
- `adr/003b-temperature-derating-correction.md` §1a only
- All files listed under Scope above
- `tasks/DEPENDENCIES.md`

## Definition of Done
- Every Audit Criterion marked PASS / FAIL / PARTIAL with file:line evidence.
- Every Test-Coverage Criterion marked COVERED / GAP with the covering
  test named, or GAP explained.
- Findings written to `tasks/AUDIT-0001-provider-package-findings.md`.
- No code changes made.

## Delivered Artifacts
- `tasks/AUDIT-0001-provider-package-findings.md` → 9 PASS, 1 PASS-with-
  scope-note, 1 PARTIAL (sunshine-duration rescaling vs. ADR-009 §1
  wording — flagged for human decision, not resolved), 2 test-coverage
  GAPs (helper-duplication regression, scoring tie-break determinism),
  1 test-coverage COVERED-but-related-to-PARTIAL. No code changes made.
