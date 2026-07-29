"""Tests for the feature dataset itself."""

import pytest

from sincewhen import Version, load_features, lookup
from sincewhen.detect import CHECKS
from sincewhen.features import (
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
    known = {"syntax", "builtin", "module", "function"}
    for feature in load_features():
        assert feature.category in known, feature.id


def test_versions_are_plausible():
    for feature in load_features():
        assert Version(1, 0) <= feature.added <= Version(3, 99), feature.id


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
    assert [f.id for f in lookup("sum")] == ["sum"]


def test_lookup_is_case_insensitive():
    assert lookup("TOMLLIB") == lookup("tomllib")


def test_lookup_orders_oldest_first():
    results = lookup("module")
    assert results == sorted(results, key=lambda f: (f.added, f.id))


def test_lookup_with_no_matches():
    assert lookup("no-such-feature") == []


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
