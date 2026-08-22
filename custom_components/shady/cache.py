"""`cache.py` — pure, index-addressable time-series store (ADR-007, ADR-007a).

No `hass` import — constructed with an injected `fetch_fn` so it never
imports the recorder API itself (ADR-007a §4). Only ever called from
`coordinator.py` (ADR-007 §2).

This module currently implements the storage core: the three-state
(`float | None | str`) value model (§1), validated-range tracking (§2),
`push`/`invalidate` (§3), the injected-`fetch_fn` validate-before-read
step (§4), and the contiguous-range `get_time_range` accessor (§5). The
other two accessors — `get_pinned_slot_pool` (ADR-007a §6) and
`get_regression_pools` (ADR-008 §2) — are deliberately out of scope here;
each is added alongside its own caller (TASK-0006, TASK-0015).

**`fetch_fn` calling convention** (established here, binding for every
caller — `coordinator.py`, and matching `providers/base.py`'s `Provider.
fetch` signature, ADR-012 §1): `fetch_fn(sensor_id, start, end)` returns
exactly one value per 5-minute slot in the **half-open** interval
`[start, end)` — `start` inclusive, `end` exclusive — so a request for
`n` slots returns a list of length `n`.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Literal, overload

SLOT_MINUTES = 5
SLOT_DURATION = timedelta(minutes=SLOT_MINUTES)
SLOTS_PER_DAY = 24 * 60 // SLOT_MINUTES  # 288

# Fixed epoch absolute indices are measured from (ADR-007a §1). Any date
# before Shady's own existence works; the exact value is otherwise
# arbitrary and never observed outside this module.
EPOCH = datetime(2020, 1, 1, tzinfo=UTC)

FetchFn = Callable[[str, datetime, datetime], list[float | None | str]]
OnInvalid = Literal["skip", "raw"] | float


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

    def _write(self, sensor_id: str, index: int, value: float | None | str) -> None:
        self._ensure_sensor(sensor_id)
        lst = self._values[sensor_id]
        if not lst:
            self._list_offset[sensor_id] = index
            lst.append(value)
            return
        offset = self._list_offset[sensor_id]
        pos = index - offset
        if pos < 0:
            lst[0:0] = [None] * (-pos)
            self._list_offset[sensor_id] = index
            lst[0] = value
        elif pos >= len(lst):
            lst.extend([None] * (pos - len(lst) + 1))
            lst[pos] = value
        else:
            lst[pos] = value

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
        across the trim (ADR-007a §1).

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
