# Task: Patch — Consolidate `predict()` into the `FittedModel` Base Class

- **Status:** done
- **Related ADRs:** [ADR-000 §4]
- **Dependencies:** [TASK-0005-regression-fitting-pipeline, TASK-0005-patch-2-unclamped-predict]

## Goal
Scenario C patch (Phase 6): TASK-0005 and TASK-0005-patch-2 are `done`
and not reopened. Human-directed observation: after `TASK-0005-patch-2`
introduced `predict_unclamped()`, every one of the four strategies'
`predict()` bodies became byte-for-byte identical —
`clamp_to_forecast(*predict_unclamped(fc)), confidence` — duplicated
verbatim in `linear.py`, `wls2.py`, `wls3.py`, and `kernel.py`. This task
collapses that duplication: `FittedModel` becomes a real base class
(`ABC` + `@abstractmethod`, the same pattern `providers/base.py`'s
`Provider` already establishes) with `predict()` implemented once,
concretely, on the base; only `predict_unclamped` — genuinely
strategy-specific — remains abstract. Every concrete strategy now
inherits from `FittedModel` instead of merely satisfying it
structurally.

## Acceptance Criteria
- Given `custom_components/shady/regression/base.py`, When inspected,
  Then `FittedModel` is `class FittedModel(ABC)` (not `Protocol`), with
  `predict_unclamped` as `@abstractmethod` and `predict` implemented
  concretely, calling `self.predict_unclamped(fc)` then
  `clamp_to_forecast`.
- Given `linear.py`, `wls2.py`, `wls3.py`, `kernel.py`, When inspected,
  Then none of them defines its own `predict()` any more — each
  `<Name>FittedModel` dataclass inherits `FittedModel` and implements
  only `predict_unclamped`.
- Given the existing `tests/test_regression.py` suite (16 tests,
  unmodified), When run against the patched modules, Then all still
  pass — `predict()`'s observable behavior is unchanged, only its
  location moved.
- Given `mypy --strict`, When run against the patched files, Then it
  reports zero issues.
- Given `tests/test_forecast_adjust.py`'s hand-written stub models
  (`TASK-0008`'s own test file), When updated to actually inherit the
  now-concrete `FittedModel` base class (rather than merely duck-typing
  it), Then `TASK-0008`'s existing 12 test assertions still pass
  unmodified — this task also updates that file, since it is the one
  other place in the codebase constructing a stand-in `FittedModel`, but
  changes no assertion, only the stub's declared base class.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/regression/base.py`
- `custom_components/shady/regression/linear.py`
- `custom_components/shady/regression/wls2.py`
- `custom_components/shady/regression/wls3.py`
- `custom_components/shady/regression/kernel.py`
- `tests/test_forecast_adjust.py` (stub classes only, no assertion changes)

## Definition of Done
- Tests green (`tests/test_regression.py` unmodified,
  `tests/test_forecast_adjust.py` assertions unmodified) · docs updated
  · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
  (none expected)

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0005 / TASK-0005-patch-2. -->
- Every symbol TASK-0005 / TASK-0005-patch-2 delivered in
  `custom_components/shady/regression/*.py` — this patch changes
  `FittedModel`'s kind (`Protocol` → `ABC`) and moves `predict()`'s one
  implementation from four places to one; every other name/signature is
  unchanged.

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/regression/base.py` → `FittedModel` changed
  from `Protocol` to `class FittedModel(ABC)` (same `ABC` +
  `@abstractmethod` pattern as `providers/base.py`'s `Provider`).
  `predict_unclamped` is `@abstractmethod` (unchanged signature).
  `predict(self, fc: NDArray[np.float64]) -> tuple[NDArray[np.float64], NDArray[np.float64]]`
  is now a concrete method on the base — `raw, confidence =
  self.predict_unclamped(fc); return clamp_to_forecast(raw, fc),
  confidence` — shared by every strategy, not overridden by any of
  them. `clamp_to_forecast`/`passthrough_where_no_confidence` are
  unchanged.
- `custom_components/shady/regression/linear.py` →
  `LinearFittedModel(FittedModel)` (now inherits); its own duplicate
  `predict()` removed; `predict_unclamped` unchanged. Unused
  `clamp_to_forecast` import removed.
- `custom_components/shady/regression/wls2.py` → `Wls2FittedModel(FittedModel)`,
  same change.
- `custom_components/shady/regression/wls3.py` → `Wls3FittedModel(FittedModel)`,
  same change.
- `custom_components/shady/regression/kernel.py` → `KernelFittedModel(FittedModel)`,
  same change (`predict_unclamped`'s locally-weighted-average body is
  unchanged, only `predict()` was removed).
- `tests/test_forecast_adjust.py` (TASK-0008's own test file, updated
  incidentally) → `_StubModel` now inherits `base_mod.FittedModel`
  directly and no longer defines its own `predict()` — it inherits the
  real, shared implementation, so
  `TestNoConfigMatchesClampedPredict.test_output_equals_predict_exactly`
  now cross-checks `adjust_forecast` against the actual production
  `predict()` code path, not a hand-rolled duplicate of it.
  `_AssertingStub` also inherits `base_mod.FittedModel` but still
  overrides `predict()` (must still raise, to prove `adjust_forecast`
  never calls it) — overriding an inherited concrete method is
  intentional here, not an oversight. Both carry a
  `# type: ignore[name-defined,misc]` on the class statement: `_load()`
  returns a plain `ModuleType`, so `base_mod.FittedModel` is `Any` to
  mypy, and mypy specifically disallows subclassing an `Any`-typed
  expression regardless of `mypy.ini`'s strictness settings — a
  structural limitation of the dynamic-loading convention every test
  file here already uses (ADR-000 §6), documented inline in the test
  file. No assertion changed; all 12 of TASK-0008's tests pass
  unmodified.
- **Also fixed as a direct side effect of this change:** two `.pyc`
  files under `__pycache__/` were being tracked in git (pre-existing,
  unrelated to this patch's actual content, but produced diff noise
  when this patch's own test runs recompiled them). Added
  `.gitignore` (`__pycache__/`, `*.pyc`, `.pytest_cache/`,
  `.mypy_cache/`, `.ruff_cache/`) and untracked all previously-tracked
  `__pycache__` contents repo-wide via `git rm -r --cached`. No source
  file content affected.
- External dependencies added: none.
- CI gate: `mypy --strict` (0 issues, 26 files), `ruff check` + `ruff
  format --check` (clean, scoped to the files this patch touched — the
  rest of the tree includes pre-existing `providers/` files written
  against Python 3.14-only syntax that this sandbox's 3.12.3 `ruff`
  install would otherwise "reformat" incorrectly; left untouched),
  `pytest` — `tests/test_regression.py`'s 16 tests and
  `tests/test_forecast_adjust.py`'s 12 tests both pass unmodified; full
  suite 128/128.
