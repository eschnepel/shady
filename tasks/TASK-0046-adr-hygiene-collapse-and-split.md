# Task: ADR Hygiene — Collapse Stacked Amendments, Split Oversized ADRs (Text Only)

- **Status:** review (awaiting Gate 2 approval)
- **Related ADRs:** [ADR-004, ADR-006, ADR-007a, ADR-008]
- **Dependencies:** \[TASK-0043-wire-cache-trim-into-recalibration,
  TASK-0044-local-day-training-window\]

> Origin: grill of 2026-10-11 on `TASK-0045` (decision record, G14 and the _ADR
> hygiene_ evaluation there). This task runs **first** of the `TASK-0045` family
> so that every later wording or semantics edit lands in lean text instead of
> becoming a further amendment. **No code, no test, no behavior changes.**

## Goal

The human's rule: _"Keep the ADRs lean. I do not like to be overflooded by the
5th amendment changing the 3rd aspect of the 2nd amendment. If an ADR is too
large, evaluate whether it can be collapsed (integrating the amendments into the
main text) and/or split."_

Make the in-scope ADRs read as one coherent, current description of the system:
integrate every amendment into the section it amends, delete superseded text
(history lives in git and in the task files), and — where an ADR is too large —
split it. The result must **say exactly what the stack of amendments says
today** (TASK-0043's and TASK-0044's amendments included, as they stand; the
later `TASK-0045c` rewrites them).

## Scope (measured 2026-10-11: lines / amendment blocks / `###` sections)

| ADR | Size | Amendments | Work |
| -- | -- | -- | -- |
| ADR-004 | 1354 / 7 / 15 | §2c–§2i, with supersession chains (2d supersedes 2c; 2f supersedes the service of §2a; 2g supersedes 2f's clear button; 2i reinterprets the tick) | **Collapse** all seven into the main text of §2/§2a/§2b, keeping the stable numbers as headings and dropping "Amendment" framing and superseded text. **Propose a split** into three parts: (1) mode select + `DiagnosticMode` interface (§1, §1a, §5); (2) scatter-series sensors and chart entry shape (§2, §2b–§2e, §2h); (3) diagnosed-slot selection, following and pinning (§2a, §2f, §2g, §2i). §3/§4 (historical pool caching, extra fitting cost) belong beside the cache ADR — propose where. |
| ADR-007a | 710 / 5 / 6 | TASK-0043 (§1), TASK-0034, TASK-0037-patch-5, TASK-0042, TASK-0037 | **Collapse.** Evaluate (propose, do not decide) splitting the threading contract (TASK-0042) from storage design. |
| ADR-008 | 286 / 2 / 3 | TASK-0037 batching edge; TASK-0044 window | **Collapse.** No split. |
| ADR-006 | 444 / 1 / 7 | TASK-0041 slot trigger | **Collapse.** |

Out of scope: ADR-002 (no amendments; edited in place by `TASK-0045d`), ADR-005,
ADR-013 (wording only, `TASK-0045a`), ADR-015 (two amendments; revisit when next
touched).

## Method

1. **Mini-gate first (no text moved yet).** The worker writes, into this task's
   _Delivered Artifacts_ draft, (a) per amendment: the target main-text section
   and a one-line statement of each decision it carries (the semantics
   checklist), and (b) for every proposed split: the old-§ → new-location table.
   Then **stop and present it to the human**. New split ADRs start as **Draft**
   until the human confirms them.
1. **Collapse rules.** Integrate into the amended section; remove the
   `Amendment (date, task)` framing; delete text that a later amendment
   superseded (including "marked superseded" blocks such as §2c); keep decisions
   that still stand; keep `Decided by` only where it records a human decision
   the main text would otherwise lose (one short line, not a block).
1. **Section numbers stay stable.** About 125 places outside ADR-004 cite
   §2c–§2i (code 38, tests 26, tasks ≈ 33, other ADRs 14, `adr-summary.md` 14);
   ADR-007a §1/§6 and ADR-008 §2 have 46/68/72 references. Headings keep their
   numbers. For a split, `ADR-004` stays as the **umbrella**: short context +
   decision summary + an old-§ → new-ADR index table, so every existing
   `ADR-004 §x` reference still resolves. Rewriting outside references is not
   required here (`TASK-0045a` edits many of those lines anyway).
1. Update `tasks/adr-summary.md` wherever a section moved. Do not change any
   decision, number, name or default.

## Acceptance Criteria

- Given the in-scope ADRs, when searched for `Amendment`, then no amendment
  block remains in their main text (quoted history in `tasks/*.md` is fine).
- Given the semantics checklist from the mini-gate, when the reviewer walks it,
  then every decision of every former amendment appears exactly once in the
  collapsed text and nothing superseded survives.
- Given every `ADR-00x §n` reference in `custom_components/`, `tests/`,
  `tasks/`, `adr/` and `README.md`, when a script resolves it (heading exists in
  the target ADR, or the umbrella index redirects it), then there are no
  unresolved references.
- Given a split was approved, then each new ADR is marked **Draft** until the
  human confirms it, and the umbrella index lists every old section.
- Given the diff, then it touches `.md` files only (no `.py`, no tests), and
  `mdformat --check` is clean on every edited file.

## Estimated File / Module Footprint (hint, not a commitment)

- `adr/004-diagnostics-select-and-scatter-sensor.md` (+ up to three new
  `adr/004a|b|c-*.md`), `adr/006-intraday-deviation-correction.md`,
  `adr/007a-cache-storage-and-accessor-design.md` (+ possibly one split ADR),
  `adr/008-numpy-backend-and-cache-array-accessor.md`
- `tasks/adr-summary.md`; a throwaway reference-resolver script (not committed)

## Definition of Done

- Tests green (untouched) · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate (old-§ → new-§ table
  included)
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected)

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation. None: text-only task. -->

- none (ADR text only)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
