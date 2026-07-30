#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Date the methods of the builtin types from the source itself.

This is `source.py`'s argument one level down. A module's method table is
the list it registers its functions from rather than a description of
one, so a name missing from it is a name that release did not have. A
type's method table is the same kind of list, and the corpus carries
every release from 0.9.1 to 2.5.

That is the only thing that reaches these names. The docs index 397
members of the builtin types and date 58 of them, because a method that
predates the "New in version" convention never got a marker: nothing in
any doc build says when `dict.setdefault`, `str.split` or `list.append`
arrived. The tables do. `dict` had `keys` and `has_key` and nothing else
in 0.9.1; `items` and `values` arrived in 1.0, `clear`, `copy`, `get` and
`update` in 1.5, `setdefault` in 2.0 and `popitem` in 2.1.

Four things had to be decided before any of it can be believed, because
each one produces a wrong version number if it is guessed at.

**A type is a family, and 2.x `str` is not 3.x `str`.** `stringobject.c`
is the bytes-ish string and `unicodeobject.c` is what became `str`, and
their tables do not agree: `encode` is in the unicode table from 1.6 and
in the string table from 2.0. So a member counts as present for `str`
only where every type in the family binds it, and absent as soon as one
of them provably lacks it. That is what "how long has `x.upper()` worked
for a string" means, and it is what the dataset's pre-2.6 entries already
claim: `str.encode` is 2.0. A member one of the family never has at all,
like `isdecimal`, is reported rather than dated, since no single release
is the answer.

**The table dates availability on instances, not on the type.** `str` was
a builtin function and not a class until 2.2, so `"x".encode` is 2.0 and
`str.encode` as an unbound attribute is 2.2. The claim here is the
instance one, and that is why the head of the name is deliberately not
consulted: `dict` the builtin is 2.2 and the `dict` type is in 0.9.1, so
treating the head as a floor under `dict.keys` would date every ancient
method to 2.2.

**A special method is a slot, not a table row.** `__lt__` and
`__index__` are filled in by the type structure itself, so no table can
date them and they stay with the docs. Worse, a dunder can be both:
`list.__getitem__` has been a slot since 0.9.1 and gained a table row in
2.4 so that it could be pickled, so the row is the age of the row. Every
dunder is left out for that reason, which costs a handful of table-only
ones like `type.__subclasses__` and buys never dating a slot by its row.

**Only the method tables, never the getset or member tables.** Those
exist from 2.2, and before then an attribute was resolved by hand-written
comparisons inside `tp_getattr`: 1.5 answers `complex.real` with a
`strcmp` and no table at all. So absence from a member table in 2.1 is
not absence from the release, and reading those would date every
attribute to the release that unified the type system. `float.real` and
`int.numerator` are 2.6 and past this corpus anyway.

The spelling moves around underneath all of that, and none of it is load
bearing. `struct methodlist` becomes `PyMethodDef`, which does not matter
because the table is found by the identifier the type points at rather
than by its declared type. Resolution moves from a `tp_getattr` function
calling `findmethod()` to a `tp_methods` slot in 2.2, so both are read.
The Python-level name moves too, and is not the C identifier: `dict` is
`Mappingtype` spelled `"dictionary"` until 2.2, `str` is `Stringtype`
spelled `"string"` until 2.2, and `long` is `"long int"`. What ties a
table to a type is the `tp_name` string in the type structure, which is
the only place the Python-visible name is written down.

Presence is read strictly and absence generously, exactly as in
`source.py`. A row inside an `#if` proves nothing, and `str.zfill` is the
case that matters: the 1.6 table carries `{"zfill", ...}` inside an
`#if 0` and so does 2.2's, because the method really did arrive in
2.2.2. So it reports as "2.3 or earlier" rather than as 1.6, and the
docs' own marker outranks a floor.

Usage:

    uv run scripts/typemethods.py                  # every method, dated
    uv run scripts/typemethods.py --type dict
    uv run scripts/typemethods.py --grep split
    uv run scripts/typemethods.py --version 1.6
    uv run scripts/typemethods.py --tables         # each release's tables
    uv run scripts/typemethods.py --partial        # what the family disagrees on
    uv run scripts/typemethods.py --compare        # against every other method
