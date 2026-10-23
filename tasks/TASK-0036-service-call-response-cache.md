# Task: Route Every Outbound Service Call Through a Persisted Last-Good-Response Cache

- **Status:** done
- **Related ADRs:** \[ADR-007 §1a (**amended 2026-09-19** — the new,
  restart-persisted `ServiceResponseCache` store), ADR-012 §4b (**amended
  2026-09-19** — Forecast.Solar poll fallback), ADR-009 §4 (**amended
  2026-09-19** — discovery-time sampling routed through the same cache), ADR-000
  §3 (**amended 2026-09-19** — new `providers --> cache` edge), ADR-007a §4
  (unchanged, referenced — the injected-callable pattern this reuses), ADR-000
  §6 (unchanged, referenced — `cache.py` stays zero-mocking-testable), ADR-000
  §8 (unchanged, referenced — graceful degradation, never an error)\]
- **Dependencies:** [] (none — independent of `TASK-0034`/`TASK-0035`)

## Goal

Every *recorder* read this integration makes is already failure-tolerant:
`cache.py` stores what it fetched and answers later reads from that store
(ADR-007a §4/§5). Nothing does the equivalent for the two request/response
**service calls** the integration depends on, and both currently degrade to "no
data at all" on any failure:

- `forecast_solar.get_forecast` — `coordinator.py`'s `_poll_forecast_solar`
  (ADR-012 §4b). On an exception, the poll is swallowed and
  `BaselineProvider.forward()` keeps returning nothing **for a full hour**
  (until the next scheduled poll); on a response with no usable `wh_period`, the
  empty response is pushed into the provider anyway, overwriting a perfectly
  good previous forecast with nothing.
- `weather.get_forecasts` — `providers/discovery.py`'s
  `_sample_weather_forecast` (ADR-009 Amendment), plus `_sample_forecast_solar`
  for the same Forecast.Solar service at discovery time. A transient failure
  silently drops an otherwise-valid candidate off the discovery list.

The failure modes are real and routine, not exotic: the upstream integration's
config entry not loaded yet during Home Assistant startup (the exact race
`_refresh_forecast_solar_providers` was already added to paper over), the
upstream API rate-limiting (Forecast.Solar's free tier does this daily), or a
plain network timeout.

This task adds a **service-response store to `cache.py`**: the last usable
response per service call is remembered, and returned when the current call
fails. It is the service-call counterpart of the injected `fetch_fn` path in the
very same module — same "a read that cannot be satisfied right now is answered
from what was stored last" contract, applied to a different I/O surface, and
therefore the same module's job rather than a new one (see `Why in cache.py`
below).

Unlike the time-series half of `cache.py`, this store is **restart-persisted**:
the single most valuable moment for a remembered forecast is exactly the one
where memory is empty — right after a restart, when the upstream integration is
not loaded yet and the very first poll fails. It joins the energy integrals as
the second restart-persisted store in that module, written by `coordinator.py`
(the only module that owns a `Store`), exactly as ADR-007 §1 already prescribes
for the first one.

### Why in `cache.py` (and not a new module)

Considered and rejected: a separate `service_cache.py`. `cache.py`'s own
docstring already defines the module as this integration's *external-read
memory* — it holds three stores that are not index-addressable time series at
all (the energy integrals, the intraday ramp state, the fitted models), so
"non-time-series store" is an established shape here, not an intrusion. A
separate module would duplicate `cache.py`'s exact invariants (injected callable
instead of an imported I/O API, `coordinator.py` owning persistence, no `hass`
import) in a second place, add a node to the module graph and ADR-000 §3's
module list, and split "what does Shady remember across a failure?" across two
files for no behavioral gain. Keeping it here also means the new store inherits
ADR-007's existing persistence and purity rules verbatim rather than restating
them.

### Phase 0 Note (amendment procedure)

This is a real architecture decision, not a same-behavior refactor: a new store
in `cache.py`, a second restart-persisted `Store`, and a behavior change at two
existing call sites. ADR-007 §1 and ADR-012 §4b must be amended (and
`tasks/adr-summary.md` updated) **before** implementation starts, with a
Refinement Log row in `tasks/INDEX.md`.

## Design

