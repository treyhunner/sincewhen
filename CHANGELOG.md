# Changelog

Everything notable that changed in each release of `sincewhen`.
This project follows [semantic versioning](https://semver.org).

Dataset changes are listed apart from everything else, because they are the changes that can alter what `sincewhen` says about code that did not change.
A corrected version is not a cosmetic fix: it changes the answer the tool gives.


## Unreleased

### Dataset

- **`x = yield value` is 2.5, where it read as 2.2.**
  PEP 342 made `yield` an expression, and the dataset had only the 2.2 entry for the statement, so every `Yield` node answered 2.2 and any code that used the value a generator hands back had its floor understated by three releases.
  The grammar settles it: 2.4 has `yield_stmt: 'yield' testlist` and nothing else mentions yield, and 2.5 adds `yield_expr` and rewrites `yield_stmt` as a wrapper around it.
  Both entries fire for the expression form, which is two true statements about one line, and the newer one sets the floor.
  This is also the beat the async story turns on, and the reason the README can now tell that arc: a 2.2 generator could only hand values out, and receiving one is what `send()`, `yield from` and everything after them are built on.
- **The member index reaches inside a class.**
  An owner is now a module or a class in one, so `unittest.TestCase.assertNotEndsWith`, `pathlib.Path.walk` and `datetime.date.fromisoformat` have answers where they had none at all.
  2,658 class members join 3,918 module members, and the file goes from 48 KB to 91 KB.
  A member of an attribute is still out: `inspect.Parameter.kind.description` is one level deeper than the index goes.
- **`source.py` reads class bodies, which is what dates the old ones.**
  `unittest.TestCase.assertAlmostEqual` was already in the 2.6 inventory, the oldest there is, so no diff could date it and nothing that reaches further back could see a class member at all.
  Reading `Lib/unittest.py` settles it: absent from 2.1 and 2.2, bound in 2.3.
  The source answers 604 class members this way, 551 of them with a date rather than a bound, `unittest.TestCase.setUp` at 2.1 and `assertTrue` at 2.4 among them, and 525 fewer come back unanswered.
  The tier is decided per class, as it already was per module: a class that inherits nothing is written down in full so absence is proof, and a class with bases is presence-only.
  The library files are read through a scanner that blanks strings and comments first, because a class docstring is full of things that look like code: without it `ftplib.FTP` reported no methods at all, `random.Random` lost five, and `SimpleXMLRPCServer` grew a class its module docstring only mentions.
  It corrects four dates the docs got wrong, all of them markers attached to the wrong thing: `pstats.Stats.sort_stats` is 1.1, not the 3.7 of the enum its nearest marker describes, and `imaplib.IMAP4.namespace` is 2.2, not 2.3.
- **Half of what is asked about a class member is still unanswered, on purpose.**
  A class page grows a member at a time and lists what the class *inherits* alongside what it defines, so the release that first indexes one is often the age of the markup rather than the age of the method.
  An inventory diff alone therefore publishes a class member only where it was indexed in the class's own release.
  Without that, `enum.Enum.name` read as 3.11 against a class that is 3.4, `logging.Logger.name` as 3.11, and `pathlib.Path.as_uri` as 3.13, which is when the method moved down from `PurePath`.
  Those now fall back to the module, which is vaguer and true.
- **183 documentation markers that were being dropped.**
  A directive may carry several signatures and one description, and only the last of them was getting the marker underneath.
  `os.spawnl` and four siblings move from "2.2 or earlier" to 1.6, `operator.iadd` and fourteen more from "2.5 or earlier" to 2.5, and `bytes.maketrans` (3.1), `bytes.isascii` (3.7) and eighteen `stat.FILE_ATTRIBUTE_*` constants (3.5) gain dates the index had nothing for.
  What counts as one directive is the run of signature lines with no blank between them, which is what reST's continuation lines render as; two adjacent directives get a blank line and stay two things.
  A grouped marker that names one of the group is read as being about that one, quoted or bare, which is what keeps `typing.Never` from inheriting the 3.6.2 that belongs to `NoReturn` and stops `sys.__excepthook__` collecting both its neighbours' versions.
  One that names something outside the group is about none of it: `assertRegex` is 3.2, not the 3.1 its description mentions for the old `assertRegexpMatches` spelling.
- **Eight entries for the assertion methods Python 3.14 added to `unittest.TestCase`**: `assertStartsWith`, `assertNotStartsWith`, `assertEndsWith`, `assertNotEndsWith`, `assertHasAttr`, `assertNotHasAttr`, `assertIsSubclass` and `assertNotIsSubclass`.
  Three of them are dated by the inventory rather than by a marker, because CPython writes those pairs as two adjacent directives with the description under the second and there is no way to tell that from a list of separate names. Their evidence says so.

### Tool

- **`self.assertNotEndsWith(...)` is detected, not just searchable.**
  The `methods` matcher now accepts a class in a module as an owner, and reads one more receiver as certain: `self`, inside a class whose own bases name the type.
  `class Test(unittest.TestCase):` and `class Test(TestCase):` both count, and so do the unbound spellings.
  A subclass of a subclass does not, and neither does `from django.test import TestCase`, which resolves to `django.test.TestCase` and matches nothing.
  A class that defines the method itself suppresses the match, the same way a module that binds its own `sum` does.
- **A bare method name reads as an answer, not a guess.**
  `sincewhen -s assertEqual` said "No entry for 'assertEqual'. Did you mean one of these?" above the correct answer, while `sincewhen -s removeprefix` printed its answer plainly.
  Same question, and the only difference was which of the two data files answered.
  One hit now prints bare, several are introduced with "is a member of:", and "Did you mean one of these?" is kept for the branch that really is guessing at a spelling, which is a misspelled module like `suprocess.Popen`.
- **`--json` search results name an `owner` where they named a `module`.**
  The field holds a class as often as a module now, and `"module": "unittest.TestCase"` would be false.
- **A check knows what its node hangs off.**
  A matcher predicate was handed a node and the names the module binds, which is everything a node can be asked about itself and nothing about where it sits.
  `ast` records no link back up, and the same node can mean two things: a `Yield` is the 2.2 statement directly under an `Expr` and the 2.5 expression everywhere else.
  The pair is now a `Context`, so the parent is there for the one check that reads it, and `yield (yield x)` gets both readings on one line rather than whichever the coarser question would have picked.

### Documentation

- **"What a class member may claim"**, folded into the member index section of `AGENTS.md`: why the class level needed a stricter rule than the module level, which 160 names it drops and which of those were wrong.
- **`tests/test_annotations.py`**, pinning the marker-to-signature shapes one test per shape, as `tests/test_modindex.py` already does for the archives.
  Both extractors fail by going quiet rather than by raising.


## 0.7.0 - 2026-08-08

### Dataset

- **A removal axis.**
  An entry can now say `removed` as well as `added`, so a feature Python took away has somewhere to go instead of being left out by rule.
  Both are read off the same presence mask: `removed` is the oldest release a name has been unavailable in ever since.
  A removal is an absence claim, so only the built interpreters, the grammar, and `manual` may fill in its `[features.removed_evidence]` table.
  A gap is not a removal, which is why `callable()` is not among these.
- **Twenty-eight entries that could not exist before**, twenty-six of them removed in 3.0.
  Fifteen builtins, `apply` through `xrange`, which detect as well as search: `apply(f, args)` parses under a 3.14 parser, so reading old code reports the whole story in one line.
  Eight methods: `dict.has_key`, the three `iter*` and three `view*` spellings, and `str.decode`.
  Five pieces of syntax: the `print` and `exec` statements, backticks, `<>`, and `=` as the equality operator.
  A 3.14 parser can produce no node for those five, so they use a new `spellings` matcher, which puts a name in the search index and builds no detector.
- **`argparse` is 2.7, not 3.2.**
  It shipped in 2.7 and again in 3.2, and this dataset does not count 3.0 and 3.1 against continuity.
  The entry carried a `manual` override claiming 3.2, and the claim is now re-derived instead.
- **`True` and `False` are entries, dated 2.3.**
  The names arrived in 2.2.1 as ints, and PEP 285's `bool` type is 2.3.
  `None` gets no entry, because it predates the "Added in version" convention and nothing dates it.

`minimum_version()` is unchanged, and there is no `maximum_version()` to go with it.

### Tool

- **Search and the report say when something went away**, with a release date on each half: `dict.has_key` reads "Python 0.9 (released 1991-02-20), removed in 3.0 (released 2008-12-03)".
  `--json` gains a `removed` key, null for everything still here.
- **A misspelled module no longer swallows the search.**
  `sincewhen --search suprocess.Popen` reported "No feature matches" and stopped; it now offers `subprocess.Popen`.
  A real module that simply lacks the member is untouched, so `os.Popen` still answers about `os`.

### Documentation

- **Two new README sections**: "Try it in your browser", pointing at [pym.dev/since](https://pym.dev/since), and "History you can look up", collecting the stories the dataset tells when read end to end.
- **"The removal axis" in `AGENTS.md`**, recording what may settle a `removed` claim, why the list is so short, and what `errno` would need so both fields are designed together.
- **Two counts the README quotes are refreshed**, having gone stale at 0.6.0 when building the 3.x interpreters produced 26 contradiction verdicts on its own.


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
