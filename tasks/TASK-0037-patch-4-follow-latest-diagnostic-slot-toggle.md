# Task: Diagnosed-Slot Companion Button Replaced by an Auto-Follow Toggle (`ShadyClearDiagnosticSlotButton` → `ShadyFollowDiagnosticSlotSwitch`)

- **Status:** done
- **Related ADRs:** \[ADR-004 §2a/§2f/§2g (Amendment 2026-09-24), ADR-007a §6,
  ADR-000 §3\]
- **Dependencies:** [TASK-0037-patch-3-forward-fill-pushed-baseline-series]

## Goal

Human feedback, after using the diagnostic module reworked alongside
`TASK-0037-patch-1`/`-2`/`-3`: the companion clear button (ADR-004 §2f, proposed
by the Lead Agent in the same commit as those patches — it never had a task file
of its own, only its ADR section) "turns out not very helpful". Two concrete
problems: `ShadyDiagnosticSlotDateTime` showed `unknown` while auto-tracking, so
a dashboard needed its own logic to work out "last complete slot"; and a button
is stateless, so nothing showed whether the slot was currently pinned or
following.

Requested rework: a **toggle between a single pinned slot and automatic slot
following**. While automatic is active, the pinned slot is set on every cadence,
so the `datetime` entity's own state is the "as of" timestamp with no dashboard
logic. Diagnostic logic always takes the currently configured slot, pinned or
automatic alike.

## Acceptance Criteria

- Given a fresh coordinator, then following is on and the diagnosed slot is the
  last complete slot as of construction.
- Given following is on, when a 5-minute tick runs, then the stored diagnosed
  slot is set to `index_for(now) − 1` — before any `extra_fit()`/`compute()` of
  that same tick reads it, and whether or not a diagnostic mode is active.
- Given following is on and the clock has moved on without a tick, then
  `diagnosed_slot()` and `ShadyDiagnosticSlotDateTime.native_value` still report
  the same stored slot — nothing re-derives it from `now` at read time.
- Given following is on, when the tick advances the slot, then the cached
  `compute()` result is not invalidated by the advance itself (the mode's own
  `compute_cadence()` decides).
- Given a slot is pinned (`pin_diagnostic_slot`, or the datetime entity set),
  then following is off and a tick never moves the slot; a rejected
  (beyond-horizon) pin changes nothing, following state included.
- Given `set_follow_latest_diagnostic_slot(True)`, then the slot jumps to the
  newest complete one immediately, `cache.pinned_reference` is cleared, and the
  cached result is invalidated.
- Given `set_follow_latest_diagnostic_slot(False)`, then the slot is pinned *as
  currently stored* (not re-derived from `now`), `cache.pinned_reference` is set
  to its date, and the cached result is invalidated.
- `ShadyDiagnosticSlotDateTime.native_value` is never `None`.
- `ShadyFollowDiagnosticSlotSwitch.is_on` mirrors the coordinator's following
  state; `async_turn_on`/`async_turn_off` call
  `set_follow_latest_diagnostic_slot(True/False)`.
- `button.py` provides only `ShadyRecalculateButton`; `switch` is a forwarded
  platform.
- The full test suite passes.

## Estimated File / Module Footprint (hint, not a commitment)

- `custom_components/shady/coordinator.py`, `coordinator_like.py`
- `custom_components/shady/switch.py` (new), `datetime.py`, `button.py`,
  `__init__.py`, `mypy.ini`
- `tests/test_switch.py` (new), `test_datetime.py`, `test_button.py`,
  `test_coordinator.py`, `test_init.py`
- ADR-004 (§2g new), ADR-000, ADR-007a §6, `adr/INDEX.md`,
  `tasks/adr-summary.md`, `tasks/adr-capability.md`

## Definition of Done

- Tests green (full suite: 683 passed) · ADR-004 §2g written before
  implementation · `tasks/adr-summary.md` updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- `mypy --config-file mypy.ini custom_components/ tests/`, `ruff check .`,
  `ruff format --check .` and `mdformat --check` clean on every edited file
- No new external dependencies

## Consumed Interfaces

- `ShadyCoordinator.pin_diagnostic_slot`/`diagnosed_slot`/`now`
  (`custom_components/shady/coordinator.py`) — pin validation/rounding rules
  unchanged (→ TASK-0015b, ADR-004 §2a)
- `Cache.index_for`/`Cache.timestamp_for`/`pin_reference`/`clear_reference`
  (`custom_components/shady/cache.py`) — unchanged (→ ADR-007a §6)
- `DiagnosedSlot` (`custom_components/shady/coordinator_like.py`) — shape
  unchanged, only its docstring

## Delivered Artifacts

- `custom_components/shady/coordinator.py` — `_pinned_slot_index: int | None`
  replaced by `_diagnostic_slot_index: int` (always set) and
  `_follow_latest_diagnostic_slot: bool` (default `True`). New:
  `set_follow_latest_diagnostic_slot(enabled, now=None)`,
  `is_following_latest_diagnostic_slot()`, `diagnostic_slot_timestamp()`,
  `_advance_followed_diagnostic_slot(now)` (called first in
  `_intraday_tick_sync`). Changed: `diagnosed_slot()` reads the stored index
  unconditionally; `pin_diagnostic_slot()` also switches following off.
  **Removed:** `clear_diagnostic_slot()`, `pinned_diagnostic_slot()`.
- `custom_components/shady/switch.py` — new; `async_setup_entry`, class
  `ShadyFollowDiagnosticSlotSwitch(SwitchEntity)`, name "Follow Latest
  Diagnostic Slot", `unique_id` `shady_follow_diagnostic_slot_{entry_id}`.
- `custom_components/shady/datetime.py` —
  `ShadyDiagnosticSlotDateTime.native_value` now `-> datetime` via
  `diagnostic_slot_timestamp()`; module docstring rewritten.
- `custom_components/shady/button.py` — `ShadyClearDiagnosticSlotButton`
  **removed**; `async_setup_entry` adds one `ShadyRecalculateButton`.
- `custom_components/shady/__init__.py` — `PLATFORMS` gains `"switch"`.
- `custom_components/shady/coordinator_like.py` — `DiagnosedSlot` docstring.
- `mypy.ini` — `[mypy-shady.switch] warn_unused_ignores = False`.
- `tests/test_switch.py` (new, 10 tests); `tests/test_datetime.py`,
  `test_button.py`, `test_coordinator.py`, `test_init.py` updated (683 passed in
  total, from 659).
- `adr/004-…md` §2g (new), §2a/§2f/§5/header updated; `adr/000-…md`,
  `adr/007a-…md` §6, `adr/INDEX.md`, `tasks/adr-summary.md`,
  `tasks/adr-capability.md` updated to match.
- **Not migrated:** an installation that already registered the clear button
  keeps a stale, unavailable registry entry (`shady_clear_diagnostic_slot_…`),
  deletable by hand.
- No external dependencies added.
