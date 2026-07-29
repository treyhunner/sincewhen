#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Date modules and builtins before the Sphinx era, from the HTML archives.

`objects.inv` only goes back to 2.6, but every HTML doc build from 1.2
onward lists the modules that release documented. Diffing those lists
does for the old era exactly what the inventory diff does for the new
one, and just as deterministically: a module absent from one release's
list and present in the next was added in that next release.

Three formats show up. From 1.5 there is a `modindex.html` that links to
a `module-<name>.html` page per module. From 1.2 to 1.4 each module has
its own HTML page whose heading reads `Standard Module <CODE>aifc</CODE>`.
Before that there is no HTML at all, only the LaTeX in the source
release, which writes the same heading as `Standard module {\tt
string}`. The wording survived every rewrite, so the oldest three
releases can be read the same way as the next three.

This is what catches the cases where the later docs are wrong about
their own history. The Python 2.7 docs claim `bisect` is "New in version
2.1", but `bisect` is right there in the 1.5 module index.

Usage:

    uv run scripts/modindex.py                 # summary per release
    uv run scripts/modindex.py --version 2.0   # what 2.0 added
    uv run scripts/modindex.py --grep bisect
"""

import argparse
import re
from functools import cache
from pathlib import Path

from sources import HTML_BUILDS, SOURCE_BUILDS, html_root

# `<a href="lib/module-bisect.html">` in a Sphinx-era module index.
INDEX_LINK = re.compile(r'href="[^"]*module-(?P<name>[a-zA-Z0-9_.]+)\.html"')

# A module's own section heading, which is the only place the phrase
# means what it looks like. Prose says "standard modules that ..." all
# the time, so matching the phrase alone collects words like `that` and
# `use`, and a stray comment in the 0.9.1 C source ("this should become
# a built-in module 'io'") turns into a claim that `io` predates 1.0.
#
# `\subsection{Standard Module {\tt string}` in the LaTeX and
# `\section{Built-in module \sectcode{array}}` in the slightly later
# LaTeX.
LATEX_HEADING = re.compile(
    r"\\(?:sub)*section\*?\{\s*(?:Standard|Built-in) [Mm]odules?\s*"
    r"(?:\{\\tt\s*|\\sectcode\{)(?P<name>[A-Za-z_][\w.]*)"
)

# `<H1>12.3. Standard Module <CODE>aifc</CODE></H1>` in 1.2 and 1.3, and
# `<H1><A NAME="...">7.3 Built-in Module select</A></H1>` in 1.4, where
# the name has no markup of its own.
HTML_HEADING = re.compile(
    r"<H[1-3][^>]*>(?:\s*<A[^>]*>)?[\d.\s]*(?:Standard|Built-in) [Mm]odules?\s*"
    r"(?:<(?:TT|CODE)>)?\s*(?P<name>[A-Za-z_][\w.]*)",
    re.IGNORECASE,
)

# The releases whose module list comes out of LaTeX rather than HTML.
# Everything about the extraction is the same; only the file extension
# and the markup around the name differ.
ARCHIVE_ORDER = list(SOURCE_BUILDS) + list(HTML_BUILDS)

# Doc-set artefacts rather than importable modules.
NOT_MODULES = frozenset(
    {
        "builtin",
        "main",
        "index",
        "modindex",
        # The extension manual's worked example, not a real module.
        "YOUR",
    }
)

# The Macintosh and distutils doc sets ship their own module indexes,
# covering modules that were never part of the portable stdlib.
SIDE_INDEXES = ("mac", "dist", "inst")


def find_index(root: Path) -> Path | None:
    """The main module index, ignoring the per-doc-set ones."""
    candidates = [
        path
        for path in root.rglob("modindex.html")
        if not any(part in SIDE_INDEXES for part in path.relative_to(root).parts)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda path: len(path.parts))


def library_pages(root: Path) -> list[Path]:
    """The per-module pages, whether HTML or LaTeX.

    A source release has a `lib/` directory too, but it holds the
    modules themselves rather than pages about them, so an empty result
    falls through to the LaTeX.
    """
    for name in ("lib", "python-lib"):
        for directory in root.rglob(name):
            pages = sorted(directory.glob("*.html"))
            if pages:
                return pages
    return sorted(root.rglob("*.tex"))


@cache
def modules_in(version: str) -> frozenset[str]:
    """Every module documented in one release."""
    root = html_root(version)
    if not root.exists():
        raise SystemExit("No cached HTML docs. Run: uv run scripts/fetch_docs.py")

    index = find_index(root)
    if index is not None:
        text = index.read_text(encoding="utf-8", errors="replace")
        found = {match["name"] for match in INDEX_LINK.finditer(text)}
    else:
        found = set()
        for page in library_pages(root):
            text = page.read_text(encoding="utf-8", errors="replace")
            pattern = LATEX_HEADING if page.suffix == ".tex" else HTML_HEADING
            found.update(match["name"] for match in pattern.finditer(text))

    return frozenset(found - NOT_MODULES)


def extraction(version: str) -> str:
    """Which of the two shapes a release's module list was read from."""
    return "modindex" if find_index(html_root(version)) is not None else "headings"


