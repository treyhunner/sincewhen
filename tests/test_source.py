"""Tests for reading a class's own body out of a release's library.

This is the one method whose *absences* count, so a reader that misses a
binding does not produce a gap, it produces a wrong version number: a
member it fails to see in 2.2 and sees in 2.3 reads as "added in 2.3".
That makes the shapes worth pinning one at a time.

Written against the text rather than against the 2 GB corpus, the way
`test_modindex.py` and `test_annotations.py` are. `ast` is not an option
for the real thing either: a 3.14 parser cannot read a 1.5 tarball,
where `print` is a statement and exceptions are caught `except E, e:`.
"""

import pytest
from source import CLASS_HEADER, NO_INHERITANCE, _body_of, _class_bound


def members(body):
    """What a class body binds, given the body's text."""
    return set(_class_bound(body))


def bodies(text):
    """`{class: (bases, members)}` for a whole file's worth of text."""
    return {
        header["name"]: (
            (header["bases"] or "").strip(),
            set(_class_bound(_body_of(text, header))),
        )
        for header in CLASS_HEADER.finditer(text)
    }


def test_a_method_is_a_member():
    assert members("\n    def spam(self):\n        pass\n") == {"spam"}


def test_a_chained_assignment_binds_every_target():
    """How two of the three spellings actually exist.

    2.3's `unittest.py` writes `assertAlmostEqual = assertAlmostEquals =
    failUnlessAlmostEqual`, so reading only `def` lines finds the name
    nobody writes and misses both of the ones they do.
    """
    body = "\n    def failUnlessAlmostEqual(self, a, b):\n        pass\n" + (
        "    assertAlmostEqual = assertAlmostEquals = failUnlessAlmostEqual\n"
    )
    assert members(body) == {
        "failUnlessAlmostEqual",
        "assertAlmostEqual",
        "assertAlmostEquals",
    }


def test_a_method_body_is_not_a_list_of_members():
    """Only the class's own indent, or every local would be a method."""
    body = "\n    def spam(self):\n        helper = 1\n        def inner():\n            pass\n"
    assert members(body) == {"spam"}


def test_a_conditional_definition_is_not_bound_outright():
    """A `def` inside an `if` is not one the release provably has.

    Absence is what this method's dates rest on, and the credulous
    `mentions` check is what covers the name anyway, so the strict
    reading here costs nothing and keeps a platform-guarded method from
    reading as unconditionally present.
    """
    body = "\n    if sys.platform == 'win32':\n        def spam(self):\n            pass\n    def eggs(self):\n        pass\n"
    assert members(body) == {"eggs"}


def test_a_docstring_sets_the_indent_without_being_a_member():
    body = '\n    """A thing."""\n\n    def spam(self):\n        pass\n'
    assert members(body) == {"spam"}


def test_a_comparison_is_not_a_binding():
    assert members("\n    spam = 1\n    if eggs == 2:\n        pass\n") == {"spam"}


def test_an_augmented_assignment_is_not_a_binding():
    assert members("\n    spam = 1\n    spam += 1\n") == {"spam"}


def test_a_nested_class_is_a_member():
    assert members("\n    class Inner:\n        pass\n") == {"Inner"}


def test_a_body_ends_at_the_next_top_level_line():
    text = "class Spam:\n    def one(self):\n        pass\n\n\nclass Eggs:\n    def two(self):\n        pass\n"
    assert bodies(text) == {"Spam": ("", {"one"}), "Eggs": ("", {"two"})}


def test_an_empty_class_binds_nothing():
    assert bodies("class Spam:\n    pass\n\n\nx = 1\n") == {"Spam": ("", set())}


@pytest.mark.parametrize(
    "header, bases",
    [
        ("class Spam:", ""),
        ("class Spam():", ""),
        ("class Spam(object):", "object"),
        ("class Spam(Base):", "Base"),
        ("class Spam(One, Two):", "One, Two"),
    ],
)
def test_the_bases_are_read_off_the_header(header, bases):
    assert bodies(f"{header}\n    pass\n")["Spam"][0] == bases


@pytest.mark.parametrize(
    "bases, closed",
    [("", True), ("object", True), ("Base", False), ("One, Two", False)],
)
def test_only_a_class_that_inherits_nothing_is_closed(bases, closed):
    """`open_modules` one level down, and the same argument decides it.

    A class that inherits gets members its body does not list, so an
    absence there says nothing. `unittest.TestCase` inherits nothing in
    every release from 2.1 to 2.5, which is what lets 2.2 prove it
    lacked `assertAlmostEqual`.
    """
    inherits_nothing = all(base.strip() in NO_INHERITANCE for base in bases.split(","))
    assert inherits_nothing is closed
