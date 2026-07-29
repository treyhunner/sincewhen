#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Turn a list of symbol names into dataset entries, with evidence.

This is the safe way to add stdlib features. Nobody types a version
number: the version comes out of the cached documentation, and a symbol
the sources cannot date, or date consistently, is reported instead of
guessed at.

    uv run scripts/propose.py math.lcm math.isqrt itertools.accumulate

Names that already appear in the dataset are skipped, so a list can be
re-run as it grows. Group related names by passing them joined with a
plus sign, which produces a single entry matching all of them:

    uv run scripts/propose.py math.comb+math.perm

The output is TOML to paste into `features.toml` after editing the name
and category to taste. Read it before pasting: this script picks a
plausible display name, but naming is editorial.
"""

import argparse
import sys
import tomllib

from dating import date_symbol
from sources import ROOT

DATASET = ROOT / "src" / "sincewhen" / "features.toml"

# The inventory records what kind of thing each symbol is, which maps
# onto the dataset's categories closely enough to be a starting point.
CATEGORY_BY_ROLE = {
    "py:module": "module",
    "py:function": "function",
    "py:class": "class",
    "py:exception": "exception",
    "py:data": "constant",
    "py:method": "function",
    "py:attribute": "constant",
    "py:decorator": "function",
}


def existing() -> set[str]:
    entries = tomllib.loads(DATASET.read_text(encoding="utf-8"))["features"]
    names = set()
    for entry in entries:
        for field in ("modules", "attributes", "builtins", "nodes"):
            names.update(entry.get(field, ()))
    return names


def slug(name: str) -> str:
    return name.replace(".", "-").replace("_", "-").lower()


def matcher_for(name: str, roles: set[str]) -> str:
    if "py:module" in roles:
        return "modules"
    if "." in name:
        return "attributes"
    return "builtins"


def display(name: str, roles: set[str], matcher: str) -> str:
    if matcher == "modules":
        return f"{name} module"
    if "py:function" in roles or "py:method" in roles:
        return f"{name}()"
    return name


def propose(group: list[str]) -> tuple[str | None, str]:
    """A TOML entry for one group of names, or a reason there is none."""
    verdicts = [date_symbol(name) for name in group]

    for name, verdict in zip(group, verdicts, strict=True):
        if verdict.status == "conflict":
            return None, (
                f"{name}: inventory says {verdict.inventory}, "
                f"docs say {verdict.annotation}"
            )
        if verdict.added is None:
            return None, f"{name}: no cached source dates it"

    versions = {verdict.added for verdict in verdicts}
    if len(versions) > 1:
        found = ", ".join(f"{v.name}={v.added}" for v in verdicts)
        return None, f"group spans several releases: {found}"

    lead = verdicts[0]
    roles = set().union(*(verdict.roles for verdict in verdicts))
    matcher = matcher_for(group[0], roles)
    category = (
        "module"
        if matcher == "modules"
        else CATEGORY_BY_ROLE.get(sorted(roles)[0] if roles else "", "function")
    )

    targets = ", ".join(f'"{name}"' for name in group)
    lines = [
        "[[features]]",
        f'id = "{slug(group[0])}"',
        f'name = "{display(group[0], roles, matcher)}"',
        f'added = "{lead.added}"',
        f'category = "{category}"',
        *(["or_earlier = true"] if lead.or_earlier else []),
        f"{matcher} = [{targets}]",
        "",
        "[features.evidence]",
    ]
    for key, value in lead.evidence(CHECKED).items():
        if value is None:
            continue
        lines.append('{} = "{}"'.format(key, str(value).replace('"', '\\"')))
    return "\n".join(lines), ""


CHECKED = "2026-07-28"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="+", help="symbols, or a+b to group them")
    parser.add_argument(
        "--all", action="store_true", help="include names already in the dataset"
    )
    args = parser.parse_args()

    known = set() if args.all else existing()
    skipped = []
    for spec in args.names:
        group = spec.split("+")
        if any(name in known for name in group):
            skipped.append(spec)
            continue
        entry, reason = propose(group)
        if entry is None:
            print(f"# SKIPPED {spec}: {reason}", file=sys.stderr)
            continue
        print(entry)
        print()

    if skipped:
        print(f"# already in the dataset: {' '.join(skipped)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
