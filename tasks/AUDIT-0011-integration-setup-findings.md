# Findings: AUDIT-0011 — Integration Setup & Wiring

**Auditor:** Lead Agent (inline, single-pass)
**Date:** 2026-09-06
**Verdict:** No behavioral FAIL — `__init__.py`'s startup-ordering logic
matches ADR-002 §1a's three-step decision tree closely and correctly,
error handling never swallows a setup failure silently, and
`services.yaml`/`manifest.json` are both internally consistent with
what the code actually implements/declares elsewhere. **2 PARTIALs**,
both documentation-staleness findings rather than code defects: ADR-002
§1a's own prose still names the removed `switch` platform instead of
`select` (the same rename AUDIT-0008/0009 already found cleanly
executed in code); and ADR-000 §3's module diagram draws `init -->
entity_glue` — an edge that doesn't correspond to any real Python
import (`__init__.py` never imports `sensor.py`/`config_flow.py`/
`select.py`/`button.py` at all; platform forwarding is HA's own
name-based mechanism) — while omitting the one direct import edge that
does exist, `init --> coordinator`. **3 coverage GAPs**: no test for a
genuine (non-`ConfigEntryNotReady`) setup-time failure such as a
malformed config entry or a provider-discovery exception; no test
exercises the service-registration side of teardown (the code, by
design, never unregisters the domain-wide service on a single entry's
unload, but nothing documents or verifies this); and no executable test
cross-checks `services.yaml` against the registered handlers — the
symmetry this audit verified by hand. All 13 tests in the one Scope
Test File re-run live: **13/13 passed**.

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
|---|---|---|---|
| 1 | [ADR-002 §1a] `async_setup_entry` sequences coordinator creation, first refresh, and platform forwarding with a concrete ordering guarantee, avoiding the "entities may not exist yet" race | PASS | Branch `hass.is_running is True` (`__init__.py:90-102`): `missing_required_entities()` checked immediately (`:91`), `ConfigEntryNotReady` raised with the transient coordinator `shutdown()` first if any are missing (`:93-97`) — matching §1a point 1 exactly, including the "never stored, never handed a platform" detail (module docstring `:22-29`, live-verified: `test_missing_required_entities_raises_not_ready` asserts `entry.entry_id not in hass.data`, `hass.config_entries.forwarded == []`, and the transient coordinator's own state-change listener already cancelled). If nothing is missing: `hass.data[...] = coordinator` → `await coordinator.async_restore_energy_state()` → `await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)` → `await coordinator.async_startup()` (`:98-101`) — every step `await`ed in sequence, a real ordering guarantee, not a scheduler assumption. Branch `hass.is_running is False` (`:104-126`): `hass.data`/energy-restore/platform-forward happen unconditionally (`:107-109`, matching §1a point 2's "forward... exactly as usual... Shady's own entities register on the normal schedule regardless"), then `async_at_started(hass, _async_handle_started)` registers the deferred fit **without being awaited** (`:125`) — matching §1a's explicit "must not itself block on that event" requirement. The deferred callback (`:111-123`) repeats the exact same `missing_required_entities()` check (§1a point 3), and on still-missing falls back to `asyncio.sleep(_MISSING_ENTITIES_RELOAD_DELAY_S)` + `hass.config_entries.async_schedule_reload(entry.entry_id)` (`:120-121`) rather than a bespoke retry loop, matching §1a's "rejoining the standard path" instruction precisely. |
| 2 | [ADR-002 §5] `__init__.py`'s module responsibility matches what §5 assigns it, distinct from `coordinator.py`'s; limits itself to setup/teardown/service registration, no business logic | PASS, with a scope note | §5's own bullet list (`002-coordinator-update-strategy.md:272-296`) assigns responsibilities to `coordinator.py`, `button.py`, and `forecast_adjust.py` specifically — it does **not** actually mention `__init__.py` at all, so there is no §5 text to compare `__init__.py` against directly; this criterion's premise (that §5 assigns something specific to `__init__.py`) doesn't hold on inspection, so the check falls back to the general "thin glue, no business logic" convention `__init__.py`'s own docstring claims (`:1-8`) and ADR-000 §3's one-line description ("wires platforms + coordinator into `hass.data`", `000-coding-standards.md:261`). On that standard: every computation is delegated — `missing_required_entities()`, `async_restore_energy_state()`, `async_startup()`, `pin_diagnostic_slot()`/`clear_diagnostic_slot()` are all `coordinator.py` methods; the service handler's own body (`__init__.py:147-176`) is a plain loop collecting rejected entry IDs and one `ServiceValidationError` construction — control flow, not domain computation. No arithmetic, no threshold logic, no forecast/regression code anywhere in the file. |
| 3 | [ADR-000 §1] `manifest.json` internally consistent with `pyproject.toml`'s declared dependencies — same `numpy` version floor | PASS | `manifest.json:8`: `"requirements": ["numpy>=1.26.0"]`. `pyproject.toml:14-16`: `dependencies = ["numpy>=1.26.0"]`. Identical floor, identical single dependency, no divergence. Triple-checked against `tasks/DEPENDENCIES.md`'s own `numpy 1.26.0 (lower bound)` entry (`:6-12`), which explicitly cross-references both files and instructs "do not re-add" — all three sources agree. |
| 4 | [ADR-000 §3] `__init__.py` sits at the correct top of the dependency chain — imports from the `entity_glue` layer below it, without reaching past into `coordinator.py` internals or `cache.py` directly | **PARTIAL** — no improper reach-past (good), but the diagram itself doesn't match the actual import graph | The good half: `__init__.py`'s only local imports are `from .const import DOMAIN` and `from .coordinator import ShadyCoordinator` (`__init__.py:54-55`, confirmed via `grep -n "^import\|^from"` — zero other local imports). Every coordinator interaction goes through public methods/attributes (`missing_required_entities()`, `shutdown()`, `async_restore_energy_state()`, `async_startup()`, `clear_diagnostic_slot()`, `pin_diagnostic_slot()`, `entry.entry_id`) — no reach into `coordinator.py` internals (no underscore-prefixed attribute access anywhere in the file) and no `cache.py` import or reference at all. The mismatch: ADR-000 §3's own diagram (`000-coding-standards.md:154,170`) draws `init --> entity_glue` (`entity_glue` = `sensor.py`/`config_flow.py`/`select.py`/`button.py`) as `__init__.py`'s one dependency edge — but `__init__.py` has **zero** Python imports from any of those four files; platform forwarding happens via `hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)` (`:100,109`), Home Assistant's own name-based dynamic-loading mechanism, not a Python import. The literal import graph instead has `init --> coordinator` directly — necessary, since `__init__.py` is the one place that *constructs* the `ShadyCoordinator` instance every `entity_glue` module later reads back out of `hass.data` — and that edge doesn't appear in the diagram at all. This is not a layering violation (`coordinator.py` is still "below" `__init__.py` in the intended stack either way) — it's a diagram that describes the conceptual relationship ("`__init__.py` wires up the entity_glue platforms") rather than the literal one, and doesn't separately show the direct construction-time import the code actually needs. Same category of documentation drift as Criterion 5 below and as AUDIT-0007's/AUDIT-0009's prior findings this session. |
| 5 | [ADR-000 §8] Error handling in `async_setup_entry` follows the documented convention, no bare `except Exception` swallowing setup failures silently | PASS, plus one incidental ADR-002 staleness finding | `grep -n "except\|try:" __init__.py` → zero matches anywhere in the file — there is no exception handling at all beyond the one intentional `raise ConfigEntryNotReady(...)` (`:95-97`) and the service handler's `raise ServiceValidationError(...)` (`:172-176`), both proper, purpose-built HA exception types, not raw text. A genuine setup-time failure (e.g., a malformed config entry raising inside `ShadyCoordinator(hass, entry)`, `:88`) is left to propagate naturally to Home Assistant's own config-entry loader, which is exactly the correct behavior for a lifecycle hook with a real caller — §8's "background failures... swallowed" rule explicitly scopes itself to "outside a request/response cycle where there is no caller to propagate the exception to" (`000-coding-standards.md:434-437`), and `async_setup_entry` is not such a context; it has a well-defined caller (HA's loader) that already knows how to handle an unhandled exception during setup. **Incidental finding, directly relevant to this audit's own scope:** ADR-002 §1a's own decision text (`002-coordinator-update-strategy.md:134`) still reads "...forward this config entry's platforms (`sensor`/`switch`/`button`) exactly as usual..." — a stale reference to the `switch` platform removed by ADR-004's 2026-08-30 amendment (`switch.py` → `select.py`). The code is correct throughout (`PLATFORMS = ["sensor", "select", "button"]`, `__init__.py:65`; the module's own docstring at `:5` correctly says "`sensor`/`select`/`button`") — this is purely an ADR-002 text staleness, the same category AUDIT-0007's FAIL and AUDIT-0010's FAIL found elsewhere. A second, out-of-scope instance of the identical stale reference exists in ADR-007's own module diagram (`007-coordinator-cache-split.md:130,153`, still listing `switch.py` in the `entity_glue` node) — noted for completeness but not part of this audit's Related ADRs. |
| 6 | `services.yaml` registers exactly the services `__init__.py` implements — no orphaned or missing service | PASS | `services.yaml` declares exactly one service, `select_diagnostic_slot` (`:1`), with one optional `timestamp` field (`required: false`, `datetime` selector, `:16-19`). `__init__.py` registers exactly one service, `SERVICE_SELECT_DIAGNOSTIC_SLOT = "select_diagnostic_slot"` (`:68`), via `hass.services.async_register(DOMAIN, SERVICE_SELECT_DIAGNOSTIC_SLOT, ..., schema=_SELECT_DIAGNOSTIC_SLOT_SCHEMA)` (`:178-183`), whose schema `vol.Schema({vol.Optional(ATTR_TIMESTAMP): cv.datetime})` (`:71`) matches the YAML's `required: false` / `datetime` selector exactly. One declared, one implemented, field shapes match — no drift in either direction. |

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | A test simulating the startup-ordering race itself — entities genuinely missing when a coordinator update fires — not just the already-settled case | COVERED, strongly | `TestAsyncSetupEntryHassStarting::test_deferred_callback_schedules_reload_if_still_missing` (`test_init.py:544-572`) is a direct, complete simulation: `hass.is_running = False`, zero entities seeded, `async_setup_entry` runs (forwarding platforms unconditionally per §1a point 2), then `hass.async_finish_starting()` fires the deferred callback while entities are **still** missing — asserts the fit correctly never ran (`coordinator._last_fit_at is None`) and the code correctly fell back to `async_schedule_reload` (`hass.config_entries.reload_calls == [entry.entry_id]`). Two sibling tests round out the state machine: `test_missing_entities_still_stores_and_forwards_platforms` (missing at initial setup, still deferred correctly) and `test_deferred_callback_runs_fit_once_started_if_entities_present` (missing at setup, present by the time "started" fires — fit runs, no reload). One phrasing note: `TASK-0016`'s own Delivered Artifacts text says this file "extends `tests/test_button.py`'s hand-written `homeassistant` stub **convention**" (`tasks/TASK-0016-integration-setup-entry.md:180-181`) — i.e. the same *style* of hand-written stub, not literal fixture reuse — so this audit criterion's "confirm this extension actually reaches the race condition, not just reuses fixtures" is answered on the stronger, more direct evidence above rather than on the (mildly imprecise) fixture-sharing premise itself. |
| 2 | A test asserting `async_unload_entry` reverses everything `async_setup_entry` registered — every platform unloaded, every service unregistered | COVERED for platforms/listeners; **GAP** for the service half | `TestAsyncUnloadEntry::test_unload_cancels_listeners_and_removes_data_slot` (`:576-589`) directly proves platform-unload symmetry (`hass.config_entries.unloaded == [(entry, PLATFORMS)]`), `hass.data` slot removal, and listener cancellation (`hass.states._listeners.get(_ACTUAL_YIELD_ENTITY, []) == []`) — genuinely strong. However, `async_unload_entry` (`__init__.py:129-136`) never unregisters the `select_diagnostic_slot` service (`grep -n "async_remove"` → zero matches) — a deliberate, defensible design given the service is domain-wide and idempotently registered once per HA instance, not once per config entry (removing it on one entry's unload could break other still-loaded entries relying on it) — but this asymmetry is neither documented in the module's own docstring nor exercised by any test: no test checks `has_service` after an unload, with either one or multiple loaded entries. `grep -n "async_unload_entry\|has_service" test_init.py` confirms the two unload tests never call `has_service` afterward. |
| 3 | A test for a provider-discovery failure at setup time asserting graceful `ConfigEntryNotReady`-or-equivalent failure, not an unhandled exception | **GAP** | `grep -n "malformed\|discovery.*fail"` across `test_init.py` found nothing; the only "raises" tests in the file cover the expected, controlled `missing_required_entities()` → `ConfigEntryNotReady` path (Criterion 1 above) and the service's `ServiceValidationError` path — neither simulates an actual unexpected exception during `ShadyCoordinator(hass, entry)` construction (e.g., a malformed config entry, or a `providers/discovery.py` failure surfacing through coordinator construction). The code's own structure (Criterion 5: zero `try`/`except` in the file) means such an exception would propagate naturally to HA's loader — the architecturally correct behavior — but nothing in the test suite exercises or documents this path explicitly; it is inferred from the absence of exception-swallowing code, not demonstrated by a test. |
| 4 | A test proving every service in `services.yaml` has a corresponding registered handler, and vice versa, as an executable check rather than manual inspection | **GAP** | `grep -rn "services.yaml" tests/*.py` → zero matches across the entire test suite. The one-service-declared/one-service-implemented symmetry (Audit Criterion 6 above) was verified by this audit through direct manual reading of both files — exactly the kind of check this criterion asks to see automated (mirroring `test_translations.py::test_every_schema_key_has_a_translation_label`'s dynamic-introspection pattern from AUDIT-0010, which this file has no equivalent of). |

## Live re-execution

```
$ python3 -m pytest tests/test_init.py -q
13 passed, 1 warning in 0.31s
```

No additional dependencies were required beyond what AUDIT-0010 already
installed into the sandbox (`voluptuous`) and AUDIT-0009's `pytest`.

## Candidate Follow-Ups (not created — proposed only)

1. **Criterion 5's incidental finding:** correct ADR-002 §1a's stale
   "`sensor`/`switch`/`button`" platform list to "`sensor`/`select`/
   `button`" — a one-line text fix, no code change, and no downstream
   task depends on this text. The identical stale reference in ADR-007's
   module diagram is a candidate for the same pass, though outside this
   audit's own Related ADRs.
2. **Criterion 4's PARTIAL:** ADR-000 §3's diagram could be corrected to
   show `init --> coordinator` (the real, necessary construction-time
   import) rather than (or in addition to) `init --> entity_glue` (which
   describes the platform-forwarding *relationship* but not an actual
   Python import edge) — a documentation-accuracy fix, not a code
   change; the underlying dependency direction is not violated either
   way.
3. **Test-Coverage Criterion 2's GAP:** add a small test — either
   asserting `has_service` correctly stays `True` after unloading one of
   two loaded entries (service persists for the remaining entry, matching
   the domain-wide design), or documenting in `__init__.py`'s own
   docstring why service unregistration is deliberately not part of
   `async_unload_entry`. Either closes the gap; the current silence
   leaves the asymmetry unverified either way.
4. **Test-Coverage Criterion 3's GAP:** add one test that makes
   `ShadyCoordinator.__init__` (or a call it makes during construction)
   raise a plain exception for a malformed config entry, and asserts
   `async_setup_entry` lets it propagate unhandled (rather than
   swallowing it) — turning the current code-structure inference into a
   demonstrated behavior.
5. **Test-Coverage Criterion 4's GAP:** add a `test_services_yaml.py`
   (or a section in `test_init.py`) that loads `services.yaml`, extracts
   its top-level service names, and cross-checks them against
   `hass.services.has_service(DOMAIN, ...)` after `_register_services`
   runs — the executable version of Audit Criterion 6's manual check,
   mirroring `test_translations.py`'s dynamic-introspection pattern from
   AUDIT-0010.

## Delivered Artifacts (for the task file)
- `tasks/AUDIT-0011-integration-setup-findings.md` (this file)
