# Task: Apply the GLOSSARY.md Language to the ADRs, the Code and the Tests (and the Semantics It Implies)

- **Status:** todo
- **Related ADRs:** \[ADR-002 §1, ADR-004 (§2, §2g, §3), ADR-005 §2, ADR-007a
  (§1, §4, §6), ADR-008 §2, ADR-013\]
- **Dependencies:** \[TASK-0043-wire-cache-trim-into-recalibration,
  TASK-0044-local-day-training-window\]

> **Handover.** Written at the end of a `grill-with-docs` session on 2026-10-10
> whose only deliverable was `GLOSSARY.md` (repo root, committed). This task is
> meant to be started in a **new chat**. Start it with the `grill-with-docs`
> skill (the human asks for a grill session; skill at
> `skills/engineering/grill-with-docs/` of https://github.com/mattpocock/skills)
> to settle the _Open questions_ below, **before** planning or touching
> anything. `TASK-0043` and `TASK-0044` are both still `review` (the human has
> **not** accepted them) — ask first whether to accept, rework or fold them in,
> because this task supersedes parts of `TASK-0044`.

## Goal

Make the repository speak the language of `GLOSSARY.md`: ADR text, code
identifiers, docstrings, comments, test names and user-facing strings. The human
warned that **the terminology actually used in the repo differs from the
glossary** — the _Terminology mapping_ below is the measured starting point.
Where the glossary also fixes **semantics** that the code does not currently
have (the _Decided semantics_ and _Known deviations_ below), align the code with
them.

`GLOSSARY.md` must stay devoid of implementation details; implementation lives
in the ADRs (as amendments, following the project's own `adr/` convention and
the Phase 0 amendment format) and in this task.

## Decided semantics (human, grill 2026-10-10 — inputs, do not re-ask)

1. A **slot** is five minutes, always labelled and entered in the **local**
   timezone. **Current slot** (the slot now falls in, unfinished) and **last
   completed slot** are different slots, both local.
1. **Diagnosed slot** = the last completed slot while **following**, the
   **pinned slot** while pinned (the diagnostics). **Analysed slot** = the slot
   the always-following **forecast sensors** analyse (always the last completed
   slot). The **reference timestamp** is always the analysed / diagnosed slot.
1. Every **day** is exactly 24 hours; its start is always 24 hours before its
   end, regardless of DST. The daylight-saving setting is used **only for the
   reference day**: the day ending at the local midnight that closes the local
   date of the reference timestamp. Every earlier day lies exactly 24 hours
   before the next (so around a clock change days start an hour off local
   midnight, and there are no 23/25-hour days, no `NaN` rows, no unused slots).
1. The **window** is the configured number of days immediately **before** the
   reference day; the reference day itself is **not** part of the pool.
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
   same radius) — `TASK-0044`, ADR-008 §2 / ADR-007a §1 amendments.

## Terminology mapping (glossary ← what the repo says today)

Counts are regex matches (ADR / src / tests / tasks), measured 2026-10-10; a
starting point, not an exhaustive inventory.

