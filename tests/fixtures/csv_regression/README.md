# `tests/fixtures/csv_regression/`

Golden-file regression fixtures for `CompareRegressionsMode.export_csv`
(ADR-015, `TASK-0038`), replayed by
`tests/diagnostics/test_csv_regression_fixtures.py`. Two folders:

| Folder | What it holds | Who writes it |
| --- | --- | --- |
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
only present between a failing run and the next). If the change was
intentional, copy it over the stale fixture.

## What a replay can and cannot detect

The replay reconstructs `export_csv`'s inputs from the fixture and recomputes
what `export_csv` itself derives. Recomputed and therefore checked: the weight
decomposition (`build_pool`), `is_valid`, `sample_date`/`day_age`, `accuracy`.
**Echoed, not checked:** metadata scalars, raw `fc`/`pv`/`temperature`,
`pv_corrected` (the replay substitutes the recorded values, the correction
parameters not being in the file), and each method's `predicted` value (the
replay does not re-run `fit()`/`predict()`). Tampering with an echoed value
cannot fail a fixture — `synthetic/` only tampers derived values for that reason.
