"""`aggregation.py` — pure cross-string aggregation math (ADR-005,
TASK-0012).

No `hass` import, no per-string knowledge of *which* string a value
came from (ADR-005's own module-diagram note) — only lists of numbers
in, one number or array out. Two families of pure logic:

- **Cross-string sums** (`sum_values`, §1/§2) and the per-slot-to-daily-
  energy conversion built on top of it (`slot_energy_wh`,
  `day_energy_total_wh`, `remaining_energy_wh`, §3/§4).
- **The trapezoidal energy-increment calculation** (§5/§6's
  implementation notes): given a previous `(timestamp, power)` sample
  and a new one, the Wh increment between them.

`coordinator.py` is the only caller (ADR-005's module diagram: "calls
`aggregation.py` for all six sensors") — `sensor.py` stays thin,
reading only whatever `coordinator.py` already computed via this
module, never calling into it directly.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime

# One 5-minute slot, in hours (ADR-005 §3) — the one place a
# slot-power-to-slot-energy conversion is needed in the whole design.
_SLOT_HOURS = 5.0 / 60.0


def sum_values(values: Iterable[float | None]) -> float | None:
    """Cross-string sum (ADR-005 §1/§2): a plain sum of whatever floats
    are present. `None` entries (a string with nothing available yet)
    are excluded, not treated as a zero contribution — the difference
    between "this string currently reports zero" and "this string has
    no value at all" matters, and only the former should pull the sum
    down. Returns `None`, not `0.0`, when every value is `None` —
    "nothing to sum" is a distinct case from "the sum is zero".
    """
    present = [value for value in values if value is not None]
    if not present:
        return None
    return sum(present)


def slot_energy_wh(power_w: float) -> float:
    """One slot's power (W) -> energy (Wh) conversion (ADR-005 §3):
    power x this slot's 5-minute duration, in hours."""
    return power_w * _SLOT_HOURS


def day_energy_total_wh(slot_values: Iterable[float | None]) -> float:
    """Sigma (P_i x 5/60) over a whole day's `slot_values` (ADR-005
    §3's own sensor state) — a `None` slot (nothing pushed yet, or
    invalidated) contributes zero energy, simply excluded from the
    sum, never synthesized as an actual zero-power reading.
    """
    return sum(slot_energy_wh(value) for value in slot_values if value is not None)


def remaining_energy_wh(
    slot_timestamps: Sequence[datetime], slot_values: Sequence[float | None], now: datetime
) -> float:
    """ADR-005 §4: the same calculation as `day_energy_total_wh`,
    restricted to the slots whose timestamp is at or after `now` —
    pure post-processing of the exact same arrays §3 already produced,
    with no second data-retention mechanism of its own (ADR-005 §4/
    Consequences).
    """
    return sum(
        slot_energy_wh(value)
        for timestamp, value in zip(slot_timestamps, slot_values, strict=True)
        if value is not None and timestamp >= now
    )


def trapezoidal_energy_increment(
    previous: tuple[datetime, float] | None, current: tuple[datetime, float]
) -> float:
    """The Wh increment between a previous `(timestamp, power)` sample
    and a new one (ADR-005 §5/§6's implementation notes) — the
    trapezoidal rule, average power x elapsed time.

    `previous=None` (the first sample ever, or the first one right
    after a midnight reset — `cache.py`'s own `reset_energy_totals`
    clears the remembered "last sample" for exactly this reason)
    contributes zero: there is no prior point yet to form an interval
    with. Remembering `current` as the new "last sample" for the next
    call is the caller's job (`coordinator.py`, via `cache.py`'s
    `set_last_energy_sample`), not this pure function's — it only
    ever computes one increment per call, never mutates anything.

    A non-advancing or out-of-order pair (`current`'s timestamp at or
    before `previous`'s) also contributes zero rather than a negative
    increment — the running total only ever moves forward.
    """
    if previous is None:
        return 0.0
    previous_timestamp, previous_power = previous
    current_timestamp, current_power = current
    elapsed_hours = (current_timestamp - previous_timestamp).total_seconds() / 3600.0
    if elapsed_hours <= 0:
        return 0.0
    return (previous_power + current_power) / 2.0 * elapsed_hours