"""

import argparse
import re
from dataclasses import dataclass
from functools import cache

from source import (
    C_STRING,
    SOURCE_ORDER,
    TABLE_ENTRY,
    c_files,
    cite,
    unconditional,
)

# A static type structure, whose fourth field is the `tp_name` the type
# answers to in Python. Every release from 0.9.1 on writes it the same
# way apart from the struct tag, which lost its `Py` prefix in 1.5.
TYPE_STRUCT = re.compile(
    r"(?:PyTypeObject|typeobject)\s+(?P<ident>\w+)\s*=\s*\{(?P<body>.*?)^\};",
    re.DOTALL | re.MULTILINE,
)

# The first string literal in that structure, which is `tp_name`. The
# fields above it are the object header and `ob_size`, and neither can
# contain a string.
TP_NAME = re.compile(r'"(?P<name>[^"\\\n]*)"')

# One slot, named by the comment beside it. CPython has commented these
# consistently since 0.9.1, and the comment is the only thing that says
# which slot a bare identifier fills without counting commas through
# macros and multi-line flag expressions.
SLOT = re.compile(r"(?P<value>[\w&()]+)\s*,\s*/\*+\s*(?P<slot>tp_\w+)\s*\*+/")

# `(getattrfunc)list_getattr`, whose cast is noise.
CAST = re.compile(r"^\(\w+\)")

# What a pre-2.2 `tp_getattr` does with the type's method table:
# `findmethod(list_methods, ...)` in 0.9.1 and `Py_FindMethod(...)`
# later. Anything the function does before that is attribute handling,
# which this method deliberately does not read.
FIND_METHOD = re.compile(r"\b(?:Py_)?[Ff]ind[Mm]ethod\s*\(\s*(?P<table>\w+)")

# A slot that resolves attributes generically, so it names no table.
GENERIC = frozenset({"0", "NULL", "PyObject_GenericGetAttr"})

# A dunder, which this method never dates. See the module docstring.
DUNDER = re.compile(r"^__\w+__$")

# Each builtin type the dataset can hold methods for, and every
# `tp_name` in its family, oldest spelling first.
#
# A family is required to agree, so what goes in one is a claim about
# which values a user would call by the modern name:
#
# - `str` is the 2.x string *and* unicode. A `"x"` literal is a string in
#   2.x and a `str` in 3.x, and the type 3.x calls `str` is unicode, so
#   both have to have a method before "strings have this method" is true.
# - `int` is the 2.x int *and* long, which 3.x unified. `5` is an int and
#   `5L` is a long, and neither carries a method the other lacks in this
#   corpus.
# - `dict`, `list` and the rest are themselves under an older `tp_name`.
#
# Four modern types are deliberately absent, because no release in this
# corpus has instances anyone would call by their name:
#
# - `bytes` and `bytearray` are 2.6. The 2.x string type became `bytes`
#   by being renamed, so mapping `bytes` onto it would date
#   `bytes.capitalize` to 1.6, five releases before anything could be
#   spelled `b"..."`.
# - `range` is 2.x `xrange`, and 2.x `range` is a builtin returning a
#   list, so `range(3).index` in this era is `list.index`.
# - `memoryview` is 2.7, and 2.x `buffer` is a different interface.
#
# Those four are what the docs' own markers and their types' dates have
# to answer for, and `type_is_covered` is what keeps the omission from
# being silent.
LINEAGE = {
    "bool": ("bool",),
    "complex": ("complex",),
    "dict": ("dictionary", "dict"),
    "float": ("float",),
    "frozenset": ("frozenset",),
    "int": ("int", "long int", "long"),
    "list": ("list",),
    "object": ("object",),
    "set": ("set",),
    "slice": ("slice",),
    "str": ("string", "str", "unicode"),
    "tuple": ("tuple",),
    "type": ("type",),
}

# Every `tp_name` any family claims, for a cheap membership test while
# scanning a whole release's C sources.
FAMILY_NAMES = frozenset(name for names in LINEAGE.values() for name in names)


@dataclass(frozen=True)
class TypeSource:
    """One type as one release implements it.

    `methods` is what the release provably binds and `literals` is what
    it so much as mentions, which is the asymmetry the whole method rests
    on: a name in the first is present, a name in neither is absent, and
    a name only in the second is a row this cannot read either way.
    """

    file: str
    methods: frozenset[str]
    literals: frozenset[str]


def _table_body(text: str, table: str) -> str | None:
    """The body of one named table, or `None` if it is not in this text.

    Looked up by the identifier the type points at, never matched
    loosely: `{"name", func}` is ordinary C that appears in every method
    table in the tree, so reading the wrong one collects a neighbouring
    type's methods.
    """
    found = re.search(
        rf"\b{re.escape(table)}\s*\[\s*\]\s*=\s*\{{(?P<body>.*?)^\}};",
        text,
        re.DOTALL | re.MULTILINE,
    )
    return None if found is None else found["body"]


def _function_body(text: str, name: str) -> str:
    """One C function, from its definition to the closing brace.

    Both eras put the name at the start of a line, since the return type
    goes on the line above it, and both close the body with a brace in
    the first column.
    """
    found = re.search(rf"^{re.escape(name)}\s*\(", text, re.MULTILINE)
    if found is None:
        return ""
    rest = text[found.end() :]
    end = re.search(r"^\}", rest, re.MULTILINE)
    return rest[: end.end()] if end is not None else rest


def _method_table(text: str, body: str) -> str | None:
    """The table a type structure gets its methods from.

    2.2 introduced `tp_methods` and everything before it resolved
    attributes through a `tp_getattr` function that ends in a call to
    `findmethod()`. Both are read, newest first, because 2.2 leaves the
    old slot filled in on a few types and the new one is the truth there.
    """
    slots = {match["slot"]: match["value"] for match in SLOT.finditer(body)}
    if slots.get("tp_methods", "0") not in GENERIC:
        return slots["tp_methods"]
    for slot in ("tp_getattro", "tp_getattr"):
        value = CAST.sub("", slots.get(slot, "0"))
        if value in GENERIC:
            continue
        found = FIND_METHOD.search(_function_body(text, value))
        if found is not None:
            return found["table"]
    return None


def types_in_text(raw: str, file: str) -> dict[str, TypeSource]:
    """Every builtin type one C file declares, by its `tp_name`.

    A type counts as existing where the raw text declares it and binds
    only what survives `unconditional`, which is the same split
    `source.py` reads a module member with. `complexobject.c` is why:
    the whole file sits inside `#ifndef WITHOUT_COMPLEX`, so `complex`
    exists in every release from 1.4 and binds nothing this can prove,
    and no `complex` method is dated from a build option.
    """
    strict = unconditional(raw)
    literals = frozenset(literal["name"] for literal in C_STRING.finditer(raw))
    found: dict[str, TypeSource] = {}
    for match in TYPE_STRUCT.finditer(raw):
        name = TP_NAME.search(match["body"])
        if name is None or name["name"] not in FAMILY_NAMES:
            continue
        methods: set[str] = set()
        table = _method_table(strict, match["body"])
        if table is not None:
            body = _table_body(strict, table)
            if body is not None:
                methods = {
                    row["name"]
                    for row in TABLE_ENTRY.finditer(body)
                    if not DUNDER.match(row["name"])
                }
        found[name["name"]] = TypeSource(
            file=file, methods=frozenset(methods), literals=literals
        )
    return found


@cache
def types_in(version: str) -> dict[str, TypeSource]:
    """Every builtin type one release implements, by its `tp_name`."""
    found: dict[str, TypeSource] = {}
    for path in c_files(version):
        found |= types_in_text(path.read_text(errors="ignore"), cite(version, path))
    return found


@cache
def readable() -> tuple[str, ...]:
    """The releases whose C sources are cached, oldest first."""
    return tuple(version for version in SOURCE_ORDER if c_files(version))


def _family(version: str, type_name: str) -> list[str]:
    """The types in one family that one release implements."""
    present = types_in(version)
    return [name for name in LINEAGE[type_name] if name in present]


def _binds(version: str, type_name: str, member: str) -> bool:
    """Whether every type in the family provably binds `member`.

    All of them, because the claim is that the method works on any value
    of the modern type. `encode` is in 1.6's unicode table and not in its
    string table, and `"x".encode()` is a 2.0 feature.
    """
    family = _family(version, type_name)
    present = types_in(version)
    return bool(family) and all(member in present[name].methods for name in family)


def _lacks(version: str, type_name: str, member: str) -> bool:
    """Whether one release can be shown not to offer `member`.

    Two ways. A release with no member of the family at all cannot offer
    any of their methods, which is what dates every `set` method to 2.4:
    `setobject.c` arrives there, and 2.3's `set` is `sets.Set` in the
    library under another name. Otherwise one member of the family that
    does not so much as mention the name is enough, since the claim being
    refuted is that every one of them has it.
    """
    family = _family(version, type_name)
    if not family:
        return True
    present = types_in(version)
    return any(member not in present[name].literals for name in family)


def _deciding_file(version: str, type_name: str, member: str, previous: str) -> str:
    """Which file to cite for a date the whole family agrees on.

    The one that settles it is the type that did not have the method in
    the release before, since that is the file a reviewer has to read to
    see the change. `str.encode` cites `stringobject.c`, which gained the
    row, and not `unicodeobject.c`, which had it all along.
    """
    present = types_in(version)
    family = _family(version, type_name)
    deciding = [
        name
        for name in family
        if name not in types_in(previous)
        or member not in types_in(previous)[name].methods
    ]
    return present[(deciding or family)[0]].file


def _note(version: str, type_name: str, member: str) -> str | None:
    """What to say when more than one type had to agree."""
    family = _family(version, type_name)
    if len(family) < 2:
        return None
    files = ", ".join(sorted(types_in(version)[name].file for name in family))
    return (
        f"{type_name} is {' and '.join(family)} in {version}, and both tables "
        f"carry it: {files}."
    )


@cache
def dated_type_methods() -> dict[str, dict[str, str]]:
    """First release each `type.method` can be shown in, by name.

    The record shape matches `source.dated_members`, so `dating.py` can
    treat this as the same method: an `added` with the release that
    demonstrably lacked it, or a `floor` for a name this can only bound.

    A floor happens two ways. The method is in the oldest release there
    is, like `list.append`, which nothing can date. Or the older release
    neither binds it nor rules it out, which is `str.zfill`: the row is
    there from 1.6 inside an `#if 0`.
    """
    dated: dict[str, dict[str, str]] = {}
    for type_name in LINEAGE:
        dated |= _date_one_type(type_name)
    return dated


def _date_one_type(type_name: str) -> dict[str, dict[str, str]]:
    """Every method of one type, dated or bounded."""
    versions = readable()
    candidates = {
        member
        for version in versions
        for name in _family(version, type_name)
        for member in types_in(version)[name].methods
    }

    dated: dict[str, dict[str, str]] = {}
    for member in sorted(candidates):
        bound = [version for version in versions if _binds(version, type_name, member)]
        if not bound:
            # The family never agrees, so no release is the answer. See
            # `partial()`, which reports these for a human.
            continue
        added = bound[0]
        if any(
            _lacks(version, type_name, member)
            for version in versions[versions.index(added) :]
        ):
            # Bound, then demonstrably gone, then bound again. `added`
            # means "available ever since" and no single release says
            # that, so this is reported rather than dated.
            continue

        name = f"{type_name}.{member}"
        record = {"file": types_in(added)[_family(added, type_name)[0]].file}
        note = _note(added, type_name, member)
        if added != versions[0] and _lacks(
            previous := versions[versions.index(added) - 1], type_name, member
        ):
            record |= {
                "file": _deciding_file(added, type_name, member, previous),
                "added": added,
                "absent_in": previous,
                "present_in": added,
            }
        else:
            record |= {"floor": added}
        if note is not None:
            record["note"] = note
        dated[name] = record
    return dated


@cache
def partial() -> dict[str, dict[str, str]]:
    """Methods one type in a family has and another never does.

    These are the disagreements, and they are findings rather than
    failures. `isdecimal` and `isnumeric` are unicode methods that the
    2.x string type never had, so "since when does a string have
    `isdecimal`" has no answer in this era at all: the answer is about
    3.0 renaming unicode to `str`, which this method cannot see. Left for
    the docs, and reported so that nobody has to notice the absence.
    """
    found: dict[str, dict[str, str]] = {}
    dated = dated_type_methods()
    for type_name, spellings in LINEAGE.items():
        if len(spellings) < 2:
            continue
        for version in readable():
            family = _family(version, type_name)
            if len(family) < 2:
                continue
            present = types_in(version)
            for name in family:
                for member in present[name].methods:
                    if f"{type_name}.{member}" in dated:
                        continue
                    holders = [
                        other for other in family if member in present[other].methods
                    ]
                    found.setdefault(
                        f"{type_name}.{member}",
                        {
                            "since": version,
                            "in": ", ".join(sorted(holders)),
                            "not_in": ", ".join(sorted(set(family) - set(holders))),
                        },
                    )
    return found


def type_is_covered(name: str) -> bool:
    """Whether this method speaks for the type a dotted name names.

    `bytes`, `bytearray`, `range` and `memoryview` have no ancestor in
    this corpus whose instances anyone would call by those names, so
    silence about them is deliberate rather than a gap in the extraction.
    """
    return name.partition(".")[0] in LINEAGE


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", help="only methods of this type")
    parser.add_argument("--grep", help="only names containing this")
    parser.add_argument("--version", help="only methods added in this release")
    parser.add_argument(
        "--tables", action="store_true", help="show each release's method tables"
    )
    parser.add_argument(
        "--partial", action="store_true", help="show what a family disagrees on"
    )
    parser.add_argument(
        "--compare", action="store_true", help="compare against the other methods"
    )
    args = parser.parse_args()

    if not readable():
        raise SystemExit("No cached source releases. Run: just fetch-docs")
    if args.tables:
        return report_tables()
    if args.partial:
        for name, record in sorted(partial().items()):
            print(
                f"{name:<28} in {record['in']} from {record['since']}, never {record['not_in']}"
            )
        print(f"\n{len(partial())} members the family disagrees about")
        return 0

    dated = dated_type_methods()
    if args.compare:
        return report_comparison(dated)

    shown = 0
    for name, record in sorted(dated.items()):
        if args.type and not name.startswith(f"{args.type}."):
            continue
        if args.grep and args.grep not in name:
            continue
        if args.version and record.get("added") != args.version:
            continue
        where = record.get("added") or f"{record['floor']} or earlier"
        print(f"{name:<28} {where:<18} {record['file']}")
        shown += 1
    print(f"\n{shown} methods")
    return 0


def report_tables() -> int:
    """What each release's tables hold, which is the raw evidence."""
    for version in readable():
        print(f"===== {version}")
        for type_name in LINEAGE:
            for name in _family(version, type_name):
                source = types_in(version)[name]
                methods = " ".join(sorted(source.methods)) or "-"
                print(f"  {type_name:<10} {name:<12} {source.file:<26} {methods}")
    return 0


