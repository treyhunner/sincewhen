"""Tests for the command-line interface."""

import json
import subprocess
import sys

import pytest

from sincewhen.cli import _print_members, main
from sincewhen.members import SUGGESTION_LIMIT, MemberAnswer
from sincewhen.versions import Version

SOURCE = """\
import tomllib

def load(path, /):
    with open(path, "rb") as f:
        return tomllib.load(f)
"""


@pytest.fixture
def example(tmp_path):
    path = tmp_path / "example.py"
    path.write_text(SOURCE, encoding="utf-8")
    return path


def test_reports_every_feature_it_finds(example, capsys):
    assert main([str(example)]) == 0
    output = capsys.readouterr().out
    assert "tomllib module" in output
    assert "positional-only parameters (/)" in output


def test_reports_no_summary_verdict(example, capsys):
    """The report is a list of ages, not a compatibility judgment.

    `sincewhen` answers how long each feature has been in Python. A
    closing "minimum version" line reframed every run as advice about
    what to target, which is a different question and not this one.
    """
    main([str(example)])
    assert "Minimum" not in capsys.readouterr().out


def test_a_module_line_gives_way_to_its_member(capsys, tmp_path):
    """Both are true, so only the more specific one is printed."""
    path = tmp_path / "m.py"
    path.write_text("from dataclasses import dataclass\n", encoding="utf-8")
    main([str(path)])
    output = capsys.readouterr().out
    assert "dataclasses.dataclass()" in output
    assert "dataclasses module" not in output


def test_reports_release_dates(example, capsys):
    main([str(example)])
    assert "2022-10-24" in capsys.readouterr().out


def test_since_hides_older_features(example, capsys):
    main([str(example), "--since", "3.0"])
    output = capsys.readouterr().out
    assert "tomllib module" in output
    assert "with statement" not in output


def test_reports_line_numbers(example, capsys):
    main([str(example)])
    assert f"{example}:1" in capsys.readouterr().out


def reported_lines(output, path):
    """The per-detection lines, without the summary that follows them."""
    return [line for line in output.splitlines() if line.startswith(str(path))]


def test_first_use_only_by_default(tmp_path, capsys):
    path = tmp_path / "repeat.py"
    path.write_text("sum(a)\nsum(b)\n", encoding="utf-8")
    main([str(path)])
    assert len(reported_lines(capsys.readouterr().out, path)) == 1


def test_all_flag_reports_every_use(tmp_path, capsys):
    path = tmp_path / "repeat.py"
    path.write_text("sum(a)\nsum(b)\n", encoding="utf-8")
    main(["--all", str(path)])
    assert len(reported_lines(capsys.readouterr().out, path)) == 2


def test_file_with_no_features(tmp_path, capsys):
    path = tmp_path / "plain.py"
    path.write_text("x = 1\n", encoding="utf-8")
    assert main([str(path)]) == 0
    assert "No dated features detected." in capsys.readouterr().out


def test_json_output(example, capsys):
    assert main(["--json", str(example)]) == 0
    data = json.loads(capsys.readouterr().out)
    entries = data[str(example)]
    assert {"tomllib", "positional-only-parameters"} <= {e["id"] for e in entries}
    assert entries[0]["line"] == 1


def test_reads_stdin(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("x: int = 1\n"))
    assert main(["-"]) == 0
    out = capsys.readouterr().out
    assert "<stdin>:1" in out
    assert "variable annotation" in out


def test_search(capsys):
    assert main(["--search", "walrus"]) == 0
    out = capsys.readouterr().out
    assert "walrus operator (:=) - Python 3.8" in out
    assert "https://peps.python.org/pep-0572/" in out


def test_search_with_no_match(capsys):
    assert main(["--search", "no-such-feature"]) == 1
    assert "No feature matches" in capsys.readouterr().err


def test_search_says_when_it_fell_back_to_a_module(capsys):
    """A member the index has never heard of still gets its module."""
    assert main(["--search", "platform.no_such_member"]) == 0
    output = capsys.readouterr().out
    assert "No entry for platform.no_such_member, but it lives in:" in output
    assert "platform module" in output


def test_search_answers_a_member_without_a_preamble(capsys):
    """Which of the two data files answered is not the reader's problem."""
    assert main(["--search", "platform.system"]) == 0
    output = capsys.readouterr().out
    assert output == "platform.system - Python 2.3 (released 2003-07-29)\n"


