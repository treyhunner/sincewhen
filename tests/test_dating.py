"""What `dating.py` refuses to answer, and how it reconciles a floor.

The guards are worth testing on their own because their whole job is to
fire before any source is consulted. The reconciliation mostly needs the
500 MB corpus and is covered by `just verify-dataset`, but `Verdict` is
a plain dataclass whose fields all default and whose `status`, `added`
and `or_earlier` are pure properties, so a verdict can be built by hand
and the ranking checked without reading anything.
"""

import dating
import pytest
from dating import Verdict, _date_the_type, date_symbol, is_keyword, removal_of


def test_a_keyword_is_refused_rather_than_answered():
    """Every keyword is a documentation anchor, and the anchor is not it.

    `in` has a `std:label` in the inventories from 2.7, so asking the
    docs about the name gives a 3.x release for an operator that is in
    the 0.9.1 grammar. The answer has to come from `grammar.py`, so this
    one refuses instead of reporting the label.
    """
    verdict = date_symbol("in")
    assert verdict.status == "keyword"
    assert verdict.added is None
    assert not verdict.or_earlier


def test_every_keyword_is_refused():
    for name in ("if", "for", "while", "return", "lambda", "not", "in", "is"):
        assert date_symbol(name).status == "keyword", name


def test_the_three_keywords_that_are_objects_are_not_refused():
    """`True`, `False` and `None` are values, not section headings.

    The refusal exists because a keyword's only presence in the
    inventories is the reference manual's anchor for it. These three
    carry a `py:data` role and no `std:label` at all, so asking the docs
    about them answers about the constant. `getattr(builtins, "True")`
    finds one, and all three were names before 3.0 made them keywords.
    """
    for name in ("True", "False", "None"):
        assert not is_keyword(name), name
        assert date_symbol(name).status != "keyword", name


def test_the_constant_keywords_the_docs_date_are_dated():
    """Two of the three, and the third stays honestly unanswered.

    `True` and `False` carry their own "New in version 2.3" marker.
    `None` predates the marker convention and carries none, so nothing
    dates it and the verdict reports no version rather than the age of
    whichever inventory first listed it.
    """
    assert date_symbol("True").added == "2.3"
    assert date_symbol("False").added == "2.3"
    assert date_symbol("None").added is None


def test_a_soft_keyword_is_still_a_name():
    """`type` is a builtin this dataset dates, and `match` is any name.

    Refusing these would throw away real answers, which is why the guard
    is the hard keyword list and not `iskeyword` plus `issoftkeyword`.
    """
    for name in ("type", "match", "case", "_"):
        assert not is_keyword(name), name


@pytest.fixture
def asked(monkeypatch):
    """Record which table keys `removal_of` reaches for, and answer none.

    The kind is the whole of what this function decides, and getting it
    wrong is silent: asking about `builtin dict.has_key` finds nothing
    and reports no removal, which looks exactly like a name that is
    still here.
    """
    seen: list[str] = []

    def fake(target):
        seen.append(target)
        return None

    monkeypatch.setattr(dating, "interpreter_removed", fake)
    return seen


def test_a_type_method_is_asked_for_as_a_method(asked):
    """The unbound spelling, which is the one that settles a removal.

    `added` deliberately never reads this column: `dict` the builtin is
    2.2 and the `dict` type is in 0.9.1, so it would date `dict.keys` to
    2.2 against the method table's 0.9. For a removal the two spellings
    agree, because a type loses a method on instances and as an unbound
    attribute in the same release.
    """
    assert removal_of("dict.has_key") is None
    assert asked == ["method dict.has_key"]


def test_a_module_member_is_asked_for_as_an_attribute_then_a_module(asked):
    """A dotted name is usually a member and sometimes a submodule."""
    assert removal_of("os.getcwdu") is None
    assert asked == ["attribute os.getcwdu", "module os.getcwdu"]


def test_a_bare_name_is_asked_for_as_a_builtin(asked):
    assert removal_of("apply") is None
    assert asked == ["builtin apply", "module apply"]


def test_a_keyword_is_refused_here_too(asked):
    """A keyword is not a symbol on this axis either.

    The table is keyed by names an interpreter can be asked about, and
    `_probe_source` cannot spell a keyword at all, so a keyword is
    absent from every column for a reason that has nothing to do with
    history. What settles syntax going away is `removed_syntax`.
    """
    assert removal_of("del") is None
    assert asked == []


def type_member(
    name: str = "memoryview.tolist",
    floor: str = "2.7",
    type_added: str = "2.7",
    type_absent_in: str | None = "2.6",
    type_is_floor: bool = False,
    annotation: str | None = None,
) -> Verdict:
    """`memoryview.tolist` as the sources leave it.

    The inventory can only bound a member of a builtin type, and 2.7 is
    the oldest one that indexes this. Built by hand so the reconciliation
    can be exercised without the 500 MB corpus behind it.
    """
    return Verdict(
        name=name,
        floor=floor,
        annotation=annotation,
        type_name="memoryview",
        type_added=type_added,
        type_absent_in=type_absent_in,
        type_is_floor=type_is_floor,
    )


