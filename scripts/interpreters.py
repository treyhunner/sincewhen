#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.14"
# dependencies = []
# ///
"""Ask the old interpreters themselves what each release could import.

Every other method in this pipeline reads a description of Python: a doc
build, an inventory, a method table, a grammar. This one reads Python.
It builds each release from the tarball already pinned in the corpus and
asks the resulting interpreter whether a name resolves.

That is the only way to settle what is left. The source method stops
where the source stops being an exhaustive list of what a release bound,
and everything it cannot answer has the same shape: `os.py` star-imports
from `posix`, `operator`'s members come out of a stringifying macro,
`types.FrameType` is bound inside a `try`, and `errno`'s members are each
behind an `#ifdef`. None of those can be read off the text. All of them
can simply be asked.

It is also the only method that can speak for a C extension module at
all. `Modules/Setup` decides what gets compiled, so the tarball cannot
say what a release could import, which is why `source.py` leaves C
modules to the archives and the archives can only ever bound them. A
built interpreter answers directly: `operator` is importable in 1.4 and
not in 1.3, so the members the archives could only call "1.5 or earlier"
have a real date under them.

Why it reaches past 2.5
-----------------------

Because the modern half of the dataset had no cross-check at all. 634
entries are dated by `objects.inv`, and 365 of those are 3.0 to 3.7,
where the inventory is the only source that speaks. Its failure mode is
silent and documented: it dates *documentation*. `platform` shipped in
2.3 and was documented in 2.4. `hashlib.sha3_256` shipped in 3.6 and was
given its own inventory entry in 3.11. Both were caught by accident.

So the same question is asked of 2.6 through 3.14 as of 0.9 through 2.5,
and the timeline is one continuous mask rather than two. That is not
tidiness: `added` is defined as the oldest release a feature has been
available in *ever since*, ignoring 3.0 and 3.1, and a mask that spans
the whole history computes precisely that. `argparse` is present in 2.7,
absent from 3.0 and 3.1, present from 3.2, and the answer is 2.7.

2.6 and 2.7 are built for the same reason the mask is continuous. Without
them the timeline has a hole either side of the Python 3 split, and a
name that arrived in 2.6 reads as a 3.0 addition.

What the answer means, precisely
--------------------------------

This method reports **what a default build of that release does in the
environment `interpreters.dockerfile` pins**, which is a narrower claim
than the other five make and has to be read as such.

- **A default build.** `Modules/Setup.in` as the release shipped it, with
  no modules enabled or disabled by hand. Where a release's own `Setup`
  says a system may need an extra library, that is configuration rather
  than modification: 1.1 through 1.4 ship `crypt cryptmodule.c #
  -lcrypt  # crypt(3); needs -lcrypt on some systems`, and this is one of
  those systems.
- **In a pinned environment.** An extension is built only if its library
  is there, so the library list in the Dockerfile is part of the claim.
  That is why it is committed rather than inherited from whatever the
  host had installed.
- **A platform answer for a platform-guarded name.** `errno.EACCES` is
  behind an `#ifdef`, so what a build settles is "available on Linux",
  not the portable availability the dataset claims. Those stay out until
  the schema can say it.

Why the pre-1.5 releases are built 32-bit
-----------------------------------------

Because 64-bit answers were wrong, silently, in the only direction that
matters. These releases were written when `int`, `long` and a pointer
were all 32 bits, and 1.0 and 1.1 pass `va_list *` around in
`modsupport.c`, which the x86-64 ABI does not allow: `va_list` is an
array type there, so `&va` is not the pointer the callee reads. Built
64-bit, `chr()` segfaults. `string.py` calls `chr()` at import time, so
`import string` takes the interpreter down, and every module after it
reports absent.

A false absence is the worst thing this file can produce, so the K&R era
is built for the architecture it was written for and the question does
not arise. 1.2 through 1.4 survive a 64-bit health check, but they share
that era's argument-parsing code, so passing a ten-item battery is luck
rather than proof and they are built 32-bit too.

The patches
-----------

Two collisions between 1990s C and a 2020s toolchain, each recorded in
the table so a claim can be audited:

- `getline` was Python's own function in `Objects/fileobject.c` until
  glibc added one in 2008. Renaming Python's is a one-file, whole-word
  change and touches no behaviour. Dustin Ingram's `vintage-python`
  images, derived independently, carry the same two fixes, which is a
  useful check that this is the minimum rather than a preference.
- `crypt` moved out of libc, so the link needs `-lcrypt`.

Nothing else is edited. `-std=gnu89` and a silenced warning list are what
let K&R declarations through a compiler that defaults to C17, and
`-U_FORTIFY_SOURCE` is what keeps 2.3 and 2.4 from aborting at startup.

Why the table is committed
--------------------------

Building thirty-one interpreters needs Docker and the better part of an
hour, and the rest of this pipeline is offline and quick. So the build is
an occasional manual step and its *result* is the artifact:
`scripts/interpreters.json` records, for every name, which releases
resolved it. Downstream reads the table and never needs a compiler, which
keeps `verify-dataset` and CI exactly as reproducible as they were.

Usage:

    uv run scripts/interpreters.py --build          # build all of them
    uv run scripts/interpreters.py --build 1.4 3.3  # or just these
    uv run scripts/interpreters.py --probe          # write the table
    uv run scripts/interpreters.py --report         # what it dates
    uv run scripts/interpreters.py --grep operator
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from datetime import date
from functools import cache
from pathlib import Path

from annotations import dated_releases
from source import c_module_files, module_paths
from sources import (
    CACHE,
    MODERN_BUILDS,
    ROOT,
    SOURCE_BUILDS,
    source_archive_path,
    source_root,
)

# Every release with a pinned source tarball, oldest first: 0.9.1 through
# 3.14. The two halves are built differently and read the same, so they
# are named separately and concatenated once.
#
# The old half is the era the Sphinx inventories cannot reach. The new
# half is the era where they are the only thing that speaks, which is a
# different problem with the same answer.
LEGACY_RELEASES = tuple(SOURCE_BUILDS)
MODERN_RELEASES = tuple(MODERN_BUILDS)
RELEASES = LEGACY_RELEASES + MODERN_RELEASES

# Where `print` and `exec` stop being statements and become names a probe
# can ask about. The line the *dialect* moves on is drawn elsewhere and
# one release earlier, at 2.6, and follows the corpus halves rather than
# any change in the language. See `_say`.
PYTHON_3_FROM = "3.0"

# Python 3.0 and 3.1 do not count against continuity, which is the
# dataset's own rule and not this file's: nobody shipped code on either,
# so a feature present in 2.7 and again in 3.2 has been available since
# 2.7. `dating.FIRST_REAL_PYTHON_3` is the same decision one level up.
FORGIVEN = frozenset({"3.0", "3.1"})

# The oldest 3.x release the dataset counts, which is the same decision
# one level up as `dating.FIRST_REAL_PYTHON_3`.
FIRST_REAL_PYTHON_3 = "3.2"

PYTHONS = CACHE / "pythons"
BUILD = PYTHONS / "build"
INSTALL = PYTHONS / "inst"
LOGS = PYTHONS / "log"

TABLE = ROOT / "scripts" / "interpreters.json"
DATASET = ROOT / "src" / "sincewhen" / "features.toml"

# One image per era, and the legacy one is never touched. Its id is part
# of the provenance of every answer the old half of the table gives, so
# adding a library a 2011 release wants would quietly invalidate what
# compiled a 1991 one.
DOCKERFILES = {
    "legacy": ROOT / "scripts" / "interpreters.dockerfile",
    "modern": ROOT / "scripts" / "interpreters-modern.dockerfile",
}
IMAGES = {
    "legacy": "sincewhen-interpreters",
    "modern": "sincewhen-interpreters-modern",
}
DOCKERFILE = DOCKERFILES["legacy"]
IMAGE = IMAGES["legacy"]

# What the table writes per release. Every release in the corpus answers
# or the table is not written, so there is no third state: a release that
# could not be asked is not a release that said no.
PRESENT = "#"
ABSENT = "."

# Printed as the last statement of a probe, so that "resolved nothing" can
# be told apart from "died part way through".
FINISHED = "PROBE-FINISHED"

# Words that were statements before Python 3, so a probe cannot spell
# them as names there. `print` is the one the dataset actually contains,
# and `exec` is here because it is the same shape: both are keywords
# through 2.7, so `_ = print` is a syntax error rather than a lookup that
# fails. From 3.0 they are ordinary names and get asked about normally,
# which is the point: `print` as a function is a thing to date.
RESERVED = frozenset({"print", "exec"})

# gcc defaults to C17 and these releases are K&R. `-std=gnu89` restores
# the old rules, and the warnings being silenced are all of one kind:
# declarations these releases never wrote because nothing required them
# yet. `-fwrapv` and `-fno-strict-aliasing` are the two assumptions
# modern gcc makes that pre-standard C does not.
KR_FLAGS = "-O -std=gnu89 -w -fno-strict-aliasing -fwrapv -fcommon -U_FORTIFY_SOURCE"
ANSI_FLAGS = "-O2 -w -fno-strict-aliasing -fwrapv -U_FORTIFY_SOURCE"

# 1.5 is where the tree stops needing the old C rules.
ANSI_FROM = "1.5"

# Built for i386, because 64-bit makes them answer wrongly. See the
# module docstring: this is not a preference, it is `chr()` segfaulting.
THIRTY_TWO_BIT = frozenset({"0.9", "1.0", "1.1", "1.2", "1.3", "1.4"})

# 0.9.1 has no `configure` and no install target: a hand-edited
# `src/Makefile` builds it, and the library is wherever it was unpacked.
NO_CONFIGURE = frozenset({"0.9"})

# `getline` was Python's until glibc claimed the name in 2008. Confined
# to one file in each of these, and gone by 1.6.
RENAME_GETLINE = frozenset({"1.0", "1.1", "1.2", "1.3", "1.4", "1.5"})

# `crypt` left libc, so the module needs the `-lcrypt` its own `Setup`
# line already suggests. 1.5 on, `configure` works this out.
LINK_CRYPT = frozenset({"1.1", "1.2", "1.3", "1.4"})

# These install the interpreter and the library under separate targets,
# and `make install` alone leaves an interpreter with no stdlib at all.
LIBINSTALL = frozenset({"1.0", "1.1", "1.2", "1.3"})

# Where 0.9.1 keeps its library, relative to the unpacked tarball.
LEGACY_LIB = "lib"

# `configure` names the platform from `uname`, so on a 6.x kernel it asks
# for `Lib/plat-linux6`, which no release in this corpus ships. 2.2 then
# tries to generate one by running `h2py.py` over the host's headers, and
# fails outright.
#
# Presetting `MACHDEP` looks like the fix and is a trap: `configure`
# computes `ac_sys_system` *inside* `if test -z "$MACHDEP"`, so presetting
# it leaves that empty, the `Linux*)` case that sets
# `LDSHARED='gcc -shared'` never matches, and every extension module then
# fails to link against a bare `ld`. That loses `math` and `time`, which
# is a silent catastrophe rather than a build error.
#
# So `configure` is left alone and the directory it wants is supplied
# from the one the release shipped. That is the faithful answer anyway:
# these are the platform constants as released, rather than ones
# regenerated from 2020s headers.
PLATFORM_DIRS = "plat-linux*"

# Where this distribution keeps its libraries, which is not where a 2005
# `setup.py` looks. Multiarch arrived in 2009, so `lib_dirs` is `/lib`,
# `/usr/lib` and a couple of `../lib` guesses, and 2.5 does not merely
# skip a library it cannot find: having found `sqlite3.h`, it calls
# `os.path.dirname(None)` and raises, which fails `make sharedmods` and
# loses *every* shared extension including `math` and `time`.
#
# `setup.py` reads `LDFLAGS` back out of the generated Makefile and adds
# its `-L` paths to the search, so this is the supported way to say it.
MULTIARCH_LIBS = "-L/usr/lib/x86_64-linux-gnu"

# The releases whose extensions are built by `setup.py` rather than
# entirely by `Modules/Setup`.
SETUP_PY_FROM = "1.6"

# Added to whatever `configure` computes for the modern half, and to
# nothing else. CPython's own `configure` adds this flag when it believes
# the compiler needs it, and modern gcc talks it out of it: the probe
# answers "checking whether gcc accepts and needs -fno-strict-aliasing...
# no", on the stated grounds that Python does not violate aliasing rules
# and that only older compilers warned about it. Built 3.2 disagrees and
# segfaults before it can print anything, so the flag goes back.
#
# This is the same kind of concession as `-U_FORTIFY_SOURCE` on the old
# half, and the health battery is what turned it from a silent empty
# column into a build that refused to be believed.
NO_STRICT_ALIASING = "-fno-strict-aliasing"

# 0.9.1 spells equality `=` and inequality `<>`; `==` is not in its
# grammar. Only the health check compares anything, so this is the only
# place it matters.
OLD_EQUALITY = frozenset({"0.9"})

# What a working interpreter has to get right before its answers are
# believed. Each is a value check rather than a "did it raise", because
# the failure being guarded against is a miscompiled build that returns
# nonsense or dies, not a missing feature. `{eq}` is the era's equality
# operator, and a condition that needs no equality does not use it.
#
# Every one of these exists in all fourteen releases, which is the whole
# point: a failure here is a broken build rather than history. Getting
# that wrong makes the check useless in both directions, and two drafts
# of it did:
#
# - `int('42')` looks like a fine check and is not. Converting a string
#   with `int()` arrived in 1.5, and `string.atoi` was the way before it.
# - `os.getcwd` is worse, because 0.9.1 has no `os` module at all. Its
#   library is `posix` and nothing else, which is itself the kind of fact
#   this oracle exists to find.
HEALTH = (
    ("chr", (), "chr(65) {eq} 'A'"),
    ("ord", (), "ord('A') {eq} 65"),
    ("len", (), "len('abc') {eq} 3"),
    ("divmod", (), "divmod(7, 2) {eq} (3, 1)"),
    ("math.sqrt", ("import math",), "math.sqrt(4.0) {eq} 2.0"),
    ("string.upper", ("import string",), "string.upper('hi') {eq} 'HI'"),
    ("posix.getcwd", ("import posix",), "len(posix.getcwd()) > 0"),
    ("time.time", ("import time",), "time.time() > 1.0"),
)

# The same battery for the modern half, which has to differ in both
# directions. `string.upper` is a 2.x function and there is nothing to
# put in its place, while `int('42')` and `repr` are checks the old half
# cannot make: converting a string with `int()` arrived in 1.5.
#
# `repr(1)` is here for a different reason from `int('42')`: `repr` is a
# builtin from 1.0, so 0.9 is what would fail it.
#
# The interesting addition is the last one. Every release from 2.6 on
# installs into its own prefix under a name that includes its version,
# and this half has seventeen of them, so "the binary this found is the
# release it was asked about" stops being obvious. A build that answered
# for the wrong release would be indistinguishable from history.
MODERN_HEALTH = (
    ("chr", (), "chr(65) {eq} 'A'"),
    ("ord", (), "ord('A') {eq} 65"),
    ("len", (), "len('abc') {eq} 3"),
    ("divmod", (), "divmod(7, 2) {eq} (3, 1)"),
    ("int", (), "int('42') {eq} 42"),
    ("repr", (), "repr(1) {eq} '1'"),
    ("math.sqrt", ("import math",), "math.sqrt(4.0) {eq} 2.0"),
    ("posix.getcwd", ("import posix",), "len(posix.getcwd()) > 0"),
    ("time.time", ("import time",), "time.time() > 1.0"),
    # Split twice rather than compared as a prefix, because neither
    # shortcut survives the corpus: 2.6 reports itself as "2.6" with no
    # micro at all, so a `2.6.` prefix never matches, and a bare `3.1`
    # prefix matches 3.10 as happily as 3.1.
    (
        "sys.version",
        ("import sys",),
        "sys.version.split()[0].split('.')[:2] {eq} {parts}",
    ),
)

# The matcher fields whose masks may date an *addition*, and what one is
# called in the table. Anything else in the dataset is syntax, which the
# grammar already settles.
DATING_KINDS = {"modules": "module", "builtins": "builtin", "attributes": "attribute"}

# Everything the probe asks about, which is those three and one more.
#
# A method of a builtin type is asked for by its unbound spelling, `_ =
# dict.has_key`, and that spelling answers the removal question and not
# the addition one. `dict` the builtin arrived in 2.2 while the `dict`
# type is in 0.9.1, so this column dates `dict.keys` to 2.2 where the
# type's own method table says 0.9, and the method table is right about
# what the dataset claims: a pre-2.6 method entry is a claim about
# instances, so `{}.keys()` is 0.9 and `dict.keys` as an attribute is
# 2.2.
#
# For a removal the two spellings agree, and they agree for a reason
# rather than by luck: a type that loses a method loses it on instances
# and as an unbound attribute in the same release. The 2.2 divergence
# exists only because `str` and `dict` were not types before then, and
# every removal in this dataset is 3.0 or later.
#
# So this set is probed and `DATING_KINDS` is what `added` is read from.
# `test_the_interpreters_never_date_a_type_method` is the guard, because
# wiring `method` into the addition path produces version numbers rather
# than failures.
KINDS = DATING_KINDS | {"methods": "method"}

# Evidence methods that record a human's decision rather than a derived
# one, so this table has no business overruling them.
OVERRIDES = frozenset({"manual", "pep", "grammar"})

# How many names to ask about in one interpreter run. Small enough that a
# crash costs little and large enough that the per-run overhead of
# `docker run` stays amortised.
BATCH = 100

# What fraction of the corpus a single release may fail to answer before
# its column is treated as a broken build rather than as a measurement.
UNANSWERED_LIMIT = 0.05

# How hard to build the modern half. Left off the old half deliberately:
# see `build`.
JOBS = max(1, (os.cpu_count() or 2) - 1)


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def era(version: str) -> str:
    """Which half of the corpus a release belongs to.

    Everything downstream of a build is shared; everything about making
    one differs. The old half is `Modules/Setup`, K&R C and a 32-bit
    toolchain, the new half is `configure` and `setup.py`, and asking
    each which era it is in beats seventeen special cases.
    """
    return "modern" if version in MODERN_BUILDS else "legacy"


def python_3(version: str) -> bool:
    return version_key(version) >= version_key(PYTHON_3_FROM)


def flags(version: str) -> str:
    """The `OPT` the old half is built with.

    The modern half is given none of this file's own, and asks
    `configure` instead.
    What `configure` computes is by definition what a default build of
    that release uses, so overriding it is a modification rather than a
    setting, and 3.3 is what proves the point: CPython's own `-DNDEBUG`
    is part of that string, and dropping it turns on an `assert` in
    `obmalloc.c` that calls a function only a debug build defines. The
    build fails at the link, which is the lucky version of that mistake.
    """
    if version_key(version) < version_key(ANSI_FROM):
        return KR_FLAGS
    return ANSI_FLAGS


def compiler(version: str) -> str:
    if version in THIRTY_TWO_BIT:
        return "gcc -m32"
    return "gcc"


def build_root(version: str) -> Path:
    return BUILD / version


def install_root(version: str) -> Path:
    return INSTALL / version


def binary(version: str) -> Path | None:
    """The built interpreter for a release, if there is one.

    0.9.1 has no install step, so it is run out of its build tree; every
    later release is run out of its install tree, because what is on
    `sys.path` is that release's own answer rather than one invented
    here.

    Named candidates rather than a glob over `python[0-9]*`, which also
    matches `python3.7-config` and has to be read twice before you can
    convince yourself it sorts a real interpreter first. Python 3
    installs no bare `python` at all, so the versioned name is the usual
    answer there.
    """
    if version in NO_CONFIGURE:
        candidate = build_root(version) / "src" / "python"
        return candidate if candidate.exists() else None
    installed = install_root(version) / "bin"
    for name in ("python", f"python{version}", f"python{version[0]}"):
        candidate = installed / name
        if candidate.exists():
            return candidate
    return None


def ensure_image(which: str = "legacy") -> str:
    """Build one pinned build environment if it is not already here.

    Returns the image id, which goes into the table: it is the closest
    thing to a checksum of "what compiled this".
    """
    image = IMAGES[which]
    dockerfile = DOCKERFILES[which]
    found = subprocess.run(
        ["docker", "images", "-q", image], capture_output=True, text=True
    )
    if not found.stdout.strip():
        print(f"Building the {image} image (once).")
        built = subprocess.call(
            [
                "docker",
                "build",
                "-t",
                image,
                "-f",
                str(dockerfile),
                str(dockerfile.parent),
            ]
        )
        if built != 0:
            raise SystemExit(f"Could not build the {image} build environment.")
        found = subprocess.run(
            ["docker", "images", "-q", image], capture_output=True, text=True
        )
    identifier = found.stdout.strip()
    if not identifier:
        # This is what the table records as "what compiled this", so an
        # empty one is a build with no provenance at all rather than a
        # cosmetic gap.
        raise SystemExit(
            f"Docker reported no id for {image}, so it cannot be recorded."
        )
    return identifier


def _volumes() -> list[str]:
    """The paths a container has to see, mounted where they already are.

    The repository is mounted at its own path rather than somewhere
    tidier, so that a prefix compiled into an interpreter means the same
    thing inside the container and out.

    The cache is mounted separately when it is a symlink out of the tree,
    which is how a worktree shares the 2 GB corpus with its main
    checkout. Mounting only the repository leaves that symlink dangling
    inside the container, and every build then fails to find its own
    tarball. Resolving it and mounting the target keeps the path itself
    valid, so nothing downstream has to know.
    """
    paths = [ROOT]
    resolved = CACHE.resolve()
    if not resolved.is_relative_to(ROOT):
        paths.append(resolved)
    return [argument for path in paths for argument in ("--volume", f"{path}:{path}")]


def _docker(
    command: list[str], cwd: Path, log: Path | None = None, image: str = IMAGE
) -> int:
    """Run a command inside the pinned image, over the real cache.

    Runs as the invoking user, so the cache does not fill up with
    root-owned files.
    """
    invocation = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        *_volumes(),
        "--workdir",
        str(cwd),
        image,
        *command,
    ]
    if log is None:
        return subprocess.call(invocation)
    with log.open("a", encoding="utf-8") as handle:
        handle.write(f"\n$ {' '.join(command)}\n")
        handle.flush()
        return subprocess.call(invocation, stdout=handle, stderr=subprocess.STDOUT)


def _unpack(version: str) -> Path:
    """Unpack a release's pinned tarball into a fresh build tree."""
    tree = build_root(version)
    if tree.exists():
        shutil.rmtree(tree)
    tree.mkdir(parents=True)
    archive = source_archive_path(version)
    if not archive.exists():
        raise SystemExit(
            f"No cached source for {version}. Run: uv run scripts/fetch_docs.py"
        )
    with tarfile.open(archive) as tar:
        # Every tarball in the corpus has a single top-level directory,
        # and its name is spelled four different ways across the era, so
        # strip it rather than trying to predict it.
        root = min(member.name for member in tar.getmembers()).partition("/")[0]
        tar.extractall(tree, filter="tar")
    inner = tree / root
    for child in inner.iterdir():
        shutil.move(str(child), str(tree / child.name))
    inner.rmdir()
    return tree


