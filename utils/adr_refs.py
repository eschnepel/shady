"""Check and rewrite ``ADR-nnn §x`` references (ADR-000 §10).

Usage (from the repository root, stdlib only)::

    python utils/adr_refs.py                 # check every reference in *.md and *.py
    python utils/adr_refs.py -v              # also list every double hop
    python utils/adr_refs.py --adr 004       # report only references to ADR-004
    python utils/adr_refs.py --rewrite       # dry run: show redirects a find/replace can remove
    python utils/adr_refs.py --rewrite --write --ext md   # apply them to Markdown files

A reference resolves directly when the target ADR has a heading ``## n`` / ``### n`` for it. A
section that moved or was removed is listed in the target ADR's ``## Redirects`` table
(``| old | new |``, new being ``§y`` or ``ADR-nnnx §y``); a reference that only resolves through
that table is a *double hop*. Exit status 1 means at least one reference does not resolve.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", ".venv", ".mypy_cache", ".ruff_cache", "node_modules", "__pycache__"}
SELF = Path(__file__).resolve()

# "ADR-004 §2a", "ADR-004 §2a/§2f", "ADR-004 §2a/2f", "ADR-004 §2c–§2i", "ADR-004 §1a, §5"
REF = re.compile(
    r"ADR-0*(\d+[a-z]?)\s*(§\s*\d+[a-z]?"
    r"(?:(?:\s*[,/–]\s*§\s*\d+[a-z]?)|(?:\s*/\s*\d+[a-z]\b)|(?:\s+and\s+§\s*\d+[a-z]?))*)"
)
SECTION = re.compile(r"\d+[a-z]?")
TARGET = re.compile(r"(?:ADR-0*(\d+[a-z]?)\s*)?§\s*(\d+[a-z]?)")
HEADING = re.compile(r"#{2,4}\s+(\d+[a-z]?)\b")
DONE_TASK = re.compile(r"^- \*\*Status:\*\* done", re.MULTILINE)


@dataclass(frozen=True)
class Target:
    adr: str
    section: str


@dataclass
class Adr:
    headings: set[str]
    redirects: dict[str, list[Target]]


def adr_key(name: str) -> str:
    """Normalise ``004`` / ``4`` / ``007a`` to a comparable key."""
    return name.lstrip("0") or "0"


def load_adrs() -> dict[str, Adr]:
    adrs: dict[str, Adr] = {}
    for path in sorted((ROOT / "adr").glob("[0-9]*.md")):
        match = re.match(r"(\d+[a-z]?)-", path.name)
        if match is None:
            continue
        key = adr_key(match.group(1))
        adr = Adr(headings=set(), redirects={})
        in_redirects = False
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                in_redirects = line.strip().lower() == "## redirects"
            heading = HEADING.match(line)
            if heading:
                adr.headings.add(heading.group(1))
            elif in_redirects and line.startswith("|"):
                cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
                old = re.fullmatch(r"§\s*(\d+[a-z]?)", cells[0]) if len(cells) >= 2 else None
                if old:
                    adr.redirects[old.group(1)] = [
                        Target(adr_key(a) if a else key, s) for a, s in TARGET.findall(cells[1])
                    ]
        adrs[key] = adr
    return adrs


def source_files() -> list[Path]:
    return [
        path
        for pattern in ("*.md", "*.py")
        for path in ROOT.rglob(pattern)
        if path.resolve() != SELF and not SKIP_DIRS.intersection(path.relative_to(ROOT).parts)
    ]


def locate(adrs: dict[str, Adr], key: str, section: str) -> str:
    """Return ``ok``, ``hop`` or ``bad`` for one reference."""
    adr = adrs[key]
    if section in adr.headings:
        return "ok"
    return "hop" if section in adr.redirects else "bad"


def check(adrs: dict[str, Adr], only: str | None, verbose: bool) -> int:
    counts: Counter[str] = Counter()
    bad: list[str] = []
    hops: list[str] = []
    for path in source_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in REF.finditer(text):
            key = adr_key(match.group(1))
            if key not in adrs or (only and key != adr_key(only)):
                continue
            where = f"{path.relative_to(ROOT)}:{text.count(chr(10), 0, match.start()) + 1}"
            for section in sorted(set(SECTION.findall(match.group(2)))):
                outcome = locate(adrs, key, section)
                counts[outcome] += 1
                if outcome != "ok":
                    line = f"{where}  ADR-{_pad(key)} §{section}"
                    (bad if outcome == "bad" else hops).append(line)
    print(f"references checked: {sum(counts.values())}")
    print(f"  direct: {counts['ok']}  double hops: {counts['hop']}  unresolved: {counts['bad']}")
    for line in bad:
        print(f"UNRESOLVED  {line}")
    if verbose:
        for line in hops:
            print(f"DOUBLE HOP  {line}")
    return 1 if bad else 0


def rewrite(adrs: dict[str, Adr], only: str | None, ext: str | None, write: bool) -> int:
    """Replace ``ADR-a §x`` by ``ADR-b §y`` where a redirect has exactly one target.

    Expressions that mix targets, contain a range (``–``) or hit a multi-target redirect are
    listed as manual work instead of being touched. Finished tasks (``Status: done``) are audit
    trail and are never rewritten.
    """
    changed = manual = 0
    for path in source_files():
        if ext and path.suffix != f".{ext}":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.relative_to(ROOT).parts[0] == "tasks" and DONE_TASK.search(text):
            continue  # a finished task is audit trail: it quotes the sections as they were

        def replace(match: re.Match[str], path: Path = path, text: str = text) -> str:
            nonlocal changed, manual
            key = adr_key(match.group(1))
            if key not in adrs or (only and key != adr_key(only)):
                return match.group(0)
            sections = SECTION.findall(match.group(2))
            if not any(locate(adrs, key, s) == "hop" for s in sections):
                return match.group(0)
            new: list[Target] = []
            for section in sections:
                if locate(adrs, key, section) == "ok":
                    new.append(Target(key, section))
                elif len(adrs[key].redirects[section]) == 1:
                    new.append(adrs[key].redirects[section][0])
                else:
                    new = []
                    break
            if not new or "–" in match.group(2) or len({t.adr for t in new}) != 1:
                manual += 1
                line = text.count("\n", 0, match.start()) + 1
                print(f"MANUAL  {path.relative_to(ROOT)}:{line}  {match.group(0)!r}")
                return match.group(0)
            changed += 1
            sep = "/" if "/" in match.group(2) else ", "
            return f"ADR-{_pad(new[0].adr)} " + sep.join(f"§{t.section}" for t in new)

        new_text = REF.sub(replace, text)
        if write and new_text != text:
            path.write_text(new_text, encoding="utf-8")
    verb = "rewritten" if write else "would be rewritten (dry run, add --write)"
    print(f"{changed} reference expressions {verb}; {manual} need manual work")
    return 0


def _pad(key: str) -> str:
    """``7a`` -> ``007a``."""
    digits = re.match(r"\d+", key)
    assert digits is not None
    return digits.group(0).zfill(3) + key[digits.end() :]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else None)
    parser.add_argument("-v", "--verbose", action="store_true", help="list double hops too")
    parser.add_argument("--adr", help="only references to this ADR, e.g. 004 or 007a")
    parser.add_argument("--rewrite", action="store_true", help="remove double hops by find/replace")
    parser.add_argument("--write", action="store_true", help="with --rewrite: apply the changes")
    parser.add_argument("--ext", help="with --rewrite: only files with this extension (md, py)")
    args = parser.parse_args()
    adrs = load_adrs()
    if args.rewrite:
        return rewrite(adrs, args.adr, args.ext, args.write)
    return check(adrs, args.adr, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
