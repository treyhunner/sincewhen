#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Date builtins and modules from the source, before the docs existed.

The archives bottom out at 1.2 for builtins, because that is the oldest
HTML build carrying a built-in functions page. Everything already on
that page can only be bounded, so with the docs as the only witness
`map` reports as "1.2 or earlier". The source releases reach further
back: 0.9.1 is the first public Python, from 1991, and its
`bltinmodule.c` carries the same method table every later release does.

Modules work the same way and gain more, because the module *index*
dates documentation rather than shipping. `bisect` ships in the 1.0
tarball, is first indexed in the 1.5 docs, and is claimed by the 2.7
docs to be 2.1. The tarball settles it.

This inverts the rule the rest of the pipeline runs on. Everywhere else
presence is strong and absence is weak, because a release's docs can
omit something it shipped. Here the table *is* the list the interpreter
registers its builtins from rather than a description of one, so a name
missing from it is a name that release did not have. That is what
settles `map`: absent from 0.9.1, present in 1.0.1, so `map` is 1.0, and
the doc archives were only ever reporting how far back they went.

0.9.1 is still the floor of everything. A builtin already in it, like
`max`, cannot be dated, only bounded, and reports as "0.9 or earlier".
That is the true floor of the surviving record rather than an artifact
of which doc builds happened to be kept.

The trap is the one the HTML side has too. `{"name", ...}` is ordinary C
that appears in every method table in the tree, so matching it loosely
would collect the members of whatever module sits next to it. Anchor on
the `builtin_methods[]` table and read only its body.

Usage:

    uv run scripts/source.py                 # every builtin, dated
    uv run scripts/source.py --modules       # every module, dated
    uv run scripts/source.py --version 1.0   # what 1.0 added
    uv run scripts/source.py --grep map
"""

import argparse
import re
from functools import cache
from pathlib import Path

from sources import SOURCE_BUILDS, html_root

# The source releases, oldest first. These are the only three that
# predate the HTML doc builds, which is exactly the era this covers.
SOURCE_ORDER = tuple(SOURCE_BUILDS)

# The builtins table, which every release from 0.9.1 on declares under
# the same name and closes with a `};` in the first column. Reading only
# what is between the two is what keeps the neighbouring method tables
# out of the result.
BUILTIN_TABLE = re.compile(
    r"builtin_methods\s*\[\s*\]\s*=\s*\{(?P<body>.*?)^\};",
    re.DOTALL | re.MULTILINE,
)

# One row of it: `{"abs", builtin_abs},`, with whitespace that is spaces
# in 0.9.1 and tabs from 1.0 on. The sentinel row is `{NULL, NULL}`,
# which has no quotes and so never matches.
TABLE_ENTRY = re.compile(r'^\s*\{\s*"(?P<name>[A-Za-z_]\w*)"', re.MULTILINE)

BUILTIN_SOURCE = "bltinmodule.c"

# Where a release keeps its Python modules. 0.9.1 lowercases it and
# every release since capitalises it.
LIBRARY_DIRS = ("Lib", "lib")

# Directories that ship alongside the library without being part of it.
# A demo or a test is not a module anyone can import by that name.
NOT_LIBRARY = frozenset({"demo", "test", "tests", "dos", "mac", "extensions"})


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def builtin_source(version: str) -> Path | None:
    """Where one release keeps `bltinmodule.c`.

    0.9.1 puts every C file in a flat `src/` and 1.0 onward split the
    tree into `Python/`, `Objects/` and `Modules/`, so this searches
    rather than assuming a layout.
    """
    root = html_root(version)
    if not root.exists():
        return None
    return next(root.rglob(BUILTIN_SOURCE), None)


@cache
def builtins_in(version: str) -> frozenset[str]:
    """Every builtin one release's interpreter registers."""
    path = builtin_source(version)
    if path is None:
        return frozenset()
    table = BUILTIN_TABLE.search(path.read_text(errors="ignore"))
    if table is None:
        return frozenset()
    return frozenset(match["name"] for match in TABLE_ENTRY.finditer(table["body"]))


