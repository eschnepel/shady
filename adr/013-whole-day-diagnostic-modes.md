# ADR-013 – Diagnostics: Whole-Day Comparison Modes (Draft — Future Work, Not Yet Scheduled)

**Date:** 2026-08-30
**Status:** Proposed — no implementation task exists; this document exists
to validate ADR-004's amended `DiagnosticMode` base class (§1/§5,
Amendment 2026-08-30) against needs beyond the one mode ADR-004 actually
specifies, and to capture the design thinking now, while fresh, rather
than re-deriving it whenever this is eventually scheduled.

---

## Context

ADR-004's `CompareRegressionsMode` compares the four `regression/`
strategies against reality for **one** slot at a time (the auto-tracked
"last complete slot," or a manually pinned one, ADR-004 §2a). During the
same design review that produced ADR-004's 2026-08-30 amendment (replacing
its boolean switch with a `select` dropdown and a `DiagnosticMode` base
class), two further comparison ideas came up, both sharing ADR-004's
general shape — "compute a per-source prediction, compare it to reality,
show accuracy" — but at **whole-day** granularity (all 288 slots) instead
of one:

- **Compare regression methods across a full day, one provider.** The
  same four-method comparison ADR-004 §2 already does for one slot,
  repeated for every slot of a day — answering "how did each method do
  today, overall," not just "how did each method do at this one moment."
- **Compare providers across a full day, one regression method.** Instead
  of varying the regression method, vary the baseline **provider**
  (ADR-012) feeding a fixed regression method, across every slot of a
  day — answering "would a different forecast source have produced a
  better-fitted result today," holding the fitting strategy constant.

Neither is scheduled — no task exists, no acceptance criteria have been
written, and no decision is made here about rendering (a day-long
line/bar chart is the likely shape, but that is explicitly not decided in
this document). This ADR's only real claim is architectural: **both fit
inside ADR-004's `DiagnosticMode` base class as written, with no change
to `diagnostics/base.py`.**

---

## Decision

### 1 — Both are `DiagnosticMode` subclasses, unchanged base class

Both modes are additional entries in `coordinator.py`'s `_DIAGNOSTIC_MODES`
registry (ADR-004 §5) and additional `const.py` `DIAGNOSTIC_MODES` option
strings — nothing else about the select entity, the sensor dispatch, or
`diagnostics/base.py` changes. Concretely, sketched (not committed) names:
`"compare_regressions_daily"` and `"compare_providers_daily"`.

The only shape difference from `CompareRegressionsMode` is **cardinality**,
already accommodated by ADR-004's `DiagnosticContext.samples` being a
`Sequence[DiagnosticSlotSample]` rather than a single sample: a whole-day
mode's `compute()` receives 288 `DiagnosticSlotSample` entries (one per
5-minute slot) instead of 1. Each sample's `predicted` mapping is keyed by
method name for the first sketched mode, or by provider name for the
second — exactly the same field ADR-004's `CompareRegressionsMode` already
populates by method name, just with a different key vocabulary. Neither
sketched mode needs `pool` (ADR-004 §2's historical scatter data) — a
288-point day view has no single "training pool" to plot per slot the way
one diagnosed slot does — so both simply leave it `None` per sample, which
`DiagnosticSlotSample.pool`'s existing `| None` type already allows.

### 2 — Accuracy: same function, no new one needed

Both modes call `aggregation.py`'s existing accuracy function (ADR-004 §5:
`1 - |predicted - actual| / actual`, clamped to `[0, 1]`) once per slot,
per compared source — the same function `CompareRegressionsMode` already
calls once, per method, per diagnosed slot. This is exactly why ADR-004's
amendment kept that function in `aggregation.py` rather than moving it
into `diagnostics/compare_regressions.py`: a mode-independent, scope-
independent definition needs no change to serve a caller with 288 slots
instead of 1, or one keyed by provider name instead of method name.

### 3 — Extra fitting cost is real and unaddressed here

- **`compare_regressions_daily`** would need `regression/`'s three
  non-default strategies fitted for **all 288 slots**, not the one
  diagnosed slot ADR-004 §4 bounds its cost to — a materially larger
  `extra_fit()` cost (roughly 4× the *entire* recalibration sweep, not 4×
  one slot). Whether this needs its own opt-in gate beyond the select
  itself, a lower refresh cadence, or a hard string-count limit is an open
  question this document deliberately does not resolve.
- **`compare_providers_daily`** would need however many candidate
  providers a person configures fitted against the same regression method
  for all 288 slots — cost scales with the number of alternate providers
  compared, a dimension `CompareRegressionsMode` doesn't have at all
  (it always compares exactly the four built-in strategies, never a
  configurable set). How a person would select *which* alternate
  providers to compare is itself undesigned — this may need its own
  config-flow or service-based selection mechanism, not just a select
  option.

Both are flagged as real, unresolved cost/design questions for whenever
this is actually scheduled — not silently assumed away by this document.

### 4 — Rendering shape is explicitly undecided

ADR-004 §2's `series`/`accuracy` ApexCharts-scatter shape is specific to
comparing predictions against one real point per source. A whole-day
comparison likely wants a day-long line or bar chart (accuracy or
predicted-vs-actual per slot, per compared source) instead — but the
exact `DiagnosticResult.attributes` shape for either sketched mode is not
designed here. `DiagnosticResult` (ADR-004 Amendment) already permits
this: it is an opaque `state`/`attributes` pair, not a scatter-specific
contract — a future mode's `compute()` can return whatever attribute
shape suits a day view without touching `diagnostics/base.py`.

---

## Consequences

- **Pro:** Validates that ADR-004's 2026-08-30 base-class redesign does
  not need to be revisited when either sketched mode is actually built —
  the cardinality generalization (`samples: Sequence[...]`) was worth
  doing now specifically because of this document's existence.
- **Pro:** Confirms `aggregation.py`'s accuracy function was correctly
  kept mode-independent — both sketched modes reuse it unmodified.
- **Con:** This ADR makes no scheduling commitment and resolves none of
  §3's real cost questions or §4's rendering shape — a future Lead Agent
  picking this up still has substantial design work to do before a task
  file could be written for either mode.
- **Con:** `compare_providers_daily`'s "which alternate providers to
  compare" selection mechanism is a genuinely new config surface with no
  precedent in ADR-009/ADR-010's existing provider-selection design
  (single default + optional per-string override, never an ad-hoc
  comparison set) — likely the larger of the two sketched modes' open
  problems, understated by how similar it looks to
  `compare_regressions_daily` in this document's §1.
