"""Tests for the feature dataset itself."""

import builtins

import pytest

from sincewhen import Version, load_features, lookup
from sincewhen.detect import CHECKS, _Index, minimum_version
from sincewhen.features import (
    EVIDENCE_METHODS,
    EVIDENCE_REQUIRED,
    MATCHER_FIELDS,
    REMOVAL_EVIDENCE_METHODS,
    REMOVAL_EVIDENCE_REQUIRED,
    SEARCH_ONLY_FIELDS,
    DatasetError,
    _build,
    build_features,
    read_dataset,
)


def entry(**overrides):
    """A minimal valid dataset entry."""
    return {
        "id": "example",
        "name": "example",
        "added": "3.0",
        "category": "syntax",
        "nodes": ["Pass"],
    } | overrides


def test_dataset_loads():
    features = load_features()
    assert len(features) > 50


def test_ids_are_unique():
    ids = [feature.id for feature in load_features()]
    assert len(ids) == len(set(ids))


def test_every_feature_has_exactly_one_matcher_kind():
    for feature in load_features():
        matchers = [field for field in MATCHER_FIELDS if getattr(feature, field)]
        assert len(matchers) == 1, feature.id


def test_named_checks_exist():
    for feature in load_features():
        if feature.check:
            assert feature.check in CHECKS, feature.id


def test_categories_are_known():
    known = {
        "syntax",
        "builtin",
        "exception",
        "module",
        "class",
        "function",
        "method",
        "constant",
    }
    for feature in load_features():
        assert feature.category in known, feature.id


def covered_attributes():
    """Every member entry paired with its module's entry, where there is one."""
    modules = {name: feature for feature in load_features() for name in feature.modules}
    for feature in load_features():
        for name in feature.attributes:
            parts = name.split(".")
            covering = next(
                (
                    modules[".".join(parts[:size])]
                    for size in range(len(parts) - 1, 0, -1)
                    if ".".join(parts[:size]) in modules
                ),
                None,
            )
            if covering is not None:
                yield feature, covering


def test_no_attribute_predates_its_module():
    """A module member cannot be older than the module it lives in."""
    for feature, module in covered_attributes():
        assert module.added <= feature.added, (feature.id, module.id)


def test_no_attribute_is_bounded_below_a_dated_module():
    """A bound at the module's own arrival is not a bound at all.

    "`weakref` arrived in 2.1" and "`weakref.ref` is 2.1 or earlier" are
    not both sayable: a member cannot predate its module, so there is
    nothing under 2.1 left for the member to reach. `weakref.ref` is 2.1
    exactly.

    A module that is itself bounded passes the bound along instead of
    closing it, which is why `operator.add` is still "1.5 or earlier".
    """
    for feature, module in covered_attributes():
        if module.or_earlier or module.added != feature.added:
            continue
        assert not feature.or_earlier, (feature.id, module.id)


def test_methods_hang_off_a_builtin_type():
    """A `methods` target is `type.method`, and the type is a builtin.

    The matcher exists for methods of the builtin types, and detection
    reads the receiver's type to decide whether to fire. A module member
    that found its way in here would simply never match anything.
    """
    for feature in load_features():
        for name in feature.methods:
            type_name, _, method = name.partition(".")
            assert method and "." not in method, name
            assert isinstance(getattr(builtins, type_name, None), type), name


def test_every_method_is_where_its_entry_says_it_is():
    """`added` and `removed` are both claims the running Python can check.

    An entry with no `removed` says the method has been available ever
    since, so a method this Python does not have is either a typo or a
    Python 2 name that 3.0 took away. An entry with `removed` says the
    opposite, and has to mean it: a name that is still here is not a name
    that went away, and an entry claiming otherwise would report a
    removal for code that runs fine.

    This is the cheapest check either claim gets, and the only one that
    needs neither the cache nor the interpreter corpus. It is also the
    one that will fail first when some future Python drops a method,
    which is the point: the dataset should not be able to go stale
    quietly in either direction.

    The special methods are exempt, because `object` documents most of
    them as a protocol rather than implementing them. Nothing has
    `__length_hint__` until a class opts into it.
    """
    for feature in load_features():
        for name in feature.methods:
            type_name, _, method = name.partition(".")
            if method.startswith("__"):
                continue
            here = hasattr(getattr(builtins, type_name), method)
            if feature.removed is None:
                assert here, name
            else:
                assert not here, (name, f"claims removal in {feature.removed}")


