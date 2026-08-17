"""Tests for reading the docs' own "Added in version" markers.

A marker belongs to the directive above it, and which directive that is
turns out to be the whole difficulty. Getting it wrong is quiet: the
marker lands on a neighbour, so one name is dated wrongly and another
falls back to whichever release happened to index it. Both look like
evidence.

So the shapes are pinned here, one test per shape, written against the
markup rather than against the 27 MB of cached text builds.
"""

import pytest
from annotations import annotations_in

HEADING = '9.1. "example" — An example module\n\n'


@pytest.fixture
def markers(tmp_path):
    """`{name: version}` for one page's worth of text-build markup."""

    def read(text):
        root = tmp_path / "docs"
        page = root / "library" / "example.txt"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(text, encoding="utf-8")
        return {
            record["name"]: record["added"] for record in annotations_in(page, root)
        }

    return read


def test_a_marker_dates_the_signature_above_it(markers):
    found = markers(
        HEADING + "example.spam(x)\n\n   Do a thing.\n\n   Added in version 3.9.\n"
    )
    assert found == {"example.spam": "3.9"}


def test_a_marker_dates_every_signature_of_one_directive(markers):
    """One directive's continuation signatures share its marker.

    reST writes them under a single `.. data::`, and the text build
    renders continuation lines with no blank between them. Keeping only
    the last one read `stat.FILE_ATTRIBUTE_ARCHIVE` and sixteen siblings
    as undated where the docs say 3.5 for all eighteen, and did the same
    to eight `os.spawn*` signatures under one "New in version 1.6".
    """
    found = markers(
        HEADING
        + "example.SPAM\nexample.EGGS\n\n   Flags.\n\n   Added in version 3.14.\n"
    )
    assert found == {"example.SPAM": "3.14", "example.EGGS": "3.14"}


def test_a_blank_line_makes_the_next_signature_its_own_directive(markers):
    """A blank between signatures is two `..` directives, not one.

    CPython writes both shapes and means different things by them.
    `ipaddress.IPv6Address` is seven `.. attribute::` directives, six of
    them empty, and the marker under the seventh belongs to `is_global`
    alone. Reading that run as one directive stole the marker for all
    seven and lost six names to the contradiction it created.
    """
    found = markers(
        HEADING + "example.spam(x)\n\nexample.eggs(x)\n\n"
        "   Do a thing, or not.\n\n   Added in version 3.14.\n"
    )
    assert found == {"example.eggs": "3.14"}


def test_prose_between_two_signatures_separates_them(markers):
    found = markers(
        HEADING + "example.spam(x)\n   Do a thing.\nexample.eggs(x)\n"
        "   Do another.\n\n   Added in version 3.14.\n"
    )
    assert found == {"example.eggs": "3.14"}


def test_a_grouped_marker_that_names_its_own_half_dates_only_that(markers):
    """`typing.Never` and `typing.NoReturn` share one directive.

    Each of their two markers says which of the pair it is about, and
    reading the group as a whole gave `Never` the 3.6.2 that belongs to
    `NoReturn` alone.
    """
    found = markers(
        HEADING + "example.Never\nexample.NoReturn\n\n   The bottom type.\n\n"
        '   Added in version 3.6: Added "NoReturn".\n\n'
        '   Added in version 3.11: Added "Never".\n'
    )
    assert found == {"example.NoReturn": "3.6", "example.Never": "3.11"}


def test_a_grouped_marker_may_name_its_half_without_quoting_it(markers):
    """`sys.__breakpointhook__` and three siblings share a directive.

    Their two markers spell the subject bare, so `MENTION` alone cannot
    see it and all four inherited both versions. A bare word is read
    only where it could not be prose.
    """
    found = markers(
        HEADING + "example.__one__\nexample.__two__\n\n   The originals.\n\n"
        "   Added in version 3.7: __one__\n\n"
        "   Added in version 3.8: __two__\n"
    )
    assert found == {"example.__one__": "3.7", "example.__two__": "3.8"}


def test_a_grouped_marker_naming_nothing_in_the_group_dates_none_of_it(markers):
    """`assertRegex` and `assertNotRegex` are 3.2, not 3.1.

    Their shared description carries `Added in version 3.1: Added under
    the name "assertRegexpMatches".`, which is a true statement about a
    third spelling and no statement at all about either of these.
    """
    found = markers(
        HEADING + "example.spam(x)\nexample.eggs(x)\n\n   Do a thing.\n\n"
        '   Added in version 3.1: Added under the name "oldSpelling".\n'
    )
    assert found == {}


def test_a_grouped_marker_naming_nothing_dates_the_whole_group(markers):
    found = markers(
        HEADING + "example.MAP_ONE\nexample.MAP_TWO\n\n   Flags.\n\n"
        "   Added in version 3.13.\n"
    )
    assert found == {"example.MAP_ONE": "3.13", "example.MAP_TWO": "3.13"}


def test_a_lone_signature_is_dated_by_its_marker_whatever_it_names(markers):
    """The singling-out rule is for groups and only for groups.

    Every existing entry rests on a marker under one signature dating
    that signature, however its prose reads, so narrowing that would
    change answers nothing here asked about.
    """
    found = markers(
        HEADING + "example.spam(x)\n\n   Do a thing.\n\n"
        '   Added in version 3.9: the "eggs" argument.\n'
    )
    assert found == {"example.spam": "3.9"}


def test_a_method_is_qualified_by_the_class_above_it(markers):
    found = markers(
        HEADING + "class example.Thing\n\n   A thing.\n\n"
        "   spam(x)\n\n      Do a thing.\n\n      Added in version 3.12.\n"
    )
    assert found["example.Thing.spam"] == "3.12"


def test_a_group_of_methods_is_qualified_the_same_way(markers):
    found = markers(
        HEADING + "class example.Thing\n\n   A thing.\n\n"
        "   spam(x)\n   eggs(x)\n\n"
        "      Do a thing, or not.\n\n      Added in version 3.14.\n"
    )
    assert found["example.Thing.spam"] == "3.14"
    assert found["example.Thing.eggs"] == "3.14"