def _patch(version: str, tree: Path) -> list[str]:
    """Apply the toolchain patches this release needs, and name them."""
    applied = []
    if version in RENAME_GETLINE:
        target = tree / "Objects" / "fileobject.c"
        source = target.read_text(encoding="utf-8", errors="surrogateescape")
        target.write_text(
            re.sub(r"\bgetline\b", "Py_getline", source),
            encoding="utf-8",
            errors="surrogateescape",
        )
        applied.append("renamed Objects/fileobject.c getline to Py_getline")
    if version in LINK_CRYPT:
        setup = tree / "Modules" / "Setup.in"
        source = setup.read_text(encoding="utf-8", errors="surrogateescape")
        setup.write_text(
            re.sub(
                r"(?m)^crypt cryptmodule\.c.*$", "crypt cryptmodule.c -lcrypt", source
            ),
            encoding="utf-8",
            errors="surrogateescape",
        )
        applied.append("enabled the -lcrypt its own Modules/Setup suggests")
    return applied


def _configured_opt(tree: Path) -> str:
    """What `configure` chose, plus the one flag it wrongly leaves out.

    Read back out of the generated Makefile rather than written down
    here, because the whole point of the modern half is that the release
    decides its own optimisation flags. Only the one addition is this
    file's, and only because `configure`'s test for it is a check for a
    bug in a compiler from 2004.
    """
    makefile = tree / "Makefile"
    found = re.search(
        r"(?m)^OPT=\s*(.*)$", makefile.read_text(encoding="utf-8", errors="replace")
    )
    computed = found[1].strip() if found else ""
    return f"{computed} {NO_STRICT_ALIASING}".strip()


