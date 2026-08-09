#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Re-derive every version claim in the dataset and compare.

This is the check that makes the dataset reviewable. A pull request that
changes a version number without changing its evidence fails here; one
that changes both, correctly, passes.

Each matcher kind is checked against the source that can actually settle
it:

    modules, attributes, builtins,  the cached documentation, via
    methods                         scripts/dating.py
    nodes                           the feature's PEP, whose
                                    Python-Version header has to agree

Syntax with no PEP, and anything the docs never dated, cannot be checked
mechanically. Those entries have to carry `manual` evidence, and this
script reports them as such rather than passing them silently.

An entry that also claims `removed` gets a second line, because it is
making a second claim that a different source settles: the built
interpreters, or the grammar for syntax. That check runs in both
directions. An entry claiming a removal nothing can see is a mismatch,
and so is a name the newest interpreter has stopped resolving on an
entry that says nothing about it, which is what keeps the dataset from
going stale silently the next time Python drops something.

Usage:

    uv run scripts/verify_dataset.py           # check everything
    uv run scripts/verify_dataset.py --verbose # show every entry
"""

import argparse
import sys
import tomllib

from dating import FIRST_PUBLIC_RELEASE, date_symbol, removal_of
from grammar import dated_syntax, removed_syntax
from sources import ROOT, load_peps

DATASET = ROOT / "src" / "sincewhen" / "features.toml"

OK = "ok"
MISMATCH = "mismatch"
UNCHECKABLE = "uncheckable"
MANUAL = "manual"


def load_entries() -> list[dict]:
    return tomllib.loads(DATASET.read_text(encoding="utf-8"))["features"]


def check_symbols(entry: dict, names: list[str]) -> tuple[str, str]:
    """Compare `added` against what the docs say about each target.

    This checks the answer, not the paperwork. The evidence records
    which source settled a claim, but the claim itself has to match what
    the whole pipeline says today, so that changing how the sources are
    reconciled shows up here as a mismatch instead of passing quietly on
    an entry whose evidence still looks tidy.

    Every name a feature matches on has to date to the same release. If
    they do not, the entry is bundling two different features together
    and the version it claims is right for at most one of them.

    Whether the version is a date or a bound is checked too, because
    "1.5" and "1.5 or earlier" are different claims and only one of them
    can be right.
    """
    added = entry["added"]
    bounded = entry.get("or_earlier", False)
    dated = {}
    for name in names:
        verdict = date_symbol(name)
        if verdict.status == "keyword":
            return (
                MISMATCH,
                f"{name} is a keyword, and the only thing the docs index "
                "under that name is a section anchor; date it from the "
                "grammar and cite it with grammar evidence",
            )
        if verdict.status == "conflict":
            return (
                MISMATCH,
                f"{name}: inventory says {verdict.inventory}, "
                f"docs say {verdict.annotation}; settle it with manual evidence",
            )
        if verdict.status == "interpreter-contradicts-docs":
            return (
                MISMATCH,
                f"{name}: the {verdict.interpreter_absent_in} interpreter does "
                f"not resolve it and the {verdict.documented_by} says "
                f"{verdict.documented}; a micro release may have fixed it, or "
                "the build may be missing a library, so settle it with manual "
                "evidence",
            )
        if verdict.status == "source-contradicts-archive":
            return (
                MISMATCH,
                f"{name}: the {verdict.source_absent_in} source does not bind it "
                f"and the {verdict.archive} docs already list it; "
                "settle it with manual evidence",
            )
        if verdict.added is not None:
            dated[name] = verdict.added
            if verdict.added == added and verdict.or_earlier != bounded:
                claimed = "or earlier" if bounded else "exactly"
                found = "a bound" if verdict.or_earlier else "a date"
                return MISMATCH, f"claims {added} {claimed}, but {name} is {found}"

    if not dated:
        return UNCHECKABLE, f"no cached source dates {', '.join(sorted(names))}"

    wrong = {name: found for name, found in dated.items() if found != added}
    if wrong:
        detail = ", ".join(
            f"{name} is {found}" for name, found in sorted(wrong.items())
        )
        return MISMATCH, f"claims {added}, but {detail}"

    undated = sorted(set(names) - set(dated))
    if undated:
        return OK, f"{added} confirmed; {', '.join(undated)} undated by the docs"
    return OK, f"{added} confirmed by the docs"


MATCHERS = ("modules", "attributes", "builtins", "methods", "spellings")


def targets(entry: dict) -> list[str]:
    """Every name one entry matches on, whichever matcher it uses."""
    return [name for field in MATCHERS for name in entry.get(field, ())]


def check_removal(entry: dict) -> tuple[str, str] | None:
    """Re-derive a `removed` claim, or report a removal the entry misses.

    `None` means "nothing to say", which is the answer for the great
    majority of entries: no claim made and none derivable.

    Both directions are checked, because the interesting failure is not
    an entry claiming a removal that did not happen. It is an entry that
    stays silent while the feature goes away underneath it, which is what
    the dataset would do by default the next time Python drops something.

    Grammar-evidenced entries go to `removed_syntax` and everything else
    to the built interpreters, which are the only two methods whose
    absences are proof: see `REMOVAL_EVIDENCE_METHODS` in features.py.

    `manual` removal evidence short-circuits, for the reason `manual`
    always does, and `<>` is why the escape hatch is needed here as well
    as on the addition side.
    """
    claimed = entry.get("removed")
    method = entry.get("removed_evidence", {}).get("method")
    if method == "manual":
        return MANUAL, entry["removed_evidence"]["note"]

    if method == "grammar" or (
        claimed is None and entry.get("evidence", {}).get("method") == "grammar"
    ):
        token = (entry.get("removed_evidence") or entry["evidence"])["symbol"]
        record = removed_syntax().get(token)
        if record is None:
            if claimed is None:
                return None
            return (
                MISMATCH,
                f"claims removal in {claimed}, but {token} is in the newest grammar",
            )
        if claimed is None:
            return (
                MISMATCH,
                f"{token} is in no grammar after {record['present_in']}; "
                f"the entry claims no removal",
            )
        if record["removed"] != claimed:
            return (
                MISMATCH,
                f"claims removal in {claimed}, but {token} was last parsed in "
                f"{record['present_in']} and is gone from {record['removed']}",
            )
        return OK, f"removed in {claimed} confirmed by the grammar"

    found = {name: removal_of(name) for name in targets(entry)}
    gone = {name: record for name, record in found.items() if record is not None}
    if claimed is None:
        if not gone:
            return None
        detail = ", ".join(
            f"{name} last resolves in {record['present_in']}"
            for name, record in sorted(gone.items())
        )
        return MISMATCH, f"the interpreters no longer resolve it: {detail}"
    if not gone:
        return (
            MISMATCH,
            f"claims removal in {claimed}, but no interpreter shows it going away; "
            "settle it with manual removal evidence",
        )
    wrong = {
        name: record["removed"]
        for name, record in gone.items()
        if record["removed"] != claimed
    }
    if wrong:
        detail = ", ".join(f"{name} is {when}" for name, when in sorted(wrong.items()))
        return MISMATCH, f"claims removal in {claimed}, but {detail}"
    return OK, f"removed in {claimed} confirmed by the interpreters"


def check_pep(entry: dict) -> tuple[str, str]:
    """Compare `added` against the PEP's own Python-Version header."""
    peps = load_peps()
    number = str(entry["pep"])
    record = peps.get(number)
    if record is None:
        return UNCHECKABLE, f"PEP {number} is not in the cached index"

    declared = record.get("python_version")
    if not declared:
        return UNCHECKABLE, f"PEP {number} declares no Python-Version"

    # A few PEPs land over several releases and list them all.
    versions = [part.strip() for part in declared.split(",")]
    if entry["added"] not in versions:
        return MISMATCH, f"claims {entry['added']}, but PEP {number} says {declared}"
    return OK, f"{entry['added']} confirmed by PEP {number}"


