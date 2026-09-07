# Findings: AUDIT-0008 — Diagnostics Package

**Auditor:** Lead Agent (inline, single-pass)
**Date:** 2026-09-06
**Verdict:** PASS on every criterion checked. No FAIL. This is the
most heavily-amended ADR in the project (five amendments) and the
code matches the *final* (2026-09-03) shape throughout — no leftover
references to any pre-amendment mechanism found anywhere in the
audited files. The one required special check — whether
`TASK-0015a-patch-1` is genuinely superseded rather than silently
still-needed — is a clean, triply-corroborated PASS (see dedicated
section below). Two minor scope-boundary notes (not findings): part of
§2a's behavior and the mypy suppression-list question resolve to code
outside this audit's own declared Source Files, and are answered by
briefly reading those adjacent files rather than by anything inside
`diagnostics/`. One coverage item is COVERED, but by tests living in
`test_coordinator.py`/cache test files rather than in this audit's own
Scope Test Files — noted, not treated as a gap, for the same reason
AUDIT-0007 gave for its analogous cases.

## Required check: is `TASK-0015a-patch-1` genuinely superseded?

**Yes — triply corroborated, not resolved on inspection alone.**

1. **The task file says so itself.** `tasks/TASK-0015a-patch-1-diagnostic-fit-inputs.md`'s own header: *"SUPERSEDED — 2026-09-01, no code written for this task... rather than threading fit inputs through `DiagnosticContext` per call as this task specifies, `DiagnosticMode` now receives the owning `ShadyCoordinator` at construction and gathers what it needs directly... `TASK-0015a-patch-2` doesn't just supersede this task's approach, it deletes the class this task would have extended — `DiagnosticSlotSample` and `DiagnosticContext` are removed from `diagnostics/base.py` entirely."*
2. **The ADR agrees.** ADR-004 §5's second Amendment (2026-09-01) describes exactly this: dropping the `DiagnosticContext` parameter and giving every mode a construction-time `ShadyCoordinator` reference instead.
3. **The code agrees, independently verified by this audit, not by trusting the above two claims.** `grep -n "DiagnosticContext\|DiagnosticSlotSample\|query_fc\|fit_inputs"  diagnostics/base.py diagnostics/compare_regressions.py` finds nothing — neither name exists anywhere in either file. `diagnostics/base.py`'s actual `DiagnosticMode.__init__(self, coordinator: "ShadyCoordinator") -> None` (`:78-84`) stores `self._coordinator` directly; `compute()`/`extra_fit()` are zero-argument (`:86-104`). `CompareRegressionsMode._gather_pool`/`_predict_all_methods` (`compare_regressions.py:79-176`) pull raw fit inputs — the exact thing patch-1 would have delivered — straight from `self._coordinator.cache.get_pinned_slot_pool(...)`/`self._coordinator.target_cell_temperature_for_slot(...)`/`self._coordinator.string_computation_config()`, on demand, with no DTO anywhere in the call chain.

Additionally, `test_diagnostics_base.py` contains a test class
literally named for this history —
`TestDiagnosticContextRemoved`/`TestComputeAndExtraFitTakeNoArguments`
(`:70-93`) — assert `not hasattr(module, "DiagnosticContext")` and
inspect `compute`'s signature has no parameters beyond `self`,
directly guarding against a regression back toward patch-1's shape.

