"""`diagnostics/compare_regressions.py` — `CompareRegressionsMode`, the
one concrete `DiagnosticMode` in scope for TASK-0015b (ADR-004
§2/§2a/§2b/§3/§4).

For each configured string, compares whatever `regression/` strategy is
actually configured (ADR-001 §2) against the other three, all evaluated
at one "diagnosed slot" (ADR-004 §2/§2a) — a scatter-chart-ready
`series` attribute plus a per-method `accuracy` figure
(one `ShadyDiagnosticsSensor` per string), plus one additional flat
entry (`sensor_id="sum"`) that pointwise-sums the same comparison
across every string (§2b, the same `ShadyDiagnosticsSensor` class,
just another declared `sensor_id` — ADR-004 §5, fifth Amendment).

As of ADR-004 §5's 2026-09-03 Amendment, the `"sum"` entry is built
*here*, inside this same `compute()` call, from each string's raw,
day-index-aligned pool arrays (`_gather_pool`'s own `_GatheredPool`) —
not reassembled by `sensor.py` from the per-string entries' already
gap-filtered display `series`. Two reasons, not one: (a) `sensor.py`
calling `compute()` once per sensor was doing the same per-string
pool-gathering work again for every entity on every poll — O(strings²)
per tick instead of O(strings) — now `compute()` runs once per tick
(`coordinator.diagnostic_result()`'s cache) and every entity, including
the sum, shares that one call's output; (b) summing the raw arrays
*before* gap-filtering aligns strings by actual calendar day, whereas
summing each string's already-filtered display list via position (what
the old `sensor.py` code did) silently drifts once two strings have
different gap patterns. Which axis a "sum" (or any other aggregate) is
sliced along is this mode's own decision, specific to what it compares —
nothing outside this module assumes it.

`compute()`/`extra_fit()` resolve everything through the `ShadyCoordinator`
reference stored at construction (ADR-004 §5, second Amendment) —
`cache.get_pinned_slot_pool` for the historical pool, `strings()` for
which strings exist, and the small set of public accessors TASK-0015b
added to `coordinator.py` for everything else (`diagnosed_slot`,
`regression_settings`, `string_computation_config`,
`target_cell_temperature_for_slot`) — never a `_`-prefixed coordinator
attribute.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from .. import string_computation
from ..aggregation import diagnostic_accuracy, sum_predicted, sum_values
from ..cache import SLOTS_PER_DAY
from .base import (
    DiagnosticCadence,
    DiagnosticFitResult,
    DiagnosticMode,
    DiagnosticResult,
    DiagnosticSensorResult,
)

if TYPE_CHECKING:
    from ..coordinator import DiagnosedSlot, RegressionSettings, StringComputationConfig


def _to_float_array(values: list[float | None | str]) -> NDArray[np.float64]:
    """Fixed-length raw `get_pinned_slot_pool(..., on_invalid="raw")`
    output -> `NaN`-padded `float64`, the exact same None/str -> `NaN`
    collapse `cache.py`'s own `_shadow_value` applies (ADR-008 §2) —
    `string_computation.py`'s functions already treat `NaN` as
    excluded/pad, matching `build_pool`'s own contract."""
    return np.array([v if isinstance(v, float) else np.nan for v in values], dtype=np.float64)


class _GatheredPool:
    """One string's diagnosed-slot pool, gathered once and shared by
    both `_pool_series` (display) and `_predict_all_methods` (fitting)
    — avoids fetching/correcting the same offsets twice per string per
    tick."""

    def __init__(
        self,
        fc_by_offset: dict[int, NDArray[np.float64]],
        corrected_pv_by_offset: dict[int, NDArray[np.float64]],
    ) -> None:
        self.fc_by_offset = fc_by_offset
        self.corrected_pv_by_offset = corrected_pv_by_offset


@dataclass
class _StringDiagnostic:
    """One string's raw `compute()` ingredients, alongside its already-
    built `DiagnosticSensorResult` — kept together so `_compute_sum_sensor`
    can build the `"sum"` entry from the same raw numbers `_compute_sensor`
    used, rather than reparsing `result.attributes["series"]` back out
    (ADR-004 §5, 2026-09-03 Amendment: the mode sums what it already has
    on hand, not its own already-formatted output).

    `pool`/`fc_selected`/`pv_selected` are all `None` together exactly
    when `result` is the "no baseline configured" placeholder — that
    string contributes nothing to the sum, the same way it has nothing
    of its own to show.
    """

    sensor_id: str
    result: DiagnosticSensorResult
    pool: _GatheredPool | None
    fc_selected: float | None
    pv_selected: float | None
    predictions: dict[str, float]


