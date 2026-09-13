"""Tests for TASK-0019: `translations/en.json`/`de.json` content vs.
`config_flow.py`'s actual schema keys (ADR-010, ADR-000).

`config_flow.py` is HA-facing (see `test_config_flow.py`'s module
docstring) so loading it needs the same small, hand-written, real
(non-`Mock`) `homeassistant` stand-in that file already establishes —
duplicated here rather than imported from it, matching this project's
per-file self-contained-harness convention (each test file owns its
load order rather than depending on another test file's module-level
side effects).

One cross-file subtlety this file must respect even though it doesn't
use it directly: five other test files (`test_button.py`,
`test_coordinator.py`, `test_init.py`, `test_sensor_aggregates.py`,
`test_sensor_forecast.py`) install their own `homeassistant
.config_entries` stub at *their* collection time, then re-fetch
`sys.modules["homeassistant.config_entries"].ConfigEntry` *dynamically,
at test-run time* (not a name bound at collection time) inside their
own `_make_entry`/`_make_config_entry` helpers. Because pytest collects
every test file (running all module-level code, including this file's)
before running any test function, whichever such stub was installed
*last* in file-collection order is the one every one of those five
files' dynamic lookups actually gets at run time — so all five,
independently, install a byte-for-byte-identical `FakeConfigEntry
(entry_id, data)` two-positional-argument shape, making them mutually
interchangeable no matter which one ends up "last". This file is
collected after all five (alphabetically), so it must keep that same
shape for its own `ConfigEntry` stub too, even though this file's own
tests never construct one — a differently-shaped stub here would
silently break those five files' `_make_entry` calls the moment this
file exists, with the failure surfacing in files that look completely
unrelated to translations.

This file does not re-drive the flow end to end (that is
`test_config_flow.py`'s job) — it only calls the three private
schema-building functions directly with empty `candidates`/`defaults`
(explicitly documented as fine for this purpose in this task's
"Consumed Interfaces") to read back each step's real field-key set, and
compares that against the translation files' `data` labels. The fourth
step, `add_another`, has no dedicated schema-building function — its
single `"add_another"` field is built inline, identically, in both
`ShadyConfigFlow.async_step_add_another` and
`ShadyOptionsFlow.async_step_add_another` — so it is checked directly
as a hard-coded one-key set rather than one this file can read back
from a function call.
"""

from __future__ import annotations

import importlib.util
import json
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


class _FlowHandlerBase:
    """Real (non-Mock) stand-in for the slice of `homeassistant.data_
    entry_flow.FlowHandler` `config_flow.py` touches at class-definition
    time / module import time (nothing here is actually called by this
    file — the schema-building functions never reach into `self`)."""


class _ConfigFlow(_FlowHandlerBase):
    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._domain = domain  # type: ignore[attr-defined]


class _OptionsFlow(_FlowHandlerBase):
    pass


class _ConfigEntry:
    """Matches the exact `(entry_id, data)` shape `test_button.py`,
    `test_coordinator.py`, `test_init.py`, `test_sensor_aggregates.py`,
    and `test_sensor_forecast.py` each independently install — see this
    module's docstring for why this file must match it even though it
    is never constructed here."""

    def __init__(self, entry_id: str, data: dict[str, Any]) -> None:
        self.entry_id = entry_id
        self.data = data


def _callback(func: Any) -> Any:
    return func


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")

    ha_core.callback = _callback  # type: ignore[attr-defined]
    ha_config_entries.ConfigFlow = _ConfigFlow  # type: ignore[attr-defined]
    ha_config_entries.OptionsFlow = _OptionsFlow  # type: ignore[attr-defined]
    ha_config_entries.ConfigEntry = _ConfigEntry  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    # `homeassistant.data_entry_flow` deliberately not stubbed:
    # `config_flow.py` only imports `FlowResult` from it under `if
    # TYPE_CHECKING:`, and with `from __future__ import annotations`
    # active every annotation using it is a deferred string, never
    # evaluated at runtime — so the module import is never actually
    # executed when this file `exec_module`s `config_flow.py` below.


_install_ha_stub()

# Same multi-module load-order convention `test_config_flow.py` already
# relies on: providers/base.py, providers/normalize.py,
# providers/discovery.py must be registered under their real dotted
# names before config_flow.py, which does `from .providers.discovery
# import ...`.
_load("providers/base.py", "shady.providers.base")
_load("providers/normalize.py", "shady.providers.normalize")
_load("providers/discovery.py", "shady.providers.discovery")
_load("const.py", "shady.const")
_flow_mod = _load("config_flow.py", "shady.config_flow")

# The three schema-building functions this task's "Consumed Interfaces"
# names — an empty candidates list / empty defaults dict is explicitly
# documented there as fine for reading back `vol.Schema(...).schema
# .keys()`.
_SETTINGS_KEYS = frozenset(str(k) for k in _flow_mod._settings_schema([], {}).schema)
_ADD_STRING_KEYS = frozenset(str(k) for k in _flow_mod._add_string_schema([], {}).schema)
_ADD_STRING_ADVANCED_KEYS = frozenset(
    str(k) for k in _flow_mod._add_string_advanced_schema({}).schema
)
# No schema-building function exists for this step (built inline,
# identically, in both flow classes) — see module docstring.
_ADD_ANOTHER_KEYS = frozenset({"add_another"})

