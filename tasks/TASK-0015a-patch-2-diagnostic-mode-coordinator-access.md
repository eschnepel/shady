# Task: Patch — `DiagnosticMode` Gains Coordinator Access + Cadence Getters

- **Status:** done
- **Related ADRs:** [ADR-004 §5 (Amendment 2026-09-01), ADR-000 §3/§6 (Amendment 2026-09-01), ADR-014]
- **Dependencies:** [TASK-0015a-diagnostic-mode-base-architecture, TASK-0010-coordinator-recalibration-recompute-push]

## Goal
Scenario C patch on the already-`done` `TASK-0015a`: give every
`DiagnosticMode` a required, construction-time reference to the owning
`ShadyCoordinator`; add two new abstract getters declaring how often a
mode needs to fit and compute; and — since a mode can now resolve
whatever it needs directly through that coordinator reference — drop
`compute()`/`extra_fit()`'s `DiagnosticContext` parameter entirely,
deleting `DiagnosticContext` and `DiagnosticSlotSample` from
`diagnostics/base.py` rather than keeping them alongside the new
constructor. This **supersedes `TASK-0015a-patch-1-diagnostic-fit-inputs`**
(not implemented, no code exists for it) rather than coexisting with it —
see ADR-004 §5's second Amendment (2026-09-01) for the full rationale and
`tasks/INDEX.md`'s matching refinement-log entry.

This is the human-directed design change discussed while reviewing
ADR-014 and `TASK-0015a`/`TASK-0015b`, refined once more on review before
any of it was implemented: the coordinator should not need to know what a
diagnostic mode does or needs internally, beyond the two cadence getters
below — a mode instead pulls whatever coordinator-owned data it needs
(string config, registered FC providers, the cache) on demand through the
coordinator's own public interface. Once that reference exists, a
separate per-call context parameter carrying the same category of
information is redundant — everything `DiagnosticContext`/
`DiagnosticSlotSample` used to carry becomes something `compute()`/
`extra_fit()` resolve for themselves, so those two dataclasses are removed
rather than left in place unused.

## Acceptance Criteria
- Given a minimal dummy `DiagnosticMode` subclass, When it is
  instantiated without a `coordinator` argument, Then instantiation
  fails — the constructor parameter is required, no default.
- Given a minimal dummy `DiagnosticMode` subclass instantiated with a
  stand-in coordinator object, When the instance is inspected, Then the
  coordinator it was constructed with is reachable from within the
  instance (e.g. via `self._coordinator` or equivalent) for `compute()`/
  `extra_fit()`/the two new getters to use.
- Given a dummy `DiagnosticMode` subclass that implements `compute()` but
  omits `fit_cadence()` or `compute_cadence()`, When it is instantiated,
  Then instantiation fails — both getters are abstract, required, no
  default, the same requiredness `compute()` itself already has.
- Given a dummy `DiagnosticMode` subclass implementing all three abstract
  members (`compute()`, `fit_cadence()`, `compute_cadence()`), When
  `fit_cadence()`/`compute_cadence()` are called, Then each returns
  exactly one of `"daily"`, `"hourly"`, `"slot"` — no other value is a
  valid return, enforced by the return type (`Literal["daily", "hourly",
  "slot"]` or an equivalent enum — implementer's choice, documented in
  Delivered Artifacts).
- Given `DiagnosticMode.compute`, When its new signature is inspected,
  Then it is `compute(self) -> DiagnosticResult` — no parameter beyond
  `self`. Given `DiagnosticMode.extra_fit`, When its new signature is
  inspected, Then it is `extra_fit(self) -> DiagnosticFitResult | None` —
  no parameter beyond `self`, still optional, still defaults to returning
  `None` when a subclass doesn't override it.
