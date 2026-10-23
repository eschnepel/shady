# Task: Slot Recalculation After Effy's Rewrite — Pure Pipeline, Per-Day As-Of Refit, Statistics Write-Back

- **Status:** todo (Gate 2 approved and ADR-017 confirmed by the human on
  2026-10-21). The largest task of the Effy line: if the worker finds it too
  large for one pass it stops and proposes a split (Phase 6 Scenario A) instead
  of cutting scope.
- **Related ADRs:** \[ADR-017 (Accepted 2026-10-21 — the decisions this task
  implements), ADR-016 §4 (the trigger), ADR-007a §3/§4 (`Cache`, edited in
  place for the setters), ADR-005 (the sensors, edited in place for the
  statistics), ADR-004 and ADR-008 (the fit), ADR-001 (the intraday correction);
  Effy's ADR-021 and `history.py` as the statistics pattern — not part of this
  repository\]
- **Dependencies:** [TASK-0047b-effy-mode-runtime]

> Split from `TASK-0047b` after the `grill-with-docs` session of 2026-10-20.
> Everything here applies only in Effy mode.

## Goal

When Effy's closing step says it rewrote slots from a timestamp *t* on, Shady
recalculates every affected slot: one invalidation and one prefetch for the
whole range, the full pipeline per slot in a pure, state-free form, a refit as
of each past day for large ranges, and short-term and long-term recorder
statistics written for the recalculated slots — so the cache, Shady's sensors
and their history agree with Effy's corrected data (GLOSSARY.md: **Slot
recalculation**).

## Decisions that shape this task (grill 2026-10-20, ADR-017)

- Range: newest complete slot − slot(*t*) + 1, clamped; a restored-marked or
  unparsable state never defines a range.
- One `Cache.invalidate` per series over the whole range (actuals and Shady's
  own pushed series); one `get_time_range` over
  `[slot(t) − window_days, newest]`.
- Up to 6 slots together (even across midnight, live model); more: one chunk per
  HA local day, oldest first, each its own cache job; each chunk begins with an
  as-of refit into a scratch model; the live model is never touched.
- The pipeline of a slot is pure: it returns the full output (including what a
  tick would push ahead) and writes nothing live; only slot *k*'s values are
  committed. State is basis and `reset_at`; the counter is derived.
- Followed slot and diagnostics once, for the newest slot, after the last chunk;
  one refit as of now after it if the range reached before today's local
  midnight and covered more than 6 slots.
- Statistics for every sensor with a state class (cumulative ones included),
  short-term only inside the recorder's retention, long-term for completed
  hours; anchors for `sum`/`state`; the integrals' accumulators are set to the
  final value.
- Retention: `purge_keep_days` minimum N + 1, optimal 2N (README, ADR-017 §9).
- Terms: "slot recalculation"; never "replay"; Effy's "recalculate" stays
  Effy's.

## Acceptance Criteria

- **AC 1 — Range and guards.** Given a closing step that is not restored-marked
  and whose state parses as *t*, the affected slots are newest complete slot −
  slot(*t*) + 1, clamped to what cache and recorder retain; a *t* after the
  newest slot counts as one slot. A restored-marked or unparsable state starts
  the normal slot job only; nothing is invalidated or recalculated.
- **AC 2 — One invalidation, one prefetch.** `Cache.invalidate` is called once
  per series over `[slot(t), newest]` for every string's actual-yield entity and
  every pushed series the recalculation rewrites; baseline and temperature are
  not invalidated (asserted). Then exactly one `get_time_range` per input kind
  over `[slot(t) − window_days, newest]` (clamped) fetches everything missing; a
  test counts the recorder reads and asserts no per-chunk or per-slot re-fetch.
- **AC 3 — Batching.** At most `EFFY_RECALC_BATCH_MAX_SLOTS` (6, a constant in
  `const.py`) affected slots run together in one batch, also across local
  midnight, with the live model. More run as one chunk per HA local day, oldest
  first, the first starting at slot *t*, each its own `async_run_cache_job`; a
  live slot job runs between chunks and never cancels one. A 23-hour and a
  25-hour day are tested.
- **AC 4 — Pure pipeline.** The intraday advance and the derived-sensor
  computations are functions of (inputs, state) that return the full output and
  write nothing to the live cache. A golden test runs the pure function and the
  existing live path on identical inputs and asserts identical output; every
  existing test passes unchanged. `active_slots_since_reset` is derived from the
  basis; a test asserts it equals the carried counter when no tick was missed.
- **AC 5 — Commit per slot.** A recalculated slot commits only its own values
  (re-pushed into the invalidated frozen slot, `not_before_index` = the slot)
  and its statistics; nothing beyond slot *k* is written by a recalculated tick.
  The newest slot's tick is the normal live tick.
- **AC 6 — As-of refit per chunk.** Each chunk of a more-than-6 range starts
  with a fit as of its day (training window = the *N* days before it) into a
  scratch model that is never stored live and never resets the live intraday
  state; the chunk's intraday state starts reset at the day's start. A batch of
  at most 6 slots uses the live model. A test proves the live model and live
  intraday state are byte-identical before and after a 28-day range.
- **AC 7 — Closing the batch.** After the last chunk the followed-slot advance
  and the diagnostics run once for the newest slot; one normal refit as of now
  runs exactly once per batch if the range reached before today's local midnight
  and covered more than 6 slots. A routine 20-minute pattern across midnight
  produces zero refits; a range within today produces none.
- **AC 8 — Short-term statistics.** For every sensor with a state class, one
  short-term row per recalculated slot **inside** the recorder's retention
  (`keep_days` of the recorder instance); none outside. `MEASUREMENT` sensors
  get mean, min and max; cumulative ones `state` and `sum`. Verified against the
  real recorder with `statistics_during_period`, not a mock.