# The four types no release from 0.9.1 to 2.5 implements under a name
# anyone would call them by, so `typemethods.LINEAGE` leaves them out.
# What the tables cannot reach, the types' own arrivals answer for.
#
# Each maps to the release the type itself arrived in, which is the floor
# under everything spelled `type.method`. Written out rather than read
# off the dataset's own `builtins` entries, because two of the four
# cannot be: `bytes` has no entry at all, and `range()` the builtin is
# 0.9 while the `range` type is 3.0.
UNCOVERED_TYPES = {
    "bytes": Version(2, 6),
    "bytearray": Version(2, 6),
    "memoryview": Version(2, 7),
    "range": Version(3, 0),
}


def test_every_method_of_the_types_the_tables_miss_is_dated():
    """Silence in `typemethods.py` is not licence to be silent here.

    `bytes` and `bytearray` are 2.6, `memoryview` is 2.7 and the `range`
    type is 3.0, so no release in the source corpus carries a method
    table for any of them. That is a decision about the derivation and
    not about the dataset: a method cannot predate the type that holds
    it, which dates every one of these.

    Attributes are a different matcher and out of this: `range.start` and
    `memoryview.itemsize` are not methods, which is what `callable`
    separates.

    This asks the running interpreter, so a Python that adds a method to
    one of these types fails the build until an entry exists for it. That
    is deliberate and not rare: 3.7 added `isascii`, 3.9 `removeprefix`
    and `removesuffix`, 3.14 `bytearray.resize`. The project already
    needs a release per Python feature release.
    """
    dated = {name for feature in load_features() for name in feature.methods}
    for type_name in UNCOVERED_TYPES:
        the_type = getattr(builtins, type_name)
        for member in dir(the_type):
            if member.startswith("_"):
                continue
            if not callable(getattr(the_type, member)):
                continue
            assert f"{type_name}.{member}" in dated, (
                f"{type_name}.{member} has no entry; add one, or add its type "
                "to UNCOVERED_TYPES if the tables now reach it"
            )


def test_no_method_of_a_modern_type_predates_that_type():
    """`bytearray` is 2.6, so nothing spelled `bytearray.x` is older.

    This is the guard on the one mistake AGENTS.md names by name: reading
    the 2.x string table for `bytes` dates `bytes.capitalize` to 1.6,
    five releases before anything could be spelled b"...". Those entries
    carry `manual` evidence, which `verify-dataset` does not re-derive,
    so nothing else checks the number.

    Only for these four. `dict.keys` is 0.9 while `dict` the builtin is
    2.2, because a method entry from that era is a claim about instances
    rather than about the type.
    """
    for feature in load_features():
        for name in feature.methods:
            floor = UNCOVERED_TYPES.get(name.partition(".")[0])
            if floor is None:
                continue
            assert floor <= feature.added, (feature.id, name)


def test_a_byte_method_is_no_older_than_the_same_method_on_str():
    """2.6's `bytes` is `str`, so `bytes.x` cannot beat `str.x` to it.

    The other half of the argument the `bytes` entries rest on: the type
    is the binding constraint only if every method it shares with `str`
    is already dated at or before the type's own arrival.
    """
    dated = {
        name: feature.added for feature in load_features() for name in feature.methods
    }
    for name, added in dated.items():
        type_name, _, method = name.partition(".")
        if type_name not in {"bytes", "bytearray"}:
            continue
        on_str = dated.get(f"str.{method}")
        if on_str is not None:
            assert on_str <= added, name


