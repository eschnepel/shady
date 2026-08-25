# Task: Patch — Thread `recency_decay_max` Through `coordinator.py`

- **Status:** todo
- **Related ADRs:** [ADR-001 §4a, ADR-010]
- **Dependencies:** [TASK-0010-coordinator-recalibration-recompute-push, TASK-0009-patch-2-recency-decay-config-field, TASK-0005-patch-4-recency-weight]

## Goal
`coordinator.py`'s `_fit_string` already reads `self._smoothing_radius`/
`self._neighbor_fitting_cutoff` at construction time (from `entry.data`)
and passes them into `build_pool(...)`. Add the third: read
`CONF_RECENCY_DECAY_MAX` into a new `self._recency_decay_max: float`
instance attribute, exactly mirroring `self._neighbor_fitting_cutoff`'s
existing line, and pass it as `build_pool`'s new `recency_decay_max`
parameter (`TASK-0005-patch-4`) at the exact call site `_fit_string`
already has. No other change to `_fit_string`, `_apply_training_corrections`,
or any other coordinator method — this patch is purely the wiring
between an already-stored config value and an already-extended function
signature, both delivered by this task's two dependencies.

**Human-initiated feature addition, not a worker-discovered gap** — same
"don't reopen a `done` task, patch instead" mechanics Scenario C already
establishes (precedent: the 2026-08-22 `NDArray` typing patches, also
human-directed). `TASK-0010` stays `done`, unreopened. This is also the
**last** of this feature's three patches — `TASK-0009-patch-2` and
`TASK-0005-patch-4` are each independently reviewable and self-contained
(neither needs the other), but this one needs both, since it is the
point where the config value and the extended `build_pool` signature
actually meet.

## Acceptance Criteria
- Given a config entry with `recency_decay_max` set (or absent, falling
  back to `DEFAULT_RECENCY_DECAY_MAX = 0.5`), When `ShadyCoordinator` is
  constructed, Then `self._recency_decay_max` holds that resolved value
  — same `data[CONF_...]` read pattern `self._neighbor_fitting_cutoff`
  already uses (`entry.data` always has every global key populated by
  the time a coordinator is constructed, config_flow's own contract — no
  `.get()`/default-fallback needed here, matching the existing sibling
  fields' own unconditional `data[CONF_...]` reads).
- Given `_fit_string` runs a refit, When it calls `build_pool(...)`,
  Then `self._recency_decay_max` is passed as the new `recency_decay_max`
  argument, alongside the existing `fc_by_offset`/`corrected_pv_by_offset`/
  `self._smoothing_radius`/`self._neighbor_fitting_cutoff` arguments —
  no change to any of those four.
- Given `TASK-0010`'s and `TASK-0010-patch-1`'s existing test suites
  (`tests/test_coordinator.py`), When re-run with this patch applied,
  Then every existing test still passes unmodified — this patch changes
  what value flows into `build_pool`, never the shape of any coordinator
  method's own inputs/outputs.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/coordinator.py` — one new `self._recency_decay_max`
  read in `__init__` (mirroring `self._neighbor_fitting_cutoff`'s
  existing line exactly), one new argument at `_fit_string`'s existing
  `build_pool(...)` call site.
- `tests/test_coordinator.py` — a small addition confirming the value
  reaches `build_pool` (e.g. two strings with different
  `recency_decay_max` config produce different fitted models against
  otherwise-identical seeded history — mirroring how existing tests
  already distinguish `smoothing_radius`/`neighbor_fitting_cutoff`
  effects, if such a test exists; otherwise a direct assertion on
  `coordinator._recency_decay_max`'s resolved value is sufficient, since
  `build_pool`'s own `TestRecencyWeight` suite (`TASK-0005-patch-4`)
  already covers the weighting math itself — this task only needs to
  prove the wiring, not re-prove the formula).

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0009-patch-2 and TASK-0005-patch-4
     once each reaches `done`. -->
- `const.CONF_RECENCY_DECAY_MAX` / `const.DEFAULT_RECENCY_DECAY_MAX`
  from `custom_components/shady/const.py` (→ task:
  TASK-0009-patch-2-recency-decay-config-field) — exact key name and
  default to be confirmed against that patch's own Delivered Artifacts
  once `done`.
- `regression.base.build_pool`'s extended signature (new
  `recency_decay_max: float` parameter) from
  `custom_components/shady/regression/base.py` (→ task:
  TASK-0005-patch-4-recency-weight) — exact parameter name/position to
  be confirmed against that patch's own Delivered Artifacts once `done`.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
