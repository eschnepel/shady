# Task: ADR Hygiene — Collapse Stacked Amendments, Split Oversized ADRs (Text Only)

- **Status:** in-progress (ADR-004 collapsed; split evaluation presented at the
  gate, awaiting the human)
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
| ADR-004 | 1354 / 7 / 15 | §2c–§2i, with supersession chains (2d supersedes 2c; 2f supersedes the service of §2a; 2g supersedes 2f's clear button; 2i reinterprets the tick) | **Collapse** all seven into the main text of §2/§2a/§2b, keeping the stable numbers as headings and dropping "Amendment" framing and superseded text. **Collapsed 2026-10-12.** Split evaluated afterwards (original proposal: three parts; evaluated against two-way cuts and no split, see Delivered Artifacts, *gate*). |
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
1. **Section numbers stay stable, and references are updated rather than left to
   hop.** Headings keep their numbers. A section that disappears or moves is
   listed in the `## Redirects` table of the ADR it left (ADR-000 §10).
   **Processing an ADR includes updating the references to whatever moved, by
   generic find/replace where that is possible**, so that resolving a reference
   later never needs a double hop: `python utils/adr_refs.py --rewrite` (a dry
   run by default; `--write --ext md` applies it). The tool rewrites only
   unambiguous single-target redirects. It lists ranges, mixed targets and
   sections split between several ADRs as manual work, and it never touches
   finished tasks (`Status: done`), which are audit trail and quote sections as
   they were. This task changes no code, so `.py` comments and docstrings are
   not rewritten and stay double hops.
1. **Lookup table for what a find/replace cannot reach.** A citation by an
   amendment's name ("§5, second Amendment") cannot be replaced generically.
   Every processed ADR therefore carries a _Citations by amendment name_ table
   (name, date, what it changed, where it lives now). **When a referencing text
   is changed for any reason, a double-hop reference in it is changed to the
   real target section at the same time** — including the `.py` comments
   `TASK-0045a` edits anyway.
1. Update `tasks/adr-summary.md` wherever a section moved. Do not change any
   decision, number, name or default.

## Acceptance Criteria

- Given the in-scope ADRs, when searched for `Amendment`, then no amendment
  block remains in their main text (quoted history in `tasks/*.md` is fine).
- Given the semantics checklist from the mini-gate, when the reviewer walks it,
  then every decision of every former amendment appears exactly once in the
  collapsed text and nothing superseded survives.
- Given `python utils/adr_refs.py --adr <n>` for each processed ADR, then it
  reports 0 unresolved references. Double hops remain only in finished-task
  files, `.py` files and expressions the tool lists as manual; each is counted
  in the Delivered Artifacts.
- Given a split was approved, then each new ADR is marked **Draft** until the
  human confirms it, and the `## Redirects` table of the origin ADR lists every
  moved section.
- Given the diff, then it touches `.md` files, the new `utils/adr_refs.py` and
  one argument of the mypy hook in `.pre-commit-config.yaml` — no behavior code,
  no tests; `mdformat --check` is clean on every edited Markdown file, and
  `ruff` and `mypy --strict` are clean on `utils/`.

## Estimated File / Module Footprint (hint, not a commitment)

- `adr/004-diagnostics-select-and-scatter-sensor.md` (+ up to three new
  `adr/004a|b|c-*.md`), `adr/006-intraday-deviation-correction.md`,
  `adr/007a-cache-storage-and-accessor-design.md` (+ possibly one split ADR),
  `adr/008-numpy-backend-and-cache-array-accessor.md`
- `tasks/adr-summary.md`, `adr/INDEX.md`; `utils/adr_refs.py` (new), ADR-000 §10
  (new, lean) and `.pre-commit-config.yaml` (the mypy hook covers `utils/`)

## Definition of Done

- Tests green (untouched) · docs updated · no open ADR conflicts ·
  `utils/adr_refs.py` reports 0 unresolved for every processed ADR
- `Delivered Artifacts` block completed and accurate (old-§ → new-§ table
  included)
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected)

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation. None: text-only task. -->

- none (ADR text only)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->

### State

