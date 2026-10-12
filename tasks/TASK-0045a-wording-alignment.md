# Task: Apply the Glossary Wording to ADRs, Code Comments and Test Names (No Behavior Change)

- **Status:** review (awaiting Gate 2 approval)
- **Related ADRs:** \[ADR-002, ADR-004 (or its split parts per TASK-0046),
  ADR-005, ADR-006, ADR-007a, ADR-008, ADR-013\]
- **Dependencies:** \[TASK-0046-adr-hygiene-collapse-and-split,
  TASK-0041-patch-1-intraday-window-ends-at-last-complete-slot\]

> Part of the split of `TASK-0045-apply-glossary-terminology` (decision record
> for the grill of 2026-10-11; decisions G5–G8 below are copied from it, so this
> file is self-contained). `GLOSSARY.md` is already updated and is the authority
> for every term. **No semantics, no logic, no public identifier changes.**

## Goal

Make ADR text, docstrings, comments and test names speak the language of
`GLOSSARY.md`. Pure wording.

## Decisions (human, grill 2026-10-11 — inputs, do not re-ask)

- **G5 — Terms.** _Followed slot_ replaces "analysed slot" (which has no
  occurrence in the repo). _Following_ is the diagnostics' mode (vs pinned).
  _Training window_ (days) and _Intraday window_ (slots, ending at the followed
  slot) are the only windows; "rolling window" and an unqualified "window" are
  `_Avoid_` for both. ADR-006's `window_slots` window is the **intraday
  window**; the `window_days` window of ADR-001/007a/008 is the **training
  window** — decide per occurrence. Config keys `window_days` / `window_slots`
  are **unchanged**.
- **G6 — Rename scope.** "auto-track\*" → "following" / "followed slot" and
  "last complete slot" → "last completed slot", everywhere (ADR text, code,
  comments, test names). "auto-track" is prose plus three test class names
  (`TestGetPinnedSlotPoolNoPinAutoTracksToday`, `TestDiagnosedSlotAutoTracking`,
  `TestAutoTrackingPinnedPoolSurvivesTheTrim`); production identifiers already
  say "follow" — no entity ID, translation, README string or persisted key is
  affected. Task file names (e.g. `…-last-complete-slot.md`) and past
  refinement-log rows stay as history. Pure wording edits in ADRs need **no**
  amendment entry (lean-ADR policy, G14).
- **G7 — Glossary.** Recalibration and Recompute are glossary terms; **no**
  `_Avoid_` for them and **no** rename of `async_refit` / `_refit_sync` /
  `_recompute_string`.
- **G8 — `slot_of_day`** stays (ADR-015 CSV metadata); do not rename it.
- **G14 — Lean ADRs.** Edit the main text in place; **do not add `Amendment`
  blocks**; keep section numbers stable.

## Acceptance Criteria

- Given the glossary, when the repo is searched for each `_Avoid_` term —
  "auto-track\*", "last complete slot", "analysed slot", "rolling window", and
  every unqualified "window" that means a training or intraday window — then
  there is no occurrence except in quoted history (git, past refinement-log
  rows, task file names, `TASK-0045*`/`TASK-0046` decision text).
- Given the diff of `custom_components/`, then it contains only docstring and
  comment changes; no identifier except the three test class names changes.
- Given the test suite, when run, then it passes with an unchanged number of
  tests (renamed, not added or removed).
- Given the ADRs, then no `Amendment` block was added and no section number
  changed.
- `mdformat --check`, `ruff check`, `ruff format --check`, `mypy` clean.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator_like.py` (docstring ~l.127),
  `aggregation.py` (~l.215), `coordinator.py`, `cache.py`, `sensor.py`,
  `diagnostics/*.py` — comments/docstrings only
- `tests/` — three class renames plus comment/docstring wording
- `adr/002`, `adr/004*`, `adr/005`, `adr/006`, `adr/007a`, `adr/008`, `adr/013`,
  `tasks/adr-summary.md`, `README.md` if it uses a `_Avoid_` term

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate (list of renamed test
  classes and the files whose wording changed)
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none)

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation. -->

- none (wording only; touches every file that contains a `_Avoid_` term)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