- Given `diagnostics/base.py` after this patch, When its exports are
  listed, Then `DiagnosticContext` and `DiagnosticSlotSample` are **not**
  among them — both are deleted outright, not deprecated-and-kept, not
  left as unused dead code. `DiagnosticResult` and `DiagnosticFitResult`
  remain exactly as `TASK-0015a` delivered them (both are `compute()`'s/
  `extra_fit()`'s output types, unaffected by the parameter removal).
- Given this patch is applied, When `tests/test_diagnostics_base.py`'s
  existing tests (from `TASK-0015a`) are revised, Then every test that
  called `compute(context)`/`extra_fit(context)` calls `compute()`/
  `extra_fit()` instead (no argument), every test that instantiated a
  `DiagnosticContext`/`DiagnosticSlotSample` is removed or rewritten to
  no longer need one, and every `DiagnosticMode` subclass instantiation
  in the suite supplies a coordinator stand-in — while every assertion
  about `DiagnosticResult`/`DiagnosticFitResult`'s own shape stays
  unchanged.
- Given `TASK-0015a-patch-1-diagnostic-fit-inputs` (todo, unimplemented,
  itself dependent on `DiagnosticSlotSample` continuing to exist), When
  this patch is written, Then it is **not** also implemented — remains
  `superseded` in its own file and in `tasks/INDEX.md`, per ADR-004 §5's
  second Amendment. This task's Delivered Artifacts must not include
  `DiagnosticSlotSample.query_fc`/`.fit_inputs` or `DiagnosticFitInputs`
  — those belong to the superseded task and are not reintroduced here,
  and could not be even if desired, since `DiagnosticSlotSample` no
  longer exists after this patch.

## Estimated File / Module Footprint (hint, not a commitment)
- `custom_components/shady/diagnostics/base.py` (rewritten —
  `DiagnosticContext`/`DiagnosticSlotSample` deleted; `DiagnosticMode`
  gains `__init__`, `fit_cadence`, `compute_cadence`; `compute`/
  `extra_fit` lose their parameter; a `TYPE_CHECKING`-only import of
  `ShadyCoordinator` from `..coordinator`, guarded so no runtime import of
  `coordinator.py`/`homeassistant.*` is introduced; `DiagnosticResult`/
  `DiagnosticFitResult` untouched)
- `tests/test_diagnostics_base.py` (revised throughout — see the
  acceptance criterion above; new tests for the constructor requirement
  and the two cadence getters, existing tests losing every
  `DiagnosticContext`/`DiagnosticSlotSample` reference)
- **Testing tier change, not just file scope:** as of ADR-004 §5's
  second Amendment (2026-09-01) and the matching ADR-000 §6 update,
  `diagnostics/` is no longer in the zero-mocking test tier. This task's
  own tests may still get away with a minimal hand-written stand-in
  object (not a full `ShadyCoordinator`) if `DiagnosticMode`'s base-class
  tests genuinely don't call through it — but any test that exercises a
  cadence getter or the stored reference against real coordinator
  behavior should follow `coordinator.py`'s own hand-written
  `homeassistant`-stub convention (TASK-0009, `tests/test_coordinator.py`)
  rather than inventing a second convention. Worker's call, documented in
  Delivered Artifacts.

## Definition of Done
- Tests green · docs updated · no open ADR conflicts
- `Delivered Artifacts` block completed and accurate
- Any new external dependencies recorded in `tasks/DEPENDENCIES.md`
- `TASK-0015a-patch-1-diagnostic-fit-inputs` remains `superseded`, not
  implemented alongside this task.

## Consumed Interfaces
<!-- Filled by the Lead Agent BEFORE implementation, derived from the
     Delivered Artifacts of TASK-0015a and TASK-0010. -->
- `diagnostics.base.DiagnosticMode`, `DiagnosticResult`,
  `DiagnosticFitResult` (as `TASK-0015a` delivered them — only
  `DiagnosticMode` itself changes shape, per the Goal above;
  `DiagnosticResult`/`DiagnosticFitResult` are unaffected) from
  `custom_components/shady/diagnostics/base.py` (→ task:
  TASK-0015a-diagnostic-mode-base-architecture). `DiagnosticContext` and
  `DiagnosticSlotSample`, also delivered by `TASK-0015a`, are **not**
  consumed here — this task deletes them; nothing about this patch reuses
  their prior shape.
- `coordinator.ShadyCoordinator` — used only as a `TYPE_CHECKING`-only
  type reference for `DiagnosticMode.__init__`'s parameter annotation, not
  a runtime import. In particular: `ShadyCoordinator.cache` (public
  attribute, not a method — confirmed directly against
  `custom_components/shady/coordinator.py`, `self.cache = Cache(...)` in
  `__init__`) and `ShadyCoordinator.strings() -> list[tuple[int, str]]`
  (public method, delivered by `TASK-0010-patch-2-string-enumeration`)
  are the two public accessors already available; no other private
  (`_`-prefixed) attribute of `ShadyCoordinator` may be referenced by
  `diagnostics/` — see ADR-004 §5's second Amendment for the boundary
  rule and what to do if a mode needs a coordinator-owned value with no
  public accessor yet. from `custom_components/shady/coordinator.py`
  (→ task: TASK-0010-coordinator-recalibration-recompute-push).

## Delivered Artifacts
<!-- Filled by the Worker AFTER implementation. Be exact —
     downstream tasks depend on this information. -->
- `custom_components/shady/diagnostics/base.py` (rewritten) →
  - `DiagnosticCadence` — module-level type alias,
    `Literal["daily", "hourly", "slot"]`.
  - `class DiagnosticMode(ABC)` — new shape:
    - `__init__(self, coordinator: ShadyCoordinator) -> None` (required,
      no default; stores `self._coordinator = coordinator`).
    - `key: ClassVar[str]` — unchanged from `TASK-0015a`.
    - `fit_cadence(self) -> DiagnosticCadence` — abstract, required, no
      default.
    - `compute_cadence(self) -> DiagnosticCadence` — abstract, required,
      no default.
    - `compute(self) -> DiagnosticResult` — abstract, required,
      no-parameter (parameter dropped).
    - `extra_fit(self) -> DiagnosticFitResult | None` — optional,
      no-parameter (parameter dropped), defaults to `None`.
  - `class DiagnosticResult` — unchanged from `TASK-0015a`
    (`state: str`, `attributes: dict[str, Any]`).
  - `class DiagnosticFitResult` — unchanged from `TASK-0015a`
    (`predictions: Mapping[str, float]`).
  - `DiagnosticContext` and `DiagnosticSlotSample` — **deleted**, not
    exported, not importable from this module.
  - `ShadyCoordinator` is imported only under `if TYPE_CHECKING:` from
    `..coordinator` — no runtime import of `coordinator.py`/
    `homeassistant.*` is introduced by this module.
- `tests/test_diagnostics_base.py` (rewritten, 15 tests across 10
  classes) — covers every acceptance criterion above: constructor
  requiredness (missing-coordinator `TypeError`), coordinator
  reachability (`mode._coordinator is coordinator`), both cadence
  getters' requiredness (individually and together), `compute()`
  requiredness, all three cadence literal values round-tripping,
  `compute()`/`extra_fit()` taking no parameters beyond `self`,
  `DiagnosticContext`/`DiagnosticSlotSample` no longer being attributes
  of the loaded module, `DiagnosticResult`/`DiagnosticFitResult` still
  being attributes of it, `extra_fit()`'s `DiagnosticFitResult` payload
  round-tripping unchanged, and one mode reading data through its stored
  coordinator reference's public `strings()` method end-to-end.
  - **Testing-tier note (worker's call, per this task's own footprint
    guidance):** kept the lighter hand-written stand-in convention
    (`_StubCoordinator`, a bare class with no behavior; a second
    `_CoordinatorWithData` stand-in with a real `strings()` method for
    the one test that reads through it) rather than switching to
    `coordinator.py`'s full `homeassistant`-stub convention — no test in
    this file exercises real coordinator/HA behavior, only
    `DiagnosticMode`'s own base-class shape and simple attribute/method
    reads off whatever object is stored. A future test here that
    exercises a cadence getter or the stored reference against *real*
    coordinator behavior should switch to the heavier
    `test_coordinator.py`-style convention instead of extending this
    one.
  - **mypy note:** `DiagnosticMode.__init__`'s `coordinator` parameter
    resolves to the real `ShadyCoordinator` type under `mypy --strict`
    (via the same `TYPE_CHECKING`-only static import convention
    `test_diagnostics_base.py` already used for `TASK-0015a`), so the
    hand-written stand-ins are constructed through small `-> Any`-typed
    factory functions (`_stub_coordinator()`, `_coordinator_with_data()`)
    rather than passed directly or suppressed with a
    `# type: ignore[arg-type]` at every call site — the same
    "fake object standing in for a strictly-typed dependency" pattern
    `test_coordinator.py`'s own `Any`-typed helpers already establish,
    applied here at the object-construction boundary instead of the
    whole-module-load boundary.
- External dependencies added: none — `tasks/DEPENDENCIES.md` unchanged.
- Full suite: 338/338 (332 pre-existing, less 9 replaced
  `TASK-0015a`-era tests, plus 15 new `TASK-0015a-patch-2` tests —
  net +6). `mypy --strict` clean on 45 source files (`custom_components/`
  + `tests/`). `ruff check` clean repo-wide. `ruff format --check` clean
  on both files this task touched (`diagnostics/base.py`,
  `test_diagnostics_base.py`); two pre-existing, unrelated,
  already-documented format-drift files (`tests/test_regression.py`,
  2026-08-26 log entry; `adr/004-diagnostics-select-and-scatter-sensor.md`,
  a markdown file with an embedded illustrative code block, not touched
  by this task) are untouched, out of scope.
- `git diff --stat` confirms only `custom_components/shady/diagnostics/base.py`
  and `tests/test_diagnostics_base.py` changed in this task's commit.
- `TASK-0015a-patch-1-diagnostic-fit-inputs` remains `superseded`, not
  implemented — confirmed no `DiagnosticSlotSample.query_fc`/`.fit_inputs`
  or `DiagnosticFitInputs` anywhere in this delivery (impossible in any
  case, since `DiagnosticSlotSample` no longer exists after this patch).