def _supply_platform_dir(tree: Path) -> str | None:
    """Give `make` the `Lib/plat-<MACHDEP>` it asks for, if it ships one.

    `make` treats the directory as a target with no prerequisites, so an
    existing one is up to date and the generation step never runs. The
    name is read out of the generated Makefile rather than guessed,
    because it follows the running kernel and this should not care which
    kernel that is.
    """
    makefile = tree / "Makefile"
    if not makefile.exists():
        return None
    found = re.search(
        r"(?m)^MACHDEP=\s*(\S+)", makefile.read_text(encoding="utf-8", errors="replace")
    )
    if found is None:
        return None
    library = tree / "Lib"
    wanted = library / f"plat-{found[1]}"
    if wanted.exists() or not library.exists():
        return None
    shipped = sorted(library.glob(PLATFORM_DIRS))
    if not shipped:
        return None
    # Highest-numbered shipped directory: `plat-linux2` over `plat-linux1`.
    shutil.copytree(shipped[-1], wanted)
    return f"{wanted.name} supplied from {shipped[-1].name}"


def recipe(version: str) -> list[str]:
    """Everything done to this release, for the record in the table."""
    recorded = [*_patch_names(version), f"CC={compiler(version)}"]
    if era(version) == "modern":
        recorded.append(f"OPT as ./configure computed it, plus {NO_STRICT_ALIASING}")
    else:
        recorded.append(f"OPT={flags(version)}")
    if version_key(version) >= version_key(SETUP_PY_FROM):
        recorded.append(f"LDFLAGS={MULTIARCH_LIBS}")
    if era(version) == "modern":
        recorded.append(f"make -j{JOBS}")
    return recorded


def _patch_names(version: str) -> list[str]:
    applied = []
    if version in RENAME_GETLINE:
        applied.append("renamed Objects/fileobject.c getline to Py_getline")
    if version in LINK_CRYPT:
        applied.append("enabled the -lcrypt its own Modules/Setup suggests")
    return applied


