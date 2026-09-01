# Task: Patch — `DiagnosticSlotSample`'s Missing Query-FC and Fit-Input Fields

> **SUPERSEDED — 2026-09-01, no code written for this task.** Human
> decision (see `tasks/INDEX.md`'s 2026-09-01 refinement-log entry and
> ADR-004 §5's second Amendment): rather than threading fit inputs through
> `DiagnosticContext` per call as this task specifies, `DiagnosticMode`
> now receives the owning `ShadyCoordinator` at construction and gathers
> what it needs directly. This task's approach and
> `TASK-0015a-patch-2-diagnostic-mode-coordinator-access`'s approach are
> mutually exclusive, not additive — the human explicitly chose the
> latter over keeping both. **Doubly moot, on review:**
> `TASK-0015a-patch-2` doesn't just supersede this task's approach, it
> deletes the class this task would have extended — `DiagnosticSlotSample`
> and `DiagnosticContext` are removed from `diagnostics/base.py` entirely,
> along with `compute()`/`extra_fit()`'s parameter. There is nothing left
> for this task's `query_fc`/`fit_inputs` fields to be added to. **Do not
> implement this task.** Kept in place, unexecuted, for the audit trail
> (slug not reused, per this project's standing convention for retired
> tasks — see the 2026-08-30 refinement-log entry). `TASK-0015b`'s
> Dependencies no longer reference this task.

- **Status:** superseded *(was: todo — never implemented; superseded before any code was written)*
- **Related ADRs:** [ADR-004 §1/§5 (Amendment 2026-08-30), ADR-014]
- **Dependencies:** [TASK-0015a-diagnostic-mode-base-architecture, TASK-0017-string-computation-module]

## Goal
Scenario C patch on the already-`done` `TASK-0015a`: while scoping
`TASK-0015b`'s Consumed Interfaces, two gaps surfaced in
`DiagnosticSlotSample` as `TASK-0015a` delivered it — neither is a bug
in what was delivered (it matched ADR-004's Amendment sketch exactly),
both are things that sketch simply never included a field for. See
`tasks/INDEX.md`'s refinement log for the full discovery context.

1. **No field carries `FC_selected`** (the diagnosed slot's own query
   forecast value) — needed as the shared x-coordinate for every
   `"selected {method}"`/`"selected actual"` point `compute()` builds
   (ADR-004 §2), and `DiagnosticSlotSample.predicted`/`actual` alone
   don't carry it.
2. **No field carries what `extra_fit()` needs to actually fit
   anything** — `DiagnosticMode` is pure (no `cache.py`, no
   `homeassistant.*`), so every raw input its `extra_fit()` needs must
   arrive via `DiagnosticContext`/`DiagnosticSlotSample`. Before
   `TASK-0017` existed, there was no shape to hand over that would even
   be useful; now that `string_computation.py`'s `fit_string_model`/
   `predict_string_forecast` exist, the missing shape is exactly their
   parameters.

## Acceptance Criteria
- Given `DiagnosticSlotSample`, When constructed with all existing
  fields unchanged and neither new field supplied, Then it behaves
  exactly as `TASK-0015a` delivered it — both new fields default to
  `None`, and every existing `tests/test_diagnostics_base.py` call site
  continues to pass with no edits.
- Given `DiagnosticSlotSample.query_fc: float | None = None`, When a
  caller supplies a value, Then it is accessible unchanged — the
  diagnosed slot's own live/historical forecast value, in the same
  units as `predicted`/`actual`.
- Given a new `DiagnosticFitInputs` frozen dataclass in
  `diagnostics/base.py` — fields: `fc_by_offset: Mapping[int,
  NDArray[np.float64]]`, `pv_by_offset: Mapping[int,
  NDArray[np.float64]]` (already training-corrected), `query_fc: float`,
  `target_cell_temperature: NDArray[np.float64] | None`,
  `coefficient_per_c: float`, `provider_already_corrects: bool`,
  `inverter_limit: float | None`, `smoothing_radius: int`,
  `neighbor_fitting_cutoff: float`, `recency_decay_max: float` — When a
  caller builds one from the exact values `coordinator.py`'s own
  `_fit_string`/`_apply_training_corrections` call sites already
  compute, Then every field is a direct, unconverted match (no new
  derivation logic invented here — this dataclass only carries values
  that already exist elsewhere in `coordinator.py`'s pipeline).
- Given `DiagnosticSlotSample.fit_inputs: DiagnosticFitInputs | None =
  None`, When a caller supplies one, Then
  `string_computation.fit_string_model`/`predict_string_forecast` can be
  called directly from its fields with no adapter/reshaping step in
  between (validates the shape end-to-end, ahead of `TASK-0015b`'s real
  caller).
- Given `DiagnosticMode`/`DiagnosticContext`/`DiagnosticResult`/
  `DiagnosticFitResult` (the other four `TASK-0015a` exports), When this
  patch runs, Then none of them change — only `DiagnosticSlotSample`
  gains fields, and `DiagnosticFitInputs` is added alongside it.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/diagnostics/base.py` (extended —
  `DiagnosticSlotSample.query_fc`/`.fit_inputs`, new
  `DiagnosticFitInputs`)
- `tests/test_diagnostics_base.py` (extended — new tests for the two
  fields and the new dataclass; existing tests untouched)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0015a and TASK-0017. -->
- `diagnostics.base.DiagnosticSlotSample` (pre-patch shape) from
  `custom_components/shady/diagnostics/base.py` (→ task: TASK-0015a)
- `string_computation.fit_string_model(fc_by_offset,
  corrected_pv_by_offset, smoothing_radius, neighbor_fitting_cutoff,
  recency_decay_max, method: str, *, apply_magnitude_weight: bool =
  True) -> FittedModel` and `string_computation.predict_string_forecast(
  model, fc, target_cell_temperature, coefficient_per_c,
  provider_already_corrects, inverter_limit) -> NDArray[np.float64]`
  from `custom_components/shady/string_computation.py` (→ task:
  TASK-0017) — exact parameter shapes, used verbatim to determine
  `DiagnosticFitInputs`'s own fields (one field per parameter these two
  functions need beyond the model itself: `fc_by_offset`, `pv_by_offset`
  (`corrected_pv_by_offset`, already training-corrected upstream by
  `string_computation.apply_training_corrections`), `query_fc` (`fc`),
  `target_cell_temperature`, `coefficient_per_c`,
  `provider_already_corrects`, `inverter_limit`, `smoothing_radius`,
  `neighbor_fitting_cutoff`, `recency_decay_max`).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
