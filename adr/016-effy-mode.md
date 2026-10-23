# ADR-016 – Effy Mode: Strings, Training Window, Slot Trigger, Live Config and Repairs Issues From Effy's Recalculated-From Sensor

**Date:** 2026-10-20 **Status:** Accepted — confirmed by the human on 2026-10-21
(Gate 2; it began as a draft, Phase 0: "Any new ADR starts in a draft state
until review confirmed by a human"). Decisions below were taken in the
`grill-with-docs` session of 2026-10-20; the question numbers in brackets
(Q1–Q39) are that session's. **Related:** ADR-017 (Accepted — what Shady does
with the sensor's state timestamp), Effy's ADR-021 (`github.com/eschnepel/effy`,
Accepted 2026-10-18; not an ADR of this repository), ADR-010 (config flow),
ADR-006 §1a (slot trigger), ADR-002 §1a.

______________________________________________________________________

## Context

A person who runs Effy has already told Effy which entities are the PV inputs
and how many days of history to recalculate. Shady asks for the same facts again
(the strings, the training window) and starts its slot job from the recorder's
statistics event, which fires *before* the slot is committed and therefore needs
a probe. Effy publishes both what Shady asks for and a signal that fires *after*
its data is final: the attributes `sensors`, `max_history_days` and
`schema_version` of `sensor.effy_recalculated_from`, and Effy's closing step
(Effy ADR-021), whose **state** is the earliest slot Effy's latest run rewrote
(used by ADR-017). Shady and Effy otherwise couple only through entity state;
this ADR adds one optional, explicit coupling and keeps it that way — Shady
imports nothing from Effy.

## Decisions

### 1. Opt-in per entry; the glossary calls it Effy mode (Q8, Q18)

A config entry is in **Effy mode** exactly when `entry.data` holds
`effy_entity_id`, the picked recalculated-from sensor. Without it nothing in
Shady changes: the existing flow, the recorder trigger and the watchdog stay as
they are. Picking is always explicit; nothing is pre-selected.

### 2. What is read, and what it replaces (Q2, Q3, Q6)

Only the attributes decide (not the state): `schema_version` must be `1` (Effy
raises it only for a breaking change); `sensors` is a list; `max_history_days`
is an integer ≥ 1.

- **Strings** = the `entity_id`s of the `sensors` entries with
  `series: effective`, `role: pv`, `direction: input`, in list order, duplicates
  dropped. All of them — there is no subset (a person who wants one leaves Effy
  mode off and picks strings by hand).
- **Training window** = `max_history_days`, copied unchanged. Effy's window ends
  now, Shady's ends before the reference day, and the recorder's real retention
  may be shorter than either (ADR-017 §9); the missing hours belong to the
  oldest day, which carries the lowest weight.

A pure module (no `homeassistant` import) parses the attributes into either
these two values or a cause: not ready, not the recalculated-from sensor,
unsupported schema, malformed, no PV inputs.

### 3. What the config flow hides (Q4, Q7)

In Effy mode the `strings` selector and the `window_days` field are not asked;
the derived values are stored in `entry.data` under today's keys and shapes, so
the coordinator cannot tell the two sources apart. The `regression_tuning` page
says, read-only, which training window was taken from Effy. A new optional first
step `effy` (an entity selector filtered to the `effy` integration) exists only
where an Effy entity exists or one is already stored. In the reconfigure menu
the "Strings" entry skips the selector and opens the per-string settings;
re-submitting the Effy step is the explicit refresh, and the only place a
removal is applied (§5). Clearing the field leaves Effy mode and shows the two
options again, pre-filled with the last derived values.

### 4. The slot trigger in Effy mode (Q10, Q11)

In Effy mode the coordinator registers **no** recorder-statistics listener and
**no** watchdog. Every state change of the picked sensor starts the slot job,
except a new state of `unknown` or `unavailable`; a state restored after a
reboot (carries `restored_as_of`) does start it. The probe, the dedupe by slot
index, the supersede rule and the followed slot (always Shady's own last
completed slot) are unchanged. A manual Effy history recalculation also starts a
job; dedupe absorbs the duplicate. The sensor's state timestamp is not used for
the followed slot; ADR-017 uses it to recalculate the slots Effy rewrote.

Consequence, accepted: Effy writes the sensor only when its run rewrote
something, so a slot in which it wrote nothing is not processed; the next job's
followed slot catches up, but the diagnostics' followed slot can skip one.

### 5. Live config changes (Q9, Q15, Q16, Q17)

On a real closing step — a valid payload without `restored_as_of` — Shady
derives strings and window again. If strings were *added* or the window changed,
it writes both into `entry.data` and reloads the entry once (the
persist-then-reload pattern of the existing provider self-heal); new strings get
default per-string settings. A restored payload never changes config: after an
Effy options change Effy restores the old list and the old `max_history_days`
until its first closing step (Effy ADR-021), which would flip the window back
and forth. At startup Shady uses the stored config and never waits for Effy.

A PV input missing from the new list is **not** removed: ADR-010 discards a
removed string's settings for good, and Effy's list can shrink briefly (a
late-created sensor is listed only from a later closing step). It stays
configured and raises the warning of §6; the person applies the removal by
re-submitting the Effy step in reconfigure.

### 6. HA messages — Repairs issues, one set per config entry (Q12, Q13, Q14, Q16, Q19)

| Issue | Severity | Raised when | Clears |
| -- | -- | -- | -- |
| `effy_unavailable` | error | the picked entity is missing from the state machine or `unavailable` (Effy disabled, removed or unloaded); checked after `EVENT_HOMEASSISTANT_STARTED`, then on every state change | next state that is neither missing nor `unavailable` |
| `effy_input_removed` | warning | a valid closing step no longer lists a configured string | Effy lists it again, or the Effy step is re-submitted |
| `effy_payload_invalid` | warning | a valid state carries an invalid payload (malformed, no PV inputs, unsupported `schema_version`) | next valid payload |

Each is not fixable by a button, carries cause-specific `en`/`de` text, and is
accompanied by one logged message per occurrence. While `effy_unavailable`
holds, only the slot job stops (followed-slot advance, intraday correction,
diagnostics, and with them ADR-017's recalculation); the 04:00 recalibration,
the recompute after a baseline update and the buttons keep running, and the
forecast sensors keep their last values. An invalid payload never stops the slot
job and never changes config. An `unknown` state is Effy not yet written — not
an error. The startup check relies on Effy restoring the sensor inside its own
setup (verified in Effy's code: the restore runs in `async_added_to_hass`,
awaited by its `async_setup_entry`); if Effy's setup outlasts Home Assistant's
bootstrap timeout the issue appears briefly and clears itself.

### 7. Contract drift (Q22)

One verbatim JSON fixture of an Effy schema-1 payload, taken from Effy's ADR-021
example with its source and date in a comment, is run through the pure parser's
tests. Shady imports nothing from Effy.

## Consequences

- Entry data gains one optional key; no migration.
- `coordinator.py` gains a second trigger registration and the issue handling;
  `cache.py` and the entity modules are untouched by this ADR.
- Shady gains its first Repairs issues (new `issue_registry` surface and an
  `issues` block in `translations/*.json`).
- With Effy mode on, Shady depends on Effy being enabled; there is deliberately
  no fallback, so a misconfiguration is visible instead of silently masked.
- Until ADR-017 is implemented, Shady's cached actual yields do not follow
  Effy's rewrites of past slots (a known interim gap of `TASK-0047b`).
- Effy's contract becomes a dependency of Shady's behavior; the fixture and the
  `schema_version == 1` rule are the guard.

## Alternatives rejected

- **Snapshot at submit time only.** Simpler and no runtime coupling, but stale
  as soon as Effy changes; kept as the behavior of the config flow's own step
  (`TASK-0047a`), with live changes added on top (`TASK-0047b`).
- **Effy's closing step as primary trigger with the recorder event and watchdog
  as fallback.** Masks a disabled Effy; the human chose a visible error.
- **Hot-adding strings to a running coordinator.** A much larger change for a
  rare event; a reload is acceptable.
- **Removing vanished PV inputs automatically.** Destroys per-string settings on
  a transient list change.
- **Copying `max_history_days − 1`.** Adds a coupling that also fails once the
  recorder retains less than Effy's setting.