@cache
def dated_modules() -> dict[str, dict[str, str]]:
    """First release each module appears in, across the HTML archives.

    Two things produce a floor rather than a date. The oldest archive is
    a baseline, since its modules were already there when the record
    starts. And a release whose predecessor was read a different way
    cannot be diffed against it: 1.5 rewrote the docs and gave modules
    their own pages, so plenty of things that look new in the 1.5 index
    were only newly *documented* as modules. `os.path` is the giveaway.
    It is as old as Python, and it first appears in the 1.5 index
    because that is when it got a page of its own.
    """
    baseline, *rest = ARCHIVE_ORDER
    seen = set(modules_in(baseline))
    dated = {name: {"floor": baseline} for name in sorted(seen)}

    previous = baseline
    for version in rest:
        comparable = extraction(version) == extraction(previous)
        for name in sorted(modules_in(version) - seen):
            dated[name] = (
                {"added": version, "absent_in": previous, "present_in": version}
                if comparable
                else {"floor": version}
            )
        seen |= modules_in(version)
        previous = version
    return dated


# A module's members, in the three shapes the archives use. The LaTeX
# names the member and leaves the module to the enclosing section; the
# oldest HTML helpfully names both on one line; the later HTML puts the
# member on its module's own page.
MEMBER_LATEX = re.compile(
    r"\\begin\{(?:func|data|exc|class|member)desc\}\{(?P<name>[A-Za-z_]\w*)\}"
)
MEMBER_NAMED_HTML = re.compile(
    r"<DT><B>(?P<name>[A-Za-z_]\w*)</B>\s*--\s*\w+ of module\s+(?P<module>[\w.]+)",
    re.IGNORECASE,
)
MEMBER_HTML = re.compile(
    r"<dt><b>(?:<a[^>]*>)?<tt[^>]*>(?P<name>[A-Za-z_]\w*)</tt>", re.IGNORECASE
)

# `\subsection{Standard Module {\tt string}` inside a LaTeX file that
# documents several modules, which is how the 0.9.1 manual is laid out.
LATEX_MODULE = re.compile(
    r"\\(?:sub)*section\*?\{\s*(?:Standard|Built-in) [Mm]odules?\s*"
    r"(?:\{\\tt\s*|\\sectcode\{)(?P<name>[A-Za-z_][\w.]*)"
)

# The page name that says which module a page documents.
MODULE_PAGE = re.compile(r"^module-(?P<name>[\w.]+)$")


def _members_from_latex(text: str) -> set[str]:
    """Members of every module a LaTeX file documents, dotted."""
    found = set()
    module = None
    for line in text.splitlines():
        heading = LATEX_MODULE.search(line)
        if heading is not None:
            module = heading["name"]
            continue
        member = MEMBER_LATEX.search(line)
        if member is not None and module is not None:
            found.add(f"{module}.{member['name']}")
    return found


@cache
def members_in(version: str) -> frozenset[str]:
    """Every documented `module.member` in one release."""
    root = html_root(version)
    found: set[str] = set()
    for page in library_pages(root):
        text = page.read_text(encoding="utf-8", errors="replace")
        if page.suffix == ".tex":
            found |= _members_from_latex(text)
            continue
        found |= {
            f"{match['module']}.{match['name']}"
            for match in MEMBER_NAMED_HTML.finditer(text)
        }
        named = MODULE_PAGE.fullmatch(page.stem)
        if named is not None:
            found |= {
                f"{named['name']}.{match['name']}"
                for match in MEMBER_HTML.finditer(text)
            }
    return frozenset(found)


