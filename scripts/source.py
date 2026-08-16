#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Date builtins, modules and members from the source itself.

The archives bottom out at 1.2 for builtins, because that is the oldest
HTML build carrying a built-in functions page. Everything already on
that page can only be bounded, so with the docs as the only witness
`map` reports as "1.2 or earlier". The source releases reach further
back: 0.9.1 is the first public Python, from 1991, and its
`bltinmodule.c` carries the same method table every later release does.

Modules work the same way and gain more, because the module *index*
dates documentation rather than shipping. `bisect` ships in the 1.0
tarball, is first indexed in the 1.5 docs, and is claimed by the 2.7
docs to be 2.1. The tarball settles it.

Members gain the most, because a doc build indexes whatever share of a
release it happened to paginate and their floors come out scattered
across every release rather than piled at the oldest archive.
`calendar.day_abbr` is in the 0.9.1 library and reads as 2.5 from the
docs, which is when it was first written down.

This inverts the rule the rest of the pipeline runs on. Everywhere else
presence is strong and absence is weak, because a release's docs can
omit something it shipped. Here a method table *is* the list a module
registers its functions from rather than a description of one, so a name
missing from it is a name that release did not have. That is what
settles `map`: absent from 0.9.1, present in 1.0.1, so `map` is 1.0, and
the doc archives were only ever reporting how far back they went.

But that argument does not hold uniformly, which is why members are read
in two tiers rather than one. A C module's namespace is written down in
full, in its method table and in the calls that insert its constants. A
Python module's need not be: `os.py` is little more than
`from posix import *`, so `os.getcwd` appears nowhere in it and its
absence means nothing. So presence is read strictly and absence
generously, and a module whose own text is not the whole of its
namespace can only ever tighten a floor.

0.9.1 is still the floor of everything. A builtin already in it, like
`max`, cannot be dated, only bounded, and reports as "0.9 or earlier".
That is the true floor of the surviving record rather than an artifact
of which doc builds happened to be kept.

The trap is the one the HTML side has too. `{"name", ...}` is ordinary C
that appears in every method table in the tree, so matching it loosely
would collect the members of whatever module sits next to it. Find the
table the registration call names and read only its body.

Usage:

    uv run scripts/source.py                 # every builtin, dated
    uv run scripts/source.py --modules       # every module, dated
    uv run scripts/source.py --members       # every module member, dated
    uv run scripts/source.py --version 1.0   # what 1.0 added
    uv run scripts/source.py --grep map
