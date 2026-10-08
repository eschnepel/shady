"""`tests/csv_fixture_support.py` — the fully generic CSV-section
parser and comparator (ADR-015 §5/§7, `TASK-0038`), shared by
`tests/diagnostics/test_csv_regression_fixtures.py`'s parametrized
runner and, for direct structural self-checks on its own `export_csv`
output, `tests/diagnostics/test_compare_regressions.py`.

Deliberately **top-level**, not nested under `tests/diagnostics/` —
this module knows nothing about diagnostic modes, `DiagnosticMode`, or
any other production concept; it only understands the generic
`# name`-marker-section file format `diagnostics/base.py`'s
`_write_csv_sections` happens to be the first writer of. Any future
package that adopts the same section-marker convention for its own
fixture-based regression tests reuses this module directly rather than
duplicating it under its own `tests/<package>/` sub-package — the same
reasoning ADR-015 §7 already gives for keeping `tests/fixtures/csv_regression/`
itself at the top level rather than nesting it under `tests/diagnostics/`.
Non-test-prefixed on purpose (`csv_fixture_support`, not `test_...`),
so pytest never collects it as a test module itself, and so importing
it here rather than the other way around avoids a `test_*.py` <->
`test_*.py` import cycle between the two files above.

Test-only code, not production — production never needs to read its
own `export_csv` output back. This is the read-side mirror of
`diagnostics/base.py`'s shared `_write_csv_sections` helper; together
they are the only two places the file *format*, as opposed to its
content, is encoded at all.
"""

from __future__ import annotations

import csv
import math
import re


def parse_csv_sections(text: str, *, source: str = "<string>") -> dict[str, list[dict[str, str]]]:
    """Splits `text` on its `# name` marker lines, `csv.DictReader` per
    section. Returns a `dict` keyed by section name (ADR-015 §5's
    2026-09-27 Amendment, not the original draft's `list[tuple[str,
    ...]]`) — making section-name uniqueness structural: a second `#
    name` marker line repeating an already-seen name raises `ValueError`
    naming both `source` (the fixture file, when the caller supplies
    one) and the duplicated section, rather than silently keeping one
    occurrence and discarding the other.

    Both `\\r\\n` (what `_write_csv_sections` emits) and bare `\\n` line
    endings are accepted -- a fixture read back through `Path.read_text()`
    (universal newlines) or checked out with LF by git's `autocrlf` must
    parse exactly like the original download.

    A section with no rows between its marker and the next one (or
    end of file) parses to an empty list — the same "marker line, no
    header, nothing else" shape `_write_csv_sections` itself produces
    for a zero-row section, not an error.
    """
    sections: dict[str, list[dict[str, str]]] = {}
    current_name: str | None = None
    body_lines: list[str] = []

    def flush() -> None:
        if current_name is None:
            return
        trimmed = list(body_lines)
        while trimmed and trimmed[-1] == "":
            trimmed.pop()
        rows: list[dict[str, str]] = []
        if trimmed:
            reader = csv.DictReader(trimmed)
            rows = [dict(row) for row in reader]
        if current_name in sections:
            raise ValueError(
                f"{source}: duplicate CSV section {current_name!r} — section "
                "identifiers must be unique"
            )
        sections[current_name] = rows

    for line in re.split(r"\r?\n", text):
        if line.startswith("# "):
            flush()
            current_name = line[2:]
            body_lines = []
        elif current_name is not None:
            body_lines.append(line)
    flush()
    return sections


def compare_sections(
    old: dict[str, list[dict[str, str]]],
    new: dict[str, list[dict[str, str]]],
    rel_tol: float = 1e-9,
) -> list[str]:
    """Walks both parsed structures section by section, row by row,
    field by field — attempting `float()` on each value and falling
    back to exact string equality — returning human-readable mismatch
    descriptions (empty if none). No section or field name is special-
    cased anywhere in this function (ADR-015 §5): a future mode's own
    fixture support needs no change here at all.
    """
    mismatches: list[str] = []
    for name in sorted(set(old) | set(new)):
        if name not in old:
            mismatches.append(f"section {name!r}: present in regenerated CSV only")
            continue
        if name not in new:
            mismatches.append(f"section {name!r}: present in original CSV only")
            continue
        old_rows = old[name]
        new_rows = new[name]
        if len(old_rows) != len(new_rows):
            mismatches.append(
                f"section {name!r}: row count differs "
                f"(original={len(old_rows)}, regenerated={len(new_rows)})"
            )
            continue
        for row_index, (old_row, new_row) in enumerate(zip(old_rows, new_rows, strict=True)):
            for field in sorted(set(old_row) | set(new_row)):
                if field not in old_row or field not in new_row:
                    mismatches.append(
                        f"section {name!r} row {row_index}: field {field!r} present in only one"
                    )
                    continue
                old_value = old_row[field]
                new_value = new_row[field]
                if not _values_match(old_value, new_value, rel_tol):
                    mismatches.append(
                        f"section {name!r} row {row_index} field {field!r}: "
                        f"{old_value!r} != {new_value!r}"
                    )
    return mismatches


def _values_match(old_value: str, new_value: str, rel_tol: float) -> bool:
    """Exact string equality first (covers every non-numeric field —
    method names, booleans, dates — with no special-casing); falling
    back to a relative-tolerance float comparison only when both sides
    parse as numbers, so a harmless `repr()` formatting difference
    (e.g. `1.0` vs `1`) never fails a fixture over nothing."""
    if old_value == new_value:
        return True
    try:
        old_float = float(old_value)
        new_float = float(new_value)
    except ValueError:
        return False
    return math.isclose(old_float, new_float, rel_tol=rel_tol, abs_tol=1e-12)
