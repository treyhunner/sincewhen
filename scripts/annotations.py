#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Date documented objects by grepping the docs' own version markers.

The plain-text doc build states its history inline:

    math.gcd(*integers)

       Return the greatest common divisor ...

       Added in version 3.5.

This is the second of the two methods in PLAN.md, and it covers what the
inventory diff cannot: anything that predates the 2.6 inventories, and
anything that shipped before the docs were built with Sphinx at all.
Where the two methods disagree, that is a curation question, not a
tie to break automatically, so `--compare` prints the disagreements
rather than resolving them.

Usage:

    uv run scripts/annotations.py --grep gcd
    uv run scripts/annotations.py --version 2.3
    uv run scripts/annotations.py --json out.json
    uv run scripts/annotations.py --compare      # against inventory.py
"""

import argparse
import json
import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

from sources import text_files, text_root

# Which cached text build to trust for a given era. The 3.x docs dropped
# the Python 2 markers, and the 2.7 docs obviously stop at 2.7. Named
# here rather than by each caller, because `dated_releases` and
# `dating.py` have to read the builds in the same order to agree.
ANNOTATION_BUILDS = ("2.7", "3.14")

# The wording changed over the years: older docs say "New in version",
# newer ones say "Added in version". Both mean the same thing.
#
# The micro is captured separately and kept separately. The dataset
# works at feature-release granularity, so `added` stays "3.5" for a
# marker that says 3.5.2, but the difference is the only thing that can
# explain a built interpreter disagreeing with the docs: this corpus
# builds each release's `.0`, and `typing.Type` really is not in 3.5.0.
ANNOTATION = re.compile(
    r"^(?P<indent>\s*)(New|Added) in version (?P<version>\d+\.\d+)(?P<micro>\.\d+)?"
)

# A signature line: a dotted name, optionally followed by a call
# signature. The leading words are the ones the text build puts in front
# of a signature: `class datetime.date(...)`, `exception OSError`,
# `classmethod date.fromisoformat(...)`, `static bytes.maketrans(...)`,
# `abstractmethod`.
#
# They are not decoration. A line whose prefix is not listed here does
# not match at all, so the marker under it attaches to whatever signature
# came before instead: leaving out `classmethod` dated `datetime.date`
# itself to 3.7, and leaving out `static` gave `bytearray.join` the 3.1
# marker belonging to `bytes.maketrans`.
SIGNATURE = re.compile(
    r"^(?P<indent>\s*)(?:(?:class|exception|classmethod|abstractmethod|static)\s+)?"
    r"(?P<name>[A-Za-z_][\w.]*)\s*(\(|$|:)"
)

# The C API dates its own additions too, but nothing there is reachable
# from Python source, so it is noise for this project.
SKIP_DIRS = ("c-api", "distutils", "install", "whatsnew", "faq", "howto")

# A module page opens with a numbered heading naming the module:
#
#     9.7. "itertools" — Functions creating iterators ...
#
# A marker sitting under that heading, before any signature, dates the
# module itself. That is the only way modules get dated by this method,
# since a module has no signature line of its own.
MODULE_HEADING = re.compile(r'^(\d+\.)*\d*\.?\s*"(?P<name>[\w.]+)"\s*[—-]')

# A name quoted inside a marker's prose, as the text build renders it:
# `"sha3_256()"`, `"math.gcd()"`, `"ZoneInfo"`.
MENTION = re.compile(r'"(?P<name>[A-Za-z_][\w.]*)(?:\(\))?"')

# A bare word that no English sentence would contain: it carries an
# underscore or an inner capital. The text build only quotes what the
# source marked up as literal, and `Added in version 3.7:
# __breakpointhook__` marks up nothing, so a grouped marker naming its
# subject in prose is invisible to `MENTION` alone. Restricted this way
# because the alternative matches every word in the sentence, and a
# group with a member called `packed` or `version` would then answer to
# its own description.
UNPROSE = re.compile(r"\b(?=\w*[_A-Z])[A-Za-z_]\w*\b")


def is_name(candidate: str) -> bool:
    """Reject prose that happens to look like a signature.

    A wrapped sentence ending in a word plus a full stop matches the
    signature pattern, but `"conversions.".split(".")` has an empty
    trailing part, which no real dotted name does.
    """
    return all(part.isidentifier() for part in candidate.split("."))


def annotations_in(path: Path, module_root: Path) -> Iterator[dict]:
    """Every version marker in one file, tied to the name above it."""
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    relative = str(path.relative_to(module_root))
    recent: list[tuple[int, list[str]]] = []
    module = None
    # Whether the line just read was a signature. A directive's own
    # continuation signatures are the line immediately after it, so a
    # blank ends the run: see `_owners`.
    after_signature = False

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            after_signature = False
            continue

        if module is None and not recent:
            heading = MODULE_HEADING.match(line)
            if heading is not None:
                module = heading["name"]

        marker = ANNOTATION.match(line)
        if marker is not None:
            after_signature = False
            depth = len(marker["indent"])
            record = {
                "added": marker["version"],
                "release": marker["version"] + (marker["micro"] or ""),
                "file": relative,
                "line": number,
                "quote": " ".join(_paragraph(lines, number - 1)),
            }
            owners = _owners(recent, depth)
            if not owners and depth == 0 and not recent:
                owners = [module] if module is not None else []
            usable = [name for name in owners if is_name(name)]
            named = _singled_out(record["quote"], usable)
            for name in named:
                yield record | {"name": name}
                # Method pages write their signatures unqualified, as
                # `Path.walk(...)` on a page whose module is `pathlib`.
                # The inventory spells the same method `pathlib.Path.walk`,
                # so both spellings are recorded.
                if module is not None and not name.startswith(f"{module}."):
                    yield record | {"name": f"{module}.{name}"}
            if not usable and module is not None:
                # A marker with no owner of its own often names what it
                # dates, in prose: `Added in version 3.6: SHA3 (Keccak)
                # and SHAKE constructors "sha3_224()", ... were added.`
                #
                # Gated on there being no owner at all rather than on
                # nothing being yielded, because a grouped marker that
                # `_singled_out` decides is about none of the group has
                # an owner and is simply not about it.
                for mentioned in _mentioned(record["quote"], module):
                    yield record | {"name": mentioned, "grouped": True}
            continue

        signature = SIGNATURE.match(line)
        if signature is None:
            after_signature = False
            continue
        depth = len(signature["indent"])
        if after_signature and recent and recent[-1][0] == depth:
            recent[-1][1].append(signature["name"])
        else:
            recent = [item for item in recent if item[0] < depth]
            recent.append((depth, [signature["name"]]))
        after_signature = True


def _paragraph(lines: list[str], start: int) -> Iterator[str]:
    """The marker line and its wrapped continuation."""
    for line in lines[start:]:
        if not line.strip():
            return
        yield line.strip()


def _singled_out(quote: str, names: list[str]) -> list[str]:
    """Which of a group's names a marker is actually about.

    A marker under a group dates the whole group unless it says
    otherwise, and a colon is how it says otherwise. `typing.Never` and
    `typing.NoReturn` share one directive and carry a marker each:

        Added in version 3.6.2: Added "NoReturn".

        Added in version 3.11: Added "Never".

    Without this, `typing.Never` inherits `NoReturn`'s 3.6.2 and the
    index loses the name entirely, the interpreters having proved it is
    not in 3.6.

    So a grouped marker that qualifies itself has to name a member, and
    dates nothing in the group if it does not. `assertRegex` and
    `assertNotRegex` are why the second half is not "fall back to the
    group": they share a description carrying

        Added in version 3.1: Added under the name "assertRegexpMatches".

    which is a true statement about a third spelling and no statement at
    all about either of these, both of which are 3.2. Reading it as
    being about the group dated both to 3.1.

    A name is looked for quoted and bare, because the text build only
    quotes what the source marked up as literal: `sys.__excepthook__`
    and its three siblings share a description and two markers, spelled
    `Added in version 3.7: __breakpointhook__` with no quotes at all.
    A bare word is taken only where it could not be prose, meaning it
    carries an underscore or an inner capital, since a group whose
    members are spelled like ordinary English words would otherwise
    match the sentence around them.

    Only for a group. A marker under a lone signature dates that
    signature whatever its prose mentions, which is the reading every
    existing entry rests on, and a name quoted from somewhere else is
    prose rather than a correction: `_mentioned` reads those, and only
    where a marker has no signature above it at all.
    """
    if len(names) < 2:
        return names
    _, colon, text = quote.partition(":")
    if not colon:
        return names
    spoken = {match["name"] for match in MENTION.finditer(text)}
    spoken |= set(UNPROSE.findall(text))
    return [name for name in names if name.rpartition(".")[2] in spoken]


def _mentioned(quote: str, module: str) -> Iterator[str]:
    """Dotted names a grouped marker quotes, qualified by their module.

    Only the part after the colon counts, so that a marker's own prose
    ("Added in version 3.6: ...") is what gets read rather than whatever
    sentence happens to precede it.
    """
    _, colon, text = quote.partition(":")
    if not colon:
        return
    for match in MENTION.finditer(text):
        name = match["name"]
        yield name if name.startswith(f"{module}.") else f"{module}.{name}"


def _owners(recent: list[tuple[int, list[str]]], depth: int) -> list[str]:
    """Every enclosing signature a marker at `depth` belongs to.

    Usually one. It is a list because a directive may carry several
    signatures and one description, and the marker under it dates all
    of them. `os.spawnl` and seven siblings sit under one "New in
    version 1.6"; `operator.iadd` and `operator.__iadd__` under one
    2.5; `stat.FILE_ATTRIBUTE_*` is eighteen names under one 3.5.
    Keeping only the last one seen read all of those as bounds.

    What counts as one directive is the run of signature lines with no
    blank between them, and that is exactly the distinction, not an
    approximation of it. reST writes a directive's extra signatures as
    continuation lines:

        .. data:: FILE_ATTRIBUTE_ARCHIVE
                  FILE_ATTRIBUTE_COMPRESSED

    and the text build renders those with no blank line between. Two
    adjacent directives, each with its own `..`, get a blank line
    between them and are two things.

    The distinction has to be believed even where it reads oddly,
    because CPython writes both shapes and means different things by
    them. `unittest`'s assertion pairs are two `.. method::` directives
    with the description under the second, and plainly mean both:
    "Test that the Unicode or byte string *s* starts (or does not
    start) with a *prefix*." `ipaddress.IPv6Address` is seven
    `.. attribute::` directives, six of them empty, and the marker
    under the seventh belongs to `is_global` alone. Nothing in either
    the source or the build separates those two cases, so the marker
    stays with the directive that carries it, and the four assertions
    that lose it are dated by the inventory instead, with a note.

    Only the innermost group expands. Each enclosing level contributes
    its last name, as it always did, since a group of *classes* sharing
    one description is not a thing the docs do.

    The name is qualified by whatever encloses it, so a marker under
    `class pathlib.Path` on a `read_text()` signature reads as
    `pathlib.Path.read_text` rather than a bare `read_text` that matches
    nothing.
    """
    enclosing = [names for indent, names in recent if indent < depth]
    if not enclosing:
        return []
    outer = [names[-1] for names in enclosing[:-1]]
    return [_qualify(name, outer) for name in enclosing[-1]]


def _qualify(name: str, outer: list[str]) -> str:
    for enclosing in reversed(outer):
        if name.startswith(f"{enclosing}."):
            break
        name = f"{enclosing}.{name}"
    return name


def collect(version: str = "3.14") -> list[dict]:
    root = text_root(version)
    if not root.exists():
        raise SystemExit("No cached text docs. Run: uv run scripts/fetch_docs.py")
    records = [
        record
        for path in text_files(version)
        if path.relative_to(root).parts[0] not in SKIP_DIRS
        for record in annotations_in(path, root)
    ]
    records.sort(key=lambda record: (_key(record["added"]), record["name"]))
    return records


def _key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


@cache
def dated_releases() -> dict[str, str]:
    """The full release each name's oldest marker names, micro included.

    Separate from the feature release the dataset records, and the only
    thing that can tell a built interpreter's absence from a mistake.
    The corpus builds each release's `.0`, so a marker that says 3.5.2 is
    a marker the 3.5 interpreter is expected to disagree with, and one
    that says 3.5 is not.

    Read in the same build order as `dating.py`'s own index, so that a
    name dated in both builds keeps its Python 2 marker in both places.
    """
    index: dict[str, str] = {}
    for build in ANNOTATION_BUILDS:
        for record in collect(build):
            existing = index.get(record["name"])
            if existing is None or _release_key(record["release"]) < _release_key(
                existing
            ):
                index[record["name"]] = record["release"]
    return index


def _release_key(release: str) -> tuple[int, ...]:
    """Sort key for a release that may or may not name a micro."""
    return tuple(int(part) for part in release.split("."))


def compare(records: list[dict]) -> list[dict]:
    """Names the two methods date differently.

    Only names dated by both are compared, since each method covers
    ground the other cannot.
    """
    import inventory

    by_name = {}
    for record in inventory.collect():
        by_name.setdefault(record["name"], record["added"])

    disagreements = []
    seen = set()
    for record in records:
        name = record["name"]
        if name in seen or name not in by_name:
            continue
        seen.add(name)
        if by_name[name] != record["added"]:
            disagreements.append(
                {
                    "name": name,
                    "inventory": by_name[name],
                    "annotation": record["added"],
                    "quote": record["quote"],
                    "file": record["file"],
                }
            )
    return disagreements


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--docs", default="3.14", help="which cached text build to read"
    )
    parser.add_argument("--version", help="only markers naming this release")
    parser.add_argument("--grep", help="only names containing this")
    parser.add_argument("--json", help="write matching records to this file")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="report where this method and the inventory diff disagree",
    )
    args = parser.parse_args()

    records = collect(args.docs)

    if args.compare:
        disagreements = compare(records)
        for item in disagreements:
            print(
                f"{item['name']:<45} inventory={item['inventory']:<5} "
                f"annotation={item['annotation']:<5} {item['file']}"
            )
        print(f"\n{len(disagreements)} disagreements")
        return 0

    if args.version:
        records = [r for r in records if r["added"] == args.version]
    if args.grep:
        records = [r for r in records if args.grep.lower() in r["name"].lower()]

    if args.json:
        Path(args.json).write_text(json.dumps(records, indent=2), encoding="utf-8")
        print(f"{len(records)} records written to {args.json}")
        return 0

    for record in records:
        print(f"{record['added']:>5}  {record['name']:<45} {record['file']}")
    print(f"\n{len(records)} markers")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