"""

import argparse
import re
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path

from sources import SOURCE_BUILDS, source_root

# The source releases, oldest first: 0.9.1 through 2.5, which is the
# whole of the era the Sphinx inventories cannot reach.
SOURCE_ORDER = tuple(SOURCE_BUILDS)

# The builtins table, which every release from 0.9.1 on declares under
# the same name and closes with a `};` in the first column. Reading only
# what is between the two is what keeps the neighbouring method tables
# out of the result.
BUILTIN_TABLE = re.compile(
    r"builtin_methods\s*\[\s*\]\s*=\s*\{(?P<body>.*?)^\};",
    re.DOTALL | re.MULTILINE,
)

# One row of it: `{"abs", builtin_abs},`, with whitespace that is spaces
# in 0.9.1 and tabs from 1.0 on. The sentinel row is `{NULL, NULL}`,
# which has no quotes and so never matches.
TABLE_ENTRY = re.compile(r'^\s*\{\s*"(?P<name>[A-Za-z_]\w*)"', re.MULTILINE)

BUILTIN_SOURCE = "bltinmodule.c"

# Where a release keeps its Python modules. 0.9.1 lowercases it and
# every release since capitalises it.
LIBRARY_DIRS = ("Lib", "lib")

# Directories that ship alongside the library without being part of it.
# A demo or a test is not a module anyone can import by that name.
NOT_LIBRARY = frozenset({"demo", "test", "tests", "dos", "mac", "extensions"})

# The same idea for the C sources: the interpreter and its modules are
# the tree, and everything else beside them describes it.
NOT_INTERPRETER = frozenset({"demo", "doc", "misc", "tools"})

# `initmodule("math", math_methods)` in 0.9.1 and 1.0, `Py_InitModule`
# in 1.1, and the `3` and `4` variants later. The spelling kept changing
# and the arguments did not: the name is a string literal and the method
# table is whatever follows it.
#
# Reading the call rather than the `init<name>()` function around it is
# deliberate. `pythonmain.c` defines `initall()` to boot every module at
# once, so reading function names credits a release with a module called
# `all`.
MODULE_INIT = re.compile(
    r'(?:Py_)?[Ii]nit[Mm]odule\d?\s*\(\s*"(?P<name>[A-Za-z_][\w.]*)"\s*,\s*(?P<table>\w+)'
)

# A name bound into a module's dict, which every era spells out as a
# string literal: `dictinsert(d, "pi", v)` and `sysset("path", v)` in
# the old tree, `insint(d, "SIGINT", n)` and
# `PyDict_SetItemString(d, "error", x)` later. The name is the first or
# the second argument depending on the helper, so both are accepted.
MODULE_BINDING = re.compile(
    r"\b(?:dictinsert|sysset|ins(?:int|str|obj)?"
    r"|PyDict_SetItemString|PyModule_Add\w+|SETBUILTIN)\s*"
    r'\(\s*(?:\w+\s*,\s*)?"(?P<name>[A-Za-z_]\w*)"\s*[,)]'
)

# A preprocessor conditional, whose body a build may or may not compile.
CONDITIONAL = re.compile(r"^[ \t]*#[ \t]*(?P<directive>if\w*|endif)\b")

# What a Python module binds at the top level: a `def`, a `class`, an
# assignment, or a name imported into it. Anything indented belongs to
# something else, or is conditional, and is not read as a member.
#
# The import case is not an edge case in this era. `random` re-exported
# `randrange` from `whrandom` for six releases, and reading only what
# the file defines dates it to when the re-export stopped.
PY_BINDING = re.compile(
    r"^(?:def[ \t]+(?P<function>\w+)"
    r"|class[ \t]+(?P<klass>\w+)"
    r"|from[ \t]+[\w.]+[ \t]+import[ \t]+(?P<imported>[^*\n(]+)"
    r"|(?P<name>[A-Za-z_]\w*)[ \t]*=(?!=))",
    re.MULTILINE,
)

# One name out of an import list, which may rename it: `a, b as c`. The
# binding is the last word either way.
IMPORTED = re.compile(r"(?:\w+[ \t]+as[ \t]+)?(?P<name>[A-Za-z_]\w*)")

# A class statement at the top level of a Python module, and whatever it
# inherits from. Only the top level: a nested class is `Outer.Inner` and
# a member of one is three levels deep, which is further than the index
# spells a name.
CLASS_HEADER = re.compile(
    r"^class[ \t]+(?P<name>\w+)[ \t]*(?:\((?P<bases>[^)]*)\))?[ \t]*:",
    re.MULTILINE,
)

# Where a class body ends: the next line starting in column zero.
AFTER_CLASS = re.compile(r"^\S", re.MULTILINE)

# A name bound in a class body. The assignment case carries as much
# weight as the `def`, because it is how several of these names actually
# exist: 2.3's `unittest.py` writes `assertAlmostEqual =
# assertAlmostEquals = failUnlessAlmostEqual`, so the two spellings
# anybody uses are chained assignments and the `def` is a third name.
#
# The chain is matched whole and split afterwards. `(?!=)` keeps `==`
# out, and `+=` never matches because the `=` is not what follows the
# name.
CLASS_MEMBER = re.compile(
    r"^(?P<indent>[ \t]+)(?:def[ \t]+(?P<function>\w+)"
    r"|class[ \t]+(?P<klass>\w+)"
    r"|(?P<targets>[A-Za-z_]\w*(?:[ \t]*=[ \t]*[A-Za-z_]\w*)*)[ \t]*=(?!=))",
    re.MULTILINE,
)

# Bases that leave a class's body an exhaustive account of it. Anything
# else brings in members the body does not list.
NO_INHERITANCE = frozenset({"", "object"})

# `from os import *`, which is what makes a Python module's own text an
# incomplete account of its namespace.
STAR_IMPORT = re.compile(r"^[ \t]*from[ \t]+[\w.]+[ \t]+import[ \t]+\*", re.MULTILINE)

# Any identifier-shaped word, used only to prove a name *absent*. Being
# generous here is the safe direction: a name the file so much as
# mentions is one this method declines to date.
WORD = re.compile(r"[A-Za-z_]\w*")

# Any identifier-shaped string literal in a C file, which is how every
# name a C module binds has to be written down.
C_STRING = re.compile(r'"(?P<name>[A-Za-z_]\w*)"')


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def builtin_source(version: str) -> Path | None:
    """Where one release keeps `bltinmodule.c`.

    0.9.1 puts every C file in a flat `src/` and 1.0 onward split the
    tree into `Python/`, `Objects/` and `Modules/`, so this searches
    rather than assuming a layout.
    """
    root = source_root(version)
    if not root.exists():
        return None
    return next(root.rglob(BUILTIN_SOURCE), None)


@cache
def builtins_in(version: str) -> frozenset[str]:
    """Every builtin one release's interpreter registers."""
    path = builtin_source(version)
    if path is None:
        return frozenset()
    table = BUILTIN_TABLE.search(path.read_text(errors="ignore"))
    if table is None:
        return frozenset()
    return frozenset(match["name"] for match in TABLE_ENTRY.finditer(table["body"]))


