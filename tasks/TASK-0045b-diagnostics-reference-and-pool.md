# Task: Diagnostics Pool Anchored on the Diagnosed Slot (Reference Day, Timestamp Arithmetic, Neighbor Fix)

- **Status:** review (awaiting Gate 2 approval)
- **Related ADRs:** \[ADR-004 §2, §2a, §2g, §3 (diagnosed-slot parts; or the
  split part per TASK-0046), ADR-007a §6, ADR-013\]
- **Dependencies:** [TASK-0045a-wording-alignment]

> Part of the split of `TASK-0045-apply-glossary-terminology` (decision record
> for the grill of 2026-10-11; the decisions below are copied from it, so this
> file is self-contained). Terms are those of `GLOSSARY.md`.

## Goal

Make the **diagnostics** pool (following or pinned) obey the glossary: it is
measured from the **diagnosed slot** as reference timestamp, holds the training
window's days **before the reference day**, never contains the diagnosed slot's
own sample, never reads the future, and its neighbors cross midnight like any
other time.

## Decisions (human — inputs, do not re-ask)

- **Reference.** The reference timestamp of the diagnostics is the diagnosed
  slot (the followed slot while following, the pinned slot while pinned). The
  **reference day** is the 24 hours ending at the local midnight that closes the
  local date of the reference timestamp; every earlier day lies exactly 24 hours
  before the next (no 23/25-hour days). The **training window** is the
  configured `window_days` days immediately before the reference day; the
  reference day is **not** part of the pool.
