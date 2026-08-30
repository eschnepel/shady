# Task: Patch — Optional `magnitude_weight_i` in `regression/base.py`'s `build_pool`

- **Status:** done
- **Related ADRs:** [ADR-001 §2, ADR-003c §2]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0005-patch-1-ndarray-typing, TASK-0005-patch-4-recency-weight]

## Goal
`regression/base.py`'s `build_pool` unconditionally computes and folds
in `magnitude_weight_i` (ADR-001 §2: continuous downweighting of
near-zero-`FC` samples, scaled against each row's own max valid `FC`).
ADR-003c §2 explicitly requires the temperature-forecast learned model
(`TASK-0014`) reuse `build_pool`'s fitting mechanics **without**
`magnitude_weight_i` — temperature has no equivalent near-a-particular-
value degeneracy, and, unlike `FC`, a temperature predictor is routinely
negative (below-freezing readings), which `_magnitude_weight`'s
`masked_fc / row_max` ratio does not handle correctly (a negative
`row_max` or a negative/positive sign mismatch between a row's samples
produces weights with the wrong sign, not merely "no-op downweighting"
— actively wrong, not just unwanted).

**Worker-discovered gap, found while filling `TASK-0014`'s own Consumed
Interfaces** (Scenario C — `TASK-0005` stays `done`, unreopened): the
task's Related ADRs commit to "no `magnitude_weight_i`" as an Acceptance
Criterion, but `build_pool`'s current signature has no way to satisfy
it. Made **optional**, defaulting to today's behavior (`True`), rather
than a second required positional parameter like
`TASK-0005-patch-4`'s `recency_decay_max` — every existing call site
(`coordinator.py`'s shading-model fit, every `tests/test_regression.py`
pool) wants `magnitude_weight_i` exactly as today and needs no edit at
all; only `TASK-0014`'s new, second `build_pool` call site opts out.

## Acceptance Criteria
- Given `apply_magnitude_weight` left at its default, When `build_pool`
  runs, Then output is byte-for-byte identical to pre-patch `build_pool`
  for every existing call site — this task's own regression guard
  (`tests/test_regression.py`'s existing cases pass unmodified, with no
  call site edited).
- Given `apply_magnitude_weight=False`, When `build_pool` runs, Then
  every offset's `magnitude_weight` term is `1.0` wherever `valid_mask`
  is `True` (i.e. `combined_weight` reduces to
  `time_weight * recency_weight * valid_mask`) — a sample's raw
  predictor value, including a negative one, never suppresses or
  distorts its own weight.
- Given `apply_magnitude_weight=False` and `smoothing_radius=0` (the
  shape `TASK-0014` actually uses, since ADR-011 §1/§2/§3 smoothing/
  exclusion is separately not reused there — no `build_pool` change
  needed for that part, since a single center-only offset never enters
  the neighbor-only code path), When `build_pool` runs, Then
  `combined_weight` reduces further to exactly `recency_weight *
  valid_mask` (`time_weight` is already `1.0` at offset `0` regardless).
- Given the `SamplePool.confidence` output, When
  `apply_magnitude_weight=False`, Then it still reflects
  `weight.sum(axis=1)` automatically (no separate formula needed).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/regression/base.py` — `build_pool` gains one
  new, last-position, keyword-only parameter,
  `apply_magnitude_weight: bool = True`; `_magnitude_weight`'s call in
  the per-offset loop is skipped (weight `1.0` under `valid_mask`) when
  `False`.
- `tests/test_regression.py` — a new small test class covering the
  `False` path; no existing call site edited (default preserves current
  behavior).

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
- `regression.base.build_pool`'s existing signature and `SamplePool`
  dataclass — already-`done`, same-module code this patch extends; no
  new external interface consumed.

## Delivered Artifacts
- `custom_components/shady/regression/base.py` → `build_pool` gains a
  new, last-position, keyword-only parameter
  `apply_magnitude_weight: bool = True`. Inside the per-offset loop,
  `magnitude_weight = _magnitude_weight(raw_fc, valid_mask) if
  apply_magnitude_weight else valid_mask.astype(np.float64)` — the
  `False` branch reduces the term to plain `0.0`/`1.0` under
  `valid_mask`, so it drops out of `combined_weight`'s product exactly
  like `time_weight=1.0` already does at offset `0`, with no other line
  in the loop touched (ADR-011 §2/§3's neighbor-exclusion block, which
  also writes into `magnitude_weight`, is untouched — it only executes
  for `offset != 0`, which `TASK-0014`'s own `smoothing_radius=0` call
  never reaches). No signature reordering; every existing positional
  call (`coordinator.py`, all of `tests/test_regression.py`) is
  unaffected since the new parameter is keyword-only with a
  behavior-preserving default. `SamplePool`, `FittedModel`, and every
  other public symbol unchanged.
- `tests/test_regression.py` → new `TestOptionalMagnitudeWeight` class
  (3 tests): `apply_magnitude_weight=False` yields `weight ==
  valid_mask` at `smoothing_radius=0` with a `recency_decay_max=0.0`
  control (isolating the one factor under test); a negative-valued
  predictor row (e.g. sub-freezing Celsius readings) produces a
  strictly positive, undistorted weight when `False` v.s. a
  sign-corrupted one under the pre-patch/`True` default — the concrete
  correctness bug this patch exists to prevent; and the default
  (omitted keyword) reproduces every pre-existing test's output
  unmodified. Full suite: 281/281 passing (278 pre-existing + 3 new).
  `mypy --strict` clean on `custom_components/` + `tests/`; `ruff check`
  clean; `ruff format --check` clean except the one pre-existing,
  unrelated `tests/test_regression.py` formatting nit already logged in
  `tasks/INDEX.md` (2026-08-29 entry, ruff-version drift, untouched by
  this patch).
- External dependencies added: none.