@cache
def dated_members() -> dict[str, dict[str, str]]:
    """The oldest release known to document each `module.member`.

    Members only ever get a floor, never a date. The markup for them
    changed three times and each build indexes a different share of
    what it documents: 2.2 yields 1456 members and 2.3 only 476, which
    is a change in the doc build rather than 980 removals. Diffing that
    would invent additions wholesale.

    Presence survives all of it. A member on a release's page was in
    that release, whatever the next build does, so "1.3 or earlier" is
    a claim these archives can carry and "added in 2.3" is not.
    """
    floors: dict[str, dict[str, str]] = {}
    for version in ARCHIVE_ORDER:
        for name in members_in(version):
            floors.setdefault(name, {"floor": version})
    return floors


# The built-in functions page, whose markup changed twice: the oldest
# builds put the name in a bare `<B>`, later ones in a `<tt>` with a
# function class.
BUILTIN = re.compile(
    r"""<tt class=['"]?function['"]?>(?P<tagged>[A-Za-z_]\w*)</tt>"""
    r"""|<DT><B>(?P<bare>[A-Za-z_]\w*)</B>""",
    re.IGNORECASE,
)

BUILTIN_PAGES = ("built-in-funcs.html", "built-in_functions.html")

# The last release whose built-in functions page this can read. From 2.4
# the page is built out of nested tables and the pattern above stops
# finding names, which would make every later release look like it
# removed most of the builtins. Nothing is lost: 2.6 onward is covered
# by the inventories, and 2.4 and 2.5 by the annotation grep.
NEWEST_READABLE_BUILTINS = "2.3"


@cache
def builtins_in(version: str) -> frozenset[str]:
    """Every builtin documented on one release's built-in functions page."""
    root = html_root(version)
    found = set()
    for page in BUILTIN_PAGES:
        for path in root.rglob(page):
            text = path.read_text(encoding="utf-8", errors="replace")
            found.update(
                match["tagged"] or match["bare"] for match in BUILTIN.finditer(text)
            )
    return frozenset(found)


@cache
def dated_builtins() -> dict[str, dict[str, str]]:
    """First release each builtin is documented in.

    Releases whose page this cannot read are skipped rather than
    treated as empty, so a gap in the archives never reads as a
    removal.
    """
    readable = [
        version
        for version in ARCHIVE_ORDER
        if builtins_in(version)
        and version_key(version) <= version_key(NEWEST_READABLE_BUILTINS)
    ]
    baseline, *rest = readable
    seen = set(builtins_in(baseline))
    dated = {name: {"floor": baseline} for name in sorted(seen)}

    previous = baseline
    for version in rest:
        for name in sorted(builtins_in(version) - seen):
            dated[name] = {
                "added": version,
                "absent_in": previous,
                "present_in": version,
            }
        seen |= builtins_in(version)
        previous = version
    return dated


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="only modules added in this release")
    parser.add_argument("--grep", help="only modules whose name contains this")
    parser.add_argument(
        "--builtins", action="store_true", help="report builtins instead of modules"
    )
    parser.add_argument(
        "--members", action="store_true", help="report module members instead"
    )
    args = parser.parse_args()

    if args.members:
        for name, record in sorted(dated_members().items()):
            where = record.get("added") or f"{record['floor']} or earlier"
            if not args.grep or args.grep in name:
                print(f"{name:<40} {where}")
        return 0

    if args.builtins:
        for name, record in sorted(dated_builtins().items()):
            where = record.get("added") or f"{record['floor']} or earlier"
            if not args.grep or args.grep in name:
                print(f"{name:<20} {where}")
        return 0

    dated = dated_modules()

    if args.grep:
        for name, record in sorted(dated.items()):
            if args.grep in name:
                where = record.get("added") or f"{record['floor']} or earlier"
                print(f"{name:<30} {where}")
        return 0

    if args.version:
        names = sorted(n for n, r in dated.items() if r.get("added") == args.version)
        for name in names:
            print(name)
        print(f"\n{len(names)} modules added in {args.version}")
        return 0

    counts: dict[str, int] = {}
    for record in dated.values():
        key = record.get("added") or f"{record['floor']} or earlier"
        counts[key] = counts.get(key, 0) + 1
    for version in ARCHIVE_ORDER:
        for key in (f"{version} or earlier", version):
            if key in counts:
                print(
                    f"{key:>16}  {counts[key]:>4} modules  ({len(modules_in(version))} documented)"
                )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
