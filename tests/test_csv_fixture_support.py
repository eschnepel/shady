"""Tests for `tests/csv_fixture_support.py` (ADR-015 §5/§7, `TASK-0038`) —
the generic `# name`-marker-section parser and comparator. Top-level, like
the module itself: nothing here knows about diagnostic modes.
"""

from __future__ import annotations

import pytest

from tests.csv_fixture_support import compare_sections, parse_csv_sections

_TEXT = "# first\r\na,b\r\n1,2\r\n3,4\r\n\r\n# empty\r\n\r\n# second\r\nx\r\nhello\r\n\r\n"


class TestParseCsvSections:
    def test_returns_a_dict_keyed_by_section_name(self) -> None:
        sections = parse_csv_sections(_TEXT)

        assert sections == {
            "first": [{"a": "1", "b": "2"}, {"a": "3", "b": "4"}],
            "empty": [],
            "second": [{"x": "hello"}],
        }

    def test_duplicate_section_name_raises_naming_file_and_section(self) -> None:
        text = _TEXT + "# first\r\na\r\n9\r\n\r\n"

        with pytest.raises(ValueError, match=r"fixture\.csv.*'first'.*unique"):
            parse_csv_sections(text, source="fixture.csv")

    def test_text_without_any_marker_parses_to_an_empty_dict(self) -> None:
        assert parse_csv_sections("a,b\r\n1,2\r\n") == {}


class TestCompareSections:
    def test_identical_structures_have_no_mismatches(self) -> None:
        sections = parse_csv_sections(_TEXT)

        assert compare_sections(sections, parse_csv_sections(_TEXT)) == []

    def test_numeric_fields_compare_with_relative_tolerance(self) -> None:
        old = {"s": [{"v": "1.0"}]}

        assert compare_sections(old, {"s": [{"v": "1.0000000001"}]}) == []
        assert compare_sections(old, {"s": [{"v": "1.1"}]}) != []

    def test_format_only_numeric_difference_is_not_a_mismatch(self) -> None:
        assert compare_sections({"s": [{"v": "1"}]}, {"s": [{"v": "1.0"}]}) == []

    def test_non_numeric_fields_compare_exactly(self) -> None:
        mismatches = compare_sections({"s": [{"m": "wls2"}]}, {"s": [{"m": "wls3"}]})

        assert len(mismatches) == 1
        assert "'m'" in mismatches[0]

    def test_section_present_on_one_side_only(self) -> None:
        mismatches = compare_sections({"a": []}, {"b": []})

        assert any("'a'" in m and "original" in m for m in mismatches)
        assert any("'b'" in m and "regenerated" in m for m in mismatches)

    def test_row_count_difference(self) -> None:
        mismatches = compare_sections({"s": [{"v": "1"}]}, {"s": [{"v": "1"}, {"v": "2"}]})

        assert len(mismatches) == 1
        assert "row count" in mismatches[0]

    def test_field_present_on_one_side_only(self) -> None:
        mismatches = compare_sections({"s": [{"v": "1"}]}, {"s": [{"v": "1", "w": "2"}]})

        assert len(mismatches) == 1
        assert "'w'" in mismatches[0]


class TestLineEndings:
    def test_bare_lf_parses_identically_to_crlf(self) -> None:
        assert parse_csv_sections(_TEXT.replace("\r\n", "\n")) == parse_csv_sections(_TEXT)
