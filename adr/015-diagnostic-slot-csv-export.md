# ADR-015 – Diagnostic Slot Raw-Data CSV Export: HTTP View, Mode-Owned Serialization

**Date:** 2026-09-24 **Status:** Accepted — confirmed by human, 2026-09-27,
alongside three further amendments (§4a/§5/§7 below) requested at confirmation
time; `TASK-0038` moves `review` -> `todo` the same day (Phase 0's own draft-ADR
procedure: "Any new ADR starts in a draft state until review confirmed by a
human" — satisfied). **Last updated:** 2026-09-29 (§9, new: `export_csv`
dispatched via `get_instance(hass).async_add_executor_job`, fixing a
blocking-recorder-call-on-the-event-loop regression §8's own new signed link
made reachable for the first time) / 2026-09-29 (§8, new: `export_csv_url`
signed-link sensor attribute, closing the gap where a plain browser click on the
§1/§2 download link 401s regardless of frontend login state -- also amends §1's
Consequences bullet) / 2026-09-29 (Amendment at the end: fit-reproducibility
metadata) / 2026-09-27 -- §4a (mode-override query parameter), §5
(fixture-replay's own reader returns a `dict`, not a `list[tuple]`), and §7
(test package structure) added at confirmation time. Decision 2/3/4/5's
2026-09-26 rewrite (delivery mechanism and `build_pool`'s extension, Decision
1/6, unchanged since the original 2026-09-24 text) otherwise stands as written.

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

**Every export's first section is `# diagnostic_mode`, one column, one row** (a
fixture file may add an optional second column, `expected`, §5a -- an export
never does) -- `diagnostic_mode,<the mode's own registry name>` (ADR-013 §2's
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

### 4a — Amendment (2026-09-27): an optional `mode` query parameter, defaulting to the configured mode

`GET /api/shady/{config_entry_id}/export_csv?sensor_id=...&mode=...` -- `mode`
is optional and names a registered `DiagnosticMode` by its own registry `key`
(§3's `# diagnostic_mode` value, e.g. `compare_regressions`), independent of
whichever mode `select.py` currently has *active*. Omitted, it defaults to the
coordinator's own currently configured mode (`coordinator.diagnostic_mode()`) --
the view's original, and still default, behavior. A registered-but-not-
currently-selected mode's data should be exportable without first switching the
live selection just to read it back afterward: a human comparing two modes' raw
inputs side by side, for instance, would otherwise have to flip `select.py` back
and forth between requests, silently changing what every other diagnostic sensor
shows in the meantime.

Resolved via a new
`ShadyCoordinator.diagnostic_mode_by_key(key: str) -> DiagnosticMode | None`
accessor (`coordinator.py`) -- any *registered* mode, not just the active one,
mirroring `diagnostic_mode()`'s own "unregistered key (including `\"off\"`)
behaves as nothing to export" contract. Not added to `ShadyCoordinatorLike`
(`coordinator_like.py`): no `DiagnosticMode` itself ever needs to look up a
*different* mode by key, only `http_export.py`, which already holds a real
`ShadyCoordinator` reference (§1's `http_export --> coordinator` edge is a
genuine import, not the `TYPE_CHECKING`-only one `diagnostics/` uses), so
extending the narrower Protocol has no reason to. `HTTPStatus.NOT_FOUND` for an
unresolvable `mode` value, the same contract as an unresolvable `sensor_id` --
both cases collapse to "nothing to export for what was asked," indistinguishable
from the HTTP caller's own point of view.

### 5 — Fixture-test replay: generic parse, generic dispatch, mode-owned interpretation only

`TASK-0038`'s own fixture-regression-test design (human addition, 2026-09-24) is
reworked the same way, splitting into three layers with the boundary drawn at
exactly the same place as §2/§3 above:

- **Generic, written once, reused by every mode forever:** a CSV-section parser,
  `parse_csv_sections(text: str) -> dict[str, list[dict[str, str]]]` -- splits
  on the `#`-marker lines, `csv.DictReader` per section, keyed by section name
  (`dict`, not the original `list[tuple[str, ...]]` draft -- **Amendment,
  2026-09-27:** a `dict` makes section-name uniqueness structural rather than
  merely conventional: building it raises loudly, naming the file and the
  duplicated section, on a second occurrence of the same `#`-marker name, rather
  than silently keeping the first/last one and losing the other -- exactly the
  "fails the test loudly, naming the file and the problem" standard this
  document's fixture design already holds every other malformed- fixture case
  to. Every real export this codebase produces (§3's `_write_csv_sections`,
  still `list[tuple[str, rows]]` on the *write* side, order still mattering
  there for a human reading the file top to bottom) only ever writes each
  section name once, so this is never expected to fire on a genuine export -- it
  exists to catch a hand-edited or corrupted fixture file before it silently
  passes with half its data discarded, which a `list`-of- duplicates would have
  allowed by construction.) This is the read-side mirror of §3's
  `_write_csv_sections`; together they are the only two places the file *format*
  (as opposed to its content) is encoded at all. Test-only code (`tests/`), not
  production -- production never needs to read its own output back. Losing the
  write side's own section *order* is not a real loss here -- §3's own fixed
  section order (`diagnostic_mode`, then a mode's own sections in the order it
  built them) is never itself asserted on by the fixture mechanism, only each
  section's own name-addressed content is.
- **Generic, written once:** dispatch by the leading `# diagnostic_mode`
  section's own value, against a small
  `dict[str, Callable[[dict[str, list[dict[str, str]]]], str]]` registry in
  `tests/diagnostics/test_csv_regression_fixtures.py` -- one entry per mode that
  has fixture-replay support, today just
  `"compare_regressions": _replay_compare_regressions`, imported from
  `tests/diagnostics/test_compare_regressions.py` (§7 below: that mode's own one
  file, not a separate module). An unregistered mode name fails the fixture
  loudly (naming the file and the unknown mode), not silently.
- **Mode-owned, one function per mode:** `_replay_compare_regressions(sections)`
  is the *only* mode-specific test code this design needs, living in
  `CompareRegressionsMode`'s own test file (§7) alongside every other test of
  that mode. It looks up `"metadata"`/`"training_pool"`/`"prediction_inputs"` by
  name (not position -- robust to a future section being added or reordered, and
  now structurally guaranteed unique by the parser's `dict` shape, §5's own
  Amendment above) from the generic parsed structure, reconstructs the real
  typed inputs `CompareRegressionsMode.export_csv` itself needs, calls it, and
  returns the fresh CSV text it produces. A future mode's own fixture support is
  exactly one such function, in that mode's own test file, plus one registry
  line in the generic runner -- no change to the parser, the dispatcher, or the
  comparator below.

**Comparison is also fully generic**, a consequence of both the original and the
regenerated CSV existing as the same `dict[str, list[dict[str, str]]]` shape
once parsed: `compare_sections(old, new, rel_tol) -> list[str]` (a list of
human-readable mismatch descriptions, empty if none) walks both structures
section by section, row by row, field by field, attempting `float()` on each
value and falling back to exact string equality -- no section or field name is
special-cased anywhere in this function. This also simplifies the original
"write to disk, compare, delete on match" design from the previous round: since
comparison happens on the **parsed, in-memory** structures, nothing needs to
touch disk on a passing run at all -- only on a **mismatch** does the
regenerated CSV get written, to
`tests/fixtures/csv_regression/_generated/<fixture folder>/<same filename as the fixture>`,
as the maintainer's ready-made replacement. A passing run is now zero I/O beyond
reading the fixture itself, not "write then delete."

#### 5a — Amendment (2026-09-27): two fixture folders, and an optional `expected` column

**Two folders**, both replayed by the same runner: `curated/` holds real exports
a maintainer downloaded and dropped in by hand (the regression net proper);
`synthetic/` holds fixtures the developers wrote -- exports of the test
scenarios, some deliberately tampered -- to test *the test system itself* (that
a correct fixture passes and a wrong one is caught). Keeping them apart means a
red `synthetic/` case indicts the mechanism while a red `curated/` case indicts
the regression math, and a maintainer never has to wonder whether a file in
`curated/` was ever a real export.

**`expected`, an optional second column of the `# diagnostic_mode` row** --
`diagnostic_mode,expected` / `compare_regressions,FAIL`. `PASS` or `FAIL`;
absent or blank means `PASS`, so **exports never write it** (production
`export_csv` emits the one-column shape of §3 unchanged) and a real export is a
`PASS` fixture with no editing. `FAIL` marks a fixture that must be *rejected*
(the regenerated CSV disagrees, or its mode is unregistered): the test passes
only if the check genuinely fails, and fails if the fixture unexpectedly replays
cleanly. The column lives on the `# diagnostic_mode` row because that is already
the one row the generic runner reads before dispatching, so no new section or
format rule is needed; the runner strips it before comparison (the regenerated
export never has it). An `expected` value other than `PASS`/`FAIL` fails loudly
naming the file. A fixture that cannot be parsed at all (duplicate section, no
`# diagnostic_mode`) cannot declare an `expected`, so those failure modes are
covered by unit tests against temporary files instead.

**What a replay checks** (rewritten by the 2026-09-29 Amendment below; the
original text listed `pv_corrected`, `predicted` and the metadata scalars as
*echoed, not checked*): `_replay_compare_regressions` runs the real
`apply_training_corrections`, `fit_string_model` (all four strategies) and
`predict_string_forecast` from the file alone, so `pv_corrected`, every
`predicted`, `accuracy`, the weight decomposition, `is_valid` and
`sample_date`/`day_age` are all recomputed and compared. Still taken on trust:
the raw `fc`/`pv`/`temperature` readings and `fc_selected`/`pv_selected`
(inputs, not derivations) and `target_cell_temperature` (how the coordinator
resolves it is not part of the fit).

### 6 — `build_pool` gains a second, optional return value — CSV-only

Unchanged from the original decision (2026-09-24). `regression/base.py`'s
`build_pool` gains an optional second return value via a keyword-only
`return_weight_breakdown: bool = False` flag, carrying the decomposed
`magnitude_weight`/`time_weight`/`recency_weight`/neighbor exclusion-or-scale
components current callers never see -- no existing caller's signature changes.
`CompareRegressionsMode.export_csv` is the only caller that ever passes `True`.

**Decomposition point (implementation-time clarification, 2026-09-27, resolved
against `TASK-0038`'s own sample CSV rather than left ambiguous):** the returned
`magnitude_weight` component is captured *before* ADR-011 §2's
neighbor-exclusion zeroing, not after -- `neighbor_excluded` is its own,
independent factor, so
`combined_weight = magnitude_weight * time_weight * recency_weight * (not neighbor_excluded) * is_valid`
holds as a genuine decomposition a reader can multiply back together, rather
than one column silently already absorbing another's effect (which `TASK-0038`'s
own sample data -- a row with a nonzero `magnitude_weight` and
`neighbor_excluded=1` alongside a `combined_weight` of `0.0` -- requires: a
post-exclusion `magnitude_weight` would have shown `0.0` there too,
indistinguishable from a row excluded for a genuinely different reason). This
changes nothing about `weight`/`confidence` on the returned `SamplePool` itself,
which still reflects the real, post-exclusion per-cell weight exactly as before.

### 7 — Amendment (2026-09-27): test package structure mirrors `diagnostics/` itself

`tests/` gains a `tests/diagnostics/` sub-package (its own `__init__.py`),
mirroring `custom_components/shady/diagnostics/` being a package rather than a
single module -- the same convention ADR-000 §6 records a general version of.
`tests/test_diagnostics_base.py`/`tests/test_diagnostics_compare_regressions.py`
move into it unchanged in content, renamed `tests/diagnostics/test_base.py`/
`tests/diagnostics/test_compare_regressions.py`: **one file per diagnostic
mode** (today, only `CompareRegressionsMode`'s own file; `DiagnosticMode`'s
shared base-class mechanism keeps its own file, the same "generic mechanism gets
its own home, mode-owned content gets its own" split §2/§3/§5 above already
apply to the *production* code). `TASK-0038`'s own new tests follow this
directly, not as a special case:

- `CompareRegressionsMode.export_csv`'s own direct unit tests (the Acceptance
  Criteria below: no-baseline -> `None`, not-yet-elapsed -> blank
  `pv_selected`/`accuracy`, unrecognized `sensor_id` -> `None`, the
  `combined_weight` reconstruction identity) and `_replay_compare_regressions`
  (§5 above) both live in `tests/diagnostics/test_compare_regressions.py` --
  everything about this one mode, in its one file, exactly as it already held
  everything about `compute()`/`extra_fit()`/`sensor_ids()` before this task.
- The fully generic fixture mechanism (`parse_csv_sections`/`compare_sections`,
  §5 above) lives in a new, top-level, non-test-prefixed
  `tests/csv_fixture_support.py` -- **not** nested under `tests/diagnostics/`,
  since the mechanism itself knows nothing about diagnostic modes, only the
  generic `# name`-marker-section file format `_write_csv_sections` happens to
  be the first writer of; a future package adopting the same fixture convention
  reuses it directly, the same reason `tests/fixtures/csv_regression/` itself
  already stays top-level rather than nesting under `tests/diagnostics/` too.
  Not embedded directly in the parametrized-runner test file either,
  specifically so a mode's own test file (`test_compare_regressions.py`) can
  import it too, for structural self-checks on its own `export_csv` output,
  without creating an import cycle between two `test_*.py` files (the runner
  file needs to import each mode's own replay function; a mode's own file
  importing the parser back from the runner file would close that loop the wrong
  way).
- `tests/diagnostics/test_csv_regression_fixtures.py` holds only the generic
  dispatch registry and the `glob`-based parametrized runner over
  `tests/fixtures/csv_regression/{curated,synthetic}/*.csv` (the fixture root
  stays top-level -- it is not diagnostics-specific in principle, even though
  every mode with fixture support today happens to be one; the two folders are
  the 2026-09-27 amendment below).
- `http_export.py`'s own tests (`tests/test_http_export.py`) stay top-level, not
  nested under `tests/diagnostics/` -- `http_export.py` itself is a top-level
  module (§1/§4), not part of the `diagnostics/` package, so its test file
  mirrors that placement the same way every other module's test file already
  mirrors its own.

Not a retroactive reorganization of every other package's own tests
(`regression/`'s own `tests/test_regression.py` stays exactly as it is, one file
for the whole package, covering all four strategies via ADR-000 §6's
shared-scenario-fixture convention already) -- this amendment establishes the
convention for a package gaining its first genuinely mode-differentiated test
content (fixture-replay support, per-mode by construction), not a mandate to
split every existing single-file test module that happens to sit next to a
multi-file production package.

### 8 — Amendment (2026-09-29): `ShadyDiagnosticsSensor` exposes a signed `export_csv_url` attribute

**Reason:** §1's "Auth is HA's own, not reinvented" consequence and §2's
original "a human drops the link into a Markdown card" delivery picture both
implicitly assumed that being logged into the HA frontend was enough to
authenticate a plain `<a href="/api/shady/...">` click. It is not: Home
Assistant's own `homeassistant.components.http.auth` middleware authenticates a
request exactly two ways -- an `Authorization: Bearer <token>` header, or a
`?authSig=...` signed-path query parameter (`async_validate_auth_header`/
`async_validate_signed_request`; a Supervisor Unix-socket request is the only
other branch) -- never a session cookie. A plain browser navigation (address
bar, bookmark, or a dashboard's own `<a href>`) can supply neither on its own,
so `requires_auth = True` rejects every such request regardless of frontend
login state, logged by HA core as "Login attempt or request with invalid
authentication." Confirmed by reading `homeassistant/components/http/auth.py`
directly (`home-assistant/core`, `dev` branch) rather than assumed.

**Decision:** `sensor.py`'s `ShadyDiagnosticsSensor.extra_state_attributes`
gains one new key, `export_csv_url` -- present whenever `self._result()` is not
`None` (i.e. whenever `native_value` is not `"disabled"`/`"unavailable"`), built
from `homeassistant.components.http.auth.async_sign_path` against
`http_export.py`'s own URL, with an explicit `mode=` query parameter (§4a) so
the link keeps pointing at the mode that actually produced it even if the active
mode changes before it's clicked. A dashboard's own Markdown card can render
`<a href="{{ state_attr('sensor.xxx', 'export_csv_url') }}">Download CSV</a>`
and have it actually work, closing the gap §1/§2 left open, still without any
new frontend technology (a signed path is plain HA API, the same "smallest
available surface" §1's own Consequences bullet already chose).

- **Thirty-minute expiration** (`_EXPORT_CSV_URL_EXPIRATION`) -- refreshed every
  coordinator tick regardless (five minutes,
  `coordinator._handle_intraday_tick`), so this is slack past that, not a tight
  window; long enough for a human to notice the attribute (e.g. in Developer
  Tools -> States) and click it, short enough that a copy of the link surviving
  in a screenshot or log goes stale soon after.
- **Present for every mode, not only ones that override `export_csv`.**
  `sensor.py` does not call `mode.export_csv(sensor_id)` itself to decide
  whether to include the link -- that would make it a second real caller of that
  method besides `http_export.py` (§2's own docstring contract) and would redo
  the same CSV-building work every coordinator tick just to answer a yes/no
  question. A mode that does not support export simply 404s once the link is
  actually clicked, the same outcome a hand-constructed URL for such a
  `sensor_id` already produces today (§4: "indistinguishable from each other by
  design").
- **No change to `http_export.py` itself, for auth.** Signed-path validation is
  handled entirely by HA's own auth middleware before the view's `get()` ever
  runs -- `requires_auth = True` already covers it, unmodified from §1. (§9
  below does change `get()` itself, but for an unrelated reason -- a blocking-
  call fix this amendment's own signed link is what first made reachable, not
  anything about auth.)
- **Amends §1's Consequences bullet** ("Auth is HA's own, not reinvented" reads
  "delegates to HA's existing session/long-lived-token auth" -- narrowed by this
  amendment to "bearer-token or signed-path auth," since no session/cookie path
  actually exists for this view).

**Decided by:** human (the auth failure report and the choice of the signed-path
fix over a documentation-only fix or a manually-supplied long-lived-token
workaround); Lead Agent (expiration value, `mode=` inclusion, and the "present
regardless of override" decision) -- **to be confirmed by the human at review.**

### 9 — Amendment (2026-09-29): `export_csv` dispatched off the event loop, on the recorder's own executor

**Reason:** §8's signed link let a request reach this view's `get()` body for
the first time (every earlier request had 401'd at HA's own auth middleware
first, per §8's own Reason) -- and the first real one, against a real Home
Assistant install with a diagnosed slot whose cached pool still had a gap to
fill, tripped HA's own asyncio blocking-call detector
(`homeassistant.util.loop.raise_for_blocking_call`), then failed the recorder
query outright. `get()` called `mode.export_csv(sensor_id)` directly, on the
event loop (an aiohttp handler's own body always is) -- and
`CompareRegressionsMode.export_csv` -> `_gather_pool` ->
`cache.get_pinned_slot_pool` can reach `_validate_range`'s `_fetch_and_store` ->
`coordinator._fetch_fn` -> `_fetch_actual_yield_statistics` -> the recorder's
own `statistics_during_period` -- exactly the blocking recorder read
`coordinator.py`'s own module docstring already documents and dispatches,
everywhere else it can be reached (`_refit_sync`/`_async_intraday_tick` via
`get_instance(hass). async_add_executor_job`; `diagnostic_result()`'s lazy
cache-miss `compute()` call via the same pattern,
`_async_recompute_diagnostic_result`, when reached on the event loop).
`http_export.py`'s own `get()` was the one caller of anything in this same
dependency chain that never went through that pattern at all -- not a gap this
ADR's original §1/§4 decision considered, since neither mentions
`coordinator.py`'s recorder-executor invariant.

**Decision:** `get()` dispatches `mode.export_csv(sensor_id)` via
`get_instance(hass).async_add_executor_job(mode.export_csv, sensor_id)` --
`homeassistant.components.recorder.get_instance`, the exact same import and call
shape `coordinator.py` already uses -- and awaits the result, rather than
calling it inline. Unlike `diagnostic_result()`'s cache-miss handling (which can
return `None`/stale-cached and let a later poll pick up the fresh result), a
`GET` request has no "later poll" to defer to, so this always dispatches,
whether or not the pool happens to be fully cached already -- simpler than
`diagnostic_result()`'s own `_running_on_the_event_loop()` branch, and correct
either way: `get_instance(hass).async_add_executor_job` on an already-cached,
non-blocking `export_csv` call costs one thread hop, not a blocking read.

- **No change to `DiagnosticMode.export_csv`'s own contract or signature** (§2)
  -- still a plain synchronous method, callable directly in tests/fixture replay
  (§5/§7) exactly as before; only its one real caller's own dispatch changed.
- **Test coverage:** `tests/test_http_export.py`'s
  `TestExportRunsOffTheEventLoop` monkeypatches `http_export.py`'s own
  `get_instance` with a recording stand-in (still calling through, so the
  response itself stays exercised end-to-end) and asserts `get()` reaches
  `mode.export_csv` only via that dispatch, not directly -- this hand-rolled
  test harness has no way to detect an actual blocking call the way a real HA
  install's own detector does (ADR-000 §6), so the regression this amendment
  fixes could not have been caught by asserting on the CSV content alone.

**Decided by:** human (reported the production traceback); Lead Agent (root
cause and the dispatch fix, mirroring `coordinator.py`'s own established
pattern) -- **to be confirmed by the human at review.**

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
`DiagnosticMode` in `diagnostics/base.py` (likewise already inside that node).
**Amendment, 2026-09-27:** one further new edge, `diagnostics --> regression` --
`CompareRegressionsMode.export_csv` calls `regression/base.py`'s `build_pool`
directly (with `return_weight_breakdown=True`, §6 above), a layer below
`string_computation.fit_string_model`'s own existing wrapper, since the weight
breakdown is method-independent (ADR-001 §2). (*2026-09-29:* `# predictions` no
longer comes from `extra_fit()`'s cache -- see the Amendment at the end of this
document.) `http_export --> diagnostics` and `diagnostics --> regression` are
the two new edges this ADR adds to the diagram in total.

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
  own bearer-token or signed-path auth (§8's 2026-09-29 Amendment narrows this
  from the original "session/long-lived-token auth" wording -- no session/
  cookie path actually exists for this view) -- no new credential surface this
  integration itself has to manage.
- **Not addressed here, left to `TASK-0038`'s own Acceptance Criteria:** the
  exact URL shape, filename convention, and `CompareRegressionsMode`'s own CSV
  column-level schema -- this document's claim is architectural (view, not
  service/frontend; mode-owned serialization via one optional method, not a
  shared module or a shared schema; `build_pool` extended, not duplicated;
  fixture replay split into generic parse/dispatch/compare plus mode-owned
  interpretation only), not a full implementation spec.

______________________________________________________________________

## Amendment — 2026-09-29

**Reason:** The export was meant to carry "all meta data needed to calculate the
fitting models", but three gaps meant it did not, and §5a recorded the fixture
replay's resulting blind spot rather than closing it:

1. `# metadata` omitted four `StringComputationConfig` scalars the fit chain
   consumes -- `converter_limit_w`, `coefficient_per_c`,
   `provider_already_corrects`, `rated_dc_capacity_wp` (the first three feed
   both `apply_training_corrections` and `predict_string_forecast`). The other
   inputs (five `RegressionSettings` scalars, `temperature_tier`, `window_days`,
   raw fc/pv/temperature, `fc_selected`, `target_cell_temperature`) were already
   present.
1. `# predictions` was read from `cache.diagnostic_fit(sensor_id)`, keyed by
   `sensor_id` alone: not invalidated by `pin_diagnostic_slot` /
   `clear_diagnostic_slot`, and never populated for a registered but inactive
   `mode` (§4a). It could therefore describe a different slot than the
   `# training_pool` gathered fresh beside it.
1. Consequently the replay had to stub `apply_training_corrections`, hard-code
   `converter_limit_w=None` / `coefficient_per_c=0.0` /
   `provider_already_corrects=False` / `rated_dc_capacity_wp=None`, and inject
   the recorded `predicted` values -- and a hand-written `synthetic/` fixture
   (`wls2=450.0` on a pool with no valid data, where every strategy passes the
   forecast through at 500.0) went unnoticed for that reason.

**Decision:**

- **`# metadata` gains four columns**, appended after `max_uplift_c` in
  `StringComputationConfig` field order: `converter_limit_w`,
  `coefficient_per_c`, `provider_already_corrects`, `rated_dc_capacity_wp` (19
  columns total). Floats are `repr()`-level, the bool is `true`/`false`, and
  `None` is a blank -- the same convention `temperature_tier` already uses in
  this one-row table. A new column rather than a new section: all four are
  always-present scalars of the same one string, exactly the case §3 gives for
  the wide-row shape.
- **`# predictions` is computed at export time from the exported pool**
  (`_predict_all_methods`, the same function `extra_fit()` uses), not read from
  the cache, so the section is reproducible from the file's own
  `# training_pool` by construction. `sensor.py`'s own `series`/`accuracy` keep
  reading the cache (unchanged). If fitting raises, the export still returns its
  other sections with an empty `# predictions` and logs the exception -- the
  export exists to explain a strange fit and must not turn into an HTTP 500 on
  exactly that input. Cost: one single-slot fit per strategy per request, the
  same work `extra_fit()` already does per string per tick.
- **The replay runs the real chain** (§5a rewritten above): no monkeypatching of
  `string_computation`, no injected `predictions`, config read from
  `# metadata`.
- **No backward compatibility shim.** A fixture lacking any of the four columns
  predates this amendment and is rejected with an error naming them and telling
  the maintainer to re-export -- never silently replayed against defaulted
  config. The six existing `synthetic/` fixtures were migrated (their scenarios
  used exactly the defaults, so the values appended are the ones they ran with);
  `curated/` held none.
- `compare_sections`' 1e-9 relative tolerance is unchanged. Measured: all four
  strategies' predictions move by \<= ~1.2e-15 relative under a reordered
  summation (the platform-dependent part of a BLAS/LAPACK solve), several orders
  of magnitude inside it.

**Decided by:** human (direction, 2026-09-29: "close the blind spot; extend the
export CSV to contain all meta data needed to calculate the fitting models");
Lead Agent (column names/placement, the switch away from the cache, and the
no-shim rejection rule) -- **to be confirmed by the human at review.**
