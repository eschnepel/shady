# Task Index

## Task Table

| Slug | Title | Status | Dependencies | Worker |
|------|-------|--------|--------------|--------|
| TASK-0001-provider-base-architecture | Provider Base Architecture | done | — | — |
| TASK-0002-cache-core-time-series-store | Cache Core — Time-Series Store & Contiguous-Range Accessor | done | — | — |
| TASK-0003-baseline-forecast-discovery | Baseline Forecast Discovery & Normalization | done | TASK-0001 | — |
| TASK-0004-temperature-source-provider | Temperature Source Provider | done | TASK-0001 | — |
| TASK-0005-regression-fitting-pipeline | Regression Fitting Pipeline | done | — | — |
| TASK-0006-cache-batched-regression-pool-accessor | Cache — Batched Regression-Pool Accessor | done | TASK-0002 | — |
| TASK-0007-yield-corrections | Optional Yield Corrections (Clipping + Temperature Derating) | done | — | — |
| TASK-0008-forecast-adjustment | Forecast Adjustment | done | TASK-0005, TASK-0007 | — |
| TASK-0009-config-flow | Config Flow | done | TASK-0003 | — |
| TASK-0010-coordinator-recalibration-recompute-push | Coordinator — Recalibration, Recompute & Provider Push | done | TASK-0002, TASK-0006, TASK-0005, TASK-0007, TASK-0008, TASK-0003, TASK-0004 | — |
| TASK-0011-forecast-sensor-and-recalculate-button | Corrected Forecast Sensor & Manual Recalculation | done | TASK-0010 | — |
| TASK-0012-aggregate-sensors | Cross-String Aggregate Sensors | done | TASK-0011, TASK-0002 | — |
| TASK-0013-intraday-deviation-correction | Intraday Deviation Correction | done | TASK-0011, TASK-0008, TASK-0012 | — |
| TASK-0014-temperature-forecast-learned-model | Temperature-Forecast Learned Model | done | TASK-0005, TASK-0006, TASK-0004, TASK-0007, TASK-0010 | — |
| TASK-0015-diagnostics-switch-and-scatter-sensors | Diagnostics — Switch & Scatter/Accuracy Sensors | done | TASK-0002, TASK-0006, TASK-0010, TASK-0011, TASK-0013 | — |

### Parallelization notes (Phase 3 will confirm at readiness time)

- **Wave 1 (no dependencies, fully parallel):** TASK-0001, TASK-0002,
  TASK-0005, TASK-0007.
- **Wave 2 (unlocked once Wave 1's relevant deps are `done`):**
  TASK-0003, TASK-0004 (both need only TASK-0001); TASK-0006 (needs only
  TASK-0002, but is **sequential** with it — same file, `cache.py`);
  TASK-0008 (needs TASK-0005 + TASK-0007).
- **Wave 3:** TASK-0009 (needs TASK-0003); TASK-0010 (needs the full
  pure-layer stack — TASK-0002/0003/0004/0005/0006/0007/0008).
  TASK-0009 and TASK-0010 do **not** share a file/interface and can run
  in parallel with each other.
- **Wave 4:** TASK-0011 (needs TASK-0010 only — does **not** need
  TASK-0009; `config_flow.py` has no downstream code-level consumers in
  this graph, only a shared data-key contract already fixed by ADR-010).
- **Wave 5:** TASK-0012 (needs TASK-0011).
- **Wave 6:** TASK-0013 (needs TASK-0011, TASK-0008, and TASK-0012 —
  the last is a shared-file sequencing dependency on `coordinator.py`/
  `cache.py`, not a true interface consumption).
- **Wave 7:** TASK-0014 (needs TASK-0005/0006/0004/0007/0010 — can run
  parallel to Wave 5/6 once its own deps are satisfied, since it touches
  no file TASK-0012/0013 also touch until it lands in `coordinator.py`
  — **recheck for coordinator.py overlap with TASK-0013 at Phase 3
  readiness time** before actually parallelizing); TASK-0015 (needs
  TASK-0002/0006/0010/0011/0013 — explicitly sequenced after TASK-0013
  for its 5-minute-trigger reuse).

## Refinement Log

| Date | Trigger task | Action | Reason |
|------|-------------|--------|--------|
| 2026-08-20 | (Phase 2 initial planning) | Split `cache.py`'s delivery into three sequential tasks (TASK-0002 core, TASK-0006 batched regression-pool accessor, TASK-0015's pinned-slot-pool addition) instead of one monolithic cache task | Mirrors ADR-007a/ADR-008/ADR-004's own documented pattern: "each [accessor] gets its own purpose-built accessor... defined alongside its one caller" — keeps each task reviewable and lets TASK-0002 unblock nearly everything else immediately instead of waiting for the full three-accessor cache design |
| 2026-08-20 | (Phase 2 initial planning) | Added TASK-0012 as an explicit dependency of TASK-0013 beyond its functional need (TASK-0011 only) | Both tasks add a new coordinator.py schedule/trigger and touch cache.py; sequenced to avoid concurrent modification of the same files even though there is no real interface dependency between the two features (ADR-005 and ADR-006 are functionally independent) |
| 2026-08-20 | (Phase 2 initial planning) | Confirmed TASK-0011 does *not* depend on TASK-0009 (config flow) | `config_flow.py` produces `ConfigEntry.data` by keys ADR-010 already fixes; no module in this project imports `config_flow.py`'s classes, so there is no code-level Consumed/Delivered Artifact relationship — only a shared, already-frozen data contract. This lets config flow proceed fully in parallel with the coordinator/sensor chain. |
