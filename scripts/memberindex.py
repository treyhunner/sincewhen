#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
r"""Build the member index that ships with the package.

The dataset has an entry for every member worth detecting, and that is a
few thousand names out of a stdlib with tens of thousands. Asking about
one of the rest used to come back with the module and nothing else:

    $ sincewhen -s platform.system
    No entry for platform.system, but it lives in:
    platform module - Python 2.3 (released 2003-07-29)

True, and vague. `sincewhen -s platform.system` now says 2.3, because
`Lib/platform.py` in the 2.3 tarball binds `system`.

An owner is a module or a class inside one, and the class level was the
second half. `unittest.TestCase.assertNotEndsWith` had no answer at all
while this stopped at what a module binds, on the grounds that a method
belongs to the class above it. True, and the wrong conclusion.

This script does two things, and only the first is its own idea.

It works out *which* names to ask about, from three sources already in
the cache: the Sphinx inventories from 2.6, `modindex.members_in` for the
doc builds before them, and `source.members_in` for what each release's
tarball binds. Union them, split each dotted symbol into an owner and a
member, and that is the question list.

Then it asks `dating.py`, once per name, and writes down the answer. It
does not rank the sources itself and must not start: every rule it would
need already exists over there, several of them subtle enough to have
been got wrong once, and two implementations of a version number is one
too many. See the note in `AGENTS.md` for what the first draft did.

The build asks about 9259 names and takes a few minutes, which is fine
for something regenerated a few times a year and checked by
`just verify-dataset`.

Rather more names are dropped than kept, and `index()` says why for each
kind. 10024 go because the newest release no longer documents them,
which is most of why the file is 83 KB.

Usage:

    uv run scripts/memberindex.py --write     # regenerate members.txt
    uv run scripts/memberindex.py --grep system
    uv run scripts/memberindex.py --module platform
"""

import argparse
import sys
from collections import defaultdict
from functools import cache

from dating import date_symbol
from modindex import ARCHIVE_ORDER, members_in, modules_in
from source import SOURCE_ORDER
from source import members_in as source_members_in
from sources import INVENTORY_VERSIONS, ROOT, load_inventories

INDEX_FILE = ROOT / "src" / "sincewhen" / "members.txt"

# The newest release there is, taken from the inventory list rather than
# restated, so that a new Python cannot leave this indexing names it
# removed. What a release *added* is `dating.py`'s question; all this
# file has to know is which names Python still has.
NEWEST = INVENTORY_VERSIONS[-1]

# The 2.x line, which is a sibling of the 3.x one rather than its prefix.
LEGACY = ("2.6", "2.7")

# Nobody shipped code on 3.0 or 3.1, so a gap there does not count
# against continuity, and a 3.2 date for a name Python 2 already had is
# not a gap at all. See `_publish`.
FIRST_REAL_PYTHON_3 = "3.2"

# The inventory roles that can name a member of a module or of a class.
#
# `py:attribute` covers both, because the docs use it for module-level
# constants as well as for a class's own: `configparser.SECTCRE`,
# `logging.lastResort` and `select.PIPE_BUF` are all spelled that way,
# and so are `array.array.itemsize` and `traceback.FrameSummary.line`.
# It brings in four names
# that belong to an object rather than a module, `traceback.tb_frame`
# and its three siblings, which is what the docs themselves say and not
# worth a special case.
#
# The four method roles are what reach a class's own namespace, and they
# used to be left out on the grounds that a method belongs to the class
# above it rather than to the module. True, and the wrong conclusion: it
# is an argument for indexing the class as an owner in its own right,
# not for having no answer at all. `unittest.TestCase.assertNotEndsWith`
# came back empty until they were let in. What keeps the level honest is
# `split_member`, which will only cut at a name some release documents
# as a class.
MEMBER_ROLES = frozenset(
    {
        "py:function",
        "py:class",
        "py:data",
        "py:exception",
        "py:decorator",
        "py:attribute",
        "py:method",
        "py:classmethod",
        "py:staticmethod",
        "py:property",
    }
)

# The roles that name a class, which is the only thing `split_member` is
# allowed to treat as an owner below the module level.
CLASS_ROLES = frozenset({"py:class", "py:exception"})


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


@cache
def known_modules() -> frozenset[str]:
    """Every name any release documents as a module.

    A dotted symbol says nothing about where the module ends: `os.path`
    is a module and `os.getcwd` is a member, and only the module list
    tells them apart. The union across releases is what to split on,
    because a symbol is read out of the release that has it and the
    module it belongs to may be documented in another.
    """
    modules = set()
    for entries in load_inventories().values():
        modules |= {
            key.partition(" ")[2] for key in entries if key.startswith("py:module ")
        }
    for version in ARCHIVE_ORDER:
        modules |= modules_in(version)
    return frozenset(modules)


