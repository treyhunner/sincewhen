"""Tests for the per-module member index."""

from sincewhen.features import has_entry, load_features
from sincewhen.members import (
    ModuleMembers,
    find_members,
    load_index,
    lookup_member,
    parse_index,
    read_index,
)
from sincewhen.versions import Version

SAMPLE = """\
# a comment

platform 2.3 system,uname 3.8 win32_edition
operator 1.4? add,sub
"""


def test_parse_reads_one_record_per_module():
    index = parse_index(SAMPLE)
    assert set(index) == {"platform", "operator"}
    assert index["platform"] == ModuleMembers(
        module="platform",
        members={
            "system": Version(2, 3),
            "uname": Version(2, 3),
            "win32_edition": Version(3, 8),
        },
        bounded=frozenset(),
    )


def test_parse_reads_a_bound():
    """`1.4?` is "1.4 or earlier", which is a different claim from 1.4."""
    record = parse_index(SAMPLE)["operator"]
    assert record.members["add"] == Version(1, 4)
    assert record.bounded == {"add", "sub"}


def test_shipped_index_parses():
    index = load_index()
    assert len(index) > 100
    assert "system" in index["platform"].members


def test_shipped_index_is_sorted_and_unrepeated():
    """A generated file nobody can diff is a file nobody reviews."""
    lines = [
        line for line in read_index().splitlines() if line and not line.startswith("#")
    ]
    modules = [line.split()[0] for line in lines]
    assert modules == sorted(modules)
    assert len(modules) == len(set(modules))


def test_lookup_takes_the_longest_module_prefix():
    found = lookup_member("os.path.join")
    assert found is not None
    assert found.module == "os.path"
    assert found.name == "join"


def test_lookup_ignores_a_bare_name():
    assert lookup_member("system") is None


def test_lookup_ignores_an_unknown_member():
    assert lookup_member("platform.no_such_member") is None
    assert lookup_member("no_such_module.thing") is None


def test_platform_system_is_dated_not_bounded():
    """The example the index exists for.

    `platform` shipped in 2.3, the 2.3 doc build has no page for it, and
    `Lib/platform.py` in the 2.3 tarball binds `system`. So the answer is
    2.3 exactly rather than "somewhere at or after 2.3".
    """
    found = lookup_member("platform.system")
    assert found is not None
    assert not found.or_earlier
    assert found.since == "2.3"


def test_a_member_the_docs_date_gets_that_date():
    """`os.path.relpath` is recorded from 2.6 only because 2.6 is the
    oldest inventory there is, and the docs say "New in version 2.6"."""
    found = lookup_member("os.path.relpath")
    assert found is not None
    assert found.since == "2.6"


def test_a_member_nothing_can_date_says_so():
    """`os.path` is a bound and nothing in it can be sharper than one."""
    found = lookup_member("os.path.join")
    assert found is not None
    assert found.or_earlier
    assert found.since == "1.5 or earlier"


def test_find_members_searches_every_module():
    found = {answer.dotted for answer in find_members("system")}
    assert {"os.system", "platform.system"} <= found


def test_find_members_is_empty_for_an_unknown_name():
    assert find_members("no_such_member_anywhere") == []


def test_find_members_is_ordered_oldest_first():
    versions = [answer.added for answer in find_members("read")]
    assert versions == sorted(versions)


def test_a_member_carries_its_modules_entry_for_context():
    found = lookup_member("platform.system")
    assert found is not None
    assert found.feature is not None
    assert found.feature.id == "platform"


def test_a_module_with_no_entry_still_answers():
    found = lookup_member("curses.ascii.isalnum")
    assert found is not None
    assert found.feature is None
    assert found.since


def test_the_unreadable_module_is_left_out():
    """`__future__` documents its features as a table of objects.

    No name in it carries a marker and none was given an inventory entry
    until 3.13, so every method here would date the markup: `division`
    would read as 3.13 rather than 2.2.
    """
    assert "__future__" not in load_index()


def test_a_member_cannot_predate_its_module():
    """`copyreg` is 3.0 as spelled; its members are older than the name.

    PEP 3108 renamed `copy_reg`, so nothing before 3.0 can import this
    spelling, but the index dates its members from the old name's
    history and comes back with "1.5 or earlier". The module is the
    binding constraint, so the answer is 3.0.
    """
    found = lookup_member("copyreg.pickle")
    assert found is not None
    assert found.since == "3.0"
    assert not found.or_earlier


def test_a_stale_index_is_clamped_at_lookup(monkeypatch):
    """The module's entry is the binding constraint even on a stale index.

    The generator applies the same rule from the pipeline's own module
    dates, so a freshly written file never carries this. An entry can
    say something the pipeline cannot, though, since a manual correction
    outranks it, and the answer must not depend on which of the two
    caught the disagreement first.
    """
    stale = parse_index("copyreg 1.5? constructor,pickle\n")
    monkeypatch.setattr("sincewhen.members.load_index", lambda: stale)
    found = lookup_member("copyreg.pickle")
    assert found is not None
    assert found.since == "3.0"
    assert not found.or_earlier


# No name the index and the dataset both date is in disagreement.
# `importlib.import_module` used to be the one exception: the index said
# 2.7 from the inventories' presence and the entry said 3.1 from the
# release that first documented it. Building the 3.x interpreters and
# asking them settled it at 2.7, so the entry moved and the exception
# closed.
PIPELINE_BUG: frozenset[str] = frozenset()


def test_the_index_agrees_with_the_dataset_where_both_speak():
    """The load-bearing check on the whole index.

    Every version here is `dating.py`'s verdict, and the dataset's
    versions are re-derived from the same arbiter by `verify-dataset`.
    So wherever a member has an entry of its own, the two have to give
    the same answer, and a difference means the index is reading the
    pipeline differently from the way the dataset was built.
    """
    both = [
        (feature, found)
        for feature in load_features()
        for name in feature.attributes
        if (found := lookup_member(name)) is not None
    ]
    assert len(both) > 1200
    assert {
        found.dotted
        for feature, found in both
        if (found.added, found.or_earlier) != (feature.added, feature.or_earlier)
    } == PIPELINE_BUG


def test_the_dataset_answers_first_for_a_name_it_dates():
    """The index sits behind the entries and never in front of them."""
    assert has_entry("platform.platform")
    assert lookup_member("platform.platform") is not None
