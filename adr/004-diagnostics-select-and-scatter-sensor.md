# ADR-004 – Diagnostics: Selectable Diagnostic Modes and Scatter-Series Sensors (Per-String and Summed)

**Date:** 2026-07-05
**Status:** Accepted
**Amended:** 2026-08-30 — §1 revised: the single on/off `ShadyDiagnosticsSwitch`
is replaced by a `ShadyDiagnosticModeSelect` dropdown (`select.py`), and the
diagnostic calculation itself moves behind a new `DiagnosticMode` base class
(new pure package `diagnostics/`, mirroring `providers/base.py`'s `Provider`
ABC, ADR-012 §1) so a future mode is a new subclass, not a rewrite of this
ADR's gating mechanism. §2/§2a/§2b/§3/§4's behavior — the one scatter/accuracy
mode this ADR actually specifies — is unchanged; only its home (a concrete
`CompareRegressionsMode`) and how it's enabled (a select option, not a
boolean) move. §5 updated to match. See the Amendment block below for full
rationale, and ADR-013 (new, Proposed) for two further diagnostic modes
sketched to validate this base class's shape against needs beyond this ADR's
own scope.
**Amended again: 2026-09-01** — §5 revised: `DiagnosticMode` gains a
required `__init__(coordinator)` (the owning `ShadyCoordinator` instance)
plus two new abstract getters, `fit_cadence()`/`compute_cadence()`,
dropping the "imports neither `cache.py` nor `homeassistant.*`" purity
guarantee this section originally established. `TASK-0015a-patch-1` is
superseded. See the second Amendment block below.
**Amended a third time: 2026-09-02** — §5 revised again: `compute()`/
`extra_fit()` keep their zero-argument signatures, but `DiagnosticResult`/
`DiagnosticFitResult` are restructured to bundle every configured
string's output in one call (`by_string: Mapping[int, ...]`), since the
2026-09-01 amendment left `_diagnostic_modes` holding one shared instance
per mode name with no way for a single call to know which string it was
for. See the third Amendment block below.
**Amended a fourth time: 2026-09-02 (later same day)** — §5 revised a
third time in one day: the string-keyed `by_string` shape didn't
generalize to ADR-013's own sketched non-string-scoped modes.
`DiagnosticResult`/`DiagnosticFitResult` restructured again to a flat,
self-identifying `sensor_id`-keyed shape instead. See the fourth
Amendment block below.
**Amended a fifth time: 2026-09-03** — §2b/§3/§5 revised: caught during
human review of `TASK-0015b`'s still-in-progress (pre-review, not yet
`done`) implementation. `coordinator.py` now caches `compute()`'s
output, refreshed once per tick via `compute_cadence()` (previously
declared but never wired to anything) — `sensor.py` no longer calls
`.compute()` itself at all. `DiagnosticMode` gains a new required
`sensor_ids()` getter; `sensor.py`'s `ShadyDiagnosticsSumSensor` is
removed outright, replaced by one generic `ShadyDiagnosticsSensor` per
declared `sensor_id` — no more hardcoded "one per string plus one sum"
shape anywhere in `sensor.py`. `CompareRegressionsMode.compute()` now
builds the `"sum"` entry itself, from raw per-string data it already
gathered, rather than `sensor.py` reassembling it from sibling sensors'
finished output — which also fixes a real cross-string day-alignment
bug in the replaced approach. See the fifth Amendment block below.

---

## Amendment — 2026-08-30

