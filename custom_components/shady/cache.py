"""Pure rolling cache for Shady."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import numpy as np

from .providers.base import ThreeStateValue

SlotGroup = Literal["sensor", "slot"]
InvalidMode = Literal["skip", "raw"] | float

__all__ = ["InvalidMode", "ShadyCache", "SlotGroup"]


class ShadyCache:
    """Index-addressable rolling cache with validate-before-read semantics."""

    def __init__(
        self,
        window_days: int,
        fetch_fn: Callable[[str, datetime, datetime], list[ThreeStateValue]],
        *,
        epoch: datetime | None = None,
    ) -> None:
        if window_days <= 0:
            raise ValueError("window_days must be positive")
        self.window_days = window_days
        self.window_slots = window_days * 288
        self.fetch_fn = fetch_fn
        self.epoch = epoch or datetime(1970, 1, 1)
        self.values: dict[str, list[ThreeStateValue]] = {}
        self.shadow: dict[str, np.ndarray] = {}
        self.list_offset: dict[str, int] = {}
        self.validated: dict[str, tuple[int, int | None]] = {}
        self.integral_totals: dict[str, float] = {"pv_energy": 0.0, "fc_energy": 0.0}
        self.last_reset_date: date | None = None
        self.intraday_state: dict[str, dict[str, object]] = {}
        self.pinned_reference: date | None = None

    def _index_for(self, moment: datetime) -> int:
        if moment.tzinfo is not None:
            moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
        delta = moment - self.epoch
        return int(delta.total_seconds() // 300)

    def _moment_for(self, index: int) -> datetime:
        return self.epoch + timedelta(minutes=5 * index)

    def _ensure_sensor(self, sensor_id: str) -> None:
        if sensor_id not in self.values:
            self.values[sensor_id] = []
            self.list_offset[sensor_id] = 0

    def _ensure_shadow(self, sensor_id: str) -> None:
        if sensor_id not in self.shadow:
            self.shadow[sensor_id] = np.full(len(self.values.get(sensor_id, [])), np.nan, dtype=float)

    def _ensure_index_range(self, sensor_id: str, start_index: int, end_index: int) -> None:
        self._ensure_sensor(sensor_id)
        self._ensure_shadow(sensor_id)
        offset = self.list_offset[sensor_id]
        values = self.values[sensor_id]
        shadow = self.shadow[sensor_id]
        if not values:
            self.list_offset[sensor_id] = start_index
            length = end_index - start_index + 1
            values.extend([None] * length)
            self.shadow[sensor_id] = np.full(length, np.nan, dtype=float)
            return

        if start_index < offset:
            prepend = offset - start_index
            values[:0] = [None] * prepend
            self.shadow[sensor_id] = np.concatenate((np.full(prepend, np.nan, dtype=float), shadow))
            self.list_offset[sensor_id] = start_index
            offset = start_index
            shadow = self.shadow[sensor_id]

        tail_index = offset + len(values) - 1
        if end_index > tail_index:
            extension = end_index - tail_index
            values.extend([None] * extension)
            self.shadow[sensor_id] = np.concatenate((shadow, np.full(extension, np.nan, dtype=float)))

    def _value_at_index(self, sensor_id: str, index: int) -> ThreeStateValue:
        values = self.values.get(sensor_id)
        if values is None:
            return None
        offset = self.list_offset[sensor_id]
        if index < offset:
            return None
        position = index - offset
        if position >= len(values):
            return None
        return values[position]

    def _write_value(self, sensor_id: str, index: int, value: ThreeStateValue) -> None:
        self._ensure_index_range(sensor_id, index, index)
        values = self.values[sensor_id]
        offset = self.list_offset[sensor_id]
        position = index - offset
        values[position] = value
        self.shadow[sensor_id][position] = self._shadow_value(value)

    @staticmethod
    def _shadow_value(value: ThreeStateValue) -> float:
        if isinstance(value, float):
            return value
        if isinstance(value, int) and not isinstance(value, bool):
            return float(value)
        return np.nan

    def _recalculate_validated(self, sensor_id: str) -> None:
        values = self.values.get(sensor_id, [])
        offset = self.list_offset.get(sensor_id, 0)
        first: int | None = None
        last: int | None = None
        for position, value in enumerate(values):
            if value is None:
                continue
            absolute_index = offset + position
            if first is None:
                first = absolute_index
            last = absolute_index
        if first is None or last is None:
            self.validated[sensor_id] = (offset, offset - 1)
            return
        validated = self.validated.get(sensor_id)
        if validated is not None and validated[1] is None:
            self.validated[sensor_id] = (first, None)
            return
        self.validated[sensor_id] = (first, last)

    def _fetch_missing_range(self, sensor_id: str, start_index: int, end_index: int) -> None:
        self._ensure_shadow(sensor_id)
        start = self._moment_for(start_index)
        end = self._moment_for(end_index)
        fetched = self.fetch_fn(sensor_id, start, end)
        self._ensure_index_range(sensor_id, start_index, end_index)
        values = self.values[sensor_id]
        shadow = self.shadow[sensor_id]
        offset = self.list_offset[sensor_id]
        for position, value in enumerate(fetched[: end_index - start_index + 1]):
            absolute_position = start_index - offset + position
            values[absolute_position] = value
            shadow[absolute_position] = self._shadow_value(value)
        self._recalculate_validated(sensor_id)

    def _validate_sensor(self, sensor_id: str, start_index: int, end_index: int) -> None:
        validated = self.validated.get(sensor_id)
        if validated is not None and validated[1] is None:
            return
        if start_index > end_index:
            return
        values = self.values.get(sensor_id, [])
        if not any(value is not None for value in values):
            window_start = end_index - self.window_slots + 1
            self._fetch_missing_range(sensor_id, window_start, end_index)
            return
        missing_start: int | None = None
        missing_end: int | None = None
        for index in range(start_index, end_index + 1):
            if self._value_at_index(sensor_id, index) is None:
                if missing_start is None:
                    missing_start = index
                missing_end = index
            elif missing_start is not None and missing_end is not None:
                self._fetch_missing_range(sensor_id, missing_start, missing_end)
                missing_start = None
                missing_end = None
        if missing_start is not None and missing_end is not None:
            self._fetch_missing_range(sensor_id, missing_start, missing_end)

    def push(
        self,
        sensor_id: str,
        values: dict[int, ThreeStateValue],
        *,
        not_before_index: int,
    ) -> None:
        self._ensure_sensor(sensor_id)
        accepted: list[int] = []
        for index, value in sorted(values.items()):
            if index < not_before_index:
                continue
            self._write_value(sensor_id, index, value)
            accepted.append(index)

        if not accepted:
            self._recalculate_validated(sensor_id)
            return

        validated = self.validated.get(sensor_id)
        min_index = min(accepted)
        max_index = max(accepted)
        if validated is None:
            self.validated[sensor_id] = (min_index, max_index)
        elif validated[1] is None:
            self.validated[sensor_id] = (min(validated[0], min_index), None)
        else:
            self.validated[sensor_id] = (min(validated[0], min_index), max(validated[1], max_index))

    def invalidate(self, sensor_id: str, start_index: int, end_index: int) -> None:
        self._ensure_sensor(sensor_id)
        self._ensure_shadow(sensor_id)
        self._ensure_index_range(sensor_id, start_index, end_index)
        values = self.values[sensor_id]
        shadow = self.shadow[sensor_id]
        offset = self.list_offset[sensor_id]
        for index in range(start_index, end_index + 1):
            if index < offset:
                continue
            position = index - offset
            if 0 <= position < len(values):
                values[position] = None
                shadow[position] = np.nan
        self._recalculate_validated(sensor_id)

    def trim(self) -> None:
        for sensor_id, values in list(self.values.items()):
            self._ensure_shadow(sensor_id)
            if len(values) <= self.window_slots:
                continue
            excess = len(values) - self.window_slots
            self.values[sensor_id] = values[excess:]
            self.shadow[sensor_id] = self.shadow[sensor_id][excess:]
            self.list_offset[sensor_id] += excess
            validated = self.validated.get(sensor_id)
            if validated is None:
                continue
            from_index, to_index = validated
            if to_index is None:
                self.validated[sensor_id] = (max(from_index, self.list_offset[sensor_id]), None)
                continue
            if to_index < self.list_offset[sensor_id]:
                self.validated[sensor_id] = (self.list_offset[sensor_id], self.list_offset[sensor_id] - 1)
            else:
                self.validated[sensor_id] = (
                    max(from_index, self.list_offset[sensor_id]),
                    to_index,
                )

    def get_regression_pools(self, sensor_ids: list[str], smoothing_radius: int) -> dict[str, np.ndarray]:
        if smoothing_radius < 0:
            raise ValueError("smoothing_radius must be non-negative")

        width = self.window_days * (2 * smoothing_radius + 1)
        pools: dict[str, np.ndarray] = {}
        for sensor_id in sensor_ids:
            self._ensure_sensor(sensor_id)
            self._ensure_shadow(sensor_id)
            shadow = self.shadow[sensor_id]
            offset = self.list_offset[sensor_id]
            rows = np.full((288, width), np.nan, dtype=float)
            column_index = 0
            for day_index in range(self.window_days):
                day_offset = day_index * 288
                for neighbor in range(-smoothing_radius, smoothing_radius + 1):
                    for slot_of_day in range(288):
                        absolute_index = offset + day_offset + slot_of_day + neighbor
                        if absolute_index < offset:
                            continue
                        position = absolute_index - offset
                        if 0 <= position < len(shadow):
                            rows[slot_of_day, column_index] = shadow[position]
                    column_index += 1
            pools[sensor_id] = rows
        return pools

    def pin_reference(self, reference: date) -> None:
        self.pinned_reference = reference

    def clear_reference(self) -> None:
        self.pinned_reference = None

    def get_pinned_slot_pool(
        self,
        sensor_ids: list[str],
        slot_of_day: int,
        on_invalid: InvalidMode = "skip",
    ) -> dict[str, list[float | ThreeStateValue]]:
        if slot_of_day < 0 or slot_of_day >= 288:
            raise ValueError("slot_of_day must be within 0..287")

        reference = self.pinned_reference or date.today()
        today = date.today()
        if reference > today:
            reference = today
        start_date = reference - timedelta(days=self.window_days)
        result: dict[str, list[float | ThreeStateValue]] = {sensor_id: [] for sensor_id in sensor_ids}
        for day_offset in range(self.window_days + 1):
            day = start_date + timedelta(days=day_offset)
            hour, minute = divmod(slot_of_day * 5, 60)
            moment = datetime(day.year, day.month, day.day, hour, minute)
            index = self._index_for(moment)
            for sensor_id in sensor_ids:
                self._validate_sensor(sensor_id, index, index)
                value = self._value_at_index(sensor_id, index)
                include, shaped_value = self._shape_invalid(value, on_invalid)
                if include:
                    result[sensor_id].append(shaped_value)
        return result

    def _shape_invalid(
        self,
        value: ThreeStateValue,
        on_invalid: InvalidMode,
    ) -> tuple[bool, float | ThreeStateValue | None]:
        if isinstance(value, float):
            return True, value
        if on_invalid == "raw":
            return True, value
        if on_invalid == "skip":
            return False, None
        return True, float(on_invalid)

    def get_time_range(
        self,
        sensor_ids: list[str],
        start: datetime,
        end: datetime,
        on_invalid: InvalidMode = 0.0,
        group_by: SlotGroup = "sensor",
    ) -> dict[str, list[float | ThreeStateValue]] | list[dict[str, float | ThreeStateValue]]:
        start_index = self._index_for(start)
        end_index = self._index_for(end)
        for sensor_id in sensor_ids:
            self._validate_sensor(sensor_id, start_index, end_index)

        if group_by == "sensor":
            result: dict[str, list[float | ThreeStateValue]] = {}
            for sensor_id in sensor_ids:
                shaped: list[float | ThreeStateValue] = []
                for index in range(start_index, end_index + 1):
                    value = self._value_at_index(sensor_id, index)
                    include, shaped_value = self._shape_invalid(value, on_invalid)
                    if not include:
                        continue
                    shaped.append(shaped_value)
                result[sensor_id] = shaped
            return result

        grouped: list[dict[str, float | ThreeStateValue]] = []
        for index in range(start_index, end_index + 1):
            slot: dict[str, float | ThreeStateValue] = {}
            for sensor_id in sensor_ids:
                value = self._value_at_index(sensor_id, index)
                include, shaped_value = self._shape_invalid(value, on_invalid)
                if not include:
                    continue
                slot[sensor_id] = shaped_value
            grouped.append(slot)
        return grouped

    def get_integral_total(self, key: str) -> float:
        return float(self.integral_totals.get(key, 0.0))

    def set_integral_total(self, key: str, value: float) -> None:
        self.integral_totals[key] = float(value)

    def reset_integral_totals(self, reset_date: date) -> None:
        self.integral_totals["pv_energy"] = 0.0
        self.integral_totals["fc_energy"] = 0.0
        self.last_reset_date = reset_date

    def get_intraday_state(self, sensor_id: str) -> dict[str, object]:
        return dict(self.intraday_state.get(sensor_id, {}))

    def set_intraday_state(self, sensor_id: str, state: dict[str, object]) -> None:
        self.intraday_state[sensor_id] = dict(state)

    def clear_intraday_state(self, sensor_id: str) -> None:
        self.intraday_state.pop(sensor_id, None)