_STEP_KEYS: dict[str, frozenset[str]] = {
    "settings": _SETTINGS_KEYS,
    "add_string": _ADD_STRING_KEYS,
    "add_string_advanced": _ADD_STRING_ADVANCED_KEYS,
    "add_another": _ADD_ANOTHER_KEYS,
}

_TRANSLATIONS_DIR = _SHADY_DIR / "translations"
_LANGUAGES = ("en", "de")
_SECTIONS = ("config", "options")


def _load_translation(language: str) -> dict[str, Any]:
    path = _TRANSLATIONS_DIR / f"{language}.json"
    with path.open(encoding="utf-8") as handle:
        result: dict[str, Any] = json.load(handle)
        return result


_TRANSLATIONS: dict[str, dict[str, Any]] = {
    language: _load_translation(language) for language in _LANGUAGES
}


def test_every_schema_key_has_a_translation_label() -> None:
    """Every real field key `config_flow.py`'s schemas define must have
    a non-empty label in both `config.step.<id>.data` and
    `options.step.<id>.data`, in both languages (the durable,
    future-proof version of this task's cross-check — a manual reading
    of the JSON files is not durable against a later field rename or
    addition, this test is)."""
    missing: list[str] = []
    for language in _LANGUAGES:
        translation = _TRANSLATIONS[language]
        for section in _SECTIONS:
            for step_id, keys in _STEP_KEYS.items():
                data = translation[section]["step"][step_id]["data"]
                for key in keys:
                    label = data.get(key)
                    if not isinstance(label, str) or not label.strip():
                        missing.append(f"{language}.json: {section}.step.{step_id}.data.{key}")
    assert not missing, "Missing/empty translation label(s):\n" + "\n".join(missing)


def _flatten_keys(data: Any, prefix: str = "") -> set[str]:
    """Recursively collect every dict node's dotted key path — the
    structural key set only, never the (necessarily different,
    per-language) string values themselves."""
    keys: set[str] = set()
    if isinstance(data, dict):
        for key, value in data.items():
            path = f"{prefix}.{key}" if prefix else key
            keys.add(path)
            keys |= _flatten_keys(value, path)
    return keys


def test_en_and_de_have_identical_key_sets() -> None:
    """Independent of and complementary to
    `test_every_schema_key_has_a_translation_label` above (which only
    ever iterates schema-derived keys, in one direction): directly
    compares the two translation files' own flattened key sets for
    equality, both directions. Catches a key added to one language file
    that isn't tied to a real schema field at all — a leftover, a
    typo'd duplicate, a future non-schema string — which the
    schema-driven check above cannot see either way. This is the same
    manual comparison `AUDIT-0010` performed by hand; this test makes it
    durable."""
    en_keys = _flatten_keys(_TRANSLATIONS["en"])
    de_keys = _flatten_keys(_TRANSLATIONS["de"])
    only_in_en = en_keys - de_keys
    only_in_de = de_keys - en_keys
    assert not only_in_en, f"Keys only in en.json: {sorted(only_in_en)}"
    assert not only_in_de, f"Keys only in de.json: {sorted(only_in_de)}"


def test_every_step_has_a_real_title_and_description() -> None:
    """Every `config.step.*`/`options.step.*` entry must have a real,
    non-placeholder `title` and `description` — no literal "Placeholder"
    or "to be defined" wording left over from the Phase-0 stub content
    this task replaces."""
    for language in _LANGUAGES:
        translation = _TRANSLATIONS[language]
        for section in _SECTIONS:
            for step_id in _STEP_KEYS:
                step = translation[section]["step"][step_id]
                for field in ("title", "description"):
                    value = step.get(field)
                    assert isinstance(value, str) and value.strip(), (
                        f"{language}.json: {section}.step.{step_id}.{field} is missing/empty"
                    )


def test_no_leftover_placeholder_wording() -> None:
    """No literal "Placeholder" or "to be defined" wording remains
    anywhere in either translation file (English wording specifically,
    since the original placeholder text used those exact English words
    in both files — see this task's Goal)."""
    for language in _LANGUAGES:
        raw = json.dumps(_TRANSLATIONS[language])
        assert "Placeholder" not in raw
        assert "to be defined" not in raw


def test_config_and_options_error_sections_are_untouched() -> None:
    """`config_flow.py` never passes `errors=` to `async_show_form`
    today (no `vol.Invalid`-driven error path exists) — this task does
    not invent error-key translations for a validation UX that does not
    exist in the code yet; `config.error`/`config.abort`/`options.error`
    stay empty."""
    for language in _LANGUAGES:
        translation = _TRANSLATIONS[language]
        assert translation["config"]["error"] == {}
        assert translation["config"]["abort"] == {}
        assert translation["options"]["error"] == {}


def test_add_string_advanced_wording_does_not_imply_conditional_visibility() -> None:
    """`_add_string_advanced_schema`'s own docstring is explicit: all
    four fields are always shown together; which of them actually
    applies is resolved downstream from the *stored* data, not by
    dynamically hiding fields in this static form. This task's wording
    must not contradict that by implying a field appears/disappears —
    phrases like "only shown if" or "only visible when" would."""
    for language in _LANGUAGES:
        raw = json.dumps(_TRANSLATIONS[language]).lower()
        assert "only shown" not in raw
        assert "only visible" not in raw
