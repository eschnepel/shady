# Consistency Issues Report - Shady ADR Documentation Review

**Date:** 2026-07-05  
**Status:** Draft for Validation  

---

## Executive Summary

This document catalogs inconsistencies found during a comprehensive review of all ADR files (ADR-000 through ADR-007). The issues span module architecture, cache management strategies, scheduling triggers, and configuration flow specifications. Each issue is documented with:
- Issue ID for tracking
- Affected documents
- Description of the inconsistency  
- Relevant section references

---

## Issue Catalog

### ISS-001: Module Diagram Conflict - yield_correction.py Architecture

**Affected Documents:** ADR-003, ADR-007  

**Description:**  
ADR-007's module diagram shows `yield_correction.py` as a pure logic module that only reads from `providers/`. However, ADR-003 explicitly describes it being used at two points in the pipeline (forward transform for training data preparation and reverse transform for prediction finishing). The diagrams are inconsistent about whether this is bidirectional or unidirectional.

**Section References:**  
- ADR-007 §1: Module diagram shows `yield_correction --> providers` only
- ADR-003 §3: Mermaid flowchart shows both forward and reverse edges with dashed line for prediction-time transform

**Impact:** Confusion about whether yield_correction.py is truly stateless or has bidirectional dependencies. Could affect unit test design assumptions in future work.

---

### ISS-002: Cache Persistence Scope Inconsistency

**Affected Documents:** ADR-005, ADR-007  

**Description:**  
ADR-005 §1 states that the running totals for energy integral sensors "live in `cache.py` — the one cache instance there that **is wired to Home Assistant's restore-state mechanism**, since losing it mid-day would visibly wrong-foot". However, ADR-007 §1 says "**Not every cache needs restart-persistence**... The other four caches are all safely rebuildable" without explicitly confirming which two need persistence. This creates ambiguity about whether only the integral totals persist or if there's a different set of persistent vs non-persistent caches than documented in ADR-005.

**Section References:**  
- ADR-005 §1: "the one cache instance there that is wired to Home Assistant's restore-state mechanism"
- ADR-007 §1: Lists five independent caches but only explicitly mentions integral totals as needing persistence, leaving the other four ambiguous about their restart behavior

**Impact:** Unclear which state survives a HA restart. Could lead to unexpected data loss or incorrect assumptions during debugging of mid-day failures.

---

### ISS-003: Dual Midnight Schedule Conflict

**Affected Documents:** ADR-002, ADR-005  

**Description:**  
ADR-002 §1 specifies the daily recalibration schedule as `async_track_time_change(hass, ..., hour=0, minute=1, second=0)` — one minute past midnight. However, ADR-005 §5 introduces a **fourth independent schedule**: `async_track_time_change(hass, ..., hour=0, minute=0, second=0)` for the energy integral reset at exactly midnight. The documentation states this is "deliberately not reusing either of those triggers" but provides no justification or explanation for why two schedules with only 1-minute difference are needed when they both operate on day boundaries.

**Section References:**  
- ADR-002 §1: `hour=0, minute=1`
- ADR-005 §5: "a fourth, independent schedule... hour=0, minute=0" — deliberately not reusing either trigger despite all being periodic coordinator things

**Impact:** Unnecessary complexity in the scheduler. If a restart occurs during this window (between 00:00 and 00:01), unclear which reset fires or if both could fire causing double-reset issues that aren't documented.

---

### ISS-004: Slot Pool Cache Refresh Timing Ambiguity

**Affected Documents:** ADR-004, ADR-006, ADR-007  

**Description:**  
ADR-004 §3 states the slot-pool series "are **not** refreshed on the 5-minute tick from §2, nor on ADR-002 §2's baseline-update trigger — only recalibration (or a restart priming it for the first time) changes what they show". However:
1. ADR-006 introduces a fourth scheduler trigger at 5 minutes for intraday correction window polling (§1)  
2. ADR-007 §2 states `coordinator.py` registers "four independent triggers" but doesn't clarify which of these four affect the slot-pool cache refresh
3. The documentation is unclear whether all four triggers cause a full recalibration (which would include pool refresh via get_slot_pool) or only two do

**Section References:**  
- ADR-004 §2a: "The 5-minute tick (§2's Refresh cadence)... for sensors currently auto-tracking"
- ADR-006 §1: Adds the 5-minute recorder-poll trigger
- ADR-007 §2: Lists four triggers but doesn't specify which affect cache refresh

