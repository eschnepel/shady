# Task: Diagnostics — Switch & Scatter/Accuracy Sensors

- **Status:** todo
- **Related ADRs:** [ADR-004 §1, ADR-004 §2, ADR-004 §2a, ADR-004 §2b, ADR-004 §3, ADR-004 §4, ADR-004 §5, ADR-007a §6]
- **Dependencies:** [TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor, TASK-0010-coordinator-recalibration-recompute-push, TASK-0011-forecast-sensor-and-recalculate-button, TASK-0013-intraday-deviation-correction]

## Goal
Implement `cache.py`'s `get_pinned_slot_pool` accessor + cache-wide
`pinned_reference: date | None` scalar (`pin_reference()`/
`clear_reference()`); `switch.py`'s `ShadyDiagnosticsSwitch` (default
off, gates all diagnostic sensors and their extra fitting cost);
`sensor.py`'s `ShadyDiagnosticsSensor` (per string) +
`ShadyDiagnosticsSumSensor` (per entry); the accuracy pure function in
`aggregation.py`; and the `shady.select_diagnostic_slot` service
registered in `__init__.py`.

**Reuses TASK-0013's 5-minute trigger** (ADR-004 §2 explicitly reuses
ADR-006 §1a's trigger rather than adding a third schedule) — this is a
genuine interface dependency, not just file overlap. Also extends
`cache.py` after TASK-0006 (both add accessors to the same file,
sequential).

## Acceptance Criteria
- Given the diagnostics switch is off, When any diagnostic sensor is
  read, Then it reports `state: "disabled"` with no `series` attribute,
  and the coordinator performs no extra per-string fitting (zero cost
  when off, ADR-004 §1).
- Given the switch is on and auto-tracking, When the diagnosed slot is
  determined, Then it defaults to the **last complete** 5-minute slot,
  not the next upcoming one (ADR-004 §2).
- Given `shady.select_diagnostic_slot` is called with a timestamp, When
  the resulting slot is within the available `FC` horizon, Then it pins
  every diagnostic sensor (per-string and summed alike) to that slot —
  there is exactly one diagnosed-slot state per config entry, not one per
  sensor (ADR-004 §2a).
- Given a future-pinned slot, When rendered, Then `"selected {method}"`
  entries still appear (evaluated against the forward-looking `FC`), but
  `"selected actual"` is omitted from `series` and `accuracy` is an empty
  `{}` (ADR-004 §2/§2a).
- Given `get_pinned_slot_pool(sensor_ids, slot_of_day)` with no pin set,
  When called, Then its window resolves to `[today - window_days,
  today]`; with a pin to a past date, Then it resolves to `[pinned -
  window_days, pinned]`; with a pin to a future date, Then it falls back
  to the same today-anchored window as auto-tracking (ADR-007a §6).
- Given the diagnostics switch is on, When recalibration runs, Then all
  four regression strategies are fitted for the diagnosed slot only
  (not all 288), and this extra cost disappears the moment the switch is
  off (ADR-004 §4).
- Given `ShadyDiagnosticsSumSensor`, When computed, Then it is the
  pointwise sum across strings at the one shared diagnosed slot, with
  `accuracy` derived from the *summed* predicted/actual values, not an
  average of per-string accuracies (ADR-004 §2b).
- Given accuracy is computed, When `predicted_i` is more than 100% off
  from `PV_selected`, Then the displayed accuracy is clamped to `0%`, not
  a negative number (ADR-004 §2).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/cache.py` (extended — `get_pinned_slot_pool`,
  `pinned_reference`)
- `custom_components/shady/switch.py` (new — `ShadyDiagnosticsSwitch`)
- `custom_components/shady/sensor.py` (extended — `ShadyDiagnosticsSensor`,
  `ShadyDiagnosticsSumSensor`)
- `custom_components/shady/aggregation.py` (extended — accuracy function)
- `custom_components/shady/coordinator.py` (extended — 4-method diagnostic
  fitting, hooked to TASK-0013's 5-minute trigger)
- `custom_components/shady/__init__.py` (extended — service registration)
- `tests/test_cache_pinned_slot_pool.py` (zero-mocking),
  `tests/test_diagnostics.py` (real `hass` fixture)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- TASK-0006's and TASK-0013's existing test suites still pass.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0002, TASK-0006, TASK-0010, TASK-0011,
     TASK-0013. -->
- `cache.<Cache class>` (post-TASK-0006 state) from `custom_components/shady/cache.py` (→ task: TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor)
- `coordinator.ShadyCoordinator` from `custom_components/shady/coordinator.py` (→ task: TASK-0010-coordinator-recalibration-recompute-push)
- `sensor.ShadyForecastSensor` (entity patterns) from `custom_components/shady/sensor.py` (→ task: TASK-0011-forecast-sensor-and-recalculate-button)
- `coordinator.ShadyCoordinator` (5-minute trigger) from `custom_components/shady/coordinator.py` (→ task: TASK-0013-intraday-deviation-correction)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
