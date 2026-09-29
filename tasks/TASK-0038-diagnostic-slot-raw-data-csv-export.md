# Task: Raw-Data CSV Export for a Diagnosed Slot (Debugging/Analysis Aid)

- **Status:** review — the delivery-mechanism and ADR-home questions are decided
  (human, 2026-09-24); the mode-generalization question is decided too (human,
  2026-09-26). This stays `review` rather than flipping to `todo` because the
  decision was recorded as a **draft** ADR (ADR-015, `Status: Proposed`), and
  per this project's own Phase 0 procedure a new ADR needs human
  review-confirmation before code is written against it, not just before the
  task admitting it is drafted.
- **Related ADRs:** ADR-015 (new, draft — the delivery-mechanism/module-shape
  decision this task now implements; revised 2026-09-26 to generalize across
  future diagnostic modes), ADR-013 §3 (amended by ADR-015 — the "no change to
  `diagnostics/base.py`" claim narrowed), ADR-000 §3 (module boundaries, amended
  by ADR-015), ADR-004 §2/§2a/§2b/§2d/§5 (`CompareRegressionsMode`, the data
  this exports; §5 cross-references ADR-015), ADR-001 §2/§4a, ADR-011 §1/§2/§3
  (the weight formula `build_pool` decomposes further for this task only),
  ADR-003a §1/§1a, ADR-003b §1/§1a (training corrections).
- **Dependencies:** [] — reads `CompareRegressionsMode`'s already-gathered data;
  changes nothing it depends on.

## Goal

A human debugging a regression result (or just curious) wants every raw number
that went into one diagnosed slot's four-method comparison, in a form they can
drop into a spreadsheet or `pandas` — not just the already-plotted
`series`/`accuracy` attributes `sensor.py` exposes today, but the *training
inputs* behind them: every neighbor-offset/day data point, every weight
component, and the four methods' predictions against what actually happened.

## Decisions (human, 2026-09-24 and 2026-09-26 — see ADR-015 for the full reasoning)

- **Delivery: a CSV download link**, not a clipboard-copy button. A new
  `HomeAssistantView` (`http_export.py`, `requires_auth = True`) serves the CSV
  on `GET`, computed fresh from live coordinator state each request — no new
  frontend technology, no button/service, matching this codebase's own
  established preference for plain HA mechanisms over ad-hoc service +
  custom-frontend combinations (the `shady.select_diagnostic_slot` service →
  `datetime`/`button` entity migration `__init__.py`'s own header comment
  documents is exactly this kind of call, decided the same way once already).
  ADR-015 §1 has the full comparison against the clipboard-copy alternative for
  the record.
- **ADR home: a new ADR (ADR-015), with minor amendments to three existing
  ones** — ADR-000 §3's module-boundary diagram (a new `http_export.py` node), a
  short cross-reference in ADR-004 §5, and ADR-013 §3's "no change to
  `diagnostics/base.py`" claim (narrowed, see below) — rather than folding the
  whole decision into any of those documents outright, since a registered HTTP
  view is a genuinely new kind of surface for this codebase (nothing today
  registers one).
- **Scope: one `sensor_id` per export**, not every entity in one file. A human
  debugging "why did string 0's fit look weird" wants that entity; exporting
  every entity is a straightforward repeat of the same shape later if ever
  wanted, not a different design now.
