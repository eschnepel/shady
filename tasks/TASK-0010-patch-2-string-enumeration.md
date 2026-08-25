# Task: Patch — Public String Enumeration for Per-String Entities

- **Status:** done
- **Related ADRs:** [ADR-000 §5, ADR-002 §5]
- **Dependencies:** [TASK-0010-coordinator-recalibration-recompute-push]

## Goal
`ShadyCoordinator` resolves every configured string into a private
`list[_StringConfig]` (`self._strings`) at construction time, but
exposes no public way to enumerate them. `TASK-0011`'s `sensor.py` (one
`ShadyForecastSensor` per string) and, later, `TASK-0015`'s per-string
diagnostics sensors both need to know how many strings are configured
and each one's `(index, name)` to construct their entities — without
reaching into the private `_StringConfig` list directly, which ADR-000
§5's naming convention ("private helpers... are not exported") and this
project's own Consumed/Delivered-Artifact discipline both rule out.
Discovered while gathering `TASK-0011`'s Consumed Interfaces (Scenario
C), before any `TASK-0011` code was written. `TASK-0010` stays `done`,
unreopened. Kept as its own small patch (not folded into
`TASK-0010-patch-1`) to stay independently reviewable, mirroring
`TASK-0005`'s own precedent of several small, focused patches over one
larger one.

## Acceptance Criteria
- Given a config entry with N configured strings, When the coordinator's
  new public accessor is called, Then it returns exactly N `(index,
  name)` pairs, in the same order `CONF_STRINGS` was configured in.
- Given the returned pairs, When inspected, Then no private
  `_StringConfig` instance or type is exposed — only the `(int, str)`
  tuple shape.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/coordinator.py` (one new public method)
- `tests/test_coordinator.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
- `coordinator._strings` / `_StringConfig` — already-private, same-module
  data this patch exposes a public accessor for; no new external
  interface consumed.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/coordinator.py` → `ShadyCoordinator.strings(self) -> list[tuple[int, str]]`
  (public, no arguments). Returns `[(string.index, string.name), ...]`
  for every configured string, in `CONF_STRINGS` order. Exposes only the
  `(int, str)` tuple shape — never a `_StringConfig` instance.
- `tests/test_coordinator.py` → `TestStringEnumeration` (2 tests): the
  default single-string fixture, and a 2-string entry confirming order
  is preserved. Full suite 154/154 (152 pre-patch + 2 this patch).
- No external dependencies added.
- Gates: `ruff check`/`ruff format --check`/`mypy --config-file mypy.ini`
  all clean; 18 source files clean overall.