@cache
def module_paths(version: str) -> dict[str, Path]:
    """The Python modules one release ships, and the file for each.

    Only the `.py` files in the library directory, and deliberately not
    the C extensions. A file in `Lib/` is importable in every build of
    that release, so presence and absence both mean something, which is
    the same exhaustive-list argument the builtins table gets.

    A C extension is not like that. `Modules/Setup` decides which ones
    get compiled, and plenty of standard modules ship commented out:
    `curses`, `syslog` and `termios` are all in the 1.1 tarball and none
    of them is in its default build. Reading the tarball alone credits a
    release with modules it could not import, and filtering on `Setup`
    overcorrects, because `select` is documented in 1.0 and commented
    out there too. Which build you had decided the answer, so the
    tarball cannot settle it and the archives keep those modules.
    """
    root = source_root(version)
    if not root.exists():
        return {}

    found: dict[str, Path] = {}
    for name in LIBRARY_DIRS:
        for directory in sorted(root.rglob(name)):
            if any(part.lower() in NOT_LIBRARY for part in directory.parts):
                continue
            for path in sorted(directory.glob("*.py")):
                found.setdefault(path.stem, path)
    return found


@cache
def module_files(version: str) -> dict[str, str]:
    """The same, as the paths the evidence cites."""
    return {
        module: cite(version, path) for module, path in module_paths(version).items()
    }


def modules_in(version: str) -> frozenset[str]:
    return frozenset(module_paths(version))


def cite(version: str, path: Path) -> str:
    """A path relative to the release, the way its evidence records it.

    One level below the cache directory is the tarball's own top
    directory, which is not worth repeating in every citation.
    """
    return str(path.relative_to(source_root(version))).split("/", 1)[-1]


def unconditional(text: str) -> str:
    """The lines of a C file that no `#if` can compile out.

    0.9.1 keeps `{"fmod", math_fmod}` inside an `#if 0`, and every
    platform-dependent module guards its members with `#ifdef`. A row
    that a build may drop cannot prove a release had that member, so
    those lines are blanked rather than read.

    Blanking rather than deleting is what keeps this honest in the other
    direction: the guarded name is still in the text the absence check
    reads, so a member this cannot prove present is also one it refuses
    to call missing. Line count is preserved so the two views of a file
    line up.
    """
    depth = 0
    kept = []
    for line in text.splitlines():
        directive = CONDITIONAL.match(line)
        if directive is not None:
            depth = (
                max(0, depth - 1) if directive["directive"] == "endif" else depth + 1
            )
            kept.append("")
        else:
            kept.append("" if depth else line)
    return "\n".join(kept)


