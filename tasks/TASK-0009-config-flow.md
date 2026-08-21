# Task: Config Flow

- **Status:** todo
- **Related ADRs:** [ADR-010, ADR-001 §1]
- **Dependencies:** [TASK-0003-baseline-forecast-discovery]

## Goal
Implement `config_flow.py`: `ShadyConfigFlow`'s `settings` →
`add_string` → `add_string_advanced` → `add_another` step sequence with
every field ADR-010 specifies (defaults included), plus
`ShadyOptionsFlow` mirroring it for post-setup editing. No code in this
project imports `config_flow.py`'s classes downstream — it is a leaf
module in the dependency graph, so it can be developed in parallel with
most other tasks once its one real dependency (discovery scoring) is
done.

## Acceptance Criteria
- Given the `settings` step, When submitted with defaults, Then the
  resulting config-entry data contains exactly ADR-010's documented
  global fields at their documented defaults (`window_days=28`,
  `regression_method="wls2"`, `smoothing_radius=1`,
  `neighbor_fitting_cutoff=0.25`, `clipping_threshold=0.98`,
  `max_uplift_c=25`, `temperature_regression_method="wls2"`,
  `intraday_correction_mode="off"`, `intraday_correction_cutoff=0.10`,
  `window_slots=24`, `ramp_slots=12`).
- Given the global baseline-candidate dropdown, When rendered, Then it is
  populated by calling TASK-0003's discovery/scoring function, ranked,
  with a "None of these" manual entity+attribute fallback always present
  (ADR-009 §3).
- Given `add_string` with "Configure advanced corrections?" left off,
  When submitted, Then the flow proceeds directly to `add_another`,
  skipping `add_string_advanced` entirely.
- Given `add_string_advanced` with a baseline candidate override set for
  that string, When the flow completes, Then that string is
  automatically treated as temperature-aware, with no separate flag
  asked (ADR-003b §1c / ADR-010's `add_string` note).
- Given `add_string_advanced`'s "Rated DC capacity" field left empty for
  a string on the ambient/weather temperature tier, When the flow
  completes, Then the stored config reflects "skip derating for this
  string" per the skip-both-sides rule (ADR-003c §5 / ADR-010).
- Given the completed flow, When rendered against ADR-001 §1's decision,
  Then no latitude/longitude/elevation field is presented anywhere.
- Given `ShadyOptionsFlow`, When invoked on an existing config entry,
  Then it can add/edit strings and change any global setting, following
  the same step shape as initial setup.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/config_flow.py`
- `tests/test_config_flow.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0003. -->
- `providers.discovery.<scoring/ranking function>` from `custom_components/shady/providers/discovery.py` (→ task: TASK-0003-baseline-forecast-discovery)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