**Reason:** §1's original design gated diagnostics behind a single boolean
switch with the one "compare regressions" behavior implemented inline
against it. Two problems, raised together: (1) a boolean has no room for a
second diagnostic mode without a breaking rework of the entity itself; (2)
the comparison logic in §2/§2a/§2b/§4 was never behind a reusable interface,
so a second mode would either duplicate it or entangle itself with it. This
project already has exactly this shape solved once, for external-series
sourcing (ADR-012's `Provider` ABC): a shared base class with required and
optional overridable methods, dispatched off a config value, so a new
concrete case is additive. No `TASK-0015a`/`TASK-0015b` code exists yet
(status `todo`), so
this is a pre-implementation redesign, not a patch to delivered code.

**Decision:**
- **Entity:** `switch.py`'s `ShadyDiagnosticsSwitch` is replaced by
  `select.py`'s `ShadyDiagnosticModeSelect` (HA `SelectEntity`), one per
  config entry. `switch.py` is removed from the project entirely — nothing
  else in this codebase uses the `switch` platform. Options are declared
  once in `const.py`: `DIAGNOSTIC_MODES: tuple[str, ...]` and
  `DEFAULT_DIAGNOSTIC_MODE = "off"` — the same shape `REGRESSION_METHODS`/
  `DEFAULT_REGRESSION_METHOD` already use for the (separate, config-flow-set)
  regression-method choice. Today's values: `"off"` (default) and
  `"compare_regressions"`. Display labels come from `translations/*.json`
  (ADR-000 §8), not hardcoded strings. Adding a future mode is one new
  option string + one translation entry + one new `DiagnosticMode` subclass
  (below) — no change to `select.py` itself.
- **New pure package `diagnostics/`** (mirrors `providers/`, ADR-012 §1):
  - `diagnostics/base.py` defines `DiagnosticMode`, an actual `ABC` (not a
    `Protocol` — same reasoning ADR-012 §1 gives: `coordinator.py` needs to
    call it generically without knowing which concrete mode it's talking
    to), plus the plain dataclasses its methods use:

    ```python
    @dataclass(frozen=True)
    class DiagnosticSlotSample:
        """One slot's already-resolved comparison inputs. `predicted` is
        keyed by whatever this mode compares — regression-method name for
        CompareRegressionsMode, provider name for a future provider-
        comparison mode (ADR-013). `actual` is None for a slot that hasn't
        elapsed yet (mirrors §2a's future-pin handling). `pool` is the
        optional historical scatter data (§2) — meaningful for a
        single-slot scatter-style mode, left None for a mode with no
        scatter concept of its own (e.g. a whole-day mode, ADR-013)."""
        slot_of_day: int
        predicted: Mapping[str, float]
        actual: float | None
        pool: Mapping[str, list[tuple[float, float]]] | None = None

    @dataclass(frozen=True)
    class DiagnosticContext:
        """One or more slots' already-fetched comparison inputs — never
        raw HA/recorder access, that's coordinator.py's job before this is
        built. A single-slot mode (CompareRegressionsMode, this ADR)
        receives exactly one sample; a whole-day mode (ADR-013, not yet
        scheduled) receives 288 — same shape, different cardinality, no
        base-class change needed either way."""
        samples: Sequence[DiagnosticSlotSample]

    @dataclass(frozen=True)
    class DiagnosticResult:
        """Pure, sensor-ready payload — sensor.py sets `state`/extends its
        attributes with `attributes` directly, no further shaping."""
        state: str
        attributes: dict[str, Any]

    @dataclass(frozen=True)
    class DiagnosticFitResult:
        """Whatever a mode's extra fitting produced, per compared source
        (method or provider name) — coordinator.py is the one that writes
        this into cache.py, same division of labor `push()` already has
        for provider forward() results (ADR-012 §4): the mode computes,
        the coordinator persists."""
        predictions: Mapping[str, float]

    class DiagnosticMode(ABC):
        key: ClassVar[str]

        @abstractmethod
        def compute(self, context: DiagnosticContext) -> DiagnosticResult:
            """Pure. No HA import — zero-mocking tier (ADR-000 §6)."""

        def extra_fit(self, context: DiagnosticContext) -> DiagnosticFitResult | None:
            """Optional, pure. Whatever extra per-slot fitting this mode
            needs beyond the default recalibration (ADR-002 §1) — e.g.
            fitting `regression/`'s other three strategies for the
            diagnosed slot, for `CompareRegressionsMode`. Run at the
            recalibration trigger while this mode is active; the returned
            `DiagnosticFitResult` (or `None`) is what `coordinator.py`
            caches, mirroring how it already handles a provider's
            `forward()` result (ADR-012 §4) — build/cache stays in
            `coordinator.py`, the mode only computes. Base default:
            `None` — "nothing extra needed," the same role `None` already
            plays for `Provider.forward()` (ADR-012 §1), generalizing
            this ADR's original §1 zero-cost-when-off guarantee to "zero
            cost for any mode that doesn't need extra fitting."
            """
            return None
    ```

    This mirrors ADR-012's *pattern* — an `ABC` with one required pure
    method and one optional, no-op-by-default hook, dispatched generically
    by `coordinator.py` — not its mechanics: a provider's `forward()` is a
    live push listener on an external entity; a mode's `extra_fit()` runs
    at the recalibration trigger instead. Different triggers, same shape.

    **Correction (2026-08-31, caught while implementing
    TASK-0015a-diagnostic-mode-base-architecture, before any code
    existed):** the sketch above originally typed `extra_fit`'s parameter
    as `DiagnosticFitContext`, a name this ADR never actually defines.
    `extra_fit` takes the same `DiagnosticContext` `compute()` receives —
    a mode's extra fitting operates on the same already-resolved
    diagnosed-slot inputs `compute()` renders (§4). Fixed in place above;
    a plain typo in this ADR's own illustrative code, not a design
    decision, so no separate dated "Amended" header line above was added
    for it — see `tasks/INDEX.md`'s refinement log for the corresponding
    entry.
  - `diagnostics/compare_regressions.py` — `CompareRegressionsMode
    (DiagnosticMode)`, `key = "compare_regressions"`. Everything §2/§2a/§2b
    of this ADR already specify moves here **verbatim, no behavior
    change**: `compute()` builds the `series`/`accuracy` payload from a
    one-sample `DiagnosticContext`; `extra_fit()` is §4's four-method fit
    for the one diagnosed slot.
  - **Accuracy stays in `aggregation.py`, not this package** (§5's original
    placement is correct and unchanged) — its definition (`1 -
    |predicted-actual|/actual`, clamped to `[0, 1]`) is independent of
    which mode or scope calls it, exactly the same function whether the
    caller is comparing regression methods at one slot (this ADR),
    regression methods across a whole day, or providers across a whole day
    (both ADR-013, sketched below). Moving it into `diagnostics/` would
    have coupled a genuinely mode-independent formula to one specific
    mode's module for no reason.
  - `coordinator.py` gets a private module-level registry, same shape as
    the existing `_REGRESSION_STRATEGIES: dict[str, module]` lookup:
    `_DIAGNOSTIC_MODES: dict[str, DiagnosticMode] = {"compare_regressions":
    CompareRegressionsMode()}`. `"off"` is a reserved key and is never
    registered — it is the *absence* of an active mode, not a
    `DiagnosticMode` subclass with a no-op body, the same way a provider
    with nothing to push simply never registers a listener (ADR-012 §4)
    rather than registering a no-op one.
- **`sensor.py` stays thin (ADR-000 §5):** `ShadyDiagnosticsSensor`/
  `ShadyDiagnosticsSumSensor` look up the select's current option in
  `_DIAGNOSTIC_MODES`; if found, build that mode's `DiagnosticContext` and
  call `.compute()`, then set `state`/`attributes` from the returned
  `DiagnosticResult` directly; if not found (`"off"` or unset), report
  `disabled` exactly as §1 always specified. No mode-specific branching
  left inline in `sensor.py`.
- **Everything else in this ADR is unchanged** — the pinned-slot
  auto-tracking/pin-override semantics (§2a), the shared config-entry-wide
  diagnosed-slot state, the summed sensor (§2b), the historical-pool
  caching cadence (§3), and the four-method fitting cost (§4, now
  `CompareRegressionsMode.extra_fit()`) all describe the exact same
  behavior as before — only the entity type and the module boundary around
  that behavior change.

**Decided by:** human (explicit instruction), confirmed by Lead Agent.

---

## Amendment — 2026-09-01

**Reason:** While reviewing this ADR and `TASK-0015a-patch-1` (not yet
implemented), the human judged the per-call, coordinator-builds-and-hands-
over shape `TASK-0015a-patch-1` was adding
(`DiagnosticSlotSample.query_fc`/`.fit_inputs`, the new `DiagnosticFitInputs`
dataclass) to be the wrong trade going forward: it requires the Lead
Agent/coordinator to anticipate and thread every future mode's exact data
needs through `DiagnosticContext` ahead of time, one dataclass field at a
time — precisely the kind of interface-extension friction
`TASK-0015a-patch-1` was itself already an instance of, discovered before
it had even shipped. The alternative decided on: give every
`DiagnosticMode` a reference to the coordinator that owns it, so a mode
can pull whatever coordinator-owned data it needs (string config,
registered FC providers, the cache, or anything added to
`ShadyCoordinator`'s public interface later) directly, on demand, without
the coordinator having to anticipate or know what any given mode does
with it — trading `DiagnosticMode`'s purity (this section's original
"imports neither `cache.py` nor `homeassistant.*`") for that flexibility.
Decided explicitly, with the human confirming this supersedes
`TASK-0015a-patch-1` outright rather than the two mechanisms coexisting.

**Decision:**

- **`DiagnosticMode.__init__(self, coordinator: ShadyCoordinator) -> None`**
  — new, required. Every concrete mode's constructor takes the owning
  `ShadyCoordinator` instance and is expected to hold onto it (e.g.
  `self._coordinator`) for `compute()`/`extra_fit()`/the two new cadence
  getters below to use as needed. The instance passed is the real
  `coordinator.py` object — no facade, protocol, or adapter type is
  introduced to soften this; `diagnostics/` now depends on `coordinator.py`
  exactly the way `coordinator.py` already depends on `diagnostics/` (§5's
  registry) — a two-way relationship. The import-level cycle this implies
  is resolved the same way this project's own test files already resolve
  a comparable problem (ADR-000 §6): `from __future__ import annotations`
  plus a `TYPE_CHECKING`-only import of `ShadyCoordinator` in
  `diagnostics/base.py`, so no runtime `import` statement in
  `diagnostics/base.py`/`compare_regressions.py` actually names
  `coordinator.py` or `homeassistant.*`. This is a resolution of the
  *import cycle* only, not a restoration of purity — every
  `DiagnosticMode` instance still holds, and calls into, a real
  `ShadyCoordinator` object at runtime, one that does import
  `homeassistant.*` and does reach `cache.py`. See the Consequences update
  below for what this actually costs.
- **Cache: no separate constructor parameter.** `coordinator.py`'s
  `self.cache` is already a plain public attribute (verified against the
  current codebase — not a private `_cache` behind a getter method), so a
  `DiagnosticMode` reaches it via `self._coordinator.cache` directly. This
  resolves the "either the coordinator already has a getter, or passes
  cache separately" question this decision was raised with: it already
  has one, in the form of a public attribute, so no second constructor
  parameter is introduced.
- **Encapsulation boundary, despite dropping purity:** a `DiagnosticMode`
  may only use `coordinator.py`'s **public** interface (no leading
  underscore) — `strings()`, `cache`, and whatever else is or becomes
  public. Reaching into `coordinator.py`-private (`_`-prefixed)
  attributes or methods from `diagnostics/` is not allowed — the same
  boundary ADR-000 §5 already enforces between every other pair of
  modules in this codebase, and the same reasoning the 2026-08-24
  refinement (`TASK-0010-patch-2-string-enumeration`, `tasks/INDEX.md`)
  already used to justify adding a public `strings()` accessor rather than
  letting `sensor.py` reach into `_StringConfig`. Where a mode needs
  coordinator-owned data that has no public accessor yet — today: full
  per-string config beyond `strings()`'s `(index, name)` pairs (the rest
  of `_StringConfig`'s fields), or which FC-provider entities/keys are
  registered (currently only `self._entity_providers`, private) — the
  coordinator must be extended with a public accessor as an explicit,
  reviewed part of whichever task needs it, not a silent reach into a
  `_`-prefixed name. This keeps *some* boundary discipline even though the
  zero-mocking guarantee itself is gone; it is a convention this ADR
  states, not one the type system enforces (see Consequences).
- **`coordinator.py`'s `_DIAGNOSTIC_MODES` registry moves from a private
  module-level constant to a per-instance attribute.** §5 originally
  specified `_DIAGNOSTIC_MODES: dict[str, DiagnosticMode] =
  {"compare_regressions": CompareRegressionsMode()}` at module scope,
  since a no-arg `DiagnosticMode` could be constructed once, at import
  time, and shared. That no longer holds once construction needs `self`:
  the registry becomes an **instance** attribute, built once in
  `ShadyCoordinator.__init__` (e.g.
  `self._diagnostic_modes: dict[str, DiagnosticMode] =
  {"compare_regressions": CompareRegressionsMode(self)}`) — functionally
  the same lookup, the same reserved-and-never-registered `"off"` key, the
  same dispatch; only *where* it is built changes.
- **Two new abstract getters:** `fit_cadence(self) -> Literal["daily",
  "hourly", "slot"]` and `compute_cadence(self) -> Literal["daily",
  "hourly", "slot"]` (exact `Literal`/enum type left to
  `TASK-0015a-patch-2`, the implementing task). Both required, no default
  — every concrete mode must state both explicitly, the same "no default"
  requiredness `compute()` itself already has, since how often a mode
  needs to fit/compute is core to what the mode *is*, not an optional
  refinement. Purpose: lets `coordinator.py` (or whichever
  trigger-registration code dispatches to `extra_fit()`/`compute()`) read
  a mode's own declared cadence generically, the same way it already reads
  `key: ClassVar[str]` generically, instead of needing a hard-coded case
  per mode's schedule. `CompareRegressionsMode` (`TASK-0015b`) declares
  both `"slot"` — it fits/computes for exactly one diagnosed 5-minute
  slot, reusing `TASK-0013`'s existing 5-minute trigger (§4, unchanged
  behavior). This also gives ADR-013's two sketched whole-day modes (not
  scheduled) a real, structural answer to the open cost question their own
  §3 raises ("whether this needs ... a lower refresh cadence") — both
  would plausibly declare `fit_cadence() -> "daily"` — without committing
  to scheduling either now; see ADR-013's own pointer note.
