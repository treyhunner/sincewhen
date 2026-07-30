# sincewhen

[![PyPI - Version](https://img.shields.io/pypi/v/sincewhen.svg)](https://pypi.org/project/sincewhen)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/sincewhen.svg)](https://pypi.org/project/sincewhen)

Find out which Python version added each feature your code uses.

Point `sincewhen` at a file and it will tell you what's in there and how long each piece of it has been in Python, back to the first public release in 1991.


## Installation

Installing with [`uv tool`](https://docs.astral.sh/uv/concepts/tools/):

```console
uv tool install sincewhen
```

Installing with [`pipx`](https://pipx.pypa.io):

```console
pipx install sincewhen
```

You can also install `sincewhen` globally with `pip`, but I usually recommend installing command-line tools in their own separate environment.


## Usage

Give `sincewhen` a file to see every dated feature it uses:

```console
$ sincewhen example.py
example.py:1  tomllib module                  3.11                        2022-10-24
example.py:3  positional-only parameters (/)  3.8                         2019-10-14
example.py:5  with statement                  2.5                         2006-09-19
example.py:5  open()                          0.9 (first public release)
```

The last column is the day that release shipped, so a version number reads as an age.

Only the first use of each feature is shown by default.
Pass `--all` to see every occurrence.

The dataset reaches back to Python 0.9.1, so a file will report things like `str()` and `open()` that have been there since 1991.
That is usually the point, but pass `--since` when you only want the recent arrivals:

```console
$ sincewhen --since 3.0 example.py
```

Read from standard input with `-`:

```console
$ echo 'x: int = 1' | sincewhen -
<stdin>:1  variable annotation  3.6                         2016-12-23
<stdin>:1  int()                0.9 (first public release)
```

Look a single feature up by name instead of analyzing code:

```console
$ sincewhen --search walrus
walrus operator (:=) - Python 3.8 (released 2019-10-14)
  PEP: https://peps.python.org/pep-0572/
  Docs: https://docs.python.org/3/whatsnew/3.8.html
```

Pass `--json` to either mode for machine-readable output.


## Library

```python
>>> import sincewhen
>>> sincewhen.minimum_version("import tomllib")
Version(major=3, minor=11)
>>> [d.feature.name for d in sincewhen.detect("if (n := 1): pass")]
['walrus operator (:=)']
>>> sincewhen.lookup("tomllib")[0].added
Version(major=3, minor=11)
```


## Why it needs Python 3.14

`sincewhen` parses code with the standard library's `ast` module, which can only understand syntax that the running interpreter understands.
A Python 3.9 interpreter cannot parse a `match` statement, so it could not report one either.
Requiring the newest Python is what lets `sincewhen` recognize the newest syntax.

The Python version you *run* `sincewhen` on has nothing to do with the versions it *reports* on, which reach back to Python 0.9.1.


## Known limits

- Some features are genuinely ambiguous in an AST.
  `a | b` could be a Python 3.9 dict merge, a Python 3.10 union type, or an integer bitwise-or that has worked since forever, and the AST alone cannot tell you which.
  Ambiguous features are left out rather than guessed at.
- Detection is syntactic.
  `sincewhen` sees that you called something named `math.isclose`, not that you called the real one.
  Shadowed builtins are skipped, but a shadowed module attribute is not.
- The dataset is curated and incomplete.
  A feature that isn't in it won't be reported, so the minimum version is a lower bound on the true answer.
- `added` is the oldest release from which a feature has been available *ever since*, ignoring Python 3.0 and 3.1.
  Nobody shipped code on those two, so a gap there is not a gap anyone lived through: `argparse` shipped in 2.7 and again in 3.2, and is dated 2.7.
  A feature missing from 3.2 as well has a real gap and takes the later date.
- Some features cannot be dated, only bounded, and those are reported as "1.5 or earlier".
  There are four of them, each a module needing something the oldest interpreters could not be built with.
- Anything present in Python 0.9.1 reads as "0.9 (first public release)" rather than "0.9 or earlier".
  Python began before it was published, so a few of those are genuinely older, but there is no earlier release to reach for: nothing has been in Python longer than Python has been public.
- Release dates come from python.org's downloads database back to 2.2, and from CPython's release tags before that.
  Python 0.9 and 1.6 have no release tag, so they show no date.
- Searching for a module member that has no entry of its own falls back to the module it lives in, since a member cannot be older than its module.


## Development

This project uses [uv](https://docs.astral.sh/uv/) and [just](https://just.systems).
Run `just` to see every available task.

```console
$ just test     # run the test suite
$ just check    # format, lint, typecheck, and test
```

No setup step is needed: `uv` creates the virtual environment and installs dependencies on the first `uv run`.

If you would rather not install `just`, every task is a short `uv` command that you can run directly (check the `justfile` for the commands):

```console
uv run pytest
```


### Adding a feature

Features live in `src/sincewhen/features.toml`, one `[[features]]` table each.
Give the feature an id, a human-readable name, the version that added it, a category, exactly one matcher, and the evidence for the version:

```toml
[[features]]
id = "walrus"
name = "walrus operator (:=)"
added = "3.8"
category = "syntax"
pep = 572
nodes = ["NamedExpr"]

[features.evidence]
method = "pep"
pep = 572
python_version = "3.8"
checked = "2026-07-28"
```

The matcher kinds are `nodes` (AST node class names), `builtins`, `modules`, and `attributes` (dotted `module.name` paths).
Node matchers can be narrowed with `requires` (a node attribute that must be truthy) or `check` (a predicate registered in `detect.py`).

Documentation links are generated from `added` and `pep`, so only set `docs` when you have a better link than the "What's New" page.

Nobody should be typing version numbers from memory.
For anything in the standard library, let the archived documentation say what the version is:

```console
$ just fetch-docs                       # one-time, ~500 MB into a gitignored .cache/
$ just whenadded math.lcm               # what each source says, and whether they agree
$ just propose math.lcm math.isqrt      # entries with evidence, ready to paste
$ just verify-dataset                   # re-derive every claim in the dataset
```

`just verify-dataset` also runs in CI, so a pull request that edits a version without editing its evidence fails.

Evidence has eight `method` values, seven of which a machine can recheck:

| method        | what it means                                                                                                                               |
|---------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| `objects.inv` | the symbol is absent from one release's Sphinx inventory and present in the next                                                            |
| `archive`     | the same diff over the module lists and built-in function pages in the pre-Sphinx doc builds, back to the 0.9.1 LaTeX                       |
| `source`      | the name is absent from one release's own C or Python implementation and present in the next, which reaches back further than any doc build |
| `interpreter` | that release's own interpreter, built from its tarball, was asked whether the name resolves                                                 |
| `annotation`  | the documentation dates it itself, in an "Added in version" marker quoted in the entry                                                      |
| `grammar`     | the token is absent from one release's grammar and present in the next, which is what shipped rather than what a PEP intended               |
| `pep`         | the feature's PEP carries a `Python-Version` header                                                                                         |
| `manual`      | a human read the archives and wrote down what they found, and why the other seven do not settle it                                          |

`interpreter` is the only method that reads Python rather than a description of it, and it outranks the rest for the era it covers, 0.9.1 to 2.5.
It is what settles a name no text can account for: `re.finditer` is defined in Python 2.2's `sre.py` and left out of its `__all__`, so `from sre import *` never bound it and the answer is 2.3, not the 2.2 the docs claim.
Building the interpreters needs Docker and about ten minutes, so the result is committed as `scripts/interpreters.json` and nothing downstream needs a compiler:

```console
$ just build-pythons                    # build 0.9.1 through 2.5 (slow)
$ just probe-pythons                    # ask them all, and record it
$ just interpreters-vs-dataset          # where they disagree with the dataset
```

`manual` is for the cases where the sources genuinely disagree, and every one of them is printed on every `verify-dataset` run so the override stays visible.

A new entry, or a corrected version on an existing one, also gets a line under `Unreleased` in [`CHANGELOG.md`](CHANGELOG.md).
Dataset changes are the ones that alter what `sincewhen` reports about code that did not change, so they are worth spelling out.


## Releasing

Move the `Unreleased` notes in [`CHANGELOG.md`](CHANGELOG.md) under a heading for the new version, then bump, tag, and push:

```console
$ just bump patch
$ just release
```

`just release` refuses to tag a version that the changelog has nothing to say about, so the notes have to be written before the release goes out rather than after.

Pushing a `v*` tag runs the release workflow, which publishes to PyPI with trusted publishing and creates a GitHub release whose notes are that version's changelog section.


## License

`sincewhen` is distributed under the terms of the [MIT license](LICENSE.txt).
