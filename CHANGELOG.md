# Changelog

Everything notable that changed in each release of `sincewhen`.
This project follows [semantic versioning](https://semver.org).

Dataset changes are listed apart from everything else, because they are the changes that can alter what `sincewhen` says about code that did not change.
A corrected version is not a cosmetic fix: it changes the answer the tool gives.


## Unreleased

### Dataset

- **37 new entries for the methods of the builtin types**, which is a gap you could previously only find by searching for one.
  `sincewhen --search removeprefix` came back empty; it now answers "Python 3.9", and so do `is_integer`, `isascii`, `casefold`, `format_map`, `bit_count`, `to_bytes`, `fromkeys`, `__set_name__` and the rest.
  A method answers to its own name as well as to `type.method`, because nobody searching for `removeprefix` types the type in front of it.
- Two of those needed a human, and the reason is worth reading:
  - **`copy()` and `clear()` on `list` and `bytearray` are 3.3.** The docs describe them once for the whole mutable-sequence family, as `sequence.copy`, so no per-name marker dates them, and the inventory does not index `list.copy` until 3.13. The 3.3 whatsnew names both types outright.
  - **`int.bit_length()` is 2.7**, which the 2.7 inventory shows and the 3.14 docs contradict with a 3.1 marker. Both are true: it shipped in 2.7 and again in 3.1, and 3.0 is the only release in between that lacks it.
- **68 more entries for the ancient methods, out of the types' own method tables**, which no doc build could ever date.
  `sincewhen --search setdefault` now answers "Python 2.0", and `split`, `append`, `keys`, `startswith` and 60-odd more answer for the first time.
  339 of the 397 methods the docs index carry no version marker at all, because a method that predates the "New in version" convention never got one.

  | release | what the tables show                                                                       |
  |---------|--------------------------------------------------------------------------------------------|
  | 0.9     | `dict.keys`, `list.append`, `list.insert`, `list.sort`, bounded rather than dated            |
  | 1.0     | `dict.items`, `dict.values`, `list.count`, `list.index`, `list.remove`, `list.reverse`       |
  | 1.5     | `dict.clear`, `dict.copy`, `dict.get`, `dict.update`, `list.extend`, `list.pop`              |
  | 1.6     | the string methods, 29 of them, from `split` to `startswith` to `translate`                 |
  | 2.0     | `dict.setdefault`, `str.encode`, `str.isalnum`, `str.isalpha`                                |
  | 2.1     | `dict.popitem`                                                                              |
  | 2.2     | `type.mro`, which the inventory would have called 3.12                                      |
  | 2.3     | `slice.indices`                                                                             |
  | 2.4     | every `set` and `frozenset` method, since `setobject.c` arrives in that release              |

  So Python's dictionary had `keys()` and `has_key()` and nothing else in 1991, and could not be copied or updated until 1.5.
- **A pre-2.6 method entry is a claim about instances.** `"x".split()` is 1.6; `str.split` written as an unbound call needs 2.2, because `str` was a builtin function and not a class until then. The head of the name is deliberately not consulted: `dict` the builtin is 2.2 and the `dict` type is in 0.9.1.
- **Five entries had their evidence re-derived**, from a doc marker to the method table that outranks it: `str.encode`, `dict.fromkeys`, `dict.pop`, `str.rsplit` and `str.partition`. All five keep the version they had, which is the cross-check: nine of the names the tables date have a marker too, and nine of nine agree.
- **`str.zfill()` stays 2.2 and now says why.** The 1.6 through 2.2 tables carry its row inside an `#if 0`, because it really arrived in 2.2.2, so the source can only bound it at "2.3 or earlier" and the docs' own marker wins.
- **`list.extend()` and `list.pop()` are 1.5.2, recorded as 1.5**, which is the corpus's 1.5 slot: it reads the 1.5.2 tarball, and both are in that release's own `Misc/NEWS`. A micro release is still 1.5 at this dataset's granularity, the same reading that keeps `str.zfill` at 2.2, and the evidence on both entries says so. `dict.clear()`, `dict.copy()`, `dict.get()` and `dict.update()` are in the 1.5.2 `HISTORY` instead, so those four are 1.5 proper.
- **Methods Python 3 removed are deliberately absent**, for the same reason the Python 2 builtins are: `added` has no way to say "and then it was taken away". `str.decode`, `dict.iteritems` and `dict.viewkeys` are all dated by the 2.7 docs and all stay out.
- **`datetime.date` no longer carries a 3.7 marker it never earned.** A version marker attaches to the signature above it, and `classmethod date.fromisoformat(...)` did not match the signature pattern, so its 3.7 marker landed on the class instead. This was invisible in the shipped dataset because the source method outranked it, and it is the kind of thing that stops being invisible later.

### Tool

- **A new `methods` matcher kind**, for the methods of builtin types.
  These are searchable everywhere and detected only where the receiver's type is certain: a literal, as in `"Mr. Smith".removeprefix("Mr. ")`, or the type's own unshadowed name, as in `dict.fromkeys(keys)`.
  `value.removeprefix(...)` is not reported, because `value` could be anything with that method, and a wrong version number is worse than a missing one.

### Research pipeline

- **A new oracle, `scripts/typemethods.py`, reads the method tables of the builtin types** out of every CPython tarball from 0.9.1 to 2.5.
  This is `source.py`'s argument one level down: a type's method table is the list it registers its methods from rather than a description of one, so a name missing from it is a name that release did not have.
  86 names come out of it, 80 dated outright.
  Four decisions govern whether any of it can be believed, and each one had a wrong answer available:
  - **A type is a family.** `stringobject.c` is the 2.x string and `unicodeobject.c` is what became `str`, and their tables disagree: `encode` is in the unicode table from 1.6 and the string table from 2.0. A member counts as present only where every type in the family binds it, which makes `str.encode` 2.0 and agrees with the marker the docs already carry. `isdecimal` and `isnumeric`, which the 2.x string type never had, are reported rather than dated.
  - **A special method is a slot, not a table row**, so every dunder is left to the docs. `list.__getitem__` has been a slot since 0.9.1 and gained a table row in 2.4 so a list could be pickled, so a row is the age of the row.
  - **Only the method tables**, never the getset or member tables. Those only exist from 2.2, and before that an attribute was a `strcmp` inside `tp_getattr`, so reading them would date every attribute to the release that unified the type system.
  - **A row inside an `#if` proves nothing either way**, exactly as for a module member. That is what keeps `str.zfill` at the 2.2 its own docs give it.
- **Two markers the docs never meant were caught by comparing the tables against them**, which is the same check that found every mistake in the module-member extractor.
  `dict.values` is 1.0 and appeared to be dated 3.9, because that marker belongs to `d | other` two signatures further down and `annotations.py` cannot see an operator expression as a signature.
  `str.translate` is 1.6 and appeared to be dated 2.6, off a marker reading "New in version 2.6: Support for a `None` *table* argument".
  Both now resolve correctly because the tables outrank a marker, and a type method's evidence note says "the nearest marker" rather than "the docs date it", since for these two the docs do not.
- **An inventory entry for a member of a builtin type now bounds rather than dates.**
  `stdtypes` documents a whole family of types in one table and Sphinx grew per-name markup for those tables release by release, so the release that first indexes one of these is the age of the markup: `list.copy` arrived in 3.3 and was first indexed in 3.13, and `type.mro` predates Python 3 entirely and was first indexed in 3.12.
  The inventory used to date 213 of the 397 such names it indexes and now dates none of them, so 179 questions it answered confidently are refused instead.
  The 2.6-to-2.7 step looked safe and was not: it dated 20 `frozenset` methods to 2.7 where `frozenset` itself is 2.4, and among them `frozenset.add`, which no `frozenset` has ever had.
- **`annotations.py` reads `classmethod`, `static` and `abstractmethod` signatures**, which it previously skipped, so their markers no longer attach to whatever signature came before them.
  That fixed the false `datetime.date` and `bytearray.join` dates above, dated 35 names the markers were stranded on, `date.fromisoformat` among them, and dropped 15 they were wrongly attached to.
- `just propose` writes `methods` entries, groups one method across sibling types from a single marker, and stops producing ids like `object---set-name--`.
- `just propose` names a group the way the dataset already names one: `set.copy() and frozenset.copy()` for two, and `hex() on bytes, bytearray and memoryview` for a method spelled for three types.
- `just typemethods` reports what the tables date, `--tables` shows each release's raw tables, `--partial` shows what a family disagrees about, and `--compare` checks every name against what the rest of the pipeline says.


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
