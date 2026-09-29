"""`diagnostics/compare_regressions.py` — `CompareRegressionsMode`, the
one concrete `DiagnosticMode` in scope for TASK-0015b (ADR-004
§2/§2a/§2b/§3/§4).

For each configured string, compares whatever `regression/` strategy is
actually configured (ADR-001 §2) against the other three, all evaluated
at one "diagnosed slot" (ADR-004 §2/§2a) — a `custom:plotly-graph`-ready
`series` attribute (each entry `{"entity": "", "name": ..., "type":
"scatter", "mode": "markers", "x": [...], "y": [...]}`, built via the
inherited `DiagnosticMode._xy_series_entry` — `base.py`, ADR-004 §2d,
`TASK-0015b-patch-3`; `entity`/`type`/`mode` are constants, so
`sensor.py` needs no reshaping step at all) plus a per-method `accuracy`
figure (one `ShadyDiagnosticsSensor` per string), plus one additional
flat entry (`sensor_id="sum"`) that pointwise-sums the same comparison
across every string (§2b, the same `ShadyDiagnosticsSensor` class, just
another declared `sensor_id` — ADR-004 §5, fifth Amendment).

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

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

import numpy as np
from numpy.typing import NDArray

from .. import string_computation
from ..aggregation import diagnostic_accuracy, sum_predicted, sum_values
from ..cache import SLOTS_PER_DAY
from ..regression.base import build_pool
from .base import (
    DiagnosticCadence,
    DiagnosticFitResult,
    DiagnosticMode,
    DiagnosticResult,
    DiagnosticSensorResult,
)

_LOGGER = logging.getLogger(__name__)

# Temporary diagnostic instrumentation (TASK-0037 follow-up) -- mirrors
# `coordinator.py`'s own `_DIAGNOSTIC_LOG` flag/convention. Flip to
# `True`, restart, and check the log for why `_selected_value` is (or
# isn't) resolving a real float for the diagnosed slot -- remove once
# the "selected ..." series-missing report is root-caused for real.
_DIAGNOSTIC_LOG = False

if TYPE_CHECKING:
    # Same reasoning as base.py's own ShadyCoordinatorLike import: this module
    # never constructs a DiagnosedSlot/RegressionSettings/
    # StringComputationConfig, only reads attributes off instances
    # coordinator.py already built -- attribute access needs no import of
    # the class that built the instance, so these three names are only
    # ever used as annotations here, already deferred by `from __future__
    # import annotations` above.
    from ..coordinator_like import DiagnosedSlot, RegressionSettings, StringComputationConfig


def _to_float_array(values: list[float | None | str]) -> NDArray[np.float64]:
    """Fixed-length raw `get_pinned_slot_pool(..., on_invalid="raw")`
    output -> `NaN`-padded `float64`, the exact same None/str -> `NaN`
    collapse `cache.py`'s own `_shadow_value` applies (ADR-008 §2) —
    `string_computation.py`'s functions already treat `NaN` as
    excluded/pad, matching `build_pool`'s own contract."""
    return np.array([v if isinstance(v, float) else np.nan for v in values], dtype=np.float64)


def _export_float_or_blank(value: float) -> str:
    """`export_csv`'s own float formatting (ADR-015): `repr()`-level
    precision — round-trip-safe for the fixture-regression tests
    (`tests/diagnostics/csv_fixture_support.py`'s `parse_csv_sections`
    reads it straight back via `float()`) — or an empty string for a
    `NaN` pad/invalid/missing sample, never a literal `"nan"` string a
    spreadsheet or a naive `float()` call would otherwise have to
    special-case."""
    if np.isnan(value):
        return ""
    return repr(float(value))