@cache
def c_files(version: str) -> tuple[Path, ...]:
    """Every C file in one release's interpreter."""
    root = source_root(version)
    if not root.exists():
        return ()
    return tuple(
        path
        for path in sorted(root.rglob("*.c"))
        if not any(part.lower() in NOT_INTERPRETER for part in path.parts)
    )


def _read(path: Path) -> str:
    return path.read_text(errors="ignore")


@cache
def c_module_files(version: str) -> dict[str, str]:
    """The C modules one release implements, and the file for each.

    Keyed on the name in the registration call, which is the only place
    a C module's import name is written down: the file is
    `mathmodule.c`, the function is `initmath()`, and only
    `initmodule("math", ...)` says `math`.
    """
    found: dict[str, str] = {}
    for path in c_files(version):
        for match in MODULE_INIT.finditer(_read(path)):
            found.setdefault(match["name"], cite(version, path))
    return found


@cache
def _c_module_members(version: str) -> dict[str, frozenset[str]]:
    """What each C module in one release provably binds.

    Two things count. The method table the registration call names is
    exhaustive in the way `builtin_methods[]` is: it is the list the
    module registers its functions from rather than a description of
    one. And a constant or an exception is bound by a call that spells
    the name out as a string literal.

    The table is looked up by name rather than matched loosely, because
    `{"name", func}` is ordinary C that appears in every method table in
    the tree, and reading the wrong one collects a neighbouring module's
    members.
    """
    found: dict[str, set[str]] = {}
    for path in c_files(version):
        text = unconditional(_read(path))
        bound = {match["name"] for match in MODULE_BINDING.finditer(text)}
        for match in MODULE_INIT.finditer(text):
            members = found.setdefault(match["name"], set()) | bound
            table = re.search(
                rf"\b{re.escape(match['table'])}\s*\[\s*\]\s*=\s*\{{(?P<body>.*?)^\}};",
                text,
                re.DOTALL | re.MULTILINE,
            )
            if table is not None:
                members |= {row["name"] for row in TABLE_ENTRY.finditer(table["body"])}
            found[match["name"]] = members
    return {name: frozenset(members) for name, members in found.items()}


def _bound(text: str) -> frozenset[str]:
    """Every name one Python file binds at the top level."""
    found = set()
    for match in PY_BINDING.finditer(text):
        if match["imported"] is not None:
            found |= {name["name"] for name in IMPORTED.finditer(match["imported"])}
        else:
            found.add(match["function"] or match["klass"] or match["name"])
    return frozenset(found)


@cache
def _python_module_members(version: str) -> dict[str, frozenset[str]]:
    """What each Python module in one release binds at the top level."""
    return {
        module: _bound(_read(path)) for module, path in module_paths(version).items()
    }


def _body_of(text: str, header: re.Match) -> str:
    """One class statement's body, as text."""
    rest = text[header.end() :]
    ends = AFTER_CLASS.search(rest)
    return rest[: ends.start()] if ends else rest


def _body_indent(body: str) -> str | None:
    """The indent a class body's own statements sit at.

    Taken from the first line rather than the smallest indent found,
    because the smallest indent would let a `def` nested inside an `if`
    count as the body's when it is the only one there. A docstring gives
    the right answer as readily as a method does, being at the same
    indent and not a binding.
    """
    for line in body.splitlines():
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            return line[: len(line) - len(stripped)]
    return None


def _class_bound(body: str) -> frozenset[str]:
    """Every name a class body binds directly.

    Only at the body's own indent. Anything deeper belongs to a method,
    or sits inside an `if` the release may not take, and a conditional
    binding is not one the source binds outright.
    """
    indent = _body_indent(body)
    if indent is None:
        return frozenset()
    found = set()
    for match in CLASS_MEMBER.finditer(body):
        if match["indent"] != indent:
            continue
        if match["targets"] is not None:
            found |= {target.strip() for target in match["targets"].split("=")}
        else:
            found.add(match["function"] or match["klass"])
    return frozenset(found)


