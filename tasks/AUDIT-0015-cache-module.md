# Audit Task: Cache Module (Round 2)

- **Status:** review
- **Group:** `custom_components/shady/cache.py`
- **Related ADRs:** [ADR-007, ADR-007a, ADR-008 §2/§3]
- **Source Tasks:** \[TASK-0002-cache-core-time-series-store,
  TASK-0006-cache-batched-regression-pool-accessor,
  TASK-0021-fitted-model-cache-location,
  TASK-0023-entity-layer-cache-access-boundary\]

## Scope

Re-audits round 1's `AUDIT-0003-cache-module` FAIL, which is the single
highest-impact code change in the entire remediation batch — `cache.py` grew by
94 lines (`git diff --stat f7fcef8 HEAD`) to absorb the relocated fitted-model
cache. This is a genuine re-audit of new code, not just a staleness re-check.

## Findings — Code Logic vs. ADRs

- **Round-1 item — fitted-model cache location (RESOLVED, verified against live
  code).** `AUDIT-0003` found `self._models`/`self._temperature_models` living
  in `coordinator.py` as raw dicts, contradicting ADR-007 §1's "five things
  `cache.py` holds" list and ADR-007a §5's explicit storage-design text.
  `TASK-0021` recorded the human's decision (Option B, relocate, "including the
  validated range logic," later clarified to "midnight invalidates; fitting
  model updates over the day just refresh/push future slots") and delivered the
  relocation. Confirmed directly in the current file:

  - `cache.py:106` — `ModelKind = Literal["shading", "temperature"]`
  - `cache.py:259-260` —
    `self._models: dict[tuple[ModelKind, int], FittedModel]` and
    `self._models_valid: dict[tuple[ModelKind, int], bool]` constructed inside
    `Cache.__init__`, not `coordinator.py`
  - `cache.py:767` —
    `def get_model(self, kind: ModelKind, string_index: int) -> FittedModel | None`
  - `cache.py:781` —
    `def set_model(self, kind: ModelKind, string_index: int, model: FittedModel) -> None`
  - `cache.py:794` — `def invalidate_models(self) -> None`
  - `coordinator.py` no longer declares `self._models`/
    `self._temperature_models` anywhere (confirmed via
    `grep -n "_models\b" custom_components/shady/coordinator.py` — every
    remaining hit is a call through
    `self.cache.get_model`/`set_model`/`invalidate_models`, never a raw-dict
    field).
  - `adr/007-coordinator-cache-split.md:70-71` and
    `adr/007a-cache-storage-and-accessor-design.md` both now describe this shape
    as the as-built design (folded into main prose by the subsequent
    `Cleanup ADR NNN` pass rather than left as a standalone `## Amendment` block
    — confirmed content-preserving: ADR-007's own line 8 explicitly notes
    "fitted-model cache's relocation into `cache.py` is folded into §1 above").

  **PASS — this is a confirmed fix, not just a claimed one.**

- No new deviations found in `cache.py`'s other four stores (time-series
  three-state array, pinned-slot pool, regression-pool batch accessor, energy
  integrals) — unchanged since round 1, re-spot-checked.

- **Cross-reference, primary write-up in `AUDIT-0020-diagnostics-package`:**
  ADR-000 §3's prose claims "`coordinator.py`... the only module that imports
  `cache.py`" (line 183 of `adr/000-coding-standards.md`). This is false —
  `diagnostics/compare_regressions.py:52` does
  `from ..cache import SLOTS_PER_DAY`. Not a defect in `cache.py` itself (the
  constant is a legitimate public export), but the prose describing `cache.py`'s
  consumers is wrong. See `AUDIT-0020` for the full finding.

- **Cross-reference, primary write-up in `AUDIT-0017-coordinator`:** ADR-000
  §3's diagram draws a `cache --> aggregation` edge that doesn't correspond to
  any real import in either direction — `cache.py` imports only
  `.regression.base`; `aggregation.py` has zero internal imports. See
  `AUDIT-0017`.

## Findings — Test Coverage vs. ADRs

- `TASK-0021`'s own claimed test additions confirmed present:
  `tests/test_cache_core.py:404` — `class TestFittedModelCacheRoundTrip`;
  `tests/test_cache_core.py:438` — `class TestFittedModelCacheInvalidation`.
  Both exist with the claimed round-trip / cross-key-independence /
  invalidate-clears-every-key coverage. **COVERED** for the storage/retrieval
  contract itself.
- **New gap, primary write-up in `AUDIT-0017-coordinator`:** the *storage*
  layer's `invalidate_models()` is unit-tested in isolation
  (`TestFittedModelCacheInvalidation`), but no test proves `coordinator.py`
  actually calls it at the right *moment* to produce the intended behavior
  change (a previously-valid model going stale must be cleared, not silently
  kept, when a later refit fails for that string). That is a coordinator-level
  orchestration question, not a cache-storage question, so the fix belongs under
  `AUDIT-0017`'s task, touching `tests/test_coordinator.py` rather than
  `tests/test_cache_core.py`.
- All other cache-module tests (`tests/test_cache_pinned_slot_pool.py`,
  `tests/test_cache_regression_pools.py`) re-run live this session as part of
  the full suite — passing.

## Open Questions

None.

## Definition of Done (for Phase 8)

- N/A — no independent fix scheduled under this task. The one open coverage item
  is tracked under `AUDIT-0017` (it requires a `coordinator.py`-level test, not
  a `cache.py`-level one).

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8 — not applicable; see AUDIT-0017 and
     AUDIT-0020 for the fixes this group's findings feed into. -->
