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
import source
from source import (
    CLASS_HEADER,
    _body_of,
    _class_bound,
    _inherits_nothing,
    code_only,
)


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
    [
        ("", True),
        ("object", True),
        (" object ", True),
        ("Base", False),
        ("One, Two", False),
        ("Base, object", False),
        ("object, Base", False),
    ],
)
def test_only_a_class_that_inherits_nothing_is_closed(bases, closed):
    """`open_modules` one level down, and the same argument decides it.

    A class that inherits gets members its body does not list, so an
    absence there says nothing. `unittest.TestCase` inherits nothing in
    every release from 2.1 to 2.5, which is what lets 2.2 prove it
    lacked `assertAlmostEqual`.

    The production predicate is called rather than restated. Restating
    it made this pass for any implementation, `any` as readily as
    `all`, and `any` would read `class Foo(Base, object):` as closed
    and take an absence in a subclass's body for proof.
    """
    assert _inherits_nothing(bases) is closed


def test_closed_classes_is_the_ones_that_inherit_nothing(monkeypatch):
    """And that `closed_classes` is wired to that predicate at all."""
    catalogue = {
        "m.Plain": ("", frozenset()),
        "m.Object": ("object", frozenset()),
        "m.Derived": ("Base", frozenset()),
        "m.Multiple": ("Base, object", frozenset()),
    }
    monkeypatch.setattr(source, "_python_classes", lambda version: catalogue)
    source.closed_classes.cache_clear()
    try:
        assert source.closed_classes("2.5") == {"m.Plain", "m.Object"}
    finally:
        source.closed_classes.cache_clear()


def unchanged_shape(text):
    """Whether blanking left every offset and every line where it was."""
    blanked = code_only(text)
    return len(blanked) == len(text) and [
        len(line) for line in blanked.splitlines()
    ] == [len(line) for line in text.splitlines()]


def test_a_comment_is_blanked_without_moving_anything():
    text = "x = 1  # note\ny = 2\n"
    assert unchanged_shape(text)
    assert code_only(text).splitlines() == ["x = 1        ", "y = 2"]


def test_a_string_is_blanked_and_keeps_its_line_count():
    text = 'a = 1\n"""\nclass Fake:\n    def nope(self):\n"""\nb = 2\n'
    blanked = code_only(text)
    assert unchanged_shape(text)
    assert "class Fake" not in blanked
    assert blanked.splitlines()[0] == "a = 1"
    assert blanked.splitlines()[-1] == "b = 2"
    assert not any(line.strip() for line in blanked.splitlines()[1:5])


def test_a_hash_inside_a_string_does_not_start_a_comment():
    assert code_only('x = "a # b"\ny = 2\n').splitlines() == ["x =        ", "y = 2"]


def test_a_quote_inside_a_comment_does_not_start_a_string():
    """`# don't` would otherwise swallow the rest of the file."""
    assert code_only("# don't\nx = 1\n").splitlines() == ["       ", "x = 1"]


def test_a_triple_quote_inside_a_comment_does_not_start_a_string():
    text = "# use ''' for docstrings\nclass Spam:\n    def one(self):\n        pass\n"
    assert bodies(code_only(text)) == {"Spam": ("", {"one"})}


def test_a_prefixed_string_is_still_a_string():
    assert code_only("x = r'a#b'\ny = 2\n").splitlines() == ["x =       ", "y = 2"]


def test_an_escaped_quote_does_not_end_a_string():
    assert code_only("x = 'a\\'b'\ny = 2\n").splitlines() == ["x =       ", "y = 2"]


def test_an_unterminated_single_quote_stops_at_the_line_end():
    """Otherwise one stray quote blanks everything after it."""
    assert (
        code_only("x = 'oops\nclass Spam:\n    pass\n").splitlines()[1] == "class Spam:"
    )


def test_a_docstring_example_is_not_a_class():
    """`SimpleXMLRPCServer`'s module docstring shows `class MyFuncs:`.

    "Prose is not a heading", one level down from the rule AGENTS.md
    already records for the doc archives.
    """
    text = '"""\nclass MyFuncs:\n    def div(self): pass\n"""\n\n\nclass Real:\n    def one(self):\n        pass\n'
    assert bodies(code_only(text)) == {"Real": ("", {"one"})}


def test_a_docstring_that_closes_in_column_zero_does_not_end_the_body():
    """`ftplib.FTP` lost all 38 of its methods to this."""
    text = "class Spam:\n    '''\n    Usage:\n'''\n    def one(self):\n        pass\n"
    assert bodies(code_only(text)) == {"Spam": ("", {"one"})}


def test_a_comment_in_column_zero_does_not_end_the_body():
    """`random.Random` lost five methods to `## ----` separators."""
    text = "class Spam:\n    def one(self):\n        pass\n## ---- section ----\n    def two(self):\n        pass\n"
    assert bodies(code_only(text)) == {"Spam": ("", {"one", "two"})}


def test_an_assignment_in_a_docstring_is_not_a_member():
    """`zipfile.ZipFile`'s docstring writes `z = ZipFile(...)`.

    Presence is believed with no guard at all, so an invented member is
    a date that is too old the first time one collides with a real name.
    """
    text = "class Spam:\n    '''Usage:\n\n    z = Spam()\n    '''\n    def one(self):\n        pass\n"
    assert bodies(code_only(text)) == {"Spam": ("", {"one"})}