def report_comparison(dated: dict[str, dict[str, str]]) -> int:
    """Every name this dates, against what the rest of the pipeline says.

    This is the check that earned its place. Comparing source dates
    against what the docs say for the same name is what caught every
    mistake the module-member extractor made, and it earns its keep here
    too: a disagreement with a version marker is a finding either way,
    and three of them are real.

    A floor is not compared, only reported. It claims less than a marker
    does, so a marker of the same release or older outranks it, which is
    what keeps `str.zfill` at the 2.2 its own docs give it rather than at
    the "2.3 or earlier" an `#if 0` leaves behind.
    """
    from dating import date_symbol  # noqa: PLC0415  (only the report needs it)

    buckets: dict[str, list[str]] = {}
    for name, record in sorted(dated.items()):
        verdict = date_symbol(name)
        added = record.get("added")
        marker = verdict.annotation
        if added is None:
            bucket = "bounded here, dated by the docs" if marker else "bounded here"
            detail = f"{record['floor']} or earlier"
            if marker:
                detail += f", docs say {marker}"
        elif marker is None:
            bucket = "dated here, and by nothing else"
            detail = added
        elif marker == added:
            bucket = "agrees with the docs"
            detail = added
        else:
            bucket = "DISAGREES with the docs"
            detail = f"source {added}, docs {marker} ({verdict.annotation_build})"
        buckets.setdefault(bucket, []).append(f"  {name:<28} {detail}")

    order = ["DISAGREES with the docs", "agrees with the docs"]
    for bucket in sorted(
        buckets, key=lambda key: (order.index(key) if key in order else len(order), key)
    ):
        print(f"===== {bucket} ({len(buckets[bucket])})")
        for line in buckets[bucket]:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