def test_search_reports_a_bounded_member_as_bounded(capsys):
    """`os.path` can only be bounded, and so can everything in it."""
    assert main(["--search", "os.path.join"]) == 0
    assert "os.path.join - Python 1.5 or earlier" in capsys.readouterr().out


def test_search_prefers_an_exact_member_to_a_near_miss(capsys):
    """`lookup` matches ids by substring, which is not "has an entry".

    `os.wait` has no entry and `os.wait3` does, so testing the wrong
    predicate printed `os.wait3` and `os.wait4` for a query about
    `os.wait` and said nothing about the substitution.
    """
    assert main(["--search", "os.wait"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("os.wait - Python 1.5 or earlier")
    assert "os.wait3" not in output


def test_search_does_not_list_a_member_twice(capsys):
    """A name the dataset dates is not also offered as a suggestion.

    `json.JSONDecodeError` has an entry and is a member of `json`, so
    without the `has_entry` filter it prints once as an entry and again
    under "is also a member of".
    """
    assert main(["--search", "JSONDecodeError"]) == 0
    output = capsys.readouterr().out
    assert output.count("JSONDecodeError") == 1
    assert "is also a member of" not in output


def test_search_offers_members_of_a_bare_name(capsys):
    """`system` matches the dataset by substring and is also a member."""
    assert main(["--search", "system"]) == 0
    output = capsys.readouterr().out
    assert "sys.getfilesystemencoding()" in output
    assert "'system' is also a member of:" in output
    assert "platform.system - Python 2.3" in output


def test_search_suggests_members_when_the_dataset_has_nothing(capsys):
    assert main(["--search", "TimeoutError"]) == 0
    output = capsys.readouterr().out
    assert "No entry for 'TimeoutError'. Did you mean one of these?" in output
    assert "asyncio.TimeoutError" in output


def test_search_caps_a_long_suggestion_list(capsys):
    """A name in fifty modules is not an answer, it is a directory."""
    answers = [
        MemberAnswer(
            module=f"m{n}",
            name="thing",
            added=Version(3, 9),
            or_earlier=False,
            feature=None,
        )
        for n in range(SUGGESTION_LIMIT + 3)
    ]
    _print_members(answers)
    output = capsys.readouterr().out
    assert output.count(" - Python ") == SUGGESTION_LIMIT
    assert "...and 3 more." in output


def test_search_member_json(capsys):
    assert main(["--search", "platform.system", "--json"]) == 0
    entry, *rest = json.loads(capsys.readouterr().out)
    assert not rest
    assert entry == {
        "name": "platform.system",
        "module": "platform",
        "added": "2.3",
        "or_earlier": False,
        "released": "2003-07-29",
    }


def test_search_json(capsys):
    assert main(["--search", "tomllib", "--json"]) == 0
    entry, *_ = json.loads(capsys.readouterr().out)
    assert entry["added"] == "3.11"


def test_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.py")]) == 2
    assert "sincewhen:" in capsys.readouterr().err


def test_version(capsys):
    """`--version` is sincewhen's own version, not a Python one."""
    with pytest.raises(SystemExit) as caught:
        main(["--version"])
    assert caught.value.code == 0
    assert capsys.readouterr().out.startswith("sincewhen ")


def test_syntax_error(tmp_path, capsys):
    path = tmp_path / "broken.py"
    path.write_text("def (\n", encoding="utf-8")
    assert main([str(path)]) == 2
    assert "sincewhen:" in capsys.readouterr().err


def test_no_arguments_is_an_error(capsys):
    with pytest.raises(SystemExit):
        main([])


def test_search_omits_missing_links(capsys):
    """`sorted()` has no PEP, so no PEP line should be printed."""
    assert main(["--search", "sorted"]) == 0
    out = capsys.readouterr().out
    assert "sorted() - Python 2.4" in out
    assert "PEP:" not in out
    assert "Docs:" in out


def test_search_json_with_no_match(capsys):
    assert main(["--search", "no-such-feature", "--json"]) == 1
    assert json.loads(capsys.readouterr().out) == []


def test_runnable_as_a_module():
    """`python -m sincewhen` works."""
    result = subprocess.run(
        [sys.executable, "-m", "sincewhen", "--search", "walrus"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "walrus operator (:=) - Python 3.8" in result.stdout