def test_a_type_closes_the_bound_on_its_own_member():
    """A bound at the type's own arrival leaves nothing underneath it.

    `memoryview` is 2.7 and a method cannot predate the type that holds
    it, so `memoryview.tolist` is 2.7 rather than "2.7 or earlier". This
    is `weakref.ref` one level down.
    """
    verdict = type_member()
    assert verdict.status == "type"
    assert verdict.added == "2.7"
    assert not verdict.or_earlier


def test_a_bound_above_the_types_arrival_stays_open():
    """A bound several releases above the type dates nothing.

    This is the `bytes` and `bytearray` shape: the types are 2.6 and
    most of their methods are first indexed in 3.4, so the inventory
    bounds from above, the type floors from below, and the two do not
    meet. Those entries need a human.
    """
    verdict = type_member(floor="3.4")
    assert verdict.status == "unknown"
    assert verdict.added is None


def test_a_bounded_type_passes_its_bound_along():
    """Only a dated type closes anything, exactly as for a module."""
    verdict = type_member(type_is_floor=True)
    assert verdict.status == "unknown"


def test_a_type_with_no_release_to_point_at_closes_nothing():
    """The evidence needs a release that demonstrably lacks the type.

    `bytearray` is the case: the 2.7 inventory is the first to list it
    and the 2.7 docs date it to 2.6, so its verdict brackets on 2.6 from
    both sides and there is no older release to cite.
    """
    assert type_member(type_absent_in=None).status == "unknown"
    assert type_member(type_absent_in="2.7").status == "unknown"


def test_a_marker_about_an_argument_does_not_reopen_the_bound():
    """The marker nearest `memoryview.tobytes` dates its `order` argument.

    "Added in version 3.8: *order* can be {'C', 'F', 'A'}" is not a claim
    about when the method arrived, and the 2.7 inventory already lists
    it, so the type's own bound answers instead of the conflict.
    """
    verdict = type_member(name="memoryview.tobytes", annotation="3.8")
    assert verdict.status == "type"
    assert verdict.added == "2.7"


def test_the_head_is_not_consulted_for_a_type_the_tables_reach():
    """`dict` the builtin is 2.2 and the `dict` type is in 0.9.1.

    Reading the head as a floor would date `dict.keys` to 2.2, which is
    why this is taken only for the four types no release in the source
    corpus implements under a name anyone would call them by.
    """
    verdict = Verdict(name="dict.keys")
    _date_the_type(verdict)
    assert verdict.type_added is None


def test_the_head_is_not_consulted_for_range_either():
    """`range()` the builtin is 0.9 and the `range` type is 3.0.

    The same gap as `dict`, in one of the four types the tables miss, so
    reading the head would report "range is 0.9, so nothing in it is
    older" about a type that did not exist until 3.0.
    """
    verdict = Verdict(name="range.count")
    _date_the_type(verdict)
    assert verdict.type_added is None


def test_a_marker_dates_an_archive_floor_of_the_same_version():
    """ "Documented in 2.3 and possibly earlier" is not "New in 2.3".

    The archives can only show a name was already there by some release;
    a marker says which release put it there. They agree on the version
    and disagree on what kind of claim it is, and the sharper one wins.
    `os.mknod` is the name that reaches this: 2.3 documents it and the
    2.7 docs mark it "New in version 2.3".
    """
    verdict = Verdict(
        name="os.mknod", archive="2.3", archive_is_floor=True, annotation="2.3"
    )
    assert verdict.status == "docs-date-the-floor"
    assert verdict.added == "2.3"
    assert not verdict.or_earlier


def test_an_archive_floor_with_no_marker_stays_a_bound():
    """The neighbour that proves the rule above is not too broad."""
    verdict = Verdict(name="zlib", archive="1.5", archive_is_floor=True)
    assert verdict.status == "archive"
    assert verdict.added == "1.5"
    assert verdict.or_earlier


def test_a_marker_newer_than_the_archive_loses_to_it():
    """Presence proves presence, so a later marker cannot be right."""
    verdict = Verdict(
        name="bisect", archive="1.5", archive_is_floor=True, annotation="2.1"
    )
    assert verdict.status == "docs-overstate"
    assert verdict.added == "1.5"


def test_a_marker_older_than_the_archive_wins():
    """Not being listed proves very little, so the marker is believed."""
    verdict = Verdict(
        name="zipfile", archive="2.0", archive_is_floor=True, annotation="1.6"
    )
    assert verdict.status == "docs-predate"
    assert verdict.added == "1.6"
