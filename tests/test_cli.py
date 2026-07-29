"""Tests for the command-line interface."""

import json
import subprocess
import sys

import pytest

from sincewhen.cli import main

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


def test_reports_features_and_minimum(example, capsys):
    assert main([str(example)]) == 0
    output = capsys.readouterr().out
    assert "tomllib module" in output
    assert "positional-only parameters (/)" in output
    assert "Minimum: Python 3.11 (set by tomllib module)" in output


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


def test_search_json(capsys):
    assert main(["--search", "tomllib", "--json"]) == 0
    (entry,) = json.loads(capsys.readouterr().out)
    assert entry["added"] == "3.11"


def test_missing_file(tmp_path, capsys):
    assert main([str(tmp_path / "nope.py")]) == 2
    assert "sincewhen:" in capsys.readouterr().err


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
