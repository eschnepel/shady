# `tests/fixtures/csv_regression/`

Golden-file regression fixtures for `CompareRegressionsMode.export_csv`
(ADR-015, `TASK-0038`), replayed by
`tests/diagnostics/test_csv_regression_fixtures.py`. Two folders:

| Folder | What it holds | Who writes it |
| -- | -- | -- |
| `curated/` | Real exports downloaded via `GET /api/shady/{config_entry_id}/export_csv?sensor_id=...` | A maintainer, by hand |
| `synthetic/` | Exports of the test scenarios (some deliberately tampered) that test *the test system itself* | The developers |

Both are picked up automatically — no test code change per fixture. Empty
folders contribute zero test cases (not a skip, not a failure).

## The optional `expected` column

A fixture's `# diagnostic_mode` section may carry a second column:

```csv
# diagnostic_mode
diagnostic_mode,expected
compare_regressions,FAIL
```

`PASS` or `FAIL`; **absent or blank means `PASS`**, so a real export (which
never writes the column) is a `PASS` fixture with no editing. `FAIL` marks a
fixture that must be *rejected* — a tampered value, an unregistered mode. The
test then passes only if the check genuinely fails, and fails if the fixture
unexpectedly replays cleanly (the test system missed a bad fixture).

## When a `PASS` fixture starts failing "correctly"

If the regression math genuinely changed, the failing test leaves the
freshly-regenerated CSV at `_generated/<folder>/<same filename>` (gitignored,
only present between a failing run and the next). If the change was intentional,
copy it over the stale fixture.

## What a replay can and cannot detect

The replay rebuilds `export_csv`'s inputs from the fixture and runs the **real**
`apply_training_corrections`, `fit_string_model` (all four strategies) and
`predict_string_forecast` -- nothing is stubbed or injected, and the correction
parameters come from the four fit columns in `# metadata`. Recomputed and
therefore checked: `pv_corrected`, every `predicted`, `accuracy`, the weight
decomposition, `is_valid`, `sample_date`/`day_age`. **Taken on trust:** the raw
`fc`/`pv`/`temperature` readings, `fc_selected`/`pv_selected`, and
`target_cell_temperature` (inputs, not derivations -- how the coordinator
resolves the last one is outside the fit). Tampering with any recomputed value
or fit scalar fails a fixture.

An export made before ADR-015's 2026-09-29 Amendment (15-column `# metadata`) is
rejected with an error asking you to re-export -- it is never replayed against
defaulted config.