def test_the_types_dated_from_their_head_are_the_ones_the_tables_miss():
    """The exclusion list exists twice, and the two have to agree.

    `dating._date_the_type` reads the head of a name for every builtin
    type `typemethods` does not speak for, which is a set neither module
    writes down. Adding a type to `BUILTIN_TYPES` without adding it to
    `LINEAGE` would silently enrol it in head-based dating, and that
    direction produces version numbers rather than failures.
    """
    import dating
    import typemethods

    assert dating.BUILTIN_TYPES - set(typemethods.LINEAGE) == set(UNCOVERED_TYPES)


def test_lookup_finds_a_method_by_its_own_name():
    """Nobody searching for a method types the type in front of it."""
    assert [f.id for f in lookup("removeprefix")] == ["str-removeprefix"]
    assert lookup("str.removeprefix") == lookup("removeprefix")
    assert [f.id for f in lookup("is_integer")] == [
        "float-is-integer",
        "int-is-integer",
    ]


def test_lookup_finds_a_special_method_by_its_dunder_name():
    assert [f.id for f in lookup("__set_name__")] == ["object-set-name"]


def test_versions_are_plausible():
    """0.9 is the floor: Python 0.9.1 is the oldest release there is."""
    for feature in load_features():
        assert Version(0, 9) <= feature.added <= Version(3, 99), feature.id


def test_pep_urls_are_zero_padded():
    (feature,) = [f for f in load_features() if f.id == "walrus"]
    assert feature.pep_url == "https://peps.python.org/pep-0572/"


def test_docs_url_defaults_to_whatsnew():
    (feature,) = [f for f in load_features() if f.id == "tomllib"]
    assert feature.docs_url == "https://docs.python.org/3/whatsnew/3.11.html"


def test_lookup_by_id():
    assert [f.id for f in lookup("walrus")] == ["walrus"]


def test_lookup_by_name():
    assert "match-statement" in {f.id for f in lookup("match")}


def test_lookup_by_target_name():
    """A target name matches exactly, where a display name matches loosely."""
    results = [f.id for f in lookup("sum")]
    assert results[0] == "sum"
    assert "math-sumprod" in results


def test_lookup_is_case_insensitive():
    assert lookup("TOMLLIB") == lookup("tomllib")


def test_lookup_orders_oldest_first():
    results = lookup("module")
    assert results == sorted(results, key=lambda f: (f.added, f.id))


def test_lookup_with_no_matches():
    assert lookup("no-such-feature") == []


def test_lookup_falls_back_to_the_enclosing_module():
    """A member with no entry is answered by the module it lives in."""
    assert not [f for f in load_features() if "platform.system" in f.attributes]
    assert [f.id for f in lookup("platform.system")] == ["platform"]


def test_lookup_falls_back_through_a_dotted_package():
    assert [f.id for f in lookup("importlib.resources.nonesuch")] == [
        "importlib-resources"
    ]


def test_lookup_gives_up_when_no_module_matches():
    assert lookup("nosuchmodule.member") == []


def test_missing_matcher_is_rejected():
    with pytest.raises(DatasetError, match="exactly one matcher"):
        _build({"id": "x", "name": "x", "added": "3.0", "category": "syntax"})


def test_multiple_matchers_are_rejected():
    with pytest.raises(DatasetError, match="exactly one matcher"):
        _build(
            {
                "id": "x",
                "name": "x",
                "added": "3.0",
                "category": "syntax",
                "nodes": ["Name"],
                "builtins": ["sum"],
            }
        )


def test_duplicate_ids_are_rejected():
    with pytest.raises(DatasetError, match="duplicate feature id"):
        build_features([entry(), entry()])


def test_build_features_accepts_distinct_ids():
    features = build_features([entry(id="a"), entry(id="b")])
    assert [feature.id for feature in features] == ["a", "b"]


