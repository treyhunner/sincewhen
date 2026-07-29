# sincewhen

[![PyPI - Version](https://img.shields.io/pypi/v/sincewhen.svg)](https://pypi.org/project/sincewhen)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/sincewhen.svg)](https://pypi.org/project/sincewhen)

Find out which Python version added each feature your code uses.

Point `sincewhen` at a file and it will tell you what's in there, when each piece of it arrived, and how old a Python you could get away with running it on.


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
example.py:1  tomllib module                3.11
example.py:3  positional-only parameters (/)  3.8
example.py:4  with statement                2.5

Minimum: Python 3.11 (set by tomllib module)
```

Only the first use of each feature is shown by default.
Pass `--all` to see every occurrence.

Read from standard input with `-`:

```console
$ echo 'x: int = 1' | sincewhen -
<stdin>:1  variable annotation  3.6

Minimum: Python 3.6 (set by variable annotation)
```

Look a single feature up by name instead of analyzing code:

```console
$ sincewhen --search walrus
walrus operator (:=) - Python 3.8
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

The Python version you *run* `sincewhen` on has nothing to do with the versions it *reports* on, which reach back to Python 2.0.


## Known limits

- Some features are genuinely ambiguous in an AST.
  `a | b` could be a Python 3.9 dict merge, a Python 3.10 union type, or an integer bitwise-or that has worked since forever, and the AST alone cannot tell you which.
  Ambiguous features are left out rather than guessed at.
- Detection is syntactic.
  `sincewhen` sees that you called something named `math.isclose`, not that you called the real one.
  Shadowed builtins are skipped, but a shadowed module attribute is not.
- The dataset is hand-curated and incomplete.
  A feature that isn't in it won't be reported, so the minimum version is a lower bound on the true answer.
- Python 1.x entries are not in the dataset yet.


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
Give the feature an id, a human-readable name, the version that added it, a category, and exactly one matcher:

```toml
[[features]]
id = "walrus"
name = "walrus operator (:=)"
added = "3.8"
category = "syntax"
pep = 572
nodes = ["NamedExpr"]
```

The matcher kinds are `nodes` (AST node class names), `builtins`, `modules`, and `attributes` (dotted `module.name` paths).
Node matchers can be narrowed with `requires` (a node attribute that must be truthy) or `check` (a predicate registered in `detect.py`).

Documentation links are generated from `added` and `pep`, so only set `docs` when you have a better link than the "What's New" page.


## Releasing

Bump the version, then tag and push:

```console
$ just bump patch
$ just release
```

Pushing a `v*` tag runs the release workflow, which publishes to PyPI with trusted publishing and creates a GitHub release.


## License

`sincewhen` is distributed under the terms of the [MIT license](LICENSE.txt).
