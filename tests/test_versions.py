"""Tests for version parsing, ordering, and links."""

from sincewhen import Version


def test_parse():
    assert Version.parse("3.14") == Version(3, 14)


def test_str():
    assert str(Version(3, 9)) == "3.9"


def test_ordering_is_numeric():
    assert Version(3, 9) < Version(3, 10) < Version(3, 14)
    assert Version(2, 7) < Version(3, 0)


def test_whatsnew_url():
    assert Version(3, 11).whatsnew_url == "https://docs.python.org/3/whatsnew/3.11.html"


def test_no_whatsnew_url_before_python_2():
    """Python 1.x predates the "What's New" documents."""
    assert Version(1, 5).whatsnew_url is None
