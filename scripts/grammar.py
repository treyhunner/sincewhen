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


def _removed(versions: list[str], peg: bool) -> dict[str, dict[str, str]]:
    """Last release each token appears in, where that is not the last one.

    The mirror of `_chain`, and the same argument: a grammar is the list
    the parser is generated from rather than a description of one, so a
    token missing from it is a token that release cannot parse.

    Computed per chain and never across the pair. Python 3.9 ships both
    grammars, and the PEG one spells a great deal differently, so
    diffing pgen's 3.9 against PEG's 3.9 would report a few hundred
    removals in a release that removed nothing. The end of a chain is
    therefore silence rather than a removal: a token still present in
    pgen's last release is a token this cannot speak about, and the PEG
    chain is what answers for it.

    Terminals only, and this is the load-bearing half. A quoted terminal
    is a thing somebody writes, so its disappearance is a fact about the
    language. A rule name is what the grammar file calls a piece of
    itself, and CPython renames those freely: `dictmaker` is in no
    grammar after 2.7 because 3.0 renamed it `dictorsetmaker`, and dict
    displays are fine. Left unfiltered that reported a removal for
    `{'k': 1}`, along with two dozen others of the same kind
    (`listmaker`, `fpdef`, `old_lambdef`, `with_var`). Additions do not
    need the distinction, because a renamed rule looks like a new one and
    nothing in the dataset cites a rule it did not go and read.

    What this cannot see is a token the grammar keeps and the compiler
    rejects, which is not hypothetical: `<>` is in every 3.x pgen grammar
    up to 3.9 and is a syntax error in all of them, because PEP 401 left
    it in for `from __future__ import barry_as_FLUFL`. So a removal here
    is the release the parser stopped knowing the token, and where
    something else stopped accepting it first, that is a question for a
    human.
    """
    last: dict[str, str] = {}
    for version in versions:
        for name in vocabulary(version, peg):
            if name.startswith("'"):
                last[name] = version
    newest = versions[-1]
    gone = {}
    for name, present_in in last.items():
        if present_in == newest:
            continue
        # The release after the last one that has it, which is both the
        # release it was removed in and the absent half of the bracket.
        # A token that went away and came back has its *last* run read
        # here, so 3.0 and 3.1 need no forgiving on this side: a token
        # missing from those two and back in 3.2 ends its run at the
        # newest release and is reported as removed by nobody.
        absent_in = versions[versions.index(present_in) + 1]
        gone[name] = {
            "removed": absent_in,
            "present_in": present_in,
            "absent_in": absent_in,
        }
    return gone


@cache
def removed_syntax() -> dict[str, dict[str, str]]:
    """The release each grammar token stopped being parsed in.

    The pgen chain answers for everything it can see, since it is the one
    that reaches back to 0.9.1 and covers every removal Python 3 made.
    The PEG chain only speaks about tokens pgen never had, so that a
    token the PEG grammar spells differently is not reported as removed
    from a release that still parses it.
    """
    pgen = _removed(["0.9", *GRAMMAR_TAGS], peg=False)
    peg = _removed(list(PEG_TAGS), peg=True)
    known = set(dated_syntax())
    return pgen | {name: record for name, record in peg.items() if name not in known}


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
    parser.add_argument(
        "--removed", action="store_true", help="tokens no current grammar has"
    )
    args = parser.parse_args()

    dated = dated_syntax()
    gone = removed_syntax()

    if args.removed:
        for name, record in sorted(gone.items()):
            print(f"{name:<28} {describe(dated[name])} to {record['present_in']}")
        print(f"\n{len(gone)} tokens removed")
        return 0

    if args.token:
        record = dated.get(args.token)
        detail = describe(record) if record else "not in any grammar"
        if (removal := gone.get(args.token)) is not None:
            detail += f", removed in {removal['removed']}"
        print(f"{args.token}: {detail}")
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
