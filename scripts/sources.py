"""Shared plumbing for the research scripts: the cache and its manifest.

Everything downstream reads from the local cache, never from the network,
so a research run is offline and repeatable. `fetch_docs.py` is the only
script that reaches out, and it records a SHA-256 for every payload it
stores. The manifest is committed; the payloads are not.
"""

import hashlib
import json
import re
import zlib
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
MANIFEST = ROOT / "scripts" / "sources.sha256"

# Every Python whose docs ship a Sphinx object inventory. 2.6 is the
# oldest; anything older is HTML only and has to be read by hand.
INVENTORY_VERSIONS = (
    "2.6",
    "2.7",
    "3.0",
    "3.1",
    "3.2",
    "3.3",
    "3.4",
    "3.5",
    "3.6",
    "3.7",
    "3.8",
    "3.9",
    "3.10",
    "3.11",
    "3.12",
    "3.13",
    "3.14",
)

# Plain-text doc builds, used for the annotation grep. The newest release
# carries the whole surviving history of `Added in version` markers; 2.7
# is kept because it still documents what Python 3 removed.
TEXT_BUILDS = {
    "2.7": "2.7.18",
    "3.14": "3.14.0",
}

INVENTORY_URL = "https://docs.python.org/{version}/objects.inv"
TEXT_URL = (
    "https://www.python.org/ftp/python/doc/{micro}/python-{micro}-docs-text.tar.bz2"
)

# The source releases, which are all that exists before the docs were
# built as HTML. Their `Doc/` LaTeX carries the same "Standard module"
# and "Built-in module" section headings the early HTML builds do, so
# the two eras can be read the same way. 0.9.1 is the first public
# release of Python, from 1991.
SOURCE_BUILDS = {
    "0.9": "src/Python-0.9.1.tar.gz",
    "1.0": "src/python1.0.1.tar.gz",
    "1.1": "src/python1.1.tar.gz",
}

# The HTML doc archives, which are all that exists before the Sphinx
# era. Each one carries a list of every module in that release, so
# diffing them dates the pre-2.6 stdlib the same way `objects.inv` dates
# the rest. Keyed by feature release; the value is the archive's name on
# python.org, which does not always match the release.
HTML_BUILDS = {
    "1.2": "doc/1.2/html-1.2.tar.gz",
    "1.3": "doc/1.3/html-1.3.tar.gz",
    "1.4": "doc/1.4/html-1.4.tar.gz",
    "1.5": "doc/1.5.2/html-1.5.2.tgz",
    "1.6": "doc/1.6/html-1.6p1.tgz",
    "2.0": "doc/2.0/html-2.0.tgz",
    "2.1": "doc/2.1/html-2.1.tgz",
    "2.2": "doc/2.2/html-2.2.tgz",
    "2.3": "doc/2.3/html-2.3.tgz",
    "2.4": "doc/2.4/html-2.4.tar.bz2",
    "2.5": "doc/2.5/html-2.5.tar.bz2",
}

HTML_URL = "https://www.python.org/ftp/python/{path}"

# CPython's grammar at each release tag. This is ground truth for
# syntax: a keyword or rule absent from one release's grammar and
# present in the next was added in that release, which beats a PEP
# header, since a PEP records intent and the grammar records what
# shipped. 0.9.1 has no usable tag, so its grammar comes out of the
# source tarball already in the cache.
#
# The parser changed in 3.9: the PEG grammar landed alongside the old
# one, and the old one was dropped after. 3.9 therefore appears in both
# chains, which is what lets each be diffed on its own terms.
GRAMMAR_TAGS = {
    "1.0": "v1.0.1",
    "1.1": "v1.1",
    "1.2": "v1.2",
    "1.3": "v1.3",
    "1.4": "v1.4",
    "1.5": "v1.5",
    "1.6": "v1.6a2",
    "2.0": "v2.0",
    "2.1": "v2.1",
    "2.2": "v2.2",
    "2.3": "v2.3.4",
    "2.4": "v2.4",
    "2.5": "v2.5",
    "2.6": "v2.6",
    "2.7": "v2.7",
    "3.0": "v3.0",
    "3.1": "v3.1",
    "3.2": "v3.2",
    "3.3": "v3.3.0",
    "3.4": "v3.4.0",
    "3.5": "v3.5.0",
    "3.6": "v3.6.0",
    "3.7": "v3.7.0",
    "3.8": "v3.8.0",
    "3.9": "v3.9.0",
}

