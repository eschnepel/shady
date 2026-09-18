# Task Index

**This is a new planning cycle**, per `tasks/archived/INDEX.md`'s own closing
note ("Any further work on this project — new features, new ADRs, a fresh audit
pass — starts a new planning cycle from Phase 0/1 rather than continuing this
remediation batch"). The 20 original capability tasks and their 13 round-1 and 4
round-2 remediation/audit follow-ups all live in `tasks/archived/` and
`tasks/AUDIT-*.md`/`tasks/AUDIT-INDEX.md` — nothing there is reopened or
renumbered by this cycle.

This cycle was triggered directly by an uploaded bug report
(`shady-baseline-history-fix.md`, itself the output of a prior analysis session)
rather than by a fresh Phase 1 capability-slicing pass — a single, well-scoped,
already-root-caused fix rather than a new set of vertical slices. Phase 0's
amendment procedure was still followed in full (ADR-009 §1c, ADR-012 §2a,
`tasks/adr-summary.md` — see the Refinement Log below), and the task itself uses
the same `tasks/<slug>.md` template and Consumed Interfaces/Delivered Artifacts
contract as every prior cycle. Numbering continues unambiguously from the last
archived task (`TASK-0033`), per the orchestration prompt's Phase 6 numbering
rule.

## Task table

| Slug | Title | Status | Dependencies | Worker |
| -- | -- | -- | -- | -- |
| TASK-0034-baseline-recorder-backed-history | Recorder-Backed History for the `forecast_solar` Baseline (Fix Permanent Cold-Start Passthrough) | done | — | Lead Agent (inline; no sub-agents available in this environment — same convention `tasks/AUDIT-INDEX.md`'s round 2 already documents) |

## Refinement Log

| Date | Trigger task | Action | Reason |
| -- | -- | -- | -- |
| 2026-09-15 | TASK-0034-baseline-recorder-backed-history | Amended ADR-009 (new §1c) and ADR-012 (new §2a); updated `tasks/adr-summary.md` §2/§9 and `README.md`'s Requirements section | Phase 0's amendment procedure: the fix specified in `shady-baseline-history-fix.md` is a real architecture decision (a `forecast_solar` baseline candidate may now carry a linked, recorder-backed history entity, resolved via the entity registry; `coordinator.py`'s `_fetch_fn` dispatch gains a second recorder-backed branch), not a same-behavior refactor — it needed to be recorded as an ADR amendment before implementation, not discovered only from the diff. |
| 2026-09-15 | TASK-0034-baseline-recorder-backed-history | Created this fresh `tasks/INDEX.md` rather than reopening `tasks/archived/INDEX.md` | `tasks/archived/INDEX.md` closed itself out explicitly ("nothing remains `todo`... any further work... starts a new planning cycle"); reopening it for one new task would blur the closed remediation batch's own audit trail. |
| 2026-09-15 | TASK-0034-baseline-recorder-backed-history | Revised the design mid-task, before any code was written against the first version: `history_entity_id` moved from a `BaselineProvider`-specific field (with an `isinstance(provider, BaselineProvider)` check in `coordinator.py`'s `_fetch_fn`) to a fourth, generic, optional method on the `Provider` base class itself (`history_entity_id() -> str \| None`, default `None`), the same opt-in shape `identify()`/`forward()` already have. `_fetch_fn`'s dispatch, and the mirrored recorder-query method, were renamed accordingly (`_fetch_provider_history_statistics`, not `_fetch_baseline_statistics`). ADR-012 §1/§2a and ADR-009 §1c were revised in place to match before implementation resumed — not left describing a design the code no longer matched. | Human directive, given before implementation started: "The base class of all baseline providers should cover this scenario too... so another pv forecast or the weather forecast history part can be added later with less effort." A `BaselineProvider`-only field would have meant every future provider re-implementing its own `isinstance` branch in `_fetch_fn` — exactly the per-provider coordinator coupling ADR-012 §4's `forward()` design already rejected for the push path. |
| 2026-09-15 | TASK-0034-baseline-recorder-backed-history | Implemented (against the revised, generic design above), reviewed (Phase 4a/4b, inline — Lead Agent acting as Worker then Reviewer), and merged in full. All Acceptance Criteria verified against the delivered diff — **PASS**. `Status` moved `todo` → `in-progress` → `done`. Full suite green (`pytest`, 558 passed), `mypy --config-file mypy.ini custom_components/ tests/` clean (58 files), `ruff check .`/`ruff format --check .` clean (174 files), `mdformat --check` clean on every edited/created `.md` file. No new external dependency (`tasks/DEPENDENCIES.md` unchanged — the entity registry ships with the `homeassistant` package itself, same category as `aiohttp`/`homeassistant.helpers.device_registry`, not something this project installs). | Routine Phase 4c close-out. |
| 2026-09-15 | TASK-0034-baseline-recorder-backed-history | Corrected a factual assumption in the already-`done` resolution logic, same session, before any downstream task consumed it (no patch task created — see Reason): the human reported the real Forecast.Solar companion sensor's `entity_id` carries no config-entry-scoping prefix or suffix at all (it is exactly `sensor.power_production_now`), invalidating the composed-`unique_id` lookup (`f"{config_entry_id}_power_production_now"` via `async_get_entity_id`). `_resolve_forecast_solar_history_entity` (`providers/discovery.py`) was rewritten to match within `async_entries_for_config_entry(registry, config_entry_id)` on `domain == "sensor"` and `translation_key == "power_production_now"` instead — a lookup with no assumption about `entity_id`/`unique_id` shape at all. `tests/test_providers_discovery.py`'s fake entity-registry doubles were rewritten to model `translation_key` instead of `unique_id`, with two new resolution tests (rename-survives, wrong-`translation_key`-does-not-match). This round's own catch-up work (after a context-window handoff) then: renamed leftover `sensor.home_power_production_now` fixture strings to the correct unprefixed form across `test_coordinator.py`/`test_config_flow.py`/`test_providers_discovery.py`; rewrote ADR-009 §1c/§4 and ADR-012 §5 to describe the `translation_key` mechanism instead of the abandoned `unique_id` one; fixed a stale method-name reference (`_fetch_baseline_statistics` → `_fetch_provider_history_statistics`, the name actually delivered) found independently in ADR-012 §5 and `tasks/adr-summary.md` (two places) while doing that pass; updated `TASK-0034`'s own Acceptance Criteria/Delivered Artifacts to match. Full suite reverified green after every fix: `pytest` (560 passed — two more than the original 558, the two new resolution tests), `mypy --config-file mypy.ini custom_components/ tests/` clean (58 files), `ruff check .` clean (one `E501` line-length violation in the rewritten resolver, fixed by `ruff format`), `ruff format --check .` clean (174 files), `mdformat --check` clean on every edited `.md` file (two required a `mdformat` pass — pure line-reflow from the edits above, no content change, reverified after). | Golden rule for sub-agents applies to the Lead Agent too: a wrong assumption caught immediately, with zero downstream consumers yet, is corrected in place rather than guessed-around or left for a separate patch task — Phase 6 Scenario C's patch-task mechanism is for a `done` task's interface proving insufficient to a *downstream* worker after the fact, which had not yet happened here. Status stays `done` throughout; this row is the audit trail Scenario C would otherwise provide. |

## Audit Groups

Not applicable yet for this cycle — Phase 7 triggers once every task in this
cycle's own table is `done` and the human asks for a fresh audit pass. With only
one task in this cycle so far, a dedicated audit batch is not warranted on its
own; folding this change into whatever group `providers/discovery.py`/
`coordinator.py` land in during a future round-3 audit (should one be requested)
is the more proportionate path, consistent with how round 2 scoped itself to
only the files that actually changed since round 1.
