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
import re
import sys
import tomllib

from dating import date_symbol, is_type_member
from sources import ROOT

DATASET = ROOT / "src" / "sincewhen" / "features.toml"

# A matcher that settles the category on its own. Everything the
# `methods` matcher holds is a method or attribute of a builtin type,
# whatever role the inventory gives it, and a `py:attribute` there is
# still part of the type's interface rather than a constant.
CATEGORY_BY_MATCHER = {"modules": "module", "methods": "method"}

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
        for field in ("modules", "attributes", "builtins", "methods", "nodes"):
            names.update(entry.get(field, ()))
    return names


def slug(name: str) -> str:
    """An id for a symbol: kebab-case, and no run of dashes.

    A dunder would otherwise come out as `object---set-name--`, since
    every underscore becomes a dash of its own.
    """
    kebab = name.replace(".", "-").replace("_", "-").lower()
    return re.sub(r"-+", "-", kebab).strip("-")


def matcher_for(name: str, roles: set[str]) -> str:
    if "py:module" in roles:
        return "modules"
    if is_type_member(name):
        return "methods"
    if "." in name:
        return "attributes"
    return "builtins"


def display(name: str, roles: set[str], matcher: str) -> str:
    if matcher == "modules":
        return f"{name} module"
    if matcher == "methods" or "py:function" in roles or "py:method" in roles:
        return f"{name}()"
    return name


def display_group(group: list[str], roles: set[str], matcher: str) -> str:
    """A name for a whole group, which is three shapes in practice.

    One method on several types reads better with the method in front,
    since that is the thing that arrived: "hex() on bytes, bytearray and
    memoryview". Two of anything else is a conjunction. Naming is
    editorial, so this only has to be a good enough draft to leave alone
    most of the time.
    """
    if len(group) == 1:
        return display(group[0], roles, matcher)
    members = {name.rpartition(".")[2] for name in group}
    if matcher == "methods" and len(members) == 1:
        types = [name.partition(".")[0] for name in group]
        if len(types) > 2:
            listed = f"{', '.join(types[:-1])} and {types[-1]}"
            return f"{members.pop()}() on {listed}"
    drawn = [display(name, roles, matcher) for name in group]
    return " and ".join(drawn) if len(drawn) == 2 else ", ".join(drawn)


def one_method_several_types(group: list[str]) -> bool:
    """Whether a group is one method spelled for several builtin types.

    `str.removeprefix`, `bytes.removeprefix` and `bytearray.removeprefix`
    are one addition, and `stdtypes` documents them that way: the
    signatures are stacked and the marker under them belongs to all of
    them. So a marker on any one of them dates the group, and the
    siblings the docs leave undated are not a gap in the evidence.

    This is the only shape where an undated name is allowed into a group,
    because it is the only one where the docs say the names go together.
    """
    return (
        len(group) > 1
        and all(is_type_member(name) for name in group)
        and (len({name.rpartition(".")[2] for name in group}) == 1)
    )


def propose(group: list[str]) -> tuple[str | None, str]:
    """A TOML entry for one group of names, or a reason there is none."""
    verdicts = [date_symbol(name) for name in group]
    siblings = one_method_several_types(group)

    for name, verdict in zip(group, verdicts, strict=True):
        if verdict.status == "conflict":
            return None, (
                f"{name}: inventory says {verdict.inventory}, "
                f"docs say {verdict.annotation}"
            )
        if verdict.status == "source-contradicts-archive":
            return None, (
                f"{name}: the {verdict.source_absent_in} source does not bind it, "
                f"and the {verdict.archive} docs already list it"
            )
        if verdict.added is None and not siblings:
            return None, f"{name}: no cached source dates it"

    dated = [verdict for verdict in verdicts if verdict.added is not None]
    if not dated:
        return None, f"no cached source dates {', '.join(group)}"

    versions = {verdict.added for verdict in dated}
    if len(versions) > 1:
        found = ", ".join(f"{v.name}={v.added}" for v in dated)
        return None, f"group spans several releases: {found}"

    lead = dated[0]
    roles = set().union(*(verdict.roles for verdict in verdicts))
    matcher = matcher_for(group[0], roles)
    category = CATEGORY_BY_MATCHER.get(matcher) or CATEGORY_BY_ROLE.get(
        sorted(roles)[0] if roles else "", "function"
    )

    targets = ", ".join(f'"{name}"' for name in group)
    lines = [
        "[[features]]",
        f'id = "{slug(group[0])}"',
        f'name = "{display_group(group, roles, matcher)}"',
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


CHECKED = "2026-07-29"


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