def check_grammar(entry: dict) -> tuple[str, str]:
    """Compare `added` against CPython's own grammar.

    A token already in the oldest cached grammar can only be bounded, the
    same way a builtin already in the oldest tarball can. Checking the
    flag as well as the version is the point: "1.5" and "1.5 or earlier"
    are different claims and only one of them is right.

    The oldest grammar there is comes from the first public release, and
    a bound there closes itself: `in` and `exprlist` are both in the
    0.9.1 grammar and nothing older exists for them to have come from, so
    those entries say 0.9 rather than "0.9 or earlier". This is the rule
    `dating.py` applies to every other method, spelled out again here
    because the grammar is checked without going through it.
    """
    token = entry["evidence"]["symbol"]
    record = dated_syntax().get(token)
    if record is None:
        return MISMATCH, f"{token} is in no cached grammar"
    bounded = entry.get("or_earlier", False)
    found = record.get("added") or record["floor"]
    if found != entry["added"]:
        where = record.get("added") or f"{record['floor']} or earlier"
        return MISMATCH, f"claims {entry['added']}, but {token} appears in {where}"
    open_bound = "added" not in record and found != FIRST_PUBLIC_RELEASE
    if bounded != open_bound:
        claimed = "or earlier" if bounded else "exactly"
        actual = "a bound" if open_bound else "a date"
        return MISMATCH, f"claims {found} {claimed}, but {token} is {actual}"
    phrase = f"{found} or earlier" if bounded else found
    return OK, f"{phrase} confirmed by the grammar"


