"""The feature dataset: what each feature is and when it arrived."""

import tomllib
from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from .versions import Version

DATA_FILE = "features.toml"

MATCHER_FIELDS = ("nodes", "builtins", "modules", "attributes")


@dataclass(frozen=True)
class Feature:
    """One detectable feature and the version that introduced it."""

    id: str
    name: str
    added: Version
    category: str
    pep: int | None = None
    docs: str | None = None
    nodes: frozenset[str] = frozenset()
    requires: str | None = None
    check: str | None = None
    builtins: frozenset[str] = frozenset()
    modules: frozenset[str] = frozenset()
    attributes: frozenset[str] = frozenset()

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


def _build(entry: dict) -> Feature:
    matchers = [field for field in MATCHER_FIELDS if entry.get(field)]
    if len(matchers) != 1:
        raise DatasetError(
            f"{entry.get('id', entry)!r} needs exactly one matcher kind, "
            f"got {matchers or 'none'}"
        )
    if entry.get("requires") and entry.get("check"):
        raise DatasetError(f"{entry['id']!r} sets both `requires` and `check`")
    return Feature(
        id=entry["id"],
        name=entry["name"],
        added=Version.parse(entry["added"]),
        category=entry["category"],
        pep=entry.get("pep"),
        docs=entry.get("docs"),
        nodes=frozenset(entry.get("nodes", ())),
        requires=entry.get("requires"),
        check=entry.get("check"),
        builtins=frozenset(entry.get("builtins", ())),
        modules=frozenset(entry.get("modules", ())),
        attributes=frozenset(entry.get("attributes", ())),
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


def lookup(query: str) -> list[Feature]:
    """Find features matching a search term, oldest first.

    This powers search mode: a query is matched against feature ids,
    human-readable names, and the names each feature detects.
    """
    query = query.casefold().strip()
    matches = [
        feature
        for feature in load_features()
        if query in feature.id.casefold()
        or query in feature.name.casefold()
        or any(query == target.casefold() for target in feature.targets)
    ]
    return sorted(matches, key=lambda feature: (feature.added, feature.id))