# The releases whose grammar is the PEG one. 3.9 is in both maps.
PEG_TAGS = {
    "3.9": "v3.9.0",
    "3.10": "v3.10.0",
    "3.11": "v3.11.0",
    "3.12": "v3.12.0",
    "3.13": "v3.13.0",
    "3.14": "v3.14.0",
}

GRAMMAR_URL = "https://raw.githubusercontent.com/python/cpython/{tag}/Grammar/{file}"

# Release dates for the era python.org's downloads database does not
# reach. CPython's own release tags do: the commit each one points at is
# the release being cut, and where the two sources overlap from 2.2 on
# they agree. Before 2.2 the tags are the only machine-readable record.
#
# 1.0 and 1.6 have no tag of their own, so 1.0 borrows 1.0.1, which is
# the release this project's corpus uses anyway. 0.9 has no tag at all.
RELEASE_TAGS = {
    "1.0": "v1.0.1",
    "1.1": "v1.1",
    "1.2": "v1.2",
    "1.3": "v1.3",
    "1.4": "v1.4",
    "1.5": "v1.5",
    "2.0": "v2.0",
    "2.1": "v2.1",
}

TAG_URL = "https://api.github.com/repos/python/cpython/commits/{tag}"
TAGS_PATH = "releases/tags.json"

# The PEP index, which carries the Python-Version header for every PEP.
# Syntax features have no documented object to diff, so this is what
# dates them.
PEPS_URL = "https://peps.python.org/api/peps.json"
PEPS_PATH = "peps/peps.json"

# Every published release with its date. This is what turns "added in
# 3.11" into "available since October 2022", which is the thing anyone
# actually wants to know. The database starts at 2.0.1, so releases
# older than 2.2 have no citable date here.
RELEASES_URL = "https://www.python.org/api/v2/downloads/release/?is_published=true"
RELEASES_PATH = "releases/releases.json"

# `name domain:role priority uri dispname`, with a name that may contain
# spaces, which is why the name group is lazy.
INVENTORY_LINE = re.compile(r"(?x)(.+?)\s+(\S+)\s+(-?\d+)\s+(\S*)\s+(.*)")

# Inventory version 1 (2.6, 3.0 and 3.1) is uncompressed and writes its
# roles bare, with no domain prefix: `mod` for modules, `cfunction` and
# friends for the C API, and the plain Python role name for everything
# else. Normalising onto the version 2 spelling is what lets the two
# eras be diffed against each other.
ROLE_ALIASES = {
    "mod": "module",
    "func": "function",
    "meth": "method",
    "exc": "exception",
}

C_ROLES = frozenset({"cfunction", "cmember", "ctype", "cvar", "cmacro", "cdata"})


def normalize_role(role: str) -> str:
    if ":" in role:
        return role
    if role in C_ROLES:
        return f"c:{role.removeprefix('c')}"
    return f"py:{ROLE_ALIASES.get(role, role)}"


def inventory_path(version: str) -> Path:
    return CACHE / "inv" / f"objects-{version}.inv"


def text_archive_path(micro: str) -> Path:
    return CACHE / "text" / f"python-{micro}-docs-text.tar.bz2"


def text_root(version: str) -> Path:
    """Where a text build's `library/` directory lives.

    The tarballs unpack into a `python-<micro>-docs-text` directory, so
    the useful root is one level below where the archive was extracted.
    """
    extracted = CACHE / "text" / version
    inner = extracted / f"python-{TEXT_BUILDS.get(version, version)}-docs-text"
    return inner if inner.exists() else extracted


def html_archive_path(version: str) -> Path:
    return CACHE / "html" / Path(HTML_BUILDS[version]).name


