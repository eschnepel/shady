# Task: Raw-Data CSV Export for a Diagnosed Slot (Debugging/Analysis Aid)

- **Status:** done — ADR-015 confirmed by human review, `Status: Accepted`,
  2026-09-27 (Phase 0's own draft-ADR procedure now satisfied); the same review
  pass requested three further amendments (recorded below and wired directly
  into ADR-015 §4a/§5/§7), which this implementation pass covers alongside the
  original schema. Moved `review` → `todo` → `in-progress` in one sitting, no
  separate human gate in between (Phase 3's readiness check — no dependency
  tasks, nothing to propagate — cleared immediately).
- **Related ADRs:** ADR-015 (`Status: Accepted` — the delivery-mechanism/
  module-shape decision this task implements, including the 2026-09-27
  amendments), ADR-013 §3 (amended by ADR-015 — the "no change to
  `diagnostics/base.py`" claim narrowed), ADR-000 §3 (module boundaries, amended
  by ADR-015; the `diagnostics --> regression` edge amended 2026-09-27), ADR-000
  §6 (testing philosophy, amended 2026-09-27 — the `tests/diagnostics/` package
  convention), ADR-004 §2/§2a/§2b/§2d/§5 (`CompareRegressionsMode`, the data
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

## Decisions addendum (human, 2026-09-27 — requested at implementation kickoff, wired into ADR-015 directly since it is a draft ADR)

- **Test package structure mirrors `diagnostics/` itself.** `tests/` gains a
  `tests/diagnostics/` sub-package, one file per diagnostic mode (today, just
  `CompareRegressionsMode`'s own `test_compare_regressions.py`) plus one file
  for the shared base-class mechanism (`test_base.py`) — see ADR-000 §6's
  2026-09-27 Amendment and ADR-015 §7 for the full rationale and exact file
  layout. `tests/test_diagnostics_base.py`/
  `tests/test_diagnostics_compare_regressions.py` move, unchanged in content,
  into it. This task's own new tests (`CompareRegressionsMode.export_csv`'s
  direct unit tests, `_replay_compare_regressions`) land directly in
  `tests/diagnostics/test_compare_regressions.py`, not a separate file — "one
  file per mode" means everything about that mode, not one file per concern
  within it. The fully generic fixture mechanism
  (`parse_csv_sections`/`compare_sections`) lives in a new, top-level,
  non-test-prefixed `tests/csv_fixture_support.py` — **not** nested under
  `tests/diagnostics/`, since it is agnostic to diagnostic modes specifically
  (only the generic `# name`-marker-section file format), the same reasoning
  that already keeps `tests/fixtures/csv_regression/` itself top-level —
  imported by both `test_compare_regressions.py` and the parametrized runner
  (`test_csv_regression_fixtures.py`) to avoid a `test_*.py` ↔ `test_*.py`
  import cycle. `tests/test_http_export.py` stays top-level, since
  `http_export.py` itself is a top-level module, not part of the `diagnostics/`
  package.
- **`http_export.py`'s view gains an optional `mode` query parameter, defaulting
  to the currently configured (active) mode.**
  `GET .../export_csv?sensor_id=...&mode=...` — `mode` names a registered
  `DiagnosticMode` by its own registry `key` independent of `select.py`'s
  current live selection; omitted, the view keeps its original behavior
  (`coordinator.diagnostic_mode()`). Resolved via a new
  `ShadyCoordinator.diagnostic_mode_by_key(key) -> DiagnosticMode | None`
  accessor — see ADR-015 §4a for the full rationale (not added to
  `ShadyCoordinatorLike`: only `http_export.py`, which already holds a real
  `ShadyCoordinator`, ever needs it).
- **The fixture mechanism's `parse_csv_sections` returns a
  `dict[str, list[dict[str, str]]]`, not the original draft's
  `list[tuple[str, ...]]`.** Section identifiers become structurally unique by
  construction — building the `dict` raises loudly (naming the file and the
  duplicated section) on a second occurrence of the same `#`-marker name, rather
  than silently discarding one, per ADR-015 §5's own Amendment. The *write* side
  (`_write_csv_sections`, `diagnostics/base.py`) is unaffected — still
  `list[tuple[str, rows]]`, order still meaningful for a human reading a real
  export top to bottom.
- **Two fixture folders and an optional `expected` column** (human, 2026-09-27,
  requested while the fixture runner was being written; ADR-015 §5a).
  `tests/fixtures/csv_regression/curated/` holds real, hand-dropped exports;
  `synthetic/` holds developer-written fixtures (exports of the test scenarios,
  some tampered) that test the test system itself. A fixture's
  `# diagnostic_mode` row may carry `expected` = `PASS`/`FAIL` (absent/blank =
  `PASS`, so exports never write it); `FAIL` fixtures must be rejected, and
  passing one that replays cleanly is itself a failure. The failure-output
  directory mirrors the folder: `_generated/<folder>/<filename>`.

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
   `parse_csv_sections(text: str) -> dict[str, list[dict[str, str]]]` (ADR-015
   §5's 2026-09-27 Amendment — a `dict`, not the original draft's
   `list[tuple[str, ...]]`, making section-name uniqueness structural: a second
   `#`-marker line with an already-seen name raises loudly while parsing, naming
   the file and the duplicated section, rather than silently keeping one and
   losing the other) splits on the `#`-marker lines, `csv.DictReader` per
   section. This is the read-side mirror of the export's own shared
   `_write_csv_sections` helper; together they are the only two places the file
   *format*, as opposed to its content, is encoded at all. Test-only code
   (`tests/csv_fixture_support.py`, top-level — agnostic to diagnostic modes
   specifically), not production — production never needs to read its own output
   back. A fixture that fails to parse at all (missing a section, malformed
   header, a duplicated section name) fails the test loudly, naming the file and
   the problem.
1. **Generic, written once — dispatch.** Read the leading `# diagnostic_mode`
   section's own value and look it up in a small
   `dict[str, Callable[[dict[str, list[dict[str, str]]]], str]]` registry in
   `tests/diagnostics/test_csv_regression_fixtures.py` — one entry per mode with
   fixture-replay support, today just
   `"compare_regressions": _replay_compare_regressions` (imported from
   `tests/diagnostics/test_compare_regressions.py`, that mode's own one file).
   An unregistered mode name fails the fixture loudly too, naming the file and
   the unknown mode — not a silently-skipped fixture either.
1. **Mode-owned, one function per mode — interpretation.**
   `_replay_compare_regressions(sections)`, in
   `tests/diagnostics/test_compare_regressions.py` alongside every other test of
   this one mode, is the *only* mode-specific test code this design needs. It
   looks up `"metadata"`/`"training_pool"`/`"prediction_inputs"` **by name**
   (now a plain `dict` lookup, structurally robust to a future section being
   added or reordered — and, per the Amendment above, structurally guaranteed
   not to collide with itself), reconstructs the real typed inputs
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
`tests/fixtures/csv_regression/_generated/<folder>/<same filename as the fixture>`:
both the diagnostic evidence for the failure and, if the underlying change was
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
  `magnitude_weight * time_weight * recency_weight * (not neighbor_excluded) * is_valid`
  exactly (the same product `build_pool` itself computes, with
  `magnitude_weight` captured *before* neighbor-exclusion zeroing — ADR-015 §6's
  2026-09-27 clarification — so the formula is a genuine decomposition, not one
  column silently already absorbing another's effect) — the export is a
  decomposition of the real fit, not an approximation of it.
- Given a string with no `baseline_entity_id` configured, when the export is
  requested for it, then `export_csv` returns `None` (matching
  `_compute_sensor`'s own "no baseline configured" contract, ADR-015 §2) rather
  than an empty or malformed file, and `http_export.py` reports
  `HTTPStatus.NOT_FOUND`.
- Given `sensor_id="sum"` (the pointwise-summed aggregate `sensor_ids()` also
  declares) or any other `sensor_id` not matching a configured string index,
  when the export is requested, then `export_csv` returns `None` — the sum
  pseudo-string has no single coherent per-string `temperature_tier`/config the
  `# metadata` section's one-row schema could represent (implementation
  decision, 2026-09-27) — and `http_export.py` reports `HTTPStatus.NOT_FOUND`,
  indistinguishable from the no-baseline/unrecognized-id cases above.
- Given a `mode` query parameter naming a *registered* `DiagnosticMode` other
  than the currently active one, when the export is requested, then
  `http_export.py` exports from that named mode via
  `coordinator.diagnostic_mode_by_key`, not the active selection (ADR-015 §4a).
  Given `mode` is omitted, the view falls back to
  `coordinator.diagnostic_mode()` (the original, still-default behavior). Given
  `mode` names an unregistered key (including `"off"`), the view reports
  `HTTPStatus.NOT_FOUND` — the same "nothing to export" contract as an
  unrecognized `sensor_id`.
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
- Given a `tests/fixtures/csv_regression/curated/*.csv` file exported from an
  actual (post-implementation) run, when
  `tests/diagnostics/test_csv_regression_fixtures.py` runs, then it parses the
  fixture, dispatches to `_replay_compare_regressions` via the leading
  `# diagnostic_mode` value, regenerates the CSV by calling
  `CompareRegressionsMode.export_csv` with the reconstructed inputs, and
  `compare_sections` reports zero mismatches between the parsed original and the
  parsed regeneration.
- Given a fixture whose regenerated CSV does *not* match (the regression math
  changed since the fixture was curated), when the test fails, then the
  freshly-generated file is written to
  `tests/fixtures/csv_regression/_generated/` — the only disk write this
  mechanism ever performs.
- Given CSV text containing two sections with the same `#`-marker name, when
  `parse_csv_sections` (`tests/csv_fixture_support.py`) parses it, then it
  raises, naming both the duplicated section and (where the caller supplies one)
  the fixture file — never silently keeping one occurrence and discarding the
  other (ADR-015 §5's 2026-09-27 Amendment).
- Given a fixture whose `# diagnostic_mode` row has an `expected` column of
  `FAIL`, when it is replayed, then the test passes only if the check fails (a
  mismatch, or an unregistered mode) and fails if it replays cleanly; given the
  column absent or blank, it behaves as `PASS`; given any other value, it fails
  loudly naming the file. The column is not part of the regenerated export.
- Given zero files in both `tests/fixtures/csv_regression/curated/` and
  `synthetic/`, when the full suite runs, then `test_csv_regression_fixtures.py`
  contributes zero test cases and neither fails nor is skipped-with-a-warning —
  an empty parametrization, not a special case needing its own guard.

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
  keyword-only flag, its second return value (`WeightBreakdown`, ADR-015 §6),
  and the `overload`-typed signature split (mypy strict)
- `coordinator.py` — two new public accessors: `diagnostic_mode_by_key(key)`
  (ADR-015 §4a, any registered mode by key, not just the active one) and
  `configured_regression_method()` (the `# metadata` section's own
  `regression_method_configured` field)
- `coordinator_like.py` — `ShadyCoordinatorLike` gains
  `configured_regression_method(self) -> str: ...` (needed by
  `CompareRegressionsMode.export_csv` via `self._coordinator`;
  `diagnostic_mode_by_key` is *not* added here — only `http_export.py`, which
  already holds a real `ShadyCoordinator`, ever calls it)
- `http_export.py` (new) — the `HomeAssistantView` registration, mode-agnostic
  (ADR-015 §1/§4), the optional `mode` query-parameter override (ADR-015 §4a)
- `__init__.py` — registers the new view once per `hass` during
  `async_setup_entry` (guarded — the URL's own `{config_entry_id}` segment
  already lets one registration serve every config entry)
- `tests/diagnostics/__init__.py` (new), plus `tests/test_diagnostics_base.py` →
  `tests/diagnostics/test_base.py` and
  `tests/test_diagnostics_compare_regressions.py` →
  `tests/diagnostics/test_compare_regressions.py` (moved, unchanged content —
  ADR-000 §6's 2026-09-27 Amendment, ADR-015 §7)
- `tests/csv_fixture_support.py` (new, top-level — not nested under
  `tests/diagnostics/`, since it is agnostic to diagnostic modes specifically) —
  `parse_csv_sections` (`dict`-returning, ADR-015 §5 Amendment) and
  `compare_sections`
- `tests/diagnostics/test_csv_regression_fixtures.py` (new) — the per-mode
  replay registry and the `glob`-based parametrized runner
- `tests/diagnostics/test_compare_regressions.py` — gains
  `CompareRegressionsMode.export_csv`'s own direct unit tests and
  `_replay_compare_regressions` (imported by the runner above)
- `tests/test_regression.py` — new zero-mocking tests for
  `build_pool(..., return_weight_breakdown=True)`'s `WeightBreakdown`, directly
  at the `regression/base.py` level (ADR-000 §6), independent of the CSV
  mechanism
- `tests/support_ha.py` — `FakeHomeAssistant` gains `.http` (a `FakeHttp`
  recording `register_view` calls); a new `_install_http_stub()` extension
  function (`homeassistant.components.http.HomeAssistantView`, a hand-rolled
  `aiohttp.web.Response` — neither package is actually installed in this
  project's own dev/test environment, same convention as `homeassistant.*`
  itself, ADR-000 §6)
- `tests/test_http_export.py` (new, top-level — mirrors `http_export.py`'s own
  top-level placement)
- `tests/fixtures/csv_regression/curated/` (new, empty bar a README — the human
  drops real exports here afterward) and `synthetic/` (new, six
  developer-written fixtures: three `PASS`, three `FAIL`, see its README), with
  a root `README.md` covering the workflow, the `expected` column and what a
  replay can and cannot detect
- `tests/fixtures/csv_regression/_generated/<folder>/` (new, always empty at
  rest — only ever holds a file between a failing test run and the next one) and
  a matching `.gitignore` entry, so a leftover generated file from a local
  failure is never accidentally committed

## Definition of Done

- ADR-015 confirmed by human review (no longer `Status: Proposed`) before
  implementation begins
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces

Empty by design, not left unfilled — `Dependencies: []` above: this task
reads/extends `CompareRegressionsMode`'s own already-gathered data and
`regression/base.py`'s own `build_pool`, both in the same codebase this task
itself modifies, not a dependency task's `Delivered Artifacts`. Nothing to copy
in from Phase 3.

## Delivered Artifacts

Production (`custom_components/shady/`):

- `regression/base.py` → `WeightBreakdown` (frozen dataclass: `magnitude_weight`
  [pre-exclusion], `valid_mask`, `combined_weight`, `time_weight`,
  `neighbor_excluded`, `neighbor_scale`, `recency_weight`);
  `build_pool(..., *, apply_magnitude_weight=True, return_weight_breakdown=False)`
  now `@overload`ed → `SamplePool` / `tuple[SamplePool, WeightBreakdown]`
- `diagnostics/base.py` →
  `DiagnosticMode.export_csv(self, sensor_id: str) -> str | None` (base default
  `None`);
  `DiagnosticMode._write_csv_sections(sections: list[tuple[str, list[dict[str, str]]]]) -> str`
  (static, `\r\n` throughout)
- `diagnostics/compare_regressions.py` → `CompareRegressionsMode.export_csv` (+
  private `_export_metadata_row`, `_export_window_start_date`,
  `_export_training_pool_rows`, `_export_predictions_rows`,
  `_export_prediction_inputs_rows`); module-level `_export_float_or_blank`;
  `_GatheredPool` gains `pv_by_offset`, `temperature_by_offset`
- `coordinator.py` →
  `ShadyCoordinator.diagnostic_mode_by_key(key) -> DiagnosticMode | None`,
  `ShadyCoordinator.configured_regression_method() -> str`
- `coordinator_like.py` → `ShadyCoordinatorLike` gains
  `configured_regression_method()` and `pinned_diagnostic_slot()` (the latter
  was already implemented on the coordinator, just not in the Protocol)
- `http_export.py` (new) → `ShadyExportCsvView(HomeAssistantView)`,
  `url = "/api/shady/{config_entry_id}/export_csv"`,
  `name = "api:shady:export_csv"`, `requires_auth = True`,
  `async get(request, config_entry_id)`; query `sensor_id`, optional `mode`
- `__init__.py` → `_HTTP_VIEW_REGISTERED_KEY`, `_register_http_view_once(hass)`
  (called from `async_setup_entry`)
- `mypy.ini` → `[mypy-shady.http_export]`; `.gitignore` → `_generated/`
- External dependencies added: none installed — `homeassistant.components.http`
  and `aiohttp` recorded as bundled-with-HA in `tasks/DEPENDENCIES.md`

Tests (`tests/`):

- `csv_fixture_support.py` (new, top-level) →
  `parse_csv_sections(text, *, source) -> dict[str, list[dict[str, str]]]`
  (raises on a duplicate section; accepts CRLF and LF),
  `compare_sections(old, new, rel_tol=1e-9) -> list[str]`;
  `test_csv_fixture_support.py`
- `diagnostics/` package: `test_base.py`, `test_compare_regressions.py` (moved;
  gains `export_csv` tests, `TestExportReplayRoundTrip`,
  `_replay_compare_regressions`), `test_csv_regression_fixtures.py`
  (`evaluate_fixture`, `check_fixture`, `_REPLAY_REGISTRY`, the `expected`
  column, `TestCheckFixture`)
- `test_http_export.py`, `test_init.py` (registration guard),
  `test_regression.py` (`TestWeightBreakdown`); `support_ha.py` → `FakeHttp`,
  `FakeHomeAssistant.http`, `_install_http_stub()`
- `test_coordinator.py` → `_TC_MODULES`, `_restore_modules()` (collection-order
  guard, see INDEX.md refinement log); applied in the five files importing `tc`
- `fixtures/csv_regression/{curated,synthetic}/` — six synthetic fixtures +
  READMEs

Known limit, documented in ADR-015 §5a and the fixtures README: a replay checks
only what `export_csv` derives, not echoed inputs or `fit()`/`predict()` output.
