"""Tests for version parsing, ordering, links, and release dates."""

from datetime import date

import pytest

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


def test_release_date():
    assert Version(3, 11).released == date(2022, 10, 24)


def test_release_date_from_a_cpython_tag():
    """Before 2.2 the dates come from CPython's release tags."""
    assert Version(1, 5).released == date(1997, 12, 31)


def test_no_release_date_for_a_release_with_no_tag():
    """0.9 and 1.6 have no release tag, so there is no date to cite."""
    assert Version(0, 9).released is None
    assert Version(0, 9).age() is None


def test_age_is_measured_in_years():
    assert Version(3, 11).age(date(2024, 10, 24)) == pytest.approx(2, abs=0.01)