@cache
def _python_classes(version: str) -> dict[str, tuple[str, frozenset[str]]]:
    """`{"module.Class": (bases, members)}` for one release's library.

    Read from `Lib/*.py` with a regex rather than with `ast`, for the
    reason the rest of this file is regexes: a 3.14 parser cannot read
    a 1.5 tarball, where `print` is a statement and `except E, e:` is
    how exceptions are caught.
    """
    found: dict[str, tuple[str, frozenset[str]]] = {}
    for module, path in module_paths(version).items():
        text = _read(path)
        for header in CLASS_HEADER.finditer(text):
            bases = (header["bases"] or "").strip()
            found[f"{module}.{header['name']}"] = (
                bases,
                _class_bound(_body_of(text, header)),
            )
    return found


@cache
def class_members_in(version: str) -> dict[str, frozenset[str]]:
    """Every `module.Class.member` one release's library binds, by class."""
    return {owner: members for owner, (_, members) in _python_classes(version).items()}


@cache
def closed_classes(version: str) -> frozenset[str]:
    """Classes whose own body is the whole of their namespace.

    This is `open_modules` one level down, and the same argument decides
    it. A class that inherits gets members its body does not list, so
    absence from the body says nothing; a class that inherits from
    nothing is written down in full, so absence is proof.

    `unittest.TestCase` is the case that earns it: `class TestCase:`
    with no bases in every release from 2.1 to 2.5, so 2.2 provably
    lacks `assertAlmostEqual` and 2.3 provably has it.
    """
    return frozenset(
        owner
        for owner, (bases, _) in _python_classes(version).items()
        if all(base.strip() in NO_INHERITANCE for base in bases.split(","))
    )


@cache
def members_in(version: str) -> dict[str, frozenset[str]]:
    """Every `module.member` one release provably binds, by module.

    A module can be written both ways at once, so the two extractions
    are merged rather than one preferred: 1.1 ships `Lib/string.py` and
    `Modules/stropmodule.c`, and the members of `string` are what the
    Python file binds.
    """
    merged = dict(_c_module_members(version))
    for module, members in _python_module_members(version).items():
        merged[module] = merged.get(module, frozenset()) | members
    return merged


@cache
def open_modules(version: str) -> frozenset[str]:
    """Modules whose own text is not the whole of their namespace.

    A Python module that star-imports is the case that matters, and it
    is common in this era: `os.py` is `from posix import *` and almost
    nothing else, so `os.getcwd` appears nowhere in it. Absence from a
    file like that says nothing at all, so these modules can only ever
    tighten a floor and never date anything.
    """
    return frozenset(
        module
        for module, path in module_paths(version).items()
        if STAR_IMPORT.search(_read(path))
    )


@cache
def _python_words(version: str, module: str) -> frozenset[str]:
    """Every word in one Python module's file."""
    path = module_paths(version).get(module)
    if path is None:
        return frozenset()
    return frozenset(match.group() for match in WORD.finditer(_read(path)))


@cache
def _c_words(version: str) -> frozenset[str]:
    """Every identifier-shaped string literal in one release's C sources.

    Deliberately the whole tree rather than one module's file. A C
    module's dict can be written to from anywhere in the interpreter:
    `sys.ps1` is set in `pythonmain.c`, `sys.last_traceback` in
    `traceback.c`, and `sys.exc_type` in `ceval.c`. Scoping the absence
    check to `sysmodule.c` would report all three as missing from a
    release that has them.

    Reading every file costs yield rather than correctness. A member
    whose name happens to be a string literal somewhere else in the tree
    is one this method declines to date, which is the direction to err
    in.
    """
    return frozenset(
        match["name"]
        for path in c_files(version)
        for match in C_STRING.finditer(_read(path))
    )


def mentions(version: str, module: str, member: str) -> bool:
    """Whether a release's source so much as names `module.member`.

    This is the absence half of the method, and it is deliberately
    credulous: it answers "is there any sign of this name?" rather than
    "is this name bound?". Only a member no reading of the source can
    find is treated as one the release did not have.
    """
    if member in _python_words(version, module):
        return True
    return module in c_module_files(version) and member in _c_words(version)