The task runs ADR by ADR in the Scope table's order: ADR-004, then ADR-007a,
then ADR-008, then ADR-006. The next ADR starts only after the previous one is
finished and accepted. **Current state: ADR-004 is collapsed (sections 1 to 4
below) and its split is evaluated (section 5), which is a gate.** ADR-007a,
ADR-008 and ADR-006 are untouched. This block is replaced by the final old-§ to
new-§ table for all four ADRs when the task completes.

**Gate decisions of 2026-10-12.** D4: the Lead-Agent details of §2g and §2h are
confirmed and implementation detail stays out of the ADR (point sizes, rounding
calls, symbol names, private attribute names were not carried over; the §2
example block still shows the emitted marker shape). D5 to D8 as proposed
(defaults). Also decided: the resolver lives in `utils/` (ADR-000 §10, lean);
processing an ADR includes updating references by find/replace; the lookup table
stays, with the rule that a double hop is fixed to the real target whenever its
text is edited.

### ADR-004

#### 0. Measured baseline (2026-10-12, before any edit)

| Measure | Value |
| -- | -- |
| Size | 1354 lines, 15 `###` sections, 18 Consequences bullets |
| Amendment blocks | 7 (§2c to §2i) = 368 lines = 27 % of the file. Plus a 60-line history header and 14 inline "as of <date>" notes in §1 to §5 and Consequences (6 more in the header) |
| Supersession chains | §2c is replaced by §2d the same day. §2f's service text is replaced by §2f's own button, which §2g replaces. §2i redefines every "5-minute tick" in the ADR |
| Citations `ADR-004 §x` repo-wide (code, tests, tasks, other ADRs, adr-summary) | §1 39 · §1a 12 · §2 79 · §2a 52 · §2b 26 · §2c 2 · §2d 20 · §2e 5 · §2f 19 · §2g 43 · §2h 17 · §2i 11 · §3 11 · §4 29 · **§5 145**. §2c to §2i together: 117 (the task text's "about 125" was an estimate) |
| Citations of ADR-004 amendments **by name** ("§5, second Amendment", "§2i Amendments") | 92 outside ADR-004: code 35, tests 19, tasks 28, adr-summary 6, other ADRs 4 (ADR-000, 013, 014, 015) |
| Bare `§n` references inside ADR-004's own text | 161 (7 more point at §5). Under the proposed split 80 stay inside their part and 81 cross, 9 of which point at §2c and vanish with it, so about 72 must be qualified (`ADR-004c §2g`). Heaviest coupling: series and diagnosed slot, 36 references both ways |
| Resolver baseline | 3622 `ADR-xxx §n` references checked repo-wide; **0 unresolved** for ADR-004, 006, 007a, 008. 19 pre-existing unresolved elsewhere (ADR-001 sections 3c, 3d and 6; ADR-003 sections 1 to 3, because the superseded umbrella has no headings; ADR-007 sections 1f and 4); not caused by and not in scope of this task |
| Formatting baseline | `mdformat` 1.0.0 with the gfm, config and ruff plugins (the pre-commit set): ADR-004, this task and `tasks/INDEX.md` are clean |

#### 1. Semantics checklist (a): what each amendment decides, where it lands, what dies

**Fate** values: _keep_ (decision stands, stated exactly once), _merge_ (folded
into the named section), _delete_ (superseded or history; survives only in git
and the task files). **Lands in** names the section in the collapsed text, with
the part in brackets if the split is approved (if it is not, everything stays in
ADR-004). Wording is not changed beyond what collapsing needs: "auto-tracking",
"last complete slot" and the other pre-glossary terms stay for `TASK-0045a`.

**Headings as implemented.** The stable numbers survive as headings, without
"Amendment" framing: §2d "Series entry shape and dashboard consumption" · §2e
"The shared entry builder" · §2f "Setting the diagnosed slot: the `datetime`
entity" · §2g "Following and pinning: the `switch` and the always-set diagnosed
slot" · §2h "Chart marker styling" · §2i "The slot trigger". **§2c has no
surviving content, so its heading is removed** and the umbrella index redirects
`§2c` to `§2d`.

##### §2c (2026-09-21, TASK-0015b-patch-1)

| ID | Decision carried | Lands in | Fate |
| -- | -- | -- | -- |
| 2c-1 | `series` entries move from `{name, data}` to the `apexcharts-card` shape `entity`/`name`/`data_generator`, replacing the old shape outright (human: one format, not two) | none | delete (superseded by 2d-1); the "one shape only" principle is implicit in §2 |
| 2c-2 | `data_generator` is `"return " + json.dumps(points)`; `entity` is the sensor's own `entity_id` | none | delete (2d drops both) |
| 2c-3 | `accuracy` stays a plain `{method: 0.0 to 1.0}` dict, never series-shaped | [b] §2 (accuracy paragraph already says it) | keep, not restated |
| 2c-4 | `apexcharts-card` cannot plot a numeric x-axis; do not retry it for this chart | [b] §2d, one clause in the reason for `plotly-graph` | merge (decision D5) |
| 2c-5 | The "Superseded same day" block and the Decided-by block | none | delete |

##### §2d (2026-09-21, TASK-0015b-patch-2)

| ID | Decision carried | Lands in | Fate |
| -- | -- | -- | -- |
| 2d-1 | Each `series` entry is `{entity: "", name, type: "scatter", mode: "markers", x: [...], "y": [...]}`, x and y as parallel flat arrays | [b] §2 entry shape (the example block already shows it) | keep |
| 2d-2 | `entity` is a constant empty string (the key must exist for `plotly-graph`'s schema); `type` and `mode` are constant | [b] §2 | keep |
| 2d-3 | `diagnostics/` builds the whole entry; `sensor.py` reshapes nothing | [b] §2 and §5 `sensor.py` paragraph | keep once; the "injection was briefly added and removed" history is deleted |
| 2d-4 | Canonical consumption: one `custom:plotly-graph` card whose `entities:` is the whole `series` list through the `state_attr` Jinja pattern | [b] §2d | keep; stated three times today (§2, §2d, §2h), collapse to once |
| 2d-5 | Design constraint: the shape must round-trip through Python `str()` into valid YAML (strings, numbers, lists, mappings; no booleans, no `None`) | [b] §2d | keep once |
| 2d-6 | `"y"` stays an explicitly quoted key in any YAML rendering (YAML 1.1 reads bare `y` as a boolean); the example is fenced `yml` so `mdformat` keeps the quotes | [b] §2 (callout already in the main text) | keep unchanged |
| 2d-7 | Human confirmed the shape and the dashboard template against a running instance | decision record (see D8) | keep as one line |

##### §2e (2026-09-21, TASK-0015b-patch-3)

| ID | Decision carried | Lands in | Fate |
| -- | -- | -- | -- |
| 2e-1 | `_xy_series_entry(name, points)` lives on `DiagnosticMode` (`diagnostics/base.py`) as an inherited `@staticmethod`; every mode gets it without importing `compare_regressions.py` | [b] §2e, plus one pointer sentence in [a] §1a | keep |
| 2e-2 | It is not an `@abstractmethod`: every mode that wants this shape wants it identically; a mode with another shape simply does not call it | [b] §2e | keep |
| 2e-3 | Reason: ADR-013's sketched modes need the same shape, and a local copy would drift | [b] §2e, one clause | merge |
| 2e-4 | `CompareRegressionsMode` now calls `self._xy_series_entry`, values byte-identical, no test changed | none | delete (relocation history) |
| 2e-5 | Human identified the base-class need | decision record (D8) | keep as one line |

##### §2f (2026-09-23)

| ID | Decision carried | Lands in | Fate |
| -- | -- | -- | -- |
| 2f-1 | `datetime.py`'s `ShadyDiagnosticSlotDateTime` (`DateTimeEntity`), one per config entry, pins through `pin_diagnostic_slot()` and rejects beyond-horizon timestamps by raising `HomeAssistantError` | [c] §2f | keep |
| 2f-2 | Validation and rounding: round down to the 5-minute boundary; reject only beyond ADR-002 §3's forecast horizon; any past timestamp is accepted | [c] §2a, where `pin_diagnostic_slot` is specified; §2f refers to it | keep once (stated in §2a and again in §2f today) |
| 2f-3 | Why an entity and not a service: config-entry state is a thin HA entity everywhere else here, and a `datetime` has a picker | [c] §2f, short rationale | merge |
| 2f-4 | A `datetime` entity cannot express "clear" (HA's frontend always sends a value), so returning to following needs a second control | [c] §2g, as the rationale for the switch | merge |
| 2f-5 | Entry-scoped (one per config entry, device grouping through `device.py`), not broadcast to every loaded entry like the old service | [c] §2f | keep |
| 2f-6 | No service is registered any more; `services.yaml` is deleted | [c] §2f, one sentence | keep |
| 2f-7 | The clear button `ShadyClearDiagnosticSlotButton`, `clear_diagnostic_slot()`, `pinned_diagnostic_slot()`, `native_value` being `None` while following | none | delete (superseded by 2g-\*) |
| 2f-8 | The "superseded in part by §2g" block; the `shady.select_diagnostic_slot` service text and the "Superseded (mechanism only)" paragraph in §2a | none | delete |
| 2f-9 | Human asked for a `datetime` input instead of the service | decision record (D8) | keep as one line |

##### §2g (2026-09-24, TASK-0037-patch-4)

| ID | Decision carried | Lands in | Fate |
| -- | -- | -- | -- |
| 2g-1 | The coordinator holds the diagnosed slot as one always-set stored index plus a following flag (default on); `diagnosed_slot()` reads the stored index unconditionally, pinned or following; `is_elapsed` is still computed against `now` | [c] §2g | keep (private attribute names not carried over, D4) |
| 2g-2 | While following, the slot is **set** on every slot job (not derived on read) to `index_for(now) - 1`: first in the job, before any `extra_fit()`/`compute()`, whether or not a mode is active; also set at construction and immediately when following is switched on; the cached `compute()` result is not invalidated by the advance (the mode's `compute_cadence()` decides) | [c] §2g | keep |
| 2g-3 | `ShadyDiagnosticSlotDateTime.native_value` returns the slot's start timestamp in both modes, never `None`; setting it pins and thereby switches following off | [c] §2f (setting) and §2g (value) | keep once |
| 2g-4 | `switch.py`'s `ShadyFollowDiagnosticSlotSwitch`, one per config entry; `is_on` means following. On: `set_follow_latest_diagnostic_slot(True)` clears `cache.pinned_reference`, sets the newest complete slot immediately, invalidates the cached result. Off: `set_follow_latest_diagnostic_slot(False)` pins the slot as currently shown (no re-derivation from `now`), sets `cache.pinned_reference` to its date, invalidates the cached result, so switching off never moves anything | [c] §2g | keep |
| 2g-5 | `cache.pinned_reference` (ADR-007a §6) is deliberately not set while following; its cap keys off "genuinely pinned" | [c] §2g | keep |
| 2g-6 | Polling, not push: the entities use HA's default polling, so the as-of timestamp can lag a sensor's attributes by up to one polling interval | [c] §2g | keep |
| 2g-7 | Not persisted across restarts: a restart returns to following | [c] §2g | keep |
| 2g-8 | Removed: the button, `clear_diagnostic_slot()`, `pinned_diagnostic_slot()`; no registry migration because one installation exists | none | delete (history; the removal is covered by 2f-7) |
| 2g-9 | Human specified the follow/pin toggle, set-on-every-cadence, and diagnostics reading the configured slot. Lead-Agent details (on/off semantics, setting the datetime while following pins, trigger-first ordering, `pinned_reference` left unset while following) confirmed 2026-10-12 | decision record | keep, confirmed (D4) |

##### §2h (2026-10-04, TASK-0015b-patch-4)

| ID | Decision carried | Lands in | Fate |
| -- | -- | -- | -- |
| 2h-1 | `x`/`y` values are shown with at most one decimal, in `DiagnosticMode._xy_series_entry`; display-only: `accuracy`, the CSV export and all fitting keep full precision | [b] §2h | keep (rounding call and `-0.0` handling not carried over, D4) |
| 2h-2 | Slot-pool point size follows the point's fit weight (from `WeightBreakdown`, ADR-015 §6, so the chart cannot drift from the fit); whole numbers, minimum 1 so low-weight points stay visible | [b] §2h | keep (formula, factor and weight product not carried over, D4) |
| 2h-3 | An ADR-011 §2 excluded neighbor series is drawn as a stroke, sized by the weight it would have had without the exclusion; all other pool series state `circle` explicitly; with `neighbor_fitting_cutoff = -1%` nothing is excluded | [b] §2h | keep (Plotly symbol name not carried over in the prose, D4) |
| 2h-4 | `selected {method}` and `selected actual` are drawn as a cross at the default size | [b] §2h | keep |
| 2h-5 | The `"sum"` entry follows the same rules on its pointwise-summed pool | [b] §2h | keep |
| 2h-6 | Consumption pattern unchanged: `marker` is a nested mapping that still round-trips through `str()` into YAML | [b] §2d (single statement, 2d-5) | merge |
| 2h-7 | Human asked for the four changes. Lead-Agent details (stroke and cross symbols, minimum size, pre-exclusion sizing, weighting the sum entry from its summed pool) confirmed 2026-10-12 | decision record | keep, confirmed (D4) |

##### §2i (2026-10-07, TASK-0041)

| ID | Decision carried | Lands in | Fate |
| -- | -- | -- | -- |
| 2i-1 | Every "5-minute tick" in this ADR means the **slot trigger** (ADR-006 §1a): one job per `EVENT_RECORDER_5MIN_STATISTICS_GENERATED` that probes until the newest complete slot's actual is readable (first probe plus up to 5 retries, 1 s apart) and then, once and in this order: advances the followed slot (first, independent of any active mode, an integer assignment), refreshes the active mode's fit and compute per its cadences, publishes | [c] §2i as the single definition | keep |
| 2i-1b | Applying 2i-1 means rewording the 25 occurrences of "tick" in §1a, §2a, §2b, §2g, §3 and Consequences (and §4's "5-minute trigger") to "slot trigger" (and dropping §2a's "reuses the `async_track_time_interval(minutes=5)` trigger" sentence) | everywhere they occur | merge (decision D7) |
| 2i-2 | The followed slot and the chart it feeds advance in the same job, so the `datetime` as-of timestamp always matches the chart; with no mode active the advance still runs every job | [c] §2i | keep |
| 2i-3 | A result without the newest actual is never published and then replaced: readers keep the previous result until the job's compute completes; if a string never delivers, the job publishes without it after the bounded retries | [c] §2i | keep |
| 2i-4 | Pinned slots keep §2a semantics: the job still runs every slot, so a future-pinned or in-progress slot's prediction and a just-elapsed slot's actual and accuracy appear on the first job after they exist | [c] §2i | keep |
| 2i-5 | The wall-clock interval stays registered as a watchdog and runs the same job only when no event-driven job ran for six minutes | [c] §2i | keep |
| 2i-6 | §3's "slot-pool series are not refreshed on the trigger" is unchanged | [b] §3 | keep |
| 2i-7 | Human chose it; the retry and watchdog parameters were confirmed at Gate 2 (2026-10-08) | decision record (D8) | keep as one line |

#### 2. Inline history outside the seven blocks (also removed, nothing is lost)

- **Header (60 lines):** a running summary of 12 dated changes. Every decision
  in it already lives in §1a, §2 or §5 as current text. Replaced by a 3-line
  header.
- **§1's second paragraph** explains that "the switch" in "historical prose"
  means the select, and §3 still says "the diagnostics switch". After the
  collapse there is no historical prose; the wording becomes "mode select"
  throughout, which also removes the clash with the new
  `ShadyFollowDiagnosticSlotSwitch`.
- **14 inline "as of <date>" and "<date> Amendment" notes** (§1, §1a, §2, §2a,
  §2b, §3, §4, §5, Consequences) and §5's "briefly, 2026-09-21: `sensor.py`
  injected `entity`" paragraph are history; the present-tense statement next to
  each stays.
- **§5's `Amendment (2026-09-24, draft ADR-015)`** becomes a one-line
  cross-reference (see F1).
- **Consequences:** C16 starts "As of 2026-09-13"; reworded in present tense.

#### 3. Findings: status

- **F1, stale claim: resolved (D6).** §5 now says only that a raw-data CSV
  export is delivered through an HTTP view, see ADR-015; it names no module.
- **F2, never confirmed: resolved (D4).** Confirmed on 2026-10-12; the trimmed
  details are listed in the State block above.
- **F3, pre-existing drift carried verbatim, not fixed here** (this task changes
  no decision): "midnight" recalibration in §3 (title and body), §4 and
  Consequences, replaced by `TASK-0045d`'s 04:00; the pool window
  `[today - window_days, today]` in §2a, which differs from ADR-008 §2 and
  ADR-007a §1/§6 as amended by `TASK-0044` and replaced by `TASK-0045b`/`c`;
  "auto-tracking" and "last complete slot" against the glossary (`TASK-0045a`).
- **F4, duplication, not removed here.** ADR-007a §6 and ADR-004 §2a/§3 each
  describe how `get_pinned_slot_pool` resolves its window. Not amendment
  residue; left for ADR-007a's pass.
- **F5, named citations: handled.** The 92 citations by amendment name outside
  ADR-004 (code 35, tests 19, tasks 28, adr-summary 6, other ADRs 4) are covered
  by the _Citations by amendment name_ table at the end of ADR-004. They are
  double hops to be fixed whenever their text is edited; none was changed here.
- **F6, observation.** §1a is 262 lines, of which about 250 are code listings of
  `DiagnosticMode`, `ShadyCoordinatorLike` and the DTOs, which also exist in
  `diagnostics/base.py` and `coordinator_like.py`. Shortening it to signatures
  would be a content decision beyond this task; not done.

#### 4. Collapse result (ADR-004)

| Check | Result |
| -- | -- |
| Size | 1354 to 1090 lines (264 fewer, 19 %); ADR-004 is still the largest ADR (next: ADR-007a, 710) |
| Amendment framing | none left in the main text; the header carries one line saying history is in git and the task files. The seven blocks, the 60-line history header, the 14 inline dated notes and the 25 mentions of "tick" are gone (the trigger is now "slot trigger", defined once in §2i) |
| Headings | §2c removed (listed in `## Redirects`); §2d to §2i kept as plain sections; no other number changed |
| Semantics checklist | walked mechanically against the new text: every "keep" and "merge" row has its anchor phrases present; every superseded or trimmed item is absent (clear button, `data_generator`, service text, private attribute names, rounding and size formulas, Plotly symbol names in prose). Two non-findings: `_follow_latest_diagnostic_slot` matches only inside the public method `set_follow_latest_diagnostic_slot`, and the §2 example block still shows the emitted marker (symbols and sizes), as it is the contract dashboard authors copy |
| In-text references | every `§n` inside ADR-004 has a heading; the only `§2c` mentions left are the ones explaining the redirect |
| Resolver | `python utils/adr_refs.py --adr 004`: 511 references, 509 direct, 2 double hops, 0 unresolved. The two double hops quote §2c as it was (a finished task, and a test docstring: audit trail and code, both left alone by rule) |
| Find/replace | `--rewrite --adr 004 --ext md` finds nothing to rewrite: after a collapse with stable numbers, the one redirect (§2c) has no reference in living Markdown |
| Other files | `adr/INDEX.md`: the ADR-004 title cell lost its amendment history; `tasks/adr-summary.md` unchanged (nothing it describes moved; its four citations by amendment name are covered by the lookup table); `utils/adr_refs.py`, ADR-000 §10 and the mypy hook argument added |
| Formatting and lint | `mdformat --check` clean on every edited Markdown file; `ruff format`, `ruff check` and `mypy --strict` clean on `utils/adr_refs.py`; resolver exercised on a fixture (plain and cross-ADR redirects rewritten; ranges, mixed targets and multi-target redirects listed as manual; finished task untouched) |

#### 5. Split evaluation (GATE)

**Question.** After the collapse, does a two-way split make more sense than the
three-way proposal, or than no split? **Method.** Everything below is measured
on the collapsed text (`evalsplit` run over ADR-004 and the repo; throwaway
script). The three parts are the task's: _a_ = mode select and `DiagnosticMode`
interface (§1, §1a, §4), _b_ = series sensors, chart shape and the pool cache
(§2, §2b, §2d, §2e, §2h, §3), _c_ = diagnosed slot, following, pinning and the
slot trigger (§2a, §2f, §2g, §2i). §5 (module map) and the Consequences bullets
are assigned by what each paragraph or bullet is about. "Cut X" means: new
ADR-004a takes that part and ADR-004 keeps its number and everything else.

| Option | Lines after | In-text references crossing the cut (must be qualified) | Outside section-hits that move | Of those, reachable by find/replace in living Markdown | Double hops left for good (`.py`, finished tasks, split §5) |
| -- | -- | -- | -- | -- | -- |
| No split | 1090 | 0 | 0 | 0 | 0 |
| **Cut A: interface out** (§1, §1a, §4 to 004a; ADR-004 keeps §2 to §3 and all of §5) | 751 + 358 | **27** | **80** | 33 | **47** (`.py` 40, finished tasks 7) |
| Cut B: diagnosed slot out (§2a, §2f, §2g, §2i) | 864 + 245 | 46 | 125 | 36 | 89 |
| Cut C: series out (§2, §2b, §2d, §2e, §2h, §3) | 729 + 380 | 47 | 156 | 58 | 98 |
| Three-way (umbrella, a, b, c; §5 split in three) | 84 + 404 + 404 + 254 | 60 | 508 | 127 | 381 (`.py` 249, finished tasks 97, §5 in living Markdown 35) |

**What the numbers say**

- **The coupling sits between series and diagnosed slot.** Of the 60 in-text
  cross-references between the three parts, 33 run between _b_ and _c_ (14
  between _a_ and _b_, 13 between _a_ and _c_). The next planned change agrees:
  `TASK-0045b` edits §2, §2a, §2g and §3 in a single pass, that is series, pool
  and diagnosed slot together. Any cut that separates _b_ from _c_ (the
  three-way, cut B, cut C) pays for the tightest coupling in the ADR.
- **The mode interface is the loosest part.** It describes how a mode plugs in;
  it is stable, and the later tasks mostly touch its wording. Cutting it out
  crosses 27 references, the fewest of any cut.
- **§5 is one map and should stay whole.** It lists every file of the feature,
  and with 145 outside citations (the most cited section) it cannot be rewritten
  generically once split between several ADRs: a reference to "§5" would stay
  ambiguous for ever. Under cut A it stays in ADR-004 and none of its citations
  change.
- **Churn.** Cut A moves 80 outside citations (16 %), the three-way moves all
  508\. Since this task cannot rewrite `.py` and finished tasks, every moved
  citation there is a permanent double hop: 47 under cut A against 381 under the
  three-way.
- **Size.** Cut A leaves 751 + 358 lines, about the size of ADR-007a (710) and
  ADR-015 (626), the next largest. The three-way gives smaller parts (254 to
  404\) but needs an 84-line umbrella whose only job is the redirect table. Of
  the 358 lines in 004a, about 250 are the interface code listing (F6), so a
  later shortening to signatures would touch only that file.
- **Against any split.** The layering problem you named is solved by the
  collapse alone; a split is size hygiene. 1090 lines is still 1.5 times the
  next-largest ADR, and a reader after "how does a mode plug in" wades through
  chart shape and slot semantics. Cut A costs: 27 qualified in-text references,
  33 Markdown citations rewritten mechanically (by the tool), 47 permanent
  double hops, one new Draft ADR to confirm, and four rows in the `## Redirects`
  table (§1, §1a, §4, plus §2c).

**Recommendation.** If ADR-004 is split at all, use the **two-way cut A** rather
than the three-way: new Draft ADR-004a "Diagnostic mode select and the
`DiagnosticMode` interface" takes §1, §1a and §4 with the Consequences bullets
about modes (default off, 4x fitting, select plus base class, zero-mocking tier,
the coordinator Protocol, a mode's own coordinator reference, cadences); ADR-004
keeps its number, §2 to §3, §5 and the collapse's tables. It keeps the old
section numbers, so the move is a mechanical `ADR-004 §1` to `ADR-004a §1`
rewrite. The original plan for §3 and §4 beside the cache ADR falls away: §3
stays with the series it feeds, §4 goes with the interface it describes
(`extra_fit()`), and no other ADR is touched. No split is also defensible; the
three-way is the weakest option on every measure except part size.

#### 6. Decisions requested at this gate

| ID | Decision | Default |
| -- | -- | -- |
| G1 | Split ADR-004: cut A (recommended), no split, or the original three-way | cut A |
| G2 | May the find/replace also rewrite references in `.py` comments and docstrings (comment text only, no code change)? It would remove the 40 permanent double hops of cut A in the files `TASK-0045a` edits anyway, but makes this a task that touches `.py` | no: `.py` stays untouched, fixed when edited |

After your answer I finish ADR-004 (cut A: move §1, §1a, §4 and their bullets,
add the redirect rows, run the find/replace and the resolver, update
`adr/INDEX.md`; or nothing more for "no split"), and only then start ADR-007a's
mini-gate.
