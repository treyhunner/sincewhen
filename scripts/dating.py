#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Answer "when was this added?" from the cached docs, two ways.

This is the oracle the dataset is checked against. It never guesses: it
reports what each method found, says whether they agree, and leaves a
disagreement standing so a human has to look at it.

The inventory diff gives a hard verdict for anything added in 3.1 or
later, because a symbol absent from one release's `objects.inv` and
present in the next was added in that release. For anything older it can
only give a *floor*: "already documented in 3.0", which rules out later
versions without picking one. The annotation grep fills that in, since
the Python 2.7 docs still carry markers going back to 1.3.

Usage:

    uv run scripts/dating.py math.isclose tomllib itertools.batched
"""

import sys
from dataclasses import dataclass, field
from functools import cache

from annotations import collect as collect_annotations
from modindex import HTML_BUILDS, dated_builtins, dated_members, dated_modules
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


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


# The newest release with an HTML module index. A module missing from
# it but present in the 2.6 inventory can only have arrived in 2.6.
NEWEST_HTML = list(HTML_BUILDS)[-1]

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
    source_file: str | None = None
    line: str | None = None
    roles: set[str] = field(default_factory=set)

    @property
    def or_earlier(self) -> bool:
        """Whether the answer is a bound rather than a date.

        Only true when the answer *is* the archive floor. A name that
        the archives can merely bound but the inventories date outright
        gets a real date, not a bounded one.
        """
        return self.archive_is_floor and self.added == self.archive

    @property
    def added(self) -> str | None:
        """The version to believe, or `None` if the methods disagree."""
        inventory, annotation = self.inventory, self.annotation
        match self.status:
            case "conflict":
                return None
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
        # A pre-Sphinx archive speaks for the 2.x line, and usually
        # beats the 3.x inventories, which are sparse for 3.0 and 3.1
        # and make old modules look new: `profile` is in the 1.5 docs
        # and first indexed in 3.1.
        #
        # It loses when the 3.x line dates the name itself *and the
        # current docs say the same*. Two sources agreeing means the
        # name really did go away and come back: `types.NoneType` is in
        # the 1.2 docs, gone for all of Python 3 until 3.10.
        readded = (
            self.inventory
            and self.line == "spine"
            and self.annotation == self.inventory
        )
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

    def evidence(self, checked: str) -> dict:
        """The provenance table this verdict justifies, ready for TOML."""
        if self.added == self.archive:
            evidence = {
                "method": "archive",
                "absent_in": self.archive_absent_in,
                "present_in": self.archive,
            }
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
            "docs": f"{self.annotation_build}:{self.source_file}",
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

    presence = _inventory_index().get(name, {})
    _date_from_archive(verdict, presence)
    if presence:
        for label, line in (("spine", SPINE), ("legacy", LEGACY)):
            available = [version for version in line if version in presence]
            if not available:
                continue
            first = available[0]
            if first == line[0]:
                # Already there when this line starts: a floor, not a date.
                if verdict.floor is None:
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
        verdict.source_file = marker["file"]

    return verdict


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 1
    for name in argv:
        verdict = date_symbol(name)
        print(f"{name}")
        print(f"  status      {verdict.status}")
        print(f"  added       {verdict.added or '?'}")
        if verdict.inventory:
            print(
                f"  objects.inv absent in {verdict.absent_in}, present in {verdict.present_in}"
            )
        elif verdict.floor:
            print(f"  objects.inv already documented in {verdict.floor}")
        if verdict.annotation:
            print(
                f"  annotation  {verdict.annotation} "
                f"({verdict.annotation_build} docs, {verdict.source_file}): {verdict.quote}"
            )
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
