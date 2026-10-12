# Task: Apply the GLOSSARY.md Language to the ADRs, the Code and the Tests (and the Semantics It Implies)

- **Status:** superseded (see 2026-10-11 refinement log; slug not reused) — kept
  as the decision record of the grill; implementation lives in the split tasks
  below
- **Related ADRs:** \[ADR-002 §1 + §3, ADR-004 (§2, §2a, §2g, §2i, §3), ADR-005
  §2, ADR-006 (§1a), ADR-007a (§1, §4, §6), ADR-008 §2, ADR-013\]
- **Dependencies:** \[TASK-0043-wire-cache-trim-into-recalibration,
  TASK-0044-local-day-training-window,
  TASK-0041-patch-1-intraday-window-ends-at-last-complete-slot\]

> **Status of the grill.** Two `grill-with-docs` sessions: 2026-10-10 produced
> `GLOSSARY.md`; **2026-10-11 settled every open question of this task** (see
> _Decisions from the grill of 2026-10-11_ — inputs, do not re-ask). On
> 2026-10-11 the human accepted the decisions and the split (Gate 2 proposal
> executed, Phase 6 Scenario A): this task is **superseded, slug not reused**,
> and is split into `TASK-0045a-wording-alignment`,
> `TASK-0045b-diagnostics-reference-and-pool`,
> `TASK-0045d-scheduled-recalibration-at-0400`,
> `TASK-0045c-training-window-and-trim-alignment`, plus the separate text-only
> `TASK-0046-adr-hygiene-collapse-and-split`. The new tasks copy the decisions
> they need and are `review` until the human approves them. `TASK-0043` /
> `TASK-0044` are accepted (`done`, G1). Nothing in code or ADRs has been
> changed yet; `GLOSSARY.md` has been updated.

## Goal

Make the repository speak the language of `GLOSSARY.md`: ADR text, code
identifiers, docstrings, comments, test names and user-facing strings. The human
warned that **the terminology actually used in the repo differs from the
glossary** — the _Terminology mapping_ below is the measured starting point.
Where the glossary also fixes **semantics** that the code does not currently
have (the _Decided semantics_ and _Known deviations_ below), align the code with
them.

`GLOSSARY.md` must stay devoid of implementation details; implementation lives
in the ADRs and in this task. **ADR edits follow the lean-ADR policy (G14):**
decisions are integrated into the main text, no new amendment blocks.

## Decided semantics (human, grill 2026-10-10, revised 2026-10-11 — inputs, do not re-ask)

1. A **slot** is five minutes, always labelled and entered in the **local**
   timezone. **Current slot** (the slot now falls in, unfinished) and **last
   completed slot** are different slots, both local.
1. **Followed slot** = what following determines: always the last completed slot
   (the forecast sensors and the intraday correction always work from it; the
   diagnostics do so while following). **Diagnosed slot** = the followed slot
   while following, the **pinned slot** while pinned. The **reference
   timestamp** is the followed slot (forecast sensors) / the diagnosed slot
   (diagnostics). _(Revised 2026-10-11: "analysed slot" is retired, G5.)_
1. Every **day** is exactly 24 hours; its start is always 24 hours before its
   end, regardless of DST. The daylight-saving setting is used **only for the
   reference day**: the day ending at the local midnight that closes the local
   date of the reference timestamp (confirmed 2026-10-11, G2). Every earlier day
   lies exactly 24 hours before the next (so around a clock change days start an
   hour off local midnight, and there are no 23/25-hour days, no `NaN` rows, no
   unused slots).
1. The **training window** is the configured number of days immediately
   **before** the reference day; the reference day itself is **not** part of the
   pool. The **intraday window** is a different thing (G5).
1. Diagnostics sample by timestamp: the sample for day _i_ is the diagnosed slot
   minus _i_ × 24 h (_i_ = 1 … window length); neighbor slots are the diagnosed
   slot ± _k_ × 5 min as plain timestamps (23:55's neighbor is 00:00 of the next
   day). The integer slot-of-day does not matter "as long as the timestamp is
   equivalent" (human's words).
1. "Local timezone" is how a slot is labelled and entered. The **fitted model's
   slot index stays the UTC-clock slot** (`index % 288`), decided in
   `TASK-0044`; forward fill and every prediction path keep that meaning.