def build(version: str) -> Path:
    """Build one release and return its interpreter.

    Serial `make` for the old half: those recursive Makefiles predate
    parallel make and race against themselves, and a `-j` build fails
    looking for a library the sibling directory has not written yet.
    From 2.6 the tree is parallel-safe and there are seventeen of them,
    so that half is built `-j`.
    """
    image = IMAGES[era(version)]
    ensure_image(era(version))
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{version}.log"
    log.write_text(f"# building Python {version}\n", encoding="utf-8")

    tree = _unpack(version)
    for note in _patch(version, tree):
        print(f"  patch: {note}")

    if version in NO_CONFIGURE:
        # No configure, no install: 0.9.1 is built where it stands.
        settings = f"CC={compiler(version)} {flags(version)}"
        _docker(["make", settings], tree / "src", log, image)
    else:
        prefix = install_root(version)
        # Cleared first, because `binary()` finds an interpreter by
        # looking for one: left in place, last run's install would stand
        # in for this run's failure and answer every question wrongly.
        if prefix.exists():
            shutil.rmtree(prefix)
        # `make install` here predates `mkdir -p`, so the prefix has to
        # exist before it tries to create anything underneath.
        for leaf in ("bin", "lib", "include", "man/man1"):
            (prefix / leaf).mkdir(parents=True, exist_ok=True)
        settings = f'CC="{compiler(version)}"'
        if version_key(version) >= version_key(SETUP_PY_FROM):
            settings += f' LDFLAGS="{MULTIARCH_LIBS}"'
        _docker(
            ["sh", "-c", f"{settings} ./configure --prefix={prefix}"],
            tree,
            log,
            image,
        )
        supplied = _supply_platform_dir(tree)
        if supplied:
            print(f"  platform: {supplied}")
        if era(version) == "modern":
            make = ["make", f"-j{JOBS}", f"OPT={_configured_opt(tree)}"]
        else:
            make = ["make", f"OPT={flags(version)}"]
        _docker(make, tree, log, image)
        _docker(["make", "install"], tree, log, image)
        if version in LIBINSTALL:
            _docker(["make", "libinstall"], tree, log, image)

    found = binary(version)
    if found is None:
        raise SystemExit(f"Python {version} did not build. See {log}")
    try:
        _check_health(version, found)
    except SystemExit:
        # Cleared, because `probe()` finds an interpreter by looking for
        # one and has no way to know this build was rejected. Left in
        # place, `--build 3.5` failing and `--probe` running anyway would
        # write a column of absences from an interpreter that was
        # explicitly judged untrustworthy, which is the one thing the
        # unbuilt guard exists to prevent.
        shutil.rmtree(install_root(version), ignore_errors=True)
        raise
    return found


def _say(version: str, message: str) -> str:
    """One line of output, in the only spelling that release accepts.

    `print 'x'` is a syntax error from 3.0, so the two halves cannot
    share one spelling. A single parenthesised string is the same thing
    in both, which is what makes the modern spelling safe for the whole
    of the modern half rather than only from 3.0: what Python 3 changes
    is `print(a, b)`, which prints a tuple before it and two arguments
    after, and the probe never writes one.
    """
    if era(version) == "modern":
        return f"print({message!r})"
    return f"print '{message}'"


def _health_source(version: str) -> str:
    """Python that prints a label per health check it passes."""
    equals = "=" if version in OLD_EQUALITY else "=="
    parts = version.split(".")
    lines = []
    for label, setup, condition in _health_checks(version):
        lines.append("try:")
        lines += [f"    {statement}" for statement in setup]
        filled = condition.format(eq=equals, parts=parts)
        lines.append(f"    if {filled}:")
        lines.append(f"        {_say(version, f'H {label}')}")
        lines.append("except:")
        lines.append("    pass")
    return "\n".join(lines) + "\n"


def _health_checks(version: str) -> tuple[tuple[str, tuple[str, ...], str], ...]:
    return MODERN_HEALTH if era(version) == "modern" else HEALTH


def _check_health(version: str, path: Path) -> None:
    """Refuse to trust an interpreter that gets the basics wrong.

    Two real failures this catches, both of which look exactly like
    evidence rather than like breakage:

    - 1.0 through 1.3 install the library under a separate target, so
      `make install` alone leaves an interpreter that answers "no" to
      every question because it can find nothing.
    - Built 64-bit, 1.0 and 1.1 segfault in `chr()`, which takes
      `import string` down with it and makes a whole release look empty.

    Both once passed a check that only asked whether `string` imported,
    so this asks for right answers instead of for absence of errors.
    """
    checks = _health_checks(version)
    script = PYTHONS / f"health-{version}.py"
    script.write_text(_health_source(version), encoding="utf-8")
    passed = {
        line.removeprefix("H ").strip()
        for line in _interpret(version, path, script).splitlines()
        if line.startswith("H ")
    }
    script.unlink(missing_ok=True)
    missing = [label for label, *_ in checks if label not in passed]
    if missing:
        raise SystemExit(
            f"Python {version} built but fails {', '.join(missing)}, so its "
            f"answers would be worse than none. See {LOGS / f'{version}.log'}"
        )
    print(f"  health: {len(passed)} of {len(checks)} checks pass")


