"""`aggregation.py` — pure cross-string aggregation math (ADR-005,
TASK-0012) plus per-string intraday-deviation-correction math (ADR-006
§5, TASK-0013).

No `hass` import, no per-string knowledge of *which* string a value
came from (ADR-005's own module-diagram note) — only numbers in, one
number or array out. Three families of pure logic:

- **Cross-string sums** (`sum_values`, §1/§2) and the per-slot-to-daily-
  energy conversion built on top of it (`slot_energy_wh`,
  `day_energy_total_wh`, `remaining_energy_wh`, §3/§4).
- **The trapezoidal energy-increment calculation** (§5/§6's
  implementation notes): given a previous `(timestamp, power)` sample
  and a new one, the Wh increment between them.
- **Intraday deviation correction** (ADR-006 §1a/§1b/§2/§5):
  `ramp_weight` (the `w(t)` ramp), `intraday_correction_factor` (the
  ratio-clamp-and-ramp math in one function), and `crossfade`
  (Blending's old/new linear blend) — all per-string scalars, called
  once (Ramping) or twice (Blending, once per side) per string per
  5-minute tick by `coordinator.py`, never per-slot: the same
  `effective_factor`/`w` applies uniformly across every one of a
  string's future slots at a given computation instant (ADR-006 §4).
- **Diagnostic accuracy** (ADR-004 §2/§2b, TASK-0015b): `diagnostic_
  accuracy` (`1 - |predicted-actual|/actual`, clamped to `[0, 1]`) and
  `sum_predicted` (§2b's pointwise per-method sum across strings, ready
  to feed back into `diagnostic_accuracy` alongside `sum_values`'s own
  summed actual). Deliberately kept here, not in `diagnostics/`
  (ADR-004 §5 Amendment) — mode-independent, so ADR-013's sketched
  future modes can reuse it unmodified.

`coordinator.py`/`diagnostics/` are the only callers (ADR-005's module
diagram: "calls `aggregation.py` for all six sensors"; ADR-006 §5's
module-placement note for the three functions above; ADR-004 §5's
Amendment for the two diagnostic functions) — `sensor.py` stays thin,
reading only whatever `coordinator.py`/`diagnostics/` already computed
via this module, never calling into it directly.
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


# -- ADR-006 §1a/§1b/§2/§5: intraday deviation correction --------------------


def ramp_weight(active_slots_since_reset: int, ramp_slots: int) -> float:
    """`w(t) = min(1, active_slots_since_reset / ramp_slots)` (ADR-006
    §1a) — the linear ramp shared by Ramping's own ramp-in, every
    provider-update restart under either state, and Blending's
    `w_blend` (§1b: "the same counter, same duration as
    effective_factor_new's own w").

    `ramp_slots <= 0` defensively (ADR-000 §8) returns `1.0` (fully
    ramped immediately) rather than raising a `ZeroDivisionError` — a
    config-flow value of `0` would otherwise be indistinguishable from
    a crash; `active_slots_since_reset <= 0` returns `0.0` (not yet
    started) directly, without dividing at all.
    """
    if ramp_slots <= 0:
        return 1.0
    if active_slots_since_reset <= 0:
        return 0.0
    return min(1.0, active_slots_since_reset / ramp_slots)


def intraday_correction_factor(
    pv_energy_window: float,
    fc_energy_window: float,
    ramp_weight: float,
    intraday_correction_cutoff: float,
) -> float:
    """`effective_factor(t)` (ADR-006 §1a/§2) in one function: the
    trailing-window ratio `pv_energy_window / fc_energy_window`,
    clamped to `[1 - intraday_correction_cutoff, 1 +
    intraday_correction_cutoff]`, then ramped in via `ramp_weight` —
    `1 + ramp_weight × (clamped_ratio - 1)`. At `ramp_weight == 0` this
    is exactly `1` (no correction applied yet, ADR-006 §1a); at
    `ramp_weight == 1` it is the full clamped ratio.

    `fc_energy_window <= 0` (no meaningful denominator — e.g. right at
    a reset point, before any forecast energy has accumulated in the
    still-emptying window) treats the raw ratio as `1.0` — "no
    correction basis" — rather than raising or dividing by zero,
    matching this design's established defensive-clamp philosophy
    (ADR-000 §8) for unexpected/degenerate numeric input.

    Called once per string, per 5-minute tick, under Ramping, and
    twice (once per side — the frozen old side and the live new side)
    under Blending (ADR-006 §5) — never per-slot: the same
    `effective_factor` this returns is applied uniformly across every
    one of that string's future slots for this tick (ADR-006 §4).
    """
    ratio = 1.0 if fc_energy_window <= 0 else pv_energy_window / fc_energy_window
    clamped_ratio = min(
        1.0 + intraday_correction_cutoff, max(1.0 - intraday_correction_cutoff, ratio)
    )
    return 1.0 + ramp_weight * (clamped_ratio - 1.0)


def crossfade(old_prediction: float, new_prediction: float, ramp_weight: float) -> float:
    """Blending's linear old/new blend (ADR-006 §1b):
    `(1 - ramp_weight) × old_prediction + ramp_weight × new_prediction`.

    `old_prediction` is `old_fc_value(t) × effective_factor_frozen` —
    the pre-update reverse-transformed value, still unclamped, times
    the ratio snapshot frozen the instant before the update fired.
    `new_prediction` is `new_fc_value(t) × effective_factor_new(t)` —
    the same shape, freshly ramping from the update. `ramp_weight` here
    is `w_blend`, driven by the same counter and duration as the new
    side's own ramp (ADR-006 §1b) — at `ramp_weight == 0` this returns
    `old_prediction` unchanged (nothing new has taken over yet); at
    `ramp_weight == 1` it returns `new_prediction` exactly, the point at
    which Blending converges to the identical steady state Ramping
    would show for the same slot.
    """
    return (1.0 - ramp_weight) * old_prediction + ramp_weight * new_prediction


# -- diagnostic accuracy (ADR-004 §2/§2b, TASK-0015b) ------------------------


def diagnostic_accuracy(predicted: float, actual: float) -> float:
    """`1 - |predicted - actual| / actual`, clamped to `[0, 1]` (ADR-004
    §2) — never a negative number even when `predicted` is more than
    100% off from `actual`. Used both per-string (`predicted`/`actual`
    the diagnosed slot's own selected values) and, via `sum_predicted`
    below, for the diagnostic "sum" sensor's summed-then-accuracy figure
    (ADR-004 §2b) — the same formula either way, only the inputs differ.

    `actual == 0` has no well-defined ratio; treated defensively
    (ADR-000 §8) as `0.0` accuracy rather than raising — a real-world
    zero-yield slot (e.g. deep night) is never actually a *diagnosed*
    slot in practice (ADR-004 §2's "last complete slot" starts from
    whatever the baseline forecast already has data for), but this
    keeps the function total rather than assuming that.
    """
    if actual == 0.0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - abs(predicted - actual) / actual))


def sum_predicted(predicted_by_string: Iterable[dict[str, float]]) -> dict[str, float]:
    """ADR-004 §2b's pointwise per-method sum across strings: Σpredicted
    per regression method, ready to pass into `diagnostic_accuracy`
    alongside `sum_values`'s own Σactual for the diagnostic "sum" sensor
    — summed *first*, accuracy derived from the sums, not averaged from
    each string's own already-computed accuracy.

    A string missing a given method entirely (should not happen in
    practice — every string is fit against the same four strategies —
    but defensively, ADR-000 §8) simply does not contribute to that
    method's sum, rather than the whole sum being dropped.
    """
    totals: dict[str, float] = {}
    for predicted in predicted_by_string:
        for method, value in predicted.items():
            totals[method] = totals.get(method, 0.0) + value
    return totals