1. Earlier decisions still standing: neighbor smoothing reads an extended window
   (`smoothing_radius` slots beyond each end of the window; `trim` takes the
   same radius) — `TASK-0044`, ADR-008 §2 / ADR-007a §1 (now to be integrated
   into the main text, G14).

## Decisions from the grill of 2026-10-11 (human — inputs, do not re-ask)

Format: **G<n>** (the grill question it settles; old open question in brackets).
Wording is the human's decision unless marked _(Lead reading)_.

**G1 (Q1) — TASK-0043 / TASK-0044.** Accept `TASK-0043` as `done`. Accept
`TASK-0044` as `done` with a note "superseded in part by TASK-0045c": its
UTC-clock slot index and smoothing-radius window extension stand; its
local-midnight 23/25-hour days are replaced (G2). Delete nothing. _(Q1 was not
answered explicitly in the rounds; the human accepted it with "Accepted." on
2026-10-11, and the statuses were flipped the same day.)_

**G2 (Q2, Q9) — Reference day.** Unchanged glossary rule: the reference day is
the 24 hours ending at the **local closing midnight after the followed/diagnosed
slot**; days before it are counted back in exact 24-hour steps. No special rule
for DST dates. _Measured consequence (Probe C):_ on a 25-hour date the first 12
slots (00:00–00:55 local; 6 slots at Lord Howe) lie **before** their own
reference day (it starts at 01:00); see G10.

**G3 (Q7) — Scheduled recalibration at 04:00 local, daily** (replaces 00:01),
identical on DST and non-DST dates. Reason: safely after every clock change; the
followed slot (03:55) is always _today_, so the reference day is today and the
training window lies fully in the past (the closing-midnight anchor would
otherwise make the 00:01 run on the fall-back date — 25 Oct 2026 — read an hour
that has not happened; Probe C). The old "let the recorder settle 23:55" worry
disappears. The energy reset at 00:00 and the slot trigger are independent and
unchanged. `_handle_midnight` is renamed; the "local midnight" wording of
ADR-002 §1 and the "00:01" wording in ADR-006 (l.169), ADR-007a (l.144) and
ADR-008 (l.243) are reworded in place.

**G4 (Q8, O1) — One reference for every trigger.** The recalibration reference
is the **followed slot** for the timer, the button and the startup safety net.
(The Lead's earlier recommendation "current slot at the trigger" is dropped.)
Consequence: a button/startup recalibration between 00:00 and 00:05 (and in the
first hour of a 25-hour date) trains a window one day short until the next 04:00
run; it never reads the future. ADR-002 §1's "complete days up to and including
yesterday" becomes "the training window before the reference day". _(Q8 not
answered explicitly; treated as accepted.)_

**G5 (Q3, Q4, Q5, O2, O4) — Terms.** **Followed slot** replaces "analysed slot".
**Following** is the diagnostics' mode (vs pinned). **Training window** (days)
and **Intraday window** (slots, ending at the followed slot) are the only
windows; "rolling window" and an unqualified "window" are `_Avoid_` for both.
Config keys `window_days` / `window_slots` stay. The "analysed slot" of the
forecast sensors has **no code counterpart except the end of the intraday
window** (ADR-006 §1a, which today ends at `now` and includes the in-progress
slot): the glossary therefore settles `TASK-0041-patch-1` / D2-b — the intraday
window ends at the followed slot. That task stays its own task, ordered before
0045a/b. _(Lead reading: the human only commented on naming in round 2; no
objection raised since — verify at Gate 2.)_

**G6 (Q4, O4) — Rename scope.** "auto-track\*" → "following" / "followed slot"
and "last complete slot" → "last completed slot", everywhere (ADR text, code,
comments, test names). Measured: "auto-track" is prose plus three test class
names (`TestGetPinnedSlotPoolNoPinAutoTracksToday`,
`TestDiagnosedSlotAutoTracking`, `TestAutoTrackingPinnedPoolSurvivesTheTrim`);
production identifiers already say "follow" — no entity ID, translation, README
or persisted key is affected. Task file names (e.g. `…-last-complete-slot.md`)
and past refinement-log rows stay as history. Pure wording edits in ADRs need no
amendment entry (G14).

**G7 — Glossary state (done).** `GLOSSARY.md` now holds: Followed slot,
Following, Diagnosed slot, Reference timestamp, Training window, Intraday
window, Pool, Recalibration, Recompute (plus the unchanged Slot, Current slot,
Last completed slot, Pinned slot, Day, Reference day, Neighbor slot). Q14: no
`_Avoid_` for Recalibration/Recompute; `async_refit` / `_refit_sync` are **not**
renamed.