def _interpret(version: str, path: Path, script: Path, timeout: int = 180) -> str:
    """Run one script under one built interpreter, inside the image.

    In the image rather than on the host because the pre-1.5 builds are
    i386 and the host has no 32-bit runtime. Doing every release the same
    way keeps one code path instead of two.

    The environment is deliberately bare. A `PYTHONPATH` or `PYTHONHOME`
    inherited from whoever ran this would put directories on a 1991
    interpreter's search path that no 1991 interpreter had, and the whole
    value of this method is that its answers are that release's own.
    """
    command = []
    if version in NO_CONFIGURE:
        # 0.9.1 was never installed, so it has to be told where its
        # library is, the same way its own README does.
        command += ["env", f"PYTHONPATH={build_root(version) / LEGACY_LIB}"]
    command += [str(path)]
    if era(version) == "modern":
        # No environment and no user site directory, so that nothing on
        # the invoking machine can put a name on a 2008 interpreter's
        # search path. `-I` says exactly this and arrived in 3.4, which
        # is six releases too late to be useful here; `-E -s` is the
        # spelling every release in this half understands.
        #
        # Deliberately not `-S`, which would skip `site.py` and take
        # `help` with it. `help` is a builtin the dataset dates, and
        # `site` is what installs it, so a run without `site` would
        # report it absent from every release.
        command += ["-E", "-s"]
    command += [str(script)]
    invocation = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        *_volumes(),
        "--workdir",
        str(ROOT),
        IMAGES[era(version)],
        *command,
    ]
    try:
        result = subprocess.run(
            invocation, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        return ""
    return result.stdout


def _dataset_names() -> dict[str, set[str]]:
    """Every name in the dataset an interpreter can be asked about."""
    entries = tomllib.loads(DATASET.read_text(encoding="utf-8"))["features"]
    names: dict[str, set[str]] = {label: set() for label in KINDS.values()}
    for entry in entries:
        for field, label in KINDS.items():
            names[label].update(entry.get(field, ()))
    return names


def _probe_source(targets: list[str], version: str = RELEASES[0]) -> str:
    """Python that prints each of `targets` it can resolve.

    Written in the narrowest dialect the corpus shares: `import`,
    `try`/`except`, attribute access and a `print`. No `hasattr`, no
    `getattr`, no `sys.stdout`, and no `==`, because the oldest release
    here predates all of them and this file has to parse under it.

    Two things differ between the halves and both have to. `print 'x'`
    is a syntax error from 3.0, so the statement and the function are
    written per era. And a word that is a keyword in a release cannot be
    spelled as a name there, which moves at 3.0 rather than with the
    halves. Everything else is written once, which is what keeps the two
    halves of the mask comparable rather than two measurements.

    Every lookup is an assignment rather than a bare expression, because
    0.9.1 echoes the value of an expression statement even when running a
    script, and the echo would land in the middle of the results.

    Each name gets one flat block per way it could resolve, rather than
    nested fallbacks, and a name printed twice is simply present.
    """
    lines = []
    for target in targets:
        kind, _, name = target.partition(" ")
        head = name.partition(".")[0]
        if not python_3(version) and RESERVED.intersection(name.split(".")):
            # `_ = print` and `_ = exec` are syntax errors in this era
            # rather than name lookups that fail, and a syntax error takes
            # the whole file down before any `try` can run. A word that
            # cannot be an identifier here cannot be a name these releases
            # resolve, so there is nothing to ask.
            continue
        attempts: list[list[str]] = []
        match kind:
            case "module":
                attempts.append([f"import {name}"])
                if "." in name:
                    # Packages arrived in 1.5, so `import os.path` is a
                    # syntax the four releases before it cannot run even
                    # though they all have `os.path`. Reaching it as an
                    # attribute is what those releases would have done.
                    attempts.append([f"import {head}", f"_ = {name}"])
            case "builtin":
                attempts.append([f"_ = {name}"])
            case "method":
                # The head is a builtin type, so there is nothing to
                # import and only one way to ask. A release that has no
                # such type answers no, which is the right answer:
                # `bytes.hex` is unreachable in 2.5 because `bytes` is.
                attempts.append([f"_ = {name}"])
            case "attribute":
                attempts.append([f"import {head}", f"_ = {name}"])
                # `str.format` has no module to import: the head is a
                # builtin that is simply there.
                attempts.append([f"_ = {name}"])
                parent = name.rpartition(".")[0]
                if parent != head:
                    # `xml.etree.ElementTree.parse` needs the package
                    # that holds it imported before the attribute walk
                    # can reach it, and importing only `xml` binds
                    # nothing.
                    attempts.append([f"import {parent}", f"_ = {name}"])
        for attempt in attempts:
            lines.append("try:")
            lines += [f"    {statement}" for statement in attempt]
            lines.append(f"    {_say(version, f'Y {target}')}")
            lines.append("except:")
            lines.append("    pass")
    # A batch that resolves nothing and a batch that died both come back
    # with no `Y` lines, and they mean opposite things. The oldest
    # releases resolve nothing for most batches, so without a sentinel
    # every one of those looks like a crash and gets retried a name at a
    # time: tens of thousands of interpreter runs instead of hundreds.
    lines.append(_say(version, FINISHED))
    return "\n".join(lines) + "\n"


def _ask(version: str, path: Path, targets: list[str]) -> tuple[set[str], set[str]]:
    """Which of `targets` this interpreter resolves, and which killed it.

    Asked in batches so that an interpreter dying part way through costs
    one batch rather than everything after it, and a batch that dies is
    retried one name at a time so the damage is confined to the name that
    caused it. A single bad name is a real possibility: a `SyntaxError`
    is raised when the file is compiled, before any `try` can catch it,
    so one unparseable name would otherwise silence the whole batch.

    A name still on its own when the interpreter dies is the second half
    of the answer, and conflating it with the first is how a false
    absence gets made. Asking 3.5 for `uuid.NAMESPACE_DNS` segfaults it,
    because that build's `uuid` module crashes on import unless `ctypes`
    happens to have been imported first. "Did not resolve" and "could not
    be asked" are different facts, and only the first is about 3.5.

    That same `uuid` case is why a batch that died taints every absence
    in it, not just the name that killed it. A hundred names share one
    interpreter process, so each is asked in a process the other
    ninety-nine have already mutated, and only *fatal* contamination is
    visible: had `uuid` raised `ImportError` instead of segfaulting, its
    neighbours would have come back cleanly absent and been dated from
    it. So every absence from a batch that died is asked again on its
    own, where nothing else can have run first, and the cost is bounded
    by how many batches died rather than by the size of the corpus.

    A name the probe declines to ask is the third case, and it is not an
    absence either: `print` and `exec` are keywords before 3.0, so
    `_probe_source` cannot spell them and the release never answers.
    Left to fall through, that wrote sixteen leading absences for
    `builtin print` and dated it 3.0 against a 2.7 that was never asked.
    """
    PYTHONS.mkdir(parents=True, exist_ok=True)
    script = PYTHONS / f"probe-{version}.py"
    found: set[str] = set()
    unanswered: set[str] = set(_unaskable(targets, version))
    tainted: set[str] = set()

    def run(batch: list[str]) -> bool:
        script.write_text(_probe_source(batch, version), encoding="utf-8")
        output = _interpret(version, path, script)
        found.update(_harvest(output))
        return FINISHED in output

    pending = [
        targets[start : start + BATCH] for start in range(0, len(targets), BATCH)
    ]
    while pending:
        batch = pending.pop()
        if run(batch):
            continue
        if len(batch) == 1:
            unanswered.update(batch)
            continue
        # The batch stopped early, so nothing after whatever killed it was
        # asked. Halve it and retry both halves, which finds the culprit
        # in a logarithmic number of runs rather than a linear one: going
        # one at a time costs a hundred interpreter starts per bad name,
        # times thirty-one releases.
        #
        # A `SyntaxError` is the usual cause and cannot be caught, because
        # it is raised when the file is compiled rather than when it runs.
        tainted.update(batch)
        middle = len(batch) // 2
        pending += [batch[:middle], batch[middle:]]

    for target in sorted(tainted - found - unanswered):
        if not run([target]):
            unanswered.add(target)

    script.unlink(missing_ok=True)
    return found, unanswered


def _unaskable(targets: list[str], version: str) -> set[str]:
    """Which of `targets` this release cannot even be asked about.

    A word that is a keyword in this release cannot be spelled as a name
    in the probe, so the release is never asked and has said nothing.
    Kept beside `_probe_source`'s own skip, because the two have to agree
    about which names never make it into the generated script.
    """
    if python_3(version):
        return set()
    return {
        target
        for target in targets
        if RESERVED.intersection(target.partition(" ")[2].split("."))
    }


def _harvest(output: str) -> set[str]:
    return {
        line.removeprefix("Y ").strip()
        for line in output.splitlines()
        if line.startswith("Y ")
    }


def probe() -> dict:
    """Ask every built interpreter about every name, and write the table.

    Every release, every time. Probing a subset and carrying the rest of
    the columns forward would be faster and would quietly let one half of
    the mask describe a build the other half no longer matches, which is
    the one thing a diff across the whole timeline cannot survive.
    """
    images = {which: ensure_image(which) for which in IMAGES}
    names = _dataset_names()
    targets = sorted(
        f"{label} {name}" for label in KINDS.values() for name in names[label]
    )
    print(f"Asking about {len(targets)} names.")

    resolved: dict[str, set[str]] = {}
    unanswered: dict[str, set[str]] = {}
    for version in RELEASES:
        path = binary(version)
        if path is None:
            print(f"  {version}: not built, skipping")
            continue
        resolved[version], unanswered[version] = _ask(version, path, targets)
        note = f"  {version}: {len(resolved[version])} of {len(targets)} resolve"
        if unanswered[version]:
            note += f", {len(unanswered[version])} killed the interpreter"
        print(note)

    # A table written from some of the releases would record every name
    # as absent from the rest, which is the most wrong thing this file
    # could possibly say.
    unbuilt = [version for version in RELEASES if version not in resolved]
    if unbuilt:
        raise SystemExit(
            f"Not built: {', '.join(unbuilt)}. Every release has to answer "
            "before the table is written, because a release that cannot be "
            "asked is not a release that said no. Run: --build"
        )

    # A release that could only be asked about a fraction of the corpus
    # is a release that mostly said nothing, and the docstring's own
    # principle applies to it as much as to one with no binary at all.
    crippled = [
        f"{version} ({len(names)})"
        for version, names in unanswered.items()
        if len(names) > len(targets) * UNANSWERED_LIMIT
    ]
    if crippled:
        raise SystemExit(
            f"Too many names killed the interpreter in {', '.join(crippled)}. "
            "That is a broken build rather than a measurement, so the table "
            "is not written."
        )

    presence = {}
    for target in targets:
        mask = "".join(
            PRESENT if target in resolved[version] else ABSENT for version in RELEASES
        )
        # A name no release resolves says nothing, and saying nothing at
        # length would triple the size of the table.
        if PRESENT in mask:
            presence[target] = mask

    table = {
        "releases": list(RELEASES),
        "checked": date.today().isoformat(),
        "images": images,
        "dockerfiles": {
            which: str(path.relative_to(ROOT)) for which, path in DOCKERFILES.items()
        },
        "era": {version: era(version) for version in RELEASES},
        "architecture": {
            version: "i386" if version in THIRTY_TWO_BIT else "x86_64"
            for version in RELEASES
        },
        "recipe": {version: recipe(version) for version in RELEASES},
        # Names that killed the interpreter when asked on their own, per
        # release. Not absences: `absence_is_real` reads this and refuses
        # to date from any of them, because "could not be asked" is a
        # fact about the build and not about the release.
        "unanswered": {
            version: sorted(names) for version, names in unanswered.items() if names
        },
        "presence": presence,
    }
    TABLE.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    load_table.cache_clear()
    print(f"Wrote {TABLE.relative_to(ROOT)}: {len(presence)} names resolve somewhere.")
    # Named rather than merely omitted. A name no release resolves gets no
    # answer, which is the right answer and an invisible one, and the
    # reason is worth seeing: `compression.zstd` resolves nowhere because
    # the image ships no `libzstd-dev`, not because 3.14 lacks it.
    silent = sorted(set(targets) - set(presence))
    if silent:
        print(f"No release resolves {len(silent)}: {', '.join(silent)}")
    return table


@cache
def load_table() -> dict:
    if not TABLE.exists():
        raise SystemExit(
            "No interpreter table. Run: uv run scripts/interpreters.py --build --probe"
        )
    return json.loads(TABLE.read_text(encoding="utf-8"))


def _imported_in(version: str, module: str) -> bool:
    """Whether the built interpreters could import `module` in `version`.

    Read off the table, so it reflects what the build actually managed
    rather than what the release contains. A module with no entry of its
    own is judged by its members: if any of them resolved, it imported.
    """
    presence = load_table()["presence"]
    index = load_table()["releases"].index(version)
    mask = presence.get(f"module {module}")
    if mask is not None:
        return mask[index] == PRESENT
    prefix = f"attribute {module}."
    return any(
        mask[index] == PRESENT
        for target, mask in presence.items()
        if target.startswith(prefix)
    )


def absence_is_real(version: str, target: str) -> bool:
    """Whether `version` lacking this name says something about `version`.

    The guard on every absence claim this file makes, and it is not
    optional. An extension is compiled only if its library is present and
    its `Modules/Setup` line is enabled, so "my build could not import
    it" and "the release did not have it" are different statements. This
    corpus contains the difference in bulk: 1.5, 1.6 and 2.0 install *no*
    shared modules at all, so every extension they ship reads as absent
    and 48 entries looked like disagreements that were nothing of the
    kind.

    The discrimination is per kind, because the same absence means
    different things:

    - **A builtin** is compiled into the interpreter, so nothing external
      can make it go missing and its absence is always real.
    - **A module** absent from a release whose own source implements it is
      a build gap, not history.
    - **A member** is different, and this is what a coarser check got
      wrong: if the module *imported* in that release, then the module was
      built and the member really was not in it. `operator.c` ships in 1.4
      and `operator` imports there, so `operator.contains` missing from
      1.4 is a fact about 1.4.

    The modern half needs the same guard for the same reason and cannot
    use the same reading, because "does this release implement the
    module" is answered differently once a C module registers itself
    through a `PyModuleDef`. `_ships_in` is where that lives. What does
    not change is which way the guard leans: `_ssl` does not build below
    3.6, because jammy's OpenSSL 3 is past what those releases compile
    against, `Lib/ssl.py` is in every one of those trees, and so
    `ssl.create_default_context` is bounded at 3.6 rather than dated from
    an absence the image caused.
    """
    if target in load_table().get("unanswered", {}).get(version, ()):
        # Asking crashed the interpreter, so this release said nothing at
        # all. Checked before the kind, because a builtin's absence is
        # otherwise always real and a build that dies on the question has
        # not reported one.
        return False
    kind, _, name = target.partition(" ")
    if kind in {"builtin", "method"}:
        # Both are compiled into the interpreter, so no library and no
        # `Modules/Setup` line can make either go missing. A method whose
        # type the release does not have is absent for a reason that is
        # still history rather than build configuration.
        return True
    module = name.partition(".")[0]
    if kind == "attribute" and _imported_in(version, module):
        return True
    return not _ships_in(version, module if kind == "attribute" else name)


@cache
def _ships_in(version: str, module: str) -> bool:
    """Whether the release's own tree carries an implementation of `module`.

    Both halves answer "the release implements it, so an absence here is
    this build's business", and both read the tree rather than the build,
    because the build is the thing being cross-checked.

    Which reading applies follows the *tree's* Python version and not the
    build recipe, and the two are not the same line. 2.6 and 2.7 are
    built like the modern half and have to be read like the old one: a C
    module there still says its own name in `Py_InitModule("dbm", ...)`,
    and grepping them for `PyInit_` finds four module names in the whole
    tree and dates `dbm` to 3.0.

    A Python 2 tree reads through `module_paths` for the library's `.py`
    files and `c_module_files` for the C ones. A pure Python module
    counts and has to: `gzip.py` ships in 2.4 and imports `zlib`,
    `threading.py` needs `thread`, `pty.py` reaches `termios`. Each is
    missing only because the extension beneath it is.

    A Python 3 tree reads the library directory by path, which also
    settles the dotted names the other reading has no way to spell:
    `unittest.mock` is `Lib/unittest/mock.py` and is genuinely absent
    before 3.3, while `Lib/xml/etree/ElementTree.py` has been there all
    along. Reading the head there would be exactly wrong, because
    the name `unittest` has been in the library since 2.1 and would
    bound every one of its members.
    """
    if not source_root(version).exists():
        # Refused rather than answered, because every caller inverts this
        # into "the absence is real". Returning False for a tree nobody
        # read turns a cold cache into a table of hard dates, and only
        # `compare()` used to check for one, so `just whenadded` and
        # `verify-dataset` could both reach here without it.
        raise SystemExit(
            f"No cached source for {version}, so an absence cannot be told "
            "from a build gap. Run: uv run scripts/fetch_docs.py"
        )
    if python_3(version):
        library = _library_root(version)
        if library is not None:
            where = library.joinpath(*module.split("."))
            if where.with_suffix(".py").exists() or (where / "__init__.py").exists():
                return True
        return module in _c_module_inits(version)
    # The one dotted module a Python 2 tree contains is `os.path`, and it
    # is not a file: `os.py` binds `path` to whichever of `posixpath` and
    # `macpath` the platform wants. So the head is what that tree can be
    # asked about, and asking for the whole dotted name would report
    # `os.path` as absent from a release that ships `posixpath.py`.
    #
    # Packages need asking separately, because a package is a directory
    # rather than one of those files. `curses` is the one in this corpus.
    head = module.partition(".")[0]
    return (
        head in _legacy_modules(version)
        or _ships_as_package(version, head)
        or _on_the_platform_path(version, head)
    )


# Directories inside `Lib/` that a Python 2 release puts on `sys.path`
# alongside the library itself. `turtle.py` moves into `lib-tk` at 1.6
# and stays there through 2.7, so a reading that only looks at `Lib/*.py`
# reports `turtle` as absent from every release after 1.5 that has it.
PYTHON_2_PATH_DIRS = ("lib-tk", "plat-*", "lib-old")


def _on_the_platform_path(version: str, module: str) -> bool:
    """Whether a Python 2 release ships `module` beside its library."""
    library = _library_root(version)
    if library is None:
        return False
    return any(
        (directory / f"{module}.py").exists()
        for pattern in PYTHON_2_PATH_DIRS
        for directory in library.glob(pattern)
    )


@cache
def _legacy_modules(version: str) -> frozenset[str]:
    """Every module an old release's tree implements, in one set.

    Held once per release rather than recomputed per name: both readings
    walk the whole unpacked tarball, and the walk backwards through the
    mask asks about thirty-one releases for every name in the dataset.
    """
    return frozenset(c_module_files(version)) | frozenset(module_paths(version))


@cache
def _library_root(version: str) -> Path | None:
    """The `Lib/` directory of an extracted release, if it has one."""
    found = sorted(source_root(version).rglob("Lib"))
    return found[0] if found else None


# What a Python 3 C extension is obliged to call its initialisation
# function. This is the one place a C module's import name is written
# down in that era, the way `initmodule("math", ...)` was in the old one,
# and it is written down by the import protocol rather than by
# convention: `import math` looks for `PyInit_math` and nothing else.
#
# That is what makes it safe to read where a bare function name is not.
# `pythonmain.c` once defined `initall()` to boot every module at once,
# and reading `init<name>` dated a builtin called `all` to 1991.
MODULE_INIT_3 = re.compile(r"\bPyInit_(\w+)\b")

# The other place a Python 3 C module writes its own name down: the first
# field of its `PyModuleDef` is `m_name`, spelled either positionally
# right after `PyModuleDef_HEAD_INIT` or as a designated initialiser.
#
# Needed because the modules built into the interpreter rather than
# loaded have no `PyInit_` at all: `sys` is created by `_PySys_Create`
# and `marshal` by `PyMarshal_Init`, so reading only `PyInit_` reported
# both as implemented by no release. That turns their absence into a real
# one, which is the direction that produces a wrong version number.
MODULE_DEF_3 = re.compile(
    r"PyModuleDef_HEAD_INIT\s*,\s*(?:\.m_name\s*=\s*)?\"(?P<name>[\w.]+)\""
)


def _c_sources(root: Path) -> list[Path]:
    """The C files that can register a module, in a Python 3 tree.

    `Python/` as well as `Modules/`, because `sys` and `marshal` live
    there and nowhere else. Reading only `Modules/` reported both as
    implemented by no release, which turns their absence into a real one
    and is the direction that produces a wrong version number.
    """
    return sorted(root.rglob("Modules/**/*.c")) + sorted(root.rglob("Python/*.c"))


@cache
def _c_module_inits(version: str) -> frozenset[str]:
    """Every C module a modern release's tree implements."""
    root = source_root(version)
    if not root.exists():
        return frozenset()
    found: set[str] = set()
    for path in _c_sources(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        found.update(match[1] for match in MODULE_INIT_3.finditer(text))
        found.update(match["name"] for match in MODULE_DEF_3.finditer(text))
    return frozenset(found)


def _ships_as_package(version: str, module: str) -> bool:
    """Whether the release ships `module` as a package directory.

    Searched rather than constructed, because the tarball unpacks into an
    inner directory whose name is spelled four different ways across the
    era, which is the same reason `source.py` reaches its library with
    `rglob`.
    """
    root = source_root(version)
    if not root.exists():
        return False
    return any(root.rglob(f"Lib/{module}/__init__.py"))


def _forgiven(mask: str, releases: list[str]) -> str:
    """The mask with 3.0 and 3.1 stopped from breaking a run.

    `added` is the oldest release a feature has been available in ever
    since, and the dataset's own rule is that 3.0 and 3.1 do not count
    against that: nobody shipped code on either, so a feature present in
    2.7 and again in 3.2 has been available since 2.7. `argparse` is the
    entry that rule was written for.

    Forgiven only where the name is on both sides of it, which is the
    whole of the care this needs and both halves matter. A name absent
    from 2.7, 3.0 and 3.1 and present from 3.2 arrived in 3.2, and
    bridging it would date the name to 3.0, a release it demonstrably
    could not be used in. A name present up to 2.7 and gone from 3.0 was
    removed, and bridging it would report it as last seen in 3.1, a
    release that never had it.
    """
    indexes = [index for index, release in enumerate(releases) if release in FORGIVEN]
    if not indexes:
        return mask
    before, after = min(indexes) - 1, max(indexes) + 1
    if before < 0 or after >= len(releases):
        return mask
    if mask[before] != PRESENT or mask[after] != PRESENT:
        return mask
    flags = list(mask)
    for index in indexes:
        flags[index] = PRESENT
    return "".join(flags)


def dated(target: str) -> dict | None:
    """When the built interpreters say `target` arrived.

    The answer is read backwards from the newest release, because the
    claim being made is "available ever since", and that is a statement
    about the end of the timeline rather than the beginning. Walk back
    while the name is there, and whatever stops the walk decides the
    shape:

    - a release that demonstrably lacks it stops the walk and dates it
    - running out of releases makes it a floor, because nothing older
      survives to be asked
    - an absence that is only this build's does not stop the walk, but it
      does cost the date: the walk carries on to see how far back
      presence reaches, and reports that as a floor.
      `ssl.create_default_context` is absent below 3.6 for a library
      reason, so it is bounded there rather than dated from it.
    - presence *before* the release that lacks it is a gap: the name came,
      went, and came back. The schema cannot record that, so it is
      reported for a human. `types.NoneType` is the case, bound in 1.1 and
      gone for all of Python 3 until 3.10.

    A name absent from the newest release was removed rather than added,
    and `added` cannot say that either. A name no release resolves is not
    in the table at all, and gets no answer rather than a wrong one.
    """
    table = load_table()
    mask = table["presence"].get(target)
    if mask is None:
        return None
    releases = table["releases"]
    flags = _forgiven(mask, releases)
    if flags[-1] == ABSENT:
        seen = [
            release
            for release, flag in zip(releases, flags, strict=True)
            if flag == PRESENT
        ]
        return {"removed_after": seen[-1], "floor": seen[0], "mask": mask}

    first = len(releases) - 1
    unbuilt: list[str] = []
    index = first - 1
    while index >= 0:
        if flags[index] == PRESENT:
            first = index
        elif absence_is_real(releases[index], target):
            break
        else:
            unbuilt.append(releases[index])
        index -= 1

    # Presence in 3.0 or 3.1 alone is not a previous life. Those two do
    # not count for continuity, so they do not count against it either,
    # and a name that was only ever in them is a name the dataset's rule
    # says nothing happened in.
    earlier = [
        position
        for position in range(index + 1)
        if flags[position] == PRESENT and releases[position] not in FORGIVEN
    ]
    if earlier:
        oldest = earlier[0]
        return {
            "gap": [
                release
                for release, flag in zip(
                    releases[oldest:first], flags[oldest:first], strict=True
                )
                if flag == ABSENT
            ],
            "since": releases[first],
            "floor": releases[oldest],
            "mask": mask,
        }
    if index < 0 or unbuilt:
        # Either nothing older survives to be asked, or what was measured
        # is this build's extension coverage rather than that release's
        # contents. Presence still proves presence, so keep the floor and
        # throw the date away.
        found = {"floor": releases[first], "mask": mask}
        if unbuilt:
            found["unbuilt_in"] = unbuilt[-1]
        return found
    return {"added": releases[first], "absent_in": releases[index], "mask": mask}


def _compare_removal(entry: dict, findings: dict[str, list[str]]) -> None:
    """Check one entry's `removed` claim, in both directions.

    Both directions matter and only one of them is obvious. An entry
    claiming a removal the interpreters do not show is the one anybody
    would think to check. The other way round is the one that keeps the
    dataset honest as Python moves: a name the newest interpreter has
    stopped resolving, on an entry that says nothing about it, is a
    feature that went away and an entry that has not noticed.

    Every probed kind is asked, `methods` included, because a removal is
    the one question the unbound spelling of a type method answers
    correctly. See `KINDS`.
    """
    claimed = entry.get("removed")
    for field, label in KINDS.items():
        for name in sorted(entry.get(field, ())):
            found = removed(f"{label} {name}")
            said = f"{entry['id']:<34} {name}"
            if found is None:
                if claimed:
                    findings.setdefault("removal-unseen", []).append(
                        f"  {said:<70} dataset says removed in {claimed}, but the "
                        "interpreters do not show it going away"
                    )
            elif not claimed:
                findings.setdefault("removed", []).append(
                    f"  {said:<70} last resolves in {found['present_in']} and is "
                    f"gone from {found['removed']}; the entry claims no removal"
                )
            elif found["removed"] != claimed:
                findings.setdefault("removal-disagrees", []).append(
                    f"  {said:<70} dataset says removed in {claimed}, interpreters "
                    f"say {found['removed']} (last in {found['present_in']})"
                )
            else:
                findings.setdefault("removal-confirms", []).append(
                    f"  {said:<70} removed in {claimed} confirmed"
                )


def removed(target: str) -> dict | None:
    """When the built interpreters say `target` was taken away.

    The mirror of `dated`, off the same mask, and read from the same end
    for the same reason: both claims are about what is true *now*.
    `added` walks back from 3.14 while the name is there; this one starts
    from the name not being there at 3.14 and reports the release after
    its last run. So `removed` is the oldest release the name has been
    unavailable in ever since, which is the sentence `added` makes with
    one word changed.

    Nothing here can be a bound, which is the one place the two axes are
    not symmetrical. `added` can only bound a name the corpus does not
    reach far enough back to see arrive; the corpus ends at the newest
    Python, so a name absent from that end has its last presence
    somewhere inside the corpus and the bracket always closes. There is
    no "or later" to match `or_earlier`.

    Four things stop it answering, and each is a refusal rather than a
    guess:

    - **A name no release resolves** is not in the table at all, and a
      name still in 3.14 was not removed.
    - **An absence the build caused** is not a removal. The release right
      after the last presence is the one whose absence carries the whole
      claim, so `absence_is_real` has to hold for it: a name that stops
      resolving because the image lacks a library has stopped being
      evidence, not stopped existing.
    - **A last presence in 3.0 or 3.1** is refused, because those two do
      not count towards availability in the other direction either and
      nothing in the corpus needs the answer. Reporting "removed in 3.2"
      for a name whose last real release was 2.7 would name a release
      two steps past where anyone stopped being able to use it.
    - **A gap that `_forgiven` bridges** never reaches here, since a name
      present on both sides of 3.0 and 3.1 is present at the end.
    """
    table = load_table()
    mask = table["presence"].get(target)
    if mask is None:
        return None
    releases = table["releases"]
    flags = _forgiven(mask, releases)
    if flags[-1] == PRESENT:
        return None
    present = [index for index, flag in enumerate(flags) if flag == PRESENT]
    if not present or releases[present[-1]] in FORGIVEN:
        return None
    last = present[-1]
    gone_in = releases[last + 1]
    if not absence_is_real(gone_in, target):
        return None
    return {
        "removed": gone_in,
        "present_in": releases[last],
        "absent_in": gone_in,
        "mask": mask,
    }


def report(grep: str | None = None) -> None:
    """What the table says, grouped by the shape of the answer."""
    table = load_table()
    images = ", ".join(f"{which} {image}" for which, image in table["images"].items())
    print(f"Images: {images}, checked {table['checked']}")
    print()
    buckets: dict[str, list[str]] = {}
    for target in sorted(table["presence"]):
        if grep and grep not in target:
            continue
        found = dated(target)
        if found is None:
            continue
        if "added" in found:
            shape = "dated"
            detail = f"{found['added']} (absent in {found['absent_in']})"
        elif "gap" in found:
            shape = "gap"
            detail = (
                f"in {found['floor']}, missing from {', '.join(found['gap'])}, "
                f"back in {found['since']}"
            )
        elif "removed_after" in found:
            # Read through `removed` rather than off `dated`, so that the
            # report and the check cannot disagree about the same name.
            # It is the stricter of the two: an absence the build caused
            # is not a removal, and shows here as one it declines to
            # date rather than as a release number.
            gone = removed(target)
            shape = "removed"
            detail = (
                f"last seen in {found['removed_after']}, gone from {gone['removed']}"
                if gone
                else f"last seen in {found['removed_after']}, "
                "and the absence after it is not this release's"
            )
        else:
            shape, detail = "floor", f"{found['floor']} or earlier"
        buckets.setdefault(shape, []).append(f"  {target:<44} {detail}")
    for shape in ("dated", "floor", "gap", "removed"):
        rows = buckets.get(shape, [])
        if not rows:
            continue
        print(f"{shape.upper()} ({len(rows)})")
        print("\n".join(rows))
        print()


def micro_explains(name: str, documented: str, found: str) -> bool:
    """Whether the docs' own marker accounts for the interpreter's absence.

    The corpus builds each release's `.0`, so a marker naming a micro is
    a marker this method is expected to disagree with. Sixteen names are
    that case, fourteen of them `typing`'s: the docs say 3.5.2, 3.5.3,
    3.6.1, 3.6.2 and 3.7.2, and the build of each `.0` correctly reports
    them absent.

    Tied to the next release rather than to any later one, because a
    marker at 3.5.2 explains an absence in 3.5 and explains nothing about
    an absence in 3.8. The two releases the dataset forgives are skipped
    when working out which release is next.

    A marker on the 2.x line is the other case, and it cannot be tied to
    the next release: a backport into a 2.x micro is invisible to a
    corpus that builds 2.7.0, and whatever the interpreter then reports
    is a fact about the 3.x line. `hmac.compare_digest` is 2.7.7 and 3.3,
    and choosing between them is the `backported` question the
    doc-derived methods already answer, so this defers to them.

    Lives here rather than in `dating.py` because both need it and they
    have to agree: `--check` reads one and `verify-dataset` reads the
    other, and two copies of this rule can reach opposite conclusions
    about the same entry.
    """
    release = dated_releases().get(name)
    if release is None or not release.startswith(f"{documented}."):
        return False
    if documented.startswith("2.") and version_key(found) >= version_key(
        FIRST_REAL_PYTHON_3
    ):
        return True
    after = [
        version
        for version in RELEASES
        if version_key(version) > version_key(documented) and version not in FORGIVEN
    ]
    return bool(after) and found == after[0]


def compare() -> dict[str, list[str]]:
    """Where the built interpreters disagree with what the dataset claims.

    This is the point of the whole exercise, so it is deliberately a
    report and not an edit. Nothing here rewrites a version: a
    disagreement between a doc-derived claim and a running interpreter
    needs a human to decide which is answering the right question, and
    several of these are the `Modules/Setup` ambiguity rather than a
    mistake.

    Four kinds of finding, in descending order of interest:

    - **closes** a bound the archives could only leave open, which is the
      yield this method was built for
    - **disagrees** with a version the dataset states outright
    - **older** than the dataset says, for a name the interpreters resolve
      before the release claimed. This is what the modern half is for:
      the inventory dates documentation, so a name the docs indexed late
      shows up here and nowhere else.
    - **confirms** what is already recorded

    Direction matters and the two are not symmetrical. An interpreter
    date *older* than the docs is believed, because presence proves
    presence. One that is *newer* is exactly where a micro release could
    have fixed something, and this corpus builds each release's `.0`, so
    it is reported and never applied.
    """
    # Every absence is cross-checked against what the release's own tree
    # implements, so without the corpus this would take each one at face
    # value and report differences that are really missing evidence.
    missing = [version for version in RELEASES if not source_root(version).exists()]
    if missing:
        raise SystemExit(
            f"No cached source for {', '.join(missing)}, so an absence cannot "
            "be told from a build gap. Run: uv run scripts/fetch_docs.py"
        )

    entries = tomllib.loads(DATASET.read_text(encoding="utf-8"))["features"]
    findings: dict[str, list[str]] = {}
    for entry in entries:
        # An override is per axis, because an entry can have one of each
        # and they need not come from the same place: `<>` is dated by
        # the grammar and its removal is a `manual` call the grammar
        # cannot make.
        if entry.get("removed_evidence", {}).get("method") not in OVERRIDES:
            _compare_removal(entry, findings)
        if entry.get("evidence", {}).get("method") in OVERRIDES:
            # A deliberate override of what the automated methods say, and
            # the note is where the reason lives. `re.finditer` is dated
            # 2.2 against this table's 2.3 because 2.2.2 fixed it, and
            # this corpus builds 2.2.0.
            continue
        claimed = entry["added"]
        bounded = entry.get("or_earlier", False)
        for field, label in DATING_KINDS.items():
            for name in sorted(entry.get(field, ())):
                found = dated(f"{label} {name}")
                if found is None:
                    continue
                said = f"{entry['id']:<34} {name}"
                if "gap" in found:
                    # The name went away and came back. `added` is the
                    # oldest release it has been available in ever since,
                    # so the release it came back in is the answer and an
                    # entry that already says so is confirmed rather than
                    # questioned. `types.NoneType` is bound in 1.1 and
                    # gone for all of Python 3 until 3.10.
                    kind = "readded" if found["since"] == claimed else "gap"
                    detail = (
                        f"in {found['floor']}, missing from "
                        f"{', '.join(found['gap'])}, back in {found['since']}; "
                        f"dataset says {claimed}"
                    )
                elif "removed_after" in found:
                    # The removal pass above already has this name, and
                    # a name the interpreters no longer resolve has no
                    # `added` for this half to check.
                    continue
                elif "added" in found:
                    if found["added"] != claimed:
                        older = version_key(found["added"]) < version_key(claimed)
                        kind = "older" if older else "disagrees"
                        if not older and micro_explains(name, claimed, found["added"]):
                            kind = "micro"
                        detail = (
                            f"dataset says {claimed}, interpreters say "
                            f"{found['added']} (absent in {found['absent_in']})"
                        )
                        if kind == "micro":
                            detail += f"; the docs say {dated_releases()[name]}"
                    elif bounded:
                        kind = "closes"
                        detail = (
                            f"dataset says {claimed} or earlier, interpreters "
                            f"date it {found['added']} (absent in "
                            f"{found['absent_in']})"
                        )
                    else:
                        kind, detail = "confirms", f"{claimed} confirmed"
                else:
                    floor = found["floor"]
                    if floor == RELEASES[0]:
                        # Present in the oldest interpreter there is, so
                        # this bounds rather than dates, exactly as the
                        # other methods' floors do.
                        kind, detail = "confirms", f"{floor} or earlier, as claimed"
                    elif version_key(floor) < version_key(claimed):
                        kind = "older"
                        detail = f"dataset says {claimed}, resolves already in {floor}"
                    else:
                        kind, detail = "confirms", f"no earlier than {floor}"
                findings.setdefault(kind, []).append(f"  {said:<70} {detail}")
    for kind in (
        "closes",
        "disagrees",
        "older",
        "gap",
        "removed",
        "removal-disagrees",
        "removal-unseen",
        "readded",
        "micro",
        "removal-confirms",
        "confirms",
    ):
        rows = findings.get(kind, [])
        if not rows:
            continue
        print(f"{kind.upper()} ({len(rows)})")
        if kind == "confirms":
            print(f"  {len(rows)} claims the interpreters agree with.")
        elif kind == "removal-confirms":
            print(f"  {len(rows)} removals the interpreters agree with.")
        elif kind == "micro":
            print(f"  {len(rows)} the docs date to a micro release this corpus")
            print("  does not build. The docs are right about the release.")
        else:
            print("\n".join(rows))
        print()
    return findings


def _wanted(asked: list[str]) -> list[str]:
    """Which releases to build, from what was asked for.

    An era name stands for its releases, because "rebuild the modern
    half" is the thing that actually gets typed and spelling out
    seventeen versions invites getting one wrong.
    """
    if not asked:
        return list(RELEASES)
    chosen = []
    for name in asked:
        if name in IMAGES:
            chosen += [version for version in RELEASES if era(version) == name]
        elif name in RELEASES:
            chosen.append(name)
        else:
            raise SystemExit(f"Unknown release: {name}")
    return chosen


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build",
        nargs="*",
        metavar="VERSION",
        help="build these releases, an era name, or all of them",
    )
    parser.add_argument("--probe", action="store_true", help="write the table")
    parser.add_argument("--report", action="store_true", help="what the table dates")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="where the interpreters disagree with the dataset",
    )
    parser.add_argument("--grep", help="report only names containing this")
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail if the table and the dataset disagree",
    )
    args = parser.parse_args(argv)

    if args.build is not None:
        for version in _wanted(args.build):
            arch = "i386" if version in THIRTY_TWO_BIT else "x86_64"
            print(f"Building Python {version} ({arch})")
            print(f"  built {build(version)}")
    if args.probe:
        probe()
    if args.report or args.grep:
        report(args.grep)
    if args.compare:
        compare()
    if args.check:
        findings = compare()
        unresolved = [
            row
            for kind in (
                "closes",
                "disagrees",
                "older",
                "removal-disagrees",
                "removal-unseen",
            )
            for row in findings.get(kind, [])
        ]
        if unresolved:
            print(
                f"{len(unresolved)} entries disagree with the interpreters. "
                "Either the dataset is stale or the table is: re-run "
                "--build --probe, or correct the entries.",
                file=sys.stderr,
            )
            return 1
        print("The dataset agrees with every name the interpreters resolve.")
    if args.build is None and not (
        args.probe or args.report or args.grep or args.compare or args.check
    ):
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
