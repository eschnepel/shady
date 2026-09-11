# Audit Task: Diagnostics Package (Round 2)

- **Status:** review
- **Group:** `custom_components/shady/diagnostics/*.py` (`base.py`,
  `compare_regressions.py`)
- **Related ADRs:** [ADR-004, ADR-012 §1, ADR-013 §1, ADR-014, ADR-000 §3]
- **Source Tasks:** \[TASK-0012-diagnostics-comparison-engine,
  TASK-0027-module-diagram-and-docstring-accuracy\]

## Scope

Re-audits round 1's `AUDIT-0008-diagnostics-package` (clean pass, no FAIL, no
gap). `diagnostics/*.py` has zero byte changes since round 1 (confirmed via
`git diff --stat f7fcef8 HEAD`). This pass's finding was surfaced by the
exhaustive import-graph trace (`tasks/AUDIT-INDEX.md` §"What round 2 actually
did," step 4), which this group's own file directly falsifies.

## Findings — Code Logic vs. ADRs

- **NEW FINDING — ADR-000 §3's prose claim that `coordinator.py` is "the only
  module that imports `cache.py`" is false.** `adr/000-coding-standards.md` line
  183 states this explicitly, in the context of explaining why `cache.py` isn't
  shown with multiple incoming edges. It is contradicted by this group's own
  code: `diagnostics/compare_regressions.py:52` reads
  `from ..cache import SLOTS_PER_DAY`. This is a real, direct import of
  `cache.py` from a module other than `coordinator.py` — confirmed by re-reading
  the full import block at the top of `compare_regressions.py` and by the
  earlier repo-wide `grep -rn "from \.\.cache\|from \.cache\|import cache"` pass
  across `custom_components/shady/`, which returns exactly two hits:
  `coordinator.py` and `diagnostics/compare_regressions.py`. The diagram itself
  is consistent with the false prose (no `diagnostics --> cache` edge is drawn),
  so both the sentence and the picture need the same fix. This is a narrow,
  low-risk import (`SLOTS_PER_DAY` is a plain module-level integer constant, not
  the `Cache` class or any stateful accessor — using it from `diagnostics/` does
  not bypass any encapsulation boundary the way the round-1 `AUDIT-0009` finding
  about direct `sensor.py` access did), so this is a documentation-accuracy fix,
  not an architectural violation requiring a design decision. **Proposed fix
  (single reasonable path):** correct the ADR-000 §3 prose to acknowledge
  `diagnostics/compare_regressions.py`'s narrow `SLOTS_PER_DAY` import (e.g.
  rephrase to "the only module that imports the `Cache` class itself" if that
  narrower claim is true, or drop the "only module" framing entirely and just
  list `cache.py`'s two real importers), and add the missing
  `diagnostics --> cache` edge to the diagram.
- No other deviations found. `compare_regressions_for_string`'s comparison
  methodology (ADR-004, ADR-012 §1, ADR-013 §1) and its
  `predict_string_forecast` call site (re-confirmed under `AUDIT-0018`) match
  round 1's confirmed reading.

## Findings — Test Coverage vs. ADRs

- No new gap found. `tests/test_diagnostics_compare_regressions.py`,
  `tests/test_diagnostics_base.py` re-run live this session as part of the full
  suite — passing. Round 1 found this group's coverage clean; unchanged.

## Open Questions

None.

## Definition of Done (for Phase 8)

- `adr/000-coding-standards.md`'s §3 prose no longer claims `coordinator.py` is
  the only module that imports `cache.py`, rephrased to accurately reflect both
  real importers (`coordinator.py`, `diagnostics/compare_regressions.py`) or
  narrowed to the specific true claim (only `coordinator.py` holds a `Cache`
  instance / calls its instance methods)
- The §3 diagram gains a `diagnostics --> cache` edge
- Full test suite still green; no `.py` file expected to change
  (documentation-only fix)
- `Delivered Artifacts` block below completed and accurate

## Delivered Artifacts

<!-- Filled by the Worker during Phase 8. -->