| Glossary term | Repo today | Counts | Action |
| -- | -- | -- | -- |
| Current slot | "current slot" / "current-slot corrected forecast" = the slot now falls in (ADR-005 §2, `coordinator.py`, `sensor.py`) | 1 / 3 / 7 / 3 | Consistent; keep. Check no place uses it for the _last completed_ slot. |
| Last completed slot | "last complete slot" (ADR-004 §2 etc., ADR-007a:197, ADR-013:14, `coordinator_like.py:127`, `aggregation.py:215`, tests) | 7 / 2 / 5 / 9 | Rename; glossary lists "last complete slot" under `_Avoid_`. |
| Following | "auto-track(ing/ed)" | 41 / 13 / 9 / 27 | Rename; glossary lists "auto-tracking" under `_Avoid_`. Confirm scope (see O4). |
| Pinned slot | "pinned slot", `pin_diagnostic_slot`, plus `pin_reference` / `pinned_reference` (a **date**, not a slot) | 55 / 34 / 90 / 144 and 19 / 31 / 50 / 34 | Keep "pinned slot"; the cache-level `pin_reference(date)` is a different, date-based concept (see D3). |
| Diagnosed slot | "diagnosed slot", `DiagnosedSlot`, `diagnosed_slot()` | 59 / 73 / 51 / 66 | Keep; matches the glossary. |
| Analysed slot | **no occurrence anywhere**; the forecast sensors (`ShadyForecastSensor`, `ShadyFcSumSensor`, `ShadyFcDaySumSensor`, `ShadyFcRemainingTodaySensor`, ...) have no slot-analysis state | 0 / 0 / 0 / 0 | **Open (O2):** find out what it denotes before naming anything. |
| Reference timestamp / day | "reference" is a bare parameter name (`Cache.get_regression_pools(reference=)`, `trim(reference=)`, `get_pinned_slot_pool(reference=)`), plus `pinned_reference` (date) | "reference day/timestamp": 0 | Introduce the terms; decide which parameters become a reference timestamp (D1, D2). |
| Window / Pool | "window_days", "training window", "rolling window", "pool" | window_days 53 / 81 / 309 / 97; training window 16 / 3 / 15 / 35; rolling window 31 / 4 / 3 / 7 | Align with glossary "Window" (days **before** the reference day). Decide `_Avoid_` for "rolling window" with the human (O4). |
| Neighbor slot | "neighbor slot" / neighbor offsets | 7 / 2 / 4 / 5 | Keep; fix the diagnostics' wraparound (D5). |
| (not a glossary term) | `slot_of_day` (integer, local, elapsed since local midnight) | 3 / 32 / 70 / 15 | Decision 5 makes it unnecessary for pools; it may stay as a display value (O5). |

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
`min(…, pinned_reference − window_days)`. Under the new definitions three
readers need data: the training pool, the **following** diagnosed slot's pool
(for ~5 minutes after local midnight its reference day is still yesterday, i.e.
one day older than the training window — otherwise one extra day is re-fetched
every midnight), and the **pinned** pool. See O3.

D7. **Analysed slot has no code counterpart** (see mapping table, O2).

## Open questions — settle with the human first (grill, one round at a time)

