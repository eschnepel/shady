# Task: Patch — Make the CSV Export Sufficient to Recompute the Fit (Close the Replay Blind Spot)

- **Status:** done
- **Related ADRs:** \[ADR-015 (§2, §5, §5a, and the 2026-09-29 Amendment this
  task implements), ADR-014 (`string_computation.py` — the three functions the
  replay now runs for real), ADR-003a §1/§1a, ADR-003b §1/§1a/§1b/§1c (the
  correction parameters that were missing), ADR-001 §2, ADR-011 §1-§3, ADR-004
  §5 (`StringComputationConfig`), ADR-000 §6\]
- **Dependencies:** [TASK-0038-diagnostic-slot-raw-data-csv-export]

## Goal

`TASK-0038` shipped an export that a human can read, but not one from which the
*fit* can be recomputed: four per-string scalars that
`apply_training_corrections` / `predict_string_forecast` consume were never
written, `# predictions` were read from a cache that can belong to a different
tick than the pool beside them, and the fixture replay compensated by stubbing
`apply_training_corrections` and echoing `predicted` (ADR-015 §5a's "what a
replay can and cannot check"). This patch closes that: an export carries every
input needed to re-run correction → pool → fit (×4 strategies) → predict, and
the replay actually does so.

## Root cause (verified against the code, 2026-09-29)

| Fit-chain function | Input | In export before? |
| -- | -- | -- |
| `apply_training_corrections` | `converter_limit_w` | **no** |
|  | `coefficient_per_c` | **no** |
|  | `provider_already_corrects` | **no** |
|  | `rated_dc_capacity_wp` | **no** |
|  | `temperature_tier`, `clipping_threshold`, `max_uplift_c`, raw fc/pv/temperature | yes |
| `fit_string_model` | `smoothing_radius`, `neighbor_fitting_cutoff`, `recency_decay_max`, `window_days`, method (all four) | yes |
| `predict_string_forecast` | `fc_selected`, `target_cell_temperature` | yes |
|  | `coefficient_per_c`, `provider_already_corrects`, `converter_limit_w` | **no** (same three as above) |

Four missing scalars in total (`StringComputationConfig`'s remaining fields).
Independently: `# predictions` came from `cache.diagnostic_fit(sensor_id)`,
which is keyed by `sensor_id` only and is **not** invalidated by
`pin_diagnostic_slot` / `clear_diagnostic_slot` (only the `compute()` cache is),
nor populated at all for a registered-but-inactive `mode` (ADR-015 §4a) — so
`# predictions` could describe a different slot than `# training_pool`.

## Acceptance Criteria

- Given any exportable string, when `export_csv` runs, then `# metadata` gains
  four columns appended after `max_uplift_c`, in `StringComputationConfig` field
  order: `converter_limit_w`, `coefficient_per_c`, `provider_already_corrects`,
  `rated_dc_capacity_wp` — floats via `repr()`, the bool as `true`/`false`, and
  a blank for `None` (same blank-means-absent convention as `temperature_tier`).
  `# metadata` is now 19 columns.
- Given an export and *nothing else*, when the replay rebuilds the inputs and
  calls the **real** `apply_training_corrections`, `fit_string_model` (all four
  `REGRESSION_STRATEGIES`) and `predict_string_forecast`, then every
  `pv_corrected`, `predicted` and `accuracy` value matches the file — for a
  plain string, a `weather`-tier string with `rated_dc_capacity_wp` and a
  non-zero `coefficient_per_c`, a string whose `converter_limit_w` excludes
  training samples, and a `provider_already_corrects` string.
- Given the replay, then nothing in `string_computation` is monkeypatched and no
  `predictions` dict is injected: tampering with a `pv_corrected` value, a
  `predicted` value, or any of the four new metadata scalars in a fixture makes
  the replay disagree with it (the three layers ADR-015 §5a formerly listed as
  "echoed, not checked").
- Given a fixture exported before this patch (missing any of the four new
  `# metadata` columns), when it is replayed, then it fails loudly naming the
  file and the missing columns and telling the maintainer to re-export — never
  silently substituting defaults.
- Given `export_csv` is called with an empty, stale, or unpopulated
  `cache.diagnostic_fit`, then `# predictions` is unchanged: it is computed from
  the same `_GatheredPool` the `# training_pool` section is built from, via
  `_predict_all_methods`, and never read from the cache. (`sensor.py`'s own
  `series`/`accuracy` still read the cache — untouched.)
- Given `_predict_all_methods` raises for the exported string, then the export
  still returns its other sections with an empty `# predictions` and logs the
  exception — a debugging aid must not 500 on exactly the weird fit it exists to
  explain.
- Given `fc_selected is None`, then `# predictions` is empty (no fabricated
  rows), as with the previous "no cached prediction → omit" contract.
- Every other `TASK-0038` acceptance criterion (section order, `None` for
  `"sum"` / unknown id / no baseline, blank `pv_selected` / `accuracy` for a
  not-yet-elapsed slot, weight decomposition identity, fixture `expected`
  column, empty-folder behaviour) still holds unchanged.
- `synthetic/` fixtures are regenerated for the 19-column schema; new
  `synthetic/` fixtures cover the clipping and derating branches and each
  formerly-echoed layer as a `FAIL` case.

## Estimated File / Module Footprint (hint, not a commitment)

- `diagnostics/compare_regressions.py` — `_export_metadata_row` (+4 columns),
  `export_csv` (fresh predictions + failure isolation), docstrings
- `tests/diagnostics/test_compare_regressions.py` —
  `_replay_compare_regressions` rewritten (no stub, no injected predictions,
  real config), new tests
- `tests/fixtures/csv_regression/{README.md,synthetic/*}` — regenerated + new
- `adr/015-…`, `adr/INDEX.md`, `tasks/adr-summary.md` §8b, `tasks/INDEX.md`
- No change to `regression/`, `string_computation.py`, `coordinator*.py`,
  `http_export.py`, `csv_fixture_support.py` (the comparator stays generic; the
  measured summation-order sensitivity of all four fits is ~1e-15 relative, far
  inside its 1e-9 tolerance)

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- No new external dependencies (`tasks/DEPENDENCIES.md` unchanged)

## Consumed Interfaces

From `TASK-0038-diagnostic-slot-raw-data-csv-export` (its
`Delivered Artifacts`):

- `CompareRegressionsMode.export_csv`, `_export_metadata_row`,
  `_export_predictions_rows`, `_export_prediction_inputs_rows` from
  `custom_components/shady/diagnostics/compare_regressions.py`
- `CompareRegressionsMode._gather_pool` / `_GatheredPool` /
  `_predict_all_methods` (same file, pre-existing from `TASK-0015b`)
- `DiagnosticMode._write_csv_sections` from
  `custom_components/shady/diagnostics/base.py`
- `parse_csv_sections`, `compare_sections` from `tests/csv_fixture_support.py`
- `_replay_compare_regressions` from
  `tests/diagnostics/test_compare_regressions.py`
- `StringComputationConfig` from `custom_components/shady/coordinator_like.py`

## Delivered Artifacts

Production (`custom_components/shady/`):

- `diagnostics/compare_regressions.py` →
  `CompareRegressionsMode._export_metadata_row` now emits 19 columns
  (`converter_limit_w`, `coefficient_per_c`, `provider_already_corrects`,
  `rated_dc_capacity_wp` appended after `max_uplift_c`); new
  `CompareRegressionsMode._export_optional_float` (static, `None` → blank); new
  `CompareRegressionsMode._export_predictions(...) -> dict[str, float]` (wraps
  `_predict_all_methods`; `{}` when `fc_selected is None` or fitting raises,
  logged); `export_csv` uses it instead of `cache.diagnostic_fit`.
- No other production file changed. `tasks/DEPENDENCIES.md`: no change.

Tests (`tests/`):

- `diagnostics/test_compare_regressions.py` → `_replay_compare_regressions`
  rewritten (real chain, no stub/injection; rejects a pre-amendment fixture);
  module constant `_FIT_METADATA_COLUMNS`; new class
  `TestExportFitReproducibility` (15 cases); `_to_nan_array` and the unused
  `numpy` imports removed.
- `fixtures/csv_regression/synthetic/` → six existing fixtures migrated to 19
  columns (`future_slot_blank_actuals_pass.csv` additionally regenerated: its
  hand-injected predictions were refuted by the real fit); new:
  `clipping_excludes_sample_pass.csv`, `derating_weather_active_pass.csv`,
  `provider_already_corrects_pass.csv`, `tampered_pv_corrected_fail.csv`,
  `tampered_predicted_fail.csv`, `tampered_coefficient_fail.csv`. READMEs
  updated.

Docs: `adr/015-…` (Amendment 2026-09-29; §5a rewritten), `adr/INDEX.md` (missing
ADR-015 row added), `tasks/adr-summary.md` §8b, `tasks/INDEX.md`,
`tasks/TASK-0038-…` (cross-reference only; status unchanged).

## Review (Phase 4b, inline — no sub-agents available)

**PASS.** (1) Acceptance criteria: each has a named test above; the mutation
check (replay ignoring the four new columns) fails 11 tests. (2) Within ADR-015
as amended; one Lead-Agent decision pending human confirmation (recorded in the
Amendment's `Decided by`). (3) Exported symbols match the block above. (4)
Consumed interfaces used as declared, none renamed. (5) Full suite 743 passed;
`ruff` (excl. `EXE002`, an artefact of zip permissions in the review sandbox),
`ruff format`, `mypy` clean. (6) No new dependencies.

**Known limits (not defects):** `target_cell_temperature` is recorded, not
re-derived (its resolution is the coordinator's, not the fit's); raw readings
are inputs; `sum` remains unexportable; the export now fits once per request
instead of reading a cache.
