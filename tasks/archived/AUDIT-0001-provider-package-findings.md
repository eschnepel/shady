# Findings: AUDIT-0001 — Provider Package

**Auditor:** Lead Agent (inline, single-pass) **Date:** 2026-09-06 **Verdict:**
PASS overall, with one PARTIAL requiring human clarification and one scope note.

## Audit Criteria

| # | Criterion (ADR) | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | One shared base class, both providers build on it (§1) | PASS | `providers/base.py:29` `class Provider(ABC)`; `discovery.py:175` `class BaselineProvider(Provider)`; `temperature.py:106` `class TemperatureProvider(Provider)`. |
| 2 | Two shared helpers used by both, not reimplemented (§1a) | PASS | `map_state_value`/`assemble_series` defined once in `base.py:73,108`; imported and called by `discovery.py:23` (via `_series_to_slots`→`map_state_value`, and `normalize.py:18`→`assemble_series`) and `temperature.py:26` (both). No local reimplementation found (`grep` for a second `def map_state_value` / `def assemble_series` returns only `base.py`). |
| 3 | Entities without discovery/scoring skip the abstraction (§2) | PASS (out-of-file, verified negatively) | `PV` (actual yield) has no provider class in this package at all — confirmed no `PvProvider`/similar exists. Full confirmation of the *consuming* side (that `coordinator.py` wires `PV`'s `entity_id` straight into `cache.py`) is AUDIT-0005's scope; this audit only confirms the providers/ side has nothing to skip. |
| 4 | Cache reuse, no parallel storage in `providers/` (§3) | PASS | No storage/persistence code anywhere in `providers/*.py` — `grep -n "self\._cache\|Cache(" providers/*.py` returns nothing; providers only compute and return values, cache ownership stays in `cache.py`. |
| 5 | `discovery.py` generic shape discovery, no per-integration adapters (§1) | PASS | `discovery.py:97-145` scans by *attribute shape* (`Mapping`/`Sequence` structural checks + `normalize_candidate_series`), never branches on `entity_id`/integration name. `grep -n "forecast_solar\|solcast\|met_no\|openweathermap"` (case-insensitive) across `providers/` returns nothing. |
| 6 | `normalize.py` reduces to one canonical series (§2) | PASS | `normalize_candidate_series` (`normalize.py:146`) is the single dispatch point; all four shapes converge on `list[tuple[datetime, float]]`. |
| 7 | Candidates scored, not auto-selected (§3) | PASS | `discover_baseline_candidates` (`discovery.py:148`) returns a sorted list, never picks one; `_build_candidate` (`discovery.py:77`) computes `score = 2.0 + keyword_bonus`, matching the ADR's "shape validation + keyword" scoring. Selection is deferred to the config flow (verified only by presence — actual config-flow behavior is AUDIT-0010's scope). |
| 8 | `discovery.py`/`temperature.py` read `hass.states` only (§4) | PASS | Both modules only call `hass.states.get`/`hass.states.async_all` (`discovery.py:103,132,196`; `temperature.py:130,146`); no `hass.services.call`, no `hass.data` writes found. `base.py`/`normalize.py` have zero `hass` references (confirmed by `grep -L "hass" providers/base.py providers/normalize.py` matching both files, i.e. neither mentions it). |
| 9 | Global default + per-string override (§5) | **PASS, but implemented outside this package's scope** | `providers/` itself has no override concept — by design, each `BaselineProvider`/`TemperatureProvider` instance is just one resolved binding. The override/default precedence logic (`has_baseline_override`, `string.has_baseline_override`) lives in `coordinator.py:249,436,592,595` — confirmed present, but its *correctness* is AUDIT-0005's scope, not this one. Flagging so the human doesn't read this PASS as "verified end-to-end." |
| 10 | Temperature-source hierarchy (§1a, ADR-003b) | PASS | `temperature.py:42` `TemperatureTier = Literal["sensor", "weather"]`, with `fetch()`/`forward()` branching by tier (`temperature.py:129-150`) and `weather` tier falling back to current reading when no forecast slot matches (`_fill_slots`, `temperature.py:81-103`) — matches the documented hierarchy fallback behavior. |

### PARTIAL finding — sunshine-duration rescaling (ADR-009 §1)

