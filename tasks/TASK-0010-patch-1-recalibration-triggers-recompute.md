# Task: Patch — Recalibration Completion Must Trigger a Recompute

- **Status:** done
- **Related ADRs:** [ADR-002 §2]
- **Dependencies:** [TASK-0010-coordinator-recalibration-recompute-push]

## Goal
ADR-002 §2 names **two** independent recompute triggers: (1) "a model
recalibration completes... the newly-fitted factors are applied to
whatever baseline data is currently cached", and (2) a baseline-entity
state-change update. `TASK-0010`'s delivered `_refit_sync` only fits and
stores each string's model — it never calls `_recompute_string`, so
trigger (1) does not actually fire; only trigger (2) does (exercised by
`TestRecomputeOnBaselineUpdate`). No acceptance criterion in `TASK-0010`
exercised trigger (1) specifically, so this shipped as `done` without it.
Discovered while gathering `TASK-0011`'s Consumed Interfaces (Scenario
C) — without this, `async_setup_entry` (TASK-0011) constructing a
coordinator and running its startup fit produces a fitted model but
pushes nothing to `ShadyForecastSensor` until a baseline entity happens
to fire a state-change event, which `TASK-0011`'s own acceptance
criterion ("`ShadyForecastSensor` exposes a plausible corrected value"
right after `async_setup_entry`) cannot rely on. `TASK-0010` stays
`done`, unreopened.

## Acceptance Criteria
- Given a string's model is freshly (re)fit during `_refit_sync` (button
  or midnight schedule, `TASK-0010`'s existing shared code path), When
  fitting succeeds, Then the exact same recompute path
  (`_recompute_string`) runs immediately for that string against
  whatever baseline data is currently cached, with no separate trigger
  needed (ADR-002 §2 trigger 1).
- Given fitting fails for a string (`_fit_string` returns `None`, e.g.
  no baseline provider configured), When `_refit_sync` runs, Then no
  recompute is attempted for that string (unchanged from before this
  patch — nothing to recompute with).
- Given `TestRecomputeOnBaselineUpdate`'s existing scenario (baseline
  update fires mid-day, no refit involved), When it runs, Then the
  behavior is unchanged — trigger (2) is untouched by this patch.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/coordinator.py` (`_refit_sync` only)
- `tests/test_coordinator.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
- `coordinator._recompute_string` / `_refit_sync` — already-private,
  same-module code; no new external interface consumed beyond what
  `TASK-0010` itself already consumed.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/coordinator.py` → `_refit_sync` now calls
  `self._recompute_string(string, now)` immediately after a string's
  model is (re)fit and stored, before moving to the next string. No
  signature changes to any public/private method; no new methods added.
- `tests/test_coordinator.py` → `TestRefitTriggersRecompute` (2 tests):
  a bare `async_refit()` (no baseline-update event at all) now results
  in a pushed forecast value; a string with no baseline provider
  configured fits no model and triggers no recompute. Full suite
  152/152 (150 pre-patch + 2 this patch).
- No external dependencies added.
- Gates: `ruff check`/`ruff format --check`/`mypy --config-file mypy.ini`
  all clean on the 2 changed files; 18 source files clean overall.
