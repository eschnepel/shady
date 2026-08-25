# Task: Patch — `recency_weight_i` in `regression/base.py`'s `build_pool`

- **Status:** todo
- **Related ADRs:** [ADR-001 §2, ADR-001 §4a, ADR-011 §1]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0005-patch-1-ndarray-typing]

## Goal
`regression/base.py`'s `build_pool` already folds `magnitude_weight_i`
and ADR-011 §1's `time_weight_i` into each sample's pool weight (ADR-001
§2). Per ADR-001 §4a's 2026-08-25 amendment, add the third factor,
`recency_weight_i` — a per-training-day downweight, linear from `1.0` at
the most recent day in the window down to `1 - recency_decay_max` at the
oldest, folded into the exact same `combined_weight` product every other
factor already uses.

**No change to `build_pool`'s input *shape*.** Every offset's
`fc_by_offset[offset]`/`pv_by_offset[offset]` array is already `(n_slots,
window_days)`, **oldest day first** in the column axis (`cache.py`'s
`get_regression_pools` "Column layout" docstring, TASK-0006's own
documented convention, unchanged by TASK-0006's own delivery) — so
`recency_weight_i` is computable entirely from `window_days` (already
recoverable as `fc_by_offset[offset].shape[1]`, exactly how the existing
code already infers array shape) and the new `recency_decay_max`
parameter, with no new data the caller must supply. This is a pure
addition to `build_pool`'s existing per-offset loop, not a change to
`coordinator.py`'s day-column assembly (`_split_by_offset`, TASK-0010) —
that adapter's own column-ordering contract is exactly what makes this
patch computable locally, and needs no change itself.

**Human-initiated feature addition, not a worker-discovered gap** — same
"don't reopen a `done` task, patch instead" mechanics Scenario C already
establishes (precedent: the 2026-08-22 `NDArray` typing patches, also
human-directed). `TASK-0005` stays `done`, unreopened.

## Acceptance Criteria
- Given `window_days > 1` and a `recency_decay_max` of `0.5`, When
  `build_pool` runs, Then every offset block's most-recent day (last
  column) contributes at weight `1.0` (before `magnitude_weight_i`/
  `time_weight_i`/validity multiply in, exactly as those two already
  combine) and its oldest day (first column) contributes at weight
  `0.5`, with every day in between linearly interpolated —
  `recency_weight_i = 1 - (day_age_i/(window_days-1)) *
  recency_decay_max`, `day_age_i` counted from the most recent column.
- Given `recency_decay_max = 0.0`, When `build_pool` runs, Then
  `recency_weight_i` is `1.0` for every day — behaviorally identical
  output to `build_pool` before this patch (this task's own regression
  guard: existing `tests/test_regression.py` cases re-run with an
  explicit `recency_decay_max=0.0` must still pass unmodified).
- Given `window_days == 1`, When `build_pool` runs, Then
  `recency_weight_i = 1.0` unconditionally (the degenerate case, ADR-001
  §4a — avoids a `window_days - 1 == 0` division).
- Given multiple ADR-011 §1 offset blocks (`smoothing_radius > 0`), When
  `build_pool` runs, Then the exact same per-day-column `recency_weight_i`
  values apply identically to every offset block — never recomputed or
  varied per offset, since recency is a property of the calendar day, not
  of slot-of-day distance (ADR-001 §4a's explicit interaction note).
- Given the `SamplePool.confidence` output, When inspected, Then it
  reflects `recency_weight_i`'s contribution automatically (no separate
  formula — `confidence = weight.sum(axis=1)` already exists and
  `weight` already includes every combined factor; ADR-001 §2's updated
  confidence formula, `Σ magnitude_weight_i · time_weight_i ·
  recency_weight_i`).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/regression/base.py` — `build_pool` gains a
  new required parameter, `recency_decay_max: float`, and one new
  per-offset-loop weight factor multiplied into `combined_weight`
  alongside `magnitude_weight`/`time_weight`/`valid_mask` (same loop
  `time_weight` already lives in — no new loop needed).
- `tests/test_regression.py` — a new `TestRecencyWeight` class:
  most-recent-day-weight-1.0, oldest-day-weight-matches-`1 -
  recency_decay_max`, `recency_decay_max=0.0` reproduces pre-patch
  output byte-for-byte, `window_days=1` degenerate case, and the
  identical-across-offset-blocks check.

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
- `regression.base.build_pool`'s existing signature and `SamplePool`
  dataclass — already-`done`, same-module code this patch extends; no
  new external interface consumed. Independent of
  `TASK-0009-patch-2-recency-decay-config-field` — `regression/base.py`
  is a pure module (no `hass`, no `const.py` import, ADR-000 §3/§6) and
  never reads a `CONF_*` key itself; it only receives
  `recency_decay_max` as a plain `float` parameter, same as
  `neighbor_fitting_cutoff` already is.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
