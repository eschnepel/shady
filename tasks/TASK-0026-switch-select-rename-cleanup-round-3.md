# Task: Finish switch→select Rename, Round 3

- **Status:** todo
- **Related ADRs:** [ADR-004, ADR-002, ADR-007]
- **Dependencies:** [TASK-0018-hacs-select-rename-cleanup]

## Goal
ADR-004's 2026-08-30 amendment replaced `switch.py`/`ShadyDiagnosticsSwitch`
with `select.py`/`ShadyDiagnosticModeSelect`. `TASK-0018` already cleaned
up three non-code files (`hacs.json`, `mypy.ini`, `README.md`) that were
never updated for this rename. Two audits run since then (`AUDIT-0011`,
`AUDIT-0012`) each independently found one more file `TASK-0018` missed:

1. **`docs/architecture.mmd`** still shows the pre-amendment `switch`
   architecture — `subgraph Diag["Diagnostics (optional, via switch)"]` /
   `SWITCH([Switch: diagnostics<br/>default off])` — confirmed by
   repo-wide grep to be the **only** remaining file outside `tasks/`/
   `adr/` still referencing "switch."
2. **ADR-002 §1a's own decision text** still reads "...forward this
   config entry's platforms (`sensor`/`switch`/`button`) exactly as
   usual..." — a stale reference; the code is correct throughout
   (`PLATFORMS = ["sensor", "select", "button"]`).
3. **ADR-007's own module diagram** also still lists `switch.py` in its
   `entity_glue` node (found incidentally by `AUDIT-0011`, outside its
   own declared scope, but the same defect).

This task is purely a continuation of `TASK-0018`'s already-decided
cleanup — no new decision, no code change, matching that task's own
established pattern exactly.

## Known Decisions
- The fix is mechanical: replace every remaining "switch" reference in
  the three listed locations with the equivalent "select" wording,
  matching how `TASK-0018` already resolved the same class of finding
  in `hacs.json`/`mypy.ini`/`README.md`. No decision needed.
- `docs/architecture.mmd`'s `SWITCH` node should become a `SELECT` node
  (or equivalent Mermaid shape already used elsewhere in the diagram
  for entity nodes) labeled to match `select.py`'s actual entity —
  mirror whatever shape/labeling convention the diagram already uses
  for its other entity nodes, don't invent a new one.

## Open Questions for Execution
- None expected — this is a mechanical text/diagram correction with a
  single obviously-correct outcome in each of the three locations. If
  the worker finds a fourth location during its own repo-wide grep that
  none of the three prior audits caught, flag it here before fixing it
  silently, per the golden rule — but do not expect one; three
  independent audits (`AUDIT-0008`, `AUDIT-0009`, this task's own grep)
  have already searched for residue.

## Acceptance Criteria
- Given `docs/architecture.mmd`, When read after this task, Then it
  describes the select-entity architecture (no `SWITCH` node, no
  "via switch" text) — the equivalent `SELECT` node/label replaces it,
  consistent with the diagram's own existing node-labeling style.
- Given `adr/002-coordinator-update-strategy.md` §1a, When read after
  this task, Then its platform list reads "`sensor`/`select`/`button`",
  not "`sensor`/`switch`/`button`."
- Given `adr/007-coordinator-cache-split.md`'s module diagram, When read
  after this task, Then it lists `select.py`, not `switch.py`, in its
  `entity_glue` node.
- Given a repo-wide case-insensitive grep for "switch" excluding
  `tasks/` and `adr/`'s own historical-rename narrative (already
  confirmed clean by `TASK-0018`/`AUDIT-0009`), When run after this
  task, Then it also returns nothing inside `adr/002-...md`,
  `adr/007-...md`, or `docs/architecture.mmd` beyond any remaining
  historical-narrative mentions of the rename itself (e.g. "this
  replaced the earlier switch-based design") — a historical mention is
  fine, a description of switch as the *current* architecture is not.
- Given the full test suite, When run after this task, Then it is
  unchanged (this task touches no `.py` file).

## Estimated File / Module Footprint (hint, not a commitment)
- `docs/architecture.mmd`
- `adr/002-coordinator-update-strategy.md`
- `adr/007-coordinator-cache-split.md`
- No `.py` file, no test file.

## Definition of Done
- Tests green (unchanged) · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
- `custom_components/shady/select.py` → `ShadyDiagnosticModeSelect` — (→
  task: TASK-0015b-diagnostics-select-and-scatter-sensors) — the
  already-implemented entity this task's diagram/text corrections must
  describe accurately.
- `custom_components/shady/__init__.py` → `PLATFORMS = ["sensor",
  "select", "button"]` — (→ task: TASK-0016-integration-setup-entry) —
  the authoritative platform list ADR-002 §1a's text must match.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