@cache
def known_classes() -> frozenset[str]:
    """Every dotted name any release documents as a class.

    The class level needs the same treatment the module level gets, and
    for the same reason: nothing about `unittest.TestCase.assertEqual`
    says where the owner ends. Read across releases rather than from the
    newest, because a member is recorded from whichever release has it
    and the class it hangs off may have been documented in another.
    """
    classes = set()
    for entries in load_inventories().values():
        classes |= {
            key.partition(" ")[2]
            for key in entries
            if key.partition(" ")[0] in CLASS_ROLES
        }
    return frozenset(classes)


def split_member(symbol: str) -> tuple[str, str] | None:
    """A dotted symbol as `(owner, member)`, if it is one.

    An owner is a module, or a class inside one. The longest module
    prefix wins, so `os.path.join` belongs to `os.path` rather than to
    `os`, and then one further cut is allowed if what it leaves behind
    is a name some release documents as a class:
    `unittest.TestCase.assertNotEndsWith` is `assertNotEndsWith` on
    `unittest.TestCase`.

    Only one further cut. `inspect.Parameter.kind.description` is a
    member of an attribute rather than of a class, and there is nothing
    the index could sensibly call its owner, so it is left out along
    with everything else still dotted after the class has been taken.
    """
    parts = symbol.split(".")
    for cut in range(len(parts) - 1, 0, -1):
        module = ".".join(parts[:cut])
        member = ".".join(parts[cut:])
        if module not in known_modules():
            continue
        if "." not in member:
            return module, member
        owner, _, name = member.rpartition(".")
        full = f"{module}.{owner}"
        return (full, name) if full in known_classes() else None
    return None


@cache
def documented() -> dict[str, frozenset[str]]:
    """`{"owner.member": {version, ...}}` across the whole corpus.

    A dotted symbol has to be split before it can be recorded, and only
    the sources that write the module out separately are exempt. The
    source tarballs are read a module at a time, so they say which is
    which; the doc builds hand over one dotted name.

    Only the inventories reach a class member. The archives index one
    name per module page and the tarballs are read for what a module
    binds, so `unittest.TestCase.subTest` is a question the 3.x line
    answers or nobody does, which is exactly what `_publish` is careful
    about.
    """
    seen: dict[str, set[str]] = defaultdict(set)

    def record(module: str, member: str, version: str) -> None:
        # A leading underscore is a private name or a doc anchor, and
        # `inventory.py` drops both for the same reason.
        if not member.startswith("_"):
            seen[f"{module}.{member}"].add(version)

    def record_dotted(symbol: str, version: str) -> None:
        split = split_member(symbol)
        if split is not None:
            record(*split, version)

    for version in ARCHIVE_ORDER:
        for symbol in members_in(version):
            record_dotted(symbol, version)
    for version in SOURCE_ORDER:
        bound = source_members_in(version)
        for module, names in bound.items():
            for member in names:
                record(module, member, version)
    for version, entries in load_inventories().items():
        for key in entries:
            role, _, symbol = key.partition(" ")
            if role in MEMBER_ROLES and ".._" not in symbol:
                record_dotted(symbol, version)
    return {name: frozenset(versions) for name, versions in seen.items()}


# Modules whose contents nothing in the corpus can read, so that every
# method here would date the markup rather than the member.
#
# `__future__` documents its features as a table of `_Feature` instances,
# so no name in it carries a marker and none was given an inventory entry
# of its own until 3.13: `division` would read as 3.13 rather than 2.2.
# The dataset has entries for the ones worth having, from their PEPs.
#
# `errno` is a curation rule rather than a reading problem. Every one of
# its members sits behind an `#ifdef`, so the honest claim is "since 1.5,
# where the platform provides it", and the schema cannot say that yet.
# AGENTS.md keeps them out of the dataset for that reason and the index
# has to keep them out for the same one.
UNREADABLE = frozenset({"__future__", "errno"})

# The oldest release with a Sphinx inventory. A 3.x inventory diff cannot
# see anything older than this, so a name it dates to the start of the
# 3.x line is a name it may simply have started indexing there.
OLDEST_INVENTORY = "2.6"


@cache
def _legacy_index() -> dict[str, str]:
    """The oldest 2.x inventory listing each name, for the ones that are.

    Python 3.0 forked from 2.6, so these are a sibling of the 3.x line
    rather than its prefix, and `dating.py` reads them only through its
    `backported` and `early-inventory` branches, both of which need an
    annotation. A name in the 2.7 inventory with no marker anywhere falls
    through all of that and is dated by the 3.x line alone.
    """
    found: dict[str, str] = {}
    inventories = load_inventories()
    for version in reversed(LEGACY):
        for key in inventories.get(version, ()):
            role, _, symbol = key.partition(" ")
            if role in MEMBER_ROLES:
                found[symbol] = version
    return found


