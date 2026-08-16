"""Tests for reading the docs' own "Added in version" markers.

A marker belongs to the signature above it, and which signature that is
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


def test_a_marker_dates_every_signature_of_a_group(markers):
    """One directive, several signatures, one description.

    The text build renders these as adjacent signature lines with
    nothing between them. Keeping only the last one dated
    `assertNotEndsWith` from the docs and left `assertEndsWith` to be
    dated by whichever release first indexed it, which is the failure
    this whole extractor exists to avoid.
    """
    found = markers(
        HEADING + "example.spam(x)\n\nexample.eggs(x)\n\n"
        "   Do a thing, or not.\n\n   Added in version 3.14.\n"
    )
    assert found == {"example.spam": "3.14", "example.eggs": "3.14"}


def test_a_described_sibling_is_not_part_of_the_next_group(markers):
    """Prose between two signatures is what separates them.

    Without this, every signature on a page would join the group before
    it and the whole page would take the first marker it reached.
    """
    found = markers(
        HEADING + "example.spam(x)\n\n   Do a thing.\n\nexample.eggs(x)\n\n"
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
        HEADING + "example.Never\n\nexample.NoReturn\n\n   The bottom type.\n\n"
        '   Added in version 3.6: Added "NoReturn".\n\n'
        '   Added in version 3.11: Added "Never".\n'
    )
    assert found == {"example.NoReturn": "3.6", "example.Never": "3.11"}


def test_a_grouped_marker_naming_nothing_dates_the_whole_group(markers):
    found = markers(
        HEADING + "example.MAP_ONE\n\nexample.MAP_TWO\n\n   Flags.\n\n"
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
        "   spam(x)\n\n   eggs(x)\n\n"
        "      Do a thing, or not.\n\n      Added in version 3.14.\n"
    )
    assert found["example.Thing.spam"] == "3.14"
    assert found["example.Thing.eggs"] == "3.14"
