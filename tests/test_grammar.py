"""What the grammar diff will and will not call a removal.

The addition side needs no tests of its own: a token absent from one
release's grammar and present in the next was added there, and nothing
about that reading has ever produced a wrong answer.

The removal side has two decisions in it, and both were wrong on the
first attempt. Reading rule names as well as terminals reported a
removal for `{'k': 1}`, because 3.0 renamed `dictmaker` to
`dictorsetmaker`. Diffing across the pgen and PEG chains would report a
few hundred removals in Python 3.9, which shipped both grammars and
removed nothing.

These work from a fake vocabulary rather than from the cached grammars,
so they run without the 2 GB corpus.
"""

import grammar
import pytest


@pytest.fixture
def vocabulary(monkeypatch):
    """Install a per-release vocabulary and return a way to fill it in."""
    built: dict[tuple[str, bool], set[str]] = {}
    monkeypatch.setattr(
        grammar,
        "vocabulary",
        lambda version, peg=False: built.get((version, peg), set()),
    )
    return built


RELEASES = ["1.0", "2.7", "3.0", "3.1"]


def test_a_terminal_the_newest_grammar_lacks_was_removed(vocabulary):
    for version in ("1.0", "2.7"):
        vocabulary[(version, False)] = {"'exec'"}
    for version in ("3.0", "3.1"):
        vocabulary[(version, False)] = set()
    assert grammar._removed(RELEASES, peg=False) == {
        "'exec'": {"removed": "3.0", "present_in": "2.7", "absent_in": "3.0"}
    }


def test_a_terminal_still_in_the_newest_grammar_was_not(vocabulary):
    for version in RELEASES:
        vocabulary[(version, False)] = {"'lambda'"}
    assert grammar._removed(RELEASES, peg=False) == {}


def test_a_rule_is_never_reported(vocabulary):
    """CPython renames rules, and a rename is not a removal.

    `dictmaker` is in no grammar after 2.7 because 3.0 calls it
    `dictorsetmaker`, and dict displays are fine. Two dozen more of the
    same shape came with it: `listmaker`, `fpdef`, `old_lambdef`,
    `with_var`.
    """
    for version in ("1.0", "2.7"):
        vocabulary[(version, False)] = {"dictmaker", "'exec'"}
    for version in ("3.0", "3.1"):
        vocabulary[(version, False)] = {"dictorsetmaker"}
    assert set(grammar._removed(RELEASES, peg=False)) == {"'exec'"}


def test_the_last_run_is_what_counts(vocabulary):
    """A token that came back and went away again is dated from the end.

    Which is also why 3.0 and 3.1 need no forgiving here: a token
    missing from those two and back in 3.2 ends its run at the newest
    release and is reported by nobody.
    """
    for version in ("1.0", "3.0"):
        vocabulary[(version, False)] = {"'access'"}
    for version in ("2.7", "3.1"):
        vocabulary[(version, False)] = set()
    assert grammar._removed(RELEASES, peg=False)["'access'"] == {
        "removed": "3.1",
        "present_in": "3.0",
        "absent_in": "3.1",
    }
