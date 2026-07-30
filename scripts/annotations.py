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
from pathlib import Path

from sources import text_files, text_root

# The wording changed over the years: older docs say "New in version",
# newer ones say "Added in version". Both mean the same thing.
ANNOTATION = re.compile(r"^(?P<indent>\s*)(New|Added) in version (?P<version>\d+\.\d+)")

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
    recent: list[tuple[int, str]] = []
    module = None

    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue

        if module is None and not recent:
            heading = MODULE_HEADING.match(line)
            if heading is not None:
                module = heading["name"]

        marker = ANNOTATION.match(line)
        if marker is not None:
            depth = len(marker["indent"])
            record = {
                "added": marker["version"],
                "file": relative,
                "line": number,
                "quote": " ".join(_paragraph(lines, number - 1)),
            }
            name = _owner(recent, depth)
            if name is None and depth == 0 and not recent:
                name = module
            if name is not None and is_name(name):
                yield record | {"name": name}
                # Method pages write their signatures unqualified, as
                # `Path.walk(...)` on a page whose module is `pathlib`.
                # The inventory spells the same method `pathlib.Path.walk`,
                # so both spellings are recorded.
                if module is not None and not name.startswith(f"{module}."):
                    yield record | {"name": f"{module}.{name}"}
            elif module is not None:
                # A marker with no owner of its own often names what it
                # dates, in prose: `Added in version 3.6: SHA3 (Keccak)
                # and SHAKE constructors "sha3_224()", ... were added.`
                for mentioned in _mentioned(record["quote"], module):
                    yield record | {"name": mentioned, "grouped": True}
            continue

        signature = SIGNATURE.match(line)
        if signature is not None:
            depth = len(signature["indent"])
            recent = [item for item in recent if item[0] < depth]
            recent.append((depth, signature["name"]))


def _paragraph(lines: list[str], start: int) -> Iterator[str]:
    """The marker line and its wrapped continuation."""
    for line in lines[start:]:
        if not line.strip():
            return
        yield line.strip()


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


def _owner(recent: list[tuple[int, str]], depth: int) -> str | None:
    """The innermost enclosing signature for a marker at `depth`.

    Qualified by whatever encloses it, so a marker under `class
    pathlib.Path` on a `read_text()` signature reads as
    `pathlib.Path.read_text` rather than a bare `read_text` that
    matches nothing.
    """
    enclosing = [name for indent, name in recent if indent < depth]
    if not enclosing:
        return None
    qualified = enclosing[-1]
    for outer in reversed(enclosing[:-1]):
        if qualified.startswith(f"{outer}."):
            break
        qualified = f"{outer}.{qualified}"
    return qualified


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
