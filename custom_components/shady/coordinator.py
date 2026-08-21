"""Coordinator core for Shady."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import numpy as np

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.util import dt as dt_util

from .aggregation import (
    build_day_slot_timestamps,
    diagnostic_accuracy,
    intraday_correction_factor,
    ramp_weight,
    sum_slot_rows,
    total_energy_from_series,
)
from .cache import ShadyCache
from .const import (
    CONF_ACTUAL_YIELD_ENTITY_ID,
    CONF_CONVERTER_LIMIT,
    CONF_MAX_UPLIFT_C,
    CONF_INTRADAY_CORRECTION_CUTOFF,
    CONF_INTRADAY_CORRECTION_MODE,
    CONF_ID,
    CONF_REGRESSION_METHOD,
    CONF_RAMP_SLOTS,
    CONF_STRINGS,
    CONF_TEMPERATURE_COEFFICIENT,
    CONF_TEMPERATURE_AWARE,
    CONF_TEMPERATURE_SOURCE_ENTITY_ID,
    CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID,
    CONF_TEMPERATURE_REGRESSION_METHOD,
    CONF_RATED_DC_CAPACITY,
    CONF_WINDOW_SLOTS,
    CONF_WINDOW_DAYS,
    DEFAULT_REGRESSION_METHOD,
    DEFAULT_INTRADAY_CORRECTION_CUTOFF,
    DEFAULT_INTRADAY_CORRECTION_MODE,
    DEFAULT_TEMPERATURE_REGRESSION_METHOD,
    DEFAULT_RAMP_SLOTS,
    DEFAULT_WINDOW_SLOTS,
)
from .forecast_adjust import adjust_forecast
from .providers.base import ProviderBase, state_to_three_state_value
from .regression import kernel, linear, wls2, wls3
from .regression.base import RegressionModel
from .yield_correction import estimate_cell_temperature_from_ambient

__all__ = ["ProviderProtocol", "ShadyCoordinator"]


class ProviderProtocol(Protocol):
    """Minimal provider interface required by the coordinator."""

    def identify(self) -> str | None: ...

    def fetch(self, start: datetime, end: datetime) -> list[tuple[datetime, float]]: ...

    def forward(self, now: datetime) -> list[tuple[datetime, float]] | None: ...


@dataclass
class _StringState:
    config: dict[str, Any]
    models: dict[int, RegressionModel] = field(default_factory=dict)
    forecast: list[tuple[datetime, float]] = field(default_factory=list)


def _slot_index(moment: datetime) -> int:
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return (moment.hour * 60 + moment.minute) // 5


def _ceil_to_slot(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc).replace(tzinfo=None)
    base = moment.replace(second=0, microsecond=0)
    remainder = base.minute % 5
    if moment.second == 0 and moment.microsecond == 0 and remainder == 0:
        return base
    return base + timedelta(minutes=5 - remainder)


def _naive_utc(moment: datetime) -> datetime:
    if moment.tzinfo is not None:
        return moment.astimezone(timezone.utc).replace(tzinfo=None)
    return moment


def _select_fit_function(method: str) -> Callable[[np.ndarray], RegressionModel]:
    if method == "linear":
        return linear.fit
    if method == "kernel":
        return kernel.fit
    if method == "wls3":
        return wls3.fit
    return wls2.fit


def _is_overridden(instance: object, method_name: str, base_type: type) -> bool:
    return getattr(type(instance), method_name) is not getattr(base_type, method_name)


class ShadyCoordinator:
    """Pure orchestration core for Shady."""

    def __init__(
        self,
        hass: HomeAssistant,
        cache: ShadyCache,
        config: Mapping[str, Any],
        baseline_providers: Mapping[str, ProviderProtocol],
        temperature_providers: Mapping[str, ProviderProtocol] | None = None,
    ) -> None:
        self.hass = hass
        self.cache = cache
        self.config = dict(config)
        self.baseline_providers = dict(baseline_providers)
        self.temperature_providers = dict(temperature_providers or {})
        self._strings: list[_StringState] = [_StringState(dict(item)) for item in self.config.get(CONF_STRINGS, [])]
        self._unsubs: list[CALLBACK_TYPE] = []
        self._listeners: list[CALLBACK_TYPE] = []
        self.last_refit_at: datetime | None = None
        self.forecasts: dict[str, list[tuple[datetime, float]]] = {}
        self.forecasts_raw: dict[str, list[tuple[datetime, float]]] = {}
        self.raw_baseline: dict[str, list[tuple[datetime, float]]] = {}
        self.temperature_models: dict[str, dict[int, RegressionModel]] = {}
        self.diagnostic_models: dict[str, dict[str, RegressionModel]] = {}
        self.aggregate_snapshot: dict[str, Any] = {}
        self.intraday_snapshot: dict[str, dict[str, Any]] = {}
        self.diagnostics_snapshot: dict[str, dict[str, Any]] = {}
        self.diagnostics_sum_snapshot: dict[str, Any] = {}
        self.diagnostics_enabled = False
        self.diagnostic_selection: datetime | None = None
        for string_state in self._strings:
            self.cache.validated.setdefault(string_state.config[CONF_ID], (0, None))

    @property
    def strings(self) -> list[dict[str, Any]]:
        return [dict(item.config) for item in self._strings]

    @property
    def current_refit_age(self) -> timedelta | None:
        if self.last_refit_at is None:
            return None
        return _naive_utc(dt_util.utcnow()) - self.last_refit_at

    async def async_setup(self) -> None:
        now = _naive_utc(dt_util.utcnow())
        if self.last_refit_at is None or self.current_refit_age is None or self.current_refit_age > timedelta(hours=24):
            await self.async_refit(now=now)
        else:
            await self.async_recompute_forecasts(now=now)
        await self.async_refresh_aggregates(now=now)
        self._register_listeners()
        self._register_aggregate_listeners()

    @callback
    def async_add_listener(self, listener: CALLBACK_TYPE) -> CALLBACK_TYPE:
        self._listeners.append(listener)

        @callback
        def _remove() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return _remove

    @callback
    def _notify_listeners(self) -> None:
        for listener in list(self._listeners):
            listener()

    def _register_listeners(self) -> None:
        self._unsubs.extend(
            async_track_time_change(
                self.hass,
                self._async_midnight_refit,
                hour=0,
                minute=1,
                second=0,
            )
        )
        self._unsubs.extend(
            async_track_time_change(
                self.hass,
                self._async_midnight_reset,
                hour=0,
                minute=0,
                second=0,
            )
        )
        seen: set[tuple[str, str | None, type[object]]] = set()
        for provider in self._all_forward_providers():
            if not _is_overridden(provider, "forward", ProviderBase):
                continue
            entity_id = provider.identify()
            if entity_id is None or entity_id == "":
                continue
            provider_key = (entity_id, getattr(provider, "attribute", None), type(provider))
            if provider_key in seen:
                continue
            seen.add(provider_key)
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    entity_id,
                    self._async_provider_update(provider),
                )
            )

    def _register_aggregate_listeners(self) -> None:
        self._unsubs.extend(
            async_track_time_change(
                self.hass,
                self._async_five_minute_refresh,
                minute=list(range(0, 60, 5)),
                second=0,
            )
        )
        for entity_id in self._actual_entity_ids():
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass,
                    entity_id,
                    self._async_actual_update,
                )
            )

    async def async_refit(self, now: datetime | None = None) -> None:
        await self.async_refit_models(now=now)
        await self.async_recompute_forecasts(now=now)

    def _all_forward_providers(self) -> Iterable[ProviderProtocol]:
        yield from self.baseline_providers.values()
        yield from self.temperature_providers.values()

    def _temperature_provider(self) -> ProviderProtocol | None:
        entity_id = str(self.config.get(CONF_TEMPERATURE_SOURCE_ENTITY_ID, ""))
        if not entity_id:
            return None
        return self.temperature_providers.get(entity_id)

    def _async_provider_update(
        self, provider: ProviderProtocol
    ) -> Callable[[Any], None]:
        @callback
        def _handle(event: Any) -> None:
            self.hass.async_create_task(self.async_handle_provider_update(provider))

        return _handle

    async def async_handle_provider_update(self, provider: ProviderProtocol, now: datetime | None = None) -> None:
        current = _naive_utc(now or dt_util.utcnow())
        series = provider.forward(current)
        if series is None:
            return
        series = [(_naive_utc(timestamp), value) for timestamp, value in series]
        entity_id = provider.identify()
        if entity_id is None:
            return
        for string_state in self._strings:
            if string_state.config[CONF_ID] == entity_id:
                intraday_state = self.cache.get_intraday_state(entity_id)
                intraday_state["reset_at"] = current
                if self._intraday_mode(string_state.config) == "blending":
                    intraday_state["old_predictions"] = list(self.forecasts_raw.get(entity_id, []))
                else:
                    intraday_state["old_predictions"] = []
                self.cache.set_intraday_state(entity_id, intraday_state)
                break
        await self.async_push_provider_series(entity_id, series, current)
        await self.async_recompute_forecasts(current)

    async def async_push_provider_series(
        self,
        sensor_id: str,
        series: list[tuple[datetime, float]],
        now: datetime,
    ) -> None:
        next_slot = _ceil_to_slot(now)
        not_before_index = self.cache._index_for(next_slot)  # noqa: SLF001
        payload = {self.cache._index_for(timestamp): value for timestamp, value in series}
        self.cache.push(sensor_id, payload, not_before_index=not_before_index)
        self.cache.validated.setdefault(sensor_id, (not_before_index, None))

    async def async_refit_models(self, now: datetime | None = None) -> None:
        current = _naive_utc(now or dt_util.utcnow())
        end = current.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(minutes=5)
        start = (end - timedelta(days=int(self.config.get(CONF_WINDOW_DAYS, 28)) - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        fit_method = _select_fit_function(str(self.config.get(CONF_REGRESSION_METHOD, DEFAULT_REGRESSION_METHOD)))
        temperature_fit_method = _select_fit_function(
            str(self.config.get(CONF_TEMPERATURE_REGRESSION_METHOD, DEFAULT_TEMPERATURE_REGRESSION_METHOD))
        )
        temperature_provider = self._temperature_provider()
        for string_state in self._strings:
            actual_entity = string_state.config[CONF_ACTUAL_YIELD_ENTITY_ID]
            baseline_provider = self.baseline_providers[string_state.config[CONF_ID]]
            actual_series = self.cache.get_time_range([actual_entity], start, end, group_by="sensor")[actual_entity]
            baseline_series = [(_naive_utc(timestamp), value) for timestamp, value in baseline_provider.fetch(start, end)]
            models: dict[int, RegressionModel] = {}
            per_slot: dict[int, list[tuple[float, float]]] = {}
            baseline_by_index = {
                int((timestamp - start).total_seconds() // 300): value
                for timestamp, value in baseline_series
                if start <= timestamp <= end
            }
            for index, actual_value in enumerate(actual_series):
                if not isinstance(actual_value, float):
                    continue
                forecast_value = baseline_by_index.get(index)
                if forecast_value is None:
                    continue
                slot = index % 288
                per_slot.setdefault(slot, []).append((float(forecast_value), float(actual_value)))
            for slot, samples in per_slot.items():
                matrix = np.asarray(samples, dtype=float)
                models[slot] = fit_method(matrix)
            string_state.models = models
            self._refit_temperature_models(
                string_state,
                start,
                end,
                temperature_provider,
                temperature_fit_method,
            )
        if self.diagnostics_enabled:
            self._fit_diagnostic_models(current)
        self.last_refit_at = current

    async def async_recompute_forecasts(self, now: datetime | None = None) -> None:
        current = _naive_utc(now or dt_util.utcnow())
        start = _ceil_to_slot(current)
        end = (current + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            minutes=5
        )
        for string_state in self._strings:
            string_id = string_state.config[CONF_ID]
            baseline_provider = self.baseline_providers[string_id]
            baseline_series = baseline_provider.forward(current)
            if baseline_series is None:
                continue
            baseline_series = [(_naive_utc(timestamp), value) for timestamp, value in baseline_series]
            baseline_series = [item for item in baseline_series if start <= item[0] <= end]
            temperature_targets = self._temperature_targets_for_series(string_state, baseline_series, current)
            model_lookup = string_state.models
            previous_raw = self.forecasts_raw.get(string_id, [])
            _, base_raw = adjust_forecast(
                baseline_series,
                model_lookup,
                inverter_limit=self._string_inverter_limit(string_state.config),
                coefficient_per_c=self._string_temperature_coefficient(string_state.config),
                clamp_output=False,
                return_raw=True,
            )
            intraday_context = self._prepare_intraday_context(string_state, current, base_raw, previous_raw)
            adjusted, raw_adjusted = adjust_forecast(
                baseline_series,
                model_lookup,
                inverter_limit=self._string_inverter_limit(string_state.config),
                coefficient_per_c=self._string_temperature_coefficient(string_state.config),
                target_temperatures=temperature_targets,
                intraday_factors=intraday_context["intraday_factors"],
                intraday_old_predictions=intraday_context["intraday_old_predictions"],
                intraday_blend_weights=intraday_context["intraday_blend_weights"],
                return_raw=True,
            )
            self.forecasts[string_id] = adjusted
            self.forecasts_raw[string_id] = raw_adjusted
            self.intraday_snapshot[string_id] = intraday_context["snapshot"]
            self.cache.validated.setdefault(string_id, (_slot_index(current), None))
            payload = {self.cache._index_for(timestamp): value for timestamp, value in adjusted}  # noqa: SLF001
            self.cache.push(string_id, payload, not_before_index=self.cache._index_for(_ceil_to_slot(current)))  # noqa: SLF001
        await self.async_refresh_aggregates(now=current)
        await self.async_refresh_diagnostics(now=current)

    async def async_handle_baseline_update(self, string_id: str, now: datetime | None = None) -> None:
        provider = self.baseline_providers[string_id]
        await self.async_handle_provider_update(provider, now=now)

    async def async_shutdown(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

    async def _async_midnight_refit(self, _: Any) -> None:
        await self.async_refit_models()
        await self.async_recompute_forecasts()

    async def _async_midnight_reset(self, _: Any) -> None:
        self.cache.reset_integral_totals(dt_util.now().date())
        self.cache.intraday_state.clear()
        self.intraday_snapshot.clear()
        await self.async_refresh_aggregates()

    async def _async_five_minute_refresh(self, _: Any) -> None:
        await self.async_recompute_forecasts()

    async def _async_actual_update(self, _: Any) -> None:
        await self.async_recompute_forecasts()

    @staticmethod
    def _string_inverter_limit(config: Mapping[str, Any]) -> float | None:
        raw = config.get(CONF_CONVERTER_LIMIT)
        if raw in (None, ""):
            return None
        return float(raw)

    @staticmethod
    def _string_temperature_coefficient(config: Mapping[str, Any]) -> float | None:
        raw = config.get(CONF_TEMPERATURE_COEFFICIENT)
        if raw in (None, ""):
            return None
        return float(raw)

    def _refit_temperature_models(
        self,
        string_state: _StringState,
        start: datetime,
        end: datetime,
        temperature_provider: ProviderProtocol | None,
        fit_method: Callable[[np.ndarray], RegressionModel],
    ) -> None:
        string_id = str(string_state.config[CONF_ID])
        target_entity_id = str(string_state.config.get(CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID, "")).strip()
        if not bool(string_state.config.get(CONF_TEMPERATURE_AWARE)) or temperature_provider is None or not target_entity_id:
            self.temperature_models.pop(string_id, None)
            return

        predictor_series = temperature_provider.fetch(start, end)
        if not predictor_series:
            self.temperature_models.pop(string_id, None)
            return
        target_series = self.cache.get_time_range([target_entity_id], start, end, group_by="sensor").get(
            target_entity_id, []
        )
        if not target_series:
            self.temperature_models.pop(string_id, None)
            return

        predictor_by_timestamp = {_naive_utc(timestamp): float(value) for timestamp, value in predictor_series}
        per_slot: dict[int, list[tuple[float, float]]] = {}
        current_timestamp = start
        for index, target_value in enumerate(target_series):
            if isinstance(target_value, (int, float)):
                predicted_value = predictor_by_timestamp.get(current_timestamp)
                if predicted_value is not None:
                    slot = index % 288
                    per_slot.setdefault(slot, []).append((predicted_value, float(target_value)))
            current_timestamp += timedelta(minutes=5)

        models: dict[int, RegressionModel] = {}
        for slot, samples in per_slot.items():
            matrix = np.asarray(samples, dtype=float)
            models[slot] = fit_method(matrix)
        self.temperature_models[string_id] = models

    def _temperature_targets_for_series(
        self,
        string_state: _StringState,
        baseline_series: list[tuple[datetime, float]],
        now: datetime,
    ) -> dict[datetime, float] | None:
        string_id = str(string_state.config[CONF_ID])
        model_lookup = self.temperature_models.get(string_id)
        if not model_lookup:
            return None
        temperature_provider = self._temperature_provider()
        if temperature_provider is None:
            return None
        predictor_series = temperature_provider.forward(now)
        if predictor_series is None:
            return None
        predictor_by_timestamp = {_naive_utc(timestamp): float(value) for timestamp, value in predictor_series}
        target_entity_id = str(string_state.config.get(CONF_TEMPERATURE_SOURCE_OVERRIDE_ENTITY_ID, "")).strip()
        if not target_entity_id:
            return None
        is_ambient = target_entity_id.startswith("weather.")
        rated_dc_capacity = self._string_rated_dc_capacity(string_state.config)
        max_uplift_c = float(self.config.get(CONF_MAX_UPLIFT_C, 25.0))
        target_temperatures: dict[datetime, float] = {}
        for timestamp, baseline_forecast in baseline_series:
            predicted_temp = predictor_by_timestamp.get(timestamp)
            if predicted_temp is None:
                continue
            model = model_lookup.get(_slot_index(timestamp))
            if model is None:
                continue
            predicted_value, _ = model.predict(predicted_temp)
            target_temperature = float(predicted_value)
            if is_ambient:
                target_temperature = float(
                    estimate_cell_temperature_from_ambient(
                        target_temperature,
                        baseline_forecast,
                        rated_dc_capacity,
                        max_uplift_c=max_uplift_c,
                    )
                )
            target_temperatures[timestamp] = target_temperature
        return target_temperatures or None

    @callback
    def set_diagnostics_enabled(self, enabled: bool) -> None:
        self.diagnostics_enabled = bool(enabled)
        if not self.diagnostics_enabled:
            self.diagnostic_models.clear()
            self.diagnostics_snapshot.clear()
            self.diagnostics_sum_snapshot.clear()
            self._notify_listeners()

    @callback
    def select_diagnostic_slot(self, moment: datetime) -> None:
        selected = _naive_utc(moment)
        self.diagnostic_selection = selected
        self.cache.pin_reference(selected.date())

    @callback
    def clear_diagnostic_slot(self) -> None:
        self.diagnostic_selection = None
        self.cache.clear_reference()

    @staticmethod
    def _last_complete_slot(moment: datetime) -> datetime:
        current = _naive_utc(moment)
        if current.minute % 5 == 0 and current.second == 0 and current.microsecond == 0:
            current -= timedelta(minutes=5)
        return current.replace(second=0, microsecond=0, minute=current.minute - (current.minute % 5))

    def _diagnostic_timestamp(self, now: datetime) -> datetime:
        if self.diagnostic_selection is not None:
            return self.diagnostic_selection
        return self._last_complete_slot(now)

    def _fit_diagnostic_models(self, now: datetime) -> None:
        if not self.diagnostics_enabled:
            self.diagnostic_models.clear()
            return

        selected = self._diagnostic_timestamp(now)
        slot_of_day = _slot_index(selected)
        methods = {
            "wls2": wls2.fit,
            "linear": linear.fit,
            "kernel": kernel.fit,
            "wls3": wls3.fit,
        }
        fitted: dict[str, dict[str, RegressionModel]] = {}
        for string_state in self._strings:
            string_id = str(string_state.config[CONF_ID])
            actual_entity = str(string_state.config[CONF_ACTUAL_YIELD_ENTITY_ID])
            pools = self.cache.get_pinned_slot_pool([string_id, actual_entity], slot_of_day, on_invalid="raw")
            forecast_values = pools.get(string_id, [])
            actual_values = pools.get(actual_entity, [])
            samples = [
                (float(forecast), float(actual))
                for forecast, actual in zip(forecast_values, actual_values)
                if isinstance(forecast, (int, float)) and isinstance(actual, (int, float))
            ]
            if not samples:
                continue
            matrix = np.asarray(samples, dtype=float)
            fitted[string_id] = {name: fit(matrix) for name, fit in methods.items()}
        self.diagnostic_models = fitted

    def _diagnostic_snapshot_for_string(self, string_state: _StringState, now: datetime) -> dict[str, Any]:
        if not self.diagnostics_enabled:
            return {"state": "disabled"}

        string_id = str(string_state.config[CONF_ID])
        actual_entity = str(string_state.config[CONF_ACTUAL_YIELD_ENTITY_ID])
        selected = self._diagnostic_timestamp(now)
        slot_of_day = _slot_index(selected)
        models = self.diagnostic_models.get(string_id, {})
        pools = self.cache.get_pinned_slot_pool([string_id, actual_entity], slot_of_day, on_invalid="raw")
        forecast_values = pools.get(string_id, [])
        actual_values = pools.get(actual_entity, [])
        scatter = [
            {"x": float(forecast), "y": float(actual)}
            for forecast, actual in zip(forecast_values, actual_values)
            if isinstance(forecast, (int, float)) and isinstance(actual, (int, float))
        ]
        selected_forecast_series = self.cache.get_time_range([string_id], selected, selected, on_invalid="skip")[string_id]
        selected_forecast = float(selected_forecast_series[0]) if selected_forecast_series else None
        selected_actual: float | None = None
        if selected <= now:
            selected_actual_series = self.cache.get_time_range([actual_entity], selected, selected, on_invalid="skip")[
                actual_entity
            ]
            if selected_actual_series:
                selected_actual = float(selected_actual_series[0])

        series: list[dict[str, Any]] = [{"name": "slot pool", "data": scatter}]
        accuracy: dict[str, float] = {}
        if selected_forecast is not None:
            for name in ("wls2", "linear", "kernel", "wls3"):
                model = models.get(name)
                if model is None:
                    continue
                predicted, _ = model.predict(selected_forecast)
                point = {"x": selected_forecast, "y": float(predicted)}
                series.append({"name": f"selected {name}", "data": [point]})
                if selected_actual is not None:
                    accuracy[name] = diagnostic_accuracy(float(predicted), selected_actual)
            if selected_actual is not None:
                series.append({"name": "selected actual", "data": [{"x": selected_forecast, "y": selected_actual}]})

        state = "enabled" if selected_forecast is not None else "no data"
        return {
            "state": state,
            "diagnosed_slot": slot_of_day,
            "selected_timestamp": selected.isoformat(),
            "series": series,
            "accuracy": accuracy,
        }

    async def async_refresh_diagnostics(self, now: datetime | None = None) -> None:
        current = _naive_utc(now or dt_util.utcnow())
        if not self.diagnostics_enabled:
            self.diagnostics_snapshot.clear()
            self.diagnostics_sum_snapshot.clear()
            self._notify_listeners()
            return

        self._fit_diagnostic_models(current)
        snapshots: dict[str, dict[str, Any]] = {}
        for string_state in self._strings:
            string_id = str(string_state.config[CONF_ID])
            snapshots[string_id] = self._diagnostic_snapshot_for_string(string_state, current)
        self.diagnostics_snapshot = snapshots
        self.diagnostics_sum_snapshot = self._diagnostic_sum_snapshot(current, snapshots)
        self._notify_listeners()

    def _diagnostic_sum_snapshot(
        self, now: datetime, per_string_snapshots: Mapping[str, dict[str, Any]] | None = None
    ) -> dict[str, Any]:
        if not self.diagnostics_enabled:
            return {"state": "disabled"}
        selected = self._diagnostic_timestamp(now)
        slot_of_day = _slot_index(selected)
        series: list[dict[str, Any]] = []
        if per_string_snapshots is None:
            per_string_snapshots = self.diagnostics_snapshot
        method_names = ("wls2", "linear", "kernel", "wls3")
        sum_points: dict[str, float] = {name: 0.0 for name in method_names}
        actual_total = 0.0
        have_actual = False
        for snapshot in per_string_snapshots.values():
            if snapshot.get("state") == "disabled":
                continue
            selected_series = snapshot.get("series", [])
            for entry in selected_series:
                name = entry.get("name")
                data = entry.get("data") or []
                if name == "selected actual" and data:
                    actual_total += float(data[0]["y"])
                    have_actual = True
                elif isinstance(name, str) and name.startswith("selected ") and data:
                    method = name.removeprefix("selected ")
                    if method in sum_points:
                        sum_points[method] += float(data[0]["y"])
        for name in method_names:
            series.append({"name": f"selected {name}", "data": [{"x": 0.0, "y": sum_points[name]}]})
        accuracy: dict[str, float] = {}
        if have_actual:
            series.append({"name": "selected actual", "data": [{"x": 0.0, "y": actual_total}]})
            for name in method_names:
                accuracy[name] = diagnostic_accuracy(sum_points[name], actual_total)
        return {
            "state": "enabled",
            "diagnosed_slot": slot_of_day,
            "selected_timestamp": selected.isoformat(),
            "series": series,
            "accuracy": accuracy,
        }

    @staticmethod
    def _string_rated_dc_capacity(config: Mapping[str, Any]) -> float | None:
        raw = config.get(CONF_RATED_DC_CAPACITY)
        if raw in (None, ""):
            return None
        return float(raw)

    @staticmethod
    def _intraday_mode(config: Mapping[str, Any]) -> str:
        mode = str(config.get(CONF_INTRADAY_CORRECTION_MODE, DEFAULT_INTRADAY_CORRECTION_MODE))
        return mode if mode in {"off", "ramping", "blending"} else "off"

    @staticmethod
    def _intraday_cutoff(config: Mapping[str, Any]) -> float:
        raw = config.get(CONF_INTRADAY_CORRECTION_CUTOFF, DEFAULT_INTRADAY_CORRECTION_CUTOFF)
        return float(raw)

    @staticmethod
    def _window_slots(config: Mapping[str, Any]) -> int:
        raw = config.get(CONF_WINDOW_SLOTS, DEFAULT_WINDOW_SLOTS)
        return int(raw)

    @staticmethod
    def _ramp_slots(config: Mapping[str, Any]) -> int:
        raw = config.get(CONF_RAMP_SLOTS, DEFAULT_RAMP_SLOTS)
        return int(raw)

    def _slot_energy_total(self, values: list[float]) -> float:
        return sum(values) * (5.0 / 60.0)

    def _build_intraday_weights(
        self,
        raw_series: list[tuple[datetime, float]],
        reset_at: datetime,
        ramp_slots: int,
    ) -> dict[datetime, float]:
        active_slots = 0
        weights: dict[datetime, float] = {}
        for timestamp, forecast in raw_series:
            if timestamp < reset_at:
                continue
            if forecast > 0:
                active_slots += 1
            weights[timestamp] = ramp_weight(active_slots, ramp_slots)
        return weights

    def _intraday_windows(
        self,
        string_id: str,
        actual_entity_id: str,
        now: datetime,
        window_slots: int,
    ) -> tuple[list[float], list[float]]:
        start = now - timedelta(minutes=5 * (window_slots - 1))
        actual = self.cache.get_time_range([actual_entity_id], start, now, on_invalid=0.0, group_by="sensor").get(
            actual_entity_id, []
        )
        forecast = self.cache.get_time_range([string_id], start, now, on_invalid=0.0, group_by="sensor").get(
            string_id, []
        )
        actual_values = [float(value) for value in actual if isinstance(value, (int, float))]
        forecast_values = [float(value) for value in forecast if isinstance(value, (int, float))]
        return actual_values, forecast_values

    def _intraday_ratio(
        self,
        string_state: _StringState,
        now: datetime,
    ) -> float:
        actual_entity_id = str(string_state.config[CONF_ACTUAL_YIELD_ENTITY_ID])
        actual_values, forecast_values = self._intraday_windows(
            str(string_state.config[CONF_ID]), actual_entity_id, now, self._window_slots(string_state.config)
        )
        pv_energy_window = self._slot_energy_total(actual_values)
        fc_energy_window = self._slot_energy_total(forecast_values)
        if fc_energy_window <= 0.0:
            return 1.0
        raw_ratio = pv_energy_window / fc_energy_window
        cutoff = self._intraday_cutoff(string_state.config)
        return min(max(raw_ratio, 1.0 - cutoff), 1.0 + cutoff)

    def _prepare_intraday_context(
        self,
        string_state: _StringState,
        now: datetime,
        raw_series: list[tuple[datetime, float]],
        previous_raw_series: list[tuple[datetime, float]],
    ) -> dict[str, Any]:
        string_id = str(string_state.config[CONF_ID])
        mode = self._intraday_mode(string_state.config)
        if mode == "off":
            self.cache.clear_intraday_state(string_id)
            return {
                "intraday_factors": None,
                "intraday_old_predictions": None,
                "intraday_blend_weights": None,
                "snapshot": {
                    "intraday_ratio": None,
                    "intraday_state": "off",
                    "intraday_ramp_weight": 0.0,
                    "values_raw": [value for _, value in raw_series],
                    "intraday_blend_active": False,
                },
            }

        ratio = self._intraday_ratio(string_state, now)
        reset_at = self.cache.get_intraday_state(string_id).get("reset_at")
        if not isinstance(reset_at, datetime):
            reset_at = now.replace(hour=0, minute=0, second=0, microsecond=0)
        ramp_slots = self._ramp_slots(string_state.config)
        weights = self._build_intraday_weights(raw_series, reset_at, ramp_slots)
        intraday_factors: dict[datetime, float] = {
            timestamp: intraday_correction_factor(ratio, 1.0, weight, self._intraday_cutoff(string_state.config))
            for timestamp, weight in weights.items()
        }
        old_predictions: dict[datetime, float] | None = None
        blend_weights: dict[datetime, float] | None = None
        if mode == "blending":
            old_predictions = {timestamp: value for timestamp, value in previous_raw_series}
            blend_weights = weights if old_predictions else None
            if not old_predictions:
                mode = "ramping"
        snapshot = {
            "intraday_ratio": ratio,
            "intraday_state": mode,
            "intraday_ramp_weight": next(iter(weights.values()), 0.0),
            "values_raw": [value for _, value in raw_series],
            "intraday_blend_active": bool(blend_weights and old_predictions),
        }
        self.cache.set_intraday_state(
            string_id,
            {
                "mode": mode,
                "reset_at": reset_at,
                "ratio": ratio,
                "weights": weights,
                "old_predictions": old_predictions or {},
                "values_raw": [value for _, value in raw_series],
                "intraday_blend_active": bool(blend_weights and old_predictions),
            },
        )
        return {
            "intraday_factors": intraday_factors,
            "intraday_old_predictions": old_predictions,
            "intraday_blend_weights": blend_weights,
            "snapshot": snapshot,
        }

    def get_forecast_series(self, string_id: str) -> list[tuple[datetime, float]]:
        return list(self.forecasts.get(string_id, []))

    def get_forecast_value(self, string_id: str) -> float | None:
        series = self.forecasts.get(string_id)
        if not series:
            return None
        return series[0][1]

    def _actual_entity_ids(self) -> list[str]:
        return [str(string.config[CONF_ACTUAL_YIELD_ENTITY_ID]) for string in self._strings]

    def _forecast_sensor_ids(self) -> list[str]:
        return [str(string.config[CONF_ID]) for string in self._strings]

    def _day_window(self, now: datetime) -> tuple[datetime, datetime]:
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start, day_start + timedelta(days=1) - timedelta(minutes=5)

    def _day_series(self, sensor_ids: list[str], now: datetime) -> tuple[list[datetime], list[float]]:
        start, end = self._day_window(now)
        timestamps = build_day_slot_timestamps(start)
        if not sensor_ids:
            return timestamps, [0.0] * len(timestamps)
        rows = self.cache.get_time_range(sensor_ids, start, end, on_invalid=0.0, group_by="slot")
        slot_rows = [dict(row) for row in rows]
        return timestamps, sum_slot_rows(slot_rows)

    @staticmethod
    def _remaining_today(timestamps: list[datetime], values: list[float], now: datetime) -> float:
        series = [(timestamp, value) for timestamp, value in zip(timestamps, values) if timestamp >= now]
        return total_energy_from_series(series)

    @staticmethod
    def _energy_today(timestamps: list[datetime], values: list[float], now: datetime) -> float:
        series = [(timestamp, value) for timestamp, value in zip(timestamps, values) if timestamp <= now]
        return total_energy_from_series(series)

    def _current_actual_sum(self) -> float:
        total = 0.0
        for entity_id in self._actual_entity_ids():
            state = self.hass.states.get(entity_id)
            value = state_to_three_state_value(state)
            if isinstance(value, float):
                total += value
        return total

    def _current_forecast_sum(self, now: datetime) -> float:
        current_slot = _ceil_to_slot(now)
        if current_slot > now:
            current_slot -= timedelta(minutes=5)
        start, end = current_slot, current_slot
        rows = self.cache.get_time_range(self._forecast_sensor_ids(), start, end, on_invalid=0.0, group_by="sensor")
        total = 0.0
        for string_id, values in rows.items():
            if values:
                total += float(values[0])
        return total

    async def async_refresh_aggregates(self, now: datetime | None = None) -> None:
        current = _naive_utc(now or dt_util.utcnow())
        current_date = dt_util.now().date()
        if self.cache.last_reset_date != current_date:
            self.cache.reset_integral_totals(current_date)
        timestamps, forecast_values = self._day_series(self._forecast_sensor_ids(), current)
        _, actual_values = self._day_series(self._actual_entity_ids(), current)
        self.aggregate_snapshot = {
            "pv_sum": self._current_actual_sum(),
            "fc_sum": self._current_forecast_sum(current),
            "fc_day_timestamps": timestamps,
            "fc_day_values": forecast_values,
            "fc_day_energy": total_energy_from_series(list(zip(timestamps, forecast_values))),
            "fc_remaining_today": self._remaining_today(timestamps, forecast_values, current),
            "pv_energy": self._energy_today(timestamps, actual_values, current),
            "fc_energy": self._energy_today(timestamps, forecast_values, current),
        }
        self.cache.set_integral_total("pv_energy", float(self.aggregate_snapshot["pv_energy"]))
        self.cache.set_integral_total("fc_energy", float(self.aggregate_snapshot["fc_energy"]))
        self._notify_listeners()

    def get_aggregate_value(self, key: str) -> Any:
        return self.aggregate_snapshot.get(key)

    def get_intraday_snapshot(self, string_id: str) -> dict[str, Any]:
        return dict(self.intraday_snapshot.get(string_id, {}))

    def get_diagnostic_snapshot(self, string_id: str) -> dict[str, Any]:
        return dict(self.diagnostics_snapshot.get(string_id, {}))

    def get_diagnostic_sum_snapshot(self) -> dict[str, Any]:
        return dict(self.diagnostics_sum_snapshot)