**Impact:** Unclear when diagnostic slot pool data becomes stale. Could lead to users seeing outdated training pools in diagnostics while believing they're current, or conversely thinking new data is available when it's not.

---

### ISS-005: Temperature Flag Introduction Without Prior Specification

**Affected Documents:** ADR-001, ADR-003  

**Description:**  
ADR-003 §2c introduces a global config-flow field "does the configured baseline provider already account for temperature effects itself?" with default `false`. However, this flag is not mentioned in:
1. ADR-001's Config Flow specification (§6) which lists all settings but omits this field entirely  
2. The initial discovery process documentation (ADR-001 §5/§6)

This creates a gap where the config flow documented in one place doesn't match what actually gets presented to users, or vice versa — suggesting either ADR-003 was written after ADR-001's spec without updating it, or this field should have been part of the original design.

**Section References:**  
- ADR-001 §6: Config flow step "settings" lists global settings but no temperature flag
- ADR-003 §2c: Introduces the flag as a new setting without prior mention in config spec

**Impact:** Users following only ADR-001's documentation would not know about this important configuration option. Could lead to incorrect baseline handling if users assume default behavior when they should be aware of temperature modeling assumptions.

---

### ISS-006: Diagnostic Slot Selection vs Cache Refresh Conflict

**Affected Documents:** ADR-004, ADR-007  

**Description:**  
ADR-004 §2a states that slot-pool series "are **not** refreshed on the 5-minute tick from §2" and only change at recalibration. However:
1. ADR-007 §1d describes a validation function that queries missing ranges, including sensors "mostly valid, missing only a few recent slots... is queried only for the **missing tail**, in one call"  
2. This suggests partial refresh capability exists but isn't documented as being triggered by any of the four coordinator schedules
3. The documentation doesn't clarify whether manual pinning (ADR-004 §2a) affects cache validation or if pinned sensors bypass normal refresh logic

**Section References:**  
- ADR-004 §3: "The slot-pool series are **not** refreshed on the 5-minute tick from §2"
- ADR-007 §1d: Describes partial fetch for missing tail but doesn't specify trigger conditions

**Impact:** Unclear when diagnostic data actually refreshes. Could lead to stale diagnostics being displayed or unexpected recorder queries during normal operation that aren't documented in the user-facing docs.

---

### ISS-007: Baseline Provider Temperature Modeling Assumption Gap

**Affected Documents:** ADR-001, ADR-003  

**Description:**  
ADR-003 §2c states "This is a single, global flag... 'does the configured baseline provider already account for temperature effects itself?'" with default `false`. However:
1. The documentation doesn't specify which providers actually model temperature internally (Solcast mentioned as example) vs those that don't  
2. ADR-001 §5 describes attribute-shape discovery without mentioning any knowledge of the underlying provider's internal modeling assumptions  
3. Users discovering baselines via heuristics have no way to know if their chosen baseline already includes temperature correction

**Section References:**  
- ADR-003 §2c: Mentions Solcast as concrete example but doesn't provide a comprehensive list
- ADR-001 §5: Discovery process has "no reliable way to infer this on its own" per ADR-003, creating circular dependency

**Impact:** Users may incorrectly enable temperature correction for providers that already model it (double-counting) or disable it when needed. The documentation doesn't provide enough information about which common integrations fall into each category.

---

### ISS-008: Ramp State Persistence Documentation Gap

**Affected Documents:** ADR-006, ADR-007  

**Description:**  
ADR-006 §1a describes ramp state as "short-lived per-string record... discarded once the ramp completes and is not restart-persisted (unlike §1)". However:
1. ADR-007 lists five caches but doesn't explicitly categorize which are persistent vs non-persistent  
2. The documentation says ramp state lives in `cache.py` as "a simple dict store" but doesn't clarify whether this is the same cache instance that handles time-series data or a separate one
3. No clear distinction between what survives restart and what gets rebuilt

**Section References:**  
- ADR-006 §1a: "not restart-persisted (unlike §1, there is no recorder-backed equivalent to read instead)"
- ADR-007 §1: Lists five caches but only explicitly mentions integral totals as needing persistence