def _publish(name: str, verdict) -> tuple[str, bool] | None:
    """What the index may say about a name, given `dating.py`'s verdict.

    Everything except a bare `inventory-only` verdict is published as it
    stands. That status is the one with no corroboration in it: the 3.x
    inventories dated the name and nothing else spoke, and what they date
    is when a release *indexed* a name rather than when it got one. The
    dataset can absorb that because 23 hand-written entries exist to
    override exactly these, and the index has no such escape hatch.

    Two things rescue such a verdict, and where neither does, the honest
    answer is to say nothing and let search fall back to the module.

    A name the 2.6 or 2.7 inventory already lists was demonstrably in
    Python 2, so a 3.2 date is the age of the 3.x index entry and the
    real claim is a bound at the 2.x release. `curses.resetty` is in the
    2.7 inventory and reads as 3.2 without this. A date later than 3.2
    is left alone, because then releases other than 3.0 and 3.1 lack the
    name and the gap is real: `hmac.compare_digest` is in 2.7 and in 3.3,
    and 3.3 is right.

    An owner that postdates the inventories has no such problem, because
    its members were indexed from the release it arrived in. It is the
    old ones that get dated by their markup, and there the index
    stays quiet: `hashlib.md5` shipped with `hashlib` in 2.5 and was
    first indexed in 3.11, `signal.SIGINT` reads as 3.7, and
    `calendar.MONDAY` as 3.10.

    A class owner gets that rescue on a shorter leash, and the reason is
    the argument the rescue rests on rather than anything about classes
    as such. "Its members were indexed from the release it arrived in"
    is close enough to true of a module page, which comes into existence
    with its module. It is not true of a class, whose page grows a
    member at a time and lists what the class *inherits* alongside what
    it defines. So an inventory-only class member is published only
    where it really was indexed in the class's own release, and where
    the class's date is a date rather than a bound.

    That is 160 names, and about half of them were wrong: `enum.Enum` is
    3.4 and `name` and `value` read as 3.11, `logging.Logger.name` as
    3.11 against a class the 2.7 inventory already lists, and
    `pathlib.Path.as_uri` as 3.13, which is the release the method moved
    down from `PurePath` rather than the release it started working.
    The other half were right and are lost: `ast.AST.end_lineno` really
    is 3.8. Losing a right answer to a rule that also loses a wrong one
    is the trade this whole index is built on, and the sharper answer is
    still a `just whenadded` away.

    A class's own answer is read through this same function, because a
    class that cannot be published is not a class anything can be dated
    from. `logging.Logger` is the case: bounded at 2.7 by the legacy
    rescue, so nothing under it leans on 3.2.

    A module's is not, and deliberately. The module half of the index
    has 1269 members cross-checked against dataset entries and the
    tighter reading costs 432 of them, `logging.handlers.QueueHandler`
    and `email.policy.Policy` among them, both of which are right. What
    carries them is that `logging.handlers` is itself only dated by the
    inventories, so a rule that refuses to lean on an unpublishable
    owner refuses these too. Whether that reading should reach the
    module level is a real question and a separate one, and it wants
    `verify-dataset` watching rather than a change made in passing here.
    """
    if verdict.status != "inventory-only":
        return verdict.added, verdict.or_earlier

    legacy = _legacy_index().get(name)
    if legacy is not None:
        if version_key(verdict.added) <= version_key(FIRST_REAL_PYTHON_3):
            return legacy, True
        return verdict.added, verdict.or_earlier

    owner_name = name.rpartition(".")[0]
    if owner_name in known_classes():
        owner = published(owner_name)
        if owner is None or owner[1] or verdict.added != owner[0]:
            return None
        return verdict.added, verdict.or_earlier

    module = date_symbol(owner_name)
    if module.added is None or version_key(module.added) < version_key(
        OLDEST_INVENTORY
    ):
        return None
    return verdict.added, verdict.or_earlier


@cache
def published(name: str) -> tuple[str, bool] | None:
    """What the index may say about `name`, or `None` for nothing.

    The one entry point, so that a member and the owner it leans on are
    answered the same way. Cached because an owner is asked about once
    per member it holds.
    """
    verdict = date_symbol(name)
    if verdict.added is None:
        return None
    return _publish(name, verdict)


