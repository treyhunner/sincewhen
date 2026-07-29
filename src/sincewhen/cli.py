"""Command-line interface for sincewhen."""

import argparse
import json
import sys
from pathlib import Path

from .detect import Detection, detect
from .features import Feature, enclosing_module, lookup
from .versions import Version


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sincewhen",
        description="Find out which Python version added each feature your code uses.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Python files to analyze (use - for standard input)",
    )
    parser.add_argument(
        "-s",
        "--search",
        metavar="TERM",
        help="look a feature up by name instead of analyzing code",
    )
    parser.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="report every use, not just the first of each feature",
    )
    parser.add_argument(
        "--since",
        metavar="VERSION",
        type=Version.parse,
        help="hide features older than this, for when the ancient ones are noise",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    return parser


def _read(path: Path) -> tuple[str, str]:
    if str(path) == "-":
        return sys.stdin.read(), "<stdin>"
    return path.read_text(encoding="utf-8"), str(path)


def _drop_implied(detections: list[Detection]) -> list[Detection]:
    """Drop a module line when a member of it says the same thing.

    `from dataclasses import dataclass` is one import that matches two
    features of the same age. Both are true and printing both is noise,
    so the more specific one speaks for the pair. The module keeps its
    line whenever it is the older of the two, since then it is saying
    something the member does not.
    """
    members = {
        (found.lineno, name.partition(".")[0], found.added)
        for found in detections
        for name in found.feature.attributes
    }
    return [
        found
        for found in detections
        if not any(
            (found.lineno, module, found.added) in members
            for module in found.feature.modules
        )
    ]


def _first_uses(detections: list[Detection]) -> list[Detection]:
    seen = set()
    kept = []
    for found in detections:
        if found.feature.id not in seen:
            seen.add(found.feature.id)
            kept.append(found)
    return kept


def _feature_data(feature: Feature) -> dict:
    return {
        "id": feature.id,
        "name": feature.name,
        "added": str(feature.added),
        "or_earlier": feature.or_earlier,
        "released": released.isoformat()
        if (released := feature.added.released)
        else None,
        "category": feature.category,
        "pep": feature.pep,
        "pep_url": feature.pep_url,
        "docs_url": feature.docs_url,
    }


def _released(version: Version) -> str:
    """When that release shipped, for the reader's sense of scale."""
    released = version.released
    return released.isoformat() if released else ""


def _report(results: list[tuple[str, list[Detection]]]) -> None:
    rows = [
        (
            f"{name}:{found.lineno}",
            found.feature.name,
            found.feature.since,
            _released(found.added),
        )
        for name, detections in results
        for found in detections
    ]
    if not rows:
        print("No dated features detected.")
        return
    location_width = max(len(location) for location, *_ in rows)
    name_width = max(len(name) for _, name, *_ in rows)
    since_width = max(len(since) for *_, since, _ in rows)
    for location, name, since, released in rows:
        line = f"{location:<{location_width}}  {name:<{name_width}}  {since:<{since_width}}"
        print(f"{line}  {released}".rstrip())

    # Non-empty rows guarantee at least one detection, so there is a floor.
    floor = max(found.added for _, detections in results for found in detections)
    setters = sorted(
        {
            found.feature.name
            for _, detections in results
            for found in detections
            if found.added == floor
        }
    )
    released = _released(floor)
    since = f", released {released}" if released else ""
    print(f"\nMinimum: Python {floor}{since} (set by {', '.join(setters)})")


def _search(term: str, as_json: bool) -> int:
    features = lookup(term)
    if as_json:
        print(json.dumps([_feature_data(f) for f in features], indent=2))
        return 0 if features else 1
    if not features:
        print(f"No feature matches {term!r}.", file=sys.stderr)
        return 1
    if features == enclosing_module(term.casefold().strip()):
        print(f"No entry for {term}, but it lives in:")
    for feature in features:
        released = _released(feature.added)
        when = f" (released {released})" if released else ""
        print(f"{feature.name} - Python {feature.since}{when}")
        for label, url in (("PEP", feature.pep_url), ("Docs", feature.docs_url)):
            if url:
                print(f"  {label}: {url}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.search:
        return _search(args.search, args.json)

    if not args.paths:
        _parser().error("provide at least one path, or use --search")

    results = []
    for path in args.paths:
        try:
            source, name = _read(path)
        except OSError as error:
            print(f"sincewhen: {error}", file=sys.stderr)
            return 2
        try:
            detections = detect(source, filename=name)
        except SyntaxError as error:
            print(f"sincewhen: {name}: {error}", file=sys.stderr)
            return 2
        detections = _drop_implied(detections)
        if args.since:
            detections = [f for f in detections if f.added >= args.since]
        if not args.all:
            detections = _first_uses(detections)
        results.append((name, detections))

    if args.json:
        print(
            json.dumps(
                {
                    name: [
                        {
                            "line": f.lineno,
                            "column": f.col_offset,
                            **_feature_data(f.feature),
                        }
                        for f in detections
                    ]
                    for name, detections in results
                },
                indent=2,
            )
        )
    else:
        _report(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