class _GatheredPool:
    """One string's diagnosed-slot pool, gathered once and shared by
    both `_pool_series` (display) and `_predict_all_methods` (fitting)
    — avoids fetching/correcting the same offsets twice per string per
    tick.

    `pv_by_offset`/`temperature_by_offset` (ADR-015 §2, `TASK-0038`):
    the raw, *uncorrected* readings `_gather_pool` already computes on
    the way to `corrected_pv_by_offset` (via `apply_training_corrections`)
    but, before this task, discarded once that call returned.
    `CompareRegressionsMode.export_csv`'s own `# training_pool` section
    is the first consumer that needs the raw values alongside the
    corrected ones, to show what a correction actually changed rather
    than only its result. `temperature_by_offset` stays `None` for a
    string with no configured `temperature_entity_id` — the same
    "absent, not a placeholder" contract `_gather_pool` already gives
    it.
    """

    def __init__(
        self,
        fc_by_offset: dict[int, NDArray[np.float64]],
        corrected_pv_by_offset: dict[int, NDArray[np.float64]],
        pv_by_offset: dict[int, NDArray[np.float64]],
        temperature_by_offset: dict[int, NDArray[np.float64]] | None,
    ) -> None:
        self.fc_by_offset = fc_by_offset
        self.corrected_pv_by_offset = corrected_pv_by_offset
        self.pv_by_offset = pv_by_offset
        self.temperature_by_offset = temperature_by_offset


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
                if _DIAGNOSTIC_LOG:
                    _LOGGER.warning(
                        "DIAG extra_fit: string_index=%d has no baseline_entity_id -- skipped",
                        string_index,
                    )
                continue
            try:
                fc_selected = self._selected_value(config.baseline_entity_id, diagnosed.index)
                if fc_selected is None:
                    if _DIAGNOSTIC_LOG:
                        _LOGGER.warning(
                            "DIAG extra_fit: string_index=%d diagnosed.index=%d"
                            " fc_selected=None -- skipped",
                            string_index,
                            diagnosed.index,
                        )
                    continue
                pool = self._gather_pool(config, settings, diagnosed)
                predictions = self._predict_all_methods(
                    string_index, config, diagnosed, settings, pool, fc_selected
                )
                if _DIAGNOSTIC_LOG:
                    _LOGGER.warning(
                        "DIAG extra_fit: string_index=%d diagnosed.index=%d"
                        " fc_selected=%r predictions=%r",
                        string_index,
                        diagnosed.index,
                        fc_selected,
                        predictions,
                    )
            except Exception:
                # ADR-000 §8: a background failure is logged and
                # swallowed, not raised — mirrors `_refit_sync`'s own
                # per-string isolation (`coordinator.py`), "leaving it
                # unmodeled, not aborting the remaining strings". Without
                # this, one string's fit failure (e.g. a transient
                # recorder/data hiccup) would blow up this whole
                # `extra_fit()` call, uncaught all the way up through
                # `_diagnostics_tick_sync` (which has no try/except of
                # its own either) — silently preventing *every* string's
                # predictions from ever being cached that tick, not just
                # this one's.
                _LOGGER.exception(
                    "Diagnostic extra_fit failed for string %d — leaving it"
                    " unmodeled this tick, not aborting the remaining strings",
                    string_index,
                )
                continue
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

        if _DIAGNOSTIC_LOG:
            _LOGGER.warning(
                "DIAG compute_sensor: sensor_id=%r fc_selected=%r pv_selected=%r"
                " predictions=%r accuracy=%r",
                sensor_id,
                fc_selected,
                pv_selected,
                predictions,
                accuracy,
            )

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
            # `export_csv("sum")` is unsupported (see its own docstring) --
            # nothing ever reads these two fields for the synthetic sum
            # pool, so they stay unpopulated rather than pointwise-summed
            # for no consumer.
            pv_by_offset={},
            temperature_by_offset=None,
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
        pointwise sums across contributing strings for the other.
        Entries are complete `plotly-graph` traces, built via the
        inherited `DiagnosticMode._xy_series_entry` (ADR-004 §2d,
        `TASK-0015b-patch-3`) — `sensor.py` performs no further
        shaping."""
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
            series.append(self._xy_series_entry(name, [[fc_selected, predicted]]))
        if pv_selected is not None:
            series.append(self._xy_series_entry("selected actual", [[fc_selected, pv_selected]]))
        return accuracy

    def _pool_series(
        self, settings: RegressionSettings, pool: _GatheredPool
    ) -> list[dict[str, Any]]:
        """The `"-1"`/`"0"`/`"1"`... slot-pool series (ADR-004 §2): one
        `[FC_i, PV_i]` pair per historical day, `PV_i` the *corrected*
        value (`apply_training_corrections`) — exactly the training
        data `regression/` itself sees for this slot's pool, not the
        raw recorder reading. Entries are complete `plotly-graph`
        traces, built via the inherited
        `DiagnosticMode._xy_series_entry` (ADR-004 §2d,
        `TASK-0015b-patch-3`) — `sensor.py` performs no further
        shaping."""
        series: list[dict[str, Any]] = []
        for offset in range(-settings.smoothing_radius, settings.smoothing_radius + 1):
            fc_row = pool.fc_by_offset[offset][0]
            pv_row = pool.corrected_pv_by_offset[offset][0]
            data = [
                [float(fc), float(pv)]
                for fc, pv in zip(fc_row, pv_row, strict=True)
                if not (np.isnan(fc) or np.isnan(pv))
            ]
            series.append(self._xy_series_entry(str(offset), data))
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
        twice. Passes `reference=self._coordinator.now()` through to
        `get_pinned_slot_pool` (ADR-007a §6 Amendment, TASK-0037) — the
        same injectable clock every other diagnostics call already
        resolves through, rather than that accessor falling back to the
        real wall clock every time."""
        assert config.baseline_entity_id is not None
        sensor_ids = [config.baseline_entity_id, config.actual_yield_entity_id]
        if config.temperature_entity_id is not None:
            sensor_ids.append(config.temperature_entity_id)

        fc_by_offset: dict[int, NDArray[np.float64]] = {}
        pv_by_offset: dict[int, NDArray[np.float64]] = {}
        temperature_by_offset: dict[int, NDArray[np.float64]] | None = (
            {} if config.temperature_entity_id is not None else None
        )
        now = self._coordinator.now()
        for offset in range(-settings.smoothing_radius, settings.smoothing_radius + 1):
            offset_slot = (diagnosed.slot_of_day + offset) % SLOTS_PER_DAY
            raw = self._coordinator.cache.get_pinned_slot_pool(
                sensor_ids, offset_slot, on_invalid="raw", reference=now
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
        return _GatheredPool(
            fc_by_offset, corrected_pv_by_offset, pv_by_offset, temperature_by_offset
        )

    # -- export_csv() ------------------------------------------------------

    def export_csv(self, sensor_id: str) -> str | None:
        """ADR-015 §2/§3/§6 (`TASK-0038`): `sensor_id`'s current
        diagnosed-slot raw regression inputs as a CSV — the leading
        `# diagnostic_mode` section (this mode's own registry `key`,
        `base.py`'s `_write_csv_sections` convention) plus four content
        sections: `# metadata` (one row, everything needed to place the
        rest in context), `# training_pool` (every neighbor-offset/day
        training point, decomposed weight components included),
        `# predictions` (all four `regression/` strategies' predicted
        values for this slot, computed from the same pool as
        `# training_pool` -- never from the `diagnostic_fit` cache),
        `# prediction_inputs` (the scalar inputs those predictions were
        made from).

        Only a real configured-string `sensor_id` ("0", "1", ...) is
        supported — `sensor_id="sum"` (also one of `sensor_ids()`'s own
        declared ids) returns `None` here: the pointwise-summed
        pseudo-string has no single coherent per-string
        `temperature_tier`/config the `# metadata` section's one-row
        schema could represent, and "why did string 0's fit look weird"
        (this task's own Goal) is inherently about one real string,
        never the sum (implementation decision, 2026-09-27,
        `TASK-0038`). Returns `None` the same way for any other
        unrecognized `sensor_id`, and for a recognized string with no
        `baseline_entity_id` configured (`_compute_sensor`'s own
        contract) — `http_export.py` reports `HTTPStatus.NOT_FOUND` for
        every one of these, indistinguishable from the HTTP caller's
        point of view (ADR-015 §4).
        """
        try:
            string_index = int(sensor_id)
        except ValueError:
            return None

        names = dict(self._coordinator.strings())
        string_name = names.get(string_index)
        if string_name is None:
            return None

        config = self._coordinator.string_computation_config(string_index)
        if config.baseline_entity_id is None:
            return None

        diagnosed = self._coordinator.diagnosed_slot()
        settings = self._coordinator.regression_settings()
        pool = self._gather_pool(config, settings, diagnosed)

        _sample_pool, breakdown = build_pool(
            pool.fc_by_offset,
            pool.corrected_pv_by_offset,
            settings.smoothing_radius,
            settings.neighbor_fitting_cutoff,
            settings.recency_decay_max,
            return_weight_breakdown=True,
        )

        fc_selected = self._selected_value(config.baseline_entity_id, diagnosed.index)
        pv_selected = (
            self._selected_value(config.actual_yield_entity_id, diagnosed.index)
            if diagnosed.is_elapsed
            else None
        )
        # ADR-015 Amendment 2026-09-29: computed here, from the very
        # `pool` this export's `# training_pool` is built from -- not read
        # back from `cache.diagnostic_fit(sensor_id)`. That cache is keyed
        # by `sensor_id` alone, is not invalidated by pinning/unpinning
        # the diagnosed slot, and is never populated for a registered but
        # inactive `mode` (§4a), so it could describe a different slot
        # (or nothing) than the pool beside it -- an export whose
        # predictions cannot be reproduced from its own training data.
        predictions = self._export_predictions(
            string_index, config, diagnosed, settings, pool, fc_selected
        )
        target_cell_temperature: float | None = None
        if config.temperature_tier is not None:
            target_cell_temperature = self._coordinator.target_cell_temperature_for_slot(
                string_index, diagnosed.index
            )

        sections = [
            ("diagnostic_mode", [{"diagnostic_mode": self.key}]),
            (
                "metadata",
                [
                    self._export_metadata_row(
                        string_index, string_name, diagnosed, settings, config, pool
                    )
                ],
            ),
            ("training_pool", self._export_training_pool_rows(settings, pool, breakdown)),
            ("predictions", self._export_predictions_rows(predictions, pv_selected)),
            (
                "prediction_inputs",
                self._export_prediction_inputs_rows(
                    fc_selected, target_cell_temperature, pv_selected
                ),
            ),
        ]
        return self._write_csv_sections(sections)

    def _export_predictions(
        self,
        string_index: int,
        config: StringComputationConfig,
        diagnosed: DiagnosedSlot,
        settings: RegressionSettings,
        pool: _GatheredPool,
        fc_selected: float | None,
    ) -> dict[str, float]:
        """All four strategies' predictions for the exported pool, via
        the same `_predict_all_methods` `extra_fit()` uses. Empty (no
        `# predictions` rows, nothing fabricated) when there is no
        `fc_selected` to predict from, and also when fitting raises: a
        debugging aid for \"why did this fit look weird\" must not turn
        into an HTTP 500 on exactly the input that made it weird, so the
        training data is still exported and the failure is logged
        (mirrors `extra_fit()`'s own per-string isolation)."""
        if fc_selected is None:
            return {}
        try:
            return self._predict_all_methods(
                string_index, config, diagnosed, settings, pool, fc_selected
            )
        except Exception:
            _LOGGER.exception(
                "export_csv: fitting failed for string %d -- exporting its training data"
                " without predictions",
                string_index,
            )
            return {}

    def _export_metadata_row(
        self,
        string_index: int,
        string_name: str,
        diagnosed: DiagnosedSlot,
        settings: RegressionSettings,
        config: StringComputationConfig,
        pool: _GatheredPool,
    ) -> dict[str, str]:
        """The `# metadata` section's one row — everything needed to
        place `# training_pool`/`# predictions`/`# prediction_inputs`
        in context without a second file, *and* to recompute the fit
        from this file alone (ADR-015 Amendment 2026-09-29): every
        scalar `apply_training_corrections`, `fit_string_model` and
        `predict_string_forecast` take is either a column here, a raw
        `# training_pool` column, or a `# prediction_inputs` value.
        `window_days` is read off
        `pool.fc_by_offset[0]`'s own shape rather than a new coordinator
        accessor — `_gather_pool`'s arrays already carry it."""
        window_days = pool.fc_by_offset[0].shape[1]
        diagnosed_at = self._coordinator.cache.timestamp_for(diagnosed.index)
        is_pinned = not self._coordinator.is_following_latest_diagnostic_slot()
        return {
            "string_index": str(string_index),
            "string_name": string_name,
            "diagnosed_at": diagnosed_at.isoformat(),
            "diagnosed_index": str(diagnosed.index),
            "slot_of_day": str(diagnosed.slot_of_day),
            "is_pinned": "true" if is_pinned else "false",
            "is_elapsed": "true" if diagnosed.is_elapsed else "false",
            "regression_method_configured": self._coordinator.configured_regression_method(),
            "temperature_tier": config.temperature_tier or "",
            "window_days": str(window_days),
            "smoothing_radius": str(settings.smoothing_radius),
            "neighbor_fitting_cutoff": repr(float(settings.neighbor_fitting_cutoff)),
            "recency_decay_max": repr(float(settings.recency_decay_max)),
            "clipping_threshold": repr(float(settings.clipping_threshold)),
            "max_uplift_c": repr(float(settings.max_uplift_c)),
            # ADR-015 Amendment 2026-09-29 (`TASK-0038-patch-1`): the four
            # `StringComputationConfig` scalars `apply_training_corrections`
            # / `predict_string_forecast` consume that the original schema
            # left out -- with them, this file alone is enough to re-run
            # correction -> pool -> fit -> predict. Blank = `None` (no
            # inverter limit / no rated capacity configured).
            "converter_limit_w": self._export_optional_float(config.converter_limit_w),
            "coefficient_per_c": repr(float(config.coefficient_per_c)),
            "provider_already_corrects": "true" if config.provider_already_corrects else "false",
            "rated_dc_capacity_wp": self._export_optional_float(config.rated_dc_capacity_wp),
        }

    @staticmethod
    def _export_optional_float(value: float | None) -> str:
        """`None` -> blank, else `repr()`-level precision -- the same
        blank-means-absent convention `temperature_tier` already uses in
        `# metadata`."""
        return "" if value is None else repr(float(value))

    def _export_window_start_date(self, window_days: int) -> date:
        """The calendar date of `# training_pool`'s `day_index=0`
        column — mirrors `cache.py`'s own `get_pinned_slot_pool` anchor
        resolution exactly (ADR-007a §6), so this export's own
        `sample_date`/`day_age` columns describe the same window
        `_gather_pool` actually fetched. Not re-derived from `diagnosed`
        alone, which doesn't carry the "does a *future* pin still anchor
        the window at today" nuance that method's own `is_pinned` check
        applies."""
        now = self._coordinator.now()
        today = now.date()
        if self._coordinator.is_following_latest_diagnostic_slot():
            anchor = today
        else:
            pinned_date = self._coordinator.diagnostic_slot_timestamp().date()
            anchor = min(pinned_date, today)
        return anchor - timedelta(days=window_days - 1)

    def _export_training_pool_rows(
        self,
        settings: RegressionSettings,
        pool: _GatheredPool,
        breakdown: Any,
    ) -> list[dict[str, str]]:
        """The `# training_pool` section — one row per (`offset`,
        `day_index`), decomposed weight components included (ADR-015
        §6). `breakdown` is a `regression.base.WeightBreakdown`
        (annotated `Any` here to avoid a `TYPE_CHECKING`-only import
        purely for a local variable's type, matching this module's own
        `DiagnosedSlot`/`RegressionSettings`/`StringComputationConfig`
        convention for names only ever used as attribute-access
        targets — `build_pool` itself, imported for real above, is the
        only symbol from `regression/base.py` this module's runtime
        code actually needs)."""
        window_days = pool.fc_by_offset[0].shape[1]
        window_start_date = self._export_window_start_date(window_days)

        rows: list[dict[str, str]] = []
        for offset in range(-settings.smoothing_radius, settings.smoothing_radius + 1):
            fc_row = pool.fc_by_offset[offset][0]
            pv_raw_row = pool.pv_by_offset[offset][0]
            pv_corrected_row = pool.corrected_pv_by_offset[offset][0]
            temperature_row = (
                pool.temperature_by_offset[offset][0]
                if pool.temperature_by_offset is not None
                else None
            )
            valid_row = breakdown.valid_mask[offset][0]
            magnitude_row = breakdown.magnitude_weight[offset][0]
            combined_row = breakdown.combined_weight[offset][0]
            time_weight = breakdown.time_weight[offset]
            recency_row = breakdown.recency_weight
            neighbor_excluded = bool(breakdown.neighbor_excluded[offset][0])
            neighbor_scale = float(breakdown.neighbor_scale[offset][0])

            for day_index in range(window_days):
                sample_date = window_start_date + timedelta(days=day_index)
                day_age = (window_days - 1) - day_index
                is_valid = bool(valid_row[day_index])
                rows.append(
                    {
                        "offset": str(offset),
                        "day_index": str(day_index),
                        "sample_date": sample_date.isoformat(),
                        "day_age": str(day_age),
                        "fc_raw": _export_float_or_blank(fc_row[day_index]),
                        "pv_raw": _export_float_or_blank(pv_raw_row[day_index]),
                        "pv_corrected": _export_float_or_blank(pv_corrected_row[day_index]),
                        "temperature_raw": (
                            _export_float_or_blank(temperature_row[day_index])
                            if temperature_row is not None
                            else ""
                        ),
                        "is_valid": "1" if is_valid else "0",
                        "magnitude_weight": repr(float(magnitude_row[day_index])),
                        "time_weight": repr(float(time_weight)),
                        "recency_weight": repr(float(recency_row[day_index])),
                        "neighbor_excluded": "1" if neighbor_excluded else "0",
                        "neighbor_scale": repr(neighbor_scale),
                        "combined_weight": repr(float(combined_row[day_index])),
                    }
                )
        return rows

    def _export_predictions_rows(
        self, predictions: dict[str, float], pv_selected: float | None
    ) -> list[dict[str, str]]:
        """The `# predictions` section — one row per `regression/`
        strategy that has a cached `extra_fit()` prediction this tick.
        `pv_selected`/`accuracy` are blank, not fabricated, for a
        not-yet-elapsed diagnosed slot (mirrors
        `_append_selected_series`'s own contract)."""
        rows: list[dict[str, str]] = []
        for method in string_computation.REGRESSION_STRATEGIES:
            predicted = predictions.get(method)
            if predicted is None:
                # No cached extra_fit() prediction yet for this method
                # this tick (ADR-004 §4's "extra fitting cost only
                # while active" -- e.g. a freshly-switched-on mode's
                # very first tick, before extra_fit() has run once) --
                # omit the row rather than fabricate one.
                continue
            row = {"method": method, "predicted": repr(float(predicted))}
            if pv_selected is not None:
                row["pv_selected"] = repr(float(pv_selected))
                row["accuracy"] = repr(float(diagnostic_accuracy(predicted, pv_selected)))
            else:
                row["pv_selected"] = ""
                row["accuracy"] = ""
            rows.append(row)
        return rows

    def _export_prediction_inputs_rows(
        self,
        fc_selected: float | None,
        target_cell_temperature: float | None,
        pv_selected: float | None,
    ) -> list[dict[str, str]]:
        """The `# prediction_inputs` section — key/value pairs, not a
        wide row, specifically so `target_cell_temperature` can be
        *absent* for a non-temperature-tier string rather than shown as
        a blank column (ADR-015's own schema note)."""
        rows: list[dict[str, str]] = [
            {
                "key": "fc_selected",
                "value": repr(float(fc_selected)) if fc_selected is not None else "",
            }
        ]
        if target_cell_temperature is not None:
            rows.append(
                {
                    "key": "target_cell_temperature",
                    "value": repr(float(target_cell_temperature)),
                }
            )
        rows.append(
            {
                "key": "pv_selected",
                "value": repr(float(pv_selected)) if pv_selected is not None else "",
            }
        )
        return rows

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
        note) — this needs no branching of its own on `is_elapsed`.
        Passes `allow_historical_backfill=True` (ADR-007a §4 Amendment,
        TASK-0037 follow-up): without it, a `forecast_solar`-shaped
        (push-sourced) `sensor_id` — `config.baseline_entity_id`, for a
        string on that provider — never gets its already-elapsed
        history fetched at all, since `get_regression_pools` (the only
        other caller that opts in) never reaches "today", and no other
        caller backfills a push-marked sensor's history unless asked."""
        slot_start = self._coordinator.cache.timestamp_for(index)
        raw = self._coordinator.cache.get_time_range(
            [sensor_id], slot_start, slot_start, on_invalid="raw", allow_historical_backfill=True
        )[sensor_id]
        value = raw[0]
        result = value if isinstance(value, float) else None
        if _DIAGNOSTIC_LOG:
            _LOGGER.warning(
                "DIAG selected_value: sensor_id=%r index=%d slot_start=%s"
                " raw=%r (type=%s) -> result=%r",
                sensor_id,
                index,
                slot_start,
                value,
                type(value).__name__,
                result,
            )
        return result
