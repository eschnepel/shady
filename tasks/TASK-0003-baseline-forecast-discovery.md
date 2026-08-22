# Task: Baseline Forecast Discovery & Normalization

- **Status:** done
- **Related ADRs:** [ADR-009, ADR-012 §1, ADR-012 §1a]
- **Dependencies:** [TASK-0001-provider-base-architecture]

## Goal
Implement `providers/discovery.py` + `providers/normalize.py`: scan
`sensor.*`/`weather.*` entities for forecast-shaped attributes, score
candidates, and normalize matches onto one canonical
`list[tuple[datetime, float]]` series — with no per-integration adapter
code.

## Acceptance Criteria
- Given a `sensor.*` entity exposing a `{timestamp: number}`-shaped
  attribute (Forecast.Solar-like) and one exposing a list-of-dicts shape
  (Solcast-like), When discovery scans entities, Then both are recognized
  and scored as candidates (ADR-009 §1).
- Given a `weather.*` entity exposing `sunshine_duration` and another
  exposing `cloud_coverage`, When discovery scans entities, Then both are
  recognized, the cloud-coverage one is inverted by
  `providers/normalize.py` (e.g. `100 - cloud_coverage`), and both are
  labeled distinctly in the candidate list (ADR-009 §1/§3).
- Given a matched candidate of any recognized shape, When
  `providers/normalize.py` processes it, Then the output is the
  canonical `list[tuple[datetime, float]]` series regardless of source
  shape or polarity.
- Given an entity with none of the recognized attribute shapes, When
  discovery scans it, Then it is not surfaced as a candidate (no false
  positive).
