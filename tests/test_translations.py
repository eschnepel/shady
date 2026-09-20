"""Tests for `translations/en.json`/`de.json` content vs. `config_flow.py`'s
actual schema keys (ADR-010, `TASK-0035`).

`config_flow.py` is HA-facing (see `test_config_flow.py`'s module
docstring) so loading it needs the same small, hand-written, real
(non-`Mock`) `homeassistant` stand-in that file already establishes —
this file's own `ConfigFlow` stub class is duplicated here rather than
imported from it (genuinely narrower than what `test_config_flow.py`
needs, matching this project's per-file self-contained-harness
convention: each test file owns its load order rather than depending on
another test file's module-level side effects); `_callback`/
`FakeConfigEntry` are shared from `tests.support_ha` instead, since those
two are identical to what every `FakeHomeAssistant`-based file already
needs.

This file does not re-drive the flow end to end (that is
`test_config_flow.py`'s job) — it only calls the schema-building
functions directly with empty `candidates`/`defaults`/`strings` (fine for
this purpose: every field these functions build always specifies its own
`default=`, so an empty input dict never changes *which* fields exist,
only what their defaults happen to be) to read back each step's real
field-key set, and compares that against the translation files' `data`
labels. There is one exception: `reconfigure` is a *menu* step (no
`data` block at all, real HA's `async_show_menu` convention) — checked
separately, against its `menu_options` instead.

`ShadyOptionsFlow` no longer exists (`TASK-0035`, ADR-010) — there is no
`options` translation section any more; every step, including the ones a
reconfigure session reaches, lives under the one `config` section, since
`async_step_reconfigure` dispatches to the exact same `async_step_*`
methods `async_step_user`'s linear sequence does.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType
from typing import Any

from tests.support import _SHADY_DIR, _load
from tests.support_ha import FakeConfigEntry, _callback


class _FlowHandlerBase:
    """Real (non-Mock) stand-in for the slice of `homeassistant.data_
    entry_flow.FlowHandler` `config_flow.py` touches at class-definition
    time / module import time (nothing here is actually called by this
    file — the schema-building functions never reach into `self`)."""


class _ConfigFlow(_FlowHandlerBase):
    def __init_subclass__(cls, *, domain: str | None = None, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        cls._domain = domain  # type: ignore[attr-defined]


class _EntitySelector:
    """Real (non-Mock) stand-in for `homeassistant.helpers.selector.
    EntitySelector`. `voluptuous.Schema` requires every value to be
    callable at *compile* time (not just when actually validating a
    submission) — this file never submits a value through it, but
    `vol.Schema(...)` still needs `__call__` to exist to compile at
    all, so a passthrough is enough."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}

    def __call__(self, value: Any) -> Any:
        return value


def _install_ha_stub() -> None:
    ha = ModuleType("homeassistant")
    ha_core = ModuleType("homeassistant.core")
    ha_config_entries = ModuleType("homeassistant.config_entries")
    ha_helpers = ModuleType("homeassistant.helpers")
    ha_helpers.__path__ = []  # mark as a package
    ha_helpers_selector = ModuleType("homeassistant.helpers.selector")

    ha_core.callback = _callback  # type: ignore[attr-defined]
    ha_config_entries.ConfigFlow = _ConfigFlow  # type: ignore[attr-defined]
    ha_config_entries.ConfigEntry = FakeConfigEntry  # type: ignore[attr-defined]
    ha_helpers_selector.EntitySelector = _EntitySelector  # type: ignore[attr-defined]
    ha_helpers_selector.EntitySelectorConfig = lambda **kw: dict(kw)  # type: ignore[attr-defined]
    ha_helpers.selector = ha_helpers_selector  # type: ignore[attr-defined]

    ha.core = ha_core  # type: ignore[attr-defined]
    ha.config_entries = ha_config_entries  # type: ignore[attr-defined]
    ha.helpers = ha_helpers  # type: ignore[attr-defined]

    sys.modules["homeassistant"] = ha
    sys.modules["homeassistant.core"] = ha_core
    sys.modules["homeassistant.config_entries"] = ha_config_entries
    sys.modules["homeassistant.helpers"] = ha_helpers
    sys.modules["homeassistant.helpers.selector"] = ha_helpers_selector
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
_load("regression/base.py", "shady.regression.base")
_load("const.py", "shady.const")
_load("cache.py", "shady.cache")
_load("providers/discovery.py", "shady.providers.discovery")
_flow_mod = _load("config_flow.py", "shady.config_flow")

# Every schema-building function this task's "Consumed Interfaces" names
# — an empty `candidates` list / empty `defaults` dict is fine for
# reading back `vol.Schema(...).schema.keys()` (see module docstring).
_BASELINE_KEYS = frozenset(str(k) for k in _flow_mod._baseline_schema([], {}).schema)
_STRINGS_KEYS = frozenset(str(k) for k in _flow_mod._strings_schema([]).schema)
_STRING_SETTINGS_HUB_KEYS = frozenset(str(k) for k in _flow_mod._hub_schema({}).schema)
_STRING_SETTINGS_EDIT_KEYS = frozenset(
    str(k) for k in _flow_mod._string_settings_edit_schema([], {}).schema
)
_REGRESSION_TUNING_KEYS = frozenset(str(k) for k in _flow_mod._regression_tuning_schema({}).schema)
_ADVANCED_OPTIONAL_KEYS = frozenset(str(k) for k in _flow_mod._advanced_optional_schema({}).schema)

