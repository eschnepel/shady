# Task: Effy Mode at Runtime — Effy's Closing Step Starts the Slot Job, Live Config Changes, Repairs Issues Instead of a Safety Net

- **Status:** todo (Gate 2 approved and ADR-016 confirmed by the human on
  2026-10-21)
- **Related ADRs:** \[ADR-016 §4–7 (Accepted 2026-10-21 — the decisions this
  task implements), ADR-006 §1a (slot trigger, edited in place), ADR-002 §1a,
  ADR-010 (the reconfigure refresh), ADR-000 §3 (diagram edge); Effy's ADR-021 —
  not an ADR of this repository\]
- **Dependencies:** \[TASK-0047a-effy-quick-config-flow,
  TASK-0045c-training-window-and-trim-alignment\] (0045c is the end of the chain
  through `TASK-0045a`/`b`/`d`, which edit the same `coordinator.py` areas; this
  task starts after them to avoid text conflicts)

> Split from `TASK-0047-effy-quick-config` (superseded, kept for history). This
> is the **runtime half without the recalculation engine**: trigger, live
> config, issues. What Shady does with the sensor's state timestamp —
> recalculating the slots Effy rewrote and writing their statistics — is
> `TASK-0047c-slot-recalculation-and-statistics` (ADR-017), which depends on
> this task.

## Goal

While a config entry is in Effy mode (an `effy_entity_id` is stored), Shady
keeps up with the picked recalculated-from sensor: Effy's closing step replaces
the recorder event as the start of the slot job, new Effy PV inputs and a
changed `max_history_days` reach the strings and the training window without a
manual re-submit, and misconfigurations are shown as Home Assistant Repairs
issues instead of being masked by a fallback.

**Known interim gap (until `TASK-0047c`):** Shady's cached actual yields, its
frozen forecast values and its recorder statistics do not follow Effy's rewrites
of past slots. The README's Effy-mode section says so plainly until 0047c
removes the sentence.

## Decisions that shape this task (grill 2026-10-20, ADR-016)

- No safety net in Effy mode: no recorder-statistics listener and no watchdog.
  Effy disabled is a misconfiguration and is shown, not worked around.
- Every state change of the picked sensor starts the slot job except a new state
  of `unknown` or `unavailable`; a restored-marked state (`restored_as_of`) does
  start it but never changes config.
- Probe, dedupe by slot index, supersede and the followed slot (Shady's own last
  completed slot) are unchanged. The state's timestamp is ignored here.
- Config changes: additions and a changed window are persisted into `entry.data`
  and the entry reloads once; removals are never automatic.
- Only the slot job stops while Effy is unavailable; recalibration, recompute
  and the buttons keep running and the sensors keep their last values.
- Startup uses the stored config and never waits for Effy.
- Terms: "Effy mode", "Effy's closing step"; never "following" for the sensor.

## Acceptance Criteria

- **AC 1 — Effy mode off is today's behavior.** Given no `effy_entity_id`, the
  recorder-statistics listener and the watchdog are registered exactly as
  before; the existing coordinator tests pass unchanged.
- **AC 2 — Trigger swap.** Given Effy mode, when the coordinator starts, then no
  recorder-statistics listener and no watchdog are registered, and a listener on
  the picked entity is. Every state change starts the slot job except a new
  state of `unknown` or `unavailable` (and a removed entity, see AC 6); a state
  with `restored_as_of` starts it. Dedupe, probe, supersede and the followed
  slot behave as before (tests drive fake state events).
- **AC 3 — Live config.** Given Effy mode and a closing step whose payload is
  valid and has no `restored_as_of`, when the derived strings contain one the
  entry lacks or the window differs, then the entry writes the new strings
  (existing per-string settings kept, new strings with the defaults) and
  `window_days` into `entry.data` and reloads **once**. Given nothing differs, a
  restored-marked state, or an invalid payload, then `entry.data` is not
  touched. A reload is not scheduled twice if an update listener already reloads
  on `entry.data` changes (worker checks).
- **AC 4 — Removals.** Given a valid closing step that no longer lists a
  configured string, then the string and its settings stay, and the Repairs
  issue `effy_input_removed` (warning, per entry, naming the entities) is
  created. It is deleted when Effy lists the string again or when the Effy step
  is re-submitted in reconfigure (`TASK-0047a` path), which removes the string.
- **AC 5 — Invalid payload.** Given a valid state with an invalid payload
  (malformed, no PV inputs, unsupported `schema_version`), then the slot job
  still starts, config is untouched, and `effy_payload_invalid` (warning, per
  entry, cause in the text) is created and logged once per occurrence; the next
  valid payload deletes it.