- **Export is owned by `DiagnosticMode`, not a standalone module** (decided
  2026-09-26, after considering ADR-013's own sketched future modes —
  `compare_regressions_daily`/`compare_providers_daily` have fundamentally
  different raw-data shapes from `CompareRegressionsMode`'s own, so one fixed
  CSV schema could not serve all of them). `DiagnosticMode` gains an optional
  `export_csv(sensor_id) -> str | None` method, mirroring `extra_fit()`'s own
  established pattern exactly (base default `None`, every mode free to override
  or not). `CompareRegressionsMode` overrides it with this task's own four
  content sections below. A shared, format-only
  `DiagnosticMode._write_csv_sections(...)` static helper (mirroring
  `_xy_series_entry`'s own placement rationale) handles only the mechanical
  `#`-marker/header/rows shape every section uses — never the column content,
  which stays entirely mode-owned. `http_export.py` itself is genuinely
  mode-agnostic: it resolves the active mode and calls
  `mode.export_csv (sensor_id)`, with zero knowledge of what any mode's export
  contains.
- **`build_pool` gains a second, optional return value**, used only by
  `CompareRegressionsMode.export_csv` — not a second, independently-maintained
  re-derivation of the weight formula living elsewhere. A keyword-only flag
  (`return_weight_breakdown: bool = False`), default off, so
  `string_computation.py`'s real fit path (every other caller) keeps its current
  single-`NDArray`-return signature and pays nothing for a breakdown it never
  asked for. ADR-015 §6 has the full rationale.

## Proposed CSV Schema

One export = one `sensor_id`'s current diagnosed state. Every export's **first
section is `# diagnostic_mode`**, one column, one row —
`diagnostic_mode,<the mode's own registry name>` (e.g. `compare_regressions`,
ADR-013 §2's `_diagnostic_modes` registry key) — ahead of everything else, in
the exact same `#`-marker/header/row shape every other section uses. Identifying
which mode produced a file has to come before anything else, including before a
generic reader can know how to interpret `# metadata`'s own fields (a future
mode's metadata may differ), and keeping it in the same uniform shape as every
other section means a generic parser needs no special case for it.
`CompareRegressionsMode`'s own four content sections follow, unchanged from the
original schema, each with its own header row, separated by a blank line —
parses cleanly with `pandas.read_csv(path, skiprows=N)` per section, or by hand
in a spreadsheet.

**`# metadata`** — a normal CSV table, one header row and exactly **one** data
row (every field is a single scalar for this export, so one row is the natural
shape — not `key,value` pairs, which would need every reader to pivot it back
before use). Everything needed to reproduce the fit *without* re-deriving it
from the coordinator: the exact `RegressionSettings` five scalars (ADR-004 §5,
second Amendment) that feed `build_pool`/`apply_training_corrections`, plus
enough identity/timing context to know exactly which slot this is.

**`# training_pool`** — one row per `(offset, day)` training data point: every
"data point from all sensors," PV/forecast history, the neighbor offsets used
for smoothing, and every weight component `regression/base.py`'s `build_pool`
computes for that point, decomposed rather than only the
already-multiplied-together final weight (`build_pool`'s new
`return_weight_breakdown=True` path, decided above).

**`# predictions`** — one row per `regression/` strategy
(`string_computation.REGRESSION_STRATEGIES`: `linear`, `kernel`, `wls2`,
`wls3`), its predicted value against `pv_selected` (the diagnosed slot's own
achieved/ground-truth PV, only present once `diagnosed.is_elapsed`), and the
same `diagnostic_accuracy` (`aggregation.py`) figure `sensor.py`'s own
`accuracy` attribute already shows — restated here so the export is
self-contained, not because the sensor doesn't already have it.

**`# prediction_inputs`** — the scalar inputs every method's `predict()` call
actually used: `fc_selected`, `target_cell_temperature` (temperature-tier
strings only — `coordinator.target_cell_temperature_for_slot`), and
`pv_selected` again for convenience next to what it's being compared against.

### Sample (illustrative numbers, not live output)

A temperature-aware (`weather` tier) string, `window_days=5`,
`smoothing_radius=1`, already-elapsed diagnosed slot:

```csv
# diagnostic_mode
diagnostic_mode
compare_regressions

# metadata
string_index,string_name,diagnosed_at,diagnosed_index,slot_of_day,is_pinned,is_elapsed,regression_method_configured,temperature_tier,window_days,smoothing_radius,neighbor_fitting_cutoff,recency_decay_max,clipping_threshold,max_uplift_c
0,Dach Süd,2026-09-23T14:35:00+00:00,297115,175,false,true,wls2,weather,5,1,0.25,0.5,0.98,25.0

# training_pool
offset,day_index,sample_date,day_age,fc_raw,pv_raw,pv_corrected,temperature_raw,is_valid,magnitude_weight,time_weight,recency_weight,neighbor_excluded,neighbor_scale,combined_weight
-1,0,2026-09-19,4,2450.0,2210.0,2380.0,22.1,1,0.98,0.5,0.60,0,1.0,0.294
-1,1,2026-09-20,3,2510.0,2600.0,2600.0,23.0,1,0.99,0.5,0.70,0,1.0,0.3465
-1,2,2026-09-21,2,180.0,140.0,150.0,19.5,1,0.35,0.5,0.80,1,1.0,0.0
-1,3,2026-09-22,1,2600.0,2500.0,2500.0,24.0,1,0.99,0.5,0.90,0,1.0,0.4455
-1,4,2026-09-23,0,2580.0,2490.0,2490.0,23.5,1,0.99,0.5,1.00,0,1.0,0.495
0,0,2026-09-19,4,2500.0,2300.0,2450.0,22.3,1,0.99,1.0,0.60,0,1.0,0.594
0,1,2026-09-20,3,2550.0,2630.0,2630.0,23.2,1,0.99,1.0,0.70,0,1.0,0.693
0,2,2026-09-21,2,200.0,160.0,170.0,19.8,1,0.40,1.0,0.80,0,1.0,0.32
0,3,2026-09-22,1,2620.0,2540.0,2540.0,24.1,1,0.99,1.0,0.90,0,1.0,0.891
0,4,2026-09-23,0,2600.0,2510.0,2510.0,23.6,1,0.99,1.0,1.00,0,1.0,0.99
1,0,2026-09-19,4,2480.0,,,22.0,0,0.0,0.5,0.60,0,1.0,0.0
1,1,2026-09-20,3,2560.0,2610.0,2610.0,23.1,1,0.99,0.5,0.70,0,1.0,0.3465
1,2,2026-09-21,2,195.0,150.0,160.0,19.6,1,0.38,0.5,0.80,0,1.0,0.152
1,3,2026-09-22,1,2630.0,2530.0,2530.0,24.0,1,0.99,0.5,0.90,0,1.0,0.4455
1,4,2026-09-23,0,2590.0,2470.0,2470.0,23.4,1,0.99,0.5,1.00,0,1.0,0.495

# predictions
method,predicted,pv_selected,accuracy
linear,2480.0,2530.0,0.980
kernel,2455.0,2530.0,0.970
wls2,2570.0,2530.0,0.984
wls3,2605.0,2530.0,0.970

# prediction_inputs
fc_selected,2610.0
target_cell_temperature,41.2
pv_selected,2530.0
```

Row 11 (`offset=1, day_index=0`) is deliberately blank on `pv_raw`/
`pv_corrected` — illustrating a day with no valid data yet (fresh string, or a
sensor gap): `is_valid=0`, `magnitude_weight` forced to `0.0`, so
`combined_weight=0.0` regardless of the other factors, matching `build_pool`'s
own `valid_mask` handling. Row 3 (`offset=-1, day_index=2`) is deliberately
`neighbor_excluded=1` — illustrating ADR-011 §2's hard-exclusion path
(`neighbor_fitting_cutoff=0.25`, not the `RESCALE_SENTINEL`, so exclusion rather
than rescale is the active mode this session): `combined_weight=0.0` even though
the row's own `is_valid=1`, because its neighbor-vs-center deviation exceeded
the configured cutoff, not because the data itself was missing — a genuinely
different reason for the same zero, worth being able to tell apart when reading
the export. `neighbor_scale` stays `1.0` on every row here because exclusion,
not rescale, is the active mode; a config with `neighbor_fitting_cutoff` set to
the rescale sentinel would instead show `neighbor_excluded=0` everywhere and a
real per-row `neighbor_scale`. `# prediction_inputs` stays `key,value` (not a
wide table like `# metadata`) since it is genuinely heterogeneous —
`target_cell_temperature` is absent entirely for a non-temperature-tier string,
which a wide table would have to represent as a blank column rather than an
absent row; `# metadata`'s fifteen fields, by contrast, are always all present
together, which is exactly what makes the wide-table shape a faithful single row
there rather than an arbitrary choice.

**Precision requirement on every float column, driven entirely by the
fixture-regression tests below:** written with enough decimal precision to
round-trip meaningfully (`repr()`-level, not a display-rounded 2-3 decimals) —
the sample above uses short numbers purely for readability; a real export must
not lose precision the fixture tests would otherwise need. Exact
`float`-formatting call TBD at implementation time (`repr(float(x))` is the
simplest option that satisfies this).

## Fixture-Based Regression Tests (human addition, 2026-09-24; generalized 2026-09-26)

A second, independent use for this export, beside the human debugging described
in the Goal above: **golden-file regression testing of the export pipeline
itself**, using real exported CSVs as fixtures a maintainer curates by hand — no
synthetic test data to keep hand-maintained in sync with `regression/base.py`'s
own formula as it evolves. Designed around the same
generic-mechanism-versus-mode-owned-content split as the export itself
(Decisions above), so a future diagnostic mode's own fixture support costs one
small function and one registry line, not a redesign of this mechanism.

**Maintainer workflow.** Download a CSV via this task's own export feature, drop
it into `tests/fixtures/csv_regression/` (new directory, any filename ending
`.csv`), next `pytest` run picks it up automatically — no test code change
needed per fixture. When `regression/base.py`'s formula genuinely, deliberately
changes (a bug fix, a new strategy, a reweighted formula) and a fixture starts
failing "correctly," not as a regression: the test (design below) leaves a
freshly-regenerated CSV sitting right next to where it looked for one, ready to
use — accepting the change is a straight file copy over the stale fixture, no
manual reconciliation needed. Worth stating plainly that this is expected,
ordinary golden-file maintenance, not a broken mechanism — a future
ridge-term-style fix (the kind `TASK-0037-patch-1` made to
`fit_weighted_polynomial`) is exactly the case this paragraph describes.

**Three layers, the boundary drawn at exactly the same place as the export
design above: generic parsing, generic dispatch, mode-owned interpretation.**

1. **Generic, written once, reused by every mode forever — parsing.**
   `parse_csv_sections(text: str) -> list[tuple[str, list[dict[str, str]]]]`
   splits on the `#`-marker lines, `csv.DictReader` per section, returns the
   sections in file order with their names. This is the read-side mirror of the
   export's own shared `_write_csv_sections` helper; together they are the only
   two places the file *format*, as opposed to its content, is encoded at all.
   Test-only code (`tests/`), not production — production never needs to read
   its own output back. A fixture that fails to parse at all (missing a section,
   malformed header) fails the test loudly, naming the file and the problem.
1. **Generic, written once — dispatch.** Read the leading `# diagnostic_mode`
   section's own value and look it up in a small
   `dict[str, Callable[[list [tuple[str, list[dict[str, str]]]]], str]]`
   registry in `tests/test_csv_regression_fixtures.py` — one entry per mode with
   fixture-replay support, today just
   `"compare_regressions": _replay_compare_regressions`. An unregistered mode
   name fails the fixture loudly too, naming the file and the unknown mode — not
   a silently-skipped fixture either.
1. **Mode-owned, one function per mode — interpretation.**
   `_replay_compare_regressions(sections)` is the *only* mode-specific test code
   this design needs. It looks up `"metadata"`/`"training_pool"`/
   `"prediction_inputs"` **by name**, not position (robust to a future section
   being added or reordered), reconstructs the real typed inputs
   `CompareRegressionsMode.export_csv` itself needs (the
   `dict[int, NDArray[np.float64]]` shape `build_pool` takes for
   `fc_raw`/`pv_raw`/`temperature_raw`, `n_slots=1`, grouped by `offset` and
   ordered by `day_index`; `RegressionSettings`' five scalars plus `window_days`
   from `# metadata`), calls the real `export_csv`, and returns the fresh CSV
   text it produces.

**Comparison is also fully generic** — a consequence of both the original and
the regenerated CSV existing as the same parsed shape once step 1 runs on each:
`compare_sections(old, new, rel_tol) -> list[str]` (a list of human-readable
mismatch descriptions, empty if none) walks both structures section by section,
row by row, field by field, attempting `float()` on each value and falling back
to exact string equality — no section or field name is special-cased anywhere in
this function.

**Disk I/O only on a mismatch.** Since comparison happens on the parsed,
in-memory structures, a passing run touches nothing beyond reading the fixture
itself — no write-then-delete dance. Only when `compare_sections` returns
anything does the regenerated CSV get written, to
`tests/fixtures/ csv_regression/_generated/<same filename as the fixture>`: both
the diagnostic evidence for the failure and, if the underlying change was
intentional, the maintainer's ready-made replacement fixture — copy it over the
original to accept the new behaviour, exactly the workflow described above.

This design means the fixture mechanism exercises
`CompareRegressionsMode.export_csv`'s real CSV-assembly/formatting code end to
end (via `_replay_compare_regressions`, which calls it directly), not only
`regression/base.py`'s underlying math in isolation. Still **not** exercised
here: `http_export.py`'s own HTTP-layer concerns (routing, `requires_auth`, the
`Content-Disposition` header) — those stay covered by their own ordinary tests
per this task's `Definition of Done`, since this mechanism never goes through
HTTP at all, only calls `export_csv` directly.

**Zero fixtures present is not a failure** (a fresh checkout, or a maintainer
who hasn't curated any yet): `glob` returning nothing means
`@ pytest.mark.parametrize` collects zero cases, which is an empty, always-green
pass — not a skip, not an error — consistent with this project's own "degrade
gracefully with no data" pattern elsewhere (e.g.
`TestFcSumFcDayArrayNoStrings`). Left deliberately unenforced whether at least
one fixture must exist; a repository-level policy decision (CI requiring N
fixtures, say) is out of scope for this task.

**The sample CSV above is not a valid fixture** — its numbers are
hand-fabricated for schema illustration (this task file's own "illustrative
numbers, not live output" note), not self-consistent under the real formulas,
and would fail the comparison step immediately if dropped into
`tests/fixtures/csv_regression/`. A real fixture can only come from an actual
export once this task is implemented.

## Acceptance Criteria

- Given a diagnosed slot with a resolved `baseline_entity_id`, when the export
  is requested for one of its strings, then the returned CSV has the leading
  `# diagnostic_mode` section plus `CompareRegressionsMode`'s four content
  sections, and every `training_pool` row's `combined_weight` equals
  \`magnitude_weight * time_weight * recency_weight * (not neighbor_excluded)
  - is_valid`exactly (the same product`build_pool\` itself computes) — the
    export is a decomposition of the real fit, not an approximation of it.
- Given a string with no `baseline_entity_id` configured, when the export is
  requested for it, then `export_csv` returns `None` (matching
  `_compute_sensor`'s own "no baseline configured" contract, ADR-015 §2) rather
  than an empty or malformed file, and `http_export.py` reports
  `HTTPStatus.NOT_FOUND`.
- Given a not-yet-elapsed (future-pinned) diagnosed slot, when the export is
  requested, then `# prediction_inputs`' `pv_selected` line and the
  `# predictions` section's `pv_selected`/`accuracy` columns are empty —
  mirroring `_append_selected_series`'s own "no `pv_selected` yet" contract
  (`sensor.py`'s `series`/`accuracy` today) — rather than the export fabricating
  a value.
- Given a `sensor_id` the active mode does not recognize, when the export is
  requested, then `export_csv` returns `None` and `http_export.py` reports
  `HTTPStatus.NOT_FOUND` — the same contract as the no-baseline case above,
  since both are "this mode has nothing to export for that identifier."
- An unauthenticated request to the export view cannot retrieve any entity's
  data (`requires_auth = True`, ADR-015 §1).
- Every existing caller of `build_pool` (`string_computation.py`'s real fit
  path) is unaffected — same signature at its default, same return shape, same
  test results — since `return_weight_breakdown` defaults to `False`.
- Every other `DiagnosticMode` subclass (none exist yet beyond
  `CompareRegressionsMode`) is unaffected by the new `export_csv` method — the
  base default `None` requires no override, the same guarantee `extra_fit()`
  already gives every mode that doesn't need it.
- Given a `tests/fixtures/csv_regression/*.csv` file exported from an actual
  (post-implementation) run, when `tests/test_csv_regression_fixtures.py` runs,
  then it parses the fixture, dispatches to `_replay_compare_regressions` via
  the leading `# diagnostic_mode` value, regenerates the CSV by calling
  `CompareRegressionsMode.export_csv` with the reconstructed inputs, and
  `compare_sections` reports zero mismatches between the parsed original and the
  parsed regeneration.
- Given a fixture whose regenerated CSV does *not* match (the regression math
  changed since the fixture was curated), when the test fails, then the
  freshly-generated file is written to
  `tests/fixtures/csv_regression/_generated/` — the only disk write this
  mechanism ever performs.
- Given zero files under `tests/fixtures/csv_regression/`, when the full suite
  runs, then `test_csv_regression_fixtures.py` contributes zero test cases and
  neither fails nor is skipped-with-a-warning — an empty parametrization, not a
  special case needing its own guard.

## Estimated File / Module Footprint (hint, not a commitment)

- `diagnostics/base.py` — `DiagnosticMode` gains the optional `export_csv`
  method (base default `None`) and the shared `_write_csv_sections` static
  helper (ADR-015 §2/§3)
- `diagnostics/compare_regressions.py` — `CompareRegressionsMode.export_csv`,
  the actual four-section CSV assembly from
  `_GatheredPool`/`_predict_all_methods`'s already-gathered data, plus capturing
  `pv_by_offset`/`temperature_by_offset` (currently discarded once
  `apply_training_corrections` runs inside `_gather_pool`) into `_GatheredPool`
  alongside `fc_by_offset`/`corrected_pv_by_offset`
- `regression/base.py` — `build_pool` gains the `return_weight_breakdown`
  keyword-only flag and its second return value (ADR-015 §6)
- `http_export.py` (new) — the `HomeAssistantView` registration, mode- agnostic
  (ADR-015 §1/§4)
- `__init__.py` — registers the new view during `async_setup_entry`
- `tests/test_csv_regression_fixtures.py` (new) — `parse_csv_sections`,
  `compare_sections`, the per-mode replay registry, and
  `_replay_compare_regressions`
- `tests/fixtures/csv_regression/` (new, empty at merge time bar a short
  `README.md` restating the maintainer workflow above) — not populated by this
  task itself; the human curates fixtures afterward
- `tests/fixtures/csv_regression/_generated/` (new, always empty at rest — only
  ever holds a file between a failing test run and the next one) and a matching
  `.gitignore` entry, so a leftover generated file from a local failure is never
  accidentally committed

## Definition of Done

- ADR-015 confirmed by human review (no longer `Status: Proposed`) before
  implementation begins
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces

<!-- Filled by the Lead Agent once ADR-015 is confirmed and this flips to
     `todo`. -->

- `DiagnosticMode.export_csv`/`DiagnosticMode._write_csv_sections`
  (`diagnostics/base.py`) — new, exact signatures per ADR-015 §2/§3
- `_GatheredPool` (`diagnostics/compare_regressions.py`) — extended per ADR-015
  §2/Estimated Footprint above, exact shape TBD until implementation
- `build_pool` (`regression/base.py`) — extended per ADR-015 §6, exact
  second-return-value shape TBD until implementation

## Delivered Artifacts

<!-- Filled by the Worker after implementation. Not applicable yet — this
     task is `review`, not `todo`. -->
