# Task: Bounded Forward-Fill With Explicit Zeros for Gaps (Flat Nightly Forecast Plateau)

- **Status:** done
- **Related ADRs:** [ADR-012 §4 (Amendment 2026-10-02), ADR-009 §1a, ADR-001 §2]
- **Dependencies:** [TASK-0037-patch-3-forward-fill-pushed-baseline-series]

## Goal

Live report (human, in chat, with a screenshot and a diagnostic CSV export):
`ShadyForecastSensor` showed a flat, nonzero value for ~10 hours every night (50
W, 22 W, 14 W on consecutive nights) while the actual yield was 0. The export
for slot 68 (05:40 local) showed `fc_raw = 14.0` against 27 days of `0.0`.

Root cause: `_forward_fill_by_day` held each raw baseline sample forward until
the next sample — and the final sample through the end of the horizon. A PV
forecast provider that reports daylight samples only therefore had its last
evening value held across the night. Night slots have no shading-model evidence
(all history `FC == 0`, zero magnitude weight), so the cold-start passthrough
displays that `FC` unmodified, and the `[0, FC]` clamp cannot lower it. Started
after switching the baseline from a weather provider (hourly, night included)
back to the PV forecast provider.

Decision (human): emit explicit `0.0` for gaps. Recorded as ADR-012 §4 Amendment
2026-10-02.

## Acceptance Criteria

- Given a daylight-only series, when forward-filled, then every slot between the
  last evening sample's one-cadence hold and the next morning's first sample is
  `0.0`, and the morning sample itself is intact.
- Given a series whose first sample is more than one cadence after `start`, then
  `start` up to that sample is `0.0`; within one cadence it stays unfilled.
- Given the last sample of the series, then it is held for one cadence and
  nothing further is written.
- Given a provider that already emits explicit night zeros, then behavior is
  unchanged.
- Given fewer than two distinct timestamps, then the original hold-through-`end`
  behavior is kept.
- Given two samples straddling a night, then the hold is capped at 3 hours.
- Given `_push_provider_series`, then overnight slots in the cache are `0.0`.
- The full suite, `mypy`, `ruff check`, `ruff format --check` pass; new tests
  fail against the pre-fix code.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` — `_forward_fill_by_day`, new
  `_sample_cadence`/`_MAX_SAMPLE_HOLD`
- `tests/test_coordinator.py` — new coverage
- `adr/012-provider-architecture.md`, `adr/INDEX.md`, `tasks/adr-summary.md`

## Definition of Done

- Tests green (full suite: 790 passed) · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- No new external dependencies

## Consumed Interfaces

- `_forward_fill_by_day(series, start, end) -> dict[date, dict[int, float]]`
  (`custom_components/shady/coordinator.py`) — signature unchanged (→
  TASK-0037-patch-3)
- `Cache.index_for`/`Cache.timestamp_for` (`custom_components/shady/cache.py`) —
  unchanged

## Delivered Artifacts

- `custom_components/shady/coordinator.py` — `_forward_fill_by_day` (same
  signature) now bounded; new module-level `_MAX_SAMPLE_HOLD`
  (`timedelta(hours=3)`) and `_sample_cadence(ordered) -> timedelta | None`; new
  import `itertools.pairwise`.
- `tests/test_coordinator.py` — new `TestForwardFillEmitsZeroForGaps` (7 tests)
  and `TestPushedNightSlotsAreZero` (1 test).
- `adr/012-provider-architecture.md` — §4 Amendment 2026-10-02.
- `adr/INDEX.md`, `tasks/adr-summary.md` — updated to match.
- No external dependencies added.