def source_archive_path(version: str) -> Path:
    return CACHE / "src" / Path(SOURCE_BUILDS[version]).name


def html_root(version: str) -> Path:
    """Where a release's extracted documentation lives.

    Source releases and HTML doc archives unpack into different trees,
    so this is the one place that knows which is which.
    """
    if version in SOURCE_BUILDS:
        return CACHE / "src" / version
    return CACHE / "html" / version


def grammar_path(version: str, peg: bool = False) -> Path:
    suffix = "gram" if peg else "grammar"
    return CACHE / "grammar" / f"{version}.{suffix}"


def peps_path() -> Path:
    return CACHE / PEPS_PATH


def releases_path() -> Path:
    return CACHE / RELEASES_PATH


def tags_path() -> Path:
    return CACHE / TAGS_PATH


def load_tag_dates() -> dict[str, str]:
    """Release-tag commit dates, keyed by feature release."""
    path = tags_path()
    if not path.exists():
        raise SystemExit("No cached tag dates. Run: uv run scripts/fetch_docs.py")
    return json.loads(path.read_text(encoding="utf-8"))


def load_releases() -> list[dict]:
    """Every published release, as python.org lists them."""
    path = releases_path()
    if not path.exists():
        raise SystemExit("No cached release list. Run: uv run scripts/fetch_docs.py")
    return json.loads(path.read_text(encoding="utf-8"))


def load_peps() -> dict[str, dict]:
    """The PEP index, keyed by PEP number as a string."""
    path = peps_path()
    if not path.exists():
        raise SystemExit("No cached PEP index. Run: uv run scripts/fetch_docs.py")
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_manifest() -> dict[str, str]:
    """Map of cache-relative path to recorded SHA-256."""
    if not MANIFEST.exists():
        return {}
    entries = {}
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sha, _, relative = line.partition("  ")
        entries[relative.strip()] = sha
    return entries


def write_manifest(entries: dict[str, str]) -> None:
    lines = [
        "# SHA-256 of every cached documentation source.",
        "# Regenerate with: uv run scripts/fetch_docs.py",
        "",
    ]
    lines += [f"{sha}  {path}" for path, sha in sorted(entries.items())]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _body(raw: bytes, header_lines: int) -> str:
    offset = 0
    for _ in range(header_lines):
        offset = raw.index(b"\n", offset) + 1
    payload = raw[offset:]
    if header_lines == 4:
        payload = zlib.decompress(payload)
    return payload.decode("utf-8", "replace")


def _parse_v1(raw: bytes) -> dict[str, str]:
    entries = {}
    for line in _body(raw, 3).splitlines():
        parts = line.rstrip().split(None, 2)
        if len(parts) != 3:
            continue
        name, role, uri = parts
        entries[f"{normalize_role(role)} {name}"] = uri
    return entries


def _parse_v2(raw: bytes) -> dict[str, str]:
    entries = {}
    for line in _body(raw, 4).splitlines():
        match = INVENTORY_LINE.fullmatch(line.rstrip())
        if match is None:
            continue
        name, role, _priority, uri, _dispname = match.groups()
        entries[f"{normalize_role(role)} {name}"] = uri
    return entries


def parse_inventory(path: Path) -> dict[str, str]:
    """Read a Sphinx `objects.inv` into `{"py:role name": uri}`.

    Both inventory formats show up in the corpus: version 1 is a plain
    three-column text file, version 2 has a fourth header line and a
    zlib-compressed body.
    """
    raw = path.read_bytes()
    first_line = raw[: raw.index(b"\n")].decode("utf-8", "replace")
    if first_line.endswith("1"):
        return _parse_v1(raw)
    return _parse_v2(raw)


def load_inventories() -> dict[str, dict[str, str]]:
    """Every cached inventory, keyed by version, in release order."""
    inventories = {}
    for version in INVENTORY_VERSIONS:
        path = inventory_path(version)
        if path.exists():
            inventories[version] = parse_inventory(path)
    return inventories


def text_files(version: str) -> Iterator[Path]:
    root = text_root(version)
    if root.exists():
        yield from sorted(root.rglob("*.txt"))
