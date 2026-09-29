"""Tests for `http_export.py`'s `ShadyExportCsvView` (ADR-015
§1/§4/§4a, `TASK-0038`).

Top-level, not nested under `tests/diagnostics/` — `http_export.py`
itself is a top-level module, mode-agnostic, not part of the
`diagnostics/` package (ADR-000 §6's 2026-09-27 Amendment, ADR-015 §7).

Not zero-mocking: reuses `test_coordinator.py`'s own hand-written
`homeassistant`-stub harness (same convention
`tests/diagnostics/test_compare_regressions.py` already follows),
extended with `support_ha.py`'s `_install_http_stub()` for
`HomeAssistantView`/`aiohttp.web.Response` — neither package is
actually installed in this project's own dev/test environment
(ADR-000 §6, `tasks/DEPENDENCIES.md`). These tests call a view's own
`get()` method directly with a hand-built fake request, bypassing real
aiohttp routing entirely — `FakeHttp.register_view` (`support_ha.py`)
only ever records the view instance, it never wires up real routes.

The export *content* itself is covered elsewhere
(`tests/diagnostics/test_compare_regressions.py`); this file's own
end-to-end test only confirms the view wires the pieces together.
"""

from __future__ import annotations

import sys
from datetime import timedelta
from typing import Any

from tests import test_coordinator as tc
from tests.diagnostics.test_compare_regressions import (
    _DAY_0,
    _DAY_1,
    _DAY_2,
    _PIN,
    _activate,
    _make_two_string_setup,
    _seed,
)
from tests.support import _load, _run
from tests.support_ha import FakeHomeAssistant, _install_http_stub

# Collection-order guard, see `tc._restore_modules`'s own comment.
tc._restore_modules()
_install_http_stub()
_http_export_mod = _load("http_export.py", "shady.http_export")
ShadyExportCsvView = _http_export_mod.ShadyExportCsvView
_DOMAIN = sys.modules["shady.const"].DOMAIN


class _FakeRequest:
    """Just enough of `aiohttp.web.Request`'s own surface for
    `ShadyExportCsvView.get` — `request.app["hass"]` and
    `request.query.get(...)`. The view's `config_entry_id` URL-path
    segment is passed as a plain positional argument to `get()`
    instead, matching how HA's own view registration calls a handler
    with its path params."""

    def __init__(self, hass: Any, query: dict[str, str]) -> None:
        self.app = {"hass": hass}
        self.query = query


class _SentinelMode:
    """A minimal, duck-typed `DiagnosticMode` stand-in — just
    `key`/`export_csv`, nothing else the view ever touches — used to
    prove the `mode` query parameter (ADR-015 §4a) really bypasses the
    active selection, not merely happens to agree with it."""

    key = "sentinel_mode"

    def export_csv(self, sensor_id: str) -> str | None:
        return f"sentinel:{sensor_id}"


def _with_entry_in_hass_data(coordinator: Any, hass: Any) -> str:
    entry_id: str = coordinator.entry.entry_id
    hass.data[_DOMAIN] = {entry_id: coordinator}
    return entry_id


class TestViewDeclaresAuthRequired:
    """`requires_auth = True` (ADR-015 §1) is declarative — real HA
    auth machinery is out of scope for this suite (ADR-000 §6); this
    only confirms the class attribute a real HA install would enforce."""

    def test_requires_auth_is_true(self) -> None:
        assert ShadyExportCsvView.requires_auth is True


class TestUnresolvableConfigEntryReturnsNotFound:
    def test_unknown_config_entry_id(self) -> None:
        hass = FakeHomeAssistant()
        hass.data[_DOMAIN] = {}
        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {"sensor_id": "0"})

        response = _run(view.get(request, "no-such-entry"))

        assert response.status == 404


