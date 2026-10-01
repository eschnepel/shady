"""Shared provider base class and two HA-agnostic helpers (ADR-012 §1/§1a).

Every concrete provider (baseline discovery, temperature) subclasses
`Provider` below. This module holds only the shared base class and the
two small assembly/mapping primitives both concrete providers need — no
concrete provider logic lives here (ADR-012 §1).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class EntityRef:
    """A resolved reference to a Home Assistant entity, and optionally a
    specific attribute on it (e.g. a `weather.*` entity's `forecast`
    attribute rather than its main state).
    """

    entity_id: str
    attribute: str | None = None


class Provider(ABC):
    """Shared base class for external time-series providers (ADR-012 §1).

    Four methods, two calling conventions:

    - `fetch` — required, pull path. No base-class default; a subclass
      that omits it fails to instantiate.
    - `identify` — optional, discovery. Defaults to `None` (nothing to
      discover).
    - `forward` — optional, push path. Defaults to `None` (this
      provider's series is not genuinely forward-looking).
    - `history_entity_id` — optional, recorder-backed pull-path assist
      (ADR-012 §2a Amendment). Defaults to `None` (no linked history
      source; `fetch()` alone answers every `coordinator.py` query for
      this provider).
    """

    @abstractmethod
    def fetch(self, start: datetime, end: datetime) -> list[float | None | str]:
        """Pull this provider's values for `[start, end)`.

        Matches `cache.py`'s `fetch_fn` signature (ADR-007a §4) exactly,
        so a provider's `fetch` can be wired in as a cache's `fetch_fn`
        directly, with no adapter layer in between. Invoked reactively,
        only when `cache.py`'s validation function finds a gap — never on
        a schedule of the provider's own.
        """

    def identify(self) -> EntityRef | None:
        """Resolve which entity this provider is currently bound to.

        Only meaningful for a provider that performs discovery/scoring.
        A provider with nothing to discover simply doesn't override this.
        """
        return None

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None:
        """Return what this provider currently believes about the future.

        Only meaningful for a provider whose live series is genuinely
        forward-looking (a forecast, not a plain current reading). A
        provider with no forecast concept of its own leaves this default
        in place and never participates in the coordinator's push path
        (ADR-012 §4).
        """
        return None

    def history_entity_id(self) -> str | None:
        """Return the entity_id of a linked, recorder-backed history
        source for this provider, if one exists (ADR-012 §2a).

        Only meaningful for a provider whose own `fetch()` has no genuine
        retrospective capability for at least part of its data (e.g. a
        push-sourced series with nothing queryable for a past-dated
        range — ADR-009 §1a/§1b/§1c) but which has identified a separate,
        ordinary HA entity representing the same physical quantity,
        continuously sampled, whose own recorder history is a safe
        stand-in. The base class default returns `None` (nothing linked)
        — a provider with a fully self-sufficient `fetch()`, or with no
        safely-linkable history source at all, leaves this default in
        place, mirroring `identify()`/`forward()`'s own opt-in shape
        above. `coordinator.py`'s `_fetch_fn` (ADR-012 §2a) checks this
        generically for every provider, exactly the way the one generic
        push loop (§4) already checks `forward()` generically — a future
        provider (another PV-forecast shape, a weather-history proxy, …)
        that resolves one of these picks up recorder-backed backfill
        automatically the moment it overrides this method, with no new
        `coordinator.py` code and no per-provider `isinstance` check
        needed, the same "free" genericity §4's Consequences already
        claims for `forward()`.
        """
        return None


def map_state_value(raw: float | str | None) -> float | None | str:
    """Map a `hass.states`-shaped raw reading to `cache.py`'s three-state
    value model (ADR-007a §1): a known numeric `float`, `None` (not yet
    known / must be re-queried), or a known, stable, non-numeric `str`
    outcome (e.g. `"unavailable"`).

    `raw` mirrors what a caller would actually have in hand after reading
    `hass.states` or an entity attribute: a numeric value, the entity's
    state text (Home Assistant represents `"unknown"`/`"unavailable"` as
    plain state strings, alongside numeric values that are also strings),
    or `None` if the attribute was simply absent.

    - `None` (attribute absent) → `None` — nothing to map, not yet known.
    - A numeric value (`int`/`float`, or a numeric string) → `float`.
    - The state string `"unknown"` → `None` — HA's own signal that the
      entity exists but has no determined value yet; may recover on the
      next read, so it is treated the same as "not yet known".
    - Any other non-numeric string (e.g. `"unavailable"`) → returned
      as-is. This is a stable, definite, non-numeric outcome: querying
      again would return the same non-answer, so it is kept distinct
      from `None` rather than discarded.
    """
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = raw.strip()
    if text.lower() == "unknown":
        return None
    try:
        return float(text)
    except ValueError:
        return text


def assemble_series(
    pairs: Mapping[datetime, float] | Sequence[Mapping[str, Any]],
    *,
    datetime_key: str = "datetime",
    value_key: str = "value",
) -> list[tuple[datetime, float]]:
    """Assemble already-resolved timestamp/value pairs into the canonical
    `list[tuple[datetime, float]]` series shape (ADR-009 §2).

    Accepts either shape a resolved source might hand back:

    - a `{timestamp: value}` mapping, or
    - a list of per-entry mappings, each already keyed by `datetime_key`/
      `value_key` (default `"datetime"`/`"value"`).

    This is deliberately scoped to the low-level assembly step only — the
    caller (`providers/normalize.py`'s alias-guessing/candidate-scoring,
    or `providers/temperature.py`'s direct entity selection) is
    responsible for resolving which keys to read before calling this
    helper (ADR-012 §1a).
    """
    if isinstance(pairs, Mapping):
        return [(timestamp, float(value)) for timestamp, value in pairs.items()]
    return [(entry[datetime_key], float(entry[value_key])) for entry in pairs]