**Impact:** Unclear behavior during HA restarts. If ramp state isn't persisted and gets lost on every restart, users might see unexpected forecast jumps after system reboot that aren't documented in the recovery strategy.

---

### ISS-009: Confidence Definition Consistency Across Methods

**Affected Documents:** ADR-001  

**Description:**  
ADR-001 §2 states confidence is "defined independently of the chosen method, as the normalized sum of sample weights... no distance calculation in forecast-value space is needed for this (that would only matter for `kernel`'s own point estimate)". However:
1. The documentation doesn't clarify whether all four methods use identical confidence calculations  
2. ADR-004 §2 shows accuracy attribute with different values per method, suggesting they're computed separately despite the claim of independence  
3. No explicit formula or reference to shared implementation is provided

**Section References:**  
- ADR-001 §2: "Confidence is defined independently of the chosen method"
- ADR-004 §2 accuracy attribute shows different values per method but doesn't explain if this violates independence claim

**Impact:** Users may assume all methods have equal confidence when they don't, or conversely that switching methods changes confidence meaning (which it shouldn't). Could lead to misinterpretation of forecast reliability metrics.

---

### ISS-010: Neighbor Exclusion vs Rescaling Mode Documentation Gap

**Affected Documents:** ADR-001  

**Description:**  
ADR-001 §3c describes neighbor exclusion with `neighbor_fitting_cutoff` default 25%. Section §3d introduces sentinel value `-1%` for rescale mode. However:
1. The config flow documentation (ADR-001 §6) doesn't mention the sentinel value or how to specify it  
2. No clear guidance on when each mode is appropriate vs exclusion-only behavior  
3. Default values aren't clearly documented as being either 25% or -1%, creating ambiguity about which strategy ships by default

**Section References:**  
- ADR-001 §6: Lists "Neighbor-fitting cut-off (default 25%, global)" but doesn't mention sentinel value
- ADR-001 §3d: Introduces `-1%` as alternative without config flow documentation update

**Impact:** Users may not know how to enable rescale mode or what the default behavior actually is. Could lead to unexpected neighbor exclusion in installations where rescaling would be preferable, especially near shading boundaries.

---

## Summary Statistics

| Category | Count |
|----------|-------|
| Total Issues Identified | 10 |
| Module Architecture Conflicts | 2 (ISS-001, ISS-008) |
| Cache Management Inconsistencies | 3 (ISS-002, ISS-004, ISS-006) |
| Scheduling Trigger Issues | 2 (ISS-003, ISS-009*) |
*Note: ISS-009 is confidence definition but affects scheduling assumptions

| Document Affected Most Often | ADR-001 (5 issues), ADR-007 (4 issues) |
|-------------------------------|----------------------------------------|
| Documents with No Issues      | None identified                        |

---

## Next Steps Recommendation

Before proceeding to fix these inconsistencies:

1. **Prioritize by Impact:** Address ISS-002 and ISS-003 first as they affect core data persistence and scheduling behavior that users depend on daily  
2. **Cross-reference All Docs:** For each issue, verify against all affected documents before making changes  
3. **User Communication Plan:** Document any breaking changes in config flow or expected restart behavior separately from technical fixes  

---

## Appendix: Issue Tracking Reference

| ID | Category | Severity* | Affected Docs |
|----|----------|-----------|---------------|
| ISS-001 | Module Diagram | Medium | ADR-003, ADR-007 |
| ISS-002 | Cache Persistence | High | ADR-005, ADR-007 |
| ISS-003 | Schedule Conflict | High | ADR-002, ADR-005 |
| ISS-004 | Refresh Timing | Medium | ADR-004, ADR-006, ADR-007 |
| ISS-005 | Config Flow Gap | Low-Medium | ADR-001, ADR-003 |
| ISS-006 | Diagnostic Refresh | Medium | ADR-004, ADR-007 |
| ISS-007 | Provider Assumption | High | ADR-001, ADR-003 |
| ISS-008 | Ramp State Docs | Low-Medium | ADR-006, ADR-007 |
| ISS-009 | Confidence Definition | Medium | ADR-001, ADR-004 |
| ISS-010 | Mode Documentation | Low | ADR-001 |

*Severity: High = affects core functionality or user expectations; Medium = causes confusion but not functional issues; Low-Medium = documentation gaps that could cause edge-case problems


---

**End of Report**  
*Generated during consistency review - requires validation before any fixes are implemented*