- **Timestamp arithmetic.** The sample for day _i_ is the diagnosed slot minus
  _i_ × 24 h (_i_ = 1 … `window_days`); neighbors are the diagnosed slot ± _k_ ×
  5 min as plain timestamps (23:55's neighbor is 00:00 of the next day). The
  integer slot-of-day "does not matter as long as the timestamp is equivalent".
- **G8** `DiagnosedSlot.slot_of_day` stays as a **local display value** (the
  ADR-015 CSV metadata `"slot_of_day"`); it must no longer feed any pool
  computation. It is not a glossary term.
- **G10 — 12 slots a year.** On the first hour (00:00–00:55) of a 25-hour date
  the closing-midnight reference day starts at 01:00, so the followed slot lies
  inside window day 1. The pool for those slots is still `diagnosed − i × 24 h`
  (_i_ = 1…N) — one day further back, never containing the slot itself, no
  special-casing in the code. State it in **one sentence** in the ADR text (not
  an amendment, not in the glossary).
- **G11 — night hours.** For 00:00–04:00 the diagnostics anchor on the followed
  slot, while the model in use was fitted at the previous 04:00 (its window ends
  one day earlier). Accepted; **one sentence** in the ADR text.
- **G14 — Lean ADRs.** Edit the main text; no `Amendment` blocks; stable section
  numbers.

> **Pitfall (hit while writing this task):** subtracting a `timedelta` from an
> aware `datetime` that carries a `ZoneInfo` does **wall-clock** arithmetic and
> silently ignores a clock change in between. Do all "minus _i_ × 24 h"
> arithmetic on UTC instants or on slot indices (`index − i × 288`), and only
> then convert to local for labels or tests.

## Evidence (reproduce before relying on it; run with `PYTHONPATH=.`)

**D1 — Following anchors on `now`, not on the diagnosed slot.** Probe A
(Europe/Berlin, 00:03 local on 20 Jun, following): the diagnosed slot is Fri 19
Jun 23:55 but `get_pinned_slot_pool` anchors on today and returns
`[Thu 18 Jun 23:55, Fri 19 Jun 23:55, None]` — a day off, with a future sample.
`compare_regressions._gather_pool` passes `reference=<now>`.

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
c = cm.Cache(3, fetch, local_tz=tz, clock=lambda: now)  # following: no pin
last_completed = cm.Cache.index_for(now) - 1
ts = cm.Cache.timestamp_for(last_completed).astimezone(tz)
slot_of_day = int((ts - datetime(ts.year, ts.month, ts.day, tzinfo=tz)) / cm.SLOT_DURATION)
pool = c.get_pinned_slot_pool(["s"], slot_of_day, on_invalid="raw", reference=now)["s"]
# measured: diagnosed Fri 19 Jun 23:55 (slot_of_day 287);
# pool -> [Thu 18 Jun 23:55, Fri 19 Jun 23:55, None]
```

**D2 — The pool includes the reference day.** `get_pinned_slot_pool`'s window is
"reference day and the `window_days − 1` days before it", so the diagnosed
slot's own sample is the newest point.

**D3 — Pinned pool places days by the oldest day's local midnight** (`cache.py`
`get_pinned_slot_pool`, ~l.1130–1200): index =
`oldest-day local midnight + day_offset × 288 + slot_of_day`; across a DST
change the pool is an hour off the diagnosed timestamp. Probe B (Berlin, pinned
Mon 30 Mar 2026 after the 29 Mar spring-forward, local slot 120 = 10:00): the
diagnostics hold `03-28 10:00, 03-29 11:00, 03-30 11:00`; the model holds
`03-28 09:00, 03-29 10:00, 03-30 10:00`. Setup: same loader and `fetch` as
above, `c = cm.Cache(3, fetch, local_tz=ZoneInfo("Europe/Berlin"))`,
`c.pin_reference(date(2026, 3, 30))`,
`c.get_pinned_slot_pool(["s"], 120, on_invalid="raw")["s"]`; the model row is
`c.get_regression_pools(["s"], 0, reference=<2026-03-31 00:01 Berlin>)["s"][96]`.
The cache-level pin is a **date** (`pin_reference(date)`); the new definition
needs a **timestamp**.

**D4 — Neighbor wraparound.** `compare_regressions._gather_pool` computes
`offset_slot = (diagnosed.slot_of_day + offset) % SLOTS_PER_DAY` (~l.540), so
23:55's neighbor reads slot 0 of the **same** local day instead of 00:00 of the
next.

## Acceptance Criteria

- Given following at 00:03 local (Probe A repeated), then the reference day is
  yesterday, the pool holds the `window_days` days before it, and there is no
  `None` sample and no sample from today.
- Given the Probe B setup (pinned Mon 30 Mar 2026 10:00 CEST = 08:00 UTC,
  `window_days = 3`), then the pool holds, oldest first,
  `27 Mar 09:00 CET, 28 Mar 09:00 CET, 29 Mar 10:00 CEST` (diagnosed − _i_ × 24
  h for _i_ = 3, 2, 1) — the reference day (30 Mar) is **not** in it. (Probe B
  as originally run, with the model reference at 31 Mar 00:01, still shows the
  old day-aligned window 28–30 Mar; do not compare against it.)
- Given any diagnosed slot (following or pinned), then every pool sample and
  every neighbor is the diagnosed slot ± whole multiples of 24 h / 5 min, and
  the diagnosed slot's own sample is not in its pool.
- Given the diagnosed slot is 23:55, then its neighbor at +1 is 00:00 of the
  next day.
- Given a diagnosed slot in 00:00–00:55 of a 25-hour date (e.g. 25 Oct 2026,
  Europe/Berlin, fake clock), then the pool is `diagnosed − i × 24 h`, contains
  no future sample and not the slot itself (G10).
- Given the CSV export, then `slot_of_day` is still written as the local display
  value, and no pool computation reads it.
- Given the pinned slot changes or is cleared, then `Cache.trim`'s pin floor
  still never removes data a pinned pool needs (a conservative floor is fine;
  `TASK-0045c` finalizes the floor).
- Given the timezone is UTC and no DST, then every pre-existing diagnostics and
  cache test passes unless it pinned a superseded definition (restate those, do
  not delete them). New tests fail against the old code.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — `get_pinned_slot_pool` (overloads and
  implementation), `pin_reference` / `clear_reference` / `pinned_reference`
- `custom_components/shady/coordinator.py` — `DiagnosedSlot`,
  `diagnosed_slot()`, `pin_diagnostic_slot`, `_diagnostic_slot_index`
- `custom_components/shady/diagnostics/compare_regressions.py` — `_gather_pool`,
  `_export_window_start_date`; `diagnostics/base.py`
- `tests/test_cache_pinned_slot_pool.py`, `tests/test_cache_core.py`,
  diagnostics and coordinator tests; ADR text of the diagnosed-slot parts
  (ADR-004 §2a/§2g, ADR-007a §6)

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none)

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation. -->

- `Cache.get_pinned_slot_pool`, `Cache.pin_reference`, `Cache.clear_reference`,
  `Cache.pinned_reference`, `Cache.trim(reference, smoothing_radius)` from
  `custom_components/shady/cache.py` (→ tasks: TASK-0043, TASK-0044, TASK-0039)
- `ShadyCoordinator.diagnosed_slot`, `DiagnosedSlot`, `pin_diagnostic_slot`,
  `_trim_cache` from `custom_components/shady/coordinator.py` (→ tasks:
  TASK-0043, TASK-0015b / TASK-0039)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. -->
