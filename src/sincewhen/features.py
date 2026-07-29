"""The feature dataset: what each feature is and when it arrived."""

import tomllib
from dataclasses import dataclass, fields
from functools import cache
from importlib.resources import files

from .versions import Version

DATA_FILE = "features.toml"

MATCHER_FIELDS = ("nodes", "builtins", "modules", "attributes")

# How a version claim was established. Each method says what a reviewer
# has to do to check it: the first three are machine-checkable against
# archived documentation, and `manual` is the one that needs a human.
#
#   objects.inv  the symbol is absent from one release's Sphinx
#                inventory and present in the next
#   archive      the same diff for the era before Sphinx, over the
#                module lists and built-in function pages in the
#                archived HTML doc builds
#   source       the same diff over the builtins table in CPython's own
#                `bltinmodule.c`, which reaches back to 0.9.1 and so
#                predates every doc build. Alone among these, its
#                absences count for as much as its presences, because
#                the table is the list the interpreter registers its
#                builtins from rather than a description of one
#   annotation   the documentation says so itself, in an
#                "Added in version" marker that is quoted here
#   grammar      the token is absent from one release's grammar and
#                present in the next, which is what shipped rather than
#                what a PEP intended
#   pep          the feature's PEP carries a Python-Version header
#   manual       read out of archived docs by hand, with a note saying
#                what was read and why the automated methods do not
#                settle it
EVIDENCE_METHODS = frozenset(
    {"objects.inv", "archive", "source", "grammar", "annotation", "pep", "manual"}
)

EVIDENCE_REQUIRED = {
    "objects.inv": ("symbol", "absent_in", "present_in"),
    "archive": ("present_in",),
    "source": ("symbol", "file", "present_in"),
    "grammar": ("symbol", "absent_in", "present_in"),
    "annotation": ("docs", "quote"),
    "pep": ("pep", "python_version"),
    "manual": ("note",),
}


@dataclass(frozen=True)
class Evidence:
    """Where a feature's version claim came from.

    Kept as data rather than a comment so that review is reading a
    citation instead of trusting whoever opened the pull request.
    """

    method: str
    checked: str | None = None
    symbol: str | None = None
    absent_in: str | None = None
    present_in: str | None = None
    docs: str | None = None
    file: str | None = None
    quote: str | None = None
    pep: int | None = None
    python_version: str | None = None
    absent_url: str | None = None
    present_url: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class Feature:
    """One detectable feature and the version that introduced it."""

    id: str
    name: str
    added: Version
    category: str
    or_earlier: bool = False
    pep: int | None = None
    docs: str | None = None
    nodes: frozenset[str] = frozenset()
    requires: str | None = None
    check: str | None = None
    builtins: frozenset[str] = frozenset()
    modules: frozenset[str] = frozenset()
    attributes: frozenset[str] = frozenset()
    evidence: Evidence | None = None

    @property
    def since(self) -> str:
        """How to say when this arrived, in one phrase.

        Some features are older than the oldest surviving record.
        `max()` is in the builtins table of Python 0.9.1, the first
        public release, so 0.9 is the oldest version it can be shown to
        have existed in rather than the version that added it.
        """
        return f"{self.added} or earlier" if self.or_earlier else str(self.added)

    @property
    def pep_url(self) -> str | None:
        if self.pep is None:
            return None
        return f"https://peps.python.org/pep-{self.pep:04d}/"

    @property
    def docs_url(self) -> str | None:
        """Where to read more, preferring a hand-picked link."""
        return self.docs or self.added.whatsnew_url

    @property
    def targets(self) -> frozenset[str]:
        """Every name this feature matches on, for searching."""
        return frozenset().union(*(getattr(self, field) for field in MATCHER_FIELDS))


class DatasetError(Exception):
    """The feature dataset is malformed."""


def _build_evidence(feature_id: str, entry: dict) -> Evidence:
    method = entry.get("method")
    if method not in EVIDENCE_METHODS:
        raise DatasetError(
            f"{feature_id!r} has evidence method {method!r}, "
            f"expected one of {sorted(EVIDENCE_METHODS)}"
        )
    missing = [field for field in EVIDENCE_REQUIRED[method] if not entry.get(field)]
    if missing:
        raise DatasetError(
            f"{feature_id!r} has {method} evidence missing {', '.join(missing)}"
        )
    unknown = set(entry) - {field.name for field in fields(Evidence)}
    if unknown:
        raise DatasetError(
            f"{feature_id!r} has unknown evidence fields: {', '.join(sorted(unknown))}"
        )
    return Evidence(**entry)


def _build(entry: dict) -> Feature:
    matchers = [field for field in MATCHER_FIELDS if entry.get(field)]
    if len(matchers) != 1:
        raise DatasetError(
            f"{entry.get('id', entry)!r} needs exactly one matcher kind, "
            f"got {matchers or 'none'}"
        )
    if entry.get("requires") and entry.get("check"):
        raise DatasetError(f"{entry['id']!r} sets both `requires` and `check`")
    evidence = entry.get("evidence")
    return Feature(
        id=entry["id"],
        name=entry["name"],
        added=Version.parse(entry["added"]),
        category=entry["category"],
        or_earlier=entry.get("or_earlier", False),
        pep=entry.get("pep"),
        docs=entry.get("docs"),
        nodes=frozenset(entry.get("nodes", ())),
        requires=entry.get("requires"),
        check=entry.get("check"),
        builtins=frozenset(entry.get("builtins", ())),
        modules=frozenset(entry.get("modules", ())),
        attributes=frozenset(entry.get("attributes", ())),
        evidence=_build_evidence(entry["id"], evidence) if evidence else None,
    )


def read_dataset() -> str:
    """The raw dataset text, read from the installed package."""
    return files(__package__).joinpath(DATA_FILE).read_text(encoding="utf-8")


def build_features(entries: list[dict]) -> tuple[Feature, ...]:
    """Validate raw dataset entries into `Feature` objects.

    Kept separate from `load_features` so validation can be exercised
    without going through the bundled file.
    """
    features = tuple(_build(entry) for entry in entries)
    seen = set()
    for feature in features:
        if feature.id in seen:
            raise DatasetError(f"duplicate feature id: {feature.id!r}")
        seen.add(feature.id)
    return features


@cache
def load_features() -> tuple[Feature, ...]:
    """Read and validate the bundled dataset."""
    return build_features(tomllib.loads(read_dataset())["features"])


def _matching(query: str) -> list[Feature]:
    matches = [
        feature
        for feature in load_features()
        if query in feature.id.casefold()
        or query in feature.name.casefold()
        or any(query == target.casefold() for target in feature.targets)
    ]
    return sorted(matches, key=lambda feature: (feature.added, feature.id))


def enclosing_module(query: str) -> list[Feature]:
    """The module a dotted name lives in, if the dataset knows it.

    Not every member of every module is worth an entry of its own, and
    asking about one should not come back empty when the module it
    belongs to has an answer. A member cannot be older than its module,
    so the module's version is a real answer to "how far back can I use
    `platform.system`?", just a less precise one.
    """
    prefix = query
    while "." in prefix:
        prefix = prefix.rpartition(".")[0]
        found = [
            feature
            for feature in load_features()
            if any(prefix == module.casefold() for module in feature.modules)
        ]
        if found:
            return found
    return []


def lookup(query: str) -> list[Feature]:
    """Find features matching a search term, oldest first.

    This powers search mode: a query is matched against feature ids,
    human-readable names, and the names each feature detects. A dotted
    name with no entry falls back to the module it belongs to.
    """
    query = query.casefold().strip()
    return _matching(query) or enclosing_module(query)
