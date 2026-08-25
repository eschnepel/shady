# Task: Patch — Recency-Decay Config Field (`recency_decay_max`)

- **Status:** todo
- **Related ADRs:** [ADR-001 §4a, ADR-010]
- **Dependencies:** [TASK-0009-config-flow]

## Goal
Add the new global setting `recency_decay_max` (ADR-001 §4a's amendment,
ADR-010's new bullet, 2026-08-25) to `config_flow.py`'s `settings` step
schema and to `ShadyOptionsFlow`'s prefill/mirror — the maximum
downweight applied to the oldest day in the rolling training window,
default `0.5` (50%). Purely a new field alongside the existing global
regression settings (`window_days`, `regression_method`,
`smoothing_radius`, `neighbor_fitting_cutoff`, `clipping_threshold`) —
no change to any existing field or step ordering.

**Human-initiated feature addition, not a worker-discovered gap** — the
same "don't reopen a `done` task, patch instead" mechanics Scenario C
already establishes apply regardless of who/what surfaces the need
(precedent: the 2026-08-22 `NDArray` typing patches, also
human-directed). `TASK-0009` stays `done`, unreopened.

## Acceptance Criteria
- Given the `settings` step form, When rendered, Then it includes a
  `recency_decay_max` field, `vol.All(vol.Coerce(float), vol.Range(min=0,
  max=1))` (same shape as `CONF_CLIPPING_THRESHOLD` — a plain 0–1
  fraction, no negative sentinel needed here, unlike
  `neighbor_fitting_cutoff`'s `-1%`), defaulting to `0.5` when not
  already present in `defaults`.
- Given a submitted `settings` step, When `_normalize_settings` runs,
  Then the resulting `entry.data` includes
  `CONF_RECENCY_DECAY_MAX: user_input[CONF_RECENCY_DECAY_MAX]`, exactly
  mirroring how every other required global field in that function is
  handled.
- Given `ShadyOptionsFlow`'s prefill, When `_settings_defaults_from_entry_data`
  runs against an existing entry, Then it returns
  `CONF_RECENCY_DECAY_MAX: data.get(CONF_RECENCY_DECAY_MAX, DEFAULT_RECENCY_DECAY_MAX)`,
  exactly mirroring the existing fields' pattern (falls back to the
  default for an entry created before this patch — no data migration
  needed, options flow prefill already handles a missing key gracefully
  for every other field).
- Given `0.0`, When submitted, Then it is accepted (disables recency
  weighting entirely per ADR-001 §4a — not a validation error).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/const.py` — new `CONF_RECENCY_DECAY_MAX =
  "recency_decay_max"` and `DEFAULT_RECENCY_DECAY_MAX = 0.5`, placed
  alongside `CONF_NEIGHBOR_FITTING_CUTOFF`/`DEFAULT_NEIGHBOR_FITTING_CUTOFF`.
- `custom_components/shady/config_flow.py` — three touch points, all
  small, mirroring the existing `CONF_NEIGHBOR_FITTING_CUTOFF` handling
  exactly: (1) the `settings` step's `vol.Schema` field list, (2)
  `_normalize_settings`'s returned dict, (3)
  `_settings_defaults_from_entry_data`'s returned dict.
- `tests/test_config_flow.py` — a new `TestRecencyDecayMax` class,
  mirroring `TestManualBaselineShape`'s (`TASK-0009-patch-1`) shape:
  default-applies-when-absent, round-trips through
  submit-then-options-flow-prefill, `0.0` accepted.

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
- `config_flow.py`'s existing `settings`-step schema, `_normalize_settings`,
  and `_settings_defaults_from_entry_data` — already-`done`,
  same-module code this patch extends; no new external interface
  consumed. No dependency on `TASK-0005`/`TASK-0010`/their patches — this
  task only produces the config-entry `data` key, it never reads
  `regression/` or `coordinator.py`.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
