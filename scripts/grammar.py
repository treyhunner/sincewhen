#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Date syntax by diffing CPython's grammar across releases.

Documentation cannot settle syntax: there is no object to look up in an
inventory and no module page to grep. PEP headers are the usual stand-in
and they record intent rather than what shipped, which is how PEP 3129
comes to say class decorators are 3.0 when 2.6 has them.

The grammar has no opinion. A keyword or rule absent from one release's
grammar and present in the next was added in that release, and the two
files are archived at every release tag.

Two chains, because the parser changed. `Grammar/Grammar` is the pgen
grammar, from 1.0 to 3.9; `Grammar/python.gram` is the PEG grammar, from
3.9 on. Python 3.9 shipped both, so each chain has a clean end and they
are never diffed against each other.

Usage:

    uv run scripts/grammar.py --grep lambda
    uv run scripts/grammar.py --version 3.8
    uv run scripts/grammar.py --token "'nonlocal'"
"""

import argparse
import re
from functools import cache

from sources import GRAMMAR_TAGS, PEG_TAGS, grammar_path, html_root

# A quoted terminal: the keywords and operators the grammar names. The
# PEG grammar embeds C in its actions, and that C is full of quoted
# strings, so a terminal has to be short and free of whitespace to
# count.
TERMINAL = re.compile(r"""['"](?P<text>[^'"\s]{1,12})['"]""")

# A rule definition at the start of a line, in either grammar format.
RULE = re.compile(r"^(?P<name>[a-z_][a-z0-9_]*)\s*(\[[^\]]*\])?\s*:", re.MULTILINE)

# Rules the PEG grammar adds for its own bookkeeping rather than for
# anything a user can write.
PEG_NOISE = frozenset(
    {"invalid", "start", "interactive", "eval", "func_type", "fstring"}
)


def _read(version: str, peg: bool) -> str:
    path = grammar_path(version, peg)
    if not path.exists():
        raise SystemExit("No cached grammars. Run: uv run scripts/fetch_docs.py")
    return path.read_text(encoding="utf-8", errors="replace")


def _oldest() -> str:
    """The 0.9.1 grammar, which lives in the source tarball."""
    path = html_root("0.9") / "python-0.9.1" / "src" / "Grammar"
    return path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""


@cache
def vocabulary(version: str, peg: bool = False) -> frozenset[str]:
    """Every terminal and rule name in one release's grammar.

    Terminals are kept quoted so that the keyword `'lambda'` cannot be
    confused with a rule that happens to be called `lambda`.
    """
    text = _oldest() if version == "0.9" else _read(version, peg)
    found = {f"'{match['text']}'" for match in TERMINAL.finditer(text)}
    found |= {
        match["name"]
        for match in RULE.finditer(text)
        if not any(match["name"].startswith(noise) for noise in PEG_NOISE)
    }
    return frozenset(found)


def _chain(versions: list[str], peg: bool) -> dict[str, dict[str, str]]:
    baseline, *rest = versions
    seen = set(vocabulary(baseline, peg))
    dated = {name: {"floor": baseline} for name in seen}

    previous = baseline
    for version in rest:
        for name in vocabulary(version, peg) - seen:
            dated[name] = {
                "added": version,
                "absent_in": previous,
                "present_in": version,
            }
        seen |= vocabulary(version, peg)
        previous = version
    return dated


@cache
def dated_syntax() -> dict[str, dict[str, str]]:
    """First release each grammar token appears in.

    The PEG chain only gets to date what it alone can see. Anything the
    pgen chain already knows about keeps that answer, since the pgen
    chain reaches back to 1.0 and the PEG one starts at 3.9.
    """
    pgen = _chain(["0.9", *GRAMMAR_TAGS], peg=False)
    peg = _chain(list(PEG_TAGS), peg=True)
    return {name: record for name, record in peg.items() if name not in pgen} | pgen


def describe(record: dict[str, str]) -> str:
    return record.get("added") or f"{record['floor']} or earlier"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grep", help="tokens containing this")
    parser.add_argument("--version", help="tokens first seen in this release")
    parser.add_argument("--token", help="one exact token, quoted as in the grammar")
    args = parser.parse_args()

    dated = dated_syntax()

    if args.token:
        record = dated.get(args.token)
        print(f"{args.token}: {describe(record) if record else 'not in any grammar'}")
        return 0 if record else 1

    if args.version:
        names = sorted(n for n, r in dated.items() if r.get("added") == args.version)
        print("\n".join(names))
        print(f"\n{len(names)} tokens new in {args.version}")
        return 0

    for name, record in sorted(dated.items()):
        if not args.grep or args.grep in name:
            print(f"{name:<28} {describe(record)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