def _diff(
    readable: list[str],
    present: dict[str, frozenset[str]],
    cited: Callable[[str, str], str],
) -> dict[str, dict[str, str]]:
    """Chain a per-release name list into dates and floors.

    Whatever is in the oldest readable release can only be bounded;
    anything appearing later is dated by the release that lacks it.
    Every record cites the file it was read from, since that is what
    makes it checkable.
    """
    baseline, *rest = readable
    seen = set(present[baseline])
    dated: dict[str, dict[str, str]] = {
        name: {"file": cited(baseline, name), "floor": baseline}
        for name in sorted(seen)
    }

    previous = baseline
    for version in rest:
        for name in sorted(present[version] - seen):
            dated[name] = {
                "file": cited(version, name),
                "added": version,
                "absent_in": previous,
                "present_in": version,
            }
        seen |= present[version]
        previous = version
    return dated


@cache
def rewritten_in_python() -> frozenset[str]:
    """Modules that were a C extension before they were a `.py` file.

    A `Lib/` file arriving is only a module arriving if the module was
    never anything else. `socket` was a C extension until 1.6 wrapped it
    in `Lib/socket.py`, and `struct` until 2.4, so reading the library
    directory alone dates both of them by when they were rewritten.
    Those are left to the archives entirely rather than dated from a
    move between two things this can read.
    """
    return frozenset().union(*(c_module_files(v) for v in SOURCE_ORDER))


@cache
def dated_modules() -> dict[str, dict[str, str]]:
    """First source release each module ships in.

    Same record shape as `modindex.dated_modules`, and a stronger
    verdict for the era it covers: that one dates documentation and
    this dates the tarball.
    """
    written_in_c = rewritten_in_python()
    present = {version: modules_in(version) - written_in_c for version in SOURCE_ORDER}
    readable = [version for version in SOURCE_ORDER if present[version]]
    return _diff(readable, present, module_file) if readable else {}


@cache
def dated_builtins() -> dict[str, dict[str, str]]:
    """First source release each builtin appears in.

    The record shape matches `modindex.dated_builtins` so that either
    can answer the same question: an `added` with the release that lacks
    it for anything the diff catches, and a `floor` for anything already
    in the oldest release there is.

    A release whose source is not cached is skipped rather than read as
    empty, so a missing tarball never looks like a mass removal.
    """
    present = {version: builtins_in(version) for version in SOURCE_ORDER}
    readable = [version for version in SOURCE_ORDER if present[version]]
    return _diff(readable, present, builtin_file) if readable else {}


def _datable(previous: str, module: str, member: str) -> bool:
    """Whether a release can be shown *not* to have `module.member`.

    This is the whole of the tiering, and it is what the rest of the
    method rests on. A hard date is a claim that the older release
    lacked the member, and only an exhaustive account of a module's
    namespace can support one.

    A C module has that account. Every name it binds is a row in the
    method table the registration call names, or a string literal in a
    call that inserts it, so a name that appears nowhere is a name the
    module did not have.

    A Python module that star-imports does not, which is why the tier is
    decided per module rather than per language. `os.py` is little more
    than `from posix import *`, so `os.getcwd` is nowhere in it and
    reading its absence as a date would be an invented answer.
    """
    return module not in open_modules(previous) and not mentions(
        previous, module, member
    )


def _datable_class_member(previous: str, owner: str, member: str) -> bool:
    """Whether a release can be shown *not* to have `owner.member`.

    The same tiering as `_datable`, decided per class rather than per
    module. A class that inherits gets members its own body does not
    list, so absence from the body is no account of the class at all; a
    class that inherits from nothing is written down in full.

    The credulous half is unchanged and is read over the whole module
    file rather than the class body, for the reason `mentions` gives:
    a name the file so much as says is one this declines to date. That
    costs yield and not correctness, and it covers the shapes the body
    reader deliberately skips, a `def` inside an `if` above all.
    """
    if owner not in closed_classes(previous):
        return False
    return not mentions(previous, owner.rpartition(".")[0], member)


