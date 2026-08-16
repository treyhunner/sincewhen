"""Command-line interface for sincewhen."""

import argparse
import json
import sys
from importlib.metadata import version
from pathlib import Path

from .detect import Detection, detect
from .features import Feature, enclosing_module, has_entry, lookup
from .members import SUGGESTION_LIMIT, MemberAnswer, find_members, lookup_member
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
        help="hide features older than this, to see only the recent arrivals",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('sincewhen')}",
        help="show the version of sincewhen itself and exit",
    )
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
        "removed": str(feature.removed) if feature.removed else None,
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


def _member_data(answer: MemberAnswer) -> dict:
    # `owner` rather than `module`, because it is a class as often as
    # one now and `"module": "unittest.TestCase"` would be a false
    # statement in machine-readable output.
    return {
        "name": answer.dotted,
        "owner": answer.owner,
        "added": str(answer.added),
        "or_earlier": answer.or_earlier,
        "released": released.isoformat()
        if (released := answer.added.released)
        else None,
    }


def _when(version: Version) -> str:
    released = _released(version)
    return f" (released {released})" if released else ""


def _print_features(term: str, features: list[Feature]) -> None:
    """Search's long form, where each half of the answer gets its date.

    The compact `since` phrase is not reused here, because appending one
    release date to it would attach the wrong one: "Python 0.9, removed
    in 3.0 (released 1991-02-20)" dates the removal to seventeen years
    before it happened. Both dates are worth having anyway, since how
    long ago a name went away is the same kind of question as how long
    ago it arrived.
    """
    if features == enclosing_module(term.casefold().strip()):
        print(f"No entry for {term}, but it lives in:")
    for feature in features:
        arrived = f"{feature.added} or earlier" if feature.or_earlier else feature.added
        line = f"{feature.name} - Python {arrived}{_when(feature.added)}"
        if feature.removed is not None:
            line += f", removed in {feature.removed}{_when(feature.removed)}"
        print(line)
        for label, url in (("PEP", feature.pep_url), ("Docs", feature.docs_url)):
            if url:
                print(f"  {label}: {url}")


def _print_members(answers: list[MemberAnswer]) -> None:
    for answer in answers[:SUGGESTION_LIMIT]:
        released = _released(answer.added)
        when = f" (released {released})" if released else ""
        print(f"{answer.dotted} - Python {answer.since}{when}")
    if len(answers) > SUGGESTION_LIMIT:
        print(f"...and {len(answers) - SUGGESTION_LIMIT} more.")


def _suggestions(query: str) -> list[MemberAnswer]:
    """Members named exactly this that the dataset does not already date."""
    return [answer for answer in find_members(query) if not has_entry(answer.dotted)]


def _search(term: str, as_json: bool) -> int:
    """Search mode: the dataset first, then the member index.

    The order is the whole of it. An entry of its own is the sharpest
    answer there is, because it carries the evidence for its version;
    the index is next, being the same version without it; and the module
    a name lives in is the vaguest, being a bound on the member rather
    than an answer about it. Each speaks only when the one above it has
    nothing, which is why the module fallback `lookup` already does is
    unpicked here rather than taken at face value.

    "An entry of its own" has to mean `has_entry` and not "`lookup`
    found something", because `lookup` matches ids and names by
    substring. Testing the wrong one hid the index's exact answer behind
    a near miss for 37 dotted names: `os.wait` printed `os.wait3` and
    `os.wait4`, `heapq.heapify` printed `heapq.heapify_max`, and nothing
    said the name printed was not the name asked for.

    A bare name gets both. `system` matches the dataset by substring and
    is also a member of `os` and of `platform`, and the second half is
    the one somebody typing it probably meant.

    The index is asked for the name as typed, because a module member is
    spelled the way its module spells it and `ElementTree` is not
    `elementtree`.
    """
    query = term.strip()
    found = lookup(term)
    module_only = bool(found) and found == enclosing_module(query.casefold())
    exact = lookup_member(query)

    if has_entry(query):
        features, answers = found, []
    elif exact is not None:
        features, answers = [], [exact]
    elif found and not module_only:
        features, answers = found, _suggestions(query)
    elif suggested := _suggestions(query):
        features, answers = [], suggested
    elif not found and "." in query and (near := _suggestions(query.rsplit(".")[-1])):
        # A dotted name that matched nothing at all, not even a module,
        # is usually a typo in the module: `suprocess.Popen`. The part
        # after the dot is still a name worth answering, and it is the
        # half the reader spelled correctly. Only when nothing was found
        # is this reached, so a real module that simply lacks the member
        # still gets the module fallback below rather than a suggestion
        # from somewhere else: `os.Popen` answers about `os`.
        features, answers = [], near
    else:
        features, answers = found, []

    if as_json:
        payload = [_feature_data(f) for f in features]
        payload += [_member_data(a) for a in answers]
        print(json.dumps(payload, indent=2))
        return 0 if payload else 1

    if not features and not answers:
        print(f"No feature matches {term!r}.", file=sys.stderr)
        return 1
    if features:
        _print_features(term, features)
    if answers:
        # An exact member gets no preamble. Which of this tool's two data
        # files answered is not something to make the reader think about,
        # and the answer is about the name they typed either way. The
        # module fallback below still announces itself, because that one
        # answers a different question from the one that was asked.
        if exact is None:
            print(
                f"{term!r} is also a member of:"
                if features
                else f"No entry for {term!r}. Did you mean one of these?"
            )
        _print_members(answers)
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
