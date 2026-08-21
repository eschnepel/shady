# Project Dependencies

> Maintained by the Lead Agent. Workers append entries; never edit existing ones
> without Lead approval. One entry per library — no duplicates.

## numpy 1.26.0 (lower bound)
- **Install:** already declared in `manifest.json` (`requirements:
  ["numpy>=1.26.0"]`) and `pyproject.toml`
  (`[project.dependencies]`) — do not re-add. For local dev:
  `pip install numpy>=1.26.0`.
- **Import:** `import numpy as np`
- **Added by task:** (pre-existing — declared before task-based work
  began; ADR-008 §1 established this pin)
- **Purpose:** batched numeric backend for `regression/`'s four
  strategies and `cache.py`'s shadow array / `get_regression_pools`
  accessor (ADR-008)

## voluptuous (dev dependency, already declared)
- **Install:** already declared in `pyproject.toml`
  `[dependency-groups] dev` — do not re-add as a runtime dependency.
  Home Assistant itself provides `voluptuous` at runtime for config-flow
  schema validation; this dev-group entry is for local testing only.
- **Import:** `import voluptuous as vol`
- **Added by task:** (pre-existing — declared before task-based work
  began)
- **Purpose:** config-flow (`config_flow.py`, TASK-0009) schema
  validation, standard Home Assistant pattern

---

*No task-added dependencies yet. Workers: append below this line,
following the format above, one entry per new library.*
