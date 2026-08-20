# ADR-007a – `cache.py`: Storage Scheme and Accessor Design

**Date:** 2026-08-19
**Status:** Accepted
**Split from:** ADR-007 (2026-07-05), §1a–§1f. Originally part of the
coordinator/cache-module-split ADR; separated because the concrete
storage scheme and accessor API are a separable, and independently
heavily cross-referenced, concern from the *decision to extract
`cache.py` as its own module* in the first place — see ADR-007's
Revision note. No behavior changed by this split.

---

## Context

ADR-007 established that `cache.py` owns five independent caches and
stays free of any `hass` import. Two of those five are genuinely the
same *shape* of thing — a 5-minute-resolution time series per sensor,
over a rolling window, generic over `sensor_id` rather than tied to any
specific pair of series: the raw `FC`/`PV` history backing both
regression training (ADR-001 §3a, ADR-011) and diagnostics (ADR-004
§3), and the day-snapshot corrected-forecast array (ADR-002 §3). §1–§5
below give this one shared, index-addressable design rather than bespoke
handling per cache — a design that pays off again in ADR-003c, which
reuses this same accessor, unmodified, for a pair of series with nothing
to do with shading. The other two — the fitted-model cache (objects, not
floats) and the short-lived ramp/crossfade state (ADR-006 §1b) — stay
simple `dict[key, value]` structures without that machinery; see the end
of §5 for why they do not need it. The integral running totals (ADR-005
§5/§6) are simpler still — one persisted scalar each, and are not
otherwise discussed in this document; see ADR-007 §1 for their
restart-persistence treatment.

`cache.py` is constructed with `window_days: int` (the global setting
from ADR-001 §4/§6) as a **setup parameter**, alongside `fetch_fn` (§4)
— not re-supplied on every call. `window_days` is one value for the
whole cache instance, exactly like the global config-flow setting it
mirrors; sizing the per-sensor lists (§1) and resolving a slot pool's
default window (§5) both read this one stored value rather than each
call site passing its own copy of a number that never actually varies
between calls.

This document is the source of truth for `cache.py`'s storage scheme and
two of its three accessors (`get_time_range`, §5; `get_pinned_slot_pool`,
§6). The third, `get_regression_pools`, was added later by ADR-008 §2 for
the full-288-slot regression sweep — see ADR-008 §3 for how the three
divide up between the two documents.

---

## Decision

### 1 — Time-series storage: index-addressable, three-state values

```
values: dict[sensor_id: str, list[float | None | str]]
```

One list per sensor-id (an entity_id, or a Shady-internal series
identifier for something like the day-snapshot array), each entry
meaning:

- `float` — a known, valid value.
- `None` — not yet fetched, or explicitly invalidated; must be
  (re-)queried before use.
- `str` — a known, *stable* non-numeric outcome (e.g. `"unavailable"`):
  the recorder was asked and gave a definite, unusable answer. This is
  still a valid cache entry — querying again would return the same
  non-answer — it just is not a number a consumer can compute with.
  Distinguishing this from `None` avoids repeatedly re-querying an entity
  that is known to have no data for a given slot.

**Index = position in the rolling window, not a raw timestamp.** For a
28-day window at 5-minute resolution, that is `28 × 288 = 8064` entries
per sensor — small enough (a plain Python list of that size is a few
hundred KB even for several sensors at once) that a straightforward
implementation is preferable to a more compact but less flexible one:
`array.array('d', ...)` would pack floats tightly but cannot hold the
`None`/`str` states this design needs, so a plain `list` is used despite
the larger per-element overhead — correctness of the three-state model
matters more here than shaving a few hundred KB. The window size tracks
`window_days` from ADR-001 §4 (default 28) times 288, so it resizes if a
user changes the training window.

Indices are **absolute and monotonically increasing** from a single fixed
epoch (`index = (timestamp - epoch) // 5min`), not re-based to `0` at
every rollover — a second, small map tracks where each sensor's list
currently starts:

