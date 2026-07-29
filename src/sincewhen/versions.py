"""Python version numbers, comparable and printable."""

from typing import NamedTuple, Self


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
