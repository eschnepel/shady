"""`http_export.py` — `ShadyExportCsvView`, a registered `HomeAssistantView`
(ADR-015 §1/§4, `TASK-0038`) serving one diagnosed slot's raw-data CSV
export on `GET /api/shady/{config_entry_id}/export_csv`.

Genuinely mode-agnostic (ADR-015 §4): resolves the config entry's
`ShadyCoordinator` out of `hass.data[DOMAIN]`, resolves *which*
`DiagnosticMode` to export from — the `mode` query parameter if given
(`coordinator.diagnostic_mode_by_key`, ADR-015 §4a's 2026-09-27
Amendment: any *registered* mode, not just the currently active one),
else the coordinator's own currently *configured* (active) mode
(`coordinator.diagnostic_mode()`) — then calls that mode's own
`export_csv(sensor_id)`. Zero knowledge of what any mode's export
contains; `HTTPStatus.NOT_FOUND` for every "nothing to export" case
(unresolvable config entry, unresolvable `mode`, or `export_csv`
returning `None`), indistinguishable from each other by design.

`requires_auth = True` (ADR-015 §1): delegates entirely to Home
Assistant's own session/long-lived-token auth, no credential surface of
its own.

Registered once per `hass`, not once per config entry — see
`__init__.py`'s own registration guard, since the `{config_entry_id}`
URL segment already lets one registration serve every config entry a
`hass` has.
"""

from __future__ import annotations

from http import HTTPStatus
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import ShadyCoordinator


class ShadyExportCsvView(HomeAssistantView):  # type: ignore[misc]
    """One `GET` endpoint, `sensor_id` (required) and `mode` (optional,
    ADR-015 §4a) as query parameters, `config_entry_id` as a URL path
    segment. No mode-specific code here at all (ADR-015 §4) — every
    branch below is either resolving *which* coordinator/mode/export to
    read, or reporting that one of those three could not be resolved.
    """

    url = "/api/shady/{config_entry_id}/export_csv"
    name = "api:shady:export_csv"
    requires_auth = True

    async def get(self, request: web.Request, config_entry_id: str) -> web.Response:
        hass: HomeAssistant = request.app["hass"]
        coordinator: ShadyCoordinator | None = hass.data.get(DOMAIN, {}).get(config_entry_id)
        if coordinator is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)

        mode_key = request.query.get("mode")
        mode = (
            coordinator.diagnostic_mode_by_key(mode_key)
            if mode_key is not None
            else coordinator.diagnostic_mode()
        )
        if mode is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)

        # Missing entirely (not just empty) resolves to "" — deferred
        # to `export_csv`'s own "not one of this mode's own declared
        # sensor_ids()" contract rather than a bespoke bad-request
        # branch here (ADR-015 §4: zero mode-specific validation in the
        # HTTP layer).
        sensor_id = request.query.get("sensor_id", "")
        csv_text = mode.export_csv(sensor_id)
        if csv_text is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)

        return web.Response(
            text=csv_text,
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{mode.key}_{sensor_id}.csv"'},
        )
