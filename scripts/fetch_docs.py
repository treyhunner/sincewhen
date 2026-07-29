#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Download the documentation corpus that the research scripts read.

This is the only script that touches the network. It stores every
payload under `.cache/` (gitignored) and records a SHA-256 for each one
in `scripts/sources.sha256` (committed), so a later run can prove it is
reading the same bytes.

Usage:

    uv run scripts/fetch_docs.py            # fetch anything missing
    uv run scripts/fetch_docs.py --check    # verify the cache, no network
"""

import argparse
import json
import sys
import tarfile
import urllib.request

from sources import (
    CACHE,
    GRAMMAR_TAGS,
    GRAMMAR_URL,
    HTML_BUILDS,
    HTML_URL,
    INVENTORY_URL,
    INVENTORY_VERSIONS,
    PEG_TAGS,
    PEPS_URL,
    RELEASE_TAGS,
    RELEASES_URL,
    SOURCE_BUILDS,
    TAG_URL,
    TEXT_BUILDS,
    TEXT_URL,
    digest,
    grammar_path,
    html_archive_path,
    html_root,
    inventory_path,
    peps_path,
    read_manifest,
    releases_path,
    source_archive_path,
    tags_path,
    text_archive_path,
    text_root,
    write_manifest,
)

USER_AGENT = "sincewhen-docs-fetcher (+https://github.com/treyhunner/sincewhen)"


def download(url: str, destination) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=120) as response:
        destination.write_bytes(response.read())


def relative(path) -> str:
    return str(path.relative_to(CACHE))


def fetch_all() -> dict[str, str]:
    entries = read_manifest()

    for version in INVENTORY_VERSIONS:
        path = inventory_path(version)
        if not path.exists():
            url = INVENTORY_URL.format(version=version)
            print(f"fetching {url}")
            download(url, path)
        entries[relative(path)] = digest(path)

    for tags, peg in ((GRAMMAR_TAGS, False), (PEG_TAGS, True)):
        for version, tag in tags.items():
            path = grammar_path(version, peg)
            if not path.exists():
                url = GRAMMAR_URL.format(
                    tag=tag, file="python.gram" if peg else "Grammar"
                )
                print(f"fetching {url}")
                download(url, path)
            entries[relative(path)] = digest(path)

    peps = peps_path()
    if not peps.exists():
        print(f"fetching {PEPS_URL}")
        download(PEPS_URL, peps)
    entries[relative(peps)] = digest(peps)

    releases = releases_path()
    if not releases.exists():
        print(f"fetching {RELEASES_URL}")
        download(RELEASES_URL, releases)
    entries[relative(releases)] = digest(releases)

    for version, micro in TEXT_BUILDS.items():
        archive = text_archive_path(micro)
        if not archive.exists():
            url = TEXT_URL.format(micro=micro)
            print(f"fetching {url}")
            download(url, archive)
        entries[relative(archive)] = digest(archive)

        root = text_root(version)
        if not root.exists():
            print(f"extracting {archive.name}")
            root.mkdir(parents=True)
            with tarfile.open(archive) as tar:
                tar.extractall(root, filter="data")

    tags = tags_path()
    if not tags.exists():
        dates = {}
        for version, tag in RELEASE_TAGS.items():
            url = TAG_URL.format(tag=tag)
            print(f"fetching {url}")
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                commit = json.load(response)["commit"]
            dates[version] = commit["committer"]["date"][:10]
        tags.parent.mkdir(parents=True, exist_ok=True)
        tags.write_text(json.dumps(dates, indent=2) + "\n", encoding="utf-8")
    entries[relative(tags)] = digest(tags)

    for version, path in SOURCE_BUILDS.items():
        archive = source_archive_path(version)
        if not archive.exists():
            url = HTML_URL.format(path=path)
            print(f"fetching {url}")
            download(url, archive)
        entries[relative(archive)] = digest(archive)

        root = html_root(version)
        if not root.exists():
            print(f"extracting {archive.name}")
            root.mkdir(parents=True)
            with tarfile.open(archive) as tar:
                tar.extractall(root, filter="data")

    for version in HTML_BUILDS:
        archive = html_archive_path(version)
        if not archive.exists():
            url = HTML_URL.format(path=HTML_BUILDS[version])
            print(f"fetching {url}")
            download(url, archive)
        entries[relative(archive)] = digest(archive)

        root = html_root(version)
        if not root.exists():
            print(f"extracting {archive.name}")
            root.mkdir(parents=True)
            with tarfile.open(archive) as tar:
                tar.extractall(root, filter="data")

    return entries


def check() -> int:
    """Verify every cached payload against the committed manifest."""
    entries = read_manifest()
    if not entries:
        print("No manifest yet. Run without --check first.", file=sys.stderr)
        return 1

    problems = []
    for path, expected in sorted(entries.items()):
        cached = CACHE / path
        if not cached.exists():
            problems.append(f"missing: {path}")
        elif digest(cached) != expected:
            problems.append(f"changed: {path}")

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"{len(entries)} cached sources match the manifest.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the cache against the manifest without downloading",
    )
    args = parser.parse_args()

    if args.check:
        return check()

    entries = fetch_all()
    write_manifest(entries)
    print(f"{len(entries)} sources cached, manifest written.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
