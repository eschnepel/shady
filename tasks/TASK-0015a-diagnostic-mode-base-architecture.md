# Task: Diagnostic Mode Base Architecture

- **Status:** todo
- **Related ADRs:** [ADR-004 §1 (Amendment 2026-08-30), ADR-004 §5 (Amendment 2026-08-30), ADR-012 §1, ADR-013 §1]
- **Dependencies:** []

## Goal
Establish `diagnostics/base.py`: the shared `DiagnosticMode` base class
every concrete diagnostic mode (starting with `compare_regressions`,
TASK-0015b-diagnostics-select-and-scatter-sensors) subclasses, plus the
plain dataclasses its methods use. This is pure plumbing — no concrete
mode lives here, mirroring how TASK-0001-provider-base-architecture
established `providers/base.py`'s `Provider` ABC before any concrete
provider existed.

This task's shape is deliberately validated against **two** future needs
beyond the one concrete mode currently scheduled: ADR-013 (Proposed, not
scheduled) sketches a "compare regression methods across a full day" mode
and a "compare providers across a full day" mode, both operating on all
288 slots of a day rather than one. `DiagnosticContext.samples` being a
`Sequence` rather than a single value exists specifically so neither
future mode requires a change to this task's deliverable — only a new
subclass, when/if either is ever scheduled.

## Acceptance Criteria
- Given a minimal dummy subclass that only implements `compute()`, When
  it is instantiated, Then it succeeds and `extra_fit(context)` returns
  `None` (base-class default, mirrors `Provider.forward()`'s optionality,
  ADR-012 §1).
- Given a dummy subclass that omits `compute()` entirely, When it is
  instantiated, Then instantiation fails (`compute` is required, no
  default — mirrors `Provider.fetch()`'s requiredness, ADR-012 §1).
- Given a `DiagnosticContext` built with exactly one `DiagnosticSlotSample`,
  When a dummy mode's `compute()` reads `context.samples`, Then it
  receives a `Sequence` of length 1 — the single-slot case
  `CompareRegressionsMode` will use.
- Given a `DiagnosticContext` built with 288 `DiagnosticSlotSample`
  entries (one per 5-minute slot of a day), When a dummy mode's
  `compute()` reads `context.samples`, Then it receives a `Sequence` of
  length 288 — no base-class change needed for cardinality alone,
  validating ADR-013's premise before any concrete whole-day mode exists.
- Given a `DiagnosticSlotSample` with `actual=None` (a slot that hasn't
  elapsed yet), When constructed, Then it is accepted — the base class
  makes no assumption that every sample has a real value (ADR-004 §2a's
  future-pin partial-data shape depends on this).
- Given a `DiagnosticSlotSample` with `pool=None`, When constructed, Then
  it is accepted — a mode with no historical-scatter concept of its own
  (any future whole-day mode, ADR-013 §1) can simply omit it.
- Given a dummy subclass whose `extra_fit()` returns a
  `DiagnosticFitResult`, When called, Then the returned value's
  `predictions` mapping is accessible unchanged — this is the value
  shape `coordinator.py` will cache in
  TASK-0015b-diagnostics-select-and-scatter-sensors, not decided or
  consumed here.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/diagnostics/base.py`
- `custom_components/shady/diagnostics/__init__.py` (package init, if needed)
- `tests/test_diagnostics_base.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- None — this task has no dependencies, mirroring TASK-0001. -->

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