- **New `ServiceResponseCache` class in `custom_components/shady/cache.py`** — a
  sibling of `Cache`, not a member of it: `Cache` is per-config-entry and
  constructed by `coordinator.py`, whereas discovery sampling runs inside the
  **config flow**, where no `Cache` (and no config entry) exists yet. One
  module, two independently constructible stores.
- **Purity is preserved exactly as `Cache` preserves it** (ADR-000 §3/§6, no
  `homeassistant.*` import): the class never calls a service itself. The caller
  injects an **async callable** that performs the one call —
  `await cache.async_call(key, call_fn, ...)` — mirroring `Cache`'s injected
  `fetch_fn` one-for-one. No duck-typed `hass`, no `hass.services` knowledge in
  `cache.py` at all.
- **One call surface**, `ServiceResponseCache.async_call(...)`: it always
  invokes `call_fn` first (recall is a *fallback*, never a short-circuit),
  returns the live response when the call succeeds **and** the response is
  usable, and the remembered response otherwise. `None` is returned only when
  there is nothing usable remembered either — i.e. today's exact behavior for
  the genuinely-cold case.
- **"Usable" is caller-defined**, with a sensible default ("not `None`, not
  empty"): `coordinator.py`'s poll passes a predicate requiring a non-empty
  `wh_period`, so the existing "returned no usable `wh_period` data" branch
  falls back instead of clobbering the last good forecast.
- **Keying**: `service_call_key(domain, service, data, target=None)` — a
  module-level helper returning a canonical, `dict`-iteration-order-independent
  string. `target` is part of the key, not folded into `data`, because
  `weather.get_forecasts` passes its entity through `target=` and two entities
  must never collide.
- **Expiry: 12 hours.** A remembered response older than
  `SERVICE_RESPONSE_MAX_AGE = timedelta(hours=12)` is never recalled — a
  half-day-old PV/weather forecast has no useful overlap left with the horizon
  being predicted, so falling back to it would be worse than reporting nothing
  and letting the existing cold-start paths run. Expired entries are pruned on
  the next write so the store does not grow without bound.
- **Time is injected, never read implicitly** — `async_call(..., now=...)`
  follows the same convention `Cache`'s `reference` parameter and
  `coordinator.py`'s `self._now` already establish; each entry stores its own
  `remembered_at`, and `remembered_at(key)` exposes it (diagnostics, and any
  future policy change, need no storage-format change).
- **Normalize on the way in, not out**: a response is JSON-normalized
  (`datetime`/`date` → `isoformat()`, tuples → lists, non-`str` mapping keys →
  `str`) *before* being remembered, so a recall is byte-identical whether it
  came from memory or from disk after a restart, and no `Store` write can ever
  fail on an unserializable payload. The value handed back to the caller on a
  *successful* call is the untouched live response.
- **Persistence is mediated by `cache.py` itself, via an injected duck-typed
  store** — a deliberate, narrow deviation from the energy integrals'
  fully-`coordinator.py`-mediated restore.
  `ServiceResponseCache.attach_store( store)` accepts an object structurally
  matching `Store`'s `async_load`/`async_save` (never importing
  `homeassistant.helpers.storage .Store` itself — the same injection discipline
  `fetch_fn` already establishes for the recorder API), and is idempotent (first
  `attach_store` wins). Loading from it happens **lazily, inside `async_call`**,
  on first use — not via an explicit `restore_*` entry point. This is necessary,
  not just simpler: the construction-time Forecast.Solar poll fires via
  `hass .async_create_task` *before* `__init__.py`'s own
  `await coordinator .async_restore_energy_state()` gets a chance to run (a
  real, already- observed ordering race — `TASK-0034-patch-1`'s own
  `_refresh_forecast_solar_providers` exists to paper over a sibling of it). An
  explicit, externally-sequenced restore would reintroduce exactly that race for
  this cache; a lazy load triggered by whichever call happens to run first does
  not, regardless of scheduling order.