- **AC 9 — Long-term statistics.** One hourly row for every completed hour the
  range touched; an edge hour partly recalculated is completed from the existing
  short-term rows of its untouched slots, or left as it is when those are beyond
  retention; the hour in progress is not written.
- **AC 10 — Cumulative sensors.** Per cumulative sensor and table one anchor row
  (slot *t* − 1 short-term; the last long-term row before the first touched
  hour) recovers `state` and `sum`; `sum` is carried forward by Home Assistant's
  rule for the sensor's class (a `TOTAL_INCREASING` decrease is a reset). The
  two integrals are re-integrated slot by slot from the anchor and their
  `cache.energy_total` accumulators are set to the final value through a new
  `Cache` setter; a test asserts that the first live compile after a
  recalculation produces no jump or reset in `sum`.
- **AC 11 — Overlap and shutdown.** A new closing step invalidates its range at
  once and re-plans the chunks not yet started; a running chunk finishes; there
  is one dirty range. `async_shutdown` cancels queued chunks.
- **AC 12 — Docs.** ADR-017 is Accepted (confirmed 2026-10-21); ADR-007a gains
  the `Cache` setter(s) in place; ADR-005 gains the statistics write-back for
  its sensors in place; `adr/INDEX.md` and `tasks/adr-summary.md` are updated;
  README Effy-mode section describes the slot recalculation, the written
  statistics, its cost, and repeats the retention rule of `TASK-0047a` AC 11
  (minimum N + 1, optimal 2N); the "interim gap" sentence of `TASK-0047b` is
  removed.
- **AC 13 — Tests and cost.** Tests for AC 1–11 with the existing harness and
  the real `Cache`/recorder where stated. The worker measures one as-of refit
  and a 28-day history run on the available hardware, records the numbers in
  Delivered Artifacts, and escalates to the human if a history run is
  unreasonable.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/slot_pipeline.py` (new, pure) — the pure tick, the
  derived-sensor functions; `adr/000-coding-standards.md` §3 diagram gains the
  node.
- `custom_components/shady/statistics_writer.py` (new) — short-term and
  long-term rows, anchors, `sum` carry-forward.
- `custom_components/shady/coordinator.py` — range planner, chunk jobs, scratch
  fit, closing step, `async_shutdown`; the live tick calls the pure functions.
- `custom_components/shady/cache.py` — setter for the energy accumulators,
  possibly a multi-series invalidate helper.
- `custom_components/shady/const.py` — `EFFY_RECALC_BATCH_MAX_SLOTS`.
- `tests/test_slot_pipeline.py`, `tests/test_statistics_writer.py`,
  `tests/test_coordinator_slot_recalculation.py` (new), existing tests adapted
  only where the refactor moves a symbol.
- `README.md`, `adr/017-slot-recalculation-and-statistics.md`, `adr/007a-*.md`,
  `adr/005-*.md`, `adr/INDEX.md`, `tasks/adr-summary.md`.

## Definition of Done

- Tests green; `mypy`, `ruff check`, `ruff format --check` and
  `mdformat --check` clean on the whole tree; coverage of every touched module
  not lower than before.
- `Delivered Artifacts` block completed and accurate, including the measured
  numbers of AC 13.
- No new external dependency (`tasks/DEPENDENCIES.md` unchanged; the recorder's
  statistics API ships with Home Assistant).
- ADR-017 Accepted; no open ADR conflict.

## To check by the worker (not verified here)

- Home Assistant's statistics import API in the targeted version
  (`async_import_statistics`, `StatisticMetaData`, `StatisticData` fields,
  `has_mean`/`has_sum`, whether `mean_type` or similar is required), whether it
  accepts entity statistic IDs for custom integrations, how short-term and
  long-term rows are written together, and how `sum` is computed for `total`
  with and without `last_reset` versus `total_increasing`.
- Effy's `history.py` statistics import as the pattern (read, not imported):
  Effy's own handling of retention, edge hours and `sum`.
- How the live recorder compile treats a row Shady wrote for the slot it
  compiled a moment earlier, and that Shady's write for the newest slot is not
  overwritten by a later compile.
- Whether the as-of fit can reuse `_refit_sync` as a non-storing variant, and
  which of its outputs mutate live state (`set_model`, `_apply_intraday_reset`).
- How a slot timestamp maps to the cache's slot index for `Cache.invalidate`
  (`start`/`end` are slot indices, inclusive) and which `Cache.trim` retention
  floor the clamp uses.
- The recorder instance's `keep_days` access and its behavior when
  `purge_keep_days` is changed at runtime.

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation, from the Delivered Artifacts
     of TASK-0047b and TASK-0047a. -->

- the picked-entity listener and the closing-step hook in `coordinator.py` (→
  task: TASK-0047b-effy-mode-runtime)
- `EffyContract` parser symbols from `custom_components/shady/effy_contract.py`
  (→ task: TASK-0047a-effy-quick-config-flow)
- `ShadyCoordinator.async_run_cache_job`, `ShadyCoordinator.async_refit`,
  `ShadyCoordinator._refit_sync`, `_advance_intraday_string`,
  `_advance_followed_diagnostic_slot`, `local_date` from
  `custom_components/shady/coordinator.py` (→ tasks: TASK-0041 and earlier,
  `done`)
- `Cache.invalidate(sensor_id, start, end)`, `Cache.get_time_range`,
  `Cache.push`, `Cache.energy_total`, `Cache.trim` from
  `custom_components/shady/cache.py` (→ ADR-007a)
- the sensor classes in `custom_components/shady/sensor.py` (→ ADR-005)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. Be exact. -->
