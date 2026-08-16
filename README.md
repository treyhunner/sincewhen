# sincewhen

[![PyPI - Version](https://img.shields.io/pypi/v/sincewhen.svg)](https://pypi.org/project/sincewhen)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/sincewhen.svg)](https://pypi.org/project/sincewhen)

Find out which Python version added each feature your code uses.

Point `sincewhen` at a file and it will tell you what's in there and how long each piece of it has been in Python, back to the first public release in 1991.


## Try it in your browser

`sincewhen` parses with the standard library's `ast` and ships no dependencies, so the whole tool runs in a browser tab.
Paste code in at [pym.dev/since](https://pym.dev/since) to see what it reports without installing anything.
The analysis runs on your own machine, in the tab, so nothing you paste is uploaded anywhere.


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

```python
# example.py
import tomllib


def load(path, /):
    with open(path, "rb") as config:
        return tomllib.load(config)
```

```console
$ sincewhen example.py
example.py:1  tomllib module                  3.11  2022-10-24
example.py:4  positional-only parameters (/)  3.8   2019-10-14
example.py:5  with statement                  2.5   2006-09-19
example.py:5  open()                          0.9   1991-02-20
example.py:6  tomllib.load()                  3.11  2022-10-24
```

The last column is the day that release shipped, so a version number reads as an age.
Every release the dataset can name has one, back to 1991-02-20.

Pass as many files as you like to see them all in one report.
Only the first use of each feature is shown by default, so a feature used a hundred times costs one line.
Pass `--all` to see every occurrence.

The dataset reaches back to Python 0.9.1, so a file will report things like `str()` and `open()` that have been there since 1991.
That is usually the point, but pass `--since` when you only want the recent arrivals:

```console
$ sincewhen --since 3.0 example.py
example.py:1  tomllib module                  3.11  2022-10-24
example.py:4  positional-only parameters (/)  3.8   2019-10-14
example.py:6  tomllib.load()                  3.11  2022-10-24
```

Read from standard input with `-`:

```console
$ echo 'x: int = 1' | sincewhen -
<stdin>:1  variable annotation  3.6  2016-12-23
<stdin>:1  int()                0.9  1991-02-20
```

Look a single feature up by name instead of analyzing code:

```console
$ sincewhen --search walrus
walrus operator (:=) - Python 3.8 (released 2019-10-14)
  PEP: https://peps.python.org/pep-0572/
  Docs: https://docs.python.org/3/whatsnew/3.8.html
```

A method of a builtin type answers to its own name, without the type in front of it:

```console
$ sincewhen --search removeprefix
removeprefix() on str, bytes and bytearray - Python 3.9 (released 2020-10-05)
  Docs: https://docs.python.org/3/whatsnew/3.9.html
```

A member with no entry of its own is answered from the member index, which covers every documented member of every stdlib module and of every class inside one:

```console
$ sincewhen --search platform.system
platform.system - Python 2.3 (released 2003-07-29)

$ sincewhen --search os.path.relpath
os.path.relpath - Python 2.6 (released 2008-10-02)

$ sincewhen --search unittest.TestCase.subTest
unittest.TestCase.subTest - Python 3.4 (released 2014-03-17)
```

A member nothing can date is bounded, exactly as an entry would be:

```console
$ sincewhen --search os.path.join
os.path.join - Python 1.5 or earlier (released 1997-12-31)
```

A bare name searches every member list, which is how a method usually gets typed:

```console
$ sincewhen --search TimeoutError
No entry for 'TimeoutError'. Did you mean one of these?
multiprocessing.TimeoutError - Python 3.3 (released 2012-09-29)
asyncio.TimeoutError - Python 3.4 (released 2014-03-17)
concurrent.futures.TimeoutError - Python 3.5 (released 2015-09-13)

$ sincewhen --search assertNoLogs
No entry for 'assertNoLogs'. Did you mean one of these?
unittest.TestCase.assertNoLogs - Python 3.10 (released 2021-10-04)
```

Pass `--json` to either mode for machine-readable output.
A search that answers from the member index emits member records, which carry `owner` where a feature record carries `id` and `category`.


## History you can look up

Dating 1,884 features against seven independent sources turns up a lot of history that is easy to misremember, and nearly all of it is one search away:

```console
$ sincewhen --search sorted
sorted() - Python 2.4 (released 2004-11-30)
  Docs: https://docs.python.org/3/whatsnew/2.4.html
```

Here are a few of my favorites.

### The same problem, solved a little better each time

The standard library is full of arcs: a series of tools for one problem, each solving it a bit better than the last.

**Counting.**
How do you count things in Python?
The answer kept improving for thirteen years: `dict.get` arrived in 1997 (Python 1.5), `dict.setdefault` in 2000 (2.0), `dict.fromkeys` in 2003 (2.3), `collections.defaultdict` in 2006 (2.5), and `collections.Counter` in 2010 (2.7).
[Counting things in Python](https://treyhunner.com/2015/11/counting-things-in-python/) walks this same history as code, refactoring one loop forward through every release.

**String formatting.**
Python has gone through several waves of string interpolation.
Percent formatting was there at the beginning, in 1991.
Then `string.Template` in 2004 (2.4), `str.format` in 2008 (2.6), f-strings in 2016 (3.6), and t-strings in 2025 (3.14).
All five still work.
[T-strings in Python](https://www.pythonmorsels.com/t-strings-in-python/#string-formatting-a-very-brief-history) lays them out side by side.

**Records.**
"A class that just holds some fields" sounds like a solved problem.
Tuples were the answer in 1991, but Python has added new answers since: `collections.namedtuple` in 2008 (2.6), `types.SimpleNamespace` in 2012 (3.3), `typing.NamedTuple` in 2015 (3.5), `dataclasses` in 2018 (3.7), and `typing.TypedDict` in 2019 (3.8).

**Running a subprocess.**
`os.system` is from 1997 (1.5).
`subprocess.Popen` arrived in 2004 (2.4) with the stated aim of replacing it, `subprocess.check_output` in 2010 (2.7), and `subprocess.run` in 2015 (3.5).
`os.system` is still there in Python 3.14.

### Other surprising stories

**Comprehensions came six years after `map()` and `filter()`.**
`map()`, `filter()`, and `lambda` are all from 1994 (1.0), so the whole functional trio was there together before any comprehension syntax existed.
List comprehensions arrived in 2000 (2.0), generator expressions in 2004 (2.4), and dict and set comprehensions in 2010 (2.7).

**`sorted()` is nearly fourteen years younger than `list.sort()`.**
Sorting a list in place worked in 1991 (0.9); sorting anything into a new list arrived in 2004 (2.4).
`reversed()` is also from 2004 (2.4), against a `list.reverse()` from 1994 (1.0).

**`enumerate()` took twelve years.**
It arrived in 2003 (2.3), so `for i in range(len(items))` was simply how you numbered things for a long time.
`zip()` beat it by three years, so from 2000 to 2003 you could pair two lists together but still could not number one.

**Curly braces meant only dictionaries for sixteen years.**
Dict literals date to 1994 (1.0).
Sets arrived as a module in 2003 (2.3), became the `set()` and `frozenset()` builtins in 2004 (2.4), and finally got literals, and set comprehensions with them, in 2010 (2.7).

**`print` has been three different things.**
The statement was there in 1991 (0.9) and gone in 2008 (3.0).
`from __future__ import print_function` arrived in 2.6, two months before 3.0 shipped, and the function itself in 3.0.
`sincewhen --search print` prints the arc in order, which is what the second axis is for: a name that was taken away has a `removed` version as well as an `added` one.

**Three dict methods were added to a release older than the one that lacks them.**
`dict.viewkeys`, `dict.viewvalues` and `dict.viewitems` arrived in 2.7, which shipped in 2010, and Python 3.0 had already shipped without them in 2008.
That is not a contradiction: 3.0 gave the view behaviour to `keys`, `values` and `items` outright, and 2.7 added the `view` spellings so that code could be written for both lines.
So they belong to exactly one release, and reading `added` and `removed` as a range would put them in the wrong order.
`dict.has_key` is the other extreme: it is in the 0.9.1 method table, so it was there for the whole of Python's first seventeen years.

**String methods did not exist for Python's first nine years.**
Until 2000 (1.6), splitting a string meant `string.split(line)` rather than `line.split()`.
That release added twenty-nine string methods at once, and the `string` module kept growing anyway: `string.ascii_lowercase` is from 2001 (2.2) and `string.Template` from 2004 (2.4), both newer than the methods that took away the module's original job.
Today `string` has twelve public names left.

### Why seven sources

The documentation is a record kept by many people over thirty-five years, and a module's early history is genuinely hard to reconstruct after the fact.
An "Added in version" marker attaches to whatever signature sits above it, which is not always the thing it was written about: `compile()` is from 1994 (1.0), and the nearest marker in the current docs says 3.8 because it documents a `flags` value.
The Python 2.7 docs date `bisect` to 2.1, while `Lib/bisect.py` is already in the 1.0 tarball, from 1994.
And a PEP records what was planned rather than what shipped: class decorators are headed `Python-Version: 3.0` by PEP 3129, and CPython's 2.6 grammar already has the rule.

That is why every version here is checked against seven independent sources rather than trusted to any one of them.
Forty-one entries are dated by a source that contradicts the documentation, and each one's evidence records which source and why.


## Library

```python
>>> import sincewhen
>>> sincewhen.minimum_version("import tomllib")
Version(major=3, minor=11)
>>> [d.feature.name for d in sincewhen.detect("if (n := 1): pass")]
['walrus operator (:=)']
>>> sincewhen.lookup("tomllib")[0].added
Version(major=3, minor=11)
>>> sincewhen.minimum_version("x = 1") is None
True
>>> sincewhen.lookup_member("platform.system").since
'2.3'
>>> [answer.dotted for answer in sincewhen.find_members("system")]
['os.system', 'platform.system']
```

`minimum_version()` returns `None` when nothing detected sets a floor, which means no known feature requires a particular release rather than that the code runs anywhere.
A bounded feature sets no floor either: "1.5 or earlier" is a limit on what the sources could read rather than a date, so `import zlib` on its own also gives `None`.


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
- The dataset is curated and incomplete, at about 1,800 entries today.
  A feature that isn't in it won't be reported, so the minimum version is a lower bound on the true answer.
- `added` is the oldest release from which a feature has been available *ever since*, ignoring Python 3.0 and 3.1.
  Nobody shipped code on those two, so a gap there is not a gap anyone lived through: `argparse` shipped in 2.7 and again in 3.2, and is dated 2.7.
  A feature missing from 3.2 as well has a real gap and takes the later date.
- Some features cannot be dated, only bounded, and those say so: `zlib` reads as "1.5 or earlier" rather than as 1.5.
  Three entries are bounded today.
  `resource` and `zlib` are already in Python 1.5, the oldest archived documentation build, so they are at least that old and may be older.
  `os.path` reads "1.2 or earlier" for a different reason: Python 1.1 ships it, but the 1.1 interpreter built from that release's own tarball cannot import it, so that absence belongs to the build rather than to the release and cannot date anything.
  A bound is a limit on what the sources could read rather than a date, so a bounded feature is left out of the minimum version entirely.
- Anything present in Python 0.9.1 is dated 0.9, the first public release, and reads like any other version.
  Python began before it was published, so a few of those are genuinely older, but there is no earlier release for them to have been added in: nothing has been in Python longer than Python has been public.
  Those entries are dated rather than bounded for that reason, and each one's evidence still records that it may predate the public record.
- Release dates come from python.org's downloads database back to 2.2, and from CPython's release tags before that.
  Python 0.9 and 1.6 are the two rows neither source reaches, 0.9 because CPython's history begins after it and 1.6 because it was cut by BeOpen and has no tag, so both are taken from Wikipedia's table of versions.
  The 0.9 date is that table's date for the whole 0.9 line, while the corpus reads the 0.9.1 tarball, which was cut within days of it and which no source dates on its own.
- Searching for a member with no entry of its own falls back to the member index, which covers about 6,000 members across 599 modules and classes.
  Its versions are derived by the same machinery that rechecks every entry in the dataset, so an answer from it is the answer an entry would carry; what it does not carry is the evidence, which is most of what an entry is for.
  It holds only names the newest Python still documents, so a member Python 3 removed is not in it; only names the sources agree about; and only names something corroborates, so a member whose sole evidence is a 3.x inventory diff is left out rather than dated by the age of its markup.
  A member the index has never heard of falls back to the module it lives in, as before.
- A method of a builtin type is dated for searching but is mostly not detected, because `value.removeprefix(...)` says nothing about what `value` is.
  Only a receiver whose type is certain reports one: a literal, as in `"Mr. Smith".removeprefix("Mr. ")`, or the type's own name, as in `dict.fromkeys(keys)`.
- `removed` says when a feature was taken away, and it is the mirror of `added`: the oldest release from which it has been *un*available ever since.
  A gap is not a removal, so `callable()` has none: it went away in 3.0 and came back in 3.2.
  There is no "or later" to match "or earlier", because the corpus reaches the newest Python and a name that is gone has a last release somewhere inside it.
- Removed syntax is searchable and never detectable.
  A Python 3.14 parser cannot produce a node for `<>`, `print x`, a backtick or the `exec` statement, so nothing can spot them in your code, and looking them up still works.
  Removed *names* are detected as usual: `apply(f, args)` parses fine, so old code reports it like anything else.
- There is no `maximum_version()`.
  It would be exactly as true as `minimum_version()` and exactly as beside the point: this tool answers how long something has been in Python, not what version you should target.


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

The matcher kinds are `nodes` (AST node class names), `builtins`, `modules`, `attributes` (dotted `module.name` paths), `methods` (`type.method` for a builtin type, or `module.Class.method` for a class in a module), and `spellings` (ways of writing something this parser can no longer produce a node for, which are searchable and never detected).
Node matchers can be narrowed with `requires` (a node attribute that must be truthy) or `check` (a predicate registered in `detect.py`).

A feature Python has taken away adds `removed` and a `[features.removed_evidence]` table of its own:

```toml
[[features]]
id = "apply"
name = "apply()"
added = "1.0"
category = "builtin"
removed = "3.0"
builtins = ["apply"]

[features.evidence]
method = "source"
symbol = "apply"
file = "Python/bltinmodule.c"
absent_in = "0.9"
present_in = "1.0"
checked = "2026-08-08"

[features.removed_evidence]
method = "interpreter"
symbol = "apply"
present_in = "2.7"
absent_in = "3.0"
checked = "2026-08-08"
```

Only three methods may settle a removal: `interpreter`, `grammar` and `manual`.
A removal is an absence claim, and the methods whose absences prove nothing cannot make one.
`just verify-dataset` re-derives it in both directions, so an entry that stays silent while its feature goes away fails as loudly as one that invents a removal.

Documentation links are generated from `added` and `pep`, so only set `docs` when you have a better link than the "What's New" page.

Nobody should be typing version numbers from memory.
For anything in the standard library, let the archived documentation say what the version is:

```console
$ just fetch-docs                       # one-time, ~2 GB into a gitignored .cache/
$ just whenadded math.lcm               # what each source says, and whether they agree
$ just propose math.lcm math.isqrt      # entries with evidence, ready to paste
$ just typemethods --compare            # what the builtin types' method tables date
$ just verify-dataset                   # re-derive every claim in the dataset
```

`just verify-dataset` also runs in CI, so a pull request that edits a version without editing its evidence fails.

Evidence has eight `method` values, seven of which a machine can recheck:

| method        | what it means                                                                                                                               |
|---------------|---------------------------------------------------------------------------------------------------------------------------------------------|
| `objects.inv` | the symbol is absent from one release's Sphinx inventory and present in the next                                                            |
| `archive`     | the same diff over the module lists and built-in function pages in the pre-Sphinx doc builds, back to the 0.9.1 LaTeX                       |
| `source`      | the name is absent from one release's own C or Python implementation and present in the next, which reaches back further than any doc build. For a method of a builtin type this is the type's own method table, which is the only thing that can date `dict.setdefault` or `str.split` at all |
| `interpreter` | that release's own interpreter, built from its tarball, was asked whether the name resolves. Thirty-one of them, 0.9.1 to 3.14                |
| `annotation`  | the documentation dates it itself, in an "Added in version" marker quoted in the entry                                                      |
| `grammar`     | the token is absent from one release's grammar and present in the next, which is what shipped rather than what a PEP intended               |
| `pep`         | the feature's PEP carries a `Python-Version` header                                                                                         |
| `manual`      | a human read the archives and wrote down what they found, and why the other seven do not settle it                                          |

`interpreter` is the only method that reads Python rather than a description of it, and it outranks the rest across the whole timeline, 0.9.1 to 3.14.
It is what settles a name no text can account for: `re.finditer` is defined in Python 2.2's `sre.py` and left out of its `__all__`, so `from sre import *` never bound it and the answer is 2.3, not the 2.2 the docs claim.
On the 3.x line it is the only cross-check `objects.inv` has, and the inventory dates *documentation*: `shutil.SpecialFileError` is first indexed in 3.13 and resolves from 2.7 on.
Building the interpreters needs Docker and the better part of an hour, so the result is committed as `scripts/interpreters.json` and nothing downstream needs a compiler:

```console
$ just build-pythons                    # build 0.9.1 through 3.14 (slow)
$ just build-pythons modern             # or just one half of it
$ just probe-pythons                    # ask them all, and record it
$ just interpreters-vs-dataset          # where they disagree with the dataset
```

`manual` is for the cases where the sources genuinely disagree, and every one of them is printed on every `verify-dataset` run so the override stays visible.

`src/sincewhen/members.txt` is the other file the package ships, and it is generated rather than curated.
It is the member index search falls back to, and it is derived from the same cache by the same rules, so it is rebuilt rather than edited:

```console
$ just memberindex --write              # regenerate the index from the cache
$ just memberindex --module platform    # what the index has for one module
$ just memberindex --grep system        # every module with a member of that name
```

`just verify-dataset` re-derives it and fails if the committed file is not what the sources produce, exactly as it does for every version claim.

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
