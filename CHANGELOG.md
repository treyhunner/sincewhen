# Changelog

Everything notable that changed in each release of `sincewhen`.
This project follows [semantic versioning](https://semver.org).

Dataset changes are listed apart from everything else, because they are the changes that can alter what `sincewhen` says about code that did not change.
A corrected version is not a cosmetic fix: it changes the answer the tool gives.


## Unreleased

### Dataset

- **115 entries at Python 0.9 are dated rather than bounded.**
  They used to carry `or_earlier = true`, which said that 0.9 was as far back as the sources reach and the feature might be older still.
  That is true and unusable: nothing older than Python 0.9.1 was ever released, so the bound left open a range of releases that does not exist.
  `max()`, `len()`, `dict.keys()`, `math.sqrt()` and 111 more now claim 0.9 outright.
  The reported phrase is unchanged, since these already read as "0.9 (first public release)", but `or_earlier` is now `false` for them in the dataset and in `--json` output.
  Each one's evidence still records that the name is at least that old and may predate the public record.
- **Four entries are still bounded**, and all four leave a real question open: `os.path` at "1.2 or earlier", and `copyreg`, `resource` and `zlib` at "1.5 or earlier".
- **Two more syntax entries, both from before Python 2.**
  A dict display with items, `{'k': 1}`, is 1.0: 0.9.1's `atom` rule spells a dict `'{' '}'` with nothing allowed between the braces and its grammar has no `dictmaker` rule at all, so only the empty display is as old as Python.
  Unpacking at a call, `f(*args)` and `f(**kwargs)`, is 1.6, where both spellings arrived in the same `arglist` line.
  `apply(f, args)` was how it was written before, and the 1.5 interpreter raises `SyntaxError` on either spelling.
  The call entry carries `manual` evidence rather than `grammar` evidence, because the 1.6 change is inside a rule's body and `grammar.py` indexes token and rule names: `arglist` and `argument` are both 1.3, `'*'` is 0.9 as multiplication and `'**'` is 1.4 as exponentiation, so there is no symbol for the evidence to cite.
  Collecting is a different feature and an older one: `def f(*args)` is 1.0 and `def f(**kwargs)` is 1.5, and neither fires this entry.

### Research pipeline

- **`dating.py` refuses a keyword instead of answering from a documentation anchor.**
  `uv run scripts/dating.py in` used to report 3.2, which is when someone wrote the reference manual's anchor for the `in` section, not when the operator arrived: it is in the 0.9.1 grammar.
  Every keyword has such a label, so `if`, `for`, `while` and `return` were all answerable and all wrong.
  A keyword now reports a `keyword` status and points at `grammar.py`, which is the method that settles syntax, and `verify-dataset` asks for grammar evidence rather than accepting the label.
  Soft keywords are deliberately still answered, because `type` is a builtin this dataset dates to 0.9 and `match` and `case` are ordinary names.
- **The floor rule lives in one place.**
  `Verdict.or_earlier` reports a bound only where a release below it could still be the answer, so no method can produce a "0.9 or earlier" claim now.
  The evidence notes are keyed on the underlying open bound instead, which is what keeps the "may be older" record on the 0.9 entries.


## 0.4.0 - 2026-07-29

### Dataset

- **105 entries for the methods of the builtin types**, where there were none.
  `sincewhen --search removeprefix` used to come back empty; it now answers 3.9, and so do `setdefault` (2.0), `split` (1.6), `mro` (2.2), `isdisjoint` (2.6), `bit_count` (3.10) and a hundred more.
  A method answers to its own name as well as to `type.method`, because nobody searching for `removeprefix` types the type in front of it.
- **Most of them could not have come from the documentation.**
  The docs date 58 of the 397 methods they index; a method older than the "New in version" convention never got a marker, so the rest are read from the types' own method tables in CPython's source:

  | release | what the tables show                                                              |
  |---------|-----------------------------------------------------------------------------------|
  | 0.9     | `dict.keys`, `list.append`, `list.insert`, `list.sort`, bounded rather than dated    |
  | 1.0     | `dict.items`, `dict.values`, and `list.count`, `index`, `remove`, `reverse`          |
  | 1.5     | `dict.clear`, `copy`, `get`, `update`, and `list.extend`, `pop`                      |
  | 1.6     | the string methods, 29 of them, from `split` to `startswith` to `translate`         |
  | 2.0     | `dict.setdefault`, `str.encode`, `str.isalnum`, `str.isalpha`                        |
  | 2.1-2.4 | `dict.popitem`, `type.mro`, `slice.indices`, then every `set` and `frozenset` method |

  So Python's dictionary had `keys()` and `has_key()` and nothing else in 1991, and could not be copied or updated until 1.5.
- **A pre-2.6 method entry is a claim about instances.**
  `"x".split()` is 1.6; `str.split` written as an unbound call needs 2.2, because `str` was a builtin function and not a class until then.
- **Five entries swapped a doc marker for the method table that outranks it** and all five kept their version, which is the cross-check worth having: nine of the names the tables date carry a marker too, and nine of nine agree.
- **`==`, `!=`, `in`, `not in` and tuple unpacking have entries now**, all settled by CPython's own grammar rather than by a PEP or a doc.
  `==` and `!=` are 1.0: 0.9.1 spelled equality `=`, and could without ambiguity, because assignment is a statement there and never an expression.
  `in`, `not in` and `a, b = 1, 2` are all in the 0.9.1 grammar, so they report as "0.9 or earlier".
  These fire on almost every file ever written, which costs one line each in a report, since the default shows the first use of a feature rather than every use.
- **Anything Python 3 removed stays out**, for the reason the Python 2 builtins do: `added` has no way to say "and then it was taken away".
  So `str.decode`, `dict.iteritems` and `<>` have no entries even though the sources date all three.

### Tool

- **A new `methods` matcher kind**, for the methods of builtin types.
  These are searchable everywhere and detected only where the receiver's type is certain: a literal, as in `"Mr. Smith".removeprefix("Mr. ")`, or the type's own unshadowed name, as in `dict.fromkeys(keys)`.
  `value.removeprefix(...)` is not reported, because `value` could be anything with that method and a wrong version is worse than a missing one.
- **Python 1.6 has a release date**, 2000-09-05, so the 29 entries that land on it read like every other release instead of printing a bare version.
  It is the one hand-entered row: 1.6 was cut by BeOpen and CPython has no `v1.6` tag, so neither machine-readable source can reach it.
  `UNTAGGED` in `scripts/release_dates.py` records why that fills a hole rather than becoming a second opinion on the rows the tags already answer for.

### Research pipeline

- **A new oracle, `scripts/typemethods.py`**, reads the method tables of the builtin types out of every CPython tarball from 0.9.1 to 2.5, which is `source.py`'s argument one level down: a method table is the list a type registers its methods from, so a name missing from it is a name that release did not have.
  86 names, 80 dated outright.
  Four rules decide whether that can be believed, and AGENTS.md explains each: a type is a *family* (2.x `str` is `stringobject.c` and `unicodeobject.c`, which disagree), a dunder is a slot rather than a table row, the getset and member tables are never read, and a row inside an `#if` proves nothing either way.
- **Two markers the docs never meant were caught by comparing the tables against them.**
  `dict.values` is 1.0 and read as 3.9, off a marker belonging to `d | other` two signatures away; `str.translate` is 1.6 and read as 2.6, off one that dates an argument.
  Both resolve correctly now, and a type method's evidence note says "the nearest marker" rather than "the docs date it".
- **An inventory entry for a member of a builtin type bounds rather than dates.**
  `stdtypes` documents a family of types in one table and Sphinx grew per-name markup release by release, so the release that first indexes one is the age of the markup: `list.copy` arrived in 3.3 and was first indexed in 3.13.
  The inventory used to date 213 of those 397 names and now dates none, so 179 confident answers are refused instead.
  The 2.6-to-2.7 step looked safe and was the worst of them, dating 20 `frozenset` methods to 2.7 where `frozenset` is 2.4, `frozenset.add` among them, which no `frozenset` has ever had.
- **`annotations.py` reads `classmethod`, `static` and `abstractmethod` signatures**, which it skipped before, so their markers no longer attach to whatever came earlier.
  That dated 35 names the markers were stranded on and dropped 15 they were wrongly attached to, `datetime.date`'s false 3.7 among them.
- **`grammar` evidence can express a bound**, which it could not before, so a token already in the 0.9.1 grammar can be recorded as "0.9 or earlier" rather than failing its own check.
- `just typemethods` reports what the tables date, with `--tables`, `--partial` and `--compare`.
  `just propose` writes `methods` entries and names a group the way the dataset already names one.


## 0.3.0 - 2026-07-29

### Dataset

- **254 features have a better answer, because the version now comes from that release's own interpreter.**
  All fourteen releases from 0.9.1 to 2.5 are built from their pinned tarballs and asked whether a name resolves.
  Every other method in the pipeline reads a description of Python; this one reads Python, so it sees what no text can.

  | what changed                                 | count | example                                             |
  |----------------------------------------------|-------|-----------------------------------------------------|
  | an older, exact version replaces a newer one | 183   | `operator` was 1.5, is 1.4                          |
  | a bound became an exact version              | 71    | `math.fmod` was "1.0 or earlier", is 1.0            |
  | a bound stayed a bound, but a tighter one    | 1     | `os.path` was "1.5 or earlier", is "1.2 or earlier" |
  | anything moved to a newer version            | 0     |                                                     |
  | anything got vaguer                          | 0     |                                                     |

  No file can report a higher minimum version than it did in 0.2.0.

- **Bounded features drop from 346 to 113.**
  109 of those sit at Python 0.9.1, the first public release, and are bounded because nothing older survives to be asked.
  Only four remain above that floor: `os.path`, `resource`, `zlib` and `copyreg`, each because a module needed something the interpreter build could not provide.
  The "or earlier" problem is now almost entirely the floor itself.
- **A feature at that floor no longer reports as "0.9 or earlier".**
  It reads `0.9 (first public release)` instead, because "or earlier" is an evasion when there is no earlier release to reach for: nothing has been in Python longer than Python has been public.
  The `or_earlier` flag is unchanged for anything reading the dataset, since the claim itself has not changed.
- **`re.finditer` stays 2.2, and now says why.**
  Python 2.2.0 defines `finditer` in `Lib/sre.py` behind a `sys.hexversion` guard that passes, but `sre.__all__` does not list it and `re.py` is `from sre import *`, so `re.finditer` does not exist in 2.2.0 or 2.2.1.
  2.2.2 added `__all__.append("finditer")` and fixed it.
  The interpreters this dataset is checked against are feature releases, so the 2.2 they build is 2.2.0 and it reports the name as absent.
  The docs are right about the release and the interpreter is right about 2.2.0, so the entry records both rather than picking one.
  A version derived from an interpreter is no longer allowed to be *newer* than a documented one without a human agreeing: that is precisely where a micro release may have fixed something the `.0` could not do.
- Notable answers that got older, all of them modules or members the archives could only bound because a C extension's availability is a build-time choice:
  - `operator` is 1.4, not 1.5, which dates its 31 members with it.
  - `signal` is 1.1 and `fcntl` is 1.0, where the tarball alone could not say whether `Modules/Setup` would compile them.
  - `cmath` is 1.4, `os.path` is 1.2, and `mmap` and `unicodedata` are 1.6 rather than 2.0.
  - `itertools.chain` is 2.3, not 2.6, where 2.6 was only the oldest inventory that indexed it.
  - `re.UNICODE` is 1.6, not 3.11.
- Every claim is still re-derived by `just verify-dataset`, which now has the interpreters to check them against as well.

### Tool

- **Removed the `Minimum: Python X` line from the end of a report.**
  `sincewhen.minimum_version()` is unchanged for anyone who wants that number from the library.


## 0.2.0 - 2026-07-29

### Dataset

- **441 features have a better answer than 0.1.0 gave**, because their versions now come from CPython's own source rather than from the oldest documentation that happened to describe them.
  Mostly this makes a vague answer exact rather than swapping one exact answer for another.
  Nothing became vaguer, and nothing moved to a *newer* version, so no file can report a higher minimum than it did before:

  | what changed                                                 | count | example                                              |
  |--------------------------------------------------------------|-------|------------------------------------------------------|
  | a bound became an exact version                              | 209   | `socket.error` was "1.0 or earlier", is 1.0          |
  | a bound became an exact, older version                       | 100   | `bisect` was "1.5 or earlier", is 1.0                |
  | a bound stayed a bound, but an older and truer one           | 109   | `calendar` was "1.5 or earlier", is "0.9 or earlier" |
  | an exact version was wrong and is now an older exact version | 23    | `turtle` was 2.2, is 1.5                             |
  | anything got vaguer                                          | 0     |                                                      |

- **Bounded features drop from 655 to 346.**
  A feature reported as "1.5 or earlier" was usually not that old: it was as old as the first doc build that wrote it down, which is a fact about the archive rather than about the feature.
  Of the 346 that remain, 109 sit at Python 0.9.1, the first public release and as far back as any record goes.
  Those are bounded because nothing older survives, which is the only honest reason to be.
- The 23 versions that were exact and wrong, rather than merely vague, are worth naming.
  In every case 0.1.0 reported the release that first *documented* the feature:
  - `turtle` is 1.5, not 2.2.
  - `linecache`, `sched` and `wave` are 1.0, not 1.6.
  - `difflib.SequenceMatcher` is 2.1, not 2.7.
    2.7 came from a doc marker that dates a parameter rather than the class.
  - `tempfile` and `ftplib` are 1.0, not 1.2, and `tempfile.gettempdir()` is 1.0, not 2.3.
  - `globals()` and `locals()` are 1.3, not 1.5.
    Neither is in the 1.2 builtins table and both are in the 1.3 one.
  - `complex()`, `list()` and `slice()` are 1.4, not 1.5.
  - `types`, `traceback`, `urllib`, `tty` and `pty` are 1.1, not 1.2 or 1.6.
  - `codeop` and `rlcompleter` are 1.5, `trace` is 2.3, and `cProfile` is 2.5, each a release earlier than claimed.
- Notable answers that stopped being vague:
  - `bisect.insort()` and `bisect.bisect()` are 1.0, not "1.5 or earlier".
    `Lib/bisect.py` is in the 1.0.1 tarball; the 1.5 docs are simply the oldest that mention it.
  - `random.choice()`, `random.random()` and `random.uniform()` are 1.1, not "2.1 or earlier".
    `random` re-exported them from `whrandom` from 1.1 on.
  - `weakref.ref`, `gc.DEBUG_LEAK`, `locale.LC_ALL` and 55 others stop saying "or earlier" without moving.
    A member cannot predate the module that holds it, so a bound at exactly the release its module arrived in was never a bound at all.
  - `calendar.day_abbr`, `calendar.month_name` and their neighbours are "0.9 or earlier", not "2.5 or earlier".
    They are in the 0.9.1 library, and 2.5 is only when they were written down.
    Still a bound, but one that reports the age of the feature rather than the age of the archive.
- Every claim is still re-derived by `just verify-dataset`, which now rechecks whether a version is a date or a bound as well as the version itself.

### Research pipeline

Not user-facing, but it is what the dataset rests on.

- `scripts/source.py` reads module members out of the implementation, in two tiers.
  A C module's namespace is written down in full, in the method table its registration call names and the calls that insert its constants, so a name missing from it is a name that release did not have.
  A Python module's need not be, since `os.py` is little more than `from posix import *`, so a module that star-imports can only tighten a bound and never date anything.
- The source corpus grows from three releases to fourteen, 0.9.1 through 2.5, which is the whole era the Sphinx inventories cannot reach.
  `just fetch-docs` now caches about 500 MB.


## 0.1.0 - 2026-07-28

First release.

### Dataset

- 1690 features, reaching back to Python 0.9.1.
  Every entry carries the evidence for the version it claims, and `just verify-dataset` re-derives all of them from the archived documentation.
- Features that predate the oldest archive that documents them are bounded rather than dated, and report as "1.2 or earlier".

### Tool

- `sincewhen FILE` lists every dated feature a file uses, with the version that added it and the day that version shipped, then reports the minimum Python the file needs.
- `--all` shows every occurrence rather than the first use of each feature.
- `--since VERSION` hides anything older than the given version.
- `--search NAME` looks a single feature up by name instead of analyzing code.
- `--json` gives machine-readable output in either mode.
- `-` reads from standard input.
- `--version` prints the installed version.
- A library API: `sincewhen.minimum_version()`, `sincewhen.detect()`, and `sincewhen.lookup()`.
