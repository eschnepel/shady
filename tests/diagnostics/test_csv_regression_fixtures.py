"""`tests/diagnostics/test_csv_regression_fixtures.py` — the fully
generic fixture-replay runner (ADR-015 §5/§7, `TASK-0038`): reads every
`*.csv` in the two fixture folders below, dispatches by its own leading
`# diagnostic_mode` value to the matching mode-owned replay function
(the registry below), regenerates the CSV, and compares section by
section against the original — a golden-file regression test of the
export pipeline itself.

Two fixture folders under `tests/fixtures/csv_regression/`:

- `curated/` — real exports a maintainer downloaded and dropped in by
  hand. The regression net proper.
- `synthetic/` — fixtures written by this project's own developers
  (exported from the test scenarios in `test_compare_regressions.py`,
  some deliberately tampered) to test *the test system itself*: that a
  correct fixture passes, and that a wrong one is actually caught.

**The optional `expected` column** (ADR-015 §5, 2026-09-27): a fixture's
`# diagnostic_mode` section may carry a second column, `expected`,
whose value is `PASS` or `FAIL`. Absent or blank means `PASS` — so a
real export, which never writes the column, is a `PASS` fixture by
default. `FAIL` marks a fixture that must be *rejected* (the regenerated
CSV disagrees with it, or its mode is unregistered): the test passes
only if the check genuinely fails, and fails if the fixture unexpectedly
replays cleanly. The column is stripped before comparison — the
regenerated export never has it.

Zero fixtures present is not a failure: no files means no parametrized
cases, an empty, always-green pass — not a skip, not an error.
"""

from __future__ import annotations

import pathlib
from collections.abc import Callable
from dataclasses import dataclass

import pytest

from tests.csv_fixture_support import compare_sections, parse_csv_sections
from tests.diagnostics.test_compare_regressions import _replay_compare_regressions

_FIXTURES_ROOT = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "csv_regression"
_FIXTURE_DIRS = (_FIXTURES_ROOT / "curated", _FIXTURES_ROOT / "synthetic")
#: Where a *failing* `PASS` fixture's freshly-regenerated CSV is left for
#: the maintainer (gitignored, mirrors the fixture folder name) — the
#: only disk write this mechanism ever performs.
_GENERATED_DIR = _FIXTURES_ROOT / "_generated"

_EXPECTED_COLUMN = "expected"

Registry = dict[str, Callable[[dict[str, list[dict[str, str]]]], str]]

#: One entry per diagnostic mode with fixture-replay support (ADR-015
#: §5) — a future mode's own support costs exactly one new line here
#: plus its own `_replay_<mode>` function, no change to anything below.
_REPLAY_REGISTRY: Registry = {
    "compare_regressions": _replay_compare_regressions,
}

_FIXTURE_FILES = sorted(p for d in _FIXTURE_DIRS if d.is_dir() for p in d.glob("*.csv"))


@dataclass(frozen=True)
class FixtureOutcome:
    expected: str
    #: Human-readable reasons the replay disagreed with the fixture; empty
    #: means it replayed cleanly.
    problems: list[str]
    #: The regenerated CSV, or `None` when no replay function ran.
    regenerated_text: str | None


def evaluate_fixture(fixture_path: pathlib.Path, registry: Registry) -> FixtureOutcome:
    """Parse, dispatch, regenerate, compare — without deciding pass/fail
    (that is `check_fixture`'s job, since it depends on `expected`).
    Raises (naming the file) for a fixture that cannot even be read as
    intended: unparseable/duplicated sections, no `# diagnostic_mode`
    section, or an `expected` value that is neither `PASS` nor `FAIL`.
    """
    original_text = fixture_path.read_text(encoding="utf-8")
    original = parse_csv_sections(original_text, source=str(fixture_path))

    mode_rows = original.get("diagnostic_mode")
    assert mode_rows, f"{fixture_path}: missing '# diagnostic_mode' section"
    mode_key = mode_rows[0]["diagnostic_mode"]

    expected = (mode_rows[0].get(_EXPECTED_COLUMN) or "PASS").strip().upper()
    assert expected in ("PASS", "FAIL"), (
        f"{fixture_path}: '{_EXPECTED_COLUMN}' must be PASS or FAIL, got {expected!r}"
    )

    # The regenerated export never carries `expected`; drop it from the
    # original before comparing so it is not reported as a phantom field.
    comparable = {
        **original,
        "diagnostic_mode": [
            {k: v for k, v in row.items() if k != _EXPECTED_COLUMN} for row in mode_rows
        ],
    }

    replay = registry.get(mode_key)
    if replay is None:
        return FixtureOutcome(expected, [f"unregistered diagnostic mode {mode_key!r}"], None)

    regenerated_text = replay(comparable)
    regenerated = parse_csv_sections(regenerated_text, source=f"{fixture_path} (regenerated)")
    return FixtureOutcome(expected, compare_sections(comparable, regenerated), regenerated_text)


def check_fixture(
    fixture_path: pathlib.Path, registry: Registry, generated_dir: pathlib.Path
) -> None:
    """Pass/fail for one fixture, honouring its `expected` column.

    `PASS` (the default): any problem fails the test; if a regenerated
    CSV exists it is written to `generated_dir/<folder>/<filename>`, ready
    to copy over the stale fixture if the change was intentional.
    `FAIL`: the fixture must be rejected — replaying cleanly is the failure.
    Parameterised on `registry`/`generated_dir` so this logic is itself
    testable without touching a real fixture folder.
    """
    outcome = evaluate_fixture(fixture_path, registry)

    if outcome.expected == "FAIL":
        if not outcome.problems:
            pytest.fail(
                f"{fixture_path.name}: marked expected=FAIL but the regenerated CSV "
                "matched it — the test system failed to catch a bad fixture"
            )
        return

    if outcome.problems:
        location = ""
        if outcome.regenerated_text is not None:
            target = generated_dir / fixture_path.parent.name / fixture_path.name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(outcome.regenerated_text, encoding="utf-8", newline="")
            location = (
                f"; see {target} for the full regenerated file, ready to copy over "
                "the fixture if this change was intentional"
            )
        details = "\n".join(outcome.problems)
        pytest.fail(
            f"{fixture_path.name}: regenerated CSV differs from the fixture "
            f"({len(outcome.problems)} problem(s)){location}:\n{details}"
        )


