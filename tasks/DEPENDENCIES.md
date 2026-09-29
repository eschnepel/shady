# Project Dependencies

> Maintained by the Lead Agent. Workers append entries; never edit existing ones
> without Lead approval. One entry per library — no duplicates.

## numpy 1.26.0 (lower bound)

- **Install:** already declared in `manifest.json`
  (`requirements: ["numpy>=1.26.0"]`) and `pyproject.toml`
  (`[project.dependencies]`) — do not re-add. For local dev:
  `pip install numpy>=1.26.0`.
- **Import:** `import numpy as np`
- **Added by task:** (pre-existing — declared before task-based work began;
  ADR-008 §1 established this pin)
- **Purpose:** batched numeric backend for `regression/`'s four strategies and
  `cache.py`'s shadow array / `get_regression_pools` accessor (ADR-008)

## voluptuous (dev dependency, already declared)

- **Install:** already declared in `pyproject.toml` `[dependency-groups] dev` —
  do not re-add as a runtime dependency. Home Assistant itself provides
  `voluptuous` at runtime for config-flow schema validation; this dev-group
  entry is for local testing only.
- **Import:** `import voluptuous as vol`
- **Added by task:** (pre-existing — declared before task-based work began)
- **Purpose:** config-flow (`config_flow.py`, TASK-0009) schema validation,
  standard Home Assistant pattern

______________________________________________________________________

## homeassistant.components.http (bundled with Home Assistant)

- **Install:** already bundled with Home Assistant — do not install separately.
  Not a real dependency of this project's own dev/test environment either (no
  `homeassistant` package installed here at all, per ADR-000 §6 — hand-rolled
  into `sys.modules` for tests, same as every other `homeassistant.*` surface
  this codebase touches).
- **Import:** `from homeassistant.components.http import HomeAssistantView`
- **Added by task:** TASK-0038
- **Purpose:** `http_export.py`'s one registered view (ADR-015 §1) serving the
  diagnostic-slot CSV export

## aiohttp (bundled with Home Assistant)

- **Install:** already bundled with Home Assistant — do not install separately;
  not installed in this project's own dev/test environment either (same as the
  entry above — `homeassistant.components.http` is the only real consumer, and
  `aiohttp` is that module's own hard dependency, not this project's). Test
  coverage (`tests/support_ha.py`'s `_install_http_stub()`) hand-stubs a minimal
  `aiohttp.web.Response`, the same convention already established for
  `homeassistant.*` itself.
- **Import:** `from aiohttp import web` (`web.Response`)
- **Added by task:** TASK-0038
- **Purpose:** `http_export.py`'s own CSV response (`Content-Type: text/csv`,
  `Content-Disposition: attachment`) — `HomeAssistantView`'s own `json`/
  `json_message` helpers only produce JSON, not a file download

______________________________________________________________________

*No further task-added dependencies. Workers: append below this line, following
the format above, one entry per new library.*