def test_read_dataset_returns_the_toml_source():
    assert "[[features]]" in read_dataset()


def test_pep_url_is_none_without_a_pep():
    (feature,) = [f for f in load_features() if f.id == "sorted"]
    assert feature.pep is None
    assert feature.pep_url is None


def test_every_feature_cites_its_evidence():
    for feature, evidence in cited():
        assert evidence.method in EVIDENCE_METHODS, feature.id


def cited():
    """Every feature with its evidence, which the dataset always has.

    `Feature.evidence` is optional in the type, since a feature built in
    memory need not cite anything, so each test that reads it says out
    loud that the shipped dataset does.
    """
    for feature in load_features():
        assert feature.evidence is not None, feature.id
        yield feature, feature.evidence


def test_evidence_carries_what_its_method_requires():
    for feature, evidence in cited():
        for field in EVIDENCE_REQUIRED[evidence.method]:
            assert getattr(evidence, field), (feature.id, field)


def test_evidence_records_the_date_it_was_checked():
    for feature, evidence in cited():
        assert evidence.checked, feature.id


def test_diffed_evidence_brackets_the_claimed_version():
    """`absent_in` then `present_in` has to be the version being claimed.

    A feature nothing can date is the exception: it is in the oldest
    archive there is, so there is no release to point at that lacks it.
    That covers the ones reported as "or earlier" and the ones at the
    first public release, which are dated rather than bounded and still
    have nothing underneath them to bracket against. `in` is that case
    for the grammar: it is in the 0.9.1 `comp_op`, so there is no earlier
    grammar to show without it.
    """
    for feature, evidence in cited():
        if evidence.method in {"objects.inv", "archive", "source", "grammar"}:
            assert evidence.present_in == str(feature.added), feature.id
            if feature.or_earlier or feature.added.is_first_public_release:
                assert evidence.absent_in is None, feature.id
            else:
                assert evidence.absent_in is not None, feature.id
                assert Version.parse(evidence.absent_in) < feature.added, feature.id


def test_source_evidence_cites_the_file_it_was_read_from():
    """A source claim is only checkable if it says where to look.

    The path moves between eras and between kinds of module, so it is
    recorded per entry rather than assumed: 0.9.1 keeps every C file in
    a flat `src/` and 1.0 onward split the tree up, a builtin is always
    in `bltinmodule.c`, and a module or one of its members is in
    `Lib/bisect.py` or `Modules/mathmodule.c` depending on what it is
    written in.
    """
    cited_by_source = [
        (feature, evidence)
        for feature, evidence in cited()
        if evidence.method == "source"
    ]
    assert cited_by_source, "the dataset should still have source-dated entries"
    for feature, evidence in cited_by_source:
        assert evidence.file is not None, feature.id
        assert evidence.file.endswith((".c", ".py")), feature.id
        targets = (
            feature.builtins | feature.modules | feature.attributes | feature.methods
        )
        assert evidence.symbol in targets, feature.id


def test_pep_evidence_agrees_with_the_feature():
    for feature, evidence in cited():
        if evidence.method == "pep":
            assert evidence.pep == feature.pep, feature.id
            assert evidence.python_version == str(feature.added), feature.id


def test_annotation_evidence_quotes_the_claimed_version():
    for feature, evidence in cited():
        if evidence.method == "annotation":
            assert evidence.quote is not None, feature.id
            assert str(feature.added) in evidence.quote, feature.id


def test_evidence_is_optional_for_a_hand_built_feature():
    assert _build(entry()).evidence is None


def test_unknown_evidence_method_is_rejected():
    with pytest.raises(DatasetError, match="evidence method"):
        _build(entry(evidence={"method": "vibes"}))


def test_evidence_missing_a_required_field_is_rejected():
    with pytest.raises(DatasetError, match="missing absent_in, present_in"):
        _build(entry(evidence={"method": "objects.inv", "symbol": "py:module x"}))


