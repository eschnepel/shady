# Task: Recorder-Backed History for the `forecast_solar` Baseline (Fix Permanent Cold-Start Passthrough)

- **Status:** done
- **Related ADRs:** \[ADR-012 §1-Amendment/§2a-Amendment, ADR-009 §1c-Amendment,
  ADR-002 §1a (unchanged, referenced), ADR-007a §4 (unchanged, referenced)\]
- **Dependencies:** [] (none — extends already-`done`, already-audited work; see
  `tasks/INDEX.md`'s Refinement Log for how this task was admitted outside the
  normal Phase 1/2 capability-slice flow)

## Goal

Source document: `shady-baseline-history-fix.md` (uploaded bug report from a
prior analysis session; root-caused and specified there in full, reproduced here
only where needed for the acceptance criteria below).

In production, every configured string's forecast sensor almost always shows the
raw, un-corrected baseline forecast instead of a shading-corrected value — all
strings identical, magnitude far too high, most 5-minute slots within an hour
identical. Root cause: the baseline (`FC`) side of the regression training pool
has no real historical data source for a `_PUSH_SOURCED_SHAPES` baseline
(`weather_sunshine`/`weather_cloud`/ `forecast_solar`) — it only accumulates
from Shady's own future-looking pushes aging into the past, and that accumulated
history is wiped on every Home Assistant restart, which keeps training
confidence at/near zero indefinitely on any instance that restarts periodically
(normal). This task gives the `forecast_solar` shape a real, recorder-backed
historical source — mirroring the mechanism that already works correctly for
actual yield — by linking each such candidate to its own config entry's
companion, continuously-recorded "power production now" sensor at discovery
time.

**Design note, settled mid-task (human directive):** the mechanism is a
**generic**, fourth optional method on `Provider` itself
(`history_entity_id() -> str | None`, ADR-012 §1 Amendment), not a
`BaselineProvider`-specific field with an `isinstance` check in
`coordinator.py`. This mirrors `forward()`'s own opt-in shape exactly, so a
future provider (another PV-forecast shape, a weather-history proxy) picks up
recorder-backed backfill for free the moment it overrides the method — no new
`coordinator.py` code, no new `isinstance` branch. See ADR-012 §2a's own "why
this generic hook" section for the full rationale.

**Explicitly out of scope** (per the source document — do not attempt): fixing
the identical-string/magnitude/hourly-flatness symptoms directly (they are
expected to resolve on their own once real history accumulates); fabricating
sub-hourly baseline resolution the source data doesn't have; changing
`cache.py`'s push/validate "actively pushed, never re-queried" behavior;
modifying `_fetch_actual_yield_statistics` or its dispatch (mirrored, not
touched); generically wiring `history_entity_id()` for
`sensor_dict`/`sensor_list`/`weather_sunshine`/`weather_cloud` (left overriding
nothing, i.e. the base class's `None` default — see ADR-009 §1c's "why only
`forecast_solar`").

## Acceptance Criteria

- Given a `forecast_solar` config entry whose companion "power production now"
  sensor is registered in the entity registry, when
  `discover_baseline_candidates` runs, then the resulting
  `forecast_solar`-shaped `BaselineCandidate` has `history_entity_id` set to
  that sensor's current `entity_id`, resolved via the entity registry's
  `(config_entry_id, domain, translation_key)` index — never by
  string-matching/guessing an `entity_id`, and never by composing a guessed
  `unique_id`.
- Given a `forecast_solar` config entry whose companion sensor is not yet
  registered (startup race) or the entity registry is unavailable, when
  discovery runs, then `history_entity_id` is `None` and discovery does not
  raise (ADR-000 §8).
- Given every other baseline shape (`sensor_dict`, `sensor_list`,
  `weather_sunshine`, `weather_cloud`), `BaselineCandidate.history_entity_id` is
  always `None` and the constructed `BaselineProvider.history_entity_id()`
  returns the base class's own `None` default — no automatic linking is
  attempted for them (ADR-009 §1c).
- Given a confirmed `forecast_solar` candidate (global default or per-string
  override) flows through the config flow, then its `history_entity_id` is
  persisted onto the config entry's data (`CONF_BASELINE_HISTORY_ENTITY_ID`/
  `CONF_STRING_BASELINE_HISTORY_ENTITY_ID`) alongside `entity_id`/`attribute`/
  `shape`, exactly as those three already are.
