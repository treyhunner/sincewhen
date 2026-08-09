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
means anything. It speaks for builtins, modules, module members and the
methods of the builtin types, and only for names it actually finds and
can account for, so everything else falls through to the doc-derived
methods exactly as before.

For a method of a builtin type it is the only witness at all. The docs
index 397 of those and date 58, because a method older than the "Added
in version" convention never got a marker, so `dict.setdefault` and
`str.split` are answered by the type's own method table and by nothing
else. Note that the head of such a name is deliberately not consulted:
see `_date_the_module`. The exception is the types no release in that
corpus implements under a name anyone would call them by, where the head
is the only floor there is: see `_date_the_type`.

Usage:

    uv run scripts/dating.py math.isclose tomllib itertools.batched
"""

import keyword
import sys
from dataclasses import dataclass, field
from functools import cache

from annotations import ANNOTATION_BUILDS
from annotations import collect as collect_annotations
from interpreters import dated as interpreter_dated
from interpreters import micro_explains
from interpreters import removed as interpreter_removed
from modindex import HTML_BUILDS, dated_builtins, dated_members, dated_modules
from source import SOURCE_ORDER
from source import dated_builtins as source_builtins
from source import dated_members as source_members
from source import dated_modules as source_modules
from sources import load_inventories
from typemethods import dated_type_methods, type_is_covered

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

# The oldest release whose source survives, and so the floor of every
# method here. A name already in it cannot be dated, only bounded.
OLDEST_SOURCE = SOURCE_ORDER[0]

# Python 0.9.1 is also the first release the public ever had, and that
# makes its floor different in kind from every other one. "1.5 or
# earlier" leaves a real question open, because 1.0 through 1.4 exist and
# one of them is the answer. "0.9 or earlier" leaves nothing open: there
# is no earlier Python to reach for, and nothing has been in the language
# longer than the language has been public. So a floor here is reported
# as a date, and the evidence note goes on recording that the name is at
# least that old and may predate the public record.
FIRST_PUBLIC_RELEASE = OLDEST_SOURCE


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


# The three keywords that are also objects. Every other keyword is a
# piece of syntax whose only presence in the inventories is the
# reference manual's anchor for it, which is what `is_keyword` refuses.
# These three are documented values living in the builtins namespace:
# each carries a `py:data` role and no `std:label` at all, and
# `getattr(builtins, "True")` finds one. So asking the docs about them
# answers about the constant rather than about a section heading, which
# is the whole of the reason the refusal exists.
#
# `True` and `False` carry their own "New in version 2.3" marker in the
# 2.7 docs. `None` predates the marker convention and carries none, so
# nothing here dates it and `date_symbol` reports no version rather than
# a wrong one.
#
# Deliberately not extended to the operators. `in` and `is` are also
# real things with real ages, and the 0.9.1 grammar is what says so.
CONSTANT_KEYWORDS = frozenset({"True", "False", "None"})


def is_keyword(name: str) -> bool:
    """Whether asking about `name` here would answer about a doc anchor.

    Almost every Python keyword is also a `std:label` in the
    inventories, since the reference manual has a section for each one,
    and a label is indexed whenever someone got around to writing the
    anchor. So `in` reports as 3.2 and `if`, `for` and `while` all report
    as some 3.x release, none of which is a fact about the language: `in`
    is in the 0.9.1 `comp_op` rule.

    This method dates symbols, and such a keyword is not one. What
    settles it is CPython's own grammar, which `grammar.py` reads, so the
    answer here is to refuse rather than to guess.

    Only the hard keywords. A soft keyword is a real name as well:
    `type` is a builtin this dataset dates to 0.9, and `match` and
    `case` are ordinary identifiers everywhere but a match statement.

    And not the three that are objects: see `CONSTANT_KEYWORDS`. The
    refusal is about what the sources have under a name, not about what
    the tokenizer does with it, and what they have under `True` is the
    constant.
    """
    return keyword.iskeyword(name) and name not in CONSTANT_KEYWORDS


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
    keyword: bool = False
    interpreter: str | None = None
    interpreter_absent_in: str | None = None
    interpreter_is_floor: bool = False
    interpreter_note: str | None = None
    source: str | None = None
    source_absent_in: str | None = None
    source_is_floor: bool = False
    source_path: str | None = None
    source_note: str | None = None
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
    type_name: str | None = None
    type_added: str | None = None
    type_absent_in: str | None = None
    type_is_floor: bool = False
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
    def micro_explains_the_interpreter(self) -> bool:
        """Whether the docs' own marker accounts for the interpreter's absence.

        The corpus builds each release's `.0`, so a marker that names a
        micro release is a marker the interpreter is *expected* to
        disagree with: `typing.Type` says "Added in version 3.5.2", the
        3.5.0 build does not have it, and 3.6 is the first release in the
        corpus that does. Nothing is wrong there and nobody needs to
        write a note about it.

        The rule itself lives in `interpreters.py`, because `--check`
        applies it too and two copies of it can reach opposite
        conclusions about the same entry.
        """
        if self.interpreter is None or self.annotation is None:
            return False
        return micro_explains(self.name, self.annotation, self.interpreter)

    @property
    def documented(self) -> str | None:
        """The oldest release any doc-derived method puts this name in.

        The two of them are one claim for the purpose of ranking a built
        interpreter against them, because they fail in the same
        direction: a marker and an inventory entry both describe what was
        written down, and both can be written down late. Which of them is
        binding is whichever says the name is older, since being listed
        proves presence and not being listed proves very little.
        """
        dates = [date for date in (self.annotation, self.inventory) if date is not None]
        return min(dates, key=version_key) if dates else None

    @property
    def documented_by(self) -> str | None:
        """Which doc-derived method the `documented` date came from."""
        if self.documented is None:
            return None
        return "annotation" if self.documented == self.annotation else "inventory"

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
    def bounded_by_its_type(self) -> bool:
        """Whether the type this hangs off closes the inventory's bound.

        The same argument as `bounded_by_its_module`, one level down. A
        method cannot predate the type that holds it, so a bound at
        exactly the release the type arrived in is not a bound at all.
        The inventory can only ever bound a type member, because
        `stdtypes` grew per-name markup release by release, and
        `memoryview.tolist` is first indexed in 2.7, which is the release
        `memoryview` itself arrived in. There is nothing under that for
        the method to have come from, so it is 2.7 rather than "2.7 or
        earlier".

        Only reached for the types `typemethods` does not speak for: see
        `_date_the_type`. It also needs a release that demonstrably lacks
        the type, since that is what the evidence points at, and that
        release has to be older than the type's own arrival. `bytearray`
        is why the comparison is strict rather than loose: the 2.7
        inventory is the first to list it and the 2.7 docs date it to
        2.6, so its verdict brackets on 2.6 from both sides and there is
        no older release to cite.

        What this does not do is cross-check the bound against anything.
        It reads "indexed in release R" as "existed in R", which
        `BUILTIN_TYPES` says is false in general: `frozenset.add` is
        indexed in 2.7 and no `frozenset` has ever had it. That is safe
        only because the bound has to land on the type's own arrival,
        which is a release the type demonstrably shipped in.
        """
        return (
            self.inventory is None
            and self.floor is not None
            and self.type_added is not None
            and not self.type_is_floor
            and self.type_added == self.floor
            and self.type_absent_in is not None
            and version_key(self.type_absent_in) < version_key(self.type_added)
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
    def _open_bound(self) -> bool:
        """Whether the winning method's floor is left open by anything else.

        Only true when the answer *is* the floor of whichever method
        produced it, and nothing else closes it. A name that one method
        can merely bound but another dates outright gets a real date, not
        a bounded one, which is why `map` stopped being "1.2 or earlier"
        once the source could be read: the archives were reporting their
        own age, not its.

        This is what the evidence note describes, and it stays true at
        the first public release even though `or_earlier` does not.
        """
        return self._is_floor and not self.bounded_by_its_module

    @property
    def or_earlier(self) -> bool:
        """Whether the answer is a bound rather than a date.

        An open bound at the first public release is not one, because
        there is nothing under it: see `FIRST_PUBLIC_RELEASE`. `max` is
        in the builtins table of Python 0.9.1 and the answer is 0.9,
        stated as a date, while `zlib` stays "1.5 or earlier" because 1.0
        through 1.4 are all still on the table.
        """
        return self._open_bound and self.added != FIRST_PUBLIC_RELEASE

    @property
    def added(self) -> str | None:
        """The version to believe, or `None` if the methods disagree."""
        inventory, annotation = self.inventory, self.annotation
        match self.status:
            case (
                "keyword"
                | "conflict"
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
            case "docs-date-the-floor":
                # The archives can only show the name was already there;
                # the marker says which release put it there, and they
                # name the same release.
                return annotation
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
            case "type":
                # The inventory bounds a type member and the type's own
                # arrival closes the bound: see `bounded_by_its_type`.
                return self.type_added
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

        A keyword is refused outright rather than reconciled, because
        every method here would be answering about something else: see
        `is_keyword`.
        """
        if self.keyword:
            return "keyword"

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
        #
        # This guards those two and no longer guards the interpreter,
        # which now sees the whole timeline and detects a re-add itself:
        # `types.NoneType` resolves in 1.1, not again until 3.10, and a
        # mask like that is reported as a gap rather than as a date.
        # Guarding the interpreter with it hid real corrections, because
        # it fires whenever the two doc-derived methods agree, which is
        # most of the 3.x line. It is what kept `dis.show_code` reading
        # as 3.2 when 3.0's own `dis.py` defines it and the 3.0
        # interpreter resolves it.
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
        if self.interpreter and not self.micro_explains_the_interpreter:
            # A marker naming a micro release explains the disagreement
            # outright, so the interpreter has nothing to add and the
            # docs answer. Skipped here rather than resolved below,
            # because "the interpreter is right about 3.5.0 and the docs
            # are right about 3.5" leaves the docs holding the answer.
            if not self.interpreter_is_floor:
                if (
                    self.source
                    and not self.source_is_floor
                    and self.source != self.interpreter
                ):
                    return "interpreter-contradicts-source"
                documented = self.documented
                if documented and documented != self.interpreter:
                    if version_key(self.interpreter) > version_key(documented):
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
                        #
                        # The inventory is read the same way and for the
                        # same reason, even though it is the method this
                        # one exists to cross-check. Being indexed late is
                        # what the inventory gets wrong, and it errs by
                        # naming a release too new; a build that answers
                        # "too new" as well is agreeing about nothing.
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
            if self.annotation and self.archive_is_floor:
                # The two agree on the version and disagree on what kind
                # of claim it is, and the marker makes the sharper one.
                # "Documented in 2.3 and possibly earlier" is a limit on
                # how far back the doc builds reach; "New in version 2.3"
                # is a date, and a date at the floor leaves nothing under
                # it. This is the rule the source branch above already
                # applies: without it every member the docs date to 2.5
                # would read as "2.5 or earlier" purely because 2.5 is
                # the newest archive there is.
                return "docs-date-the-floor"
            return "archive"

        # A type member the inventory can only bound, whose type arrived
        # in exactly the release that bound it. Checked before the
        # annotation, because the marker nearest one of these is often
        # not a claim about it: the one above `memoryview.tobytes` says
        # "Added in version 3.8: *order* can be {'C', 'F', 'A'}", which
        # dates an argument to a method the 2.7 inventory already lists.
        if self.bounded_by_its_type:
            return "type"

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

    def _overridden_docs_note_for_interpreter(self) -> str:
        """What to say when a built interpreter outranks a doc-derived date.

        Which doc source is being outranked changes what the note is
        claiming, so it changes what the note says. A marker is the docs
        making a dated statement and being wrong about it. An inventory
        entry is not a statement about dates at all: it is the release
        whose documentation first indexed the name, and the gap between
        that and the release that shipped it is precisely what this
        method exists to measure. `hashlib.sha3_256` shipped in 3.6 and
        was first indexed in 3.11.
        """
        if self.documented_by == "annotation":
            return (
                f"The {self.annotation_build} docs date it to "
                f"{self.annotation}, but the {self.interpreter_absent_in} "
                f"interpreter does not resolve it and {self.interpreter} does."
            )
        return (
            f"First indexed by the {self.inventory} inventory, which dates "
            f"the documentation rather than the release: the "
            f"{self.interpreter_absent_in} interpreter does not resolve it "
            f"and {self.interpreter} does."
        )

    def _overridden_docs_note(self) -> str:
        """What to say when the source outranks a version marker.

        A method of a builtin type gets its own wording, because the
        marker nearest one of those is often not about it. `stdtypes`
        describes a whole family per page, so the nearest marker to
        `dict.values` is the 3.9 one under `d | other`, which the
        extractor cannot see as a signature, and the nearest one to
        `str.translate` says "New in version 2.6: Support for a `None`
        *table* argument", which dates an argument. Neither is a claim
        about when the method arrived, so neither is reported as one.
        """
        if is_type_member(self.name):
            return (
                f"The {self.annotation_build} docs' nearest marker to this "
                f"name says {self.annotation}, which the method table "
                f"contradicts: {self.source_absent_in} does not carry the row "
                f"and {self.source} does."
            )
        return (
            f"The {self.annotation_build} docs date it to {self.annotation}, "
            f"but the {self.source_absent_in} interpreter does not register it."
        )

    def evidence(self, checked: str) -> dict:
        """The provenance table this verdict justifies, ready for TOML."""
        if self.status in {"interpreter", "interpreter-overrides-docs"}:
            evidence = {
                "method": "interpreter",
                "symbol": self.name,
                "absent_in": self.interpreter_absent_in,
                "present_in": self.interpreter,
            } | self._closed_by_module()
            if self._open_bound:
                evidence["note"] = (
                    f"Resolves in {self.interpreter}, and no earlier release "
                    "can be shown to lack it. " + (self.interpreter_note or "")
                ).strip()
            elif self.interpreter_note:
                evidence["note"] = self.interpreter_note
            elif self.status == "interpreter-overrides-docs":
                evidence["note"] = self._overridden_docs_note_for_interpreter()
            return evidence | {"checked": checked}
        if self.status in {"source", "source-overrides-docs"}:
            evidence = {
                "method": "source",
                "symbol": self.name,
                "file": self.source_path,
                "absent_in": self.source_absent_in,
                "present_in": self.source,
            } | self._closed_by_module()
            notes = []
            if self._open_bound and self.source == OLDEST_SOURCE:
                notes.append(
                    f"Registered in {self.source}, the oldest source release "
                    "there is, so it is at least that old and may be older."
                )
            elif self._open_bound:
                # A floor above the oldest release means the older
                # source neither binds the name nor rules it out: a
                # method table row inside an `#if`, or a module whose
                # own file is not the whole of its namespace.
                notes.append(
                    f"Bound in {self.source}, so it is at least that old. "
                    "No earlier source release can be shown to lack it."
                )
            elif self.status == "source-overrides-docs":
                notes.append(self._overridden_docs_note())
            if self.source_note:
                notes.append(self.source_note)
            if notes:
                evidence["note"] = " ".join(notes)
            return evidence | {"checked": checked}
        if self.status in {"archive", "docs-overstate"}:
            evidence = {
                "method": "archive",
                "absent_in": self.archive_absent_in,
                "present_in": self.archive,
            } | self._closed_by_module()
            if self._open_bound:
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
        if self.status == "type":
            return {
                "method": "objects.inv",
                "symbol": f"{sorted(self.roles)[0]} {self.name}"
                if self.roles
                else self.name,
                "absent_in": self.type_absent_in,
                "present_in": self.type_added,
                "note": (
                    f"The inventory only bounds a member of a builtin type, and "
                    f"{self.floor} is the oldest one that indexes this. "
                    f"{self.type_name} is absent from {self.type_absent_in} and "
                    f"arrived in {self.type_added}, so nothing in it can be "
                    "older and the bound closes."
                ),
                "checked": checked,
            }
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

    A method of a builtin type is read from that type's own method
    table, which is the same argument one level down and the only thing
    that reaches these names at all: the docs date 58 of the 397 they
    index, because a method older than the "Added in version" convention
    never got a marker.
    """
    if is_type_member(verdict.name):
        record = dated_type_methods().get(verdict.name)
    elif verdict.module is not None:
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
    verdict.source_note = record.get("note")


def _date_the_module(verdict: Verdict) -> None:
    """Date the module a dotted name belongs to, if it is one.

    A member is answered partly by its module, in both directions: the
    module is a floor under it, and where the module is dated the module
    is a ceiling too. Both need the module's own verdict, so it is taken
    once here rather than recomputed by each rule that wants it.

    A method of a builtin type gets neither, because the head of the name
    is not a module and answers a different question. `dict` the builtin
    arrived in 2.2 and the `dict` type is in 0.9.1, so treating the head
    as a floor would date `dict.keys` to 2.2, and treating it as a
    ceiling would throw the 0.9.1 evidence away. What a method table
    dates is availability on instances, which is what the dataset's
    pre-2.6 method entries have always claimed: `"x".encode()` is 2.0
    and `str.encode` as an unbound attribute is 2.2.

    The narrow exception is `_date_the_type`, for the types whose method
    tables no release in the corpus carries, where the head is the only
    floor there is and none of the above applies.
    """
    module, _, member = verdict.name.rpartition(".")
    if not (module and member) or is_type_member(verdict.name):
        return
    found = date_symbol(module)
    verdict.module = module
    verdict.module_added = found.added
    verdict.module_absent_in = found.absent_from
    verdict.module_is_floor = found.or_earlier


# The one head this refuses to read. `range` names a builtin function
# that returns a list until 3.0, and the source dates that function to
# 0.9, so asking about the head answers about `range()` and not about the
# `range` type, which is 3.0. That is exactly the `dict` gap below, and
# the only one of these four types that falls into it: `bytes`,
# `bytearray` and `memoryview` name the same thing throughout.
HEAD_IS_NOT_THE_TYPE = frozenset({"range"})


def _date_the_type(verdict: Verdict) -> None:
    """Date the builtin type a method hangs off, where anything can.

    A method cannot predate the type that holds it, which is the
    argument `_date_the_module` makes about a module member one level
    up. Unlike that one it is deliberately narrow: it is only taken for
    the types `typemethods.py` does not speak for, because for every
    other builtin type the head of the name answers a different
    question. `dict` the builtin arrived in 2.2 and the `dict` type is
    in 0.9.1, so a floor from the head would date `dict.keys` to 2.2.

    For `bytes`, `bytearray` and `memoryview` the head is the only floor
    there is, because no release in the source corpus implements a type
    anyone would call by those names and nothing else in the corpus
    reaches these methods. `range` is excluded outright: see
    `HEAD_IS_NOT_THE_TYPE`.

    A head the sources cannot date leaves the fields unset and the
    member unanswered, which is what `bytes` does: the 3.x inventories
    have it from 3.0, so they can only bound it, and no older source
    names it at all.
    """
    if not is_type_member(verdict.name) or type_is_covered(verdict.name):
        return
    head = verdict.name.partition(".")[0]
    if head in HEAD_IS_NOT_THE_TYPE:
        return
    found = date_symbol(head)
    verdict.type_name = head
    verdict.type_added = found.added
    verdict.type_absent_in = found.absent_from
    verdict.type_is_floor = found.or_earlier


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
    """What the cached docs say about when `name` arrived.

    A keyword is refused before anything is consulted, because the
    sources all have something of that name and none of them is the
    keyword. `grammar.py` is what answers those.
    """
    if is_keyword(name):
        return Verdict(name=name, keyword=True)

    verdict = Verdict(name=name)
    _date_the_module(verdict)
    _date_the_type(verdict)

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


def removal_of(name: str) -> dict | None:
    """When a name stopped being available, or `None` if it has not.

    One method answers this and it is deliberate rather than a gap. The
    doc-derived methods can see the releases in question and still may
    not speak, because a removal is an absence claim and their absences
    prove nothing: an inventory drops names when the markup changes and
    a doc build that stops mentioning something has not removed it.
    `source.py`, the archives and the type method tables all stop at 2.5
    and every removal here is 3.0 or later, so they cannot see one at
    all. That leaves the built interpreters, whose absences are the thing
    itself. Syntax is the other half and `grammar.py` answers it.

    The kind is chosen the way `_date_from_interpreters` chooses it, with
    one addition: a method of a builtin type is asked for by its unbound
    spelling, which answers this question correctly and the addition
    question wrongly. See `KINDS` in interpreters.py.
    """
    if is_keyword(name):
        return None
    if is_type_member(name):
        kinds = ("method",)
    elif "." in name:
        kinds = ("attribute", "module")
    elif name in source_modules() or name in dated_modules():
        kinds = ("module",)
    else:
        kinds = ("builtin", "module")
    for kind in kinds:
        found = interpreter_removed(f"{kind} {name}")
        if found is not None:
            return found | {"symbol": name, "kind": kind}
    return None


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    for name in argv:
        verdict = date_symbol(name)
        print(f"{name}")
        print(f"  status      {verdict.status}")
        if verdict.keyword:
            print(
                f"  {name!r} is a keyword, and the only thing here with that "
                "name is a documentation anchor. Ask the grammar instead:\n"
                f"    uv run scripts/grammar.py --token \"'{name}'\"\n"
            )
            continue
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
        if verdict.type_added:
            bound = (
                f"{verdict.type_added} or earlier"
                if verdict.type_is_floor
                else verdict.type_added
            )
            print(
                f"  type        {verdict.type_name} is {bound}, so nothing in it is older"
            )
        if verdict.annotation:
            print(
                f"  annotation  {verdict.annotation} "
                f"({verdict.annotation_build} docs, {verdict.annotation_file}): {verdict.quote}"
            )
        if (gone := removal_of(name)) is not None:
            print(
                f"  removed     {gone['removed']} "
                f"(last resolves in {gone['present_in']})"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
