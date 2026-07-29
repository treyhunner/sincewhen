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

Building fourteen interpreters needs Docker and several minutes, and the
rest of this pipeline is offline and quick. So the build is an occasional
manual step and its *result* is the artifact:
`scripts/interpreters.json` records, for every name, which releases
resolved it. Downstream reads the table and never needs a compiler, which
keeps `verify-dataset` and CI exactly as reproducible as they were.

Usage:

    uv run scripts/interpreters.py --build          # build all fourteen
    uv run scripts/interpreters.py --build 1.4      # or just one
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

from source import c_module_files, module_paths
from sources import CACHE, ROOT, SOURCE_BUILDS, source_archive_path, source_root

# Every release with a pinned source tarball, oldest first: 0.9.1 through
# 2.5, which is the whole of the era the Sphinx inventories cannot reach
# and the whole of the era that still has bounded entries.
RELEASES = tuple(SOURCE_BUILDS)

PYTHONS = CACHE / "pythons"
BUILD = PYTHONS / "build"
INSTALL = PYTHONS / "inst"
LOGS = PYTHONS / "log"

TABLE = ROOT / "scripts" / "interpreters.json"
DATASET = ROOT / "src" / "sincewhen" / "features.toml"
DOCKERFILE = ROOT / "scripts" / "interpreters.dockerfile"
IMAGE = "sincewhen-interpreters"

# What the table writes per release. Every release in the corpus answers
# or the table is not written, so there is no third state: a release that
# could not be asked is not a release that said no.
PRESENT = "#"
ABSENT = "."

# Printed as the last statement of a probe, so that "resolved nothing" can
# be told apart from "died part way through".
FINISHED = "PROBE-FINISHED"

# Words that were statements in this era, so a probe cannot spell them as
# names. `print` and `exec` are the ones the dataset actually contains:
# both are Python 3 builtins and both are keywords here, so `_ = print` is
# a syntax error rather than a lookup that fails.
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

# The matcher fields that name something an interpreter can be asked
# about, and what one is called in the table. Anything else in the
# dataset is syntax, which the grammar already settles.
KINDS = {"modules": "module", "builtins": "builtin", "attributes": "attribute"}

# How many names to ask about in one interpreter run. Small enough that a
# crash costs little and large enough that the per-run overhead of
# `docker run` stays amortised.
BATCH = 100


def version_key(version: str) -> tuple[int, int]:
    major, _, minor = version.partition(".")
    return int(major), int(minor)


def flags(version: str) -> str:
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
    """
    if version in NO_CONFIGURE:
        candidate = build_root(version) / "src" / "python"
        return candidate if candidate.exists() else None
    installed = install_root(version) / "bin"
    if (installed / "python").exists():
        return installed / "python"
    # 2.5 installs `python2.5` and only symlinks `python` at the very end
    # of `make install`, which does not get there: its `libinstall` step
    # runs `compileall` over a library that deliberately ships
    # `badsyntax_*.py` test files, so `compileall` exits non-zero. The
    # `.pyc` files are no loss, because an interpreter compiles `.py` on
    # the way in, so the versioned name is what to look for.
    versioned = sorted(installed.glob("python[0-9]*"))
    return versioned[0] if versioned else None


def ensure_image() -> str:
    """Build the pinned build environment if it is not already here.

    Returns the image id, which goes into the table: it is the closest
    thing to a checksum of "what compiled this".
    """
    found = subprocess.run(
        ["docker", "images", "-q", IMAGE], capture_output=True, text=True
    )
    if not found.stdout.strip():
        print(f"Building the {IMAGE} image (once).")
        built = subprocess.call(
            [
                "docker",
                "build",
                "-t",
                IMAGE,
                "-f",
                str(DOCKERFILE),
                str(DOCKERFILE.parent),
            ]
        )
        if built != 0:
            raise SystemExit("Could not build the interpreter build environment.")
        found = subprocess.run(
            ["docker", "images", "-q", IMAGE], capture_output=True, text=True
        )
    return found.stdout.strip()


def _docker(command: list[str], cwd: Path, log: Path | None = None) -> int:
    """Run a command inside the pinned image, over the real cache.

    The repository is mounted at its own path rather than somewhere
    tidier, so that a prefix compiled into an interpreter means the same
    thing inside the container and out. Runs as the invoking user, so the
    cache does not fill up with root-owned files.
    """
    invocation = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{ROOT}:{ROOT}",
        "--workdir",
        str(cwd),
        IMAGE,
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
    recorded = [
        *_patch_names(version),
        f"CC={compiler(version)}",
        f"OPT={flags(version)}",
    ]
    if version_key(version) >= version_key(SETUP_PY_FROM):
        recorded.append(f"LDFLAGS={MULTIARCH_LIBS}")
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

    Serial `make` throughout: these recursive Makefiles predate parallel
    make and race against themselves, and a `-j` build fails looking for
    a library the sibling directory has not written yet.
    """
    ensure_image()
    LOGS.mkdir(parents=True, exist_ok=True)
    log = LOGS / f"{version}.log"
    log.write_text(f"# building Python {version}\n", encoding="utf-8")

    tree = _unpack(version)
    for note in _patch(version, tree):
        print(f"  patch: {note}")

    opt = flags(version)
    if version in NO_CONFIGURE:
        # No configure, no install: 0.9.1 is built where it stands.
        _docker(["make", f"CC={compiler(version)} {opt}"], tree / "src", log)
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
        )
        supplied = _supply_platform_dir(tree)
        if supplied:
            print(f"  platform: {supplied}")
        _docker(["make", f"OPT={opt}"], tree, log)
        _docker(["make", "install"], tree, log)
        if version in LIBINSTALL:
            _docker(["make", "libinstall"], tree, log)

    found = binary(version)
    if found is None:
        raise SystemExit(f"Python {version} did not build. See {log}")
    _check_health(version, found)
    return found