- Given a `ShadyCoordinator` constructed against config entry data carrying a
  baseline whose registered provider's `history_entity_id()` resolves
  non-`None`, when `cache.py`'s `fetch_fn` is invoked for that baseline's
  `sensor_id` with a past-dated `[start, end)` range, then `_fetch_fn`
  dispatches **generically** (checking `provider.history_entity_id()` for
  whichever provider is registered, no `isinstance` check against
  `BaselineProvider` or any other concrete subclass) to a new
  `_fetch_provider_history_statistics(history_entity_id, start, end)` method
  (recorder `statistics_during_period`, `_STATISTICS_PERIOD`/`{"mean"}`,
  mirroring `_fetch_actual_yield_statistics`'s own pattern exactly, without
  modifying that existing method) **instead of** calling `provider.fetch()` for
  that call.
- Given the same setup but `provider.history_entity_id() is None` (every
  provider today except a `forecast_solar`-shaped `BaselineProvider` whose
  companion sensor was resolved), `_fetch_fn` dispatch is completely unchanged
  from before this task — `provider.fetch()` is still called.
- `forward()` (the live push path, ADR-012 §4b) is unaffected by this task —
  unmodified behavior, verified by existing tests continuing to pass unchanged.
- `_baseline_missing`/`missing_required_entities()` (ADR-002 §1a) are unaffected
  — a `forecast_solar` baseline's required-entity check stays keyed to the
  config entry's own `ConfigEntryState.LOADED`, not to `history_entity_id()`
  resolution; a not-yet-resolved history entity must never block setup.
- On a fresh `Cache` (simulating a just-restarted instance) with recorder
  history available for the linked history entity,
  `_fetch_provider_history_statistics` returns real (non-placeholder) values for
  historical slots immediately — verified directly against the method, not by
  asserting on `regression/base.py`'s `build_pool`/
  `passthrough_where_no_confidence` (unmodified, out of scope; the source
  document's own Acceptance Criteria 1/2 are about those modules' existing,
  already-correct behavior once fed real data, not something this task
  re-verifies).
- `tasks/adr-summary.md`, ADR-009, and ADR-012 accurately describe the above
  (done as part of this task, before/alongside implementation — see the Lead
  Agent's own amendment procedure; ADR-012 §1's method table and Consequences
  were revised a second time mid-task when the design moved from a
  `BaselineProvider`-specific field to the generic base-class method).
