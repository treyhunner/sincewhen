"""The feature dataset: what each feature is and when it arrived."""

import tomllib
from dataclasses import dataclass, fields
from functools import cache
from importlib.resources import files

from .versions import Version

DATA_FILE = "features.toml"

MATCHER_FIELDS = ("nodes", "builtins", "modules", "attributes", "methods", "spellings")

# The one matcher kind that matches nothing. A `spellings` entry names a
# way of writing something that a Python 3.14 parser cannot produce a
# node for, because 3.0 took the syntax away: `<>`, the `print`
# statement, the `exec` statement. Detecting those would mean shipping
# old parsers, which is a different project, so the entry is searchable
# and never detectable.
#
# It is a matcher field rather than an absence of one so that the "exactly
# one matcher kind" rule keeps holding, and so that the spelling lands in
# `targets` and search can find it. `detect.py` builds no index from it,
# which is the whole of how it stays undetectable.
SEARCH_ONLY_FIELDS = frozenset({"spellings"})

# How a version claim was established. Each method says what a reviewer
# has to do to check it: the first three are machine-checkable against
# archived documentation, and `manual` is the one that needs a human.
#
#   objects.inv  the symbol is absent from one release's Sphinx
#                inventory and present in the next
#   archive      the same diff for the era before Sphinx, over the
#                module lists and built-in function pages in the
#                archived HTML doc builds
#   source       the same diff over the tables CPython registers names
#                from: `builtin_methods[]` in `bltinmodule.c`, a
#                module's own method table, and a builtin type's. It
#                reaches back to 0.9.1 and so predates every doc build.
#                Alone among these, its absences count for as much as
#                its presences, because such a table is the list the
#                interpreter builds a namespace from rather than a
#                description of one. It is the only thing that dates a
#                method as old as `dict.setdefault`, which no doc build
#                ever marked
#   interpreter  the name was asked of that release's own interpreter,
#                built from its pinned tarball, and resolved. The only
#                method that reads Python rather than a description of
#                it, so it sees what no text can: a name filtered out of
#                a star-import by `__all__`, a module that ships and
#                raises on import, a C extension the build config
#                decides. Its absences are guarded, because a module
#                missing from a build is not a module missing from a
#                release
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
    {
        "objects.inv",
        "archive",
        "source",
        "interpreter",
        "grammar",
        "annotation",
        "pep",
        "manual",
    }
)

EVIDENCE_REQUIRED = {
    "objects.inv": ("symbol", "absent_in", "present_in"),
    "archive": ("present_in",),
    "source": ("symbol", "file", "present_in"),
    "interpreter": ("symbol", "present_in"),
    "grammar": ("symbol", "present_in"),
    "annotation": ("docs", "quote"),
    "pep": ("pep", "python_version"),
    "manual": ("note",),
}

# Which methods may settle a *removal*, which is a much shorter list, and
# short for two separate reasons.
#
# Three of them cannot see one at all. `source`, `archive` and the type
# method tables all stop at 2.5, and every removal this dataset records
# happened in 3.0 or later, so a corpus that ends before the removal has
# nothing to say about it.
#
# `objects.inv` and `annotation` can see the releases in question and are
# still refused, because of the rule the whole project turns on: presence
# is strong evidence and absence is weak. A removal *is* an absence
# claim, so the two methods whose absences prove nothing are exactly the
# two that cannot make it. The archives are full of names that vanish
# from an index because the markup changed, and a doc build that stops
# mentioning something has not thereby removed it.
#
# That leaves the two methods whose absences are proof. A built
# interpreter is the thing itself: a name it cannot resolve is a name
# that build did not have. A grammar is the list the parser is generated
# from rather than a description of one, which is the `builtin_methods[]`
# argument applied to syntax. `manual` remains the escape hatch, and
# `<>` is why it has to: see `barry_as_FLUFL` in AGENTS.md.
REMOVAL_EVIDENCE_METHODS = frozenset({"interpreter", "grammar", "manual"})