class TestModeDefaultsToActiveSelection:
    """Given no `mode` query parameter, When the export is requested,
    Then the view falls back to `coordinator.diagnostic_mode()` — the
    original, still-default behavior (ADR-015 §4)."""

    def test_end_to_end_export_uses_active_mode_by_default(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _seed(hass, tc._ACTUAL_YIELD_ENTITY, {_DAY_0: 500.0, _DAY_1: 500.0, _DAY_2: 500.0})
        _seed(hass, tc._SECOND_ACTUAL_YIELD_ENTITY, {_DAY_0: 300.0, _DAY_1: 300.0, _DAY_2: 300.0})
        coordinator._now = lambda: _PIN + timedelta(minutes=10)
        ok = coordinator.pin_diagnostic_slot(_PIN, now=_PIN + timedelta(minutes=10))
        assert ok
        coordinator.set_active_diagnostic_mode("compare_regressions")
        entry_id = _with_entry_in_hass_data(coordinator, hass)

        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {"sensor_id": "0"})
        response = _run(view.get(request, entry_id))

        assert response.status == 200
        assert response.content_type == "text/csv"
        assert (
            response.headers["Content-Disposition"]
            == 'attachment; filename="compare_regressions_0.csv"'
        )
        assert response.text is not None
        assert response.text.startswith("# diagnostic_mode")

    def test_no_active_mode_and_no_override_returns_404(self) -> None:
        coordinator, hass = _make_two_string_setup()
        # `set_active_diagnostic_mode` never called -- default is "off",
        # never a registered mode (`const.py`'s `DEFAULT_DIAGNOSTIC_MODE`).
        entry_id = _with_entry_in_hass_data(coordinator, hass)

        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {"sensor_id": "0"})
        response = _run(view.get(request, entry_id))

        assert response.status == 404


class TestModeQueryParameterOverride:
    """ADR-015 §4a (2026-09-27 Amendment): an explicit `mode` query
    parameter names any *registered* `DiagnosticMode`, independent of
    `select.py`'s own currently active selection."""

    def test_explicit_mode_overrides_active_selection(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _activate(coordinator)  # active mode is "compare_regressions"
        coordinator._diagnostic_modes["sentinel_mode"] = _SentinelMode()
        entry_id = _with_entry_in_hass_data(coordinator, hass)

        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {"sensor_id": "7", "mode": "sentinel_mode"})
        response = _run(view.get(request, entry_id))

        assert response.status == 200
        assert response.text == "sentinel:7"
        assert (
            response.headers["Content-Disposition"] == 'attachment; filename="sentinel_mode_7.csv"'
        )

    def test_unregistered_mode_returns_404(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _activate(coordinator)
        entry_id = _with_entry_in_hass_data(coordinator, hass)

        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {"sensor_id": "0", "mode": "no-such-mode"})
        response = _run(view.get(request, entry_id))

        assert response.status == 404

    def test_off_is_never_a_registered_mode_key(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _activate(coordinator)
        entry_id = _with_entry_in_hass_data(coordinator, hass)

        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {"sensor_id": "0", "mode": "off"})
        response = _run(view.get(request, entry_id))

        assert response.status == 404


class TestExportCsvNoneBecomesNotFound:
    """Given `mode.export_csv(sensor_id)` returns `None` (an
    unrecognized `sensor_id`, `"sum"`, a string with no baseline, or
    `sensor_id` missing from the query string entirely), When the
    export is requested, Then the view reports `HTTPStatus.NOT_FOUND` —
    no mode-specific branching in the HTTP layer at all (ADR-015 §4)."""

    def test_sum_sensor_id(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _activate(coordinator)
        entry_id = _with_entry_in_hass_data(coordinator, hass)

        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {"sensor_id": "sum"})
        response = _run(view.get(request, entry_id))

        assert response.status == 404

    def test_missing_sensor_id_query_param(self) -> None:
        coordinator, hass = _make_two_string_setup()
        _activate(coordinator)
        entry_id = _with_entry_in_hass_data(coordinator, hass)

        view = ShadyExportCsvView()
        request = _FakeRequest(hass, {})
        response = _run(view.get(request, entry_id))

        assert response.status == 404