- Full existing test suite stays green; `mypy --strict` clean; `ruff check`/
  `ruff format --check` clean; `mdformat --check` clean on every edited/ created
  `.md` file; no new external dependency (the entity registry is part of the
  `homeassistant` package itself, "already bundled" — same category as
  `aiohttp`/`homeassistant.helpers.device_registry` in `tasks/DEPENDENCIES.md`,
  not a new pip package).

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/providers/base.py` — fourth optional `Provider`
  method, `history_entity_id()`.
- `custom_components/shady/providers/discovery.py` —
  `BaselineCandidate.history_entity_id` field, `BaselineProvider.__init__`/
  `.history_entity_id()` override, guarded `entity_registry` import,
  `_resolve_forecast_solar_history_entity`, `_build_forecast_solar_candidate`
  extended, `_scan_forecast_solar_domain` wired up.
- `custom_components/shady/const.py` — `CONF_BASELINE_HISTORY_ENTITY_ID`,
  `CONF_STRING_BASELINE_HISTORY_ENTITY_ID`.
- `custom_components/shady/config_flow.py` — `_normalize_settings`,
  `_build_current_string` carry the new field through.
- `custom_components/shady/coordinator.py` —
  `_StringConfig. baseline_history_entity_id`, `_resolve_string`,
  `_ensure_baseline_provider` extended, generic `_fetch_fn` dispatch, new
  `_fetch_provider_history_statistics`.
- `tests/test_providers_discovery.py`, `tests/test_coordinator.py`,
  `tests/test_config_flow.py` — corresponding coverage.
- `adr/009-baseline-forecast-sourcing.md`, `adr/012-provider-architecture.md`,
  `tasks/adr-summary.md`, `README.md` — amendments (Lead Agent, before/
  alongside implementation).

## Definition of Done

- Tests green (full suite) · docs updated (ADRs, `adr-summary.md`, `README.md`)
  · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none — see
  Acceptance Criteria)

## Consumed Interfaces

<!-- Filled by the Lead Agent before implementation. This task has no
     Dependencies (extends already-`done` work directly), so every symbol
     below comes from the current, already-audited checkout rather than
     another task's Delivered Artifacts. -->

- `ShadyCoordinator._fetch_actual_yield_statistics` (exact recorder-query
  pattern to mirror, NOT to modify or call) —
  `custom_components/shady/ coordinator.py`
- `ShadyCoordinator._fetch_fn`, `._entity_providers`, `._STATISTICS_PERIOD`,
  `SLOT_DURATION` (module-level, `cache.py`), `._StringConfig`,
  `._resolve_string`, `._ensure_baseline_provider`, `._baseline_missing`,
  `.missing_required_entities` — `custom_components/shady/coordinator.py`
- `providers.base.Provider` (`fetch`/`identify`/`forward` contract, and the base
  class this task adds `history_entity_id()` to) —
  `custom_components/shady/providers/base.py`
- `providers.discovery.BaselineCandidate`, `.BaselineProvider`
  (`__init__`/`.shape`/`.forecast_type`/`.update_live_forecast`/`.identify`/
  `.fetch`/`.forward`), `._build_forecast_solar_candidate`,
  `._scan_forecast_solar_domain`, `._FORECAST_SOLAR_DOMAIN`,
  `._PUSH_SOURCED_SHAPES` — `custom_components/shady/providers/discovery.py`
- `const.CONF_BASELINE_ENTITY_ID`/`CONF_BASELINE_ATTRIBUTE`/
  `CONF_BASELINE_SHAPE`/`CONF_STRING_BASELINE_ENTITY_ID`/
  `CONF_STRING_BASELINE_ATTRIBUTE`/`CONF_STRING_BASELINE_SHAPE` (exact sibling
  pattern the two new keys mirror) — `custom_components/shady/ const.py`
- `config_flow._normalize_settings`, `._build_current_string`,
  `._resolve_candidate_choice` — `custom_components/shady/config_flow.py`
- `cache.py`'s `FetchFn` contract
  (`fetch_fn(sensor_id, start, end) -> list[float | None | str]`, ADR-007a §4) —
  referenced only, unmodified — `custom_components/shady/cache.py`
- Test doubles extended: `tests/test_providers_discovery.py`'s own
  `FakeHomeAssistant`/`FakeConfigEntries` (real, non-`Mock` stand-ins);
  `tests/test_coordinator.py`'s `_make_entry`/`_make_coordinator`/
  `FakeHomeAssistant` (`tests/support_ha.py`); `tests/test_config_flow.py`'s
  `ShadyConfigFlow`/`flow_call`/`_defaults_from_schema`/
  `_finish_minimal_flow`/`_accept_settings_defaults` helpers.

## Delivered Artifacts

- `adr/012-provider-architecture.md` → §1 amended (fourth optional `Provider`
  method, `history_entity_id() -> str | None`, base class default `None`, added
  to the method table); new §2a Amendment ("recorder-backed baseline history
  backfill via a linked entity") describing the generic `_fetch_fn` dispatch and
  the new, generically-named `_fetch_provider_history_ statistics` coordinator
  method; §5 amended (cross-reference to §2a, entity registry as a public
  core-level surface); Consequences gained a matching Pro/Con pair; header "Last
  updated" line updated.
- `adr/009-baseline-forecast-sourcing.md` → new §1c Amendment ("recorder-backed
  baseline history via a linked history entity") — discovery-time resolution,
  the "why only `forecast_solar`" shape-safety argument, and `BaselineProvider`
  overriding the generic base-class method (not a bespoke field); §4 amended
  (entity-registry read added to the module-boundary rule); header "Last
  updated" line updated.
- `tasks/adr-summary.md` → §2 (module boundary line + `providers/` bullet), §9
  (recorder-read-path exclusion clarified) updated to match.
- `README.md` → "Requirements" section: one clarifying bullet on
  Forecast.Solar's companion sensor now also feeding real recorder history into
  the baseline side of training.
- `custom_components/shady/providers/base.py` →
  `Provider.history_entity_id() -> str | None`, base class default `None`; class
  docstring updated from "Three methods" to "Four methods".
- `custom_components/shady/const.py` → new module-level constants
  `CONF_BASELINE_HISTORY_ENTITY_ID = "baseline_history_entity_id"`,
  `CONF_STRING_BASELINE_HISTORY_ENTITY_ID = "baseline_history_entity_id"`.
- `custom_components/shady/providers/discovery.py` →
  - `BaselineCandidate` gains field `history_entity_id: str | None = None`.
  - `BaselineProvider.__init__` gains parameter
    `history_entity_id: str | None = None`; overrides `history_entity_id()` (a
    method, matching the base class contract — not a property) to return it.
  - `_build_forecast_solar_candidate(config_entry_id, history_entity_id=None)` —
    new optional second parameter, backward-compatible default (existing
    single-argument test call unmodified, still passes).
  - New module-level
    `_FORECAST_SOLAR_HISTORY_TRANSLATION_KEY = "power_production_now"` and
    function
    `_resolve_forecast_solar_history_entity(hass, config_entry_id) -> str | None`,
    using `entity_registry.async_get(hass)` +
    `async_entries_for_config_entry(registry, config_entry_id)`, narrowed to the
    one `sensor`-domain entry whose `translation_key` matches. Deliberately
    **not** a composed `unique_id`/`async_get_entity_id` lookup: this sensor's
    real-world `entity_id` carries no config-entry-scoping prefix or suffix at
    all (confirmed against a live deployment — it is simply
    `sensor.power_production_now`), which ruled out assuming anything about its
    `unique_id`'s composition. This was a mid-task design correction (human
    caught the wrong assumption after the first pass); see `tasks/INDEX.md`'s
    Refinement Log.
  - `_scan_forecast_solar_domain` now resolves and attaches `history_entity_id`
    per candidate.
  - Guarded module-level import:
    `from homeassistant.helpers import entity_registry as _entity_registry`
    under `try/except ImportError` (mirrors `coordinator.py`'s existing
    `weather.const.DATA_COMPONENT` guarded-import precedent),
    `_entity_registry = None` on failure — the one exception to this module's
    otherwise-zero runtime `homeassistant` dependency (module docstring updated
    to say so).
- `custom_components/shady/config_flow.py` →
  - imports `CONF_BASELINE_HISTORY_ENTITY_ID`,
    `CONF_STRING_BASELINE_HISTORY_ENTITY_ID` from `.const`.
  - `_normalize_settings` return dict gains
    `CONF_BASELINE_HISTORY_ENTITY_ID: candidate.history_entity_id if candidate is not None else None`.
  - `_build_current_string` return dict gains
    `CONF_STRING_BASELINE_HISTORY_ENTITY_ID: candidate.history_entity_id if candidate else None`.
- `custom_components/shady/coordinator.py` →
  - `_StringConfig` gains field `baseline_history_entity_id: str | None`;
    `_resolve_string` reads it from `CONF_STRING_BASELINE_HISTORY_ENTITY_ID`.
  - `self._global_baseline_history_entity_id: str | None` read from
    `CONF_BASELINE_HISTORY_ENTITY_ID` at construction.
  - `_ensure_baseline_provider` gains parameter
    `history_entity_id: str | None = None`, passed through to
    `BaselineProvider(...)`; both call sites (global default, per-string
    override) updated.
  - New method
    `_fetch_provider_history_statistics(history_entity_id, start, end) -> list[float | None | str]`
    — mirrors `_fetch_actual_yield_ statistics` exactly (not shared/refactored;
    that method is untouched). Named generically, not
    `_fetch_baseline_statistics`, matching the generic dispatch below.
  - `_fetch_fn` dispatch extended **generically**: for whichever provider is
    registered, `provider.history_entity_id()` is checked; a non-`None` result
    routes to `_fetch_provider_history_statistics` instead of
    `provider.fetch()`. No `isinstance(provider, BaselineProvider)` check
    anywhere.
- `tests/support_ha.py` → unchanged (no shared-fixture change needed; the
  guarded-import fallback exercised by `test_coordinator.py`/
  `test_config_flow.py` needed no new stub, mirroring the existing
  `DATA_COMPONENT` precedent exactly).
- `tests/test_providers_discovery.py` →
  - `_install_fake_entity_registry_module()` (new): injects a hand-written
    `homeassistant.helpers.entity_registry` stand-in into `sys.modules` before
    loading `discovery.py`, so the guarded import exercises the real resolution
    logic in this file, not only its fallback branch.
  - `FakeEntityRegistryEntry`, `FakeEntityRegistry` (new, real non-`Mock`
    stand-ins).
  - `FakeHomeAssistant` gains optional `entity_registry` constructor param.
  - `TestForecastSolarHistoryEntityResolution` (new): resolves via a matching
    registry entry; `None` when no match, wrong domain, or wrong config entry
    id; `None` when the registry itself is absent;
    `_build_forecast_solar_candidate`/`_scan_forecast_solar_domain`/
    `discover_baseline_candidates` end-to-end wiring, both with and without a
    resolvable companion sensor. The pre-existing single-argument
    `_build_forecast_solar_candidate` test is unmodified and still passes.
  - `TestBaselineProviderHistoryEntityId` (new): `.history_entity_id()`
    default/override, and confirms `fetch()`/`forward()` are unaffected by it.
- `tests/test_coordinator.py` →
  - `TestEnsureBaselineProviderGuards` extended: `history_entity_id` is threaded
    through to the constructed `BaselineProvider`, readable back via
    `.history_entity_id()`; defaults to `None` when omitted.
  - `TestFetchFnHistoryEntityRouting` (new): a `forecast_solar` provider whose
    `history_entity_id()` resolves routes `_fetch_fn` to
    `_fetch_provider_history_statistics`, seeded via `hass.statistics`; the
    default fixture's `sensor_dict` provider (no history entity) still calls
    `provider.fetch()`, asserted unchanged; a resolved history entity leaves
    `forward()`/the push path untouched.
  - `TestFetchProviderHistoryStatistics` (new): mirrors
    `TestFetchActualYieldStatisticsEpochTimestamp`'s own epoch-timestamp
    coverage for the new, generically-named method.
- `tests/test_config_flow.py` →
  - captures the `_load("providers/discovery.py", ...)` return value as
    `_discovery_mod` (previously discarded) for direct `BaselineCandidate`
    construction in new tests.
  - `TestBaselineHistoryEntityIdFlowsThrough` (new): a synthetic
    `forecast_solar` candidate (this file's own `FakeHomeAssistant` models no
    `.config_entries` scan, so real discovery can't produce one — the candidate
    is injected directly via `flow._candidates`) with `history_entity_id` set
    flows into both the `settings` step's global default and the `add_string`
    step's per-string override, under the new config keys; a manually-entered
    baseline and a discovered candidate without a history entity (every other
    fixture in this file) both store `None`, matching pre-task behavior.

**Verification run (final, after the post-`done` `translation_key` correction —
see `tasks/INDEX.md`'s Refinement Log for the full account):** full `pytest`
suite (560 passed — two more than the original 558, the two new resolution tests
added during the correction),
`mypy --config-file mypy.ini custom_components/ tests/` (0 issues, 58 files),
`ruff check .` (clean, after fixing one `E501` line-length violation in the
rewritten resolver via `ruff format`), `ruff format --check .` (174 files
formatted), `mdformat --check` on every edited/created `.md` file (clean, after
a line-reflow-only `mdformat` pass on ADR-009 and `tasks/adr-summary.md`) — all
green.