def check(entry: dict) -> tuple[str, str]:
    """What the sources say about one entry.

    The evidence decides which source is consulted, since that is what
    the evidence is for. It matters most where a feature has a matcher
    the docs can see and a claim the docs cannot settle:
    `from __future__ import annotations` is a use of a name the
    inventory only started listing in 3.13, so its date comes from
    PEP 563 and the PEP is what gets rechecked.

    `manual` evidence short-circuits the mechanical check, because it
    exists precisely for the claims no source settles: a feature the
    docs never dated, a PEP header that disagrees with what shipped, or
    a version that is a deliberate curation call. Those entries are
    still printed on every run, so an override stays visible rather than
    quietly becoming permanent.
    """
    match entry.get("evidence", {}).get("method"):
        case "manual":
            return MANUAL, entry["evidence"]["note"]
        case "pep":
            return check_pep(entry)
        case "grammar":
            return check_grammar(entry)
    for field in ("modules", "attributes", "builtins", "methods"):
        if entry.get(field):
            return check_symbols(entry, entry[field])
    if entry.get("pep"):
        return check_pep(entry)
    return UNCHECKABLE, "syntax with no PEP; needs manual evidence"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="show every entry")
    parser.add_argument("--only", help="only entries whose id contains this")
    args = parser.parse_args()

    entries = load_entries()
    if args.only:
        entries = [entry for entry in entries if args.only in entry["id"]]

    counts = dict.fromkeys((OK, MISMATCH, UNCHECKABLE, MANUAL), 0)
    removals = 0
    for entry in entries:
        status, detail = check(entry)
        counts[status] += 1
        if status != OK or args.verbose:
            print(f"{status.upper():<12} {entry['id']:<38} {detail}")
        # The second claim gets its own line rather than its own entry.
        # An entry that says a feature arrived in 1.0 and went away in
        # 3.0 is making two statements that two different methods
        # settle, and folding them into one status would let a verified
        # `added` cover for an unchecked `removed`.
        gone = check_removal(entry)
        if gone is None:
            continue
        status, detail = gone
        counts[status] += 1
        removals += 1
        if status != OK or args.verbose:
            print(f"{status.upper():<12} {entry['id']:<38} removed: {detail}")

    print(
        f"\n{counts[OK]} verified, {counts[MANUAL]} manual, "
        f"{counts[MISMATCH]} mismatched, {counts[UNCHECKABLE]} unverifiable, "
        f"{len(entries)} entries and {removals} removal claims",
        file=sys.stderr,
    )
    return 1 if counts[MISMATCH] or counts[UNCHECKABLE] else 0


if __name__ == "__main__":
    raise SystemExit(main())
