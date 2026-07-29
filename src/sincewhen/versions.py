"""Python version numbers, comparable and printable."""

from datetime import date
from typing import NamedTuple, Self

# When each feature release's `.0` shipped, so that a version number can
# be read as an age: 3.2 is not just older than 3.11, it is fourteen
# years older.
#
# Two sources, checked against each other and against this table by
# `just verify-dataset`. Regenerate with `uv run scripts/release_dates.py`.
#
# From 2.2 on, python.org's downloads database, which is the record of
# what was published. Before that it has nothing, so the dates come from
# the commit each CPython release tag points at. The two agree wherever
# they overlap.
#
# Missing: 0.9 and 1.6, which have no release tag, and so no date this
# project can cite. 1.0 is dated from its 1.0.1 tag.
RELEASE_DATES = {
    (1, 0): "1994-02-15",
    (1, 1): "1994-10-11",
    (1, 2): "1995-04-10",
    (1, 3): "1995-10-12",
    (1, 4): "1996-10-25",
    (1, 5): "1997-12-31",
    (2, 0): "2000-10-16",
    (2, 1): "2001-04-16",
    (2, 2): "2001-12-21",
    (2, 3): "2003-07-29",
    (2, 4): "2004-11-30",
    (2, 5): "2006-09-19",
    (2, 6): "2008-10-02",
    (2, 7): "2010-07-03",
    (3, 0): "2008-12-03",
    (3, 1): "2009-06-26",
    (3, 2): "2011-02-20",
    (3, 3): "2012-09-29",
    (3, 4): "2014-03-17",
    (3, 5): "2015-09-13",
    (3, 6): "2016-12-23",
    (3, 7): "2018-06-27",
    (3, 8): "2019-10-14",
    (3, 9): "2020-10-05",
    (3, 10): "2021-10-04",
    (3, 11): "2022-10-24",
    (3, 12): "2023-10-02",
    (3, 13): "2024-10-07",
    (3, 14): "2025-10-07",
}

DAYS_PER_YEAR = 365.2425


class Version(NamedTuple):
    """A Python feature-release version, such as 3.14.

    Tuple ordering gives correct comparisons for free, so 3.9 sorts
    before 3.10 rather than after it.
    """

    major: int
    minor: int

    @classmethod
    def parse(cls, text: str) -> Self:
        major, _, minor = text.partition(".")
        return cls(int(major), int(minor))

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}"

    @property
    def whatsnew_url(self) -> str | None:
        """Link to the "What's New" page, when one exists."""
        if self.major < 2:
            return None
        return f"https://docs.python.org/3/whatsnew/{self}.html"

    @property
    def released(self) -> date | None:
        """The day this release shipped, if python.org records one."""
        recorded = RELEASE_DATES.get(tuple(self))
        return date.fromisoformat(recorded) if recorded else None

    def age(self, today: date | None = None) -> float | None:
        """How many years ago this release shipped."""
        released = self.released
        if released is None:
            return None
        return ((today or date.today()) - released).days / DAYS_PER_YEAR