@cache
def index() -> dict[str, dict[str, tuple[str, bool]]]:
    """`{owner: {member: (version, or_earlier)}}`.

    An owner is a module, or a class inside one. Both are asked the same
    question and answered by the same arbiter, and both are the binding
    constraint on what they hold: a method cannot predate its class any
    more than a function can predate its module.

    The version is `dating.py`'s verdict, which is the same arbiter that
    rechecks every entry in the dataset. That is the whole design: the
    index is not a fourth opinion about when things arrived, it is the
    pipeline's own answer for the several thousand names nobody is going
    to write an entry for, worked out once and written down.

    Deriving it here rather than ranking the sources again is what took
    the members that disagree with a dataset entry from 6 to 1, and the
    interpreters have since corrected that entry and closed the last one. Every rule this
    needs already existed: a bound the module closes, a marker that
    outranks a floor, a backport to 2.7 that really arrived on the spine,
    a re-add that belongs to the 3.x line. Restating any of them here
    means maintaining them twice and getting a version number wrong when
    they drift.

    Four kinds of name are left out, and each silence is deliberate:

    - 10024 the newest release no longer documents, since answering for
      them would be answering about a language this parser cannot read;
    - 1963 `dating.py` refuses, because the sources contradict each
      other;
    - 168 in a module nothing here can read, see `UNREADABLE`;
    - 1277 whose verdict rests on an inventory diff alone and cannot be
      corroborated, see `_publish`.

    The class tier accounts for most of the growth in all four, and for
    the last two disproportionately: 1537 of the refusals and 558 of the
    uncorroborated ones are class members, out of 4193 asked about.
    A class member is the shape the sources agree about least, which is
    why so few of them are published and why the ones that are had to be
    argued for one rule at a time.

    A member dated older than its own owner takes the owner's date
    instead. It cannot be older, so the owner is the binding constraint,
    and the one that reaches this is `copyreg`, which is 3.0 as spelled
    while its members inherit `copy_reg`'s history. That is the rename
    rule in AGENTS.md, one level down, and the same closing of a bound
    that `bounded_by_its_module` does: a bounded module still passes its
    bound along.
    """
    members: dict[str, dict[str, tuple[str, bool]]] = defaultdict(dict)
    for name, versions in documented().items():
        owner_name, _, member = name.rpartition(".")
        if NEWEST not in versions or owner_name.partition(".")[0] in UNREADABLE:
            continue
        answer = published(name)
        if answer is None:
            continue
        owner = date_symbol(owner_name)
        if owner.added is not None and version_key(answer[0]) < version_key(
            owner.added
        ):
            answer = (owner.added, owner.or_earlier)
        members[owner_name][member] = answer
    return dict(sorted(members.items()))


def render() -> str:
    """The index as the package reads it.

    One line per module: the module's name, then a release and the
    members recorded from it, repeated. Grouping by release is what keeps
    the file small, and a plain text format is what keeps it reviewable
    as a diff, which a second dataset nobody can read by hand would not
    be.
    """
    lines = [
        "# Which members each stdlib module has had, and from which release.",
        "# Generated by scripts/memberindex.py. Do not edit by hand.",
        "#",
        "# <module> <release> <member>,... <release>? <member>,...",
        "#",
        "# A release is when those members arrived. One written with `?` could",
        "# only be bounded: `1.5?` means 1.5 or earlier.",
    ]
    for module, members in index().items():
        groups: dict[str, list[str]] = defaultdict(list)
        for member, (version, or_earlier) in members.items():
            groups[version + "?" * or_earlier].append(member)
        parts = [
            f"{tag} {','.join(sorted(groups[tag]))}"
            for tag in sorted(
                groups, key=lambda tag: (version_key(tag.rstrip("?")), tag)
            )
        ]
        lines.append(f"{module} {' '.join(parts)}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="regenerate members.txt")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the committed index is not what the sources produce",
    )
    parser.add_argument("--module", help="show one module's members")
    parser.add_argument("--grep", help="show every module with a member of this name")
    args = parser.parse_args()

    built = index()

    def show(name: str, record: tuple[str, bool]) -> str:
        version, or_earlier = record
        return f"{name:<32} {version}{' or earlier' if or_earlier else ''}"

    if args.module:
        for member, record in sorted(built.get(args.module, {}).items()):
            print(show(member, record))
        return 0

    if args.grep:
        for module, members in built.items():
            if args.grep in members:
                print(show(f"{module}.{args.grep}", members[args.grep]))
        return 0

    text = render()
    members = sum(len(names) for names in built.values())

    if args.check:
        committed = INDEX_FILE.read_text(encoding="utf-8")
        if committed != text:
            print(
                f"{INDEX_FILE.name} is not what the sources produce. "
                "Rebuild it with: just memberindex --write",
                file=sys.stderr,
            )
            return 1
        print(f"{members} indexed members re-derived and unchanged.")
        return 0

    if args.write:
        INDEX_FILE.write_text(text, encoding="utf-8")
        print(f"{len(text):,} bytes written to {INDEX_FILE}")

    print(f"{members} members across {len(built)} modules", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