def test_the_first_public_release_is_a_date_and_not_a_bound():
    """Nothing at the floor is flagged, and it reads as a plain version.

    `max` is the exemplar because it is in the builtins table of the
    oldest Python that survives, so nothing can date it further back.
    That used to make it "0.9 or earlier", which is true and useless:
    there is no release under 0.9 for it to have been added in. `map`
    is the contrast, and it stopped being bounded once the source could
    be read: absent from 0.9.1, present in 1.0.1.
    """
    (feature,) = [f for f in load_features() if f.id == "max"]
    assert not feature.or_earlier
    assert feature.since == "0.9"

    (dated,) = [f for f in load_features() if f.id == "map"]
    assert not dated.or_earlier
    assert dated.since == "1.0"


def test_no_feature_is_bounded_at_the_first_public_release():
    """The rule holds across the dataset, not just for `max`.

    "0.9 or earlier" cannot be acted on by anything: `sincewhen` reports
    the release a feature has been available since, and there is no
    release below the first public one to report.
    """
    for feature in load_features():
        if feature.added.is_first_public_release:
            assert not feature.or_earlier, feature.id


def test_a_bound_above_the_oldest_release_still_reads_as_a_bound():
    """Only the floor gets the different phrasing.

    `zlib` needs a library the interpreter builds could not link before
    2.5, so the sources can only say it is no newer than 1.5.
    """
    (feature,) = [f for f in load_features() if f.id == "zlib"]
    assert feature.or_earlier
    assert feature.since == "1.5 or earlier"


def removed_features():
    """Every entry that claims Python took something away."""
    return [feature for feature in load_features() if feature.removed is not None]


def test_the_dataset_records_removals():
    assert removed_features(), "the dataset should still have removed entries"


def test_every_removal_cites_its_own_evidence():
    """`added` evidence does not cover `removed`.

    They are two claims settled by two different methods, and a source
    diff that dates `apply` to 1.0 has nothing at all to say about 3.0
    taking it away: its corpus stops at 2.5.
    """
    for feature in removed_features():
        assert feature.removed_evidence is not None, feature.id
        assert feature.removed_evidence.method in REMOVAL_EVIDENCE_METHODS, feature.id
        assert feature.removed_evidence.checked, feature.id


def test_removal_evidence_carries_what_its_method_requires():
    for feature in removed_features():
        evidence = feature.removed_evidence
        assert evidence is not None, feature.id
        for field in REMOVAL_EVIDENCE_REQUIRED[evidence.method]:
            assert getattr(evidence, field), (feature.id, field)


def test_diffed_removal_evidence_brackets_the_claimed_version():
    """`present_in` then `absent_in`, and `absent_in` is the claim.

    The mirror of the addition side and the same two fields read the
    same way round: they are the adjacent releases that bracket the
    change, and the version claimed is the one on the far side of it.
    For an addition the far side is presence; for a removal it is
    absence.
    """
    for feature in removed_features():
        evidence = feature.removed_evidence
        assert evidence is not None, feature.id
        if evidence.method == "manual":
            continue
        assert evidence.absent_in == str(feature.removed), feature.id
        assert evidence.present_in is not None, feature.id
        assert Version.parse(evidence.present_in) < feature.removed, feature.id


def test_a_removal_is_never_a_bound():
    """There is no "or later", so `removed` is always an exact release.

    The corpus ends at the newest Python, so a name absent from that end
    has its last presence inside the corpus and the bracket closes. This
    checks the consequence rather than the field: every removal names a
    release the dataset also knows a date for.
    """
    for feature in removed_features():
        assert feature.removed is not None
        assert feature.removed.released is not None, feature.id


def test_a_removal_cannot_predate_its_arrival():
    with pytest.raises(DatasetError, match="cannot be taken away"):
        _build(entry(added="3.9", removed="3.4"))