@cache
def module_files(version: str) -> dict[str, str]:
    """The Python modules one release ships, and the file for each.

    Only the `.py` files in the library directory, and deliberately not
    the C extensions. A file in `Lib/` is importable in every build of
    that release, so presence and absence both mean something, which is
    the same exhaustive-list argument the builtins table gets.

    A C extension is not like that. `Modules/Setup` decides which ones
    get compiled, and plenty of standard modules ship commented out:
    `curses`, `syslog` and `termios` are all in the 1.1 tarball and none
    of them is in its default build. Reading the tarball alone credits a
    release with modules it could not import, and filtering on `Setup`
    overcorrects, because `select` is documented in 1.0 and commented
    out there too. Which build you had decided the answer, so the
    tarball cannot settle it and the archives keep those modules.
    """
    root = html_root(version)
    if not root.exists():
        return {}

    def cite(path: Path) -> str:
        # One level below the cache directory is the tarball's own top
        # directory, which is not worth repeating in every citation.
        return str(path.relative_to(root)).split("/", 1)[-1]

    found: dict[str, str] = {}
    for name in LIBRARY_DIRS:
        for directory in root.rglob(name):
            if any(part.lower() in NOT_LIBRARY for part in directory.parts):
                continue
            for path in directory.glob("*.py"):
                found.setdefault(path.stem, cite(path))
    return found


def modules_in(version: str) -> frozenset[str]:
    return frozenset(module_files(version))


def _diff(
    readable: list[str], present: dict[str, frozenset[str]]
) -> dict[str, dict[str, str]]:
    """Chain a per-release name list into dates and floors.

    Whatever is in the oldest readable release can only be bounded;
    anything appearing later is dated by the release that lacks it.
    """
    baseline, *rest = readable
    seen = set(present[baseline])
    dated: dict[str, dict[str, str]] = {
        name: {"floor": baseline} for name in sorted(seen)
    }

    previous = baseline
    for version in rest:
        for name in sorted(present[version] - seen):
            dated[name] = {
                "added": version,
                "absent_in": previous,
                "present_in": version,
            }
        seen |= present[version]
        previous = version
    return dated


@cache
def dated_modules() -> dict[str, dict[str, str]]:
    """First source release each module ships in.

    Same record shape as `modindex.dated_modules`, and a stronger
    verdict for the era it covers: that one dates documentation and
    this dates the tarball.
    """
    present = {version: modules_in(version) for version in SOURCE_ORDER}
    readable = [version for version in SOURCE_ORDER if present[version]]
    return _diff(readable, present) if readable else {}


@cache
def dated_builtins() -> dict[str, dict[str, str]]:
    """First source release each builtin appears in.

    The record shape matches `modindex.dated_builtins` so that either
    can answer the same question: an `added` with the release that lacks
    it for anything the diff catches, and a `floor` for anything already
    in the oldest release there is.

    A release whose source is not cached is skipped rather than read as
    empty, so a missing tarball never looks like a mass removal.
    """
    present = {version: builtins_in(version) for version in SOURCE_ORDER}
    readable = [version for version in SOURCE_ORDER if present[version]]
    return _diff(readable, present) if readable else {}


@cache
def source_file(version: str, module: str | None = None) -> str | None:
    """The path to cite for a release, relative to its unpacked root.

    The evidence is only checkable if it says where to look, and the
    answer differs by era and by module: `src/bltinmodule.c` in 0.9.1,
    `Python/bltinmodule.c` from 1.0 on, `Lib/bisect.py` for a Python
    module and `Modules/mathmodule.c` for a C one.
    """
    if module is not None:
        return module_files(version).get(module)
    path = builtin_source(version)
    if path is None:
        return None
    return str(path.relative_to(html_root(version))).split("/", 1)[-1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="only names added in this release")
    parser.add_argument("--grep", help="only names containing this")
    parser.add_argument(
        "--modules", action="store_true", help="report modules instead of builtins"
    )
    args = parser.parse_args()

    dated = dated_modules() if args.modules else dated_builtins()
    if not dated:
        raise SystemExit("No cached source releases. Run: just fetch-docs")

    if args.version:
        names = sorted(n for n, r in dated.items() if r.get("added") == args.version)
        for name in names:
            print(name)
        print(f"\n{len(names)} builtins added in {args.version}")
        return 0

    for name, record in sorted(dated.items()):
        if args.grep and args.grep not in name:
            continue
        where = record.get("added") or f"{record['floor']} or earlier"
        print(f"{name:<20} {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
