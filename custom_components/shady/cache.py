"""`cache.py` — pure, index-addressable time-series store (ADR-007, ADR-007a).

No `hass` import — constructed with an injected `fetch_fn` so it never
imports the recorder API itself (ADR-007a §4). Only ever called from
`coordinator.py` (ADR-007 §2).

This module implements the storage core: the three-state (`float | None
| str`) value model (§1), validated-range tracking (§2), `push`/
`invalidate` (§3), the injected-`fetch_fn` validate-before-read step
(§4), and two of the three accessors — the contiguous-range
`get_time_range` (§5) and the batched, full-288-slot-sweep
`get_regression_pools` (ADR-008 §2). The third accessor,
`get_pinned_slot_pool` (ADR-007a §6), is deliberately out of scope here
— added alongside its own caller, TASK-0015.

Also owns the two energy-integral running totals (ADR-005 §5/§6,
TASK-0012) — plain in-memory `float`/`last_reset_date` fields, not part
of the index-addressable time-series design above (a single scalar per
kind needs none of that machinery). This is the **one** cache instance
in this module that is restart-persisted (ADR-007 §1) — `cache.py`
itself stays plain in-memory either way, per the module's own no-`hass`
rule; `coordinator.py` is the one that reads/writes Home Assistant's
`Store` helper and calls `restore_energy_state`/back onto this module.

**`fetch_fn` calling convention** (established here, binding for every
caller — `coordinator.py`, and matching `providers/base.py`'s `Provider.
fetch` signature, ADR-012 §1): `fetch_fn(sensor_id, start, end)` returns
exactly one value per 5-minute slot in the **half-open** interval
`[start, end)` — `start` inclusive, `end` exclusive — so a request for
`n` slots returns a list of length `n`.

**Shadow `float64` array (ADR-008 §2, this task):** alongside each
sensor's three-state list (the system of record, unchanged), `cache.py`
also maintains a `float64` `numpy` array over the exact same rolling
window — same length, same `list_offset` alignment — with `NaN` standing
in for whatever the three-state list holds as `None` or a `str` reason.
It is kept incrementally in sync at the single choke point every
mutation already routes through (`_write`, called by both the push path
and the fetch-and-store path) and trimmed in lockstep by `trim()` —
never rebuilt from the three-state list on read. `get_regression_pools`
is built from strided/broadcast views over this shadow array, per
ADR-008 §2.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, overload

import numpy as np
from numpy.typing import NDArray

SLOT_MINUTES = 5
SLOT_DURATION = timedelta(minutes=SLOT_MINUTES)
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES  # 288

# Fixed epoch absolute indices are measured from (ADR-007a §1). Any date
# before Shady's own existence works; the exact value is otherwise
# arbitrary and never observed outside this module.
EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

FetchFn = Callable[[str, datetime, datetime], list[float | None | str]]
OnInvalid = Literal["skip", "raw"] | float

# The two energy-integral running totals (ADR-005 §5/§6) — the one
# restart-persisted cache in this module (ADR-007 §1). `coordinator.py`
# is the only caller, for both of the source sums each kind integrates:
# "pv" tracks `pv_sum()` (§1), "fc" tracks `fc_sum()` (§2).
EnergyKind = Literal["pv", "fc"]


@dataclass(frozen=True)
class IntradayBasis:
    """One reset cycle's pre-intraday-correction basis for a string's
    future slots (ADR-006 §1a/§1b, TASK-0013): `values` is the
    reverse-transformed, still-unclamped per-slot prediction — exactly
    what ADR-006 calls `fc_value(t)` (Ramping) / `old_fc_value(t)` or
    `new_fc_value(t)` (Blending); `fc` is the raw baseline forecast for
    the same slots, kept alongside since the one final output clamp
    (`forecast_adjust.clamp_output`) needs a per-slot upper bound. Both
    keyed by this module's own absolute slot index (`Cache.index_for`).
    """

    values: dict[int, float]
    fc: dict[int, float]
    inverter_limit: float | None


@dataclass(frozen=True)
class IntradayState:
    """Short-lived, per-string ramp/crossfade state (ADR-006 §1b/§5) —
    the "simple dict store" §5 calls for, distinct from the
    time-series-shaped stores above. Deliberately **not**
    restart-persisted (ADR-007's existing accepted-gap trade-off,
    ADR-006 §1b's own note): a lost ramp or crossfade simply restarts
    from the next recompute rather than resuming, since none of this
    state has a recorder-backed equivalent to reload from.

    `reset_at`/`active_slots_since_reset` back `ramp_weight`'s own `w`;
    `ratio_string`/`effective_factor` are the most recently computed
    live values (ADR-006 §4's `intraday_ratio`/derived
    `intraday_ramp_weight` transparency attributes read straight off
    this). `frozen_basis`/`frozen_effective_factor` are Blending-only
    (`None` under Ramping, and under Blending's own first-reset-of-a-
    crossfade-sequence case, ADR-006 §1b — "nothing yet to blend
    against") — the frozen old-side snapshot, taken the instant before
    the provider update that started the current crossfade.
    """

    reset_at: datetime
    active_slots_since_reset: int
    basis: IntradayBasis
    ratio_string: float | None
    effective_factor: float
    frozen_basis: IntradayBasis | None = None
    frozen_effective_factor: float | None = None


def _shape(value: float | None | str, on_invalid: OnInvalid) -> tuple[bool, float | None | str]:
    """Shape one stored value per `on_invalid` (ADR-007a §5).

    Returns `(keep, shaped_value)` — `keep=False` signals the caller to
    drop this entry entirely (only relevant for `on_invalid="skip"`).
    """
    if on_invalid == "raw":
        return True, value
    if isinstance(value, float):
        return True, value
    if on_invalid == "skip":
        return False, None
    return True, on_invalid


def _shadow_value(value: float | None | str) -> float:
    """Map a three-state value onto the shadow array's `float64` encoding
    (ADR-008 §2): a known `float` passes through unchanged; `None`
    (not-yet-fetched/invalidated) and `str` (a stable "unavailable"-type
    non-answer) both become `NaN` — the shadow array collapses the
    three-state model's *two* invalid states into `NaN`'s single one,
    since `get_regression_pools`'s only consumer (`regression/base.py`'s
    `build_pool`, TASK-0005) already treats any `NaN` as fully excluded/
    padding regardless of *why* the sample is invalid.
    """
    if isinstance(value, float):
        return value
    return float("nan")


class Cache:
    """Index-addressable time-series store, generic over any `sensor_id`.

    Constructed with `window_days` (a setup parameter, not re-supplied
    per call, mirroring the global config-flow setting it tracks) and
    `fetch_fn` (injected, never imported directly).
    """

    def __init__(self, window_days: int, fetch_fn: FetchFn) -> None:
        self.window_days = window_days
        self._fetch_fn = fetch_fn
        self._values: dict[str, list[float | None | str]] = {}
        self._list_offset: dict[str, int] = {}
        self._validated: dict[str, tuple[int, int | None]] = {}
        self._shadow: dict[str, NDArray[np.float64]] = {}

        # -- energy-integral totals (ADR-005 §5/§6, ADR-007 §1) --
        # In-memory defaults for a brand-new instance; `restore_energy_state`
        # overwrites these from `coordinator.py`'s storage-backed restart
        # persistence (never called from here — `cache.py` stays plain
        # in-memory, per its own module docstring).
        self._energy_totals: dict[EnergyKind, float] = {"pv": 0.0, "fc": 0.0}
        self._last_energy_samples: dict[EnergyKind, tuple[datetime, float] | None] = {
            "pv": None,
            "fc": None,
        }
        self._last_reset_date: date | None = None

        # -- intraday ramp/crossfade state (ADR-006 §1b/§5, TASK-0013) --
        # Short-lived, per-string-index, never restart-persisted (see
        # `IntradayState`'s own docstring) — a plain dict store, unlike
        # every time-series-shaped cache above.
        self._intraday_state: dict[int, IntradayState] = {}

    # -- index <-> timestamp (ADR-007a §1) -----------------------------------

    @staticmethod
    def index_for(timestamp: datetime) -> int:
        """Absolute slot index for `timestamp`, from the fixed epoch."""
        return (timestamp - EPOCH) // SLOT_DURATION

    @staticmethod
    def timestamp_for(index: int) -> datetime:
        """The timestamp at the start of absolute slot `index`."""
        return EPOCH + index * SLOT_DURATION

    # -- introspection (read-only; mainly for tests/callers to inspect state) --

    def validated_range(self, sensor_id: str) -> tuple[int, int | None] | None:
        """The `(from_index, to_index)` currently valid for `sensor_id`,
        or `None` if this sensor has never been validated at all."""
        return self._validated.get(sensor_id)

    # -- internal storage helpers --------------------------------------------

    def _window_length(self) -> int:
        return self.window_days * SLOTS_PER_DAY

    def _ensure_sensor(self, sensor_id: str) -> None:
        if sensor_id not in self._values:
            self._values[sensor_id] = []
            self._list_offset[sensor_id] = 0
            self._shadow[sensor_id] = np.empty(0, dtype=np.float64)

    def _write(self, sensor_id: str, index: int, value: float | None | str) -> None:
        self._ensure_sensor(sensor_id)
        lst = self._values[sensor_id]
        shadow = self._shadow[sensor_id]
        shadow_value = _shadow_value(value)

        if not lst:
            self._list_offset[sensor_id] = index
            lst.append(value)
            self._shadow[sensor_id] = np.array([shadow_value], dtype=np.float64)
            return

        offset = self._list_offset[sensor_id]
        pos = index - offset
        if pos < 0:
            lst[0:0] = [None] * (-pos)
            self._list_offset[sensor_id] = index
            lst[0] = value
            shadow = np.concatenate((np.full(-pos, np.nan, dtype=np.float64), shadow))
            shadow[0] = shadow_value
        elif pos >= len(shadow):
            shadow = np.concatenate(
                (shadow, np.full(pos - len(shadow) + 1, np.nan, dtype=np.float64))
            )
            lst.extend([None] * (pos - len(lst) + 1))
            lst[pos] = value
            shadow[pos] = shadow_value
        else:
            lst[pos] = value
            shadow[pos] = shadow_value

        self._shadow[sensor_id] = shadow

    def _read(self, sensor_id: str, index: int) -> float | None | str:
        if sensor_id not in self._values:
            return None
        offset = self._list_offset[sensor_id]
        lst = self._values[sensor_id]
        pos = index - offset
        if pos < 0 or pos >= len(lst):
            return None
        return lst[pos]

    # -- validation / fetch injection (ADR-007a §4) --------------------------

    def _fetch_and_store(self, sensor_id: str, start: int, end: int) -> None:
        """Fetch `[start, end]` (inclusive) for `sensor_id` and store it,
        then widen `validated` to cover it."""
        start_ts = self.timestamp_for(start)
        end_ts = self.timestamp_for(end + 1)  # fetch_fn's end is exclusive
        fetched = self._fetch_fn(sensor_id, start_ts, end_ts)
        for offset_i, value in enumerate(fetched):
            self._write(sensor_id, start + offset_i, value)

        current = self._validated.get(sensor_id)
        if current is None:
            self._validated[sensor_id] = (start, end)
            return
        from_index, to_index = current
        new_from = min(from_index, start)
        new_to = end if to_index is None else max(to_index, end)
        self._validated[sensor_id] = (new_from, new_to)

    def _validate_range(self, sensor_id: str, start: int, end: int) -> None:
        """Bring `sensor_id` up to date for `[start, end]` before reading
        (ADR-007a §4) — on-demand, fetching only what's actually missing.
        """
        self._ensure_sensor(sensor_id)
        current = self._validated.get(sensor_id)

        if current is None:
            # No valid data at all: fetch the *entire* configured window,
            # not just the requested slice (ADR-007a §4).
            window_len = self._window_length()
            fetch_start = min(start, end - window_len + 1)
            self._fetch_and_store(sensor_id, fetch_start, end)
            return

        from_index, to_index = current
        if to_index is None:
            # Actively pushed by Shady — always current, never (re-)queried
            # (ADR-007a §2).
            return

        # Fetch only the missing head and/or tail, in one call each.
        if start < from_index:
            self._fetch_and_store(sensor_id, start, from_index - 1)
        if end > to_index:
            self._fetch_and_store(sensor_id, to_index + 1, end)

    # -- writing (ADR-007a §3) ------------------------------------------------

    def push(self, sensor_id: str, values: dict[int, float], not_before_index: int) -> None:
        """Write one or more calculated values directly into `sensor_id`'s
        series in a single call. Any index below `not_before_index` is
        silently dropped, never written — this is what keeps a slot's
        value frozen the moment it elapses (ADR-007a §3).

        Marks `sensor_id` as actively pushed (`to_index=None`, ADR-007a
        §2) — new values arrive by push from here on, not by query.
        """
        self._ensure_sensor(sensor_id)
        written: list[int] = []
        for index, value in values.items():
            if index < not_before_index:
                continue
            self._write(sensor_id, index, value)
            written.append(index)
        if not written:
            return

        current = self._validated.get(sensor_id)
        new_from = min(written) if current is None else min(current[0], min(written))
        self._validated[sensor_id] = (new_from, None)

    def invalidate(self, sensor_id: str, start: int, end: int) -> None:
        """Reset `sensor_id`'s values over `[start, end]` (inclusive) back
        to `None`, forcing the next access to re-fetch (or, for a
        push-based sensor, to wait for the next push) before serving that
        range again (ADR-007a §3).
        """
        self._ensure_sensor(sensor_id)
        for index in range(start, end + 1):
            self._write(sensor_id, index, None)

        current = self._validated.get(sensor_id)
        if current is None:
            return
        from_index, to_index = current
        if start <= from_index and (to_index is None or end >= to_index):
            del self._validated[sensor_id]
            return
        if start <= from_index <= end:
            from_index = end + 1
        elif to_index is not None and start <= to_index <= end:
            # Invalidating only the tail: shrink to_index. (A hole
            # strictly inside the range is conservatively treated the
            # same way — see module note below.)
            to_index = start - 1
        self._validated[sensor_id] = (from_index, to_index)

    # -- trimming (ADR-007a §1) -----------------------------------------------

    def trim(self, reference: datetime | None = None) -> None:
        """Drop each sensor's oldest entries once the rolling window has
        advanced past them, advancing `list_offset`. `validated` ranges
        are adjusted in place, not rewritten, so they stay meaningful
        across the trim (ADR-007a §1). The shadow array (ADR-008 §2) is
        trimmed by the exact same `drop_count`, in the same call, so it
        never drifts out of alignment with the three-state list.

        `reference` anchors "today" for the retention floor
        (`reference - window_days`); defaults to the real current time.
        Exposed as a parameter (rather than reading the wall clock
        internally) so this stays testable with zero mocking, the same
        way `fetch_fn` injection keeps validation testable.
        """
        now = reference if reference is not None else datetime.now(UTC)
        floor = self.index_for(now) - self._window_length() + 1

        for sensor_id in list(self._values):
            offset = self._list_offset[sensor_id]
            lst = self._values[sensor_id]
            if floor > offset:
                drop_count = min(floor - offset, len(lst))
                del lst[:drop_count]
                self._list_offset[sensor_id] = offset + drop_count
                self._shadow[sensor_id] = self._shadow[sensor_id][drop_count:]

            current = self._validated.get(sensor_id)
            if current is None:
                continue
            from_index, to_index = current
            new_from = max(from_index, floor)
            if to_index is not None and new_from > to_index:
                del self._validated[sensor_id]
            else:
                self._validated[sensor_id] = (new_from, to_index)

    # -- accessors (ADR-007a §5) -----------------------------------------------

    @overload
    def get_time_range(
        self,
        sensor_ids: list[str],
        start: datetime,
        end: datetime,
        on_invalid: OnInvalid = 0.0,
        group_by: Literal["sensor"] = "sensor",
    ) -> dict[str, list[float | None | str]]: ...

    @overload
    def get_time_range(
        self,
        sensor_ids: list[str],
        start: datetime,
        end: datetime,
        on_invalid: OnInvalid = 0.0,
        *,
        group_by: Literal["slot"],
    ) -> list[dict[str, float | None | str]]: ...

    def get_time_range(
        self,
        sensor_ids: list[str],
        start: datetime,
        end: datetime,
        on_invalid: OnInvalid = 0.0,
        group_by: Literal["sensor", "slot"] = "sensor",
    ) -> dict[str, list[float | None | str]] | list[dict[str, float | None | str]]:
        """Every slot in a contiguous range (ADR-007a §5): whole-day
        arrays, trailing rolling windows.

        `group_by="sensor"` → `{sensor_id: [v0, v1, ...]}`.
        `group_by="slot"` → `[{sensor_id: v, ...}, ...]`, one dict per
        slot — "for this slot, every string's value", ready to sum
        directly.

        Validates before reading (§4): fetches on-demand anything not
        already fresh for `sensor_ids` over `[start, end]`, for every
        `on_invalid` mode alike.
        """
        start_index = self.index_for(start)
        end_index = self.index_for(end)
        for sensor_id in sensor_ids:
            self._validate_range(sensor_id, start_index, end_index)

        if group_by == "sensor":
            sensor_result: dict[str, list[float | None | str]] = {}
            for sensor_id in sensor_ids:
                shaped_list: list[float | None | str] = []
                for index in range(start_index, end_index + 1):
                    keep, shaped = _shape(self._read(sensor_id, index), on_invalid)
                    if keep:
                        shaped_list.append(shaped)
                sensor_result[sensor_id] = shaped_list
            return sensor_result

        slot_result: list[dict[str, float | None | str]] = []
        for index in range(start_index, end_index + 1):
            slot_entry: dict[str, float | None | str] = {}
            for sensor_id in sensor_ids:
                keep, shaped = _shape(self._read(sensor_id, index), on_invalid)
                if keep:
                    slot_entry[sensor_id] = shaped
            slot_result.append(slot_entry)
        return slot_result

    def get_regression_pools(
        self,
        sensor_ids: list[str],
        smoothing_radius: int,
        reference: datetime | None = None,
    ) -> dict[str, NDArray[np.float64]]:
        """The full 288-slot regression sweep, batched (ADR-008 §2): one
        `(288, window_days * (2*smoothing_radius + 1))` `float64` array
        per sensor, in a single call — never 864 individual per-slot
        calls (ADR-008 §1's naive-per-slot rejection extends here).

        **Window:** the most recent `window_days` *complete* days,
        ending yesterday — never today, which recalibration (ADR-002 §1)
        never trains on. `reference` anchors "today" the same way
        `trim()`'s own `reference` parameter does: defaults to the real
        current time, but is exposed as a parameter so this stays
        testable with zero mocking rather than depending on the wall
        clock internally. This is an addition to ADR-008 §2's literal
        `(sensor_ids, smoothing_radius)` signature, not a deviation from
        it — omitting `reference` reproduces the ADR's real-time
        behavior exactly.

        **Column layout**, matching `regression/base.py`'s `build_pool`
        convention (TASK-0005's own "load-bearing" layout note):
        offsets concatenated in ascending order (`-smoothing_radius, ...,
        0, ..., +smoothing_radius`), each contributing exactly
        `window_days` columns, oldest day first within each block. A
        caller adapting this into `build_pool`'s `dict[int, NDArray]`-
        per-offset input contract (TASK-0005's own documented gap) slices
        out each `window_days`-wide block in this same order.

        **288-slot day-boundary wraparound** (`regression/base.py`'s
        "the caller has already applied any 288-slot wraparound" note)
        is resolved via plain absolute-index arithmetic — slot `s` with
        offset `o` on day `d` is simply absolute index
        `day_start(d) + s + o`, which is already correct whether or not
        `s + o` over/underflows `[0, 288)`, with no explicit modulo step
        needed. When that arithmetic lands *outside* this call's own
        window (the earliest day's negative-offset neighbors, or the
        latest/yesterday's positive-offset neighbors reaching into
        today), the cell is `NaN` — the same pad/invalid sentinel
        `regression/base.py` already treats as zero weight — rather than
        fetching one extra day beyond the configured window; in
        practice these are always near-midnight slots, where `FC ~ 0`
        makes `magnitude_weight_i` suppress them regardless.

        Built via broadcast/gather over the shadow array (ADR-008 §2's
        "strided views/concatenation", not the three-state list) —
        `_validate_range` is still called first, per sensor, over the
        exact window this call needs, so the shadow array is fetched/
        current before it's read.
        """
        now = reference if reference is not None else datetime.now(UTC)
        today_start = datetime(now.year, now.month, now.day, tzinfo=UTC)
        yesterday_start = today_start - timedelta(days=1)
        yesterday_day_index = self.index_for(yesterday_start)
        window_start_day_index = yesterday_day_index - (self.window_days - 1) * SLOTS_PER_DAY
        window_end_index = yesterday_day_index + SLOTS_PER_DAY - 1

        offsets = np.arange(-smoothing_radius, smoothing_radius + 1)
        slots = np.arange(SLOTS_PER_DAY)
        days = np.arange(self.window_days)

        # Broadcasts to shape (SLOTS_PER_DAY, window_days, 2*radius+1) —
        # absolute index for (target slot, day-in-window, neighbor offset).
        abs_index = (
            window_start_day_index
            + days[None, :, None] * SLOTS_PER_DAY
            + slots[:, None, None]
            + offsets[None, None, :]
        )

        pools: dict[str, NDArray[np.float64]] = {}
        for sensor_id in sensor_ids:
            self._validate_range(sensor_id, window_start_day_index, window_end_index)
            shadow = self._shadow[sensor_id]
            list_offset = self._list_offset[sensor_id]

            if len(shadow) == 0:
                gathered = np.full(abs_index.shape, np.nan, dtype=np.float64)
            else:
                pos = abs_index - list_offset
                valid = (pos >= 0) & (pos < len(shadow))
                clipped = np.clip(pos, 0, len(shadow) - 1)
                gathered = np.where(valid, shadow[clipped], np.nan)

            # (slot, day, offset) -> (slot, offset, day) -> (slot, offset*day)
            # so each offset contributes a contiguous window_days-wide
            # block, matching build_pool's column-layout convention.
            pools[sensor_id] = gathered.transpose(0, 2, 1).reshape(SLOTS_PER_DAY, -1)

        return pools

    # -- energy-integral totals (ADR-005 §5/§6) -------------------------------

    def energy_total(self, kind: EnergyKind) -> float:
        """The current running Wh total for `kind` ("pv" or "fc") —
        `coordinator.py`'s `ShadyPvEnergyIntegralSensor`/
        `ShadyFcEnergyIntegralSensor` read this directly."""
        return self._energy_totals[kind]

    def set_energy_total(self, kind: EnergyKind, value: float) -> None:
        """Write back `kind`'s running total — `coordinator.py` calls
        this after adding a `trapezoidal_energy_increment` (ADR-005
        §5/§6's implementation notes)."""
        self._energy_totals[kind] = value

    def last_energy_sample(self, kind: EnergyKind) -> tuple[datetime, float] | None:
        """The `(timestamp, power)` sample last accumulated for `kind`,
        or `None` if there is no prior sample to form a trapezoidal
        interval with yet — either genuinely the first sample ever, or
        the first one since a reset (midnight or restart) cleared it."""
        return self._last_energy_samples[kind]

    def set_last_energy_sample(
        self, kind: EnergyKind, sample: tuple[datetime, float] | None
    ) -> None:
        """Remember the sample just accumulated, for the next
        `trapezoidal_energy_increment` call's `previous` argument."""
        self._last_energy_samples[kind] = sample

    def last_reset_date(self) -> date | None:
        """The calendar date (HA's local timezone, per `coordinator.py`'s
        own `now.date()`) both totals were last zeroed for — `None` if
        never reset/restored at all yet (a brand-new instance, before
        `coordinator.py`'s startup idempotency check has run). Backs the
        restart-during-the-reset-window idempotency check (ADR-005 §5/§6
        Implementation notes)."""
        return self._last_reset_date

    def reset_energy_totals(self, today: date) -> None:
        """Zero both energy-integral totals and clear both remembered
        last-samples (ADR-005 §5/§6's midnight reset). Clearing the
        last-samples — not just zeroing the totals — is what actually
        matters here: the next `trapezoidal_energy_increment` call for
        either kind then starts from `previous=None` and so contributes
        zero, rather than bridging an interval across the reset using a
        now-stale pre-reset sample. `today` becomes the new
        `last_reset_date`, closing the idempotency check for this day
        regardless of whether this call came from the midnight schedule,
        startup, or (in the pathological both-in-one-window case) both.
        """
        self._energy_totals = {"pv": 0.0, "fc": 0.0}
        self._last_energy_samples = {"pv": None, "fc": None}
        self._last_reset_date = today

    def restore_energy_state(self, pv_total: float, fc_total: float, last_reset_date: date) -> None:
        """Restart-persistence entry point (ADR-005 §5/§6, ADR-007 §1) —
        `coordinator.py`'s `async_restore_energy_state` calls this with
        whatever it loaded from storage. Deliberately does **not**
        restore either `last_energy_sample`: they stay `None` (this
        instance's fresh-construction default), so the first
        accumulation after a restart always starts from `previous=None`
        — exactly like a fresh midnight reset — rather than bridging a
        trapezoidal increment across the restart gap using a sample
        that is now stale by an unknown, possibly-large amount of time.
        """
        self._energy_totals = {"pv": pv_total, "fc": fc_total}
        self._last_reset_date = last_reset_date

    # -- intraday ramp/crossfade state (ADR-006 §1b/§5) ------------------

    def intraday_state(self, string_index: int) -> IntradayState | None:
        """This string's current ramp/crossfade state, or `None` if
        intraday correction is off, or no recompute has produced a
        basis for it yet since setup (or since this state was last
        cleared)."""
        return self._intraday_state.get(string_index)

    def set_intraday_state(self, string_index: int, state: IntradayState | None) -> None:
        """Write back `string_index`'s ramp/crossfade state —
        `coordinator.py` calls this at every reset point (a fresh
        recompute) and at every 5-minute tick. `state=None` clears it
        (never needed by TASK-0013's own coordinator logic today, which
        always has a fresh `IntradayState` to write instead, but kept
        symmetric with `set_last_energy_sample`'s own `| None` shape for
        a future caller that genuinely needs to clear it)."""
        if state is None:
            self._intraday_state.pop(string_index, None)
        else:
            self._intraday_state[string_index] = state
