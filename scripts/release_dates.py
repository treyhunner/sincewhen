#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Derive the release-date table that ships in `versions.py`.

A version number on its own does not say much. "Added in 3.2" lands
differently once you know 3.2 shipped in February 2011, so the package
carries the date of every feature release's `.0` and reports it
alongside the version.

Two machine-readable sources, split at the point where one runs out.
python.org's downloads database covers 2.2 onward and is the record of
what was published. Before that it has nothing, so the dates come from
CPython's own release tags: the commit each tag points at is the release
being cut. Where the two overlap they agree, which is the reason to
trust the tags where they are all there is.

1.0 and 1.6 have no tag of their own and 0.9 has none at all. 1.0 is
dated from its 1.0.1 tag, and 1.6 and 0.9 are the two hand-entered rows,
which say why below.

Usage:

    uv run scripts/release_dates.py            # print the table
    uv run scripts/release_dates.py --check    # compare with versions.py
"""

import argparse
import re
import sys

from sources import ROOT, load_releases, load_tag_dates

VERSIONS = ROOT / "src" / "sincewhen" / "versions.py"

# `Python 3.11.0`, and the handful of old entries written without the
# trailing zero.
RELEASE_NAME = re.compile(r"Python (?P<major>\d+)\.(?P<minor>\d+)(\.0)?$")


# The two releases neither source can reach, and where their dates come
# from instead: <https://en.wikipedia.org/wiki/History_of_Python>.
#
# 0.9 is older than the repository. CPython's history begins at 1.0.1,
# so there is no tag to point at, and python.org's downloads database
# does not start until 2.2. Wikipedia's table gives the whole 0.9 line
# one row, 1991-02-20, which is the release this project calls the first
# public release. The corpus reads the 0.9.1 tarball, cut within days of
# it and never separately dated, so this is a `.0` date in exactly the
# sense every other row is one. It being an approximation of 0.9.1 by a
# few days is the smallest error in the table by some margin, and a
# blank column claimed the release had no date at all, which is wrong in
# a way a reader cannot see past.
#
# 1.6 was cut by BeOpen rather than by CNRI, and the modern CPython
# repository carries no `v1.6` tag of any kind, so the tags cannot date
# it and python.org's downloads database starts eleven releases later.
# The corpus cannot either: the 1.6 doc build says "September 18, 2000"
# in its front matter, but that archive is `html-1.6p1`, a rebuilt doc
# set, and the doc date is only a reliable proxy where it is not.
#
# Both fill a hole rather than offering a second opinion, which matters
# because Wikipedia's table and CPython's tags do not agree everywhere
# they overlap: it dates 1.0 to 1994-01-26 against the 1.0.1 tag's
# 1994-02-15, 1.5 to 1998-01-03 against 1997-12-31, and 2.1 to
# 2001-04-15 against 2001-04-16. Those are announcement dates against
# the commit each release was cut from, and the tags keep the rows they
# already answer for. So these are added under the derived table rather
# than over it, and each would become dead the day its tag appears.
UNTAGGED = {
    (0, 9): "1991-02-20",
    (1, 6): "2000-09-05",
}


def dated_releases() -> dict[tuple[int, int], str]:
    """The release date of every feature release this can date."""
    dates = {
        (int(version.split(".")[0]), int(version.split(".")[1])): date
        for version, date in load_tag_dates().items()
    }
    for release in load_releases():
        match = RELEASE_NAME.fullmatch(release["name"])
        if match is None or not release["release_date"]:
            continue
        key = (int(match["major"]), int(match["minor"]))
        dates[key] = release["release_date"][:10]
    return dict(sorted((UNTAGGED | dates).items()))


def render() -> str:
    lines = []
    for (major, minor), date in dated_releases().items():
        lines.append(f'    ({major}, {minor}): "{date}",')
    return "\n".join(lines)


def shipped() -> dict[tuple[int, int], str]:
    """The table as `versions.py` currently has it."""
    text = VERSIONS.read_text(encoding="utf-8")
    body = text.partition("RELEASE_DATES")[2]
    return {
        (int(major), int(minor)): date
        for major, minor, date in re.findall(
            r"\((\d+), (\d+)\): \"(\d{4}-\d{2}-\d{2})\"", body
        )
    }


def check() -> int:
    derived, current = dated_releases(), shipped()
    if derived == current:
        print(f"{len(derived)} release dates match their sources.")
        return 0
    for key in sorted(derived.keys() | current.keys()):
        if derived.get(key) != current.get(key):
            version = f"{key[0]}.{key[1]}"
            print(
                f"{version}: shipped {current.get(key)}, the sources say "
                f"{derived.get(key)}",
                file=sys.stderr,
            )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="compare the shipped table with the source"
    )
    args = parser.parse_args()
    if args.check:
        return check()
    print(render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
