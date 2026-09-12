"""Zero-mocking tests for `providers/normalize.py` (ADR-009 §2, ADR-000 §6).

Loaded via direct file-path import (ADR-000 §6) so `providers/base.py`'s
runtime dependency chain stays free of `custom_components/shady/__init__.py`
(and therefore `homeassistant.*`).
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

_SHADY_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "shady"


def _load(relative_path: str, module_name: str) -> ModuleType:
    path = _SHADY_DIR / relative_path
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


_load("providers/base.py", "shady.providers.base")
_normalize_mod = _load("providers/normalize.py", "shady.providers.normalize")


class TestResolveDictSeries:
    """Given a {timestamp: number}-shaped attribute (Forecast.Solar-like),
    resolve_dict_series returns the canonical series (ADR-009 §1)."""

    def test_dict_shape_resolves(self) -> None:
        raw = {
            "2026-01-01T10:00:00+00:00": 100.0,
            "2026-01-01T10:05:00+00:00": 110.5,
        }
        result = _normalize_mod.resolve_dict_series(raw)
        assert result == [
            (datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 100.0),
            (datetime(2026, 1, 1, 10, 5, tzinfo=UTC), 110.5),
        ]

    def test_non_mapping_returns_none(self) -> None:
        assert _normalize_mod.resolve_dict_series([1, 2, 3]) is None

    def test_empty_dict_returns_none(self) -> None:
        assert _normalize_mod.resolve_dict_series({}) is None

    def test_unparseable_key_returns_none(self) -> None:
        assert _normalize_mod.resolve_dict_series({"not-a-timestamp": 1.0}) is None

    def test_non_numeric_value_returns_none(self) -> None:
        assert _normalize_mod.resolve_dict_series({"2026-01-01T10:00:00+00:00": "n/a"}) is None


class TestResolveListSeries:
    """Given a list-of-dicts-shaped attribute (Solcast-like), resolve_list_series
    returns the canonical series via known key-name aliases (ADR-009 §1/§2)."""

    def test_solcast_like_shape_resolves(self) -> None:
        raw = [
            {"period_start": "2026-01-01T10:00:00+00:00", "pv_estimate": 1.23},
            {"period_start": "2026-01-01T10:30:00+00:00", "pv_estimate": 2.5},
        ]
        result = _normalize_mod.resolve_list_series(raw)
        assert result == [
            (datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 1.23),
            (datetime(2026, 1, 1, 10, 30, tzinfo=UTC), 2.5),
        ]

    def test_alternate_alias_keys_resolve(self) -> None:
        raw = [{"time": "2026-01-01T10:00:00+00:00", "wh": 500.0}]
        result = _normalize_mod.resolve_list_series(raw)
        assert result == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 500.0)]

    def test_value_key_hint_selects_specific_key(self) -> None:
        raw = [
            {
                "datetime": "2026-01-01T10:00:00+00:00",
                "sunshine_duration": 900.0,
                "temperature": 12.0,
            }
        ]
        result = _normalize_mod.resolve_list_series(raw, value_key_hint="sunshine_duration")
        assert result == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 900.0)]

    def test_no_recognized_value_key_returns_none(self) -> None:
        raw = [{"datetime": "2026-01-01T10:00:00+00:00", "condition": "sunny"}]
        assert _normalize_mod.resolve_list_series(raw) is None

    def test_no_recognized_timestamp_key_returns_none(self) -> None:
        raw = [{"foo": "2026-01-01T10:00:00+00:00", "value": 1.0}]
        assert _normalize_mod.resolve_list_series(raw) is None

    def test_empty_list_returns_none(self) -> None:
        assert _normalize_mod.resolve_list_series([]) is None

    def test_string_input_returns_none(self) -> None:
        assert _normalize_mod.resolve_list_series("not-a-list") is None

    def test_first_entry_not_a_mapping_returns_none(self) -> None:
        assert _normalize_mod.resolve_list_series([1, 2, 3]) is None

    def test_a_later_entry_missing_a_key_returns_none(self) -> None:
        # The first entry alone decides which timestamp_key/value_key
        # apply (both present here) — a later entry lacking one of them
        # invalidates the whole series rather than being skipped, same
        # "all or nothing" contract `resolve_dict_series` has.
        raw = [
            {"datetime": "2026-01-01T10:00:00+00:00", "value": 1.0},
            {"datetime": "2026-01-01T10:05:00+00:00"},  # missing "value"
        ]
        assert _normalize_mod.resolve_list_series(raw) is None

    def test_a_later_entry_with_an_unparseable_timestamp_returns_none(self) -> None:
        raw = [
            {"datetime": "2026-01-01T10:00:00+00:00", "value": 1.0},
            {"datetime": "not-a-timestamp", "value": 2.0},
        ]
        assert _normalize_mod.resolve_list_series(raw) is None

    def test_a_later_entry_with_a_non_numeric_value_returns_none(self) -> None:
        raw = [
            {"datetime": "2026-01-01T10:00:00+00:00", "value": 1.0},
            {"datetime": "2026-01-01T10:05:00+00:00", "value": "n/a"},
        ]
        assert _normalize_mod.resolve_list_series(raw) is None


class TestParseTimestamp:
    """`parse_timestamp` (ADR-009 §3's scoring signal) is only ever
    exercised indirectly above, through `resolve_dict_series`/`resolve_
    list_series` — direct coverage of its own three short-circuit
    branches."""

    def test_already_a_datetime_is_returned_directly(self) -> None:
        already_parsed = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        assert _normalize_mod.parse_timestamp(already_parsed) is already_parsed

    def test_non_string_non_datetime_returns_none(self) -> None:
        assert _normalize_mod.parse_timestamp(12345) is None

    def test_blank_string_returns_none(self) -> None:
        assert _normalize_mod.parse_timestamp("   ") is None


class TestNormalizeCandidateSeriesUnrecognizedShape:
    """`normalize_candidate_series`'s own final `return []` — reached
    only if `shape` is somehow none of the four `BaselineShape` values
    at runtime (e.g. stale config data from a version with a shape this
    version no longer recognizes) — the same "never raises outside its
    normal operating range" contract the module docstring states for
    the recognized-shape branches above."""

    def test_unrecognized_shape_string_returns_empty(self) -> None:
        result = _normalize_mod.normalize_candidate_series("some_future_shape", {"x": 1.0})
        assert result == []


class TestInvertCloudCoverage:
    """Given cloud-coverage percentage values, invert_cloud_coverage
    inverts them into a positive clear-sky proxy (ADR-009 §1)."""

    def test_default_scale(self) -> None:
        assert _normalize_mod.invert_cloud_coverage(30.0) == 70.0

    def test_zero_cloud_is_full_scale(self) -> None:
        assert _normalize_mod.invert_cloud_coverage(0.0) == 100.0

    def test_custom_scale(self) -> None:
        assert _normalize_mod.invert_cloud_coverage(2.0, scale=8.0) == 6.0


class TestNormalizeCandidateSeries:
    """Given any recognized shape, normalize_candidate_series (the one
    canonical mapping function, ADR-012 §1) returns the same canonical
    series shape regardless of source shape or polarity (this task's own
    acceptance criterion)."""

    def test_sensor_dict_shape(self) -> None:
        raw = {"2026-01-01T10:00:00+00:00": 42.0}
        result = _normalize_mod.normalize_candidate_series("sensor_dict", raw)
        assert result == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 42.0)]

    def test_sensor_list_shape(self) -> None:
        raw = [{"start": "2026-01-01T10:00:00+00:00", "power": 42.0}]
        result = _normalize_mod.normalize_candidate_series("sensor_list", raw)
        assert result == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 42.0)]

    def test_weather_sunshine_shape_not_inverted(self) -> None:
        raw = [{"datetime": "2026-01-01T10:00:00+00:00", "sunshine_duration": 600.0}]
        result = _normalize_mod.normalize_candidate_series("weather_sunshine", raw)
        assert result == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 600.0)]

    def test_weather_cloud_shape_is_inverted(self) -> None:
        raw = [{"datetime": "2026-01-01T10:00:00+00:00", "cloud_coverage": 25.0}]
        result = _normalize_mod.normalize_candidate_series("weather_cloud", raw)
        assert result == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 75.0)]

    def test_weather_cloud_total_alias(self) -> None:
        raw = [{"datetime": "2026-01-01T10:00:00+00:00", "cloud_coverage_total": 10.0}]
        result = _normalize_mod.normalize_candidate_series("weather_cloud", raw)
        assert result == [(datetime(2026, 1, 1, 10, 0, tzinfo=UTC), 90.0)]

    def test_unrecognized_raw_for_shape_returns_empty_not_raise(self) -> None:
        assert _normalize_mod.normalize_candidate_series("sensor_dict", "garbage") == []
        assert _normalize_mod.normalize_candidate_series("weather_cloud", []) == []
