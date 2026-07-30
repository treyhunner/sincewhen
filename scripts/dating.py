#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Answer "when was this added?" from the cached sources, several ways.

This is the oracle the dataset is checked against. It never guesses: it
reports what each method found, says whether they agree, and leaves a
disagreement standing so a human has to look at it.

The inventory diff gives a hard verdict for anything added in 3.1 or
later, because a symbol absent from one release's `objects.inv` and
present in the next was added in that release. For anything older it can
only give a *floor*: "already documented in 3.0", which rules out later
versions without picking one. The annotation grep fills that in, since
the Python 2.7 docs still carry markers going back to 1.3. The members of
the builtin types are a floor either way: see `BUILTIN_TYPES` below.

Below all of those sits the interpreter's own source, which is the only
witness that predates the HTML doc builds and the only one whose absence
means anything. It speaks for builtins, modules and module members, and
only for names it actually finds and can account for, so everything else
falls through to the doc-derived methods exactly as before.

Usage:

    uv run scripts/dating.py math.isclose tomllib itertools.batched
"""

import sys
from dataclasses import dataclass, field
from functools import cache

from annotations import collect as collect_annotations
from interpreters import dated as interpreter_dated
from modindex import HTML_BUILDS, dated_builtins, dated_members, dated_modules
from source import SOURCE_ORDER
from source import dated_builtins as source_builtins
from source import dated_members as source_members
from source import dated_modules as source_modules
from sources import load_inventories

# The 3.x line, in release order: a single linear history.
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

# The 2.x line. Python 3.0 forked from 2.6, so this is a sibling of the
# spine rather than its prefix, and the two are never chained.
LEGACY = ("2.6", "2.7")

# Which cached text build to trust for a given era. The 3.x docs dropped
# the Python 2 markers, and the 2.7 docs obviously stop at 2.7.
ANNOTATION_BUILDS = ("2.7", "3.14")

# The oldest release whose source survives, and so the floor of every
# method here. A name already in it cannot be dated, only bounded.
OLDEST_SOURCE = SOURCE_ORDER[0]


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


# The newest release with an HTML module index. A module missing from
# it but present in the 2.6 inventory can only have arrived in 2.6.
NEWEST_HTML = list(HTML_BUILDS)[-1]

# The builtin types, whose members the inventory can only ever bound.
#
# Every other kind of name gets a hard date out of an inventory diff: a
# module or a function absent from one release's `objects.inv` and
# present in the next was documented in that release, and documentation
# follows shipping closely enough to date it. A method of a builtin type
# does not work that way, because `stdtypes.rst` describes these in
# family tables rather than one entry per name, and Sphinx grew per-name
# markup for those tables release by release. So the release that first
# indexes one of these is the age of the markup and not of the method:
# `list.copy` arrived in 3.3 and was first indexed in 3.13, `range.start`
# in 3.3 and first indexed in 3.5, `type.mro` predates Python 3 entirely
# and was first indexed in 3.12, and `bytearray.capitalize` shipped with
# `bytearray` in 2.6 and was first indexed in 3.4.
#
# What does date these is the docs' own "Added in version" markers, which
# sit on the family table's own signature lines. So an inventory entry
# for one of these contributes a floor, exactly as an inventory that
# starts with the name already in it does, and the annotation answers.
#
# The 2.6-to-2.7 step is one release apart and looks safer, and is not.
# It dates 20 `frozenset` methods to 2.7 where `frozenset` itself is 2.4,
# and `frozenset.add`, which no `frozenset` has ever had: the 2.7 docs
# describe the whole set family on one page, so the markup covers names
# the type does not even have. So this holds for both lines.
BUILTIN_TYPES = frozenset(
    {
        "bool",
        "bytearray",
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "memoryview",
        "object",
        "range",
        "set",
        "slice",
        "str",
        "tuple",
        "type",
    }
)


def is_type_member(name: str) -> bool:
    """Whether `name` is a method or attribute of a builtin type."""
    head, _, member = name.partition(".")
    return head in BUILTIN_TYPES and bool(member)


# Python 3.0 and 3.1 do not count against continuity. Plenty of features
# shipped in 2.7 and then reappeared in 3.2, and calling those 3.2
# additions would be pedantically true and practically wrong: nobody
# shipped code on 3.0 or 3.1, so a gap there is not a gap anyone lived
# through. A feature in 2.7 and in 3.2 is dated 2.7. A feature missing
# from 3.2 as well has a real gap, and takes the later date.
FIRST_REAL_PYTHON_3 = "3.2"


@dataclass
class Verdict:
    """What each method says about one name, and whether they agree."""

    name: str
    interpreter: str | None = None
    interpreter_absent_in: str | None = None
    interpreter_is_floor: bool = False
    interpreter_note: str | None = None
    source: str | None = None
    source_absent_in: str | None = None
    source_is_floor: bool = False
    source_path: str | None = None
    archive: str | None = None
    archive_absent_in: str | None = None
    archive_is_floor: bool = False
    inventory: str | None = None
    absent_in: str | None = None
    present_in: str | None = None
    floor: str | None = None
    annotation: str | None = None
    annotation_build: str | None = None
    quote: str | None = None
    annotation_file: str | None = None
    line: str | None = None
    module: str | None = None
    module_added: str | None = None
    module_absent_in: str | None = None
    module_is_floor: bool = False
    roles: set[str] = field(default_factory=set)

    @property
    def _is_floor(self) -> bool:
        """Whether the winning method could only bound the answer."""
        match self.status:
            case "interpreter" | "interpreter-overrides-docs":
                return self.interpreter_is_floor
            case "source" | "source-overrides-docs":
                return self.source_is_floor
            case "archive" | "docs-overstate":
                return self.archive_is_floor
        return False

    @property
    def bounded_by_its_module(self) -> bool:
        """Whether the module this belongs to closes an open bound.

        A member cannot predate the module that holds it, so a bound at
        exactly the release the module arrived in is not a bound at all:
        there is nothing under it to reach. `weakref` arrived in 2.1 and
        the 2.1 docs are the oldest that describe `weakref.ref`, so
        `weakref.ref` is 2.1 and not "2.1 or earlier".

        This only follows when the module is *dated*. A module that is
        itself bounded passes its bound along rather than closing it,
        which is why `operator.add` stays "1.5 or earlier": `operator` is
        a C extension, the archives can only bound it, and both of them
        may well be older.

        A member the sources dated on its own is not bounded by anything,
        and keeps the bracket its own evidence found rather than
        borrowing the module's.
        """
        return (
            self._is_floor
            and self.module_added is not None
            and not self.module_is_floor
            and self.module_added == self.added
        )

    @property
    def absent_from(self) -> str | None:
        """The newest release that demonstrably lacks this name.

        Whichever method won says it, and each keeps its own, so this
        picks the one that matches the answer rather than the first one
        that happens to be filled in.
        """
        match self.status:
            case "interpreter" | "interpreter-overrides-docs":
                return self.interpreter_absent_in
            case "source" | "source-overrides-docs":
                return self.source_absent_in
            case "archive" | "docs-overstate":
                return self.archive_absent_in
        return self.absent_in

    @property
    def or_earlier(self) -> bool:
        """Whether the answer is a bound rather than a date.

        Only true when the answer *is* the floor of whichever method
        produced it, and nothing else closes it. A name that one method
        can merely bound but another dates outright gets a real date, not
        a bounded one, which is why `map` stopped being "1.2 or earlier"
        once the source could be read: the archives were reporting their
        own age, not its.
        """
        return self._is_floor and not self.bounded_by_its_module

    @property
    def added(self) -> str | None:
        """The version to believe, or `None` if the methods disagree."""
        inventory, annotation = self.inventory, self.annotation
        match self.status:
            case (
                "conflict"
                | "source-contradicts-archive"
                | "interpreter-contradicts-source"
                | "interpreter-contradicts-docs"
            ):
                return None
            case "interpreter" | "interpreter-overrides-docs":
                return self.interpreter
            case "source" | "source-overrides-docs":
                return self.source
            case "archive" | "docs-overstate":
                # `docs-overstate` means the docs claim it arrived later
                # than a release that demonstrably has it, so the
                # release wins.
                return self.archive
            case "docs-predate":
                # The docs claim it arrived earlier than the oldest
                # archive that lists it. Being listed proves presence;
                # not being listed proves very little, because the old
                # builds have real gaps, so the docs win.
                return annotation
            case "backported" if inventory is not None:
                # Available in a 2.x release and again from this 3.x
                # one. If the only releases in between are 3.0 and 3.1,
                # the 2.x date stands; otherwise the gap is real and the
                # 3.x date is the oldest it has been available since.
                if version_key(inventory) <= version_key(FIRST_REAL_PYTHON_3):
                    return annotation
                return inventory
            case "early-inventory":
                # The docs described it before the inventory indexed it.
                return annotation
        return inventory or annotation

    @property
    def status(self) -> str:
        """Which sources spoke, and whether they can be reconciled.

        Two disagreements are routine rather than suspicious. A symbol
        backported to 2.7 shows up in the 3.x inventories later than the
        docs date it, because 3.0 and 3.1 genuinely did not have it. And
        the 2.6 inventory is an early Sphinx build that indexed less
        than the 2.6 docs described, so it can make a 2.6 addition look
        like a 2.7 one.

        Against the archives, presence and absence carry different
        weight, and that asymmetry settles both directions of
        disagreement.

        Seeing something listed in a release proves it was there, which
        beats a later release's claim that it arrived afterwards: the
        2.7 docs date `bisect` to 2.1 and the 1.5 module index contains
        it, so the docs are simply wrong.

        Not seeing it proves much less, because the old builds have real
        gaps and documentation lags shipping. Python 1.6 shipped
        `zipfile` and documented it but built no module-index entry for
        it; `platform` shipped in 2.3 and was documented in 2.4;
        `property` shipped in 2.2 and reached the built-in functions
        page in 2.3. In all three the docs are right and the archive is
        merely late.
        """
        # Both the source and the pre-Sphinx archives speak for the old
        # era, and both usually beat the 3.x inventories, which are
        # sparse for 3.0 and 3.1 and make old modules look new:
        # `profile` is in the 1.5 docs and first indexed in 3.1.
        #
        # Both lose when the 3.x line dates the name itself *and the
        # current docs say the same*. Two sources agreeing means the
        # name really did go away and come back: `types.NoneType` is
        # bound in the 1.1 tarball and in the 1.2 docs, then gone for
        # all of Python 3 until 3.10.
        readded = (
            self.inventory
            and self.line == "spine"
            and self.annotation == self.inventory
        )

        # The interpreter's source outranks every doc-derived method,
        # and it is the one place where absence carries as much weight
        # as presence, because a method table is the list the module is
        # built from rather than a description of it. So unlike the
        # archive, it wins in both directions: the docs cannot be right
        # that a name predates a release whose source does not bind it.
        #
        # That holds only for the dates it can prove. A source *floor* is
        # not an absence claim at all, only a limit on what could be
        # read: `gc.collect` is in a table this cannot follow until 2.3
        # and the 2.0 docs list it, `time.strptime` is behind an
        # `#ifdef` until 2.3, and `random.randrange` reaches `random` by
        # a re-export until 2.1.
        #
        # So a floor yields to an archive that shows the name earlier,
        # and to any annotation that does not show it later, because an
        # annotation is a date and a floor is only a bound. That second
        # case is mostly the newest release the source can read: without
        # it, everything the docs date to 2.5 would be reported as "2.5
        # or earlier" purely because 2.5 is where the tarballs stop.
        #
        # A source date older than the archive's is the whole point of
        # the method. One that is newer is a real disagreement: both
        # sides claim proof and they cannot both be right, so it is left
        # standing rather than resolved.
        # A built interpreter outranks everything that reads a
        # *description* of Python, because availability is precisely what
        # it measures and every other method infers it. It sees what no
        # text can: `re.finditer` is defined in 2.2's `sre.py` and left
        # out of its `__all__`, so `from sre import *` never binds it and
        # `re.finditer` is 2.3; `token` ships in 1.2 and raises on import.
        #
        # Its absences are already guarded where they are derived, so a
        # release that merely failed to build a module reports a floor
        # here rather than a date. A floor claims nothing the other
        # methods cannot, so it falls through to them.
        #
        # Against the source it is a real disagreement rather than a
        # ranking: both claim proof, one about what the text binds and one
        # about what the interpreter bound, and they cannot both be right.
        if self.interpreter and not readded:
            if not self.interpreter_is_floor:
                if (
                    self.source
                    and not self.source_is_floor
                    and self.source != self.interpreter
                ):
                    return "interpreter-contradicts-source"
                if self.annotation and self.annotation != self.interpreter:
                    if version_key(self.interpreter) > version_key(self.annotation):
                        # The interpreter says it arrived *later* than the
                        # docs claim, and this method cannot tell that from
                        # a micro release having fixed it. The corpus builds
                        # each release's `.0`, so an absence here is an
                        # absence in 2.2.0 rather than in 2.2.
                        #
                        # `re.finditer` is exactly this: unreachable in
                        # 2.2.0 and 2.2.1 because `sre.__all__` left the
                        # name out, and reachable from 2.2.2, which added
                        # `__all__.append("finditer")`. The docs saying
                        # "New in version 2.2" are right about the release
                        # even though the release's own `.0` could not do
                        # it. So this needs a human rather than a winner.
                        return "interpreter-contradicts-docs"
                    return "interpreter-overrides-docs"
                return "interpreter"

            # A floor is still worth having when it is tighter than the
            # other floors, for the reason every doc-derived floor is
            # suspect: "1.5 or earlier" for `os.path` is the age of the
            # oldest doc build that lists it, and 1.2 is the age of the
            # feature. It never beats an actual date, from any method.
            dated_elsewhere = (
                (self.source and not self.source_is_floor)
                or (self.archive and not self.archive_is_floor)
                or self.annotation is not None
            )
            others = [
                version
                for version in (self.source, self.archive)
                if version is not None
            ]
            if (
                not dated_elsewhere
                and others
                and all(
                    version_key(self.interpreter) < version_key(other)
                    for other in others
                )
            ):
                return "interpreter"

        if self.source and not readded:
            outranked = self.archive and version_key(self.archive) < version_key(
                self.source
            )
            if self.source_is_floor:
                dated = self.annotation and version_key(self.annotation) <= version_key(
                    self.source
                )
                outranked = outranked or dated
            elif outranked:
                return "source-contradicts-archive"
            if not outranked:
                if self.annotation and self.annotation != self.source:
                    return "source-overrides-docs"
                return "source"

        if self.archive and not readded:
            if self.annotation and self.annotation != self.archive:
                later = version_key(self.annotation) > version_key(self.archive)
                return "docs-overstate" if later else "docs-predate"
            return "archive"
        if self.inventory and self.annotation:
            if self.inventory == self.annotation:
                return "agree"
            older = version_key(self.annotation) < version_key(self.inventory)
            if older and self.line == "spine" and self.annotation.startswith("2."):
                return "backported"
            if older and self.line == "legacy":
                return "early-inventory"
            return "conflict"
        if self.inventory:
            return "inventory-only"
        if self.annotation:
            # An annotation newer than the release that already documents
            # the name cannot be right.
            if self.floor and version_key(self.annotation) > version_key(self.floor):
                return "conflict"
            return "annotation-only"
        return "unknown"

    def _closed_by_module(self) -> dict:
        """The half of a member's evidence that its module supplies.

        A bound that the module closes has to say so, and it has a
        release that demonstrably lacks the name to point at: whatever
        lacks the module lacks everything in it. So `gc.DEBUG_LEAK`
        brackets on 1.6 and 2.0, the same two releases `gc` does.
        """
        if not self.bounded_by_its_module:
            return {}
        return {
            "absent_in": self.module_absent_in,
            "note": (
                f"{self.module} is absent from {self.module_absent_in} and "
                f"arrived in {self.module_added}, so nothing in it can be older."
            ),
        }

    def evidence(self, checked: str) -> dict:
        """The provenance table this verdict justifies, ready for TOML."""
        if self.status in {"interpreter", "interpreter-overrides-docs"}:
            evidence = {
                "method": "interpreter",
                "symbol": self.name,
                "absent_in": self.interpreter_absent_in,
                "present_in": self.interpreter,
            } | self._closed_by_module()
            if self.or_earlier:
                evidence["note"] = (
                    f"Resolves in {self.interpreter}, and no earlier release "
                    "can be shown to lack it. " + (self.interpreter_note or "")
                ).strip()
            elif self.interpreter_note:
                evidence["note"] = self.interpreter_note
            elif self.status == "interpreter-overrides-docs":
                evidence["note"] = (
                    f"The {self.annotation_build} docs date it to "
                    f"{self.annotation}, but the {self.interpreter_absent_in} "
                    "interpreter does not resolve it and "
                    f"{self.interpreter} does."
                )
            return evidence | {"checked": checked}
        if self.status in {"source", "source-overrides-docs"}:
            evidence = {
                "method": "source",
                "symbol": self.name,
                "file": self.source_path,
                "absent_in": self.source_absent_in,
                "present_in": self.source,
            } | self._closed_by_module()
            if self.or_earlier and self.source == OLDEST_SOURCE:
                evidence["note"] = (
                    f"Registered in {self.source}, the oldest source release "
                    "there is, so it is at least that old and may be older."
                )
            elif self.or_earlier:
                # A floor above the oldest release means the older
                # source neither binds the name nor rules it out: a
                # method table row inside an `#if`, or a module whose
                # own file is not the whole of its namespace.
                evidence["note"] = (
                    f"Bound in {self.source}, so it is at least that old. "
                    "No earlier source release can be shown to lack it."
                )
            elif self.status == "source-overrides-docs":
                evidence["note"] = (
                    f"The {self.annotation_build} docs date it to "
                    f"{self.annotation}, but the {self.source_absent_in} "
                    "interpreter does not register it."
                )
            return evidence | {"checked": checked}
        if self.status in {"archive", "docs-overstate"}:
            evidence = {
                "method": "archive",
                "absent_in": self.archive_absent_in,
                "present_in": self.archive,
            } | self._closed_by_module()
            if self.or_earlier:
                evidence["note"] = (
                    f"Documented in {self.archive}, the oldest archived "
                    "doc build, so it is at least that old and may be older."
                )
            elif self.status == "docs-overstate":
                evidence["note"] = (
                    f"The {self.annotation_build} docs date it to "
                    f"{self.annotation}, but the {self.archive} "
                    "documentation already lists it."
                )
            return evidence | {"checked": checked}
        if self.added == self.inventory:
            evidence = {
                "method": "objects.inv",
                "symbol": f"{sorted(self.roles)[0]} {self.name}"
                if self.roles
                else self.name,
                "absent_in": self.absent_in,
                "present_in": self.present_in,
            }
            if self.status == "backported":
                evidence["note"] = (
                    f"Also in Python {self.annotation}, but missing from "
                    f"{self.absent_in} as well as 3.0 and 3.1, so "
                    f"{self.inventory} is the oldest release it has been "
                    "available in ever since."
                )
            return evidence | {"checked": checked}
        evidence = {
            "method": "annotation",
            "docs": f"{self.annotation_build}:{self.annotation_file}",
            "quote": self.quote,
        }
        if self.status == "backported":
            evidence["note"] = (
                f"Missing from Python 3.0 and 3.1 and back in "
                f"{self.inventory}. Those two releases do not count "
                f"against continuity, so the date is {self.annotation}."
            )
        return evidence | {"checked": checked}


@cache
def _inventory_index() -> dict[str, dict[str, set[str]]]:
    """`{name: {version: {role, ...}}}` across every cached inventory."""
    index: dict[str, dict[str, set[str]]] = {}
    for version, entries in load_inventories().items():
        for key in entries:
            role, _, name = key.partition(" ")
            index.setdefault(name, {}).setdefault(version, set()).add(role)
    return index


@cache
def _annotation_index() -> dict[str, dict]:
    """First recorded marker per name, oldest build first.

    The 2.7 build is read first so that a name dated in both builds keeps
    its original Python 2 date rather than a later "changed in" note.
    """
    index: dict[str, dict] = {}
    for build in ANNOTATION_BUILDS:
        for record in collect_annotations(build):
            existing = index.get(record["name"])
            if existing is None or version_key(record["added"]) < version_key(
                existing["added"]
            ):
                index[record["name"]] = record | {"build": build}
    return index


def _date_from_interpreters(verdict: Verdict) -> None:
    """Fill in what the built interpreters say about a name.

    The table records a name per kind, because how you ask differs: a
    module is imported, a builtin is referenced, a member is reached
    through its module. Which one a name is here is decided the same way
    the source method decides it, so that `repr` the module and `repr` the
    builtin do not answer for each other.

    A gap is left alone deliberately. `token` is importable in 1.0 and
    1.1, raises in 1.2 and 1.3, and works again from 1.4, and no single
    version can say that. The schema has no way to record it, so the
    entry keeps whatever the other methods make of it and the gap is
    reported by `interpreters.py --report` for a human.
    """
    if verdict.module is not None:
        # A dotted name is usually a member and sometimes a submodule, and
        # the table is keyed by how the dataset asks about it. `os.path`
        # is listed as a module, so looking only for a member finds
        # nothing and the answer falls back to the doc builds.
        kinds = ("attribute", "module")
    elif verdict.name in source_modules() or verdict.name in dated_modules():
        kinds = ("module",)
    else:
        kinds = ("builtin", "module")
    for kind in kinds:
        found = interpreter_dated(f"{kind} {verdict.name}")
        if found is None or "gap" in found or "removed_after" in found:
            continue
        version = found.get("added") or found["floor"]
        if verdict.module is not None and _predates_module(verdict, version):
            return
        verdict.interpreter = version
        verdict.interpreter_absent_in = found.get("absent_in")
        verdict.interpreter_is_floor = "added" not in found
        if found.get("unbuilt_in"):
            verdict.interpreter_note = (
                f"Resolves from {version}. Python {found['unbuilt_in']} ships "
                "it too, so its absence there is this build's and not that "
                "release's."
            )
        return


def _date_from_source(verdict: Verdict) -> None:
    """Fill in what the interpreter's own source says about a name.

    Builtins come from the builtins table, and only those it names. A
    name bound into the builtins dict some other way, like `None` or an
    exception, is absent from the table without being absent from the
    release, so staying quiet about those is what keeps this method's
    absences worth trusting.

    A module wins the name outright, the way it does for the archives,
    because a name can be both: `repr` is a builtin and a module, and
    reading the builtins table for the module would answer about the
    wrong thing. A module the source era never shipped is left to the
    archives rather than answered from the builtins table.

    A dotted name is a module member, which is read from whatever
    implements the module: the method table and insert calls of a C
    module, or the top-level bindings of a Python one.
    """
    if verdict.module is not None:
        record = source_members().get(verdict.name)
    elif verdict.name in source_modules() or verdict.name in dated_modules():
        record = source_modules().get(verdict.name)
    else:
        record = source_builtins().get(verdict.name)
    if record is None:
        return

    found = record.get("added") or record["floor"]
    if verdict.module is not None and _predates_module(verdict, found):
        return
    verdict.source = found
    verdict.source_absent_in = record.get("absent_in")
    verdict.source_is_floor = "added" not in record
    verdict.source_path = record["file"]


def _date_the_module(verdict: Verdict) -> None:
    """Date the module a dotted name belongs to, if it is one.

    A member is answered partly by its module, in both directions: the
    module is a floor under it, and where the module is dated the module
    is a ceiling too. Both need the module's own verdict, so it is taken
    once here rather than recomputed by each rule that wants it.
    """
    module, _, member = verdict.name.rpartition(".")
    if not (module and member):
        return
    found = date_symbol(module)
    verdict.module = module
    verdict.module_added = found.added
    verdict.module_absent_in = found.absent_from
    verdict.module_is_floor = found.or_earlier


def _predates_module(verdict: Verdict, version: str) -> bool:
    """Whether a member's source date is older than its module's own.

    A member cannot be available before the module that holds it, and
    the source can claim otherwise. `signalmodule.c` is in the 1.1
    tarball and `signal` is dated 1.2, because `Modules/Setup` ships the
    module commented out and the tarball cannot say what a build could
    import. Where the two disagree the module is the binding constraint,
    so the source stays quiet and the archives answer for both.
    """
    added = verdict.module_added
    return added is not None and version_key(version) < version_key(added)


def _date_from_archive(verdict: Verdict, presence: dict) -> None:
    """Fill in what the pre-Sphinx HTML docs say about a name.

    Modules come from each release's module index and builtins from its
    built-in functions page. Either shape can produce two kinds of
    answer: the name shows up partway through the archives, which dates
    it outright, or it is there in the oldest one, which is a floor.

    A module in none of the archives but in the 2.6 inventory has to be
    2.6, since 2.5 is the newest release with an HTML index.
    """
    record = (
        dated_modules().get(verdict.name)
        or dated_builtins().get(verdict.name)
        or dated_members().get(verdict.name)
    )
    if record is not None:
        verdict.archive = record.get("added") or record["floor"]
        verdict.archive_absent_in = record.get("absent_in")
        # Present in the oldest archive there is, so this is the oldest
        # release that can be shown to have it, not the one that added
        # it. `map` is as old as Python; 1.2 is just as far back as the
        # documentation goes.
        verdict.archive_is_floor = "added" not in record
        return

    if "2.6" in presence and "py:module" in presence["2.6"]:
        verdict.archive = "2.6"
        verdict.archive_absent_in = NEWEST_HTML


def date_symbol(name: str) -> Verdict:
    """What the cached docs say about when `name` arrived."""
    verdict = Verdict(name=name)
    _date_the_module(verdict)

    presence = _inventory_index().get(name, {})
    _date_from_interpreters(verdict)
    _date_from_source(verdict)
    _date_from_archive(verdict, presence)
    if presence:
        for label, line in (("spine", SPINE), ("legacy", LEGACY)):
            available = [version for version in line if version in presence]
            if not available:
                continue
            first = available[0]
            if first == line[0] or is_type_member(verdict.name):
                # Already there when this line starts, or indexed later
                # than it shipped: a floor, not a date. The oldest such
                # release wins, since it is the stronger bound: a name in
                # the 2.7 inventory is no newer than 2.7 whatever the 3.x
                # builds did with it later.
                if verdict.floor is None or version_key(first) < version_key(
                    verdict.floor
                ):
                    verdict.floor = first
            else:
                verdict.inventory = first
                verdict.present_in = first
                verdict.absent_in = line[line.index(first) - 1]
                verdict.line = label
                break
        verdict.roles = set().union(*presence.values())

    marker = _annotation_index().get(name)
    if marker is not None:
        verdict.annotation = marker["added"]
        verdict.annotation_build = marker["build"]
        verdict.quote = marker["quote"]
        verdict.annotation_file = marker["file"]

    return verdict


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    for name in argv:
        verdict = date_symbol(name)
        print(f"{name}")
        print(f"  status      {verdict.status}")
        print(
            f"  added       {verdict.added or '?'}{' or earlier' if verdict.or_earlier else ''}"
        )
        if verdict.source:
            where = (
                f"already registered in {verdict.source}"
                if verdict.source_is_floor
                else f"absent in {verdict.source_absent_in}, present in {verdict.source}"
            )
            print(f"  source      {where} ({verdict.source_path})")
        if verdict.inventory:
            print(
                f"  objects.inv absent in {verdict.absent_in}, present in {verdict.present_in}"
            )
        elif verdict.floor:
            print(f"  objects.inv already documented in {verdict.floor}")
        if verdict.annotation:
            print(
                f"  annotation  {verdict.annotation} "
                f"({verdict.annotation_build} docs, {verdict.annotation_file}): {verdict.quote}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