**Conclusion: TASK-0015a-patch-1's intended functionality was
genuinely delivered — just via a completely different mechanism
(direct coordinator pull inside `compute()`/`extra_fit()`) than the
one it specified (a `DiagnosticContext` DTO). Its `SUPERSEDED` marking
is accurate, not a task-file claim left unverified.**

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
|---|---|---|---|
| 1 | §1 (2026-08-30 amendment): no leftover `switch.py`/boolean diagnostic entity | PASS | `find . -iname switch.py` finds nothing in the whole repo; the only reference to "switch.py" anywhere in `custom_components/` is `select.py`'s own docstring explicitly noting its absence ("there is no `switch.py` anywhere in this..."), i.e. the code itself documents the amendment rather than silently having stale references. |
| 2 | §2/§2b: per-string identity threaded correctly, no cross-string mixing, sum entry independent | PASS | `CompareRegressionsMode.sensor_ids()`/`compute()` loop over `self._coordinator.strings()` once per configured string, each producing a `_StringDiagnostic` with `sensor_id=str(string_index)` (`compare_regressions.py`, confirmed via `TestSensorIdsDeclaredWithoutComputing.test_one_id_per_string_plus_sum` — exactly `n_strings + 1` ids, the `+1` being `"sum"`). `TestSumEntryDayAlignment`'s two tests specifically regression-guard the sum entry against a real, previously-shipped bug (summing values from misaligned days across strings) — not a synthetic edge case. |
| 3 | §2a: manual slot-selection timestamp validation, out-of-range handling | PASS, **but implemented outside this audit's declared Scope Source Files** | `pin_diagnostic_slot` (`coordinator.py:907`) and its caller, the `shady.select_diagnostic_slot` service handler (`__init__.py:147-176`), carry this behavior — confirmed the handler raises `ServiceValidationError` naming every rejecting config entry when `pin_diagnostic_slot` returns `False` (beyond-forecast-horizon), rather than crashing or silently no-op'ing. Neither `diagnostics/base.py` nor `diagnostics/compare_regressions.py` contains any timestamp-validation logic at all — by design, this behavior belongs entirely to `coordinator.py`/`__init__.py` (correctly out of AUDIT-0008's Scope Source Files, which list only the two `diagnostics/*.py` files plus the empty `diagnostics/__init__.py`). Verified by briefly reading the adjacent files, the same shallow-cross-check pattern AUDIT-0006/0007 used for adjacent-but-out-of-deep-scope files. |
| 4 | §3: historical-pool cache refresh happens at midnight/system start, not every tick | PASS, **verified via a test in a different file's scope, not duplicated here** | Neither `diagnostics/base.py` nor `compare_regressions.py` contains any refresh-gating logic of its own — `_gather_pool` calls `self._coordinator.cache.get_pinned_slot_pool(...)` unconditionally on every `extra_fit()` invocation, by design (ADR-004 §3's own text: "the same call whether currently pinned or auto-tracking"). The actual no-refire guarantee is `cache.py`'s validated-range mechanism, proven directly by `tests/test_cache_pinned_slot_pool.py::TestAlreadyValidatedWindow::test_already_validated_window_triggers_no_new_fetch` — two calls to `get_pinned_slot_pool` within the same validated window produce `len(calls) == 1` (a genuine fetch-count spy, not an output check). This test lives in AUDIT-0003's territory, correctly — `diagnostics/` has nothing to test here of its own. |
| 5 | §4: extra fitting cost only while `compare_regressions` is active, not merely hidden from display | PASS, confirmed with a genuine call-count spy | `coordinator.py`'s `_diagnostics_tick_sync` (`:1682-1700`) does `mode = self._diagnostic_modes.get(self._active_diagnostic_mode); if mode is None: return` — a real early return, not a display-only gate. `tests/test_coordinator.py::TestDiagnosticResultCaching::test_off_by_default_returns_none_without_calling_compute` uses a purpose-built `_CountingDiagnosticMode` spy and asserts `fake_mode.compute_calls == 0` when off — proving the extra computation itself never runs, not just that its result is hidden. (Lives in `test_coordinator.py`, outside this audit's own Scope Test Files, same pattern as Criterion 4 above.) |
| 6 | §5 (final, 2026-09-03 amendment): module responsibility split — `diagnostics/` computes, `coordinator.py`/`cache.py` persist and dispatch | PASS | `diagnostics/base.py`'s `DiagnosticMode` never imports `cache.py` or persists anything itself — `compute()`/`extra_fit()` are pure computations returning `DiagnosticResult`/`DiagnosticFitResult` value objects; `_compute_sensor` (`compare_regressions.py:176`) *reads* `self._coordinator.cache.diagnostic_fit(sensor_id)` (persisted by `coordinator.py` after a prior `extra_fit()` call) but never writes to the cache itself — the read/write asymmetry matches the amendment's split exactly. |
| 7 | ADR-000 §3/§6 cross-ref: package correctly described as no longer zero-mocked, tests use a real coordinator where the ADR says purity was dropped | PASS | `tests/test_diagnostics_compare_regressions.py` imports and constructs a real `ShadyCoordinator`/`FakeHomeAssistant` via `tests.test_coordinator`'s own harness (`import tests.test_coordinator as tc`, throughout) — genuinely not zero-mocked, matching the amendment. `tests/test_diagnostics_base.py` correctly stays with a minimal hand-rolled stub coordinator instead (its own module docstring explicitly notes this is deliberate — it only exercises the base class's own shape, not real coordinator interaction — and that a future test needing real behavior should switch to the heavier convention). Two different, correctly-reasoned choices, not an inconsistency. |
| 8 | ADR-000 §3/§6 cross-ref: does `mypy.ini`'s per-file HA-stub suppression list correctly account for the loss of purity? | PASS — correctly needs **no** entry, confirmed empirically | `mypy.ini`'s `warn_unused_ignores = False` suppression list exists specifically for modules that subclass untyped HA entity base classes (`config_flow`, `sensor`, `coordinator`, `select`, `button` — its own comment says so explicitly). Neither `diagnostics/base.py` nor `diagnostics/compare_regressions.py` subclasses any HA entity — they hold a `TYPE_CHECKING`-only reference to the fully-typed, project-owned `ShadyCoordinator` and call its public methods, a different kind of "impurity" (runtime coupling, not untyped-decorator coupling) that doesn't need this particular suppression. Ran `mypy --config-file mypy.ini` directly against both files during this audit: **"Success: no issues found in 2 source files"** with zero suppressions — corroborating (not conclusive: the real `homeassistant` package is not installed in this sandbox, so some transitively-typed surface may be weaker than in CI) but consistent with the reasoning above. |
| 9 | ADR-012 §1 cross-ref: shared-base-class pattern — one access mechanism, not per-mode reimplementation | PASS | `DiagnosticMode.__init__` (`base.py:78-84`) is the single place `self._coordinator` gets stored, in the base class, once — `CompareRegressionsMode` never re-derives or duplicates a coordinator reference of its own; it inherits the one the base class already holds. |
| 10 | ADR-013: no premature implementation of the still-Proposed whole-day comparison modes | PASS | `grep -rln "compare_providers_daily\|compare_regressions_daily\|WholeDay" custom_components/` finds only `diagnostics/base.py`, and only inside docstring prose explaining *why* the base class is shaped the way it is (citing ADR-013's *sketched*, not implemented, future mode) — no class, function, or constant implementing any whole-day mode exists anywhere in the codebase. Matches ADR-013's own `Status: Proposed — no implementation task exists`. |

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
|---|---|---|---|
| 1 | Test names/docstrings still map onto the *current* (post-fifth-amendment) responsibilities, not a pre-amendment shape | COVERED, unusually well | `test_diagnostics_base.py`'s `TestDiagnosticContextRemoved` and `TestDiagnosticStringResultNoLongerExported`-style tests (exact names confirmed via `grep -n "class Test"`, `:70,` `:150`-ish) explicitly name what was *removed*, correctly framing prior states as history, not as current behavior under test — the opposite of the stale-docstring risk this criterion is checking for. |
| 2 | A test would fail if `DiagnosticMode`'s `TYPE_CHECKING`-only coordinator reference became an unconditional import | COVERED, verified empirically during this audit, not merely asserted | This audit built a scratch copy of `diagnostics/base.py` with the `TYPE_CHECKING` guard removed (unconditional `from ..coordinator import ShadyCoordinator`) and attempted to load it the same way `test_diagnostics_base.py`'s own `_load()` helper does (file-path `importlib` load, no package context). Result: **`ModuleNotFoundError: No module named 'shady.coordinator'`** — immediate failure at module-load time. Since every test in the file shares this same loading mechanism, this regression would fail the *entire file's test collection*, not just one assertion — a strong, if indirect, guarantee. (Scratch copy only; no repository file was modified.) |
| 3 | Historical-pool no-refire-mid-tick guarantee, call-count style | COVERED, in a different file (see Audit Criterion 4) | `test_cache_pinned_slot_pool.py::test_already_validated_window_triggers_no_new_fetch` — see above. |
| 4 | Extra-fitting-cost gating, call-count/spy style, not just "different sensor data" | COVERED, in a different file (see Audit Criterion 5) | `test_coordinator.py::TestDiagnosticResultCaching::test_off_by_default_returns_none_without_calling_compute` and its five sibling tests in the same class (`test_multiple_reads_share_one_compute_call`, `test_tick_refreshes_the_cache`, `test_tick_skips_compute_when_compute_cadence_is_coarser`, `test_switching_mode_invalidates_the_cache`, `test_pinning_a_slot_invalidates_the_cache`) all use a purpose-built `_CountingDiagnosticMode` spy with `compute_calls`/`extra_fit_calls`/`call_order` counters — this is a notably thorough, dedicated spy-based test class, going well beyond the minimum the criterion asks for. |

## Live re-execution

`tests/test_diagnostics_base.py` requires no `homeassistant` install
(stub coordinator only) — re-ran live during this audit:

```
$ python3 -m pytest tests/test_diagnostics_base.py -q
22 passed
```

`tests/test_diagnostics_compare_regressions.py` imports
`tests.test_coordinator`, which requires the real `homeassistant`
package — not installed in this sandbox (a very large dependency to
add for a single audit task) and **not re-run live**; its correctness
was verified by full manual reading instead, cross-checked against
`string_computation.py`'s and `aggregation.py`'s already-live-verified
behavior (AUDIT-0006/0007) wherever this file calls into them.

## Candidate Follow-Ups (not created — proposed only)

1. **Not diagnostics-specific, noted in passing:** `mypy.ini`'s
   `python_version = "3.14"` line has extra quotes mypy itself rejects
   (`Invalid python version '"3.14"' (expected format: 'x.y')`),
   silently falling back to a default rather than enforcing 3.14
   semantics. Discovered incidentally while empirically checking
   Criterion 8 above. This is tooling/config, squarely AUDIT-0012's
   territory (Tooling & Release Config) — flagged here only because
   this audit happened to run mypy first; not otherwise investigated
   or acted on.
2. No diagnostics-specific follow-ups — every criterion resolved
   cleanly, with no FAIL and no coverage GAP found in this audit
   (unusual among AUDIT-0005 through AUDIT-0007, all of which found
   at least one FAIL or GAP — worth the human's attention as a
   positive data point, not just an absence of findings).

## Delivered Artifacts (for the task file)
- `tasks/AUDIT-0008-diagnostics-package-findings.md` (this file)
