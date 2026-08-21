# Task: Baseline Forecast Discovery & Normalization

- **Status:** todo
- **Related ADRs:** [ADR-009, ADR-012 §1, ADR-012 §1a]
- **Dependencies:** [TASK-0001-provider-base-architecture]

## Goal
Implement `providers/discovery.py` + `providers/normalize.py`: scan
`sensor.*`/`weather.*` entities for forecast-shaped attributes, score
candidates, and normalize matches onto one canonical
`list[tuple[datetime, float]]` series — with no per-integration adapter
code.

## Acceptance Criteria
- Given a `sensor.*` entity exposing a `{timestamp: number}`-shaped
  attribute (Forecast.Solar-like) and one exposing a list-of-dicts shape
  (Solcast-like), When discovery scans entities, Then both are recognized
  and scored as candidates (ADR-009 §1).
- Given a `weather.*` entity exposing `sunshine_duration` and another
  exposing `cloud_coverage`, When discovery scans entities, Then both are
  recognized, the cloud-coverage one is inverted by
  `providers/normalize.py` (e.g. `100 - cloud_coverage`), and both are
  labeled distinctly in the candidate list (ADR-009 §1/§3).
- Given a matched candidate of any recognized shape, When
  `providers/normalize.py` processes it, Then the output is the
  canonical `list[tuple[datetime, float]]` series regardless of source
  shape or polarity.
- Given an entity with none of the recognized attribute shapes, When
  discovery scans it, Then it is not surfaced as a candidate (no false
  positive).
- Given the base class's `fetch()`/`forward()` contract from TASK-0001,
  When this provider's `fetch()` is called for a past range and
  `forward()` for the live forward range, Then both go through the same
  canonical-series mapping function (ADR-012 §1 — "one mapping function,
  two callers").

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/providers/discovery.py`
- `custom_components/shady/providers/normalize.py`
- `tests/test_providers_discovery.py` (real `hass` fixture, per ADR-000 §6's exception)
- `tests/test_providers_normalize.py` (zero-mocking)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0001. -->
- `providers.base.<ProviderBase>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)
- `providers.base.<state_value_mapping_helper>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)
- `providers.base.<series_tuple_assembly_helper>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