- Given the base class's `fetch()`/`forward()` contract from TASK-0001,
  When this provider's `fetch()` is called for a past range and
  `forward()` for the live forward range, Then both go through the same
  canonical-series mapping function (ADR-012 §1 — "one mapping function,
  two callers").

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/providers/discovery.py`
- `custom_components/shady/providers/normalize.py`
- `tests/test_providers_discovery.py` (real `hass` fixture, per ADR-000 §6's exception)
- `tests/test_providers_normalize.py` (zero-mocking)

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0001. -->
- `providers.base.<ProviderBase>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)
- `providers.base.<state_value_mapping_helper>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)
- `providers.base.<series_tuple_assembly_helper>` from `custom_components/shady/providers/base.py` (→ task: TASK-0001-provider-base-architecture)

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- **Testing-environment design note (binding for TASK-0004, which has the
  same real-hass-fixture exception):** no `homeassistant` package is
  installed in this dev/CI sandbox (by design, ADR-000 §6: "pytest
  only — no `pytest-homeassistant-custom-component` needed"). Both new
  modules import `homeassistant.core.HomeAssistant` **only** under
  `TYPE_CHECKING`, relying on `from __future__ import annotations`
  (already project-wide) to keep all annotations lazy strings — so
  neither module has a runtime import of `homeassistant.*`. Tests build
  a small hand-rolled `FakeHomeAssistant`/`FakeState`/`FakeStates` object
  graph (real, concrete Python classes — not `unittest.mock.Mock()`)
  implementing exactly the `hass.states.async_all(domain)` /
  `hass.states.get(entity_id)` / `state.entity_id` / `state.attributes`
  surface these two provider modules actually touch. This is what "a
  real `hass` fixture" (ADR-000 §6) resolves to given the no-HA-package
  sandbox constraint — reuse this exact fixture shape for TASK-0004
  rather than inventing a second one.
- `custom_components/shady/providers/normalize.py`:
  - `TIMESTAMP_KEY_ALIASES: tuple[str, ...]`, `VALUE_KEY_ALIASES: tuple[str, ...]`
    — the ADR-009 §2 key-name alias tables.
  - `BaselineShape = Literal["sensor_dict", "sensor_list", "weather_sunshine", "weather_cloud"]`
    — the four recognized shapes (ADR-009 §1).
  - `CLOUD_COVERAGE_KEYS: tuple[str, ...] = ("cloud_coverage", "cloud_coverage_total")`,
    `SUNSHINE_DURATION_KEY: str = "sunshine_duration"`.
  - `parse_timestamp(raw: Any) -> datetime | None` — ISO8601 parse,
    `None` if unparseable (used both as a shape-validity check and as
    the actual timestamp parser).
  - `invert_cloud_coverage(value: float, *, scale: float = 100.0) -> float`
    — `scale - value` (ADR-009 §1).
  - `resolve_dict_series(raw: Any) -> list[tuple[datetime, float]] | None`
    — `{timestamp: number}` shape (Forecast.Solar-like); `None` if `raw`
    doesn't actually match (not a mapping, unparseable key, non-numeric
    value). Calls `providers.base.assemble_series` internally (ADR-012
    §1a's "one small primitive" reuse).
  - `resolve_list_series(raw: Any, *, value_key_hint: str | None = None) -> list[tuple[datetime, float]] | None`
    — list-of-dicts shape (Solcast-like, or a `weather.*` `forecast`
    entry). Resolves the timestamp key via `TIMESTAMP_KEY_ALIASES`
    always; the value key via `value_key_hint` if given, else
    `VALUE_KEY_ALIASES`. `None` if not actually this shape. Also calls
    `assemble_series` internally.
  - `normalize_candidate_series(shape: BaselineShape, raw: Any) -> list[tuple[datetime, float]]`
    — **the one canonical-series mapping function (ADR-012 §1: "one
    mapping function, two callers").** Dispatches on `shape`; applies
    `invert_cloud_coverage` for `"weather_cloud"`. Never raises — returns
    `[]` if `raw` doesn't match `shape` at call time (ADR-000 §8). Used
    by all three of: `discovery.py`'s candidate scan,
    `BaselineProvider.fetch()`, `BaselineProvider.forward()`.
- `custom_components/shady/providers/discovery.py`:
  - `BaselineCandidate` — frozen dataclass: `entity_id: str`,
    `attribute: str`, `shape: BaselineShape`, `score: float`,
    `label: str`. Labels are exactly `"forecast sensor (timestamp map)"`,
    `"forecast sensor (list)"`, `"sunshine duration"`,
    `"cloud coverage (inverted)"` — the latter two are ADR-009 §3's own
    worked examples, verbatim.
  - `discover_baseline_candidates(hass: HomeAssistant) -> list[BaselineCandidate]`
    — scans `sensor.*` (both `sensor_dict`/`sensor_list` shapes) and
    `weather.*` (both `weather_sunshine`/`weather_cloud` shapes, an
    entity can yield candidates of both kinds from the same `forecast`
    attribute if it carries both keys), returns every recognized
    candidate sorted by `score` descending. **Never auto-selects** — no
    "pick the best one" method exists here by design (ADR-009 §3); the
    config flow (ADR-010, TASK-0009) is responsible for presenting these
    and capturing the user's confirmed choice (or manual fallback).
  - `BaselineProvider(Provider)` — the concrete baseline provider
    (ADR-012 §1). **Constructor signature (load-bearing for TASK-0009/
    TASK-0010):**
    `BaselineProvider(hass: HomeAssistant, entity_id: str, attribute: str, shape: BaselineShape)`
    — takes an **already-confirmed** candidate resolution (design
    decision: `identify()` does not itself run discovery/scoring; it
    only reports back the resolution it was constructed with). Callers
    (TASK-0009's config flow, TASK-0010's coordinator wiring) call
    `discover_baseline_candidates()` separately to get the choices, then
    construct `BaselineProvider` with the user's confirmed
    `(entity_id, attribute, shape)`.
    - `identify(self) -> EntityRef | None` → `EntityRef(entity_id, attribute)`.
    - `fetch(self, start, end) -> list[float | None | str]` — reads the
      live attribute, normalizes via `normalize_candidate_series`, maps
      onto the `[start, end)` 5-minute slot grid (`None` for
      slots the series has no entry for). Matches `cache.py`'s
      `fetch_fn`/TASK-0001's `Provider.fetch` calling convention exactly
      (half-open interval, one value per 5-min slot) — can be wired in
      as a cache's `fetch_fn` directly, per ADR-012 §1.
    - `forward(self, now) -> list[tuple[datetime, float]] | None` — reads
      the live attribute, normalizes via the same
      `normalize_candidate_series` call, filters to `timestamp >= now`.
      Returns `None` only if the entity is currently unresolvable (state
      missing) — an empty/no-match series still returns `None` here since
      there is nothing to push.
  - **Known scope boundary, flagged for TASK-0010:** `fetch()`'s "past
    range" read is, today, still sourced from the **live** attribute
    snapshot (there is no historical archive of past attribute values to
    query) — genuinely queryable per-slot history only exists for
    already-`push()`-ed slots via `cache.py`, per ADR-002 §4/ADR-012 §4's
    whole rationale for the `forward()`/push mechanism existing in the
    first place. This task does not attempt to reconstruct pre-Shady
    history; `fetch()` here is correct for the "first-ever validation
    pass, gap partially overlaps the live snapshot" case and for tests,
    but TASK-0010's coordinator wiring should treat `BaselineProvider`
    as the `cache.py` `fetch_fn` for genuinely fresh gaps only, relying
    on `forward()`+push for everything after the provider was first
    wired up — exactly the split ADR-012 §4 already describes.
- `tests/test_providers_normalize.py` → 21 zero-mocking tests (5 test
  classes) covering `resolve_dict_series`, `resolve_list_series`,
  `invert_cloud_coverage`, and `normalize_candidate_series` (all shapes
  + the never-raises guarantee).
- `tests/test_providers_discovery.py` → 12 tests (4 test classes) against
  the `FakeHomeAssistant` fixture described above, covering all 5
  acceptance criteria: both `sensor.*` shapes recognized (AC1), both
  `weather.*` shapes recognized + inverted + distinctly labeled (AC2),
  canonical-series shape regardless of source (AC3, also covered in
  `test_providers_normalize.py`), no false positives (AC4), and
  `fetch()`/`forward()` sharing the one mapping function (AC5).
- External dependencies added: none — pure stdlib (`datetime`,
  `collections.abc`, `dataclasses`, `typing`) plus the already-existing
  `providers.base` helpers.
- Gates: `ruff check` passes with zero errors on all 4 new/changed files.
  `mypy --config-file mypy.ini` passes with zero issues (19 source files
  total across `custom_components/shady` + `tests`). `pytest` — full
  suite 72 tests, all pass (8 cache-core + 15 providers-base + 12
  providers-discovery + 21 providers-normalize + 16 regression).
  **`ruff format` note:** this sandbox's installed `ruff format` (0.16.4)
  has a reproducible bug that rewrites the syntactically-required
  `except (TypeError, ValueError):` into the invalid-Python
  `except TypeError, ValueError:` (verified in isolation on a trivial
  scratch file, unrelated to this module's content) — applying it would
  break the file. `normalize.py` is left in its valid, standard
  `ruff format`-style form (confirmed via `ruff format --check --diff`
  that this tuple-parenthesization is the *only* remaining diff); every
  other file this task touches reports "already formatted". Flagging
  this as a sandbox/tooling issue for the human, not a code defect.