- **One instance per `hass`, shared by both call sites.** `coordinator.py`
  (possibly several config entries) and `providers/discovery.py` must see the
  same store; discovery runs in the config flow with no config entry to hang one
  off. The instance is held in `hass.data` under a key from `const.py`, via an
  accessor in `providers/discovery.py` (`async_get_service_response _cache`) —
  the one `hass`-aware module both sides already share. This is a new import
  edge (`providers/discovery.py` importing `ServiceResponseCache`/
  `service_call_key` from `..cache`), needing an ADR-000 §3 amendment alongside
  ADR-007's — the same kind of narrow, `Cache`-independent exception
  `diagnostics/compare_regressions.py`'s existing `SLOTS_PER_DAY` import already
  established. A `hass` with no `.data` attribute (a minimal test double)
  degrades to "no cache available" — callers fall back to calling the service
  directly, exactly today's behavior, per ADR-000 §8.
- **A second config entry's `Store` never double-writes**: `attach_store` is
  idempotent, but all coordinators use one fixed, domain-wide store key (not
  suffixed by `entry_id`) so every config entry's `Store` object — attached or
  not — points at the same on-disk payload regardless of which one wins.

## Acceptance Criteria

**`ServiceResponseCache` (in `cache.py`, zero-mocking tier)**

- Given a successful, usable call, when it returns, then the caller receives the
  live response unchanged and the (normalized) response is remembered under its
  call key with the supplied `now` as its `remembered_at`.
- Given a `call_fn` that raises, when a usable, unexpired response for the same
  key was remembered earlier, then that remembered response is returned, the
  exception does not propagate, and `call_fn` was still genuinely invoked.
- Given a call that returns `None`/`{}` (or fails the caller's own `usable`
  predicate), when a response was remembered earlier, then the remembered one is
  returned and the remembered entry is **not** replaced or re-timestamped.
- Given a failing call with nothing remembered for that key, when it returns,
  then the result is `None` — unchanged from today's behavior.
- Given a failing call whose remembered entry is older than 12 hours, then
  `None` is returned (the expired entry is never recalled), and given one
  exactly at the 12-hour boundary, then it is still recalled (inclusive bound).
- Given an expired entry, when the next successful call writes to the store,
  then the expired entry is pruned from `service_response_state()`.
- Given two calls differing only in domain, service, service data, or target,
  then they are remembered independently; given two calls whose service-data
  `dict`s differ only in key insertion order, then they share one key.
- Given a response containing `datetime` values, when it is remembered and later
  recalled, then the recalled copy carries ISO-8601 strings — identical to what
  a post-restore recall of the same entry returns.
- Given a call key, `remembered_at(key)` returns its capture timestamp, or
  `None` when nothing is remembered.
- Given `restore_service_responses(...)` fed a malformed/foreign payload, then
  it degrades to "nothing remembered" and never raises (ADR-000 §8).
- Given a cache whose entries were never restored or persisted at all, then
  remembering and recalling still work for the process lifetime — persistence is
  additive, never required.

**`coordinator.py` — the Forecast.Solar poll (ADR-012 §4b)**

- Given a previously successful poll for a config entry, when a later poll
  raises, then the provider is updated with the remembered forecast (its
  `forward()` keeps producing values) instead of being left stale for an hour.
- Given a previously successful poll, when a later poll returns a response with
  no usable `wh_period`, then the remembered forecast is used and the empty
  response is never pushed into the provider.
- Given no previous successful poll, when a poll raises, then behavior is
  exactly as today: swallowed, nothing pushed, no exception escapes.
- Given a successful poll on a restarted Home Assistant whose service now fails,
  when the coordinator is constructed, then the construction-time poll recovers
  the previous run's forecast from `Store`, provided it is less than 12 hours
  old; given a persisted response older than that, then it is not used and the
  poll behaves as a cold one.
- Given a successful poll, then the existing push path into `Cache` is unchanged
  (`get_time_range` sees the same values as today), and the updated
  service-response state is written back to `Store`.

**`providers/discovery.py` — candidate sampling (ADR-009 Amendment)**

- Given a previously successful `weather.get_forecasts` sample for an entity,
  when a later sample fails, then the remembered response is used and the
  candidate is still discovered; two different weather entities never share a
  remembered response.
- Given a previously successful `forecast_solar.get_forecast` sample for a
  config entry, when a later sample fails, then the remembered response is used.
- Given no previous successful sample, when one fails, then both helpers still
  return `None` — unchanged from today.

**Non-goals (explicitly out of scope)**

- No user-facing setting for the 12-hour expiry, and no diagnostics entity
  exposing cache contents.