**G8 (Q6, O5) — `DiagnosedSlot.slot_of_day`** stays as a local display value
(ADR-015 CSV metadata `"slot_of_day"`); it no longer feeds any pool computation;
not in the glossary. _(Q6 not answered explicitly; treated as accepted.)_

**G9 (Q10) — Horizon.** ADR-002 §3's calendar horizon (remainder of today + all
of tomorrow, as far as the raw forecast reaches) **stays**. Record the
invariant: the horizon always reaches at least the next scheduled recalibration.
Recompute (ADR-002 §2) runs after each baseline update (3–5 per day; the raw
solar and weather forecasts cover two days) and applies the current model.

**G10 (Q11) — Start of a 25-hour date.** For the 12 slots 00:00–00:55 on the
fall-back date the followed slot lies inside training-window day 1. Diagnostics
for those slots use the timestamp rule (`followed − i × 24 h`, _i_ = 1…N): the
slot never contains itself, one day further back, no change to any definition.
One sentence in ADR-004 §2 (main text, not an amendment); not in the glossary.
The _forecasts_ for those slots come from the previous day's recalibration like
any night slot (≈ 0). _(Lead reading of the human's explanatory reply; tell me
if the 12 diagnostics slots should behave differently.)_

**G11 (Q12) — Night-hours difference.** For 00:00–04:00 the diagnostics anchor
on the followed slot, whereas the model in use was fitted at the previous 04:00
(its window ends one day earlier). Accepted; one sentence in ADR-004 §2.

**G12 (Q13, O3) — Trim retention.** Floor = **min(training window start, pinned
pool window start) − smoothing radius**. No extra day for the following pool (at
00:00–04:00 its window is anchored one day _later_ than the model's, so it needs
no older data; from 04:00 both share the reference day). Trim stays at the
scheduled recalibration only (as `TASK-0043` wires it).

**G13 (Q15) — Acceptance criteria** — see _Acceptance Criteria_ (confirmed).

**G14 (Q16, O6) — Lean ADRs.** _"Keep the ADRs lean. I do not like to be
overflooded by the 5th amendment changing the 3rd aspect of the 2nd amendment.
If an ADR is too large, evaluate whether it can be collapsed (integrating the
amendments into the main text) and/or split."_ Consequences for this task:

- Decisions are **integrated into the main text** of the affected section; **no
  new `Amendment` blocks**, no new ADR. History lives in git and in this task
  (this overrides the Phase 0 amendment-block convention for this task's ADR
  edits).
- **Section numbers stay stable** (≈ 125 places outside ADR-004 cite §2c–§2i;
  ADR-002 §1 has 145 references): when text is collapsed or an ADR is split,
  either keep the heading numbers or ship an old-§ → new-§ redirect table and
  rewrite the references in the same task.
- Touched ADRs that carry stacked amendments or are very large get the
  collapse/split evaluation below.

## ADR hygiene: collapse / split evaluation (G14)

Measured 2026-10-11 (lines / amendment blocks / `###` sections). Recommendation
is text-only work; the human decides at Gate 2.

