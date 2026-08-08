# Changelog

Everything notable that changed in each release of `sincewhen`.
This project follows [semantic versioning](https://semver.org).

Dataset changes are listed apart from everything else, because they are the changes that can alter what `sincewhen` says about code that did not change.
A corrected version is not a cosmetic fix: it changes the answer the tool gives.


## Unreleased

### Dataset

**A removal axis.**
An entry can now say `removed` as well as `added`, so a feature Python took away has somewhere to go instead of being left out by rule.
The two are the same sentence with one word changed and are read off the same presence mask from the same end: `added` is the oldest release a name has been available in ever since, and `removed` is the oldest release it has been unavailable in ever since.
A removal carries its own `[features.removed_evidence]` table, which only the built interpreters, the grammar and `manual` may fill in: a removal is an absence claim, and the methods whose absences prove nothing cannot make one.

Twenty-eight entries that could not exist before, twenty-six of them removed in 3.0:

- **Fifteen builtins**: `apply`, `basestring`, `buffer`, `cmp`, `coerce`, `execfile`, `file`, `intern`, `long`, `raw_input`, `reduce`, `reload`, `unichr`, `unicode`, `xrange`.
  These are detected as well as searchable, at no cost: `apply(f, args)` parses under a 3.14 parser, so reading old code reports the whole story in one line.
  Fourteen are removed in 3.0 and `cmp()` in 3.1, which the 3.0 docs already distinguish: they spell the rest "Removed apply()" and spell that one "The cmp() function should be treated as gone".
  The 3.0 interpreter resolves it and the 3.1 interpreter does not.
- **Eight methods**: `dict.has_key`, `dict.iterkeys`, `dict.itervalues`, `dict.iteritems`, `dict.viewkeys`, `dict.viewvalues`, `dict.viewitems`, `str.decode`.
  `dict.viewkeys` and its two siblings exist in exactly one release: added in 2.7, gone in 3.0.
- **Five pieces of syntax**: the `print` statement, the `exec` statement, backticks, `<>`, and `=` as the equality operator.
  A 3.14 parser cannot produce a node for any of these, so they use a new `spellings` matcher that puts a name in the search index and builds no detector.
  `sincewhen --search print` now tells the whole arc: the statement from 0.9 to 3.0, `from __future__ import print_function` in 2.6, the function in 3.0.
  `=` is the only pre-1.0 removal in the dataset: 0.9.1 spelled equality `=`, and could without ambiguity, because assignment is a statement there and never an expression.
  1.0 replaced it with `==`.

**`argparse` is 2.7, not 3.2.**
It shipped in 2.7 and again in 3.2, with 3.0 and 3.1 lacking it, and this dataset's own rule is that those two do not count against continuity.
The entry had a `manual` override claiming 3.2 on the grounds that a 2.7 claim would mislead anyone on 3.x, which contradicted the rule everything else follows and the four places AGENTS.md states it.
The built interpreters settle it: absent in 2.6, present in 2.7, and the entry is now re-derived rather than overridden.

**`True` and `False` are now entries, dated 2.3.**
Python had no booleans for its first eleven years.
The names arrived in 2.2.1 as ints; PEP 285's `bool` type is 2.3, which is what the 2.7 docs describe and what the built interpreters find.
`None` gets no entry: it predates the "New in version" convention and carries no marker, so nothing dates it.

`callable()` is deliberately not among them.
It went away in 3.0 and came back in 3.2, which under this dataset's own rule is a gap rather than a removal.

`minimum_version()` is unchanged, and there is no `maximum_version()` to go with it.

### Tool

- **Search and the report say when something went away.**
  `dict.has_key` reads "Python 0.9 (released 1991-02-20), removed in 3.0 (released 2008-12-03)", with a release date on each half, and a report line reads "0.9, removed in 3.0".
  `--json` gains a `removed` key, null for everything still here.
- **A misspelled module no longer swallows the search.**
  `sincewhen --search suprocess.Popen` reported "No feature matches" and stopped, throwing away the half of the name that was spelled right.
  A dotted name that matches nothing at all, not even a module, now gets the same suggestions a bare name would: `suprocess.Popen` offers `subprocess.Popen`.
  A real module that simply lacks the member is untouched, so `os.Popen` still answers about `os`.

### Documentation

- **A "Try it in your browser" section**, pointing at [pym.dev/since](https://pym.dev/since), where the tool runs in the tab rather than on a server.
- **A "History you can look up" section**, collecting the stories the dataset tells when read end to end: the arcs where one problem got a better answer every few years, the features that are younger than they feel, and what the mismatches between the sources look like in practice.


## 0.6.0 - 2026-07-30

### Dataset

Six corrected versions, found by building the 3.x releases and asking them.
Five are the same mistake: `objects.inv` dates when a name was *documented*, and these were documented late.

- **`shutil.SpecialFileError` is 2.7, not 3.13.** Indexed in 2.7, dropped for all of 3.x, indexed again in 3.13, and importable from 2.7 on apart from 3.0.
- **`re.RegexFlag` is 3.6, not 3.11.** The 3.11 marker dates its addition to `__all__`.
- **`importlib.import_module()` is 2.7, not 3.1.** First indexed in 3.1.
- **`dis.show_code()` is 3.0, not 3.2.** It shipped undocumented for two releases, as `platform` did in 2.3.
- **`os.DirEntry` is 3.6, not 3.5.** The type is 3.5; nothing binds it under a name until 3.6.
- **The `repr` module entry is gone, replaced by `reprlib` at 3.0.** PEP 3108 renamed it, so `import repr` fails on every Python 3 and the entry was feeding a 1.0 floor into `minimum_version()`.

Four more `dis` opcode constants moved the other way, to the release `Lib/dis.py` first binds the name: `dis.SEND` is 3.12 and `dis.CONTAINS_OP`, `dis.IS_OP` and `dis.END_ASYNC_FOR` are 3.14.
Their markers date the opcode, which is older, and `minimum_version()` was reporting 3.11 for code that raises `AttributeError` until 3.14.
Two entries keep their versions and gained `manual` evidence: `os.mknod` and `hashlib.scrypt` are absent from a build for reasons that are the toolchain's rather than the release's.

- **46 entries for the methods of `bytes`, `bytearray`, `memoryview` and `range`**, the four type families the method-table work had to leave out.
  `sincewhen --search bytes.split` used to come back empty while `str.split` answered 1.6; it now answers 2.6, along with the other 35 string methods the two byte types share and `bytearray`'s seven of its own.
  `memoryview.tobytes()` and `.tolist()` are 2.7, `range.count()` and `.index()` are 3.2, and `bytes.fromhex()` is 3.0.
  `bytes` had 5 dated methods against `str`'s 42, and now has 42 of its own.
- **`bytes.fromhex()` is 3.0 where `bytearray.fromhex()` is 2.6.**
  2.6 and 2.7 spell `bytes` as a synonym for `str`, and no 2.x `str` has `fromhex()`, so that one name waits for the real `bytes` type.

### Research pipeline

- **The interpreter oracle reaches 3.14**, building thirty-one releases instead of fourteen, in a second pinned image.
  This is the cross-check the 3.x half never had: 634 entries rest on `objects.inv` and its failure mode is silent.
  1634 claims are now confirmed by a release that was built and asked.
- **The presence mask is one continuous string**, so "the oldest release it has been available in ever since, ignoring 3.0 and 3.1" is read straight off it.
  2.6 and 2.7 are built for the same reason: without them a 2.6 addition reads as 3.0.
- **A marker naming a micro release explains an interpreter that contradicts it**, since the corpus builds each `.0`.
  Sixteen names, fourteen of them `typing`'s, needed no hand-written note once the extractor kept the micro it had been discarding.
- **A name that kills the interpreter is recorded as unanswered, not absent**, and so is one the probe cannot spell.
  Asking the 3.5 build for `uuid.NAMESPACE_DNS` segfaults it, and "could not be asked" is not a fact about 3.5.
  Every absence from a batch that died is now re-asked on its own, since a hundred names share one process and only a fatal crash is visible.
- **The absence guard reads a tree by that tree's own Python version.**
  A Python 2 C module names itself in `Py_InitModule("dbm", ...)`, and grepping 2.7 for `PyInit_` dated `dbm` to 3.0.
- **The re-add guard no longer covers the interpreter**, which detects a re-add from the mask itself.
  Guarding it fired on most of the 3.x line and hid two of the corrections above.
- **A builtin type closes the bound on its own methods, as a module already did for its members.**
  The inventory can only bound a method of a builtin type, so where that bound sits at exactly the release the type arrived in, `dating.py` reports a date: `memoryview.tolist` is 2.7 rather than "2.7 or earlier".
  Taken only for the four types `type_is_covered` rules out, because elsewhere the head of the name answers a different question: `dict` the builtin is 2.2 and the `dict` type is in 0.9.1.
- **`just whenadded bytearray.pop` shows the whole bracket**, the type's date under it as well as the inventory's bound over it.

### Tool

- **A per-module member index ships with the package, so searching for a module member answers about the member rather than its module.**
  `sincewhen -s platform.system` used to say "no entry, but it lives in `platform`, which is 2.3" and now says `platform.system - Python 2.3`; a bare `TimeoutError` suggests `asyncio.TimeoutError` and two others instead of finding nothing.
  The index is `src/sincewhen/members.txt`, 3,760 members across 248 modules, and every version in it is `scripts/dating.py`'s verdict rather than a fresh opinion, published only where something corroborates it.
  It sits behind `features.toml`, so a name with an entry of its own never reaches it, and `sincewhen.lookup_member()` and `sincewhen.find_members()` are the library equivalents.
- **Python 0.9 has a release date, 1991-02-20, so the 115 entries at the first public release report an age like every other row.**
  They read as a plain `0.9` now instead of `0.9 (first public release)`, and the release column, which was blank for them, carries the date.
  0.9 is the second row neither python.org's downloads database nor CPython's tags can reach, and it comes from the same Wikipedia table of versions that already dates 1.6.
  The date is the 0.9 line's, while this project's corpus is the 0.9.1 tarball, cut within days of it and never separately dated.
  Leaving the row out was the larger error: a blank column says the release has no date at all, which no source claims.
  Every version the dataset can name now has a release date.

### Research pipeline

- **`modindex.py` reads 3289 module members out of the pre-Sphinx doc builds, up from 2165.**
  Four markup changes the extractor had silently stopped matching at: 2.3 moved every signature into a one-row table, 1.5 paginated each module across several pages so `os.listdir` belonged to nothing, 1.2 and 1.3 put the signature before the `-- function of module math`, and 1.4's HTML is a broken LaTeX2HTML run whose members are now read from its own LaTeX instead.
  A regex that stops matching reports an empty module rather than an error, which is why none of it showed up until the member index needed the data.
- **An archive floor no longer outranks a documentation marker of the same version.**
  "Documented in 2.3 and possibly earlier" is a bound and "New in version 2.3" is a date, so `dating.py` returns `docs-date-the-floor` for that pair and reports the date.
  This is the rule the source method already applied, and `os.mknod` is what surfaced its absence.


## 0.5.0 - 2026-07-30

### Dataset

- **115 entries at Python 0.9 are dated rather than bounded.**
  Nothing older than Python 0.9.1 was ever released, so "0.9 or earlier" left open a range of releases that does not exist.
  `max()`, `len()`, `dict.keys()` and 112 more now claim 0.9 outright.
  The reported phrase is unchanged, but `--json` now says `or_earlier: false`, and the evidence still records that the name may predate the public record.
  Three bounded entries remain: `os.path` at "1.2 or earlier", `resource` and `zlib` at "1.5 or earlier".
- **`copyreg` was "1.5 or earlier" and is now 3.0.**
  The old claim dated `copy_reg`, a name Python 3 removed: PEP 3108 renamed it in 3.0, so no earlier release can import this spelling.
  The old name's history stays in the evidence note.
- **Two more syntax entries, both from before Python 2.**
  A dict display with items, `{'k': 1}`, is 1.0: 0.9.1's grammar allows nothing between the braces, so only the empty display is as old as Python.
  Unpacking at a call, `f(*args)` and `f(**kwargs)`, is 1.6, where both spellings arrived in one `arglist` line; `apply(f, args)` was the spelling before.
  Collecting is older and separate: `def f(*args)` is 1.0, `def f(**kwargs)` is 1.5, and neither fires this entry.

### Tool

- **A bounded feature no longer sets a floor in `minimum_version()`.**
  "1.5 or earlier" is a limit on what the sources could read, not a date, so treating it as one could claim a minimum newer than the truth.
  A file whose only detected features are bounded now gets `None` instead of a bound presented as exact.

### Research pipeline

- **`dating.py` refuses a keyword instead of answering from a documentation anchor.**
  `uv run scripts/dating.py in` used to report 3.2, the age of the reference manual's anchor for the `in` section rather than of the operator, which is in the 0.9.1 grammar.
  A keyword now points at `grammar.py`, and `verify-dataset` demands grammar evidence for one.
  Soft keywords are still answered, because `type` is a builtin and `match` and `case` are ordinary names.
- **The floor rule lives in one place.**
  `Verdict.or_earlier` reports a bound only where a release below it could still be the answer, so no method can produce a "0.9 or earlier" claim.


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
