#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Date documented stdlib objects by diffing Sphinx inventories.

Every documented module, class, function, method and attribute appears in
`objects.inv`. A symbol that is absent from one release's inventory and
present in the next was added in that next release, which is a claim that
can be rechecked from two archived URLs rather than taken on trust.

The 3.x inventories are the spine, because 3.0 through 3.14 is a single
linear history. Python 3.0 forked from 2.6, so the 2.6 and 2.7
inventories are a *separate* line: a symbol first seen in 2.7 is not
newer than one seen in 3.0. That is why this script never chains the two
lines together, and why anything already present in 3.0 comes back as
undated rather than as "added in 3.0".

Usage:

    uv run scripts/inventory.py                 # summary per version
    uv run scripts/inventory.py --version 3.11  # what 3.11 added
    uv run scripts/inventory.py --grep pairwise # find one symbol
    uv run scripts/inventory.py --json out.json # every dated symbol
"""

import argparse
import json
import sys
from collections.abc import Iterator

from sources import load_inventories

# The 3.x line, in release order. Anything present in the first entry is
# older than this line can see and is reported as undated.
SPINE = (
    "3.0",
    "3.1",
    "3.2",
    "3.3",
    "3.4",
    "3.5",
    "3.6",
    "3.7",
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "3.13",
    "3.14",
)

# The 2.x line, kept separate from the spine on purpose.
LEGACY = ("2.6", "2.7")

# Roles worth reporting. The rest are docs plumbing (labels, terms,
# command-line options) rather than things code can use.
INTERESTING_ROLES = frozenset(
    {
        "py:module",
        "py:function",
        "py:class",
        "py:method",
        "py:attribute",
        "py:data",
        "py:exception",
        "py:decorator",
        "py:classmethod",
        "py:staticmethod",
        "py:property",
    }
)

DOCS_URL = "https://docs.python.org/{version}/{uri}"


def dated_symbols(inventories: dict[str, dict[str, str]], line: tuple[str, ...]):
    """First appearance of every symbol along one release line.

    The oldest release in the line is the baseline: its symbols are
    already there when the line starts, so they cannot be dated from it.
    """
    available = [version for version in line if version in inventories]
    if len(available) < 2:
        return {}

    baseline, *rest = available
    seen = set(inventories[baseline])
    dated = {}
    previous = baseline
    for version in rest:
        for symbol, uri in inventories[version].items():
            if symbol not in seen:
                dated[symbol] = {
                    "symbol": symbol,
                    "added": version,
                    "absent_in": previous,
                    "present_in": version,
                    "uri": uri,
                }
        seen.update(inventories[version])
        previous = version
    return dated


def interesting(dated: dict[str, dict]) -> Iterator[dict]:
    for record in dated.values():
        role, _, name = record["symbol"].partition(" ")
        if role not in INTERESTING_ROLES:
            continue
        # Deprecated aliases and doc-only anchors are noise.
        if name.startswith("_") or ".._" in name:
            continue
        yield record | {"role": role, "name": name}


def collect() -> list[dict]:
    inventories = load_inventories()
    if not inventories:
        raise SystemExit(
            "No cached inventories. Run: uv run scripts/fetch_docs.py",
        )
    records = list(interesting(dated_symbols(inventories, SPINE)))
    records += list(interesting(dated_symbols(inventories, LEGACY)))
    records.sort(key=lambda record: (version_key(record["added"]), record["name"]))
    for record in records:
        record["url"] = DOCS_URL.format(
            version=record["present_in"], uri=record["uri"].replace("$", record["name"])
        )
    return records


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="only symbols added in this release")
    parser.add_argument("--grep", help="only symbols whose name contains this")
    parser.add_argument("--role", help="only this role, e.g. py:function")
    parser.add_argument("--json", help="write every matching record to this file")
    args = parser.parse_args()

    records = collect()
    if args.version:
        records = [r for r in records if r["added"] == args.version]
    if args.grep:
        records = [r for r in records if args.grep.lower() in r["name"].lower()]
    if args.role:
        records = [r for r in records if r["role"] == args.role]

    if args.json:
        with open(args.json, "w", encoding="utf-8") as file:
            json.dump(records, file, indent=2)
        print(f"{len(records)} records written to {args.json}")
        return 0

    if args.version or args.grep or args.role:
        for record in records:
            print(f"{record['added']:>5}  {record['role']:<14} {record['name']}")
        print(f"\n{len(records)} symbols", file=sys.stderr)
        return 0

    counts: dict[str, int] = {}
    for record in records:
        counts[record["added"]] = counts.get(record["added"], 0) + 1
    for version in sorted(counts, key=version_key):
        print(f"{version:>5}  {counts[version]:>5} symbols")
    print(f"{'total':>5}  {len(records):>5} symbols")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
