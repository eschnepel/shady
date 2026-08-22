# Task: Cache Core — Time-Series Store & Contiguous-Range Accessor

- **Status:** done
- **Related ADRs:** [ADR-007, ADR-007a §1, ADR-007a §2, ADR-007a §3, ADR-007a §4, ADR-007a §5]
- **Dependencies:** []

## Goal
Build `cache.py`'s foundational time-series storage: the three-state
(`float|None|str`) index-addressable store, validated-range tracking,
push/invalidate, `trim()`, injected `fetch_fn` with validate-before-read,
and the `get_time_range` contiguous-range accessor. This is the shared
storage layer nearly every later task builds on — keep it free of any
`hass` import.

## Acceptance Criteria
- Given a cache constructed with a fake `fetch_fn` returning canned
  three-state data and no valid data yet for a sensor, When
  `get_time_range` is called for that sensor, Then the validation
  function fetches the sensor's entire configured `window_days` history
  in one call before returning results (ADR-007a §4).
- Given a sensor already valid except for a missing recent tail, When
  `get_time_range` is called, Then only the missing tail is fetched.
- Given a `push(sensor_id, {index: value, ...})` call whose lowest index
  is below a supplied `not_before_index`, When the push is applied, Then
  entries below that boundary are silently dropped and never written
  (ADR-007a §3's frozen-history guarantee).
- Given a `to_index=None` sensor (Shady-pushed, e.g. a stand-in for
  `ShadyForecastSensor`), When values are pushed, Then `validated`'s
  `to_index` extends without ever being re-queried.
- Given `get_time_range(sensor_ids, start, end, group_by="sensor")` vs.
  `group_by="slot"`, When called against the same data, Then the two
  return the documented complementary shapes (`{sensor_id: [v...]}` vs.
  `[{sensor_id: v}, ...]`) per ADR-007a §5.
- Given `cache.trim()` is called after the rolling window has advanced,
  When trimming occurs, Then `list_offset` advances and `validated`
  ranges stay meaningful (no off-by-one against the new offset).

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/cache.py` (storage core only — no
  `get_pinned_slot_pool`/`get_regression_pools` yet, see TASK-0006/TASK-0015)
- `tests/test_cache_core.py`

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- Zero-mocking test suite (ADR-000 §6): no `unittest.mock`, no fake
  `hass`, loaded via direct file-path import.

## Consumed Interfaces
<!-- None — this task has no dependencies. -->

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/cache.py`:
  - `SLOT_MINUTES: int = 5`, `SLOT_DURATION: timedelta`,
    `SLOTS_PER_DAY: int = 288` — module-level slot-resolution constants.
  - `EPOCH: datetime` — fixed epoch (`2020-01-01T00:00:00+00:00`) absolute
    indices are measured from. Arbitrary value, never observed outside
    this module — downstream code should always go through
    `index_for`/`timestamp_for`, never read `EPOCH` directly.
  - `FetchFn = Callable[[str, datetime, datetime], list[float | None | str]]`
    — the type alias for the injected fetch function.
  - **`fetch_fn` calling convention (binding for every caller):**
    `fetch_fn(sensor_id, start, end)` returns exactly one value per
    5-minute slot in the half-open interval `[start, end)` — `start`
    inclusive, `end` exclusive. `len(result) == (end-start)/5min`. This
    is the same convention `providers/base.py`'s `Provider.fetch` already
    follows (TASK-0001) — a `Provider.fetch` can be wired in as a cache's
    `fetch_fn` with no adapter.
  - `OnInvalid = Literal["skip", "raw"] | float` — type alias for the
    `on_invalid` parameter shared by every accessor.
  - `Cache` — the store. Constructor: `Cache(window_days: int, fetch_fn: FetchFn)`.
    - `Cache.index_for(timestamp: datetime) -> int` (staticmethod) —
      absolute slot index from the fixed epoch.
    - `Cache.timestamp_for(index: int) -> datetime` (staticmethod) —
      inverse of `index_for`.
    - `validated_range(self, sensor_id: str) -> tuple[int, int | None] | None`
      — introspection: the sensor's `(from_index, to_index)`, or `None`
      if never validated. `to_index=None` means "actively pushed by
      Shady, no fixed upper edge, never (re-)queried" (ADR-007a §2).
    - `push(self, sensor_id: str, values: dict[int, float], not_before_index: int) -> None`
      — writes values directly; entries with `index < not_before_index`
      are silently dropped. **Always leaves `validated[sensor_id][1]` as
      `None`** after any push (the sensor becomes/stays "actively
      pushed"). **Known scope boundary:** this does not yet implement
      ADR-012 §4's *hybrid* provider-predictor case, where a sensor's
      already-elapsed portion should stay query-bounded (a concrete,
      non-`None` `to_index`) while only its not-yet-elapsed portion is
      push-extended. TASK-0010 (coordinator) will need to build that
      on top of `push`/`invalidate`/direct `_validated` manipulation, or
      request a patch task against this file if the primitives here
      prove insufficient (Scenario C).
    - `invalidate(self, sensor_id: str, start: int, end: int) -> None` —
      resets `[start, end]` to `None`; shrinks `validated` accordingly
      (removes it entirely if the whole validated range is invalidated).
      A hole strictly inside the validated range is conservatively
      truncated at the hole's start rather than tracked as a real gap
      (the truncated tail is simply re-fetched on next access — correct,
      just not maximally efficient).
    - `trim(self, reference: datetime | None = None) -> None` — drops
      each sensor's entries older than `reference - window_days`,
      advancing `list_offset` and shrinking `validated` in place.
      `reference` defaults to `datetime.now(timezone.utc)`; tests (and
      any other deterministic caller) should pass it explicitly.
    - `get_time_range(self, sensor_ids: list[str], start: datetime, end: datetime, on_invalid: OnInvalid = 0.0, group_by: Literal["sensor", "slot"] = "sensor") -> dict[str, list[float | None | str]] | list[dict[str, float | None | str]]`
      — validates (fetches on-demand) before reading, for every
      `on_invalid` mode. `group_by="sensor"` → `{sensor_id: [v...]}`;
      `group_by="slot"` → `[{sensor_id: v}, ...]`. `on_invalid="raw"`
      keeps every entry as its true three-state value (no dropping);
      `on_invalid="skip"` drops non-float entries (variable-length
      result); a numeric default substitutes that number in place
      (fixed-length result, one entry per slot always present) —
      two `@overload` signatures give precise per-`group_by` static types.
  - **Not yet implemented (future tasks, by design):**
    `get_pinned_slot_pool` (ADR-007a §6, → TASK-0006 or TASK-0015 per
    INDEX.md's refinement note) and `get_regression_pools` (ADR-008 §2,
    → TASK-0006).
- `tests/test_cache_core.py` → 8 zero-mocking tests (6 test classes)
  covering all 6 acceptance criteria, plus one extra test
  (`test_missing_head_is_also_fetched_correctly`) exercising the
  symmetric head-gap path (and `invalidate`'s head-shrink branch) that
  wasn't separately called out in the acceptance criteria but follows
  directly from ADR-007a §3/§4.
- External dependencies added: none (pure stdlib — `datetime`,
  `collections.abc.Callable`, `typing`).
- Gates: `ruff format`, `ruff check`, `mypy --config-file mypy.ini`
  (project is configured strict), `pytest` all pass with zero
  errors/warnings. Full `tests/` suite (23 tests total, this task +
  TASK-0001) passes with no cross-file interference.
