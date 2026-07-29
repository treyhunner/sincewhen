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

1.0 and 1.6 have no tag of their own and 0.9 has none at all, so 1.0 is
dated from 1.0.1 and the other two go undated.

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
    return dict(sorted(dates.items()))


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
        print(f"{len(derived)} release dates match python.org.")
        return 0
    for key in sorted(derived.keys() | current.keys()):
        if derived.get(key) != current.get(key):
            version = f"{key[0]}.{key[1]}"
            print(
                f"{version}: shipped {current.get(key)}, python.org says "
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