# Defined only when at least one fixture exists: an empty
# `@pytest.mark.parametrize` yields one *skipped* placeholder case under
# pytest's default `empty_parameter_set_mark`, but zero fixtures must
# contribute zero cases -- neither a failure nor a skip (task Acceptance
# Criteria).
if _FIXTURE_FILES:

    @pytest.mark.parametrize(
        "fixture_path", _FIXTURE_FILES, ids=lambda p: f"{p.parent.name}/{p.name}"
    )
    def test_fixture_replays_as_expected(fixture_path: pathlib.Path) -> None:
        """Given a fixture CSV, When it is replayed through its mode's own
        function, Then it behaves as its `expected` column says (default
        `PASS`) — see `check_fixture`."""
        check_fixture(fixture_path, _REPLAY_REGISTRY, _GENERATED_DIR)


class TestCheckFixture:
    """`check_fixture`'s own behaviour, against stub replay functions --
    independent of any real fixture on disk."""

    _BODY = "# s\r\nv\r\n1.0\r\n\r\n"

    @staticmethod
    def _mode_section(expected: str | None) -> str:
        if expected is None:
            return "# diagnostic_mode\r\ndiagnostic_mode\r\nstub\r\n\r\n"
        return f"# diagnostic_mode\r\ndiagnostic_mode,expected\r\nstub,{expected}\r\n\r\n"

    def _fixture(self, tmp_path: pathlib.Path, expected: str | None = None) -> pathlib.Path:
        path = tmp_path / "case.csv"
        path.write_text(self._mode_section(expected) + self._BODY, encoding="utf-8", newline="")
        return path

    def _replay(self, value: str = "1.0") -> Registry:
        text = self._mode_section(None) + self._BODY.replace("1.0", value)
        return {"stub": lambda _sections: text}

    def test_matching_replay_passes_and_writes_nothing(self, tmp_path: pathlib.Path) -> None:
        generated = tmp_path / "_generated"

        check_fixture(self._fixture(tmp_path), self._replay(), generated)

        assert not generated.exists()

    def test_explicit_pass_column_is_ignored_by_the_comparison(
        self, tmp_path: pathlib.Path
    ) -> None:
        check_fixture(self._fixture(tmp_path, "PASS"), self._replay(), tmp_path / "_generated")

    def test_blank_expected_defaults_to_pass(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(pytest.fail.Exception, match="differs"):
            check_fixture(self._fixture(tmp_path, ""), self._replay("2.0"), tmp_path / "_g")

    def test_mismatch_fails_and_leaves_the_regenerated_file(self, tmp_path: pathlib.Path) -> None:
        generated = tmp_path / "_generated"

        with pytest.raises(pytest.fail.Exception, match=r"(?s)case\.csv.*'v'"):
            check_fixture(self._fixture(tmp_path), self._replay("2.0"), generated)

        left = generated / tmp_path.name / "case.csv"
        assert "2.0" in left.read_text(encoding="utf-8")

    def test_unregistered_mode_fails_naming_file_and_mode(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(pytest.fail.Exception, match=r"(?s)case\.csv.*unregistered.*'stub'"):
            check_fixture(self._fixture(tmp_path), {}, tmp_path / "_generated")

    def test_expected_fail_passes_when_the_replay_disagrees(self, tmp_path: pathlib.Path) -> None:
        generated = tmp_path / "_generated"

        check_fixture(self._fixture(tmp_path, "FAIL"), self._replay("2.0"), generated)

        assert not generated.exists()  # an expected failure leaves nothing behind

    def test_expected_fail_passes_for_an_unregistered_mode(self, tmp_path: pathlib.Path) -> None:
        check_fixture(self._fixture(tmp_path, "fail"), {}, tmp_path / "_generated")

    def test_expected_fail_that_replays_cleanly_is_itself_a_failure(
        self, tmp_path: pathlib.Path
    ) -> None:
        with pytest.raises(pytest.fail.Exception, match=r"expected=FAIL.*failed to catch"):
            check_fixture(self._fixture(tmp_path, "FAIL"), self._replay(), tmp_path / "_g")

    def test_invalid_expected_value_is_rejected(self, tmp_path: pathlib.Path) -> None:
        with pytest.raises(AssertionError, match=r"case\.csv.*PASS or FAIL.*'MAYBE'"):
            check_fixture(self._fixture(tmp_path, "MAYBE"), self._replay(), tmp_path / "_g")

    def test_missing_diagnostic_mode_section_fails(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "bad.csv"
        path.write_text(self._BODY, encoding="utf-8", newline="")

        with pytest.raises(AssertionError, match=r"bad\.csv.*missing"):
            check_fixture(path, self._replay(), tmp_path / "_g")

    def test_duplicate_section_in_a_fixture_fails_loudly(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "dup.csv"
        path.write_text(
            self._mode_section(None) + self._BODY + self._BODY, encoding="utf-8", newline=""
        )

        with pytest.raises(ValueError, match=r"dup\.csv.*'s'"):
            check_fixture(path, self._replay(), tmp_path / "_g")

    def test_the_real_registry_knows_compare_regressions(self) -> None:
        assert "compare_regressions" in _REPLAY_REGISTRY