- **AC 6 — Effy unavailable.** Given Effy mode, when the picked entity is
  missing from the state machine or `unavailable` — checked after
  `EVENT_HOMEASSISTANT_STARTED` (immediately if already started), then on every
  state change and on removal — then `effy_unavailable` (error, per entry) is
  created and one error is logged, and the slot job does not start while it
  holds. The 04:00 recalibration, the recompute after a baseline update and the
  buttons are unaffected, and the forecast sensors keep their last values. The
  next state that is neither missing nor `unavailable` deletes the issue; an
  `unknown` state is not an error.
- **AC 7 — Startup.** Given Effy mode, the coordinator starts from the stored
  config and does not wait for Effy. A test makes the entity appear after
  `EVENT_HOMEASSISTANT_STARTED` and asserts the error is raised first and then
  clears on the first valid state.
- **AC 8 — Translations.** `en.json` and `de.json` carry an `issues` block for
  the three issue IDs (title and description with placeholders for the entity
  and the cause); `test_translations.py` covers the new block.
- **AC 9 — Docs.** ADR-016 is Accepted (confirmed 2026-10-21); ADR-006 §1a is
  edited in place (the trigger in Effy mode); ADR-000 §3 gains the edge
  `coordinator --> effy_contract`; `adr/INDEX.md` and `tasks/adr-summary.md` are
  updated; README gains an "Effy mode" section that states the consequences
  plainly: no fallback, a slot in which Effy wrote nothing is not processed, and
  the interim gap above.
- **AC 10 — Tests.** Coordinator tests for AC 2–7 using the existing harness;
  the issues are asserted through Home Assistant's real issue registry, not a
  mock.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py` — the trigger registration (~l.2726
  area), the picked-entity listener, the derived-config comparison, the issue
  handling; `async_shutdown` unregisters the new listener.
- `custom_components/shady/const.py` — issue IDs, the `restored_as_of` attribute
  name.
- `custom_components/shady/translations/en.json`, `de.json` — `issues` block.
- `custom_components/shady/effy_contract.py` — reused from `TASK-0047a`;
  extended only if a cause needs a payload for the issue text.
- `tests/test_coordinator_effy_mode.py` (new), `tests/test_translations.py`.
- `README.md`, `adr/016-effy-mode.md`, `adr/006-*.md`,
  `adr/000-coding-standards.md`, `adr/INDEX.md`, `tasks/adr-summary.md`.

## Definition of Done

- Tests green; `mypy`, `ruff check`, `ruff format --check` and
  `mdformat --check` clean on the whole tree.
- Coverage of `coordinator.py` not lower than before.
- `Delivered Artifacts` block completed and accurate.
- No new external dependency (`tasks/DEPENDENCIES.md` unchanged; the issue
  registry ships with Home Assistant).
- ADR-016 Accepted; no open ADR conflict.

## To check by the worker (not verified here)

- `homeassistant.helpers.issue_registry`: `async_create_issue` /
  `async_delete_issue` with `is_fixable=False`, a per-entry `issue_id`, and the
  `translation_key` / `translation_placeholders` shape in this repo's
  `translations/*.json`. Shady has no Repairs issue today.
- Whether an `entry.data` update already reloads the entry through an existing
  update listener (the provider self-heal at ~l.2345 persists with
  `async_update_entry`).
- Whether `manifest.json` should gain `after_dependencies: ["effy"]` so Home
  Assistant sets Effy up first when both are installed; ADR-016 §6 relies on
  Effy restoring inside its own setup, and this would harden that. Not decided
  here.
- That Effy's `force_update` writes arrive as `state_changed` events with the
  same state value (the state is a timestamp that repeats when two runs start at
  the same slot).

## Consumed Interfaces

<!-- Filled by the Lead Agent BEFORE implementation, from the Delivered Artifacts
     of TASK-0047a: the parser module path, its result type and cause names,
     CONF_EFFY_ENTITY_ID, the supported schema_version constant. -->

- `EffyContract` parser symbols from `custom_components/shady/effy_contract.py`
  (→ task: TASK-0047a-effy-quick-config-flow)
- `CONF_EFFY_ENTITY_ID` from `custom_components/shady/const.py` (→ task:
  TASK-0047a-effy-quick-config-flow)
- `_handle_recorder_statistics`, `_start_slot_job`, `_async_slot_job`,
  `_probe_slot_ready_sync`, `_handle_slot_watchdog`, the registration block in
  `coordinator.py` ~l.2726–2730 (→ task:
  TASK-0041-recorder-synchronized-slot-trigger, `done`, as changed by
  `TASK-0045a`/`d`)

## Delivered Artifacts

<!-- Filled by the Worker AFTER implementation. Be exact. -->
