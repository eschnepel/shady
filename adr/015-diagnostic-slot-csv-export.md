# ADR-015 – Diagnostic Slot Raw-Data CSV Export: HTTP View, Mode-Owned Serialization

**Date:** 2026-09-24 **Status:** Proposed — draft, pending human review before
`TASK-0038` moves `review` -> `todo` (Phase 0's own draft-ADR procedure: "Any
new ADR starts in a draft state until review confirmed by a human"). **Last
updated:** 2026-09-26 -- Decision 2/3/4/5 below rewritten (delivery mechanism
and `build_pool`'s extension, Decision 1/6 here, are unchanged from the original
2026-09-24 text).

______________________________________________________________________

## Context

`TASK-0038` asks for a way to export one diagnosed slot's full raw regression
input set (every neighbor-offset/day training point, its decomposed weight
components, and all four `regression/` strategies' predictions against reality)
as a CSV a human can drop into a spreadsheet or `pandas` -- something
`sensor.py`'s existing `series`/`accuracy` attributes (ADR-004 §2/§2d) don't
carry today, since those exist to be *plotted*, not analysed raw.

Two delivery mechanisms were on the table, evaluated against this codebase's own
established conventions rather than against CSV-generation itself (which is
trivial, plain Python string formatting, regardless of which mechanism delivers
it):

- **A button/service triggering a clipboard-copy.** Home Assistant has no
  built-in "copy a service's response to the clipboard" affordance, and a
  Markdown dashboard card's raw HTML is sanitized on render -- `onclick` and
  other `on*` attributes are stripped -- so a plain
  `<button onclick="navigator.clipboard.writeText(...)">` embedded there would
  not survive. A genuine one-click copy needs a new custom Lovelace card (a new
  frontend JS resource), calling a service registered with
  `supports_response=SupportsResponse.ONLY`. Nothing in this codebase has ever
  needed frontend code before -- every existing platform
  (`sensor.py`/`select.py`/`button.py`/`datetime.py`) is a plain HA entity
  platform, Python-only.
- **A download link.** `hass.http.register_view` -- a plain Python API, no new
  technology -- can serve the CSV directly on `GET` (`Content-Type: text/csv`,
  `Content-Disposition: attachment`), computed fresh from live coordinator state
  each request, no button/service/caching needed at all. A plain
  `<a href="/api/shady/...">` link in a Markdown card survives HA's sanitizer
  (plain links are preserved; only script-bearing attributes are stripped).

The download link needs no new technology and stays inside this integration's
Python-only footprint, matching this codebase's own established preference for
**entities/plain HA mechanisms over ad-hoc service+frontend combinations** --
the `shady.select_diagnostic_slot` service -> `datetime`/`button` entity
migration `__init__.py`'s own header comment documents is exactly this kind of
call, decided the same way once already, and ADR-004's own "thin entity glue"
framing (`sensor.py`'s attributes exist so an external dashboard tool does the
actual rendering, not this integration) generalizes cleanly to "thin HA glue,
full stop" here: this integration computes and formats; it does not grow a
frontend.

**Human decision (2026-09-24):** the download link. A new ADR, with minor
amendments to existing ones (ADR-000 §3's module diagram; a cross-reference in
ADR-004), rather than folding this into either of those documents outright --
this is a new kind of surface for this codebase (an HTTP view; nothing today
registers one), not a same-shape extension of `sensor.py`'s existing
attribute-exposing pattern, and deserves its own record for that reason. Scope:
**one `sensor_id` per export**, not every entity in one file -- a human
debugging "why did string 0's fit look weird" wants that string, not every
entity's data interleaved in one file.

**Second round of context (2026-09-26), before implementation began:** ADR-013
sketches two further diagnostic modes -- `compare_regressions_daily` (288 slots
x 4 methods, no single training pool the way one diagnosed slot has) and
`compare_providers_daily` (varies the provider, not the regression method, no
weight breakdown or regression training data in the same sense at all). Their
raw-data shapes are fundamentally different from `CompareRegressionsMode`'s own
-- ADR-013 §1 says so explicitly, which is exactly why `DiagnosticResult` stays
opaque (`state`/`attributes`, ADR-004 §2b) rather than a shared schema. A CSV
export tied to one fixed four-section schema, as originally drafted here, would
not generalize to either sketched mode without either forcing empty/misleading
columns onto them or duplicating the whole delivery mechanism per mode. The
decision below reworks §2-§4 accordingly; §1 (delivery mechanism) and §5/§6
(weight-breakdown extension to `build_pool`) are unchanged from the original
decision.

______________________________________________________________________

## Decision

### 1 — A new `HomeAssistantView`, registered from `__init__.py`

Unchanged from the original decision. `requires_auth = True`; registered during
`async_setup_entry` in `__init__.py`, the same place platforms are forwarded
today (ADR-000 §3's `init -.-> entity_glue` edge, extended rather than
replaced).

### 2 — `DiagnosticMode` gains one more optional method: `export_csv`

Mirrors `extra_fit()`'s own established pattern in `diagnostics/base.py` exactly
-- an optional capability, base-default `None` ("not supported"), every mode
free to override it or not:

```python
def export_csv(self, sensor_id: str) -> str | None:
    """Optional. A raw-data CSV export of sensor_id's own current
    diagnosed state, for a human to analyse -- one of this mode's own
    declared sensor_ids() (ADR-004 §5). Returns None if sensor_id is
    not one of this mode's own, or if this mode does not support
    export at all. Base default: None, the same role None already
    plays for extra_fit()."""
    return None
```

`CompareRegressionsMode` overrides it with this task's own four content sections
(`# metadata`/`# training_pool`/`# predictions`/`# prediction_inputs`, unchanged
from the original schema, `TASK-0038`). A future
`compare_regressions_daily`/`compare_providers_daily` overrides it with whatever
sections make sense for *that* mode's own data -- a day-long per-slot table, no
weight breakdown, no neighbor offsets -- or does not override it at all if
export isn't wanted for that mode yet. There is deliberately **no** standalone
`diagnostics/export.py` module (the original draft's design) -- the export
content is exactly as mode-owned as `compute()`/`extra_fit()` already are, so it
lives beside them, on the mode itself, not in a sibling module.

**Amends ADR-013 §3.** That document currently states no `diagnostics/base.py`
change is needed to support either sketched mode. This `export_csv` addition is
exactly such a change -- small, optional, additive (every existing mode keeps
working via the base-default `None`), but real. ADR-013 §3's claim is narrowed
by this ADR to "no change to `DiagnosticResult`'s shape," which remains true.

### 3 — A shared, format-only helper on `DiagnosticMode`, not a shared schema

Mirrors `_xy_series_entry`'s own placement rationale precisely (a
`@staticmethod` on the base class specifically so every mode gets identical
mechanics for free without importing a sibling mode's module): a new
`_write_csv_sections(sections: list[tuple[str, list[dict[str, str]]]]) -> str`
static helper handles only the low-level, mode-agnostic mechanic -- a `# name`
marker line, a header row, the data rows, a blank line, repeated per section --
never the column *content*, which stays entirely each mode's own.
`CompareRegressionsMode.export_csv` builds its own four `(name, rows)` pairs and
passes them through this one shared formatter; a future mode does the same with
its own sections.

**Every export's first section is `# diagnostic_mode`, one column, one row** --
`diagnostic_mode,<the mode's own registry name>` (ADR-013 §2's
`_diagnostic_modes` registry key, e.g. `compare_regressions`) -- ahead of
`# metadata`, not folded into it. Identifying which mode produced a file has to
come before anything else, including before a generic reader can know how to
interpret `# metadata`'s own fields (different modes' metadata may differ too),
and keeping it in the exact same `#`-marker/header/row shape as every other
section (rather than a bare, differently-shaped first line) means a fully
generic parser needs zero special-casing for it -- section 0 is exactly as
uniform as section 1 onward.

### 4 — `http_export.py`'s view is genuinely mode-agnostic

Resolves the config entry, then the *active* `DiagnosticMode`
(`coordinator.diagnostic_mode()`), then reads `sensor_id` from the query string
(`/api/shady/{config_entry_id}/export_csv?sensor_id=...` -- not
`?string=<index>` as the original draft had; that assumed string-scoping, which
`compare_providers_daily` explicitly is not, ADR-013 §1) and calls
`mode.export_csv(sensor_id)`. `HTTPStatus.NOT_FOUND` if that comes back `None`
(unknown `sensor_id`, or this mode doesn't support export). Zero mode-specific
code in the HTTP layer -- the same generalization ADR-004 §5's fourth Amendment
already forced onto `compute()`'s own output shape, applied one layer further
out.

### 5 — Fixture-test replay: generic parse, generic dispatch, mode-owned interpretation only

`TASK-0038`'s own fixture-regression-test design (human addition, 2026-09-24) is
reworked the same way, splitting into three layers with the boundary drawn at
exactly the same place as §2/§3 above:

- **Generic, written once, reused by every mode forever:** a CSV-section parser,
  `parse_csv_sections(text: str) -> list[tuple[str, list[dict[str, str]]]]` --
  splits on the `#`-marker lines, `csv.DictReader` per section, returns the
  sections in file order with their names. This is the read-side mirror of §3's
  `_write_csv_sections`; together they are the only two places the file *format*
  (as opposed to its content) is encoded at all. Test-only code (`tests/`), not
  production -- production never needs to read its own output back.
- **Generic, written once:** dispatch by the leading `# diagnostic_mode`
  section's own value, against a small
  `dict[str, Callable[[list[tuple[str, list[dict[str, str]]]]], str]]` registry
  in `tests/test_csv_regression_fixtures.py` -- one entry per mode that has
  fixture-replay support, today just
  `"compare_regressions": _replay_compare_regressions`. An unregistered mode
  name fails the fixture loudly (naming the file and the unknown mode), not
  silently.
- **Mode-owned, one function per mode:** `_replay_compare_regressions(sections)`
  is the *only* mode-specific test code this design needs. It looks up
  `"metadata"`/`"training_pool"`/`"prediction_inputs"` by name (not position --
  robust to a future section being added or reordered) from the generic parsed
  structure, reconstructs the real typed inputs
  `CompareRegressionsMode.export_csv` itself needs, calls it, and returns the
  fresh CSV text it produces. A future mode's own fixture support is exactly one
  such function plus one registry line -- no change to the parser, the
  dispatcher, or the comparator below.

**Comparison is also fully generic**, a consequence of both the original and the
regenerated CSV existing as the same `list[tuple[str, list[dict[str, str]]]]`
shape once parsed: `compare_sections(old, new, rel_tol) -> list[str]` (a list of
human-readable mismatch descriptions, empty if none) walks both structures
section by section, row by row, field by field, attempting `float()` on each
value and falling back to exact string equality -- no section or field name is
special-cased anywhere in this function. This also simplifies the original
"write to disk, compare, delete on match" design from the previous round: since
comparison happens on the **parsed, in-memory** structures, nothing needs to
touch disk on a passing run at all -- only on a **mismatch** does the
regenerated CSV get written, to
`tests/fixtures/csv_regression/_generated/<same filename as the fixture>`, as
the maintainer's ready-made replacement. A passing run is now zero I/O beyond
reading the fixture itself, not "write then delete."

### 6 — `build_pool` gains a second, optional return value — CSV-only

Unchanged from the original decision (2026-09-24). `regression/base.py`'s
`build_pool` gains an optional second return value via a keyword-only
`return_weight_breakdown: bool = False` flag, carrying the decomposed
`magnitude_weight`/`time_weight`/`recency_weight`/neighbor exclusion-or-scale
components current callers never see -- no existing caller's signature changes.
`CompareRegressionsMode.export_csv` is the only caller that ever passes `True`.

______________________________________________________________________

## Amendments to Existing ADRs

**ADR-000 §3** (module boundaries and dependency direction): the diagram gains
`http_export.py` as a new node alongside `entity_glue`
(`http_export --> coordinator`, `init -.-> http_export`, the same dashed "not a
Python import, HA's own forwarding-equivalent registration" style the existing
`init -.-> entity_glue` edge already uses). **Revised from the original
2026-09-24 amendment:** no `diagnostics/export.py` node -- Decision 2 above
places the export logic on `CompareRegressionsMode` itself (inside the existing
`diagnostics/` node, no new edge) plus a shared static helper on
`DiagnosticMode` in `diagnostics/base.py` (likewise already inside that node) --
`http_export --> diagnostics` remains the only new edge this ADR adds to the
diagram.

**ADR-004** (diagnostics sensors): a cross-reference note near §5's "thin entity
glue" framing, pointing to this document -- the CSV export reads the same
`CompareRegressionsMode`-gathered data `sensor.py`'s attributes do, but is not
itself a `DiagnosticMode` concern in the sense of feeding
`DiagnosticSensorResult`, and does not change that shape. Unchanged from the
original 2026-09-24 amendment.

**ADR-013 §3** (whole-day diagnostic modes): narrowed, per Decision 2 above --
`diagnostics/base.py` does gain a change to support future modes cleanly (the
new optional `export_csv` method and its shared `_write_csv_sections` helper),
though `DiagnosticResult`'s own shape still does not need to change, which is
what that section's claim was actually protecting.

______________________________________________________________________

## Consequences

- **New technology surface, deliberately the smallest available one.**
  `hass.http.register_view` is a plain, well-established HA API, not a new
  dependency -- but it is a genuinely new *kind* of registration for this
  codebase, worth this document existing to record rather than being folded
  silently into an existing ADR.
- **`build_pool`'s signature grows by one optional parameter.** Every existing
  call site is unaffected (default `False`); only
  `CompareRegressionsMode.export_csv` ever passes `True`.
- **Every future diagnostic mode's export support, and its fixture-test replay
  support, costs exactly one method override plus one small test function plus
  one registry line each** -- no change to `http_export.py`,
  `diagnostics/base.py`'s shared helper, the fixture parser, the dispatcher, or
  the comparator, for any mode added after this one.
- **Auth is HA's own, not reinvented.** `requires_auth = True` delegates to HA's
  existing session/long-lived-token auth -- no new credential surface this
  integration itself has to manage.
- **Not addressed here, left to `TASK-0038`'s own Acceptance Criteria:** the
  exact URL shape, filename convention, and `CompareRegressionsMode`'s own CSV
  column-level schema -- this document's claim is architectural (view, not
  service/frontend; mode-owned serialization via one optional method, not a
  shared module or a shared schema; `build_pool` extended, not duplicated;
  fixture replay split into generic parse/dispatch/compare plus mode-owned
  interpretation only), not a full implementation spec.