class CompareRegressionsMode(DiagnosticMode):
    """ADR-004 §2: one scatter/accuracy comparison per configured
    string, all four `regression/` strategies evaluated at the one
    diagnosed slot."""

    key = "compare_regressions"

    def fit_cadence(self) -> DiagnosticCadence:
        # "slot" = every slot, i.e. TASK-0013's existing 5-minute
        # trigger (see `DiagnosticCadence`'s own docstring) — not the
        # once-daily recalibration trigger `extra_fit()`'s base-class
        # docstring generically describes; the diagnosed slot itself
        # advances every 5 minutes while auto-tracking (ADR-004 §2), so
        # refitting must keep pace with it, not with recalibration.
        return "slot"

    def compute_cadence(self) -> DiagnosticCadence:
        return "slot"

    def sensor_ids(self) -> Sequence[tuple[str, str]]:
        """One id per configured string, named to match what
        `sensor.py` used to build itself (`"{string name} Diagnostics"`),
        plus the fixed `"sum"` id `_compute_sum_sensor` below always
        produces — the two `compute()` already ever emits (ADR-004 §5,
        fifth Amendment)."""
        return [
            (str(string_index), f"{string_name} Diagnostics")
            for string_index, string_name in self._coordinator.strings()
        ] + [("sum", "Diagnostics Sum")]

    def compute(self) -> DiagnosticResult:
        diagnosed = self._coordinator.diagnosed_slot()
        settings = self._coordinator.regression_settings()
        per_string = [
            self._compute_sensor(string_index, diagnosed, settings)
            for string_index, _name in self._coordinator.strings()
        ]
        sensors = [item.result for item in per_string]
        sensors.append(self._compute_sum_sensor(settings, per_string))
        return DiagnosticResult(sensors=sensors)

    def extra_fit(self) -> DiagnosticFitResult | None:
        diagnosed = self._coordinator.diagnosed_slot()
        settings = self._coordinator.regression_settings()
        by_sensor: dict[str, dict[str, float]] = {}
        for string_index, _name in self._coordinator.strings():
            config = self._coordinator.string_computation_config(string_index)
            if config.baseline_entity_id is None:
                continue
            fc_selected = self._selected_value(config.baseline_entity_id, diagnosed.index)
            if fc_selected is None:
                continue
            pool = self._gather_pool(config, settings, diagnosed)
            predictions = self._predict_all_methods(
                string_index, config, diagnosed, settings, pool, fc_selected
            )
            if predictions:
                by_sensor[str(string_index)] = predictions
        if not by_sensor:
            return None
        return DiagnosticFitResult(by_sensor=by_sensor)

    # -- per-string compute() ---------------------------------------------

    def _compute_sensor(
        self, string_index: int, diagnosed: DiagnosedSlot, settings: RegressionSettings
    ) -> _StringDiagnostic:
        sensor_id = str(string_index)
        config = self._coordinator.string_computation_config(string_index)
        if config.baseline_entity_id is None:
            # No baseline configured for this string — nothing to
            # diagnose (mirrors `coordinator._fit_string`'s own
            # graceful skip for the same condition), and nothing for
            # `_compute_sum_sensor` to include either.
            result = DiagnosticSensorResult(sensor_id=sensor_id, state="unavailable", attributes={})
            return _StringDiagnostic(sensor_id, result, None, None, None, {})

        pool = self._gather_pool(config, settings, diagnosed)
        series: list[dict[str, Any]] = self._pool_series(settings, pool)

        fc_selected = self._selected_value(config.baseline_entity_id, diagnosed.index)
        pv_selected = (
            self._selected_value(config.actual_yield_entity_id, diagnosed.index)
            if diagnosed.is_elapsed
            else None
        )

        predictions = self._coordinator.cache.diagnostic_fit(sensor_id) or {}
        accuracy = self._append_selected_series(series, predictions, fc_selected, pv_selected)

        attributes: dict[str, Any] = {"series": series, "accuracy": accuracy}
        state = self._coordinator.now().isoformat()
        result = DiagnosticSensorResult(sensor_id=sensor_id, state=state, attributes=attributes)
        return _StringDiagnostic(sensor_id, result, pool, fc_selected, pv_selected, predictions)

    def _compute_sum_sensor(
        self, settings: RegressionSettings, per_string: list[_StringDiagnostic]
    ) -> DiagnosticSensorResult:
        """ADR-004 §2b: the `sensor_id="sum"` entry — pointwise-summed
        across every string that has anything to contribute (`pool is
        not None`), built from the same raw ingredients `_compute_sensor`
        gathered above, not from those strings' already-formatted
        `result.attributes`.

        `state` mirrors `_compute_sensor`'s own "no baseline configured"
        placeholder when no string contributes anything at all (zero
        configured strings, or every one of them unconfigured) — the
        same `"unavailable"` contract, for the same reason.
        """
        contributing = [item for item in per_string if item.pool is not None]
        state = self._coordinator.now().isoformat()
        if not contributing:
            return DiagnosticSensorResult(sensor_id="sum", state="unavailable", attributes={})

        pools = [item.pool for item in contributing if item.pool is not None]
        offsets = pools[0].fc_by_offset.keys()
        summed_pool = _GatheredPool(
            fc_by_offset={
                offset: self._sum_arrays_nan_aware([pool.fc_by_offset[offset] for pool in pools])
                for offset in offsets
            },
            corrected_pv_by_offset={
                offset: self._sum_arrays_nan_aware(
                    [pool.corrected_pv_by_offset[offset] for pool in pools]
                )
                for offset in offsets
            },
        )
        series = self._pool_series(settings, summed_pool)

        fc_selected = sum_values(item.fc_selected for item in contributing)
        pv_selected = sum_values(item.pv_selected for item in contributing)
        predictions = sum_predicted(item.predictions for item in contributing if item.predictions)
        accuracy = self._append_selected_series(series, predictions, fc_selected, pv_selected)

        return DiagnosticSensorResult(
            sensor_id="sum", state=state, attributes={"series": series, "accuracy": accuracy}
        )

    def _sum_arrays_nan_aware(self, arrays: list[NDArray[np.float64]]) -> NDArray[np.float64]:
        """Elementwise sum across strings, day-index aligned — each
        array is one string's fixed-length, `NaN`-padded pool for one
        offset (`_gather_pool`'s own shape), so summing across strings
        first, at this raw stage, sums the *same calendar day* for every
        string. A day where every contributing string is `NaN` stays
        `NaN` (so `_pool_series`'s own filter drops it, same as any
        other missing day); a day where only some strings are `NaN`
        sums just the present ones — the array-level equivalent of
        `aggregation.sum_values`'s None-exclusion for scalars, not a
        zero contribution from the missing string."""
        stacked = np.stack(arrays, axis=0)
        all_missing = np.all(np.isnan(stacked), axis=0)
        summed = np.nansum(stacked, axis=0)
        return np.where(all_missing, np.nan, summed)

    def _append_selected_series(
        self,
        series: list[dict[str, Any]],
        predictions: dict[str, float],
        fc_selected: float | None,
        pv_selected: float | None,
    ) -> dict[str, float]:
        """Appends the `"selected {method}"`/`"selected actual"` entries
        to `series` in place and returns the resulting `accuracy` dict —
        shared by `_compute_sensor` and `_compute_sum_sensor`, which
        differ only in which `predictions`/`fc_selected`/`pv_selected`
        they pass in (ADR-004 §2/§2b): per-string values for one, the
        pointwise sums across contributing strings for the other."""
        accuracy: dict[str, float] = {}
        if fc_selected is None:
            return accuracy
        for method, predicted in predictions.items():
            if pv_selected is not None:
                method_accuracy = diagnostic_accuracy(predicted, pv_selected)
                accuracy[method] = method_accuracy
                name = f"selected {method} ({round(method_accuracy * 100)}%)"
            else:
                name = f"selected {method}"
            series.append({"name": name, "data": [[fc_selected, predicted]]})
        if pv_selected is not None:
            series.append({"name": "selected actual", "data": [[fc_selected, pv_selected]]})
        return accuracy

    def _pool_series(
        self, settings: RegressionSettings, pool: _GatheredPool
    ) -> list[dict[str, Any]]:
        """The `"-1"`/`"0"`/`"1"`... slot-pool series (ADR-004 §2): one
        `[FC_i, PV_i]` pair per historical day, `PV_i` the *corrected*
        value (`apply_training_corrections`) — exactly the training
        data `regression/` itself sees for this slot's pool, not the
        raw recorder reading."""
        series: list[dict[str, Any]] = []
        for offset in range(-settings.smoothing_radius, settings.smoothing_radius + 1):
            fc_row = pool.fc_by_offset[offset][0]
            pv_row = pool.corrected_pv_by_offset[offset][0]
            data = [
                [float(fc), float(pv)]
                for fc, pv in zip(fc_row, pv_row, strict=True)
                if not (np.isnan(fc) or np.isnan(pv))
            ]
            series.append({"name": str(offset), "data": data})
        return series

    # -- shared pool gathering ------------------------------------------------

    def _gather_pool(
        self,
        config: StringComputationConfig,
        settings: RegressionSettings,
        diagnosed: DiagnosedSlot,
    ) -> _GatheredPool:
        """Fetch + correct the diagnosed slot's pool across every
        neighbor offset (`-smoothing_radius..+smoothing_radius`), one
        `get_pinned_slot_pool` call per offset — shared by `compute()`'s
        display series and `extra_fit()`'s model fitting alike, so a
        string's pool is only fetched/corrected once per call, not
        twice."""
        assert config.baseline_entity_id is not None
        sensor_ids = [config.baseline_entity_id, config.actual_yield_entity_id]
        if config.temperature_entity_id is not None:
            sensor_ids.append(config.temperature_entity_id)

        fc_by_offset: dict[int, NDArray[np.float64]] = {}
        pv_by_offset: dict[int, NDArray[np.float64]] = {}
        temperature_by_offset: dict[int, NDArray[np.float64]] | None = (
            {} if config.temperature_entity_id is not None else None
        )
        for offset in range(-settings.smoothing_radius, settings.smoothing_radius + 1):
            offset_slot = (diagnosed.slot_of_day + offset) % SLOTS_PER_DAY
            raw = self._coordinator.cache.get_pinned_slot_pool(
                sensor_ids, offset_slot, on_invalid="raw"
            )
            fc_by_offset[offset] = _to_float_array(raw[config.baseline_entity_id])[None, :]
            pv_by_offset[offset] = _to_float_array(raw[config.actual_yield_entity_id])[None, :]
            if temperature_by_offset is not None:
                assert config.temperature_entity_id is not None
                temperature_by_offset[offset] = _to_float_array(raw[config.temperature_entity_id])[
                    None, :
                ]

        corrected_pv_by_offset = string_computation.apply_training_corrections(
            fc_by_offset,
            pv_by_offset,
            temperature_by_offset,
            config.temperature_tier,
            config.converter_limit_w,
            settings.clipping_threshold,
            config.coefficient_per_c,
            config.provider_already_corrects,
            config.rated_dc_capacity_wp,
            settings.max_uplift_c,
        )
        return _GatheredPool(fc_by_offset, corrected_pv_by_offset)

    # -- extra_fit() ------------------------------------------------------

    def _predict_all_methods(
        self,
        string_index: int,
        config: StringComputationConfig,
        diagnosed: DiagnosedSlot,
        settings: RegressionSettings,
        pool: _GatheredPool,
        fc_selected: float,
    ) -> dict[str, float]:
        target_cell_temperature: NDArray[np.float64] | None = None
        if config.temperature_tier is not None:
            resolved = self._coordinator.target_cell_temperature_for_slot(
                string_index, diagnosed.index
            )
            if resolved is not None:
                target_cell_temperature = np.array([resolved], dtype=np.float64)

        fc_selected_array = np.array([fc_selected], dtype=np.float64)
        predictions: dict[str, float] = {}
        for method in string_computation.REGRESSION_STRATEGIES:
            model = string_computation.fit_string_model(
                pool.fc_by_offset,
                pool.corrected_pv_by_offset,
                settings.smoothing_radius,
                settings.neighbor_fitting_cutoff,
                settings.recency_decay_max,
                method,
            )
            predicted = string_computation.predict_string_forecast(
                model,
                fc_selected_array,
                target_cell_temperature,
                config.coefficient_per_c,
                config.provider_already_corrects,
                config.converter_limit_w,
            )
            predictions[method] = float(predicted[0])
        return predictions

    # -- shared helpers -------------------------------------------------------

    def _selected_value(self, sensor_id: str, index: int) -> float | None:
        """The single value at absolute slot `index` for `sensor_id` —
        `FC_selected`/`PV_selected` (ADR-004 §2). `cache.get_time_range`'s
        validate-before-read already handles both an elapsed (recorder-
        backed) and a not-yet-elapsed (push-extended provider) slot
        transparently (`adr-summary.md` §5's hybrid validated-range
        note) — this needs no branching of its own on `is_elapsed`."""
        slot_start = self._coordinator.cache.timestamp_for(index)
        raw = self._coordinator.cache.get_time_range(
            [sensor_id], slot_start, slot_start, on_invalid="raw"
        )[sensor_id]
        value = raw[0]
        return value if isinstance(value, float) else None