- No new cached surface beyond the two services named above — the recorder path
  keeps its own, separate `fetch_fn` mechanism (ADR-007a §4); nothing else in
  this integration makes an outbound service call.
- No change to `Cache`'s own time-series behavior, accessors, or constructor.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/cache.py` — new `ServiceResponseCache` class,
  `service_call_key`, `SERVICE_RESPONSE_MAX_AGE`, the JSON-normalizer, and the
  `service_response_state`/`restore_service_responses` persistence pair.
- `custom_components/shady/const.py` — the `hass.data` key for the shared
  instance.
- `custom_components/shady/providers/discovery.py` — the accessor
  (`async_get_service_response_cache`); `_sample_weather_forecast`/
  `_sample_forecast_solar` route their service calls through it.
- `custom_components/shady/coordinator.py` — construct the service-response
  `Store` alongside `_energy_store`, wire it into the shared instance, and route
  `_poll_forecast_solar` through `async_call` with its `wh_period` predicate and
  `self._now()`.
- `tests/test_cache_service_responses.py` — **new** zero-mocking file (matching
  the existing
  `test_cache_core.py`/`test_cache_pinned_slot_pool.py`/`test_cache_regression_pools.py`
  split): cache core, key derivation, expiry, JSON-normalization,
  restore/persist round-trip.
- `tests/test_coordinator_provider_push.py` — poll fallback, expiry, and
  restart-recovery cases; `tests/test_providers_discovery.py` — sampling
  fallback cases.
- `adr/` (ADR-007 §1, ADR-012 §4b), `tasks/adr-summary.md`, `tasks/INDEX.md` —
  Phase 0 amendments and the Refinement Log row.

## Definition of Done

- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md` (none
  expected — `homeassistant.helpers.storage.Store` is core Home Assistant and
  already used by `coordinator.py`)

## Consumed Interfaces

- `cache.py`'s existing module conventions — injected callable rather than
  imported I/O, `coordinator.py`-owned persistence
  (`energy_total`/`restore_energy_state` as the shape to mirror), no `hass`
  import. Full-file context (inline Worker-and-Reviewer task, not a cross-task
  handoff).
- `coordinator.py`'s existing `_poll_forecast_solar`, `_entity_providers`, and
  `Store` construction pattern (`_energy_store`).
- `providers/discovery.py`'s `_sample_weather_forecast(hass, entity_id)` and
  `_sample_forecast_solar(hass, config_entry_id)` — both keep their current
  signature and `None`-on-total-failure contract.
- `tests/support_ha.py`'s `FakeStore` (already backed by `hass.store_data`, so a
  simulated restart observes a prior `async_save`) and `FakeHomeAssistant`.

## Delivered Artifacts

- `custom_components/shady/cache.py`:
  - New: `SERVICE_RESPONSE_MAX_AGE` (`timedelta(hours=12)`),
    `ServiceResponseStore` (a `Protocol` structurally matching
    `Store.async_load`/`async_save`),
    `service_call_key(domain, service, data=None, *, target=None) -> str`,
    `_normalize_for_json`, `_default_usable`, `_ServiceResponseEntry`, and the
    `ServiceResponseCache` class (`attach_store`, `async_call`, `recall`,
    `remembered_at`, `service_response_state`, `restore_service_responses`) —
    exactly as designed above, including the lazy-load-on-first-`async_call`
    behavior.
- `custom_components/shady/const.py`: new `SERVICE_RESPONSE_CACHE_HASS_KEY`.
- `custom_components/shady/providers/discovery.py`:
  - New: `async_get_service_response_cache(hass) -> ServiceResponseCache | None`
    — the `hass.data`-held singleton accessor; returns `None` for a `hass` with
    no `.data` mapping (`getattr`-guarded, matching `coordinator.py`'s existing
    weather-entity-component convention).
  - `_sample_weather_forecast`/`_sample_forecast_solar` rewritten to route their
    service call through the cache (when available), each wrapping the raw
    `hass.services.async_call` in a local `_call_service` closure that keeps the
    pre-existing try/except-and-return-`None` swallowing;
    `_sample_weather _forecast` passes a `usable` predicate requiring a
    `Mapping` entry for the sampled `entity_id`.
  - New imports: `from ..cache import ServiceResponseCache, service_call_key`
    and `from ..const import SERVICE_RESPONSE_CACHE_HASS_KEY` — the new
    `providers --> cache` edge.
- `custom_components/shady/coordinator.py`:
  - New import: `service_call_key` (from `.cache`) and
    `async_get_service_response_cache` (from `.providers.discovery`).
  - New constants: `_SERVICE_RESPONSE_STORE_VERSION`,
    `_SERVICE_RESPONSE_STORE_KEY` (one fixed, domain-wide key, not
    per-config-entry).
  - `__init__`: constructs/attaches `self._service_response_cache` right after
    `self._energy_store`, via `async_get_service_response_cache(self.hass)` +
    `attach_store(Store(...))` (skipped if the accessor returns `None`).
  - `_poll_forecast_solar` rewritten: the raw service call + its existing
    exception/warning logging moved into a local `_call_service` closure
    (messages updated to mention the fallback); a `_usable` predicate requires a
    non-empty `wh_period`; routes through
    `self._service_response_cache.async_call(key, _call_service, usable= _usable, now=self._now())`
    when a cache is available, else calls `_call_service()` directly;
    `if response is None: return` replaces the old unconditional
    `provider.update_live_forecast(response)` — a response is now only ever
    pushed when it is genuinely usable (live or recalled).
- `tests/test_cache_service_responses.py` — **new**, 28 zero-mocking tests: key
  derivation (4), core recall/fallback behavior (9), 12-hour expiry (4), JSON
  normalization (2), persistence/restart (10, including store-failure tolerance
  and the idempotent-`attach_store` case).
- `tests/test_coordinator_provider_push.py` — new
  `TestForecastSolarPollServiceResponseCache` class (6 tests): fallback on a
  raising poll, fallback on a `wh_period`-less response, the cold case is
  unchanged, an expired remembered entry is not used, the poll result survives a
  restart, and a persisted-but-expired entry is not used after a restart.
- `tests/test_providers_discovery.py`:
  - `FakeHomeAssistant` gained an opt-in `data: dict[str, object] | None = None`
    constructor parameter (unset by default, matching the existing
    `entity_registry`/`config_entries` optionality convention) — every
    pre-existing test in this file keeps exercising
    `async_get_service_response _cache`'s "no `.data` at all" fallback
    unchanged.
  - New `TestServiceResponseCacheFallback` class (5 tests): weather-sample
    fallback, per-entity isolation, Forecast.Solar-sample fallback, the cold
    case is unchanged, and one end-to-end `discover_baseline_candidates` test
    proving a second discovery run still finds a candidate after a transient
    failure.
- Test load-order fixes (mechanical, no logic changes) in 8 files that
  `_load("providers/discovery.py", ...)` before this task's own
  `providers/discovery.py` gained its new `..cache`/`..const` imports:
  `test_button.py`, `test_config_flow.py`, `test_coordinator.py`,
  `test_init.py`, `test_providers_discovery.py`, `test_sensor_aggregates.py`,
  `test_sensor_forecast.py`, `test_translations.py` — each now loads
  `regression/base.py`, `const.py`, and `cache.py` before
  `providers/ discovery.py`, matching this module's own new dependency order
  (`cache.py`'s own `from .regression.base import FittedModel` requires the same
  ordering discipline already established by `test_cache_core.py`).
- `adr/000-coding-standards.md` (§3 — new `providers --> cache` edge + two
  bullet amendments), `adr/007-coordinator-cache-split.md` (new §1a),
  `adr/009-baseline-forecast-sourcing.md` (§4 amendment),
  `adr/012-provider-architecture.md` (§4b amendment) — all amended before
  implementation, per Phase 0. `tasks/adr-summary.md` §2/§5 updated to match.
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged
  (`homeassistant.helpers.storage.Store` is core Home Assistant, already used by
  `coordinator.py` for the energy integrals).

**Verification (fresh, full run):** `pytest` — 630 passed (591 baseline + 39
new: 28 in `test_cache_service_responses.py`, 6 in
`test_coordinator_provider_push.py`, 5 in `test_providers_discovery.py`);
`mypy --config-file mypy.ini custom_components/ tests/` — clean, 59 files;
`ruff check .` — clean; `ruff format --check .` — clean, 178 files;
`mdformat --check` — clean on every edited/created `.md` file.
