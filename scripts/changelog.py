#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Read one release's notes out of `CHANGELOG.md`.

The release workflow feeds the printed section to `gh release create
--notes-file`, so the GitHub release, the PyPI page, and the repository
all describe a release the same way. `just release` runs the same code
with `--check` and refuses to tag a version the changelog has nothing to
say about, which is what keeps the changelog from drifting behind the
releases it documents.

Usage:

    uv run scripts/changelog.py 0.2.0            # print that release's notes
    uv run scripts/changelog.py 0.2.0 --check    # only check they exist
"""

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"

# `## 0.2.0 - 2026-08-01`, and the undated `## Unreleased`.
HEADING = re.compile(r"^## +(?P<version>\S+)")

# What the Unreleased section says when nothing has landed in it yet.
PLACEHOLDER = "Nothing yet."


def section(text: str, version: str) -> str:
    """The body of the `## <version>` section, without its heading."""
    body: list[str] = []
    found = False
    for line in text.splitlines():
        if match := HEADING.match(line):
            if found:
                break
            found = match["version"] == version
        elif found:
            body.append(line)
    if not found:
        raise LookupError(f"CHANGELOG.md has no section for {version}.")
    notes = "\n".join(body).strip()
    if not notes or notes == PLACEHOLDER:
        raise LookupError(f"The {version} section of CHANGELOG.md is empty.")
    return notes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="the release to read, such as 0.2.0")
    parser.add_argument(
        "--check", action="store_true", help="check the notes exist without printing"
    )
    args = parser.parse_args()
    try:
        notes = section(CHANGELOG.read_text(encoding="utf-8"), args.version)
    except LookupError as error:
        print(error, file=sys.stderr)
        return 1
    if args.check:
        print(f"CHANGELOG.md documents {args.version}.")
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
