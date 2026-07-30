"""What `dating.py` refuses to answer.

Only the guards are exercised here, not the reconciliation: everything
else in that module reads the 500 MB corpus, which `just verify-dataset`
covers and a unit test cannot. A guard is worth testing on its own
because its whole job is to fire before any source is consulted.
"""

from dating import date_symbol, is_keyword


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
    for name in ("if", "for", "while", "return", "lambda", "not", "None"):
        assert date_symbol(name).status == "keyword", name


def test_a_soft_keyword_is_still_a_name():
    """`type` is a builtin this dataset dates, and `match` is any name.

    Refusing these would throw away real answers, which is why the guard
    is the hard keyword list and not `iskeyword` plus `issoftkeyword`.
    """
    for name in ("type", "match", "case", "_"):
        assert not is_keyword(name), name