@cache
def dated_members() -> dict[str, dict[str, str]]:
    """First source release each member can be shown in, by dotted name.

    A member of a module, and a member of a class inside one. The two
    are chained together rather than kept apart because everything
    downstream reads this by dotted name and neither `dating.py` nor the
    index has to care which it got: `os.getcwd` and
    `unittest.TestCase.assertAlmostEqual` are one question asked twice.

    Presence is read strictly and absence generously, so the two halves
    of the answer are not symmetric. A member counts as present only
    where the source binds it outright, and counts as absent only where
    no reading of the source finds the name at all. Anything in between
    produces a floor.

    That is the difference between this and `modindex.dated_members`,
    which only ever emits floors. A doc build indexes whatever share of
    a release it happened to paginate, so its absences are meaningless.
    A module's own implementation is the thing itself, and so is a
    class's own body where the class inherits nothing.
    """
    readable = [version for version in SOURCE_ORDER if members_in(version)]
    if not readable:
        return {}

    baseline = readable[0]
    dated: dict[str, dict[str, str]] = {}
    previous = baseline
    for version in readable:
        for owner, module, members, datable in _owners_in(version):
            for member in sorted(members):
                name = f"{owner}.{member}"
                if name in dated:
                    continue
                where = {"file": module_file(version, module)}
                if version != baseline and datable(previous, owner, member):
                    dated[name] = where | {
                        "added": version,
                        "absent_in": previous,
                        "present_in": version,
                    }
                else:
                    dated[name] = where | {"floor": version}
        previous = version
    return dated


def _owners_in(
    version: str,
) -> Iterator[tuple[str, str, frozenset[str], Callable[[str, str, str], bool]]]:
    """Each namespace one release can be read for, with its absence rule.

    The module is carried alongside the owner rather than derived from
    it, because the two are only sometimes the same and splitting a
    dotted name cannot tell which case it is: `os.path` is a module and
    `unittest.TestCase` is a class, and both cite `Lib/os.py` and
    `Lib/unittest.py` respectively. A class is read out of the module
    that holds it, so a reviewer goes to the same file for either
    answer.
    """
    for module, members in sorted(members_in(version).items()):
        yield module, module, members, _datable
    for owner, members in sorted(class_members_in(version).items()):
        yield owner, owner.rpartition(".")[0], members, _datable_class_member


def module_file(version: str, module: str) -> str:
    """The file one release implements a module in.

    The evidence is only checkable if it says where to look, and the
    answer differs by era and by module: `Lib/bisect.py` for a Python
    module and `Modules/mathmodule.c` for a C one.
    """
    found = module_files(version).get(module) or c_module_files(version).get(module)
    if found is None:
        raise LookupError(f"{module} is not in the {version} source")
    return found


def builtin_file(version: str, name: str = "") -> str:
    """The file one release registers its builtins in.

    Always `bltinmodule.c`, and never in the same place twice: 0.9.1
    keeps every C file in a flat `src/` and 1.0 onward split the tree
    up. The name is taken and ignored so that this and `module_file` can
    be passed to the same diff.
    """
    del name
    path = builtin_source(version)
    if path is None:
        raise LookupError(f"the {version} source has no {BUILTIN_SOURCE}")
    return cite(version, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", help="only names added in this release")
    parser.add_argument("--grep", help="only names containing this")
    parser.add_argument(
        "--modules", action="store_true", help="report modules instead of builtins"
    )
    parser.add_argument(
        "--members", action="store_true", help="report module members instead"
    )
    args = parser.parse_args()

    if args.members:
        dated = dated_members()
    elif args.modules:
        dated = dated_modules()
    else:
        dated = dated_builtins()
    if not dated:
        raise SystemExit("No cached source releases. Run: just fetch-docs")

    if args.version:
        names = sorted(n for n, r in dated.items() if r.get("added") == args.version)
        for name in names:
            print(name)
        print(f"\n{len(names)} builtins added in {args.version}")
        return 0

    for name, record in sorted(dated.items()):
        if args.grep and args.grep not in name:
            continue
        where = record.get("added") or f"{record['floor']} or earlier"
        print(f"{name:<20} {where}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