- **`compute()` and `extra_fit()` drop their parameter — `DiagnosticContext`
  and `DiagnosticSlotSample` are removed from `diagnostics/base.py`
  entirely, not kept alongside the new constructor.** Correction to the
  bullets above, caught on review before any of this had been implemented:
  once a mode holds its own coordinator reference, there is nothing left
  for a per-call context argument to carry that the mode cannot already
  reach itself — which slot is diagnosed (`cache.py`'s
  `pinned_reference`, reached via `self._coordinator.cache`), that slot's
  pool/predicted/actual values, string config, anything else. Threading
  the same information through both a constructor-time reference *and* a
  per-call DTO is redundant, and reintroduces exactly the "coordinator
  must anticipate every mode's inputs" friction this whole amendment
  exists to remove. The new signatures:
  - **`compute(self) -> DiagnosticResult`** (abstract, required, no
    parameters beyond `self`).
  - **`extra_fit(self) -> DiagnosticFitResult | None`** (optional, still
    defaults to returning `None` — the base-class default's meaning is
    unchanged, only its signature loses the parameter).

  `DiagnosticResult` and `DiagnosticFitResult` are **not** removed — they
  are output shapes (`compute()`'s sensor-ready payload,
  `extra_fit()`'s cached predictions), not per-call input, and nothing
  about receiving a coordinator reference changes what a mode needs to
  return. `TASK-0015a-patch-2` deletes `DiagnosticSlotSample` and
  `DiagnosticContext` from `diagnostics/base.py` outright (not deprecate-
  and-keep) — obsolete classes are dropped, per explicit review
  instruction, not left as unused dead code for a future mode to
  rediscover.
- **What does not change:** the single-active-mode-or-`"off"` dispatch
  model (§1), `key: ClassVar[str]`, and the `DiagnosticResult`/
  `DiagnosticFitResult` dataclasses exactly as `TASK-0015a` delivered
  them (both remain outputs only — see above). Everything else about
  `DiagnosticMode`'s public shape moves: the constructor, both new
  cadence getters, and `compute()`/`extra_fit()` losing their parameter
  together with `DiagnosticSlotSample`/`DiagnosticContext`'s removal.
- **`TASK-0015a-patch-1-diagnostic-fit-inputs` is superseded, not kept
  alongside this.** Its `DiagnosticSlotSample.query_fc`/`.fit_inputs`
  fields and the `DiagnosticFitInputs` dataclass existed to carry
  `string_computation.fit_string_model`/`predict_string_forecast`'s raw
  inputs through `DiagnosticContext` *because* `DiagnosticMode` could not
  otherwise reach them — moot twice over now, since both the mechanism
  (`DiagnosticContext`) and the class it would have extended
  (`DiagnosticSlotSample`) are removed by this same amendment. Now that a
  mode holds a coordinator reference, it gathers those same raw inputs
  itself, inside its own no-argument `compute()`/`extra_fit()`
  (`self._coordinator.cache.get_pinned_slot_pool(...)`, the resolved
  temperature target via the coordinator's own provider access, string
  config via `strings()`/whatever public accessor is added) and calls
  `string_computation.fit_string_model`/`predict_string_forecast` directly
  — the same functions, same module (ADR-014, unchanged), just invoked
  from inside `CompareRegressionsMode` instead of assembled by
  `coordinator.py` into a DTO first. `TASK-0015a-patch-1` is marked
  superseded in its own file and in `tasks/INDEX.md`; its slug is not
  reused, per this project's standing convention for retired tasks
  (`tasks/INDEX.md`'s 2026-08-30 refinement-log entry).

**Decided by:** human (explicit instruction, 2026-09-01), confirmed by
Lead Agent.

---

## Amendment — 2026-09-02

**Reason:** Scoping `TASK-0015b`'s Consumed Interfaces against the
2026-09-01 amendment's zero-argument `compute()`/`extra_fit()` surfaced a
gap neither amendment had actually resolved: `coordinator.py`'s
`_diagnostic_modes` holds **one shared `CompareRegressionsMode` instance
per mode name** (mirroring `string_computation.py`'s `REGRESSION_STRATEGIES`
lookup in shape, per the 2026-09-01 amendment's own wording) — but §2
requires **one `ShadyDiagnosticsSensor` per configured string**, each
needing its own series/accuracy, and neither `compute()` nor `extra_fit()`
takes any parameter (or has any per-string state) a shared instance could
use to know which string a given call is for. This was caught before any
`TASK-0015b` code existed, while assembling that task's Consumed
Interfaces — the same "before code, not after" timing every prior
amendment to this ADR has had. Three resolutions were identified and
presented to the human: (1) one `DiagnosticMode` instance per (mode,
string) pair instead of per mode name alone; (2) a single shared instance
whose zero-argument `compute()`/`extra_fit()` internally loop over
`self._coordinator.strings()` and return a result bundling every
configured string's output in one call; (3) reintroducing a single
`string_index: int` parameter to `compute()`/`extra_fit()`, reopening the
2026-09-01 amendment's just-implemented, just-merged signature a third
time in three days. The human chose (2).

**Decision:**

- **`compute()`/`extra_fit()` keep their zero-argument signatures from the
  2026-09-01 amendment unchanged** — `compute(self) -> DiagnosticResult`,
  `extra_fit(self) -> DiagnosticFitResult | None`. What changes is what
  `DiagnosticResult`/`DiagnosticFitResult` themselves hold: each call now
  covers **every configured string in one shot**, resolved via
  `self._coordinator.strings()` the same way any other coordinator-owned
  data is reached (2026-09-01 amendment, unchanged encapsulation
  boundary).
- **`DiagnosticResult` restructured to bundle by string:**
  ```python
  @dataclass(frozen=True)
  class DiagnosticStringResult:
      """One string's sensor-ready payload — exactly `DiagnosticResult`'s
      pre-2026-09-02 shape, now nested one level under `DiagnosticResult.
      by_string` instead of being the top-level return value itself."""
      state: str
      attributes: dict[str, Any]

  @dataclass(frozen=True)
  class DiagnosticResult:
      """Every configured string's already-shaped payload from one
      compute() call, keyed by string index (coordinator.py's strings()
      index half)."""
      by_string: Mapping[int, DiagnosticStringResult]
  ```
  `sensor.py`'s per-string `ShadyDiagnosticsSensor` calls `compute()` and
  indexes into `by_string[self._string_index]` for its own
  `state`/`attributes` — still "straight from the returned result", just
  one dict lookup deeper than the 2026-09-01 amendment's text described,
  since that text predates this gap being caught.
- **`DiagnosticFitResult` restructured the same way:**
  ```python
  @dataclass(frozen=True)
  class DiagnosticFitResult:
      """Every configured string's extra-fitting output from one
      extra_fit() call, keyed by string index — same bundling rationale
      as DiagnosticResult, same reason (one shared mode instance, one
      zero-argument call covering every string)."""
      by_string: Mapping[int, Mapping[str, float]]
  ```
  The inner `Mapping[str, float]` is unchanged from the 2026-09-01
  amendment's `DiagnosticFitResult.predictions` — still keyed by
  compared-source name (method or provider name) — only relocated one
  level deeper, under each string's own key. `coordinator.py` iterates
  `by_string` and writes each string's inner mapping into `cache.py`
  individually, the same division of labor (mode computes, coordinator
  persists) the 2026-09-01 amendment already established for the
  single-string case.
- **`ShadyDiagnosticsSumSensor` is unaffected by this amendment** — per
  §5's existing text, it was never going to call `compute()` a second
  time; it reads the per-string sensors' own already-computed
  `state`/`attributes` and sums them itself (`aggregation.py`'s second,
  sum-then-accuracy pure function, unchanged). This amendment only
  changes how the per-string sensors' own calls are shaped.
- **Cost trade-off, stated plainly:** every per-string `ShadyDiagnosticsSensor`
  now triggers a full recomputation of *every* configured string's
  series/accuracy on each read (N sensors x N-strings-worth of work per
  5-minute tick, instead of N sensors x 1-string-worth), not just its
  own. `compute()`'s own per-string cost is already documented as cheap
  (§2a "Refresh cadence": one PV/FC lookup plus four model evaluations
  per string), so this is judged an acceptable, explicitly-accepted
  trade for keeping `compute()`/`extra_fit()` argument-free and avoiding
  a fourth signature change to the same method pair — not a
  correctness concern, a constant-factor one, bounded by how many
  strings a real installation configures (typically single digits).
- **What does not change:** the single-active-mode-or-`"off"` dispatch
  model (§1), `key: ClassVar[str]`, the two cadence getters
  (`fit_cadence()`/`compute_cadence()`), the constructor
  (`__init__(self, coordinator: ShadyCoordinator)`), and the
  encapsulation boundary (public-interface-only) — all exactly as the
  2026-09-01 amendment left them. Only the two output dataclasses'
  internal shape changes, per above.
- **No further patch task for `TASK-0015a-patch-1`** — it remains
  superseded from the 2026-09-01 amendment; this amendment does not
  reopen that question.

**Decided by:** human (explicit instruction, 2026-09-02), confirmed by
Lead Agent.

---

## Amendment — 2026-09-02 (second, same day)

**Reason:** Reviewing the just-decided string-keyed `by_string` shape
against **ADR-013**'s own sketched future modes — written specifically
to validate this base class against needs beyond
`CompareRegressionsMode` — surfaced that it doesn't generalize.
`compare_providers_daily` (ADR-013 §1) compares candidate **providers**
across a whole day, a dimension with no relationship to string index at
all; `compare_regressions_daily` (ADR-013 §1) compares methods across a
whole day as a **single array-wide series**, not one entry per string
either. Keying `DiagnosticResult`/`DiagnosticFitResult` by string index,
as the first same-day amendment just did, would have silently broken
ADR-013's own central claim — "both fit inside ADR-004's `DiagnosticMode`
base class as written, with no change to `diagnostics/base.py`" — the
moment either sketched mode was actually built. Caught by the human
before any `TASK-0015b` code existed (the same "before code" timing
every amendment to this ADR has had), immediately following the first
same-day amendment.

**Decision:**

- **`compute()`/`extra_fit()` keep their zero-argument signatures**,
  unchanged again. What changes, a second time today, is what
  `DiagnosticResult`/`DiagnosticFitResult` hold — generalized from
  "keyed by string index" to "a flat, self-identifying collection,
  however many entries a given mode's one call produces and whatever
  those entries represent (one per string, one per provider, one for an
  entire array, ...)."
- **`DiagnosticStringResult` renamed `DiagnosticSensorResult`, gains a
  required `sensor_id` and three optional entity hints:**
  ```python
  @dataclass(frozen=True)
  class DiagnosticSensorResult:
      sensor_id: str
      state: str
      attributes: dict[str, Any]
      name: str | None = None
      unit: str | None = None
      device_class: str | None = None
  ```
  `state`/`attributes` are exactly `DiagnosticResult`'s original
  pre-2026-09-02 fields, unchanged again. `sensor_id` is however the
  producing mode chooses to identify this one entity — a string index as
  text for `CompareRegressionsMode`, a provider name for a future
  `compare_providers_daily`, a fixed sentinel for a mode that only ever
  produces one whole-array entity. `name`/`unit`/`device_class` are
  optional, plain-`str` hints (not `homeassistant.*` enums — this module
  stays free of that runtime import, same as before both amendments
  today) `sensor.py` may use when shaping the real entity beyond its own
  per-mode defaults; a mode with nothing to override leaves them `None`.
- **`DiagnosticResult` restructured to a flat list:**
  ```python
  @dataclass(frozen=True)
  class DiagnosticResult:
      sensors: Sequence[DiagnosticSensorResult]
  ```
  `sensor.py`'s per-string `ShadyDiagnosticsSensor` calls `compute()`
  once and finds its own entry by matching `sensor_id` — one dict/list
  lookup deeper than the first same-day amendment's text described,
  since that text (written minutes earlier the same session) predates
  this second gap being caught.
- **`DiagnosticFitResult` restructured the same way, keyed by
  `sensor_id` instead of string index:**
  ```python
  @dataclass(frozen=True)
  class DiagnosticFitResult:
      by_sensor: Mapping[str, Mapping[str, float]]
  ```
  Not explicitly requested by the human alongside `DiagnosticResult`'s
  change, but applied here for symmetry with the same stated principle
  (not every mode is string-scoped) — flagged plainly in this amendment
  so it can be corrected if that symmetry wasn't intended. The inner
  `Mapping[str, float]` is unchanged — still keyed by compared-source
  name. `coordinator.py` iterates `by_sensor` and writes each entry's
  inner mapping into `cache.py` individually, same division of labor as
  before.
- **`ShadyDiagnosticsSumSensor` remains unaffected** — it was never
  calling `compute()` a second time (§5's original text, unchanged by
  either amendment today); it reads the per-string sensors' own
  already-computed output and sums that.
- **ADR-013 §1's "no change to `diagnostics/base.py`" claim is revised**
  by a matching note in that document — the base class changed twice
  today, but neither sketched mode there needs any further change of its
  own beyond what today's two amendments already made: both already
  described their output as "whatever shape `compute()` decides to
  build," which is exactly what a flat, self-identifying list gives them
  cleanly, more so than the string-keyed shape this amendment replaces.
- **What does not change (a second time today):** the
  single-active-mode-or-`"off"` dispatch model (§1), `key: ClassVar[str]`,
  the two cadence getters, the constructor, and the encapsulation
  boundary — all exactly as both prior amendments left them.

**Decided by:** human (explicit instruction, 2026-09-02, second
instruction same day), confirmed by Lead Agent.

---

## Amendment — 2026-09-03

**Reason:** Caught during human review of `TASK-0015b`'s own
still-in-progress implementation — code already existed (per the
fourth Amendment's shape) but the task was not yet at review/`done`, so
this is an in-flight correction to that same task, not a Scenario C
patch against completed work. Two separate observations, addressed
together since both concern how `sensor.py` and `CompareRegressionsMode`
divide responsibility for the `"sum"` entry:

1. Every per-string `ShadyDiagnosticsSensor` called `mode.compute()`
   directly, on every poll — since one call already computes every
   configured string's data (fourth Amendment), an entry with N
   strings did the same O(N) work N times over per poll cycle, for data
   that does not change between ticks. `compute_cadence()` (second
   Amendment) already existed for exactly this — declared by every
   mode, read by nothing.
2. `ShadyDiagnosticsSumSensor` built the `"sum"` `series` itself, in
   `sensor.py`, from the per-string sensors' own already-computed,
   already gap-filtered display series, via `zip()` — a mismatch this
   code's own comments already flagged: two strings with different gap
   patterns in their historical data can end up compared day-for-day
   incorrectly, since `zip()` aligns by *position in the filtered
   list*, not by calendar day. Separately, and regardless of the
   alignment bug: this shape hardcodes "compute() always produces
   exactly one aggregate, and `sensor.py` is the one who builds it" —
   which fixed `sensor.py` to know a specific mode's output shape,
   contradicting the fourth Amendment's own "the container doesn't
   assume what dimension a mode varies over" principle, just moved from
   `DiagnosticResult` itself onto `sensor.py`'s entity-creation code
   instead.

**Decision:**

- **`coordinator.py` gains `diagnostic_result()`**, a cached accessor
  for the active mode's `compute()` output:
  ```python
  def diagnostic_result(self) -> DiagnosticResult | None:
      mode = self.diagnostic_mode()
      if mode is None:
          return None
      if self._diagnostic_result_cache is None:
          self._diagnostic_result_cache = mode.compute()
      return self._diagnostic_result_cache
  ```
  `_diagnostics_tick_sync` (§4) now reads `compute_cadence()` the same
  way it already reads `fit_cadence()` for `extra_fit()` — independently
  gated, since a future mode could need one cadence but not the other,
  even though `CompareRegressionsMode` declares `"slot"` for both.
  `extra_fit()` is attempted first within that same tick, so on a tick
  where both cadences are `"slot"`, `compute()` reads back predictions
  `extra_fit()` just cached rather than the previous tick's; a mode
  with a coarser `fit_cadence()` than `compute_cadence()` gets no such
  freshness guarantee from this ordering, which is correct for that
  mode, not a bug — `compute()` was never promised anything fresher
  than `fit_cadence()` itself provides. The cache is invalidated
  (`= None`) on `set_active_diagnostic_mode` (a different mode's
  `compute()` output is not this mode's), `pin_diagnostic_slot`, and
  `clear_diagnostic_slot` (both change what the diagnosed slot itself
  is, per §2a) — a read between ticks with no cached value yet (mode
  just switched on, or right after a pin/clear) computes once, lazily,
  and caches that result for whatever reads follow before the next
  tick refreshes it.
- **`DiagnosticMode` gains a new required abstract method,
  `sensor_ids()`:**
  ```python
  @abstractmethod
  def sensor_ids(self) -> Sequence[tuple[str, str]]:
      """Every (sensor_id, name) pair this mode's compute() will
      ever produce, resolvable without calling compute() itself."""
  ```
  Cheap and static — no recorder fetch, no fitting — so it can run at
  HA platform-setup time, before any mode is necessarily even active.
  `CompareRegressionsMode.sensor_ids()` returns one `(str(index),
  f"{name} Diagnostics")` pair per configured string plus
  `("sum", "Diagnostics Sum")` — the same two `compute()` already ever
  produced, just declared up front now.
- **`coordinator.py` gains `diagnostic_sensor_ids()`**, the union of
  every *registered* mode's `sensor_ids()` (not just the active one),
  de-duplicated by `sensor_id`:
  ```python
  def diagnostic_sensor_ids(self) -> list[tuple[str, str]]:
      by_id: dict[str, str] = {}
      for mode in self._diagnostic_modes.values():
          for sensor_id, name in mode.sensor_ids():
              by_id.setdefault(sensor_id, name)
      return list(by_id.items())
  ```
  Union across every registered mode, not just the active selection,
  so entities stay stable across a `select.py` mode switch rather than
  needing to be added/removed dynamically — a `sensor_id` belonging to
  a currently-inactive mode simply reads `"unavailable"`
  (`ShadyDiagnosticsSensor._result()` finds no match in
  `diagnostic_result()`'s current output) until that mode is selected.
  Only one mode is registered as of this ADR (`compare_regressions`),
  so this is currently equivalent to that mode's own `sensor_ids()`;
  the generalization is free once a second mode exists.
- **`sensor.py`'s `ShadyDiagnosticsSumSensor` is removed outright.**
  `ShadyDiagnosticsSensor` becomes the one, generic diagnostic-sensor
  class — constructed with `(coordinator, entry, sensor_id, name)`
  directly, no longer `string_index`/`string_name` specifically — and
  `async_setup_entry` creates one instance per pair from
  `coordinator.diagnostic_sensor_ids()`:
  ```python
  entities.extend(
      ShadyDiagnosticsSensor(coordinator, entry, sensor_id, name)
      for sensor_id, name in coordinator.diagnostic_sensor_ids()
  )
  ```
  `sensor.py` has no notion of "per-string" vs "sum" vs anything else
  at all now — a mode producing several distinct aggregate entities
  (more than one kind of "sum") is handled exactly the same way as one
  that doesn't: it simply declares more `sensor_id`s. `_result()` is
  unchanged in shape — a `sensor_id` lookup into
  `coordinator.diagnostic_result()` — but every entity, "sum" included,
  now shares that one cached call rather than triggering its own.
- **`CompareRegressionsMode.compute()` builds the `"sum"` entry
  itself**, from each contributing string's raw pool data gathered in
  the same pass that builds its own per-string entry (a new
  `_StringDiagnostic` container holds both, so the pool is fetched
  once, not twice), summed via a new `_sum_arrays_nan_aware` helper —
  elementwise across strings, at the raw, fixed-length, day-index-
  aligned array stage, *before* `_pool_series`'s per-string NaN-
  filtering:
  ```python
  def _sum_arrays_nan_aware(self, arrays: list[NDArray[np.float64]]) -> NDArray[np.float64]:
      stacked = np.stack(arrays, axis=0)
      all_missing = np.all(np.isnan(stacked), axis=0)
      summed = np.nansum(stacked, axis=0)
      return np.where(all_missing, np.nan, summed)
  ```
  This is not just a relocation — it fixes the alignment bug from the
  Reason above: summing before per-string filtering keeps every day
  correctly aligned by calendar day across strings, rather than by
  position in each string's already-filtered list. Verified end-to-end
  against a real `ShadyCoordinator`: two strings sharing a 3-day window,
  one with full history, one missing the middle day — the corrected sum
  correctly keeps that day (counting only the string that has data,
  `[Σ FC, Σ PV] = [1000, 500]`) rather than dropping it or pairing it
  with the wrong calendar day. `fc_selected`/`pv_selected`/predictions
  for the sum are summed via the same pre-existing `aggregation.py`
  functions (`sum_values`, `sum_predicted`) the replaced `sensor.py`
  code already used — relocated, not changed — with one confirmed,
  deliberately-kept asymmetry: `predictions` only sums strings with a
  cached prediction, while `fc_selected`/`pv_selected` sum every
  contributing string regardless, so a string with real yield but no
  fitted model yet still counts toward the actual total without a
  corresponding predicted contribution. This is inherited unchanged
  from the design being replaced (not a new decision introduced here),
  and is being kept deliberately: it reflects currently-unmodeled
  production honestly rather than silently excluding it, and the
  accuracy figure itself is still correctly a sum-then-ratio
  computation, not an average of per-string ratios — `diagnostic_accuracy`
  and `sum_predicted`'s existing docstrings already document that
  principle and are unchanged by this amendment.
  FC and PV pool arrays are summed independently of each other (a
  string missing PV on a given day still contributes its FC to that
  day's summed forecast) — deliberate, matching how `sum_values`
  already treats "no value" as excluded-from-that-quantity rather than
  requiring joint presence across quantities.
- **§2b's/§5's prior text describing `ShadyDiagnosticsSumSensor` as
  reading "each per-string sensor's already-computed series... and
  summing them pointwise," doing "no new fitting or fetching of its
  own," is superseded** — that sentence, and the near-identical claim
  restated in both 2026-09-02 amendments above, described the design
  this amendment replaces, not the current one.
- **What does not change:** §1's off-by-default gating and `"disabled"`
  state, §2/§2a's per-string scatter/accuracy shape and one-shared-
  diagnosed-slot model, §4's fitting-cost-only-while-active guarantee,
  and `DiagnosticMode`'s constructor/`key`/cadence getters.

**Decided by:** human (explicit instruction, 2026-09-03, three separate
rounds of review during `TASK-0015b`'s implementation), confirmed by
Lead Agent.

---

## Context

Throughout this project's design process, understanding *why* a given
regression method produces the forecast it does required building
ad-hoc scatter plots of `(FC, PV)` training points with each method's
fitted curve overlaid, evaluated at today's query point. That exercise —
manually repeated several times during design — is exactly the kind of
visual validation a real user would want on their own real data, not just
during design. This ADR turns that ad-hoc process into a first-class,
opt-in diagnostic feature.

---

## Decision

### 1 — A dedicated diagnostic-mode select, default off (revised 2026-08-30)

A single `ShadyDiagnosticModeSelect` entity (one per config entry) gates
all diagnostic sensors — every per-string `ShadyDiagnosticsSensor` (§2)
and the config-entry-level `"sum"` entity (§2b, the same
`ShadyDiagnosticsSensor` class as of the 2026-09-03 Amendment) alike. It
defaults to **off**. While off, diagnostic sensors exist (so they don't
appear/disappear from the entity registry, which HA handles awkwardly)
but report `state: "disabled"` with no `series` attribute, and —
importantly — the coordinator does **not** do the extra fitting work
described in §4 while no mode is active. This keeps the cost of
diagnostics at zero for the common case of a user who never enables one,
following the same "no-op when not configured" pattern already
established for the corrections in ADR-003a §2 / ADR-003b §2.

Selecting `"compare_regressions"` — the one mode this ADR specifies —
activates exactly the behavior §2/§2a/§2b/§3/§4 describe below, now
implemented as `diagnostics/compare_regressions.py`'s `CompareRegressionsMode`
(see the Amendment block above for the base-class shape and why it moved
here). Everything below describes that one mode's behavior; "the switch"
in the historical prose that follows means "this select set to
`compare_regressions`," and "the switch is off" means "set to `off`" — the
underlying behavior is identical to what shipped in this ADR's original
version, only the entity/dispatch mechanism around it changed.

### 2 — One scatter-series sensor per configured PV string

Each configured string gets one `ShadyDiagnosticsSensor`, exposing a
`series` attribute pre-shaped for direct use as an ApexCharts scatter
chart `series` option — no client-side reshaping needed — and an
`accuracy` attribute carrying the same numbers in a form other automations
or templates can use directly, without parsing a series name string. The
state itself is a simple timestamp (last computed); all the content is in
the attributes:

```js
series: [
  {
    name: '0',
    data: [
      [16.4, 5.4],
      [21.7, 2],
      [25.4, 3],
      // ...one point per day in the rolling window (ADR-001 §4);
      // shown here with 3 instead of window_days points for brevity
    ],
  },
  {
    name: '-1',
    data: [ /* same shape, this slot's -1 neighbor (ADR-011 §1) */ ],
  },
  {
    name: '1',
    data: [ /* same shape, this slot's +1 neighbor */ ],
  },
  {
    name: 'selected linear (94%)',
    data: [[21.7, 3.1]],
  },
  {
    name: 'selected wls2 (96%)',
    data: [[21.7, 3.2]],
  },
  {
    name: 'selected wls3 (89%)',
    data: [[21.7, 3.3]],
  },
  {
    name: 'selected kernel (91%)',
    data: [[21.7, 3.4]],
  },
  {
    name: 'selected actual',
    data: [[21.7, 3.15]],
  },
],
accuracy: {
  linear: 0.94,
  wls2: 0.96,
  wls3: 0.89,
  kernel: 0.91,
},
```

Two kinds of series, both keyed by `name` so ApexCharts renders each as
its own scatter series/color:

- **Slot-pool series**, named by signed slot offset relative to the
  diagnosed slot (`"-1"`, `"0"`, `"1"`, … up to ±`smoothing_radius` from
  ADR-011 §1) — each point is one historical day's `[FC_i, PV_i]` pair
  for that slot, i.e. exactly the training data ADR-001 §2's regression
  actually sees for the diagnosed slot's pool. This is the same data a
  person would otherwise have to pull from the recorder by hand to
  reproduce the plots built during this project's own design process.
- **Selected-prediction series**, one per regression method, named
  `"selected {method} ({accuracy}%)"` (`linear`, `kernel`, `wls2`,
  `wls3`) — each a single-point series at `[FC_selected, predicted_i]`
  for that method. `FC_selected` is that slot's own recorded value — the
  training-time `FC` role from ADR-001 §2 — whenever the diagnosed slot
  has already elapsed, true for auto-tracking by construction (see
  below) and for most manually-pinned slots too. For a manually-pinned
  slot that is still in the future (§2a), there is no recorded value yet,
  so `FC_selected` is instead the same forward-looking, not-yet-elapsed
  `FC` a live prediction for that slot would already query (ADR-002
  §2/§3) — the four methods are simply evaluated against whichever `FC`
  value actually exists for the slot. All four are always included
  regardless of which method is the configured default (ADR-001 §2) —
  the point of this sensor is comparing methods on the user's own data,
  so showing only the active one would defeat it. **Accuracy** is `1 -
  |predicted_i - PV_selected| / PV_selected`, clamped to `[0, 1]` before
  formatting as a percentage (a predicted value more than 100% off is
  displayed as `0%`, not a negative number that would need explaining)
  — recomputed whenever the diagnosed slot changes (§2a), since it
  depends on `PV_selected`, which only exists once that slot is
  complete. For a future-pinned slot, `PV_selected` does not exist yet,
  so accuracy cannot be computed at all: the series names drop the
  `(...%)` suffix entirely (`"selected wls2"`, not `"selected wls2
  (96%)"`), and the `accuracy` attribute is an empty `{}` rather than
  carrying partial or placeholder numbers — see §2a. Otherwise, the
  `accuracy` attribute carries the same four numbers as plain `0.0`–`1.0`
  floats, keyed by method name, so the series-name string is a display
  convenience, not the only place this value lives. (Named `"selected"`,
  not `"today"` — see §2a: a manually chosen slot need not be from
  today, in either direction.)

  **Not to be confused with `confidence` (ADR-001 §2/§2a):** confidence
  is forward-looking and always available — it measures how much
  training evidence backs a slot's fit, independent of whether any
  particular prediction turned out to be right. `accuracy` is
  backward-looking and diagnostics-only — it measures how close a
  specific prediction actually landed, and only exists once the slot has
  elapsed (or, for a future-pinned slot, not at all — see above). A
  well-supported slot (high confidence) can still have a bad individual
  prediction (low accuracy), and vice versa; the two are deliberately
  independent numbers, not two views of the same thing.
- **Selected-actual series**, `"selected actual"` — a single-point series
  at `[FC_selected, PV_selected]`, the *real* measured yield for the
  diagnosed slot. This depends entirely on the diagnosed slot already
  being over: auto-tracking (below) always satisfies this by
  construction, and so does most manual pinning (§2a). The one exception
  is a manually-pinned slot still in the future — there is no `PV`
  reading yet, so this series is simply **omitted from `series` entirely**
  (not present with an empty `data`) rather than shown with a placeholder
  point. See §2a for how a future pin is validated and what the rest of
  the sensor shows in that case.

**Which slot is "the diagnosed slot"** defaults, for a given moment, to
the **last complete** 5-minute slot, not the next upcoming one. A
not-yet-elapsed slot has no actual yield to compare against, so its
diagnostic view could only ever show the four methods disagreeing with
each other, never with reality. Using the most recently finished slot
means `"selected actual"` above is always populated, letting a person
directly see which method's prediction — made using the same historical
pool shown alongside it — actually came closest. This default can be
overridden to inspect a specific past **or future** slot instead — see
§2a.

### 2a — Manually selecting a specific slot via timestamp

Auto-tracking "the last complete slot" is the default, but a person
debugging a specific event (e.g. "why did the forecast look off around
14:00 yesterday") needs to inspect *that* slot specifically, not whatever
is currently most recent. A service, `shady.select_diagnostic_slot`,
takes a single optional parameter:

- **`timestamp`** (optional, ISO-8601 datetime): pins the diagnosed slot
  to the slot containing this timestamp, rounded *down* to the nearest
  5-minute boundary (matching the slot grid, ADR-001 §3a). Rejected with
  a validation error if the resulting slot falls **beyond the available
  `FC` data** — i.e. past ADR-002 §3's forecast horizon (the remainder of
  today, plus tomorrow if and only if the baseline provider has published
  that far) — since beyond that point there is no `FC` value of any kind,
  not even a forecasted one, for the four methods to evaluate. A slot
  that has not yet elapsed but *is* within that horizon is accepted:
  `"selected {method}"` still renders (§2, evaluated against the
  forward-looking `FC` for that slot), but `"selected actual"` is
  omitted and `accuracy` is an empty `{}`, since there is no `PV` yet to
  compare against — see §2 for the exact shape this takes. Omitting
  `timestamp` entirely (or calling the service with no parameters)
  **clears** the pin and returns to auto-tracking "last complete slot".

**There is exactly one diagnosed-slot state per config entry — not one
per sensor.** Every diagnostic sensor, the per-string
`ShadyDiagnosticsSensor`s (§2) and the summed `"sum"` entry (§2b,
the same class as of the 2026-09-03 Amendment) alike, shows the *same*
moment: whichever slot `cache.py`'s
`pinned_reference` (ADR-007a §6) currently names, or "last complete slot"
if it is unset. There is no per-sensor "is this one pinned or still
auto-tracking" toggle to keep in sync — the service is not entity-
targeted at all, since there is only ever one thing, config-entry-wide,
for it to affect. This is also what makes §2b's sum sensor well-defined
in the first place: summing `FC`/`PV` values across strings only makes
sense if every string's diagnostic is looking at the same instant: a
per-sensor pin would let strings disagree about *when*, making a
config-entry-level sum meaningless. In practice, one shared moment also
matches the motivating use case directly — "what did every string look
like around 14:00 yesterday" is a cross-string comparison at one moment,
not several strings each frozen at a different, unrelated one.

While pinned, the 5-minute tick (§2's "Refresh cadence") never advances
*which* slot is diagnosed — the pin, not the clock, decides that. For an
already-elapsed pinned slot, nothing about its underlying data changes as
time passes either, so the tick is a true no-op end to end, same as
before. A pinned slot that is still in the future is the one exception —
see "Refresh cadence" below for how that slot's own actual value and
accuracy eventually appear once real time catches up to it, without the
pin having to be re-issued.

**Every diagnostic sensor's slot-pool series comes from one function,
`get_pinned_slot_pool` (ADR-007a §6) — whether currently pinned or
auto-tracking.** There is no separate today-only call for the
auto-tracking case. See ADR-007a §6 for exactly how the function
resolves its own window from `pinned_reference` — including why a pin to
a **future** date falls back to the same window an auto-tracking sensor
already uses, since recalibration (ADR-002 §1) never trains on data
newer than yesterday, so there is no future-anchored pool for a future
pin to resolve to in the first place. What that resolution means for
this sensor specifically:

- **Auto-tracking, or pinned to today or a future date** — free. The
  resolved window is `[today − window_days, today]`, exactly what the
  same day's recalibration already fetched moments earlier to fit all
  288 slots' models, so the call is served from already-validated cache
  entries with no new recorder query.
- **Pinned to a past date outside the live window** — not free. The
  resolved window will typically not already be cached, so the call
  triggers a real recorder fetch for the missing range (`cache.py`'s
  validate-before-read, ADR-007a §4, handles this like any other cache
  miss).
- **Residual limitation:** data already trimmed *before* the pin was set
  cannot be recovered from the cache alone — `cache.trim()` (ADR-007a
  §1/§6) only extends its retained floor for a pin that already
  existed at trim time. `selected {method}`/`selected actual` still work
  for such a slot regardless, as long as the recorder itself still has
  that slot's raw `FC`/`PV` history — they don't depend on the pool
  cache at all, and are cheap either way, pinned or not.

**Pinning does not freeze the predictions themselves.** When
recalibration (ADR-002 §1) next runs, the four models refit regardless of
whether a pin is currently active, and a pinned sensor's `selected
{method}`/`accuracy` values are recomputed against the *newly*-fitted
models, still queried at the same (unchanged) pinned slot's own `FC`
value. Only *which slot* stays fixed while pinned — what the current
models say about that slot can still change once a day, same as it
would for an auto-tracking sensor whose slot happened to stay put.

**Refresh cadence.** Which slot counts as "last complete" changes purely
by the passage of time — every 5 minutes, independent of any event — so
neither ADR-002 §1's daily recalibration nor §2's irregular,
provider-driven baseline-update trigger would keep it current on their
own (a person could be looking at a diagnosed slot up to an hour stale,
waiting for the next baseline update to happen to fire). Rather than add
a third schedule, this reuses the 5-minute recorder-poll trigger ADR-006
§1a already introduces (`async_track_time_interval(hass, ...,
minutes=5)`) — advancing which slot is diagnosed, and refreshing
`"selected actual"`/`"selected {method}"`/`accuracy` (all cheap: one
PV/FC lookup plus four model evaluations per string, then a sum for
§2b's sensor) on every tick, **while auto-tracking**. While pinned
(§2a), *which* slot is diagnosed never advances on this tick — but
`"selected actual"`/`accuracy` still get re-evaluated on the same tick
if the pinned slot has not elapsed yet. An already-elapsed pinned slot
has nothing new to find (its `PV` was fixed the moment it happened), so
the tick is a genuine no-op for it, same as before this ADR's change. A
future-pinned slot's tick keeps checking whether it has elapsed yet, so
`"selected actual"`/`accuracy` populate — and the series-name accuracy
suffix appears — on the first tick after it does, without the pin
needing to be re-issued. The slot-pool series (`"-1"`/`"0"`/`"1"`) do
**not** get re-queried on this same tick either way — see §3. The four
fitted models behind the `"selected {method}"` points are unaffected by
this faster tick and still only change at ADR-002 §1's cadence, exactly
as §4 describes; only *which* slot's data is being displayed, and that
slot's now-available actual value and accuracy, track the 5-minute
tick.

### 2b — A summed-up diagnostics sensor across all strings (revised 2026-09-03)

Alongside the per-string sensors (§2), one `sensor_id="sum"` entity
(same `ShadyDiagnosticsSensor` class, per §5's 2026-09-03 revision —
not a dedicated `ShadyDiagnosticsSumSensor` class) mirrors ADR-005's
`ShadyPvSumSensor`/
`ShadyFcSumSensor` pattern: the same `series`/`accuracy` shape as §2, but
every point is the **pointwise sum across strings** at the one shared
diagnosed slot (§2a) — e.g. the `"0"` series' day-*i* point is
`[Σ FC_i, Σ PV_i]` across all configured strings for that day, not a
concatenation of every string's own points into one bigger cloud. This
is exactly why §2a makes the diagnosed slot config-entry-wide rather than
per-sensor: a pointwise sum across strings is only meaningful if "day
*i*'s point" means the same day and slot for every string being summed.

This sensor's `series`/`accuracy` are, as of the 2026-09-03 Amendment,
built by `CompareRegressionsMode.compute()` itself, from each
contributing string's raw pool data — not assembled in `sensor.py` from
the per-string sensors' own already-computed output (see that
Amendment for why: the original approach here was vulnerable to a
cross-string day-alignment bug once two strings' historical data had
different gap patterns). `accuracy` is still computed from *summed*
predicted/actual values (`1 - |Σ predicted_i − Σ PV_selected| /
Σ PV_selected`, same clamping as §2), not by averaging the per-string
accuracy percentages — consistent with deriving ratios from sums rather
than summing ratios, the same principle ADR-005 applies throughout,
unchanged by the 2026-09-03 revision. It updates on the same triggers
as the per-string sensors (§2a's 5-minute tick while auto-tracking; a
pin update; recalibration for the four fitted-model points), gated by
the same diagnostic-mode select (§1).



### 3 — Caching the historical pool: refresh at midnight/system start, not every tick

Re-querying the recorder for a slot's full rolling-window history
(`window_days` samples, ADR-001 §4, times up to `2·smoothing_radius + 1`
slots, ADR-011 §1) on every 5-minute tick — just to redraw the same
`"-1"`/`"0"`/`"1"` series with one slot's worth of difference — would be
wasteful: that data only meaningfully changes once a day, when the
rolling window advances by one calendar day.

This does not need a second recorder-reading mechanism, because the data
required is **exactly what `cache.py`'s cache already holds** — the same
per-slot historical pool `coordinator.py` reads for every one of the 288
slots during recalibration (ADR-002 §1), since fitting all 288 slot
models necessarily means reading all 288 pools first. When the
diagnostics switch (§1) is on, every per-string sensor's
`"-1"`/`"0"`/`"1"` series are populated by calling `get_pinned_slot_pool`
(ADR-007a §6) for the diagnosed slot (and its neighbors) — the **same**
call whether currently pinned or auto-tracking (§2a); there is no
separate today-only accessor diagnostics falls back to. While
auto-tracking, that call's internally-resolved window happens to be
exactly what recalibration already fetched moments earlier, so it costs
nothing extra: no new recorder query, just a read of already-validated
cache entries. While pinned to a date outside the live window, the same
call's resolved window is typically *not* already cached, so it is not
free the same way — see §2a for what that costs. §2b's sum entry adds
no third fetch of its own — as of the 2026-09-03 Amendment, it's built
from the same `_gather_pool` call `compute()` already makes for each
contributing string's own per-string entry, not a separate read.

The cache refreshes on exactly the same triggers as the recalibration
that produces it — **midnight or button** (ADR-002 §1) — plus **once at
system start**, since a fresh restart has no recalibration-produced data
yet to retain until the first one runs; a restart also invalidates
`cache.py`'s validated ranges (ADR-007a §2) for these sensors, so the
first `get_pinned_slot_pool` call after one naturally triggers the
full-history fetch path (ADR-007a §4) rather than assuming stale
in-memory state survived. While **auto-tracking**, the slot-pool series
are **not** refreshed on the 5-minute tick from §2, nor on ADR-002 §2's
baseline-update trigger — only recalibration (or a restart priming it
for the first time) changes what they show for the rest of the day.
Turning the diagnostics switch on *between* two recalibrations means
`get_pinned_slot_pool` may return mostly-invalidated data until the next
of those triggers fires; the slot-pool series show nothing new until
then, while `"selected {method}"`/`"selected actual"`/`accuracy` keep
working immediately, since those only need the diagnosed slot's own live
`FC`/`PV` values, not the historical pool. While **pinned**, none of
this staleness applies — see §2a.

### 4 — Extra fitting cost only while `compare_regressions` is active

Producing the four `"selected {method}"` points requires fitting all four
strategies for the diagnosed slot, not just the one configured default —
extra work beyond what ADR-002 §1's normal recalibration does. This only
happens while the select (§1) is set to `compare_regressions` — as of the
2026-08-30 amendment, `CompareRegressionsMode.extra_fit()` — and only for
the one diagnosed slot per string (not all 288), keeping the added cost
bounded and opt-in: the three non-default methods are fitted alongside
the active one at the same recalibration trigger (midnight or button,
ADR-002 §1). All four are then queried on the same 5-minute trigger that
advances which slot is diagnosed (ADR-006 §1a, per §2 above) — not
ADR-002 §2's irregular baseline-update trigger — so the four predictions
always match whichever slot's pool and actual value are currently being
displayed, rather than momentarily lagging behind it.

### 5 — Module responsibility (revised 2026-08-30, 2026-09-01, 2026-09-03)

`select.py` adds `ShadyDiagnosticModeSelect`, a simple, single-purpose HA
entity (`SelectEntity`) with no business logic of its own beyond exposing
`const.py`'s `DIAGNOSTIC_MODES` option list and persisting the chosen
option for `coordinator.py` to read — the same "thin entity glue"
philosophy `button.py`'s `EffyRecalculateButton`-style pattern (ADR-002
§1) already established, just for a multi-value control instead of a
single-purpose trigger. The actual diagnostic calculation lives in the new
pure package `diagnostics/` (ADR-012-style base class + concrete modes;
see the Amendment blocks above for the full `DiagnosticMode` shape):
`diagnostics/base.py` holds the shared `DiagnosticMode` ABC; `diagnostics/
compare_regressions.py` holds this ADR's one concrete mode,
`CompareRegressionsMode`. `coordinator.py` holds `_diagnostic_modes` (a
per-instance registry as of the 2026-09-01 amendment — mirroring its
existing `REGRESSION_STRATEGIES` lookup in shape) and calls the active
mode's `extra_fit()` generically at the recalibration trigger, exactly as
it already runs one generic loop over `forward()`-implementing providers
(ADR-012 §4) — same "one dispatch site, not one branch per concrete case"
shape. As of 2026-09-01, that call takes no arguments — `extra_fit()`
resolves whatever it needs itself through the `ShadyCoordinator` reference
it was constructed with, rather than `coordinator.py` assembling anything
for it first.

The retained per-slot pool cache from §3 lives in `cache.py` (ADR-007),
populated by `coordinator.py` as a side effect of recalibration — not
owned by `coordinator.py` directly, matching every other cache in this
design. The accuracy calculation (`1 - |predicted - actual| / actual`,
clamped, per §2) stays a pure function in `aggregation.py` — **not** in
`diagnostics/`, since it takes plain numbers in and returns a plain
number out, with no per-mode or per-string knowledge needed, and is
therefore reusable by any future `DiagnosticMode` unchanged (see ADR-013
for two sketched future modes that call this same function); §2b's
pointwise sum-then-accuracy calculation is a second, equally pure
function alongside it, taking each string's already-computed numbers in
rather than reaching back into `regression/` itself. As of 2026-09-01,
each `DiagnosticMode` calls into `aggregation.py` itself, from within its
own `compute()`, having first resolved the predicted/actual values it
needs via its coordinator reference — `aggregation.py`'s functions
themselves are untouched by this amendment.

`sensor.py` adds `ShadyDiagnosticsSensor` — as of 2026-09-03, one
generic instance per `(sensor_id, name)` pair from
`coordinator.diagnostic_sensor_ids()` (§2's per-string ids and §2b's
`"sum"` id alike, no dedicated `ShadyDiagnosticsSumSensor` class),
following the six `ShadyPvSumSensor`-style sensors' placement in
`sensor.py` per ADR-005's "Module: a new pure aggregation layer"
section — staying thin like every other sensor in this design. **As of
2026-09-01, this got thinner still, and as of 2026-09-03, thinner
again:** each instance looks up its own `sensor_id` in
`coordinator.diagnostic_result()` — a cached accessor over the active
mode's `.compute()` output, not a direct call — and sets
`state`/`attributes` straight from the matching entry (the `"sum"`
entry included: built by the mode itself now, not reassembled here from
sibling sensors' output); if no mode is active, it reports `disabled`
as §1 specifies. `sensor.py` no longer assembles anything for the mode
to consume, nor knows how many entities a mode produces or what any of
them represent beyond a `(sensor_id, name)` pair — resolving which slot
is being diagnosed (reading `cache.py`'s `pinned_reference` scalar via
its coordinator reference, or falling back to the last-complete-slot
default when unset, §2a), fetching that slot's pool/predicted/actual
values, and deciding what aggregate entities (if any) to produce
alongside the per-string ones are all the mode's own job, done inside
`compute()`/`extra_fit()`/`sensor_ids()` via the coordinator reference
each was constructed with. This shaping is pure presentation and does
not belong in `regression/` or `forecast_adjust.py`. The
`shady.select_diagnostic_slot` service (§2a) is registered in
`__init__.py` (the usual home for service registration), is **not**
entity-targeted (§2a — there is one diagnosed-slot state per config
entry, not one per sensor), and its handler is a thin wrapper that
validates the timestamp and calls that config entry's coordinator, which
in turn forwards to `cache.py`'s `pin_reference`/`clear_reference`
(ADR-007a §6) — `cache.py` is still only ever reached through
`coordinator.py` (ADR-007 §2), the same as every other caller; `__init__.py`
does not reach into `cache.py` directly, and no new module is needed for
a single service handler this small.

---

## Consequences

- **Pro:** Turns the manual "build a scatter plot to understand this
  slot's fit" exercise from this project's own design process into a
  standing, opt-in feature — the same validation is available to every
  installation on its own real data, not just during development.
- **Pro:** Diagnosing the last complete slot rather than the next upcoming
  one means the sensor always has a real measured value to compare all
  four methods against, not just the four methods disagreeing with each
  other — turning it from "which prediction do I trust" guesswork into a
  direct accuracy check against what just actually happened.
- **Pro:** Showing all four methods' selected-predictions side by side,
  against the real training pool, lets a user judge whether the
  configured default (`wls2`) is behaving sensibly for their specific
  installation, and switch methods (ADR-001 §2, a global setting) with
  actual evidence rather than guessing.
- **Pro:** Manually selecting a slot by timestamp (§2a) turns this from a
  "what does it look like right now" tool into one that can also answer
  "what did it look like at that specific moment" — useful precisely when
  investigating a specific past event — or "what does it look like at an
  upcoming moment", e.g. previewing how the four methods currently
  disagree on a slot later today or tomorrow, without waiting for it to
  elapse. A past pin costs nothing extra when the pinned date is recent
  enough to already be cached, and at most one bounded, on-demand fetch
  (ADR-007a §4/§6) otherwise; a future pin is always free the same way
  auto-tracking already is (§2a), since it resolves to the same
  already-cached window.
- **Pro:** Default-off plus the always-on entity / conditionally-computed
  content pattern (§1) keeps the cost at zero for installations that
  never enable it, consistent with ADR-003a §2 / ADR-003b §2's no-op
  philosophy for optional features.
- **Pro:** Embedding accuracy directly in each series name (`"selected
  wls2 (96%)"`) means the comparison is visible on the chart itself — no
  separate legend, tooltip, or lookup needed — while the plain-number
  `accuracy` attribute (§2) still gives automations/templates a value to
  read without parsing a formatted string.
- **Pro:** Both the auto-tracking and pinned cases go through the same
  `get_pinned_slot_pool` call (§3, ADR-007a §6), reusing the exact same
  recorder-reading mechanism (`fetch_fn`/`statistics_during_period`,
  ADR-007a §4) `coordinator.py` already uses for fitting — the diagnostic
  feature introduces no second way of talking to the recorder, only an
  occasional extra invocation of the one it already has.
- **Pro:** The summed diagnostics sensor (§2b) gives a config-entry-level
  "how did the whole system do" view alongside the per-string detail,
  matching ADR-005's existing sum-sensor pattern, at no extra fitting or
  fetching cost of its own — it only ever sums numbers the per-string
  sensors already computed.
- **Con:** With `compare_regressions` active, recalibration (ADR-002 §1)
  does roughly 4× the fitting work per string (all four methods instead
  of one) for the diagnosed slot — small in absolute terms (one slot, not
  288), but not free, and scales with the number of configured strings.
- **Pro (2026-08-30 amendment):** The select-plus-base-class redesign
  turns "add a second diagnostic mode" from a rework of a boolean-gated
  entity and its inline logic into an additive change — a new option
  string, a new `DiagnosticMode` subclass, one registry entry.
  *(2026-09-01 note: ADR-013's own two sketched modes needing no change
  to* `diagnostics/base.py` *was true of this redesign in isolation;
  `diagnostics/base.py` did change again, 2026-09-01, for the unrelated
  reason covered in that Amendment block — see ADR-013's own pointer note
  for what did and didn't need revisiting as a result.)*
- **Con (2026-08-30 amendment, superseded 2026-09-01):**
  `DiagnosticContext.samples` being a `Sequence` (one item today,
  potentially 288 for a future whole-day mode) means
  `CompareRegressionsMode.compute()` must still assume exactly one sample
  even though the type does not enforce that — the same category of
  runtime-not-enforced contract ADR-012 §1 already accepts for
  `forward()`'s optionality. *Moot as of 2026-09-01: `DiagnosticContext`
  is removed outright (see that Amendment block); a future whole-day
  mode's `compute()` would instead resolve however many slots it needs
  directly through its own coordinator reference, with no shared
  cardinality-typed parameter to under-constrain in the first place.*
- **Con:** There is exactly one diagnosed-slot state per config entry
  (§2a), not one per string — a direct trade against the summed sensor
  (§2b) being well-defined at all. A person cannot pin string A to one
  moment while comparing it against string B at a different moment; every
  currently-pinned view, across every string, moves together.
- **Con:** The slot-pool series (§3) can be up to a day stale relative to
  the diagnosed slot's own live position — e.g. right before the next
  midnight recalibration, the cached pool still reflects yesterday's
  rolling window, not one that has already silently advanced by a day.
  This is a deliberate trade for avoiding constant re-querying, but it
  means the slot-pool series and the `"selected {method}"`/`"selected actual"`
  points are not always drawn from windows that agree to the day.
- **Con:** The `series` attribute's shape is a public contract once
  dashboards are built against it, and embedding accuracy in the name
  (`"selected wls2 (96%)"`) makes this sharper than a plain `"selected
  wls2"` would have been: the percentage changes on every 5-minute tick
  for auto-tracking sensors (§2), so a dashboard cannot match against an
  exact series name at all — it must match by prefix (`"selected wls2"`)
  or, better, ignore `series` names for programmatic use and read the
  plain `accuracy` attribute instead, which
  exists precisely to give a stable, unformatted alternative. This is the
  same category of concern ADR-009 raises about *other* integrations'
  attributes — except here it is Shady's own contract to keep predictable.
  A future-pinned slot (§2a) sharpens this further: `accuracy` is `{}`
  and the `"selected actual"` entry is absent from `series` altogether,
  so a consumer needs to treat "not present yet" as a valid state, not
  just anticipate different numbers.
- **Con:** A future-pinned slot (§2a) is a genuinely incomplete view by
  design — `"selected actual"` and `accuracy` are simply unavailable
  until real time catches up to it, and the series-name accuracy suffix
  disappears along with them (§2). Pinning a future slot to "see what the
  forecast currently looks like there" gets exactly that, and nothing
  that claims to have validated it yet.
- **Con (2026-09-01 amendment):** `diagnostics/` moves out of ADR-000
  §6's zero-mocking test tier entirely — every `DiagnosticMode` test now
  needs a real or hand-stubbed `ShadyCoordinator` (the same `hass`-stub
  convention `coordinator.py`'s own tests already use, TASK-0009), not a
  bare dataclass. This is a genuine loss of the "pure, zero-mocking"
  guarantee this ADR's original 2026-08-30 amendment, and ADR-014 in
  full, both specifically built toward.
- **Con (2026-09-01 amendment):** A `DiagnosticMode` can now, in
  principle, reach any public method `ShadyCoordinator` exposes — the
  boundary that keeps this disciplined (only public, non-`_`-prefixed
  access; extend the coordinator's public surface deliberately rather
  than reaching into private state) is a convention this ADR states, not
  one the type system enforces, the same category of "runtime-not-
  enforced contract" ADR-012 §1 already accepts for `forward()`'s
  optionality (the same comparison the now-superseded
  `DiagnosticContext.samples` Con above used to make).
- **Pro (2026-09-01 amendment):** Removes the need to keep extending
  `DiagnosticSlotSample`/a per-mode input dataclass every time a new or
  changed mode needs one more coordinator-owned value —
  `TASK-0015a-patch-1` was itself already one instance of this friction,
  discovered before it had even shipped. A mode now pulls what it needs
  directly, the same way `sensor.py`/`select.py`/`button.py` already
  reach `coordinator.py` freely as HA-facing glue.
- **Pro (2026-09-01 amendment):** `compute()`/`extra_fit()` losing their
  parameter, and `DiagnosticSlotSample`/`DiagnosticContext` being deleted
  rather than kept alongside the new constructor, avoids two competing,
  overlapping ways to hand a mode its inputs existing in the codebase at
  once — a mode has exactly one path to its data (the coordinator
  reference) with nothing to remember to keep in sync between it and a
  now-redundant parallel DTO.
- **Pro (2026-09-01 amendment):** `fit_cadence()`/`compute_cadence()`
  give `coordinator.py` (or its trigger-registration code) a generic,
  declared answer to "how often does this mode need to run," directly
  useful for ADR-013's sketched whole-day modes' unresolved cadence
  question (§3) without committing to scheduling them now.