# Every `data`-bearing step. `reconfigure` is deliberately excluded here
# — it is a menu step with no `data` block at all, checked separately
# below against its own `menu_options`.
_STEP_KEYS: dict[str, frozenset[str]] = {
    "baseline": _BASELINE_KEYS,
    "strings": _STRINGS_KEYS,
    "string_settings_hub": _STRING_SETTINGS_HUB_KEYS,
    "string_settings_edit": _STRING_SETTINGS_EDIT_KEYS,
    "regression_tuning": _REGRESSION_TUNING_KEYS,
    "advanced_optional": _ADVANCED_OPTIONAL_KEYS,
}

_MENU_STEP_ID = "reconfigure"
_MENU_OPTIONS = frozenset(
    {"baseline", "strings", "regression_tuning", "advanced_optional", "finish"}
)

_TRANSLATIONS_DIR = _SHADY_DIR / "translations"
_LANGUAGES = ("en", "de")


def _load_translation(language: str) -> dict[str, Any]:
    path = _TRANSLATIONS_DIR / f"{language}.json"
    with path.open(encoding="utf-8") as handle:
        result: dict[str, Any] = json.load(handle)
        return result


_TRANSLATIONS: dict[str, dict[str, Any]] = {
    language: _load_translation(language) for language in _LANGUAGES
}


def test_every_schema_key_has_a_translation_label() -> None:
    """Every real field key each `data`-bearing step's schema defines
    must have a non-empty label in `config.step.<id>.data`, in both
    languages (the durable, future-proof version of this task's
    cross-check — a manual reading of the JSON files is not durable
    against a later field rename or addition, this test is)."""
    missing: list[str] = []
    for language in _LANGUAGES:
        translation = _TRANSLATIONS[language]
        for step_id, keys in _STEP_KEYS.items():
            data = translation["config"]["step"][step_id]["data"]
            for key in keys:
                label = data.get(key)
                if not isinstance(label, str) or not label.strip():
                    missing.append(f"{language}.json: config.step.{step_id}.data.{key}")
    assert not missing, "Missing/empty translation label(s):\n" + "\n".join(missing)


def test_reconfigure_menu_options_have_translation_labels() -> None:
    """The `reconfigure` menu step's `menu_options` match exactly the
    five documented sections, each with a non-empty label, in both
    languages."""
    for language in _LANGUAGES:
        menu_options = _TRANSLATIONS[language]["config"]["step"][_MENU_STEP_ID]["menu_options"]
        assert set(menu_options) == _MENU_OPTIONS, (
            f"{language}.json: config.step.{_MENU_STEP_ID}.menu_options "
            f"key set mismatch: {sorted(menu_options)}"
        )
        for option, label in menu_options.items():
            assert isinstance(label, str) and label.strip(), (
                f"{language}.json: config.step.{_MENU_STEP_ID}.menu_options.{option} "
                "is missing/empty"
            )


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
    that isn't tied to a real schema field at all — a leftover, a typo'd
    duplicate, a future non-schema string — which the schema-driven
    check above cannot see either way."""
    en_keys = _flatten_keys(_TRANSLATIONS["en"])
    de_keys = _flatten_keys(_TRANSLATIONS["de"])
    only_in_en = en_keys - de_keys
    only_in_de = de_keys - en_keys
    assert not only_in_en, f"Keys only in en.json: {sorted(only_in_en)}"
    assert not only_in_de, f"Keys only in de.json: {sorted(only_in_de)}"


def test_every_step_has_a_real_title_and_description() -> None:
    """Every `config.step.*` entry — the `data`-bearing steps and the
    `reconfigure` menu step alike — must have a real, non-placeholder
    `title` and `description`."""
    for language in _LANGUAGES:
        translation = _TRANSLATIONS[language]
        for step_id in (*_STEP_KEYS, _MENU_STEP_ID):
            step = translation["config"]["step"][step_id]
            for field in ("title", "description"):
                value = step.get(field)
                assert isinstance(value, str) and value.strip(), (
                    f"{language}.json: config.step.{step_id}.{field} is missing/empty"
                )


def test_no_leftover_placeholder_wording() -> None:
    """No literal "Placeholder" or "to be defined" wording remains
    anywhere in either translation file."""
    for language in _LANGUAGES:
        raw = json.dumps(_TRANSLATIONS[language])
        assert "Placeholder" not in raw
        assert "to be defined" not in raw


def test_no_options_section_and_error_section_is_untouched() -> None:
    """`ShadyOptionsFlow` no longer exists (`TASK-0035`) — there is no
    `options` translation section any more. `config_flow.py` never
    passes `errors=` to `async_show_form` (no `vol.Invalid`-driven error
    path exists), so `config.error` stays empty; `config.abort` is not
    empty any more, though — `async_update_reload_and_abort` always
    produces `reason="reconfigure_successful"`, which needs exactly one
    real translated string."""
    for language in _LANGUAGES:
        translation = _TRANSLATIONS[language]
        assert "options" not in translation
        assert translation["config"]["error"] == {}
        abort = translation["config"]["abort"]
        assert set(abort) == {"reconfigure_successful"}
        assert (
            isinstance(abort["reconfigure_successful"], str)
            and abort["reconfigure_successful"].strip()
        )


def test_string_settings_edit_wording_does_not_imply_conditional_visibility() -> None:
    """`_string_settings_edit_schema`'s own docstring is explicit: every
    field is always shown together; which of them actually applies is
    resolved downstream from the *stored* data, not by dynamically
    hiding fields in this static form (ADR-010's `string_settings_edit`
    note: no separate "configure advanced corrections?" gate). This
    task's wording must not contradict that by implying a field
    appears/disappears — phrases like "only shown if" or "only visible
    when" would."""
    for language in _LANGUAGES:
        raw = json.dumps(_TRANSLATIONS[language]).lower()
        assert "only shown" not in raw
        assert "only visible" not in raw