```
list_offset: dict[sensor_id: str, int]   # absolute index of list[0]
```

**Trimming is one explicit call, not an implicit side effect of writes.**
`cache.trim()` drops each sensor's oldest entries once its window has
rolled forward, advancing `list_offset` without needing to touch every
other piece of state that refers to an absolute index — in particular,
the validated ranges in §2 stay meaningful across a trim without
rewriting. `coordinator.py` calls `cache.trim()` exactly once, at the
ADR-002 §1 recalibration trigger (midnight or button) — never as a side
effect of the 5-minute tick (ADR-006 §1a) or a baseline update (ADR-002
§2). This matters beyond tidiness once §6's pinned reference date
exists: trimming needs to check whether it is currently set before
discarding anything older than the live window, and tying that check to
one explicit, predictable call — rather than letting it happen
implicitly on whichever trigger's write is next — is what makes that
check a guarantee instead of a race. See §6 for exactly how the
retained floor is computed.

### 2 — Validated range tracking

```
validated: dict[sensor_id: str, tuple[int, int | None]]
```

`(from_index, to_index)` — the absolute-index range currently known to be
up to date for that sensor. `to_index = None` has a specific meaning:
this sensor's values are **calculated by Shady and actively pushed**
(e.g. `ShadyForecastSensor`'s own corrected values, ADR-002 §2), so there
is no fixed upper edge to track — new values arrive by push (§3), not by
query, and are always current the moment they're written. Only sensors
sourced from *outside* Shady (raw actual-yield, raw `FC` history) have a
concrete `to_index` bounded by "the last slot known to be complete" —
these are the ones the validation function (§4) may need to query
forward for.

### 3 — Writing: push (by Shady) and invalidate (by anyone)

`coordinator.py` (the only caller of `cache.py`, per ADR-007 §2) can:

- **Push** a calculated value directly into a sensor's list at a given
  index, extending `validated`'s `to_index` for `to_index = None`
  sensors — this is how `ShadyForecastSensor`'s own output ends up in the
  cache without ever being queried back from the recorder.
- **Invalidate** a sensor's values over a given index range — sets those
  entries back to `None` and shrinks `validated` accordingly, forcing the
  next access to re-fetch (or, for a push-based sensor, to wait for the
  next push) before serving that range again.

### 4 — Initialization: an injected fetch function, and how validation catches up

`cache.py` is constructed with a **function parameter**, not a direct
recorder dependency:

```
fetch_fn: Callable[[sensor_id: str, start: datetime, end: datetime], list[float | None | str]]
```

`cache.py` never imports the recorder API itself — it calls whatever
`fetch_fn` it was given. This is what keeps it in the pure, zero-mocking
tier (ADR-000 §6): tests construct a cache with a trivial fake `fetch_fn`
returning canned data, no HA or recorder fixture needed. In the running
integration, `coordinator.py` supplies a `fetch_fn` backed by
`statistics_during_period` — the same call ADR-006 §1a already established
as this project's recorder-read pattern.

A **validation function**, given one or more sensor-ids (§5) and a
requested range, brings the cache up to date for exactly that request
before any accessor reads from it:

- A sensor with **no valid data at all** in the requested range (first
  ever access, or fully invalidated) is queried for its **entire**
  configured history window in one call — `window_days` worth, not just
  the requested slice, since a partial fetch now would likely just need
  extending again on the next access.
- A sensor **mostly valid, missing only a few recent slots** (the common
  case after being briefly offline, or simply time having passed since
  the last validation) is queried only for the **missing tail**, in one
  call.
- **Sensors sharing an identical missing range are a plausible, common
  case** — e.g. every sensor is equally behind after an HA restart — so
  the validation function groups sensors by their missing range first,
  issuing one `fetch_fn` call per distinct range rather than one per
  sensor, even though `fetch_fn` itself is still a single-sensor
  signature (grouping reduces call *count*, not by batching multiple
  sensors into one `fetch_fn` call, which would need a different
  `fetch_fn` shape than the simple per-sensor one above — kept simple
  deliberately, since the *number* of distinct missing ranges in practice
  is small, usually one).

### 5 — Accessor methods

`cache.py` exposes one generically-shaped accessor for the "contiguous
range" pattern, shared across its callers:

- **`get_time_range(sensor_ids, start, end, on_invalid: Literal["skip", "raw"] | float = 0.0, group_by="sensor"|"slot") -> dict | list[dict]`**
  — "every slot in a contiguous range": ADR-005 §3's whole-day array,
  ADR-006 §1a's trailing rolling window (length configurable, ADR-006
  §3). `group_by="sensor"` returns
  `{sensor_id: [v0, v1, ...]}` (one time series per sensor — what ADR-006
  §1a's per-string window sum wants); `group_by="slot"` returns one dict
  per slot instead, `[{sensor_id: v, ...}, ...]` (what ADR-005 §3's
  cross-string per-slot sum wants — "for this slot, every string's
  value", ready to sum directly without a second transpose step). Default
  `on_invalid=0.0` here, not `"skip"` — a whole-day array is expected to
  have one entry per slot for charting (ADR-004 §2's `series`), so a
  fixed length matters more than it does for a training pool, and `0` is
  a reasonable stand-in for "no data" in a power series.

The other shape this module needs — "the same slot, across many days",
exactly ADR-001 §3a's / ADR-011's training pool — is **not** given a
shared, generic accessor. It has exactly two callers, and they turned out
to need different enough outputs — diagnostics (§6) wants a pin-aware
date anchor resolved internally and a plain `list[float]`; regression
fitting wants a batched `numpy` array across the full 288-slot sweep and
never a pin — that a single parameterized method would need a branch for
a concern only one caller actually has. Each gets its own purpose-built
accessor instead, defined alongside its one caller: `get_pinned_slot_pool`
for diagnostics, next in §6; `get_regression_pools` for regression
fitting, in ADR-008 §2.

**What the third mode, `"raw"`, is for.** `"skip"` and a numeric default
both
already discard the difference between "never queried"/"invalidated"
(`None`) and "queried, definitively unavailable" (`str`, §1) — the right
choice for a consumer like `get_pinned_slot_pool`'s diagnostics caller or
ADR-005/ADR-006's summed windows, which only ever want a clean
`list[float]` and have no use for the reason a gap exists. `"raw"` skips
that shaping step entirely and returns each entry exactly as `cache.py`
stores it internally (§1) — `float`, `None`, or the `str` reason-id,
unchanged. This changes the accessor's own return-type contract for that
one call, from `list[float]` to `list[float | None | str]`; a consumer
choosing `"raw"` takes on the same responsibility for handling all three
states that reading `cache.py`'s `values` store (§1) directly would
require, the one difference being that it still goes through §4's
validate-before-read step below rather than bypassing it. No consumer
described elsewhere in this design uses `"raw"` today — every current
caller genuinely wants the cleaned shape their own default already gives
them — but the accessor design does not foreclose it: a future
diagnostic or data-quality consumer (e.g. surfacing *which* sensors are
stuck on a stable `"unavailable"` versus merely not-yet-queried) can
request it from either method without `cache.py` needing a new method or
a bespoke escape hatch added later.

Both accessors — `get_time_range` above and `get_pinned_slot_pool` in
§6 — **validate before reading**: each call first runs §4's validation
function for the requested sensor-ids and range, fetching on-demand
anything not already fresh, then reads and shapes the result — a
consumer never has to separately remember to validate first. This
applies identically regardless of which `on_invalid` mode is chosen —
`"raw"` changes how a gap is *reported*, not whether the cache was
brought up to date before reporting it.

Both **return** a fully-materialized `dict`/`list`, not a generator. Data
volumes here are small (at most a few thousand floats per call, a
handful of sensors) — a generator would add interface complexity for no
real memory or latency benefit at this scale.

`sensor_ids` always accepts a **list**, even for a single sensor (a
one-element list) — the common real callers (ADR-005's cross-string
sums, ADR-001's per-string fits run across every configured string) need
several sensors at once, and a single-sensor call is just the trivial
case of the same interface, not different enough to warrant a second
method. This is also what makes a combined `FC`+`PV` fetch for an entire
regression sweep a single call rather than one per string: the caller
passes every string's `PV` `sensor_id` plus every *distinct* `FC`
`sensor_id` actually in use (naturally fewer than the string count
whenever strings share the global default baseline, ADR-009 §5) in one
list, and `get_regression_pools`'/`get_time_range`'s `dict[sensor_id,
...]` return shape means a shared `FC` entry is present exactly once in
the result regardless of how many strings reference it — no separate
call, and no duplicate storage, per string that happens to share it.

The **model cache** (fitted model objects per string/slot) and the
**ramp/crossfade state** (ADR-006 §1b) do not fit this time-series shape
— a fitted model is an object, not a float, and ramp/crossfade state is a
small, short-lived record, not a rolling window. Both stay as simple
`dict[key, value]` structures elsewhere in `cache.py`, without the
index/validation machinery above; only the genuinely time-series-shaped
caches (raw `FC`/`PV` history, the day-snapshot array) use it.

### 6 — Pinned diagnostic reference date: one value, cache-wide

A manually-pinned diagnostic slot (ADR-004 §2a) needs its slot-pool built
from a window ending at the *pinned* date, not at today. **There is only
one pinned reference date at a time, for the whole cache instance — not
one per sensor, and not one per string.** `cache.py` holds it as a
single scalar, `pinned_reference: date | None`, set via
`pin_reference(date)` and cleared via `clear_reference()` — no
`sensor_id` argument to either, in the same spirit as `window_days`
(see Context above) being one setup-level value rather than something
re-supplied, or re-scoped, per call. `coordinator.py` calls these in
direct response to the `shady.select_diagnostic_slot` service (ADR-004
§2a), which is itself not entity-targeted — there is no per-
`ShadyDiagnosticsSensor` "am I pinned" state anywhere, in `cache.py` or
otherwise. Every diagnostics sensor (each string's, and ADR-004 §2b's
summed one) simply reads whether `pinned_reference` is currently set
each time it needs to know which slot to show: `cache.py`'s one scalar
is the *complete* answer, not one input alongside separate per-entity
state.

Diagnostics gets its own dedicated accessor for this — rather than a
`pinned: bool` flag bolted onto a shared method — because pin-resolution
below is a concern unique to this one caller, consistent with
`window_days` also not being a per-call argument (§5):
**`get_pinned_slot_pool(sensor_ids, slot_of_day, on_invalid: Literal["skip",
"raw"] | float = "skip") -> dict[sensor_id, list[float]]`** — "the same
slot, across many days" shape (ADR-001 §3a's / ADR-011's training pool),
scoped to this one caller. Its window is resolved from
`pinned_reference` **internally**: `[pinned_reference − window_days,
pinned_reference]` if a pin is currently set to a date no later than
today, otherwise falling back to today-anchored — `[today − window_days,
today]`, `window_days` sizing the window identically either way. A pin to
a **future** date takes that same today-anchored branch, not a
`pinned_reference`-anchored one: recalibration (ADR-002 §1) never trains
any slot's model on data newer than yesterday, so there is no
future-anchored pool for a future pin to resolve to in the first place
— a future-pinned slot's pool is, and can only ever be, the same one an
auto-tracking sensor for that same time-of-day already sees (ADR-004
§2a). This is the **only** accessor
ADR-004's diagnostics feature ever calls, whether currently pinned or
auto-tracking — there is no separate today-only diagnostics call to
choose between; `coordinator.py` never branches on `pinned_reference`
itself to decide which function to call, it just always calls this one
and lets it resolve its own anchor. Regression fitting during
recalibration needs "today", full stop, regardless of any diagnostic pin
— it has its own accessor entirely, `get_regression_pools` (ADR-008 §2),
serving a different caller with a different output shape (a batched
`numpy` array for the full sweep, rather than this method's
per-diagnostic-call `list[float]`); the two never share a code path.

Because both branches resolve to the same-shaped `[anchor − window_days,
anchor]` window and go through the same validate-before-read call
(§4), whether a given `get_pinned_slot_pool` call actually needs a new
recorder fetch or is served entirely from cache depends on **whether
that window is already cached** — not on which branch was taken. In the
common auto-tracking case, and for any pin to today or a future date,
the resolved window is `[today − window_days, today]`, exactly what the
same day's recalibration already fetched moments earlier, so the call is
served from already-validated entries with no new recorder query. A pin
to an older *past* date will typically *not* already be cached, so that
same call does trigger a genuine fetch for the missing range — the
underlying mechanism is identical in both cases; only whether it happens
to find its target already there differs.

**Effect on trimming.** Because there is only one pinned date, not one
per sensor, trimming does not need any per-sensor bookkeeping for this
either: whenever `pinned_reference` is set, `cache.trim()` (§1) uses
`min(today − window_days, pinned_reference − window_days)` as the
retained floor for **every** sensor — simpler than tracking which
sensor-ids the pin specifically depends on, at the cost of retaining
slightly more data than the strict minimum while a pin is active. Once `clear_reference()`
is called, the floor reverts to the plain `today − window_days` on the
*next* `cache.trim()` call — clearing a pin does not itself reclaim
anything retained on its account; the next explicit trim does. A pin set
for a date whose data an *earlier* trim (before the pin existed) already
discarded cannot be recovered from cache alone — same residual
limitation ADR-004 §2a already accepts for the pre-existing "outside the
window" case, just narrower in scope now.

---

## Consequences

- **Pro:** The index-addressable time-series design (§1-§5) is one
  shared implementation backing multiple caches (raw `FC`/`PV` history
  for both training and diagnostics, the day-snapshot array — and, per
  ADR-003c, a second and unrelated series pair) instead of bespoke
  handling per consumer — a bug fixed or an optimization made in the
  validation/fetch logic (§4) benefits all of them at once.
- **Pro:** The three-state value model (`float`/`None`/`str`, §1)
  distinguishes "not yet known" from "known to be unavailable" — without
  it, an entity with genuine recorder gaps would be re-queried forever,
  since a cache could never tell "haven't checked" apart from "checked,
  there's nothing there".
- **Pro:** `fetch_fn` injection (§4) keeps `cache.py` fully testable
  without a real or mocked recorder — a test constructs a cache with a
  trivial fake function returning canned data.
- **Pro:** The third `on_invalid="raw"` mode (§5) means a future consumer
  that needs to distinguish "not yet queried" from "queried, definitively
  unavailable" does not require a new accessor method or a direct reach
  into `cache.py`'s internal `values` store to get it — both existing
  accessors already expose the full three-state value model (§1)
  on request, alongside the two cleaned shapes (`"skip"`/default value)
  their current, known consumers actually use.
- **Con:** The absolute-index-with-offset scheme (§1) is more moving
  parts than a naive "re-slice a list every day" approach would be —
  justified by avoiding the need to rewrite every sensor's `validated`
  range (§2) on every rollover, but it is still a piece of bookkeeping
  that has to be gotten right (an off-by-one in `list_offset` silently
  misaligns every subsequent read for that sensor).
- **Con:** `get_time_range` (§5) and `get_pinned_slot_pool` (§6) are
  two separate methods with different defaults (`on_invalid=0.0` vs.
  `"skip"`, out of the three modes — `"skip"`, a numeric default, or
  `"raw"` — either accessor accepts) rather than one uniform interface —
  a deliberate choice given how differently their consumers need to treat
  a gap, but it means there are two accessor shapes to learn instead of
  one, each with its own default out of three possible `on_invalid`
  behaviors.