| ADR | Size | Amendments | Recommendation |
| -- | -- | -- | -- |
| ADR-002 | 312 / 0 / 6 | none | Edit in place (§1 timer 04:00, training window, followed-slot reference; §3 horizon invariant). 145 refs to §1 — keep numbering. |
| ADR-004 | 1354 / 7 / 15 | §2c–§2i, with supersession chains (2d supersedes 2c; 2f supersedes the service of §2a; 2g supersedes 2f's clear button; 2i reinterprets the tick) | **Collapse** all seven into the main text of §2/§2a/§2b (keeping the stable numbers as headings, dropping "Amendment" framing and superseded text). **Split candidate**, three parts: (1) mode select + `DiagnosticMode` interface (§1, §1a, §5); (2) scatter-series sensors and chart entry shape (§2, §2b–§2e, §2h); (3) **diagnosed-slot selection, following and pinning** (§2a, §2f, §2g, §2i) — the part this task changes. §3/§4 (historical pool caching, extra fitting cost) belong beside the cache ADR. ≈ 125 outside references (code 38, tests 26, tasks ≈ 33, other ADRs 14, adr-summary 14) need the redirect table. |
| ADR-007a | 710 / 5 / 6 | TASK-0043 (§1), TASK-0034, TASK-0037-patch-5, TASK-0042, TASK-0037 | **Collapse** (the §1 amendment is rewritten by this task anyway). Evaluate splitting the threading contract (TASK-0042) from storage design. |
| ADR-008 | 286 / 2 / 3 | TASK-0037 batching edge; TASK-0044 window (superseded by G2) | **Collapse**; the TASK-0044 amendment is replaced by the new main text. No split needed. |
| ADR-006 | 444 / 1 / 7 | TASK-0041 slot trigger | **Collapse**; §1a text changes for the intraday window (end = followed slot). |
| ADR-005, ADR-013 | 220 / 147 | none | Wording only. |
| ADR-015 | 626 / 2 / 10 | two | Out of scope; leave (revisit when next touched). |

**Recommended order:** run the collapse/split as a **separate text-only task
before 0045a**, so the wording and semantics edits land in lean text instead of
becoming further amendments. Start with ADR-004 (largest, most stacked, and the
home of the followed/diagnosed-slot text).

## Terminology mapping (glossary ← what the repo says today)

Counts are regex matches (ADR / src / tests / tasks), measured 2026-10-10; a
starting point, not an exhaustive inventory. Actions reflect the grill of
2026-10-11.

| Glossary term | Repo today | Counts | Action |
| -- | -- | -- | -- |
| Current slot | "current slot" / "current-slot corrected forecast" = the slot now falls in (ADR-005 §2, `coordinator.py`, `sensor.py`) | 1 / 3 / 7 / 3 | Consistent; keep. Check no place uses it for the _last completed_ slot. |
| Last completed slot | "last complete slot" (ADR-004 §2 etc., ADR-007a:197, ADR-013:14, `coordinator_like.py:127`, `aggregation.py:215`, tests) | 7 / 2 / 5 / 9 | Rename (G6); `_Avoid_`: "last complete slot". |
| Following | "auto-track(ing/ed)" (prose + 3 test class names; production identifiers already say "follow") | 41 / 13 / 9 / 27 | Rename (G6); `_Avoid_`: "auto-tracking". |
| Followed slot | `_advance_followed_diagnostic_slot`, ADR-006 "followed-slot advance", "analysed slot" (0 occurrences) | — | New glossary term (G5). The forecast sensors have no slot-analysis state; its only code counterpart is the end of the intraday window (D8). |
| Pinned slot | "pinned slot", `pin_diagnostic_slot`, plus `pin_reference` / `pinned_reference` (a **date**, not a slot) | 55 / 34 / 90 / 144 and 19 / 31 / 50 / 34 | Keep "pinned slot"; the cache-level `pin_reference(date)` is a different, date-based concept (D3). |
| Diagnosed slot | "diagnosed slot", `DiagnosedSlot`, `diagnosed_slot()` | 59 / 73 / 51 / 66 | Keep; matches the glossary. |
| Reference timestamp / day | "reference" is a bare parameter name (`Cache.get_regression_pools(reference=)`, `trim(reference=)`, `get_pinned_slot_pool(reference=)`), plus `pinned_reference` (date) | "reference day/timestamp": 0 | Introduce the terms; decide which parameters become a reference timestamp (D1, D2, G4). |
| Training window | "window_days", "training window", "rolling window" | window_days 53 / 81 / 309 / 97; training window 16 / 3 / 15 / 35; rolling window 31 / 4 / 3 / 7 | Bare "window" / "rolling window" → "training window" (days) **or** "intraday window" (slots, mostly ADR-006's `window_slots`) — decide per occurrence (G5). Config keys unchanged. |
| Intraday window | ADR-006 §1a "rolling window" of `window_slots` slots | (part of the 31 "rolling window" hits) | New term (G5); must end at the followed slot (D8). |
| Pool | "pool" | — | Keep; now "samples on each day of the training window + neighbors". |
| Neighbor slot | "neighbor slot" / neighbor offsets | 7 / 2 / 4 / 5 | Keep; fix the diagnostics' wraparound (D4). |
| Recalibration / Recompute | ADR-002 title "Recalibration vs. Forecast Recompute"; code `async_refit`, `_refit_sync`, `_recompute_string` | — | New glossary terms (G7); **no** rename of `refit` identifiers. |
| (not a glossary term) | `slot_of_day` (integer, local, elapsed since local midnight) | 3 / 32 / 70 / 15 | Stays as CSV/display value only (G8). |

## Known deviations of the code/ADRs from the decided semantics (evidence)

D1. **Following anchors on `now`, not on the diagnosed slot.** Probe A
(appendix), Europe/Berlin, 00:03 local on 20 Jun: the diagnosed slot is Fri 19
Jun 23:55, but `get_pinned_slot_pool` (auto-tracking) anchors on today, and
returns `[Thu 18 Jun 23:55, Fri 19 Jun 23:55, None]` — off by a day, with a
future sample. `compare_regressions._gather_pool` passes `reference=<now>`
(`diagnostics/compare_regressions.py`, around line 523/542).

D2. **The pool includes the reference day today.** `get_pinned_slot_pool`'s
window is "reference day and the `window_days − 1` days before it", so the
diagnosed slot's own sample is the newest point, and nothing in the diagnostics'
fit holds it out. Decision 4 says it is not part of the pool.

D3. **Pinned pool places days by the oldest day's local midnight.** Index =
`oldest-day local midnight + day_offset × 288 + slot_of_day` (`cache.py`,
`get_pinned_slot_pool`, ~lines 1130-1200). Across a DST change the pool is one
hour off the diagnosed timestamp. Probe B (appendix): Berlin, pinned Mon 30 Mar
(after the 29 Mar spring-forward), local slot 120 (10:00): the diagnostics' pool
holds `03-28 10:00, 03-29 11:00, 03-30 11:00`; the model's pool for the same
instant holds `03-28 09:00, 03-29 10:00, 03-30 10:00`. In a window without a DST
change (June) the two are identical. Pre-existing (TASK-0039 / TASK-0015b);
affects ~`window_days` days after each clock change. The cache-level pin is also
a **date** (`pin_reference(date)`) — decision 3 needs a timestamp.

D4. **Neighbor wraparound.** `compare_regressions._gather_pool` computes
`offset_slot = (diagnosed.slot_of_day + offset) % SLOTS_PER_DAY` (line ~540), so
23:55's neighbor reads slot 0 of the **same** local day, not 00:00 of the next.

D5. **`TASK-0044` (in `review`) defines days as local midnight-to-midnight**
(`Cache._training_day_starts`, `_training_window_start_index`,
`get_regression_pools`; ADR-008 §2 Amendment 2026-10-10 "Decided by: human";
ADR-007a §1 amendment): 23/25-hour DST days, `NaN` rows for UTC slots a short
day lacks, first 288 slots of a long day. Decision 3 (every day exactly 24
hours, anchored once at the reference day) **supersedes** it; with 24-hour
strides every day start is congruent modulo 288, so with `D_i = R − i × 288`
(`R` = the reference day's start) the sample for UTC slot _s_ on day _i_ is
`D_i + ((s − D_i) mod 288)` and `(s − D_i) mod 288` is the same for every day:
all DST special-casing disappears.

D6. **Trim floors.** `Cache.trim(reference, smoothing_radius)` keeps the
training window start minus the radius, plus the pin floor
`min(…, pinned_reference − window_days)`. Target (G12): the older of the
training window start and the pinned pool's window start, minus the radius; no
extra day for the following pool (the 04:00 timer, G3, makes training and
following share the reference day all day).

D7. **"Analysed slot" has no code counterpart** — retired in favor of **followed
slot** (G5); its only code counterpart is D8.

D8. **The intraday window ends at `now`, not at the followed slot.** ADR-006 §1a
/ `coordinator.py`: the window includes the in-progress slot, whose actual yield
is always `None` (≈ 4 % downward bias). Same as the pending, human-gated
`TASK-0041-patch-1` (D2-b); settled by G5.

D9. **The scheduled recalibration fires at 00:01 local** (ADR-002 §1,
`ShadyCoordinator._handle_midnight`). Under the closing-midnight reference day
(G2) this reads an hour of the future on the fall-back date (Probe C: 12
slots/year, 6 at Lord Howe). Target: 04:00 local daily (G3).

D10. **ADR-002 §1 wording** ("complete days up to and including yesterday",
"midnight") and the "00:01" prose in ADR-006, ADR-007a, ADR-008 no longer match
G3/G4 — reword in place (G14).

## Open questions

**None — all settled in the grill of 2026-10-11.** Mapping of the former
questions: O1 (training anchor) → G4; O2 (analysed slot) → G5, D7, D8; O3 (trim)
→ G12; O4 (rename scope, `_Avoid_`) → G5, G6; O5 (`slot_of_day`) → G8; O6 (ADR)
→ G14 and the ADR-hygiene evaluation. Items marked _(Lead reading)_ / _(treated
as accepted)_ in the decisions (G1, G4, G5, G8, G10) were re-confirmed by the
human with "Accepted." on 2026-10-11.

## Acceptance Criteria (confirmed, G13)

- Given the glossary, when the repo is searched for each `_Avoid_` term, then
  there is no occurrence except in quoted history (git, past refinement-log
  rows, task file names).
- Given a diagnosed slot (following or pinned) and any DST situation in the
  window, then every sample of its pool and every neighbor is the diagnosed slot
  ± whole multiples of 24 h / 5 min, and the pool's timestamps equal the model's
  pool timestamps for the same instant (Probe B repeated with the model's
  reference on the same date: identical). The only exception is the 12 slots at
  the start of a 25-hour date (G10), where the pool uses `followed − i × 24 h`.
- Given following at 00:03 local, then the reference day is yesterday and the
  pool holds the `window_days` days before it (Probe A repeated: no `None`
  sample, no sample from today).
- Given the diagnosed slot is 23:55, then its neighbor at +1 is 00:00 of the
  next day (not slot 0 of the same day).
- Given the scheduled recalibration (fake clock) on every date including 29 Mar
  2026 and 25 Oct 2026, then it fires at 04:00 local, its training window ends
  at the start of the reference day and lies fully in the past, and it is
  trimmed without a re-fetch, in UTC and non-UTC timezones.
- Given a button or startup recalibration, then its reference is the followed
  slot and it never reads the future.
- Given any recompute, then the horizon reaches at least the next scheduled
  recalibration (G9).
- Given the intraday correction, then its window ends at the followed slot
  (`TASK-0041-patch-1` / D2-b).
- Given the timezone is UTC and no DST, then fitted models are unchanged (all
  pre-existing tests pass unless they pinned a superseded definition; restate
  those, do not delete them).

## Split and order (executed 2026-10-11; new tasks await Gate 2 approval)

Proposal for **Gate 2** — not executed yet (numbering per Phase 6: a/b/c/d).

- **ADR hygiene (separate, text-only; number at Gate 2):** collapse/split per
  the evaluation above, with the redirect table. Runs **first** so that all
  later ADR edits land in lean text.
- **TASK-0041-patch-1 (existing, `todo`, gated):** intraday window ends at the
  followed slot (D8, G5). Ordered before 0045a/b.
- **0045a — wording only:** renames and glossary alignment (G5, G6) in ADRs,
  docstrings, comments, test names; no behavior change.
- **0045b — diagnostics semantics:** D1–D4 (reference = diagnosed slot, pool
  excludes the reference day, timestamp arithmetic, neighbor fix) plus the G10
  rule and the G11 sentence in ADR-004 §2.
- **0045d — scheduled recalibration timer (new, small):** 04:00 local daily,
  followed-slot reference for every trigger (G3, G4, D9, D10), the G9 horizon
  invariant in ADR-002 §3, "00:01" rewording. **Must land before or together
  with 0045c**: under the closing-midnight reference day the 00:01 run would
  read the future on 25 Oct 2026. (Until 0045c is released, the current
  `TASK-0044` code handles the 25-hour day at 00:01.)
- **0045c — training/trim alignment:** D5–D6 and G12 (24-hour days anchored at
  the reference day, one anchor, trim floor), superseding `TASK-0044`'s local
  midnight-to-midnight days; ADR-007a §1/§6 and ADR-008 §2 rewritten in the main
  text.

Suggested order: ADR hygiene → TASK-0041-patch-1 → 0045a → 0045b → 0045d →
0045c. 0045a/b can run in either order; 0045d/c are strictly sequential.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `get_pinned_slot_pool` (overloads and
  implementation), `get_regression_pools`, `_training_day_starts`,
  `_training_window_start_index`, `trim`, `pin_reference` / `clear_reference` /
  `pinned_reference`
- `custom_components/shady/coordinator.py` — `DiagnosedSlot`,
  `diagnosed_slot()`, `pin_diagnostic_slot`, `_diagnostic_slot_index`,
  `_refit_sync`, `_trim_cache`
- `custom_components/shady/coordinator_like.py` (docstring, protocol),
  `aggregation.py` (docstring), `diagnostics/compare_regressions.py`
  (`_gather_pool`, `_export_window_start_date`), `diagnostics/base.py`
- `tests/` — `test_cache_regression_pools.py`, `test_cache_pinned_slot_pool.py`,
  `test_cache_core.py`, `test_coordinator_recalibration_trim.py`, diagnostics
  and coordinator tests (many names contain the terms above)
- `adr/004`, `adr/005`, `adr/007a`, `adr/008`, `adr/013`, `tasks/adr-summary.md`
- `custom_components/shady/coordinator.py` — also the scheduled-recalibration
  registration and `_handle_midnight` (rename; 04:00 local) and the intraday
  window end (via `TASK-0041-patch-1`)
- `GLOSSARY.md` (already updated), `adr/002`, `adr/006` (in addition to the ADR
  list above)

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected)
- `GLOSSARY.md` still devoid of implementation details; every new term the grill
  resolves is added to it **at that moment**
- ADR edits follow G14: integrated into the main text, no new `Amendment`
  blocks, section numbers stable (or a redirect table plus rewritten
  references); `tasks/adr-summary.md` updated

## Consumed Interfaces

- `Cache.get_regression_pools`, `Cache.get_pinned_slot_pool`,
  `Cache._training_day_starts`, `Cache._training_window_start_index`,
  `Cache.trim(reference, smoothing_radius)`, `Cache.pin_reference`,
  `Cache.clear_reference`, `Cache.pinned_reference` from
  `custom_components/shady/cache.py` (→ tasks: TASK-0043, TASK-0044, TASK-0039)
- `ShadyCoordinator.diagnosed_slot`, `DiagnosedSlot`, `pin_diagnostic_slot`,
  `_refit_sync`, `_trim_cache` from `custom_components/shady/coordinator.py` (→
  tasks: TASK-0043, TASK-0015b / TASK-0039)
- Intraday window end in `custom_components/shady/coordinator.py` (→ task:
  TASK-0041-patch-1-intraday-window-ends-at-last-complete-slot)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->

## Handover: repository state and working notes

- State after the split of 2026-10-11 (working copy of the uploaded
  `shady__8_.zip`): only `GLOSSARY.md` and task/INDEX files were touched; no
  code, no ADR. `TASK-0043` and `TASK-0044` are `done` (G1, accepted by the
  human). This task is `superseded`; its children `TASK-0046`,
  `TASK-0045a/b/d/c` are `review` (awaiting Gate 2 approval).
- Previous commits: `2d6c01c` (TASK-0044 smoothing extension), `6253d46`
  (TASK-0044), `469f279` / `c841e6a` (TASK-0043).
- Suite at the 2026-10-10 handover: `pytest` 996 passed;
  `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` clean; coverage `coordinator.py` 13 and `cache.py` 12
  uncovered lines (pre-existing). Environment: `uv sync`, then `uv run <tool>`.
  (The 2026-10-11 session did not run the suite; its probes ran with the system
  `python3` + numpy, `PYTHONPATH=.`.)
- Test harness worth reusing: `tests/test_coordinator_recalibration_trim.py`
  (`_make_setup(window_days, time_zone, smoothing_radius)` builds a real
  coordinator on the hand-written `homeassistant` stub, with a counting recorder
  spy; the fixture data is periodic per UTC clock slot, so pools must be
  identical across timezones) and `tests/test_cache_regression_pools.py`
  (zero-mocking `Cache` tests with an index-valued `fetch_fn`: the value **is**
  the absolute slot index, so any misplaced slot changes the array).
- Method that paid off: write the failing tests first, run them against the old
  code, then **mutation-test** the new behavior (apply a deliberate bug, assert
  the suite fails, restore from a saved copy). A mutation script once silently
  applied nothing — always assert the mutation changed the file.
- `mdformat` re-wraps Markdown: edit `.md` with whitespace-insensitive matching
  and run `mdformat <files>` then `--check`.
- The human's standing preferences: reason before changing, ask before widening
  scope, "local time for everything user-facing", the integer slot index is
  irrelevant if the timestamp is right, **lean ADRs (G14)**.

## Appendix: probes behind the findings (reproduce before relying on them)

Probes A and B run from the repo root with `PYTHONPATH=. uv run python <file>`;
`Cache` is loaded the way the cache tests do (`tests.support._load`).

Probe A — following at 00:03 local (finding D1):

```python
from datetime import datetime
from zoneinfo import ZoneInfo
from tests.support import _load

_load("regression/base.py", "shady.regression.base")
cm = _load("cache.py", "shady.cache")
tz = ZoneInfo("Europe/Berlin")


def fetch(sid, s, e):  # value == absolute index == the timestamp
    first = cm.Cache.index_for(s)
    n = round((e - s) / cm.SLOT_DURATION)
    return [float(first + i) for i in range(n)]


now = datetime(2026, 6, 20, 0, 3, tzinfo=tz)
c = cm.Cache(3, fetch, local_tz=tz, clock=lambda: now)  # auto-tracking: no pin
last_completed = cm.Cache.index_for(now) - 1
ts = cm.Cache.timestamp_for(last_completed).astimezone(tz)
slot_of_day = int((ts - datetime(ts.year, ts.month, ts.day, tzinfo=tz)) / cm.SLOT_DURATION)
pool = c.get_pinned_slot_pool(["s"], slot_of_day, on_invalid="raw", reference=now)["s"]
# measured: diagnosed Fri 19 Jun 23:55 (slot_of_day 287);
# pool -> [Thu 18 Jun 23:55, Fri 19 Jun 23:55, None]
```

Probe B — DST window, diagnostics vs model (finding D3): same loader and
`fetch`; `c = cm.Cache(3, fetch, local_tz=ZoneInfo("Europe/Berlin"))`,
`c.pin_reference(date(2026, 3, 30))`,
`diag = c.get_pinned_slot_pool(["s"], 120, on_invalid="raw")["s"]`; the model's
row is
`c.get_regression_pools(["s"], 0, reference=<2026-03-31 00:01 Berlin>)["s"][u]`
with `u = index_for(local midnight 30 Mar + 120 slots) % 288` (= 96). Measured
(local labels): diagnostics `03-28 10:00, 03-29 11:00, 03-30 11:00`; model
`03-28 09:00, 03-29 10:00, 03-30 10:00`. With `date(2026, 6, 19)` / reference
`2026-06-20 00:01` both give `06-17, 06-18, 06-19` at 10:00 (identical).

Probe C — reference-day anchoring across a year (findings G2, G3, D9). Pure
`zoneinfo`; for every slot of every local date it tests whether the slot lies
inside its own reference day (anchor "closing": 24 h ending at the local
midnight that closes the date; anchor "opening": 24 h starting at the midnight
that opens it) and whether the window start (`R`) lies after the slot (i.e. a
recalibration there would read the future). **Walk every slot of the date, not a
fixed 288** (a first version missed the 25th hour). Measured for 2026:

| Timezone | closing: slots outside own day / window in the future | opening: outside / future |
| -- | -- | -- |
| Europe/Berlin, America/New_York | 12 / 12 | 12 / 0 |
| Australia/Lord_Howe | 6 / 6 | 6 / 0 |
| UTC | 0 / 0 | 0 / 0 |

```python
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

UTC, STEP, DAY = timezone.utc, timedelta(minutes=5), timedelta(hours=24)


def lm(tz, d):
    return datetime(d.year, d.month, d.day, tzinfo=tz).astimezone(UTC)


def run(tzname, year):
    tz = ZoneInfo(tzname)
    res = {k: dict(not_in_refday=0, window_reaches_future=0) for k in ("closing", "opening")}
    d = datetime(year, 1, 1).date()
    while d.year == year:
        k = -1
        while True:  # every slot of this local date, including a 25th hour
            k += 1
            t = lm(tz, d) + k * STEP
            if t.astimezone(tz).date() != d:
                break
            anchors = {
                "closing": lm(tz, d + timedelta(days=1)) - DAY,
                "opening": lm(tz, d),
            }
            for key, R in anchors.items():
                if not (R <= t < R + DAY):
                    res[key]["not_in_refday"] += 1
                if R > t:
                    res[key]["window_reaches_future"] += 1
        d += timedelta(days=1)
    return res


print(run("Europe/Berlin", 2026))
```

Decision G2 keeps the **closing** anchor; G3 (04:00 timer) is what keeps the
scheduled recalibration out of the 12 affected slots, and G10 covers the
diagnostics for them.
