"""Tests for the per-module member index."""

from sincewhen.features import has_entry, load_features
from sincewhen.members import (
    OwnerMembers,
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
    assert index["platform"] == OwnerMembers(
        owner="platform",
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
    assert found.owner == "os.path"
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


def test_a_class_is_an_owner_like_a_module():
    """The question that started the class tier off.

    `unittest.TestCase.assertNotEndsWith` came back with nothing at all,
    because the index stopped at what a module binds and a method
    belongs to the class above it.
    """
    found = lookup_member("unittest.TestCase.assertNotEndsWith")
    assert found is not None
    assert found.owner == "unittest.TestCase"
    assert found.name == "assertNotEndsWith"
    assert found.since == "3.14"


def test_a_class_member_is_searchable_by_its_own_name():
    """Nobody types the class in front of the method they want."""
    found = {answer.dotted for answer in find_members("subTest")}
    assert found == {"unittest.TestCase.subTest"}


def test_a_member_of_a_member_has_no_owner_to_be_indexed_under():
    """`inspect.Parameter.kind.description` is one cut too deep.

    A class is the last owner this index knows how to name, so an
    attribute of an attribute is left out rather than filed under
    something invented for it.
    """
    assert "inspect.Parameter.kind" not in load_index()


def test_a_class_member_the_inventories_alone_date_is_left_out():
    """The class tier's own version of the `_publish` rule.

    A class page lists what the class inherits alongside what it
    defines, and grows a member at a time, so the release that first
    indexes one is often the age of the markup. `pathlib.Path.as_uri`
    reads as 3.13, which is when the method moved down from `PurePath`;
    `enum.Enum.name` reads as 3.11 against a class that is 3.4. Neither
    is corroborated by a marker, so neither is published and search
    falls back to the module.
    """
    for name in ("pathlib.Path.as_uri", "enum.Enum.name", "logging.Logger.name"):
        assert lookup_member(name) is None, name


def test_a_class_member_the_source_dates_is_dated_exactly():
    """The question the class tier was built to stop dodging.

    `assertAlmostEqual` was already in the 2.6 inventory, the oldest
    there is, so no diff can date it and none of the methods that reach
    further back can see a class member. Reading the class bodies in
    `Lib/unittest.py` settles it outright: absent from 2.1 and 2.2,
    bound in 2.3 by `assertAlmostEqual = assertAlmostEquals =
    failUnlessAlmostEqual`.
    """
    found = lookup_member("unittest.TestCase.assertAlmostEqual")
    assert found is not None
    assert found.since == "2.3"
    assert not found.or_earlier


def test_a_class_member_as_old_as_its_module_is_not_bounded():
    """`unittest` is 2.1, so a member floored there is dated there.

    The bound closes because there is nothing under it: a member cannot
    predate the module that holds it. Same rule as `weakref.ref`, two
    levels down.
    """
    found = lookup_member("unittest.TestCase.setUp")
    assert found is not None
    assert found.since == "2.1"


def test_a_class_member_a_marker_corroborates_is_published():
    """The other side of it: a marker is what makes one publishable.

    `pathlib.Path.walk` is 3.12 in the inventory and the docs say so
    too, so it survives the rule that drops `as_uri`.
    """
    found = lookup_member("pathlib.Path.walk")
    assert found is not None
    assert found.since == "3.12"


def test_a_module_with_no_entry_still_answers():
    found = lookup_member("_thread.TIMEOUT_MAX")
    assert found is not None
    assert found.feature is None
    assert found.since


def test_a_member_carries_the_entry_for_the_module_it_lives_in():
    """The owner is not always the module, so the module is walked to.

    `curses.ascii` has no entry and `curses` has one, and a member of a
    submodule cannot predate the package any more than a method can
    predate its class. Reaching only the owner meant a class member
    never found its module at all, which is where `copyreg`'s rename
    would have stopped applying.
    """
    found = lookup_member("curses.ascii.isalnum")
    assert found is not None
    assert found.feature is not None
    assert found.feature.id == "curses"


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
        for name in feature.attributes | feature.methods
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
