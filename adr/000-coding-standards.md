# ADR-000 – Code Quality Standards, Programming Style & Core Concepts

**Date:** 2026-07-04
**Status:** Accepted

---

## Context

This ADR documents the overarching engineering conventions used throughout
the Shady codebase. It exists so that contributors and future maintainers can
understand *why* the code looks the way it does without having to infer it
from individual diffs. The numbered ADRs (001 onward) cover specific
domain decisions (e.g. horizon-profile modeling, sun-position calculation,
forecast-adjustment strategy); this one covers everything that applies
uniformly across all files.

This document is adapted from the sibling project
[Effy](https://github.com/eschnepel/effy)'s ADR-000, so that both projects
share a consistent engineering baseline. Sections specific to Effy's domain
(loss distribution) have been replaced with Shady's own module boundaries.

---

## Decision

### 1 — Tooling: ruff, mypy strict, pytest

Three tools gate every change, run via `.github/workflows/ci.yml`:

| Tool | Purpose | Invocation |
|---|---|---|
| `ruff format` | Code formatting (replaces black) | `ruff format custom_components/` |
| `ruff check` | Linting (replaces flake8/isort/pyupgrade) | `ruff check custom_components/` |
| `mypy --strict` | Static type checking | `mypy custom_components/shady tests --config-file mypy.ini` |
| `pytest` | Unit tests | `pytest tests/` |

All four must pass with zero errors before a change is considered complete.
`mypy --strict` is non-negotiable: every function signature carries full
type annotations, including return types on methods that return `None`.

### 2 — Handling Home Assistant's untyped surface

Home Assistant ships without inline type stubs for many of its base classes
and decorators (`SensorEntity`, `ConfigFlow`, `@callback`, etc.). Under
`mypy --strict` this produces two categories of unavoidable noise:

- `misc` errors when subclassing a base class typed as `Any`.
- `untyped-decorator` errors when `@callback` wraps a method.

These are suppressed **per-file**, not globally, via `mypy.ini`
(`warn_unused_ignores = False` on the specific modules that subclass HA
entities or use `@callback`), combined with targeted
`# type: ignore[<code>]` comments at the exact line mypy flags. Suppression
is never broad (no bare `# type: ignore` without a code, no
`disable_error_code` at the global `[mypy]` level) — the goal is to silence
exactly the HA-stub gap, not to weaken type checking elsewhere.

The comment goes on the exact source line mypy reports, not on a nearby
line: `misc` errors on subclassing are attached to the base-class entry in
the class statement (e.g. `class ShadySensor(SensorEntity):  # type:
ignore[misc]`), and `untyped-decorator` errors are attached to the
`@callback` line itself, not the `def` line below it — mypy's reported line
number is authoritative and should never be guessed at.

`shading.py` and `sun_geometry.py` have zero Home Assistant imports and are
held to the full, unsuppressed strict standard — they are pure,
framework-independent Python and are tested as such (see §6).

### 3 — Module boundaries and dependency direction

```
sun_geometry.py  (pure math: sun azimuth/elevation for a given lat/lon/time)
horizon_profile.py (pure data: user-defined obstruction profile, e.g. tree)
       ↑                    ↑
shading.py       (pure logic: combines sun position + horizon → shading factor)
       ↑
forecast_adjust.py (pure logic: applies shading factor to a raw PV forecast series)
       ↑
coordinator.py   (orchestrates: fetches forecast source + schedules recalculation)
       ↑
sensor.py / config_flow.py  (HA entity glue)
       ↑
__init__.py      (wires platforms + coordinator into hass.data)
```

Dependencies point upward only. `sun_geometry.py`, `horizon_profile.py`,
`shading.py`, and `forecast_adjust.py` never import from any HA-facing
module, and never import `homeassistant.*` directly. This separation is
what allows the entire shading/forecast math to be unit-tested in complete
isolation from Home Assistant (see §6), independent of which upstream PV
forecast integration (e.g. Forecast.Solar, Solcast) is being adjusted.

### 4 — Type-hinting conventions

- `from __future__ import annotations` at the top of every module — allows
  modern `list[str] | None` syntax without runtime evaluation cost and
  without requiring Python 3.10+ at runtime (HA's actual minimum is lower).
- Built-in generics (`list[str]`, `dict[str, float]`) are used directly;
  `typing.List`/`typing.Dict` are never imported.
- `X | None` is used instead of `Optional[X]`.
- Every function and method has a complete signature: parameter types and
  a return type, including `-> None`. This applies to private helpers
  (e.g. `_interpolate_horizon`, `_clamp_elevation`) and test code exactly as
  it does to public HA-facing methods — `mypy --strict` does not
  distinguish, and a single unannotated parameter triggers `no-untyped-def`
  just as an entirely bare signature does.
- `@dataclass` is used for plain data containers (`SunPosition`,
  `HorizonPoint`, `ShadingFactor`) instead of dicts or named tuples — gives
  attribute access, auto-generated `__init__`/`__repr__`/`__eq__`, and a
  single place to add validation later if needed.

### 5 — Naming and structure

- Module-level constants are `UPPER_SNAKE_CASE` and live in `const.py`
  (cross-module) or at the top of the module that owns them (single-use,
  e.g. `DEFAULT_POLL_INTERVAL` in `coordinator.py`).
- Private helpers are prefixed with a single underscore (`_interpolate_horizon`,
  `_azimuth_to_bearing`) and are not exported.
- HA-facing entities (`ShadySensor`, `ShadyCoordinator`, `ShadyConfigFlow`,
  `ShadyOptionsFlow`) are all prefixed `Shady` for discoverability when
  grepping or reading stack traces.
- One concept per module: `sun_geometry.py` only computes sun position,
  `horizon_profile.py` only models the obstruction outline, `shading.py`
  only turns the two into a shading factor, `forecast_adjust.py` only
  applies that factor to a forecast series, `coordinator.py` only
  orchestrates. A module that starts doing two unrelated things is a signal
  to split it.

### 6 — Testing philosophy

- `sun_geometry.py`, `horizon_profile.py`, `shading.py`, and
  `forecast_adjust.py` are unit-tested with **zero mocking** — no
  `unittest.mock`, no fake `hass` object. Because they have no Home
  Assistant dependency, tests call the real functions with real dataclass
  instances and assert on real return values. This is only possible
  *because* of the module boundary in §3; it is the practical payoff of
  that design choice.
- Tests are loaded via direct file-path import
  (`importlib.util.spec_from_file_location`) rather than package import,
  specifically to avoid pulling in `custom_components/shady/__init__.py`
  (which imports `homeassistant.*`) just to test a dependency-free module.
  This keeps the test environment lightweight (`pytest` only — no
  `pytest-homeassistant-custom-component` needed).
- Because file-path loading yields plain `ModuleType` objects, mypy cannot
  see the real classes on attributes such as `_shading_mod.ShadingFactor` —
  it only sees `Any`. Test files still get full static typing for these
  names via a `TYPE_CHECKING`-only static import that mirrors the runtime
  path (`if TYPE_CHECKING: from shady.shading import ShadingFactor as
  ShadingFactor`). This import is never executed (it runs only under
  static analysis), so it does not reintroduce the `homeassistant`
  dependency the file-path loading was designed to avoid; the runtime
  assignment (`ShadingFactor = _shading_mod.ShadingFactor`) is
  correspondingly guarded with `if not TYPE_CHECKING:` so the two bindings
  never conflict. This is mandatory for any test module that binds a
  dynamically-loaded class to a name used later as a type annotation —
  leaving it untyped cascades into dozens of unrelated
  `attr-defined`/`valid-type` mypy errors on every usage of that name,
  rather than a single fixable root cause.
- Every test class documents the scenario it covers in a docstring or
  comment referencing the worked example in the README where applicable
  (e.g. a test mirroring "tree shades the array between 08:00 and 10:30 in
  winter" from the README's worked example).
- Invariant checks (e.g. `0.0 <= shading_factor <= 1.0` for every sample,
  or "adjusted forecast never exceeds the raw forecast at the same
  timestamp") are asserted explicitly in tests, not just spot-checked
  values — these are the most important correctness guarantees of the
  whole system and are tested as first-class assertions in every scenario
  class.

### 7 — Documentation: ADRs over inline essays

Design rationale lives in `adr/`, not in large module docstrings or inline
comment blocks. Module docstrings stay short (what the module does, 1–3
sentences); the *why* behind non-obvious decisions is captured once in an
ADR and referenced by number from the code (e.g. `# Interpolate linearly
between horizon points (ADR-002)`). This avoids rationale drifting out of
sync with the code, since an ADR is versioned independently and can be
marked `Superseded` if a decision changes, without having to hunt down
every comment that explained it.

### 8 — Error handling

- User-facing errors (config flow validation, e.g. an invalid horizon
  profile or an unreachable forecast entity) return error keys resolved
  via `translations/*.json`, never raw exception text — keeps the UI
  translatable and avoids leaking internals.
- Background failures (forecast refresh, coordinator update) are logged via
  `_LOGGER.exception`/`_LOGGER.warning` and swallowed rather than raised,
  since these run outside a request/response cycle where there is no caller
  to propagate the exception to.
- The pure calculation modules (`sun_geometry.py`, `shading.py`,
  `forecast_adjust.py`) raise no exceptions in their normal operating
  range; they use `min`/`max` clamps (e.g. shading factor clamped to
  `[0.0, 1.0]`) instead of validation errors, because the inputs are
  derived from live sensor/forecast data and configuration that is expected
  to occasionally be noisy rather than invalid.

---

## Consequences

- **Pro:** A new contributor can run four commands
  (`ruff format --check`, `ruff check`, `mypy --strict`, `pytest`) and know
  immediately whether their change meets the bar.
- **Pro:** The pure-logic/HA-glue split makes the sun-position and shading
  math trivially testable and reusable (e.g. it could power a non-HA CLI
  tool or a different forecast source unchanged).
- **Pro:** ADRs prevent "tribal knowledge" about *why* a clamp, an
  interpolation choice, or a suppression exists from living only in a pull
  request that gets buried.
- **Con:** Strict mypy plus per-file suppression configuration is more
  upfront setup than "just ignore HA imports everywhere" — but it means type
  errors in actual business logic are never silently masked by a blanket
  ignore.
