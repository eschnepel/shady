# Task: Provider Base Architecture

- **Status:** done
- **Related ADRs:** [ADR-012 §1, ADR-012 §1a]
- **Dependencies:** []

## Goal
Establish `providers/base.py`: the shared base class every concrete
provider (baseline, temperature) subclasses, plus two small HA-agnostic
helper functions both concrete providers need. This is pure plumbing —
no concrete provider lives here.

## Acceptance Criteria
- Given a minimal dummy subclass that only implements `fetch()`, When it
  is instantiated, Then it succeeds, `identify()` returns `None`, and
  `forward(now)` returns `None` (base-class defaults, ADR-012 §1).
- Given a dummy subclass that omits `fetch()` entirely, When it is
  instantiated, Then instantiation fails (per ADR-012 §1: `fetch` is
  required, no default).
- Given a range of raw `hass.states`-shaped inputs (a plain numeric
  state, an `"unknown"` state, an `"unavailable"` state, an attribute
  that is simply absent), When the state-value mapping helper processes
  each, Then it returns exactly one of `cache.py`'s three storage states
  (`float`/`None`/`str`) per ADR-007a §1.
- Given a set of already-resolved timestamp/value pairs (both a dict
  shape and a list-of-dicts shape), When the series-tuple assembly
  helper processes them, Then it returns the canonical
  `list[tuple[datetime, float]]` shape (ADR-009 §2).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/providers/base.py`
- `custom_components/shady/providers/__init__.py` (package init, if needed)
- `tests/test_providers_base.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- None — this task has no dependencies. -->

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/providers/base.py` → class `ProviderBase`, type aliases `EntityRef`, `ThreeStateValue`, helper functions `state_to_three_state_value()` and `assemble_series_tuples()`