ADR-009 §1 states sunshine-duration values are "used directly, **only rescaled**
to the baseline's expected numeric range." The shipped code does not rescale
this value at all: `normalize_candidate_series`'s `"weather_sunshine"` branch
(`normalize.py:162-163`) calls
`resolve_list_series(raw, value_key_hint=SUNSHINE_DURATION_KEY)` with no scaling
step, in contrast to the `"weather_cloud"` branch two lines below it, which
explicitly calls `invert_cloud_coverage`. The test suite confirms this is
intentional, not an oversight: `tests/ test_providers_normalize.py:137-140`,
`test_weather_sunshine_shape_not_inverted`, asserts a raw `600.0` maps to
`600.0` unchanged.

This is not necessarily a bug — since ADR-001's regression is an empirical fit
of `PV` against whatever numeric range `FC` happens to be in, a
linear/wls2/wls3/kernel model does not strictly need `FC` to be pre-scaled to
match physical units; the fit absorbs an arbitrary linear scale automatically.
But the ADR text commits to an explicit rescale step that the code does not
perform, and no ADR amendment records this as a deliberate simplification. **Per
this project's golden rule ("when in doubt, escalate, never guess"), this is
flagged as a question for the human rather than resolved here:** either (a) the
code is missing a rescale step ADR-009 §1 requires, or (b) ADR-009 §1's wording
should be amended to drop "only rescaled" as unnecessary given the regression
model's scale-invariance — a decision only the human/Lead Agent should make, not
something to silently patch during an audit.

## Test-Coverage Criteria

| # | Criterion | Verdict | Evidence |
| -- | -- | -- | -- |
| 1 | Duplication regression (helpers reimplemented locally) would be caught | GAP | No test asserts `discovery.py`/`temperature.py` call `base.py`'s functions specifically (e.g. via monkeypatch/spy) — current tests only check output values, so a correct-but-duplicated reimplementation would still pass. Low-severity gap (duplication would still need to be *behaviorally* correct to pass, which is most of what matters), but worth naming. |
| 2 | Tied/near-tied scoring produces a deterministic winner | GAP | No test constructs two candidates with equal scores and asserts a specific, stable ordering. `discover_baseline_candidates` (`discovery.py:154-156`) uses Python's stable `list.sort`, so ties would in practice preserve scan order (sensor domain before weather domain, dict-shape before list-shape within `_scan_sensor_domain`) — but nothing pins this down as intentional, testable behavior. |
| 3 | Per-string override precedence | N/A to this package | Correctly out of scope — see AUDIT-0005 for the actual test-coverage check on `coordinator.py`'s override logic. |
| 4 | Temperature hierarchy fallback path | COVERED | `tests/test_providers_temperature.py:130-136` `test_slot_without_forecast_entry_falls_back_to_current_condition` exercises exactly this. |
| 5 | `hass.states`-reading vs. zero-mocking boundary | COVERED | `test_providers_discovery.py`/`test_providers_temperature.py` both use a `FakeHomeAssistant`/`FakeStates` real-object fixture (not a mock library), consistent with ADR-000 §6's zero-mocking philosophy; `test_providers_normalize.py` and `test_providers_base.py` construct no `hass`-shaped object anywhere in the file — the boundary is real, not merely asserted. |
| 6 | Sunshine rescale (per the PARTIAL finding above) | GAP (test correctly reflects current code, but see PARTIAL finding) | `test_weather_sunshine_shape_not_inverted` (`test_providers_normalize.py:137`) documents current (unscaled) behavior accurately — the test is not wrong, but it also means no test would fail if this is in fact a missing feature per ADR-009 §1's literal text. |

## Candidate Follow-Ups (not created — proposed only)

1. **Human decision needed:** resolve the ADR-009 §1 "rescaled" wording vs.
   actual unscaled sunshine-duration behavior — either amend ADR-009 §1 to drop
   the rescale claim (with rationale: regression model absorbs arbitrary linear
   scale), or open a Scenario-C patch task against
   `TASK-0003-baseline-forecast-discovery` to add the rescale step.
1. Optional, low-priority: add a tie-break test for
   `discover_baseline_candidates` if deterministic candidate ordering ever
   becomes user-visible/relied-upon (currently cosmetic — the user confirms a
   candidate manually regardless of list order per ADR-009 §3).

## Delivered Artifacts (for the task file)

- `tasks/AUDIT-0001-provider-package-findings.md` (this file)
