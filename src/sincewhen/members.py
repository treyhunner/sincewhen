"""The member index: which members each stdlib module has, and since when.

The dataset has an entry for every member worth *detecting*, which is a
few thousand names out of a stdlib with tens of thousands. This is the
answer for the rest, and it sits strictly behind the dataset: a name with
an entry of its own is answered by that entry and never gets here.

It is not a second opinion about when things arrived. Every version in it
is `scripts/dating.py`'s verdict, worked out once at build time by the
same arbiter that rechecks every entry in the dataset, so an answer from
here is the answer an entry would carry if somebody wrote one. What it
does not carry is the evidence, which is most of what an entry is for.

The two claims an entry can make are both here, and they read the same
way. `platform.system` is 2.3, dated. `os.path.join` is "1.5 or earlier",
bounded, because no tarball has a file called `os.path` and the archives
can only say how far back they go.

Plenty of names are missing on purpose: ones the newest Python no longer
documents, ones the sources contradict each other about, and ones whose
only evidence is a 3.x inventory diff that may be dating the markup.
`scripts/memberindex.py` decides all of that, and the silence is what
sends somebody to `just whenadded`.
"""

from dataclasses import dataclass
from functools import cache
from importlib.resources import files

from .features import Feature, load_features
from .versions import Version

DATA_FILE = "members.txt"

# How many names a bare-name search offers before it stops listing them.
SUGGESTION_LIMIT = 12


@dataclass(frozen=True)
class ModuleMembers:
    """One module's member list, as the index records it.

    `bounded` is the members whose version is a limit on what the sources
    could read rather than a date, which is the same "or earlier" the
    dataset uses and means the same thing.
    """

    module: str
    members: dict[str, Version]
    bounded: frozenset[str]


@dataclass(frozen=True)
class MemberAnswer:
    """When one `module.member` arrived, as the index has it.

    `added` already accounts for the module's own date, which `_answer`
    applies on the way in, so a caller holding both should not reconcile
    them a second time. `feature` is the entry that was applied, and is
    `None` where the dataset does not date the module at all.
    """

    module: str
    name: str
    added: Version
    or_earlier: bool
    feature: Feature | None

    @property
    def dotted(self) -> str:
        return f"{self.module}.{self.name}"

    @property
    def since(self) -> str:
        """How to say when this arrived, in one phrase.

        The same two shapes a `Feature` has, for the same reasons: see
        `Feature.since`.
        """
        return f"{self.added} or earlier" if self.or_earlier else str(self.added)


def read_index() -> str:
    """The raw index text, read from the installed package."""
    return files(__package__).joinpath(DATA_FILE).read_text(encoding="utf-8")


def parse_index(text: str) -> dict[str, ModuleMembers]:
    """Read the index file into one record per module.

    The format is one module per line: its name, then a release and the
    members that arrived in it, over and over. A release spelled with a
    trailing `?` could only be bounded. Grouping by release is what keeps
    the file to 48 KB, and being a text file is what keeps a regenerated
    index reviewable as a diff.
    """
    index = {}
    for line in text.splitlines():
        if not line or line.startswith("#"):
            continue
        module, *rest = line.split()
        members, bounded = {}, set()
        for tag, names in zip(rest[::2], rest[1::2], strict=True):
            version = Version.parse(tag.rstrip("?"))
            for name in names.split(","):
                members[name] = version
                if tag.endswith("?"):
                    bounded.add(name)
        index[module] = ModuleMembers(
            module=module, members=members, bounded=frozenset(bounded)
        )
    return index


@cache
def load_index() -> dict[str, ModuleMembers]:
    """Read the bundled member index."""
    return parse_index(read_index())


@cache
def _module_features() -> dict[str, Feature]:
    """The dataset entry for each module, by module name.

    The first entry wins, which is only a tie-break: no module in the
    dataset is claimed by two entries, and one that was would be a
    curation mistake rather than something to reconcile here.
    """
    found: dict[str, Feature] = {}
    for feature in load_features():
        for module in feature.modules:
            found.setdefault(module, feature)
    return found


def _answer(module: str, name: str) -> MemberAnswer | None:
    """One member's answer, with its module's own date applied.

    A member cannot predate the module that holds it, so where the two
    disagree the module is the binding constraint. The index is built
    without reading the dataset, on purpose, so this is the one place
    both numbers are in hand.

    `copyreg` is what reaches it. The module is 3.0 because PEP 3108
    renamed it and no earlier release can import that spelling, while
    its members are dated from `copy_reg`'s history and come out at
    "1.5 or earlier". That is the rename rule in `AGENTS.md` one level
    down, and letting it through would date `copyreg.pickle` five
    releases before the name existed.
    """
    record = load_index().get(module)
    if record is None or name not in record.members:
        return None
    added, or_earlier = record.members[name], name in record.bounded
    feature = _module_features().get(module)
    if feature is not None and added < feature.added:
        added, or_earlier = feature.added, feature.or_earlier
    return MemberAnswer(
        module=module,
        name=name,
        added=added,
        or_earlier=or_earlier,
        feature=feature,
    )


def lookup_member(query: str) -> MemberAnswer | None:
    """What the index says about a dotted name, if anything.

    The longest module prefix wins, so `os.path.join` is answered by
    `os.path` rather than by `os`. Only a direct member is answered:
    `logging.handlers.RotatingFileHandler.doRollover` is a question
    about a class, and the index is about what a module binds.
    """
    module, _, name = query.rpartition(".")
    return _answer(module, name) if module and name else None


def find_members(name: str) -> list[MemberAnswer]:
    """Every module with a member of this name, oldest first.

    This is what makes a bare name searchable. Nobody types
    `platform.system` into a search box, and until the index existed
    a bare `system` had nothing to match, since a module member is
    written dotted wherever it appears and the dataset looks its
    members up by the whole dotted name.
    """
    answers = [
        answer
        for module in load_index()
        if (answer := _answer(module, name)) is not None
    ]
    return sorted(answers, key=lambda answer: (answer.added, answer.dotted))