def test_removal_evidence_without_a_removal_is_rejected():
    with pytest.raises(DatasetError, match="cites a removal it does not claim"):
        _build(entry(removed_evidence={"method": "manual", "note": "x"}))


def test_a_doc_derived_method_cannot_settle_a_removal():
    """The methods whose absences prove nothing are refused outright.

    An inventory drops names when the markup changes and a doc build
    that stops mentioning something has not removed it, so neither may
    make an absence claim. Ten of the removed builtins are indexed by
    the 3.2 or 3.4 docs as `std:2to3fixer`, which is what that failure
    looks like in practice.
    """
    assert REMOVAL_EVIDENCE_METHODS < EVIDENCE_METHODS
    assert not REMOVAL_EVIDENCE_METHODS & {"objects.inv", "annotation", "archive"}
    with pytest.raises(DatasetError, match="removal evidence method"):
        _build(
            entry(
                added="1.0",
                removed="3.0",
                removed_evidence={
                    "method": "objects.inv",
                    "symbol": "py:function apply",
                    "absent_in": "3.0",
                    "present_in": "2.7",
                },
            )
        )


def test_a_search_only_spelling_reaches_search_and_not_detection():
    """`spellings` is a matcher kind that matches nothing on purpose.

    It has to be a matcher kind so that "exactly one matcher" keeps
    holding and a typo cannot produce an entry with nothing to find it
    by, and it has to be absent from the detector so that `<>` is never
    reported against source a 3.14 parser accepted.

    Checked by identity rather than by name, because a spelling and a
    detectable name can be the same word: the `print` statement and the
    `print()` function are two entries dated eight releases apart, and
    only the second of them has anything to detect.
    """
    assert SEARCH_ONLY_FIELDS <= set(MATCHER_FIELDS)
    index = _Index(load_features())
    indexes = (
        index.by_builtin,
        index.by_module,
        index.by_attribute,
        index.by_method,
        index.by_node,
    )
    for feature in load_features():
        for spelling in feature.spellings:
            assert spelling in feature.targets, feature.id
            assert lookup(spelling) != [], feature.id
            for found in indexes:
                assert feature not in _listed(found.get(spelling)), (
                    feature.id,
                    spelling,
                )


def _listed(found):
    """One index entry as a list, since `by_node` holds several."""
    if found is None:
        return []
    return found if isinstance(found, list) else [found]


def test_removed_syntax_is_search_only():
    """Nothing this parser can produce a node for belongs in `spellings`.

    The other half of the rule: a spelling is there because 3.14 cannot
    parse it, so an entry using the matcher has to be one Python took
    away.
    """
    for feature in load_features():
        if feature.spellings:
            assert feature.removed is not None, feature.id


def test_a_removed_feature_reads_as_removed():
    feature = _build(entry(added="1.0", removed="3.0"))
    assert feature.since == "1.0, removed in 3.0"


def test_a_bounded_removed_feature_keeps_both_hedges():
    feature = _build(entry(added="1.5", or_earlier=True, removed="3.0"))
    assert feature.since == "1.5 or earlier, removed in 3.0"


def test_removal_does_not_set_a_floor_for_minimum_version():
    """A removed feature still says how old it is and nothing more.

    `apply(f, args)` needs 1.0 and always did. That the name went away
    in 3.0 is a fact about the name rather than a version requirement,
    and this project deliberately has no `maximum_version()` for it to
    feed.
    """
    assert minimum_version("apply(f, args)") == Version(1, 0)


def test_unknown_evidence_field_is_rejected():
    with pytest.raises(DatasetError, match="unknown evidence fields: source"):
        _build(entry(evidence={"method": "manual", "note": "n", "source": "x"}))


def test_requires_and_check_together_are_rejected():
    with pytest.raises(DatasetError, match="both"):
        _build(
            {
                "id": "x",
                "name": "x",
                "added": "3.0",
                "category": "syntax",
                "nodes": ["Dict"],
                "requires": "keys",
                "check": "has_none_key",
            }
        )