def _health_source(version: str) -> str:
    """Python that prints a label per health check it passes."""
    equals = "=" if version in OLD_EQUALITY else "=="
    lines = []
    for label, setup, condition in HEALTH:
        lines.append("try:")
        lines += [f"    {statement}" for statement in setup]
        lines.append(f"    if {condition.format(eq=equals)}:")
        lines.append(f"        print 'H {label}'")
        lines.append("except:")
        lines.append("    pass")
    return "\n".join(lines) + "\n"


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
    script = PYTHONS / f"health-{version}.py"
    script.write_text(_health_source(version), encoding="utf-8")
    passed = {
        line.removeprefix("H ").strip()
        for line in _interpret(version, path, script).splitlines()
        if line.startswith("H ")
    }
    script.unlink(missing_ok=True)
    missing = [label for label, *_ in HEALTH if label not in passed]
    if missing:
        raise SystemExit(
            f"Python {version} built but fails {', '.join(missing)}, so its "
            f"answers would be worse than none. See {LOGS / f'{version}.log'}"
        )
    print(f"  health: {len(passed)} of {len(HEALTH)} checks pass")


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
    command += [str(path), str(script)]
    invocation = [
        "docker",
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{ROOT}:{ROOT}",
        "--workdir",
        str(ROOT),
        IMAGE,
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


def _probe_source(targets: list[str]) -> str:
    """Python that prints each of `targets` it can resolve.

    Written in the only dialect all fourteen releases share, which is a
    narrow one: `import`, `try`/`except`, attribute access and a `print`
    statement. No `hasattr`, no `getattr`, no `sys.stdout`, and no `==`,
    because the oldest release here predates all of them and this file
    has to parse under it.

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
        if RESERVED.intersection(name.split(".")):
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
            lines.append(f"    print 'Y {target}'")
            lines.append("except:")
            lines.append("    pass")
    # A batch that resolves nothing and a batch that died both come back
    # with no `Y` lines, and they mean opposite things. The oldest
    # releases resolve nothing for most batches, so without a sentinel
    # every one of those looks like a crash and gets retried a name at a
    # time: tens of thousands of interpreter runs instead of hundreds.
    lines.append(f"print '{FINISHED}'")
    return "\n".join(lines) + "\n"


def _ask(version: str, path: Path, targets: list[str]) -> set[str]:
    """Which of `targets` this interpreter resolves.

    Asked in batches so that an interpreter dying part way through costs
    one batch rather than everything after it, and a batch that dies is
    retried one name at a time so the damage is confined to the name that
    caused it. A single bad name is a real possibility: a `SyntaxError`
    is raised when the file is compiled, before any `try` can catch it,
    so one unparseable name would otherwise silence the whole batch.
    """
    PYTHONS.mkdir(parents=True, exist_ok=True)
    script = PYTHONS / f"probe-{version}.py"
    found: set[str] = set()
    pending = [
        targets[start : start + BATCH] for start in range(0, len(targets), BATCH)
    ]
    while pending:
        batch = pending.pop()
        script.write_text(_probe_source(batch), encoding="utf-8")
        output = _interpret(version, path, script)
        found |= _harvest(output)
        if FINISHED in output or len(batch) == 1:
            continue
        # The batch stopped early, so nothing after whatever killed it was
        # asked. Halve it and retry both halves, which finds the culprit
        # in a logarithmic number of runs rather than a linear one: going
        # one at a time costs a hundred interpreter starts per bad name,
        # times fourteen releases.
        #
        # A `SyntaxError` is the usual cause and cannot be caught, because
        # it is raised when the file is compiled rather than when it runs.
        middle = len(batch) // 2
        pending += [batch[:middle], batch[middle:]]
    script.unlink(missing_ok=True)
    return found


def _harvest(output: str) -> set[str]:
    return {
        line.removeprefix("Y ").strip()
        for line in output.splitlines()
        if line.startswith("Y ")
    }


def probe() -> dict:
    """Ask every built interpreter about every name, and write the table."""
    image = ensure_image()
    names = _dataset_names()
    targets = sorted(
        f"{label} {name}" for label in KINDS.values() for name in names[label]
    )
    print(f"Asking about {len(targets)} names.")

    resolved: dict[str, set[str]] = {}
    for version in RELEASES:
        path = binary(version)
        if path is None:
            print(f"  {version}: not built, skipping")
            continue
        resolved[version] = _ask(version, path, targets)
        print(f"  {version}: {len(resolved[version])} of {len(targets)} resolve")

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

    presence = {}
    for target in targets:
        mask = "".join(
            PRESENT if target in resolved[version] else ABSENT for version in RELEASES
        )
        # A name no release in this era has says nothing, and saying
        # nothing at length would triple the size of the table.
        if PRESENT in mask:
            presence[target] = mask

    table = {
        "releases": list(RELEASES),
        "checked": date.today().isoformat(),
        "image": image,
        "dockerfile": str(DOCKERFILE.relative_to(ROOT)),
        "architecture": {
            version: "i386" if version in THIRTY_TWO_BIT else "x86_64"
            for version in RELEASES
        },
        "recipe": {version: recipe(version) for version in RELEASES},
        "presence": presence,
    }
    TABLE.write_text(json.dumps(table, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {TABLE.relative_to(ROOT)}: {len(presence)} names resolve somewhere.")
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
    """
    kind, _, name = target.partition(" ")
    if kind == "builtin":
        return True
    module = name.partition(".")[0]
    if kind == "attribute" and _imported_in(version, module):
        return True
    # `module_paths` is the library's `.py` files and `c_module_files` the
    # C ones, so between them this is "the release implements it". A pure
    # Python module counts too, and has to: `gzip.py` ships in 2.4 and
    # imports `zlib`, `threading.py` needs `thread`, `pty.py` reaches
    # `termios`. Each is missing here only because the extension beneath it
    # is, which is this build's business and not that release's.
    #
    # Packages need asking separately, because a package is a directory
    # rather than one of those files. `curses` is the one in this corpus.
    shipped = module in c_module_files(version) or module in module_paths(version)
    return not (shipped or _ships_as_package(version, module))


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


def dated(target: str) -> dict | None:
    """When the built interpreters say `target` arrived.

    Four shapes come out of a presence mask, and only one of them is a
    date:

    - absent, then present ever since: the release it appeared in, which
      is a date, with the release before it as proof of absence
    - present in the oldest release built: a floor, because nothing older
      survives to be asked
    - present, gone, present again: a gap, left standing for a human
    - present and then gone for good: a removal, which the schema cannot
      record, so it is reported rather than dated

    A name no release resolves is not in the table at all, and gets no
    answer rather than a wrong one.
    """
    table = load_table()
    mask = table["presence"].get(target)
    if mask is None:
        return None
    releases = table["releases"]
    seen = [
        release for release, flag in zip(releases, mask, strict=True) if flag == PRESENT
    ]
    first = releases.index(seen[0])
    last = releases.index(seen[-1])
    span = mask[first : last + 1]
    if ABSENT in span:
        return {
            "gap": [
                release
                for release, flag in zip(releases[first : last + 1], span, strict=True)
                if flag == ABSENT
            ],
            "floor": seen[0],
            "mask": mask,
        }
    if seen[-1] != releases[-1]:
        return {"removed_after": seen[-1], "floor": seen[0], "mask": mask}
    if first == 0:
        return {"floor": seen[0], "mask": mask}
    absent_in = releases[first - 1]
    if not absence_is_real(absent_in, target):
        # What was measured is this build's extension coverage rather than
        # that release's contents. Presence still proves presence, so keep
        # the floor and throw the date away.
        return {"floor": seen[0], "unbuilt_in": absent_in, "mask": mask}
    return {"added": seen[0], "absent_in": absent_in, "mask": mask}


def report(grep: str | None = None) -> None:
    """What the table says, grouped by the shape of the answer."""
    table = load_table()
    print(f"Image {table['image']}, checked {table['checked']}")
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
            shape, detail = "gap", f"missing from {', '.join(found['gap'])}"
        elif "removed_after" in found:
            shape, detail = "removed", f"last seen in {found['removed_after']}"
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
      before the release claimed
    - **confirms** what is already recorded
    """
    entries = tomllib.loads(DATASET.read_text(encoding="utf-8"))["features"]
    findings: dict[str, list[str]] = {}
    for entry in entries:
        claimed = entry["added"]
        bounded = entry.get("or_earlier", False)
        for field, label in KINDS.items():
            for name in sorted(entry.get(field, ())):
                found = dated(f"{label} {name}")
                if found is None:
                    continue
                said = f"{entry['id']:<34} {name}"
                if "gap" in found:
                    kind = "gap"
                    detail = f"present, then missing from {', '.join(found['gap'])}"
                elif "removed_after" in found:
                    kind = "removed"
                    detail = f"last seen in {found['removed_after']}"
                elif version_key(claimed) > version_key(RELEASES[-1]):
                    # The dataset dates it past the newest interpreter
                    # here and these releases resolve it, so the name went
                    # away and came back. `types.NoneType` is bound in 1.1
                    # and gone for all of Python 3 until 3.10, and 3.10 is
                    # right under the "oldest release it has been
                    # available in ever since" rule.
                    kind = "readded"
                    detail = (
                        f"dataset says {claimed}; also present from "
                        f"{found.get('added', found.get('floor'))} to {RELEASES[-1]}"
                    )
                elif "added" in found:
                    if found["added"] != claimed:
                        older = version_key(found["added"]) < version_key(claimed)
                        kind = "older" if older else "disagrees"
                        detail = (
                            f"dataset says {claimed}, interpreters say "
                            f"{found['added']} (absent in {found['absent_in']})"
                        )
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
        "readded",
        "confirms",
    ):
        rows = findings.get(kind, [])
        if not rows:
            continue
        print(f"{kind.upper()} ({len(rows)})")
        if kind == "confirms":
            print(f"  {len(rows)} claims the interpreters agree with.")
        else:
            print("\n".join(rows))
        print()
    return findings


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build",
        nargs="*",
        metavar="VERSION",
        help="build these releases, or all of them",
    )
    parser.add_argument("--probe", action="store_true", help="write the table")
    parser.add_argument("--report", action="store_true", help="what the table dates")
    parser.add_argument(
        "--compare",
        action="store_true",
        help="where the interpreters disagree with the dataset",
    )
    parser.add_argument("--grep", help="report only names containing this")
    args = parser.parse_args(argv)

    if args.build is not None:
        for version in args.build or list(RELEASES):
            if version not in RELEASES:
                raise SystemExit(f"Unknown release: {version}")
            arch = "i386" if version in THIRTY_TWO_BIT else "x86_64"
            print(f"Building Python {version} ({arch})")
            print(f"  built {build(version)}")
    if args.probe:
        probe()
    if args.report or args.grep:
        report(args.grep)
    if args.compare:
        compare()
    if args.build is None and not (
        args.probe or args.report or args.grep or args.compare
    ):
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
