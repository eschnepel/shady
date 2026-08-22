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
- `custom_components/shady/providers/__init__.py` → empty package marker,
  no exports.
- `custom_components/shady/providers/base.py`:
  - `EntityRef` — frozen dataclass, fields `entity_id: str`,
    `attribute: str | None = None`. A resolved reference to a Home
    Assistant entity (optionally a specific attribute on it).
  - `Provider` — abstract base class (`abc.ABC`).
    - `fetch(self, start: datetime, end: datetime) -> list[float | None | str]`
      — abstract, **required**. A subclass that omits it fails to
      instantiate (`TypeError`). **Calling convention (binding for every
      concrete provider and consumer, matches `cache.py`'s `fetch_fn`
      exactly, ADR-007a §4):** half-open interval `[start, end)`, one
      value per 5-minute slot, so `len(result) == (end-start)/5min`.
    - `identify(self) -> EntityRef | None` — optional hook, base default
      returns `None`.
    - `forward(self, now: datetime) -> list[tuple[datetime, float]] | None`
      — optional hook, base default returns `None`.
  - `map_state_value(raw: float | str | None) -> float | None | str` —
    maps a `hass.states`-shaped raw reading (numeric value, the state
    string `"unknown"`, any other non-numeric state string e.g.
    `"unavailable"`, or `None` for an absent attribute) to `cache.py`'s
    three-state value model (ADR-007a §1). `"unknown"` and `None` (absent)
    both map to `None`; any other non-numeric string is returned as-is
    (kept distinct, not discarded); numeric values (incl. numeric
    strings) map to `float`.
  - `assemble_series(pairs: Mapping[datetime, float] | Sequence[Mapping[str, Any]], *, datetime_key: str = "datetime", value_key: str = "value") -> list[tuple[datetime, float]]`
    — assembles already-resolved timestamp/value pairs (dict shape, or
    list-of-dicts shape keyed by `datetime_key`/`value_key`) into the
    canonical series shape (ADR-009 §2). Does no alias-guessing itself —
    callers (`providers/normalize.py`, `providers/temperature.py`) must
    resolve keys before calling this. **Default key names `"datetime"`/
    `"value"` are now the established convention** for callers that don't
    override them.
- `tests/test_providers_base.py` → 15 zero-mocking tests (4 test classes)
  covering all 4 acceptance criteria above. Establishes the
  `TYPE_CHECKING`-only static-import pattern (ADR-000 §6) for subclassing
  a dynamically file-path-loaded ABC — reusable by later provider tasks'
  test suites (e.g. TASK-0003, TASK-0004) that need to subclass `Provider`
  under the same zero-mocking, no-`homeassistant`-import constraint.
- External dependencies added: none.
- Gates: `ruff format`, `ruff check`, `mypy --config-file mypy.ini
  --strict` (effectively, via project config), `pytest` all pass with
  zero errors/warnings.