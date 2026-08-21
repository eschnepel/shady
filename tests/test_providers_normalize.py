from __future__ import annotations

from datetime import datetime

from ._module_loader import load_module


normalize = load_module("shady.providers.normalize", "providers/normalize.py")


def test_normalize_mapping_and_list_shapes_to_canonical_series():
    start = datetime(2026, 8, 21, 12, 0)
    mapping = {
        start.isoformat(): 10,
        (start.replace(minute=5)).isoformat(): 20,
    }
    rows = [
        {"datetime": start.isoformat(), "value": 10},
        {"datetime": start.replace(minute=5).isoformat(), "value": 20},
    ]

    assert normalize.normalize_series(mapping) == [(start, 10.0), (start.replace(minute=5), 20.0)]
    assert normalize.normalize_series(rows) == [(start, 10.0), (start.replace(minute=5), 20.0)]


def test_normalize_inverts_cloud_coverage():
    start = datetime(2026, 8, 21, 12, 0)
    rows = [{"datetime": start.isoformat(), "cloud_coverage": 25}]

    assert normalize.normalize_series(rows, source_kind="weather-cloud") == [(start, 75.0)]