O1. **What anchors _training_?** The glossary says the reference timestamp is
the analysed/diagnosed slot, but a recalibration is not tied to a diagnostics
slot. Under decision 4 (window excludes the reference day) the training
reference must lie **in today** at every trigger time for ADR-002 §1 ("complete
days up to and including yesterday", also for a mid-day button press) to hold:
the **current slot** at the trigger does (00:00 slot at 00:01, 14:35 slot at
14:37); the **last completed slot** does not (at 00:01 it is yesterday 23:55, so
the window would stop a day short). Recommended: training reference = current
slot at the trigger. Needs the human's confirmation and a glossary line for it.

O2. **What is the "analysed slot" in the code?** The human: "the
always-following forecast sensors". Find which sensors/attributes this means
(candidates: the `Shady*Sensor` forecast sensors in `sensor.py`; ADR-005 §2
speaks of "the current slot's corrected forecast"), then decide the mapping and
where a reference timestamp is used for them at all.

O3. **Trim retention.** Recommended: keep the oldest of {training window, the
following diagnosed slot's pool, the pinned pool}, each less the smoothing
radius (one extra day retained). Confirm.

O4. **Rename scope and ADR procedure.** Rename "auto-tracking" → "following" and
"last complete slot" → "last completed slot" everywhere (ADR text, code, test
names)? Are pure wording edits in ADRs allowed without an amendment entry? Also
decide `_Avoid_` for "rolling window" / "training window".

O5. **`DiagnosedSlot.slot_of_day`**: drop it, or keep as a local display value
(entity attributes may expose it — check ADR-004's attribute list)?

O6. **ADR.** The 24-hour-day / reference-day / pool-excludes-reference-day /
UTC-clock-slot semantics are hard to reverse, surprising and a real trade-off
(domain-modeling skill's three criteria) — propose one consolidated amendment
set (ADR-008 §2, ADR-007a §1 and §6, ADR-004 §2) superseding `TASK-0044`'s
amendment, in the project's amendment format (Reason / Decision / Decided by).

## Acceptance Criteria (draft; refine after the grill)

- Given the glossary, when the repo is searched for each `_Avoid_` term, then
  there is no occurrence except in quoted history (amendment text, git).
- Given a diagnosed slot (following or pinned) and any DST situation in the
  window, then every sample of its pool and every neighbor is the diagnosed slot
  ± whole multiples of 24 h / 5 min, and the pool's timestamps equal the model's
  pool timestamps for the same instant (Probe B repeated: identical).
- Given following at 00:03 local, then the reference day is yesterday and the
  pool holds the `window_days` days before it (Probe A repeated: no `None`
  sample, no sample from today).
- Given the diagnosed slot is 23:55, then its neighbor at +1 is 00:00 of the
  next day (not slot 0 of the same day).
- Given a recalibration at any time of day (decision per O1), then the trained
  window is the same, trimmed without a re-fetch, in UTC and non-UTC timezones,
  across both DST changes.
- Given the timezone is UTC and no DST, then fitted models are unchanged (all
  pre-existing tests pass unless they pinned a superseded definition; restate
  those, do not delete them).

## Suggested split (decide at Gate 2; numbering per Phase 6: a/b/c)

- **0045a — wording only:** renames and glossary alignment in ADRs, docstrings,
  comments, test names; no behavior change.
- **0045b — diagnostics semantics:** D1–D4 (reference = diagnosed slot, pool
  excludes the reference day, timestamp arithmetic, neighbor fix).
- **0045c — training/trim alignment:** D5–D6 and O1/O3 (24-hour days, one
  anchor, supersede `TASK-0044`'s amendment).

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

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected)
- `GLOSSARY.md` still devoid of implementation details; every new term the grill
  resolves is added to it **at that moment**

## Consumed Interfaces

- `Cache.get_regression_pools`, `Cache.get_pinned_slot_pool`,
  `Cache._training_day_starts`, `Cache._training_window_start_index`,
  `Cache.trim(reference, smoothing_radius)`, `Cache.pin_reference`,
  `Cache.clear_reference`, `Cache.pinned_reference` from
  `custom_components/shady/cache.py` (→ tasks: TASK-0043, TASK-0044, TASK-0039)
- `ShadyCoordinator.diagnosed_slot`, `DiagnosedSlot`, `pin_diagnostic_slot`,
  `_refit_sync`, `_trim_cache` from `custom_components/shady/coordinator.py` (→
  tasks: TASK-0043, TASK-0015b / TASK-0039)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->

## Handover: repository state and working notes

- Last commits: `GLOSSARY.md` (this session), `2d6c01c` (TASK-0044 smoothing
  extension), `6253d46` (TASK-0044), `469f279` / `c841e6a` (TASK-0043).
  `TASK-0043`, `TASK-0044`: `review`, **not accepted**.
- Suite at handover: `pytest` 996 passed;
  `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` clean; coverage `coordinator.py` 13 and `cache.py` 12
  uncovered lines (pre-existing). Environment: `uv sync`, then `uv run <tool>`.
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
  and run `uv run mdformat <files>` then `--check`.
- The human's standing preferences seen this session: reason before changing,
  ask before widening scope, "local time for everything user-facing", the
  integer slot index is irrelevant if the timestamp is right.

## Appendix: probes behind the findings (reproduce before relying on them)

Both run from the repo root with `PYTHONPATH=. uv run python <file>`; `Cache` is
loaded the way the cache tests do (`tests.support._load`).

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
