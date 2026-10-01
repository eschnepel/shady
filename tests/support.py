"""Generic, non-HA test support shared by every test file (ADR-000 §6).

`_load`/`_SHADY_DIR` let a test file import a `custom_components/shady/`
module by direct file path rather than as an installed package, so
`custom_components/shady/__init__.py` (which imports `homeassistant.*`)
is never pulled in just to test a dependency-free module — the same
reason every zero-mocking-tier test file, and every HA-dependent one
that hand-stubs `homeassistant.*` instead of installing it, needs this.
`_run` is the matching `asyncio.run()` wrapper the HA-dependent files
use to drive coroutine-returning methods synchronously in a plain
`def test_...` function.

This module was extracted from 22 near-identical copies across
`tests/*.py` — every one of them defined its own byte-identical `_load`/
`_SHADY_DIR`, and 6 their own byte-identical `_run`. Deliberately
excludes anything Home-Assistant-specific (the hand-written
`homeassistant` stub, `Fake*` classes) — see `support_ha.py` for that;
a pure-tier test file that never touches `homeassistant.*` should not
have to import a module named after it.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _run(coro: Any) -> Any:
    return asyncio.run(coro)
