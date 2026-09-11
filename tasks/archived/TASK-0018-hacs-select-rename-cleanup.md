# Task: HACS/Tooling-Config Cleanup — Finish the switch→select Rename

- **Status:** done
- **Related ADRs:** [ADR-004, ADR-000]
- **Dependencies:** \[TASK-0015b-diagnostics-select-and-scatter-sensors,
  TASK-0016-integration-setup-entry\]

## Goal

ADR-004's 2026-08-30 amendment replaced `switch.py`/`ShadyDiagnosticsSwitch`
with `select.py`/`ShadyDiagnosticModeSelect`. The application code and its own
tests were updated at the time (`TASK-0015b`); `__init__.py`'s `PLATFORMS` list
confirms `select`, not `switch` (`TASK-0016`). Three non-code files were never
updated for the same rename and still describe a `switch` domain/entity that
does not exist anywhere in this repo, while one is also missing the equivalent
`select` entry it should have gained instead. This task finishes that
propagation — no new decision, purely catching up already-decided ADR-004
content to files outside `custom_components/` and `tests/`.

## Acceptance Criteria

- Given `custom_components/shady/hacs.json`, When read after this task, Then
  `"domains"` is `["sensor", "select", "button"]`, not
  `["sensor", "switch", "button"]`.
- Given `hacs.json`'s `"homeassistant"` key, When read after this task, Then it
  matches ADR-000's own documented amendment value (`"2026.3"`), not the
  currently-present `"2026.3.1"` (a patch digit ADR-000 never specified).
- Given `mypy.ini`, When read after this task, Then there is no
  `[mypy-shady.switch]` section (dead — no `switch.py` file exists to apply it
  to) and there is a `[mypy-shady.select]` section with
  `warn_unused_ignores = False`, matching the treatment already given to
  `config_flow`/`sensor`/`coordinator`/`button` for the same
  HA-base-class-is-`Any` reason (`select.py`'s
  `class ShadyDiagnosticModeSelect(SelectEntity):  # type: ignore[misc]`). The
  section comment block naming which modules need this treatment is updated to
  say `select.py` (`ShadyDiagnosticModeSelect`, ADR-004 §2a), not
  `switch.py`/`ShadyDiagnosticsSwitch`.
- Given `README.md`'s description of the diagnostics feature (currently
  "diagnostics switch, default off"), When read after this task, Then it
  describes a select entity instead, in wording consistent with how the rest of
  the README already describes other entities.
- Given `mypy --config-file mypy.ini custom_components/ tests/` and
  `ruff check .`/`ruff format --check .`, When run after this task, Then all
  three remain clean (aside from the two pre-existing, unrelated `ruff format`
  drift files already noted in `tasks/INDEX.md`'s refinement log:
  `adr/004-diagnostics-select-and-scatter-sensor.md`,
  `tests/test_regression.py`).
- Given the full test suite, When run after this task, Then it is still 414/414
  green — this task touches no `.py` source file's behavior, only config/docs
  and one `mypy.ini` per-file section.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/hacs.json`
- `mypy.ini`
- `README.md`
- No `.py` files, no ADR amendment (ADR-004 already made this decision; this
  task only finishes propagating it)

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected — pure config/doc text)

## Consumed Interfaces

- `custom_components/shady/select.py` → `ShadyDiagnosticModeSelect` (→ task:
  TASK-0015b-diagnostics-select-and-scatter-sensors) — only its existence/name
  matters here, to confirm what `hacs.json`/`mypy.ini` should say; no code from
  it is imported by this task.
- `custom_components/shady/__init__.py` →
  `PLATFORMS = ["sensor", "select", "button"]` (→ task:
  TASK-0016-integration-setup-entry) — the authoritative, already-implemented
  platform list this task's `hacs.json` fix must match.

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->

- `hacs.json` (repo root — **not** `custom_components/shady/hacs.json` as the
  Estimated Footprint hint guessed; corrected here since downstream readers of
  this block should get the real path, not the estimate) → `"domains"` changed
  to `["sensor", "select", "button"]`; `"homeassistant"` changed to `"2026.3"`
  (patch digit dropped).
- `mypy.ini` → `[mypy-shady.switch]` section removed; `[mypy-shady.select]`
  section added (`warn_unused_ignores = False`), same treatment as
  `config_flow`/`sensor`/`coordinator`/`button`; the shared comment block above
  it updated to name `select.py` (`ShadyDiagnosticModeSelect`, ADR-004 §2a)
  instead of `switch.py`/`ShadyDiagnosticsSwitch`.
- `README.md` → point 6's "diagnostics switch, default off" reworded to "a
  diagnostic-mode select entity, default off"; no other text in that paragraph
  changed.
- No `.py` source file touched; no new external dependency —
  `tasks/DEPENDENCIES.md` unchanged.
- Verification: full suite 414/414 (behavior-unchanged, config/docs-only task);
  `mypy --config-file mypy.ini custom_components/ tests/` clean on 52 source
  files; `ruff check .` clean repo-wide; `ruff format --check .` shows only the
  two pre-existing, unrelated drift files already on record in
  `tasks/INDEX.md`'s refinement log (`tests/test_regression.py`,
  `adr/004-diagnostics-select-and-scatter-sensor.md`'s embedded code block) —
  neither touched by this task. `git diff --stat` confirms only `README.md`,
  `hacs.json`, `mypy.ini` changed.
- Remaining "switch" mentions repo-wide (checked via grep) are all inside
  already-`done` task files / `tasks/adr-summary.md`, describing the historical
  rename itself or listing an older task's own original scope wording — not this
  task's Acceptance Criteria, left untouched.
