from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace

from ._module_loader import load_module


coordinator = load_module("shady.coordinator", "coordinator.py")


@dataclass
class _FakeProvider:
    entity_id: str
    series: list[tuple[datetime, float]]

    def identify(self) -> str:
        return self.entity_id

    def fetch(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]:
        return [(timestamp, value) for timestamp, value in self.series if start <= timestamp <= end]

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None:
        return [(timestamp, value) for timestamp, value in self.series if timestamp >= now]


class _FakeCache:
    def __init__(self, window_days: int = 28) -> None:
        self.window_days = window_days
        self.validated: dict[str, tuple[int, int | None]] = {}
        self.push_calls: list[tuple[str, dict[int, float], int]] = []
        self.series: dict[str, list[tuple[datetime, float]]] = {}
        self.epoch = datetime(1970, 1, 1)
        self.integral_totals: dict[str, float] = {"pv_energy": 0.0, "fc_energy": 0.0}
        self.last_reset_date = None
        self.intraday_state: dict[str, dict[str, object]] = {}

    def _index_for(self, moment: datetime) -> int:
        return int((moment - self.epoch).total_seconds() // 300)

    def push(self, sensor_id: str, values: dict[int, float], *, not_before_index: int) -> None:
        self.push_calls.append((sensor_id, dict(values), not_before_index))

    def get_integral_total(self, key: str) -> float:
        return self.integral_totals[key]

    def set_integral_total(self, key: str, value: float) -> None:
        self.integral_totals[key] = value

    def reset_integral_totals(self, reset_date):
        self.integral_totals["pv_energy"] = 0.0
        self.integral_totals["fc_energy"] = 0.0
        self.last_reset_date = reset_date

    def get_intraday_state(self, sensor_id: str) -> dict[str, object]:
        return dict(self.intraday_state.get(sensor_id, {}))

    def set_intraday_state(self, sensor_id: str, state: dict[str, object]) -> None:
        self.intraday_state[sensor_id] = dict(state)

    def clear_intraday_state(self, sensor_id: str) -> None:
        self.intraday_state.pop(sensor_id, None)

    def get_time_range(
        self,
        sensor_ids: list[str],
        start: datetime,
        end: datetime,
        on_invalid=0.0,
        group_by: str = "sensor",
    ):
        current = start
        timestamps: list[datetime] = []
        while current <= end:
            timestamps.append(current)
            current += timedelta(minutes=5)

        if group_by == "sensor":
            result: dict[str, list[float]] = {}
            for sensor_id in sensor_ids:
                series = {timestamp: value for timestamp, value in self.series.get(sensor_id, [])}
                result[sensor_id] = [float(series.get(timestamp, 0.0)) for timestamp in timestamps]
            return result

        grouped: list[dict[str, float]] = []
        for timestamp in timestamps:
            row: dict[str, float] = {}
            for sensor_id in sensor_ids:
                series = {sample_timestamp: value for sample_timestamp, value in self.series.get(sensor_id, [])}
                row[sensor_id] = float(series.get(timestamp, 0.0))
            grouped.append(row)
        return grouped


def test_setup_registers_daily_and_provider_listeners(monkeypatch):
    cache = _FakeCache()
    baseline = _FakeProvider("string-1", [(datetime(2026, 8, 21, 12, 0), 10.0)])
    temperature = _FakeProvider("sensor.temp", [(datetime(2026, 8, 21, 12, 0), 21.0)])
    flow = coordinator.ShadyCoordinator(
        SimpleNamespace(
            async_create_task=lambda coro: coro,
            states=SimpleNamespace(
                get=lambda entity_id: SimpleNamespace(state="0", attributes={}),
                async_all=lambda: [],
            ),
        ),
        cache,
        {
            coordinator.CONF_STRINGS: [
                {
                    coordinator.CONF_ID: "string-1",
                    coordinator.CONF_ACTUAL_YIELD_ENTITY_ID: "sensor.actual",
                    coordinator.CONF_CONVERTER_LIMIT: "",
                    coordinator.CONF_TEMPERATURE_COEFFICIENT: -0.4,
                }
            ]
        },
        {"string-1": baseline},
        {"sensor.temp": temperature},
    )

    time_calls: list[tuple[int, int, int]] = []
    state_calls: list[str] = []
    monkeypatch.setattr(
        coordinator,
        "async_track_time_change",
        lambda hass, callback, hour=None, minute=None, second=None: time_calls.append((hour, minute, second))
        or [lambda: None],
    )
    monkeypatch.setattr(
        coordinator,
        "async_track_state_change_event",
        lambda hass, entity_id, callback: state_calls.append(entity_id) or (lambda: None),
    )
    monkeypatch.setattr(flow, "async_refit_models", lambda now=None: asyncio.sleep(0))

    asyncio.run(flow.async_setup())

    assert (0, 1, 0) in time_calls
    assert (0, 0, 0) in time_calls
    assert any(call[1] == list(range(0, 60, 5)) for call in time_calls)
    assert sorted(state_calls) == ["sensor.actual", "sensor.temp", "string-1"]


def test_provider_update_pushes_future_series_and_recomputes(monkeypatch):
    now = datetime(2026, 8, 21, 12, 3)
    cache = _FakeCache()
    provider = _FakeProvider(
        "string-1",
        [
            (datetime(2026, 8, 21, 12, 5), 11.0),
            (datetime(2026, 8, 21, 12, 10), 12.0),
        ],
    )
    flow = coordinator.ShadyCoordinator(
        SimpleNamespace(
            async_create_task=lambda coro: coro,
            states=SimpleNamespace(
                get=lambda entity_id: SimpleNamespace(state="0", attributes={}),
                async_all=lambda: [],
            ),
        ),
        cache,
        {
            coordinator.CONF_STRINGS: [
                {
                    coordinator.CONF_ID: "string-1",
                    coordinator.CONF_ACTUAL_YIELD_ENTITY_ID: "sensor.actual",
                    coordinator.CONF_CONVERTER_LIMIT: "",
                    coordinator.CONF_TEMPERATURE_COEFFICIENT: -0.4,
                }
            ]
        },
        {"string-1": provider},
    )

    recompute_calls: list[datetime] = []

    async def _fake_recompute(current=None):
        recompute_calls.append(current)

    monkeypatch.setattr(flow, "async_recompute_forecasts", _fake_recompute)

    asyncio.run(flow.async_handle_provider_update(provider, now=now))

    assert cache.push_calls == [
        (
            "string-1",
            {
                cache._index_for(datetime(2026, 8, 21, 12, 5)): 11.0,
                cache._index_for(datetime(2026, 8, 21, 12, 10)): 12.0,
            },
            cache._index_for(datetime(2026, 8, 21, 12, 5)),
        )
    ]
    assert recompute_calls == [now]


def test_recompute_limits_output_to_today_remaining_plus_tomorrow(monkeypatch):
    current = datetime(2026, 8, 21, 12, 0)
    cache = _FakeCache()
    series = [
        (datetime(2026, 8, 21, 12, 0), 10.0),
        (datetime(2026, 8, 22, 12, 0), 11.0),
        (datetime(2026, 8, 23, 12, 0), 12.0),
    ]
    baseline = _FakeProvider("string-1", series)
    flow = coordinator.ShadyCoordinator(
        SimpleNamespace(
            async_create_task=lambda coro: coro,
            states=SimpleNamespace(
                get=lambda entity_id: SimpleNamespace(state="0", attributes={}),
                async_all=lambda: [],
            ),
        ),
        cache,
        {
            coordinator.CONF_STRINGS: [
                {
                    coordinator.CONF_ID: "string-1",
                    coordinator.CONF_ACTUAL_YIELD_ENTITY_ID: "sensor.actual",
                    coordinator.CONF_CONVERTER_LIMIT: "",
                    coordinator.CONF_TEMPERATURE_COEFFICIENT: -0.4,
                }
            ]
        },
        {"string-1": baseline},
    )
    flow._strings[0].models = {0: SimpleNamespace(predict=lambda forecast: (forecast, 1.0))}  # noqa: SLF001
    def _fake_adjust_forecast(baseline_series, models, **kwargs):
        result = list(baseline_series)
        if kwargs.get("return_raw"):
            return result, result
        return result

    monkeypatch.setattr(coordinator, "adjust_forecast", _fake_adjust_forecast)

    asyncio.run(flow.async_recompute_forecasts(now=current))

    assert [timestamp for timestamp, _ in flow.forecasts["string-1"]] == [
        datetime(2026, 8, 21, 12, 0),
        datetime(2026, 8, 22, 12, 0),
    ]


def test_recompute_applies_intraday_blending_and_updates_snapshot():
    current = datetime(2026, 8, 21, 12, 0)
    cache = _FakeCache()
    cache.series["sensor.actual"] = [
        (datetime(2026, 8, 21, 11, 55), 11.0),
        (datetime(2026, 8, 21, 12, 0), 11.0),
    ]
    cache.series["string-1"] = [
        (datetime(2026, 8, 21, 11, 55), 10.0),
        (datetime(2026, 8, 21, 12, 0), 10.0),
    ]
    provider = _FakeProvider(
        "string-1",
        [
            (datetime(2026, 8, 21, 12, 0), 100.0),
            (datetime(2026, 8, 21, 12, 5), 100.0),
        ],
    )
    flow = coordinator.ShadyCoordinator(
        SimpleNamespace(
            async_create_task=lambda coro: coro,
            states=SimpleNamespace(
                get=lambda entity_id: SimpleNamespace(state="0", attributes={}),
                async_all=lambda: [],
            ),
        ),
        cache,
        {
            coordinator.CONF_STRINGS: [
                {
                    coordinator.CONF_ID: "string-1",
                    coordinator.CONF_ACTUAL_YIELD_ENTITY_ID: "sensor.actual",
                    coordinator.CONF_CONVERTER_LIMIT: "",
                    coordinator.CONF_TEMPERATURE_COEFFICIENT: -0.4,
                    coordinator.CONF_INTRADAY_CORRECTION_MODE: "blending",
                    coordinator.CONF_WINDOW_SLOTS: 2,
                    coordinator.CONF_RAMP_SLOTS: 2,
                }
            ]
        },
        {"string-1": provider},
    )
    flow._strings[0].models = {144: SimpleNamespace(predict=lambda forecast: (60.0, 1.0))}  # noqa: SLF001
    flow.forecasts_raw["string-1"] = [
        (datetime(2026, 8, 21, 12, 0), 40.0),
        (datetime(2026, 8, 21, 12, 5), 40.0),
    ]

    asyncio.run(flow.async_recompute_forecasts(now=current))

    assert flow.forecasts_raw["string-1"][0][1] == 51.5
    assert flow.get_intraday_snapshot("string-1")["intraday_state"] == "blending"
    assert flow.get_intraday_snapshot("string-1")["intraday_blend_active"] is True


def test_midnight_reset_clears_intraday_state(monkeypatch):
    cache = _FakeCache()
    flow = coordinator.ShadyCoordinator(
        SimpleNamespace(
            async_create_task=lambda coro: coro,
            states=SimpleNamespace(get=lambda entity_id: None, async_all=lambda: []),
        ),
        cache,
        {coordinator.CONF_STRINGS: []},
        {},
    )
    cache.intraday_state["string-1"] = {"mode": "blending"}
    flow.intraday_snapshot["string-1"] = {"intraday_state": "blending"}
    monkeypatch.setattr(flow, "async_refresh_aggregates", lambda now=None: asyncio.sleep(0))

    asyncio.run(flow._async_midnight_reset(None))

    assert cache.intraday_state == {}
    assert flow.intraday_snapshot == {}


def test_temperature_model_uses_direct_cell_override(monkeypatch):
    current = datetime(2026, 8, 21, 12, 0)
    cache = _FakeCache()
    cache.series["sensor.cell_temp"] = [
        (datetime(2026, 8, 19, 12, 0), 18.0),
        (datetime(2026, 8, 19, 12, 5), 19.0),
        (datetime(2026, 8, 20, 12, 0), 20.0),
        (datetime(2026, 8, 20, 12, 5), 21.0),
    ]
    baseline = _FakeProvider(
        "string-1",
        [
            (datetime(2026, 8, 21, 12, 0), 100.0),
            (datetime(2026, 8, 21, 12, 5), 100.0),
        ],
    )
    temp_provider = _FakeProvider(
        "weather.home",
        [
            (datetime(2026, 8, 19, 12, 0), 18.0),
            (datetime(2026, 8, 19, 12, 5), 19.0),
            (datetime(2026, 8, 20, 12, 0), 20.0),
            (datetime(2026, 8, 20, 12, 5), 21.0),
            (datetime(2026, 8, 21, 12, 0), 22.0),
            (datetime(2026, 8, 21, 12, 5), 23.0),
        ],
    )
    flow = coordinator.ShadyCoordinator(
        SimpleNamespace(
            async_create_task=lambda coro: coro,
            states=SimpleNamespace(
                get=lambda entity_id: SimpleNamespace(state="0", attributes={}),
                async_all=lambda: [],
            ),
        ),
        cache,
        {
            coordinator.CONF_WINDOW_DAYS: 2,
            coordinator.CONF_TEMPERATURE_REGRESSION_METHOD: "linear",
            "max_uplift_c": 25.0,
            coordinator.CONF_STRINGS: [
                {
                    coordinator.CONF_ID: "string-1",
                    coordinator.CONF_ACTUAL_YIELD_ENTITY_ID: "sensor.actual",
                    coordinator.CONF_CONVERTER_LIMIT: "",
                    coordinator.CONF_TEMPERATURE_COEFFICIENT: -0.004,
                    coordinator.CONF_TEMPERATURE_AWARE: True,
                    coordinator.CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID: "sensor.cell_temp",
                }
            ],
            coordinator.CONF_TEMPERATURE_SOURCE_ENTITY_ID: "weather.home",
        },
        {"string-1": baseline},
        {"weather.home": temp_provider},
    )
    captured: dict[str, dict[datetime, float] | None] = {}

    def _fake_adjust_forecast(baseline_series, models, **kwargs):
        if kwargs.get("target_temperatures") is not None:
            captured["target_temperatures"] = kwargs.get("target_temperatures")
        if kwargs.get("return_raw"):
            return list(baseline_series), list(baseline_series)
        return list(baseline_series)

    monkeypatch.setattr(coordinator, "adjust_forecast", _fake_adjust_forecast)

    asyncio.run(flow.async_refit_models(now=current))
    asyncio.run(flow.async_recompute_forecasts(now=current))

    assert captured["target_temperatures"] == {
        datetime(2026, 8, 21, 12, 0): 22.0,
        datetime(2026, 8, 21, 12, 5): 23.0,
    }


def test_temperature_model_uplifts_weather_tier_targets(monkeypatch):
    current = datetime(2026, 8, 21, 12, 0)
    cache = _FakeCache()
    cache.series["weather.ambient"] = [
        (datetime(2026, 8, 19, 12, 0), 18.0),
        (datetime(2026, 8, 19, 12, 5), 19.0),
        (datetime(2026, 8, 20, 12, 0), 20.0),
        (datetime(2026, 8, 20, 12, 5), 21.0),
    ]
    baseline = _FakeProvider(
        "string-1",
        [
            (datetime(2026, 8, 21, 12, 0), 100.0),
            (datetime(2026, 8, 21, 12, 5), 100.0),
        ],
    )
    temp_provider = _FakeProvider(
        "weather.home",
        [
            (datetime(2026, 8, 19, 12, 0), 18.0),
            (datetime(2026, 8, 19, 12, 5), 19.0),
            (datetime(2026, 8, 20, 12, 0), 20.0),
            (datetime(2026, 8, 20, 12, 5), 21.0),
            (datetime(2026, 8, 21, 12, 0), 22.0),
            (datetime(2026, 8, 21, 12, 5), 23.0),
        ],
    )
    flow = coordinator.ShadyCoordinator(
        SimpleNamespace(
            async_create_task=lambda coro: coro,
            states=SimpleNamespace(
                get=lambda entity_id: SimpleNamespace(state="0", attributes={}),
                async_all=lambda: [],
            ),
        ),
        cache,
        {
            coordinator.CONF_WINDOW_DAYS: 2,
            coordinator.CONF_TEMPERATURE_REGRESSION_METHOD: "linear",
            "max_uplift_c": 25.0,
            coordinator.CONF_STRINGS: [
                {
                    coordinator.CONF_ID: "string-1",
                    coordinator.CONF_ACTUAL_YIELD_ENTITY_ID: "sensor.actual",
                    coordinator.CONF_CONVERTER_LIMIT: "",
                    coordinator.CONF_TEMPERATURE_COEFFICIENT: -0.004,
                    coordinator.CONF_TEMPERATURE_AWARE: True,
                    coordinator.CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID: "weather.ambient",
                    "rated_dc_capacity": "1000",
                }
            ],
            coordinator.CONF_TEMPERATURE_SOURCE_ENTITY_ID: "weather.home",
        },
        {"string-1": baseline},
        {"weather.home": temp_provider},
    )
    captured: dict[str, dict[datetime, float] | None] = {}

    def _fake_adjust_forecast(baseline_series, models, **kwargs):
        if kwargs.get("target_temperatures") is not None:
            captured["target_temperatures"] = kwargs.get("target_temperatures")
        if kwargs.get("return_raw"):
            return list(baseline_series), list(baseline_series)
        return list(baseline_series)

    monkeypatch.setattr(coordinator, "adjust_forecast", _fake_adjust_forecast)

    asyncio.run(flow.async_refit_models(now=current))
    asyncio.run(flow.async_recompute_forecasts(now=current))

    assert captured["target_temperatures"] == {
        datetime(2026, 8, 21, 12, 0): 24.5,
        datetime(2026, 8, 21, 12, 5): 25.5,
    }
