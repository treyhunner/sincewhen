"""Tests for the feature dataset itself."""

import builtins

import pytest

from sincewhen import Version, load_features, lookup
from sincewhen.detect import CHECKS
from sincewhen.features import (
    EVIDENCE_METHODS,
    EVIDENCE_REQUIRED,
    MATCHER_FIELDS,
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


def test_every_dated_method_is_still_there():
    """`added` claims a method has been available ever since.

    So a method the running Python does not have is either a typo or a
    Python 2 name that 3.0 removed, and neither belongs in the dataset:
    the schema has no way to say "and then it was taken away".

    The special methods are exempt, because `object` documents most of
    them as a protocol rather than implementing them. Nothing has
    `__length_hint__` until a class opts into it.
    """
    for feature in load_features():
        for name in feature.methods:
            type_name, _, method = name.partition(".")
            if method.startswith("__"):
                continue
            assert hasattr(getattr(builtins, type_name), method), name


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

    A feature dated "or earlier" is the exception: it is in the oldest
    archive there is, so there is no release to point at that lacks it.
    `in` is that case for the grammar: it is in the 0.9.1 `comp_op`, so
    there is no earlier grammar to show without it.
    """
    for feature, evidence in cited():
        if evidence.method in {"objects.inv", "archive", "source", "grammar"}:
            assert evidence.present_in == str(feature.added), feature.id
            if feature.or_earlier:
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


def test_or_earlier_features_say_so():
    """The phrase, and the release date, both come off the same flag.

    `max` is the exemplar because it is in the builtins table of the
    oldest Python that survives, so nothing can date it further back.
    `map` used to sit here, and stopped qualifying once the source
    could be read: it is absent from 0.9.1 and present in 1.0.1.

    At the oldest release the bound is not phrased as one. "0.9 or
    earlier" is true and reads as an evasion, because there is no earlier
    release to reach for. The flag itself is unchanged, so anything
    reading the dataset still sees a bound.
    """
    (feature,) = [f for f in load_features() if f.id == "max"]
    assert feature.or_earlier
    assert feature.since == "0.9 (first public release)"

    (dated,) = [f for f in load_features() if f.id == "map"]
    assert not dated.or_earlier
    assert dated.since == "1.0"


def test_a_bound_above_the_oldest_release_still_reads_as_a_bound():
    """Only the floor gets the different phrasing.

    `zlib` needs a library the interpreter builds could not link before
    2.5, so the sources can only say it is no newer than 1.5.
    """
    (feature,) = [f for f in load_features() if f.id == "zlib"]
    assert feature.or_earlier
    assert feature.since == "1.5 or earlier"


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
