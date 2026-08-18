# ADR-003 – Optional Per-String Yield Corrections: Clipping and Derating

**Date:** 2026-07-04
**Status:** Superseded — split into ADR-003a and ADR-003b (2026-08-18)
**Superseded by:**
[ADR-003a – Inverter Clipping Exclusion](003a-inverter-clipping-exclusion.md),
[ADR-003b – Temperature Derating Correction](003b-temperature-derating-correction.md)

---

## Revision note

This document originally specified both of Shady's optional per-string
yield corrections — inverter clipping exclusion (§1/§1a) and temperature
derating (§2/§2a/§2b/§2c) — together, because both are optional, both
are a mix of global/per-string configuration, and both live in the same
`yield_correction.py` module. On review, the two were found to be
independently optional, independently configured, and to share no
decision-relevant logic beyond that module placement — exactly the kind
of separable concern ADR-001's own 2026-08-14/2026-08-17 splits (into
ADR-009, ADR-010, ADR-011) already established a precedent for.

Split on 2026-08-18 into:

- **ADR-003a** — inverter clipping exclusion (formerly §1/§1a)
- **ADR-003b** — temperature derating correction (formerly
  §2/§2a/§2b/§2c), which also retains this document's original
  module-placement discussion (formerly §3) and its shared-with-clipping
  framing, since derating's forward/reverse round-trip is what gives
  `yield_correction.py` its two-role shape in the first place

Unlike ADR-001's earlier splits, which each extracted one separable
piece while leaving a core decision behind, this split moved this
document's entire content out — nothing remains here to be independently
"accepted" any more, hence this document's status is **Superseded**
rather than merely narrowed. No decision, default, or behavior changed
by the split. Every cross-reference throughout the ADR set that pointed
at this document's numbered sections has been updated to point at
ADR-003a or ADR-003b directly.