# Both fields are required, unlike the addition side, because a removal
# is always bracketed. `added` can be a floor, since the corpus may not
# reach far enough back to find a release without the name; `removed`
# never can, since the corpus ends at the newest Python and a name absent
# from that end has a last release somewhere inside the corpus. So there
# is no "or later" to match `or_earlier`, and both sides of the bracket
# are always known.
REMOVAL_EVIDENCE_REQUIRED = {
    "interpreter": ("symbol", "present_in", "absent_in"),
    "grammar": ("symbol", "present_in", "absent_in"),
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
    removed: Version | None = None
    pep: int | None = None
    docs: str | None = None
    nodes: frozenset[str] = frozenset()
    requires: str | None = None
    check: str | None = None
    builtins: frozenset[str] = frozenset()
    modules: frozenset[str] = frozenset()
    attributes: frozenset[str] = frozenset()
    methods: frozenset[str] = frozenset()
    spellings: frozenset[str] = frozenset()
    evidence: Evidence | None = None
    removed_evidence: Evidence | None = None

    @property
    def since(self) -> str:
        """How to say when this arrived, in one phrase.

        Some features cannot be dated, only bounded, and those say so:
        `zlib` is "1.5 or earlier", which leaves a real question open,
        since 1.0 through 1.4 all exist and one of them is the answer.

        The first public release needs no such hedge and gets no such
        phrase. `max()` is in the builtins table of Python 0.9.1 and may
        well be older, but there is no earlier Python to have been added
        in: nothing has been in the language longer than the language
        has been public. So those entries are dated rather than bounded,
        and 0.9 reads like any other version, with 1991-02-20 in the
        released column saying how long ago that was. Their evidence
        still records that the name is at least that old and may predate
        the public record.

        A feature that was taken away says so at the end, and says it in
        words rather than as a range. "0.9 to 3.0" is the tempting
        spelling and it is wrong at both ends: it reads as inclusive,
        when 3.0 is precisely the release that does *not* have
        `dict.has_key`, and it does not survive a bound on the other
        side, where "1.5 or earlier to 3.0" stops being a sentence.
        "removed in" composes with both.
        """
        arrived = f"{self.added} or earlier" if self.or_earlier else str(self.added)
        if self.removed is None:
            return arrived
        return f"{arrived}, removed in {self.removed}"

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


def _build_evidence(feature_id: str, entry: dict, *, removal: bool = False) -> Evidence:
    """Validate one evidence table, for whichever axis it justifies.

    The two axes share the `Evidence` shape and read two of its fields
    the same way round: `absent_in` and `present_in` are always the two
    adjacent releases that bracket the change, and the entry's version is
    whichever of them is on the far side of it. For an addition the far
    side is presence, so `added` is `present_in`; for a removal it is
    absence, so `removed` is `absent_in`. Nothing else needed a second
    vocabulary.
    """
    label = "removal evidence" if removal else "evidence"
    methods = REMOVAL_EVIDENCE_METHODS if removal else EVIDENCE_METHODS
    required = REMOVAL_EVIDENCE_REQUIRED if removal else EVIDENCE_REQUIRED
    method = entry.get("method")
    if method not in methods:
        raise DatasetError(
            f"{feature_id!r} has {label} method {method!r}, "
            f"expected one of {sorted(methods)}"
        )
    missing = [field for field in required[method] if not entry.get(field)]
    if missing:
        raise DatasetError(
            f"{feature_id!r} has {method} {label} missing {', '.join(missing)}"
        )
    unknown = set(entry) - {field.name for field in fields(Evidence)}
    if unknown:
        raise DatasetError(
            f"{feature_id!r} has unknown {label} fields: {', '.join(sorted(unknown))}"
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
    added = Version.parse(entry["added"])
    removed = Version.parse(entry["removed"]) if entry.get("removed") else None
    if removed is not None and removed <= added:
        raise DatasetError(
            f"{entry['id']!r} is removed in {removed} and added in {added}; "
            "a feature cannot be taken away before it arrives"
        )
    removed_evidence = entry.get("removed_evidence")
    if removed_evidence and removed is None:
        raise DatasetError(f"{entry['id']!r} cites a removal it does not claim")
    evidence = entry.get("evidence")
    return Feature(
        id=entry["id"],
        name=entry["name"],
        added=added,
        category=entry["category"],
        or_earlier=entry.get("or_earlier", False),
        removed=removed,
        pep=entry.get("pep"),
        docs=entry.get("docs"),
        nodes=frozenset(entry.get("nodes", ())),
        requires=entry.get("requires"),
        check=entry.get("check"),
        builtins=frozenset(entry.get("builtins", ())),
        modules=frozenset(entry.get("modules", ())),
        attributes=frozenset(entry.get("attributes", ())),
        methods=frozenset(entry.get("methods", ())),
        spellings=frozenset(entry.get("spellings", ())),
        evidence=_build_evidence(entry["id"], evidence) if evidence else None,
        removed_evidence=_build_evidence(entry["id"], removed_evidence, removal=True)
        if removed_evidence
        else None,
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
        or any(query == _method_name(target) for target in feature.methods)
    ]
    return sorted(matches, key=lambda feature: (feature.added, feature.id))


def _method_name(target: str) -> str:
    """A method's own name, without the type it hangs off.

    A method is looked up by the name it is called by. Nobody searching
    for `removeprefix` types `str.removeprefix`, because the type is not
    part of how the method is written at the call site, so both spellings
    find the entry.

    Module members are deliberately left out: `math.isclose` is written
    dotted wherever it appears, so a bare `isclose` is a fuzzier kind of
    search than this, and one that would have to rank its answers.
    """
    return target.rpartition(".")[2].casefold()


@cache
def _targets() -> frozenset[str]:
    return frozenset().union(*(feature.targets for feature in load_features()))


def has_entry(name: str) -> bool:
    """Whether some entry matches this exact name.

    Search offers the member index alongside the dataset for a bare
    name, and a member the dataset already dates should not be listed
    twice, once as an entry and once as a suggestion.
    """
    return name in _targets()


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
    human-readable names, and the names each feature detects. A method of
    a builtin type also answers to its own name, so `removeprefix` finds
    `str.removeprefix`. A dotted name with no entry falls back to the
    module it belongs to.
    """
    query = query.casefold().strip()
    return _matching(query) or enclosing_module(query)
