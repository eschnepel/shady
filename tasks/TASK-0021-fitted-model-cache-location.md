# Task: Fitted-Model Cache Location — Decision & Fix

- **Status:** todo
- **Related ADRs:** [ADR-007, ADR-007a, ADR-014]
- **Dependencies:** [TASK-0002-cache-core-time-series-store, TASK-0006-cache-batched-regression-pool-accessor, TASK-0010-coordinator-recalibration-recompute-push, TASK-0017-string-computation-module]

## Goal
`AUDIT-0003-cache-module` found a confirmed FAIL: ADR-007 §1 lists
"Per-string, per-slot fitted-model cache" as one of the five things
`cache.py` holds, and ADR-007a §5 is explicit that the model cache
should live "elsewhere in `cache.py`, without the index/validation
machinery." The shipped code does not do this — `self._models: dict[int,
FittedModel]` and `self._temperature_models: dict[int, FittedModel]` are
constructed and live directly in `coordinator.py` (`coordinator.py:461,
470`), alongside, not inside, `self.cache = Cache(...)`. `cache.py`'s own
module docstring independently confirms it never claims to own this —
code and its own documentation agree with each other, and both disagree
with the two ADRs.

This is a genuine, undecided fork: the audit itself flags this as
architecturally defensible (a `FittedModel` is an object, not a
`float | None | str` time-series value; keeping it next to
`coordinator.py`'s fit/predict loop may be the more coherent design) —
but no ADR amendment records the deviation. This task's job is to get a
human decision, then execute exactly one of the two resulting paths.

## Known Decisions
- The as-built behavior (predictions are correct either way; this is a
  documentation/architecture-consistency question, not a correctness
  bug) is not itself in question — `AUDIT-0003` found no behavioral
  defect anywhere in the cache module.
- Whichever path is chosen, `TASK-0002`/`TASK-0006`'s own `Delivered
  Artifacts` blocks must **not** be reopened or edited — this task
  either patches them (Scenario C, if relocating) or amends the ADRs
  that describe them (if documenting as-built).

## Open Questions for Execution
**This task cannot start implementation until the human picks one of
the following two paths.** Do not guess; do not default to either
option without an explicit answer recorded here first.

- **Option A — Amend the ADRs to match the code.** Add an amendment to
  ADR-007 §1 and ADR-007a §5 stating the fitted-model cache is
  intentionally `coordinator.py`-resident (not `cache.py`-resident),
  with the rationale AUDIT-0003 already sketched (object identity vs.
  time-series value; co-location with the per-string fit/predict loop,
  which TASK-0017 later also relocated to `string_computation.py`). No
  code changes. Lowest risk, fastest to close.
- **Option B — Relocate the model cache into `cache.py` to match the
  ADRs as written.** Move `self._models`/`self._temperature_models`
  (and their read/write access patterns) into `Cache` as plain
  `dict[key, value]` stores, per ADR-007a §5's own description, and
  update every `coordinator.py` call site to go through the new
  accessor instead of the raw dict. Higher risk — touches
  `coordinator.py`'s fit (`_fit_string`/`_fit_temperature_string`) and
  predict (`_predict_day_basis`) paths, both already patched multiple
  times (see `tasks/INDEX.md` refinement log), and every test file that
  constructs a coordinator/cache pair.
- If Option B is chosen, a follow-up question: should the relocated
  store go through `cache.py`'s existing three-state/validated-range
  machinery, or stay a bare `dict` exactly as ADR-007a §5 already
  specifies ("without the index/validation machinery above")? ADR-007a
  §5's text already answers this (bare `dict`) — flagged here only so
  the worker doesn't second-guess it once Option B is chosen.

## Decision
Proceed with Option B including the validated range logic.

## Acceptance Criteria
*(Both options share the first two; the rest are option-specific.)*
- Given the human's decision is recorded in this task's own `Known
  Decisions`/`Open Questions` section (edited in place once answered,
  not silently assumed), When implementation begins, Then the worker
  proceeds only along the recorded path.
- Given the full test suite, When run after this task, Then it is still
  100% green, with **no additions to Option A's own scope** (Option A
  changes no `.py` file, so no test count change is expected) and, for
  Option B, `tests/test_cache_core.py`/`tests/test_cache_regression_pools.py`
  gaining model-cache-specific tests plus `tests/test_coordinator.py`'s
  existing model-cache-adjacent tests updated to use the new accessor
  (not deleted — behavior-preserving refactor).
- **Option A only:** Given `adr/007-coordinator-cache-split.md` and
  `adr/007a-cache-storage-and-accessor-design.md`, When read after this
  task, Then each carries a new, dated Amendment block documenting the
  as-built `coordinator.py` location and its rationale, and
  `tasks/adr-summary.md` is updated to match.
- **Option B only:** Given `cache.py`, When read after this task, Then
  it exposes the model cache via new `Cache` methods (naming convention
  matching the file's existing accessors, e.g. `get_model`/`set_model`
  or equivalent) and `coordinator.py` no longer constructs
  `self._models`/`self._temperature_models` as raw dicts — every read/
  write site (`_fit_string`, `_fit_temperature_string`,
  `_predict_day_basis`, and any diagnostics call site added by
  `TASK-0015b`) goes through the new accessor.

## Estimated File / Module Footprint (hint, not a commitment)
- **Option A:** `adr/007-coordinator-cache-split.md`,
  `adr/007a-cache-storage-and-accessor-design.md`,
  `tasks/adr-summary.md` — no `.py` file.
- **Option B:** `custom_components/shady/cache.py`,
  `custom_components/shady/coordinator.py`,
  `tests/test_cache_core.py`, `tests/test_coordinator.py`, and any
  diagnostics call site `TASK-0015b` added.

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate, stating which
  option was chosen and why
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected for either option)

## Consumed Interfaces
- `custom_components/shady/cache.py` → `Cache` class and its existing
  three accessors (`get_time_range`, `get_pinned_slot_pool`,
  `get_regression_pools`) — (→ task: TASK-0002, TASK-0006) — the
  existing accessor-naming/shape convention Option B must match if
  chosen.
- `custom_components/shady/coordinator.py` → `self._models`,
  `self._temperature_models`, `_fit_string`, `_fit_temperature_string`,
  `_predict_day_basis` — (→ task: TASK-0010) — the current call sites
  Option B must update.
- `custom_components/shady/string_computation.py` → `fit_string_model`,
  `predict_string_forecast` — (→ task: TASK-0017) — confirms the
  fit/predict logic itself is already relocated out of `coordinator.py`;
  only the *storage* of the resulting `FittedModel` objects is in
  question here.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. -->
