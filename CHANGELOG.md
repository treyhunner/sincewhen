# Changelog

Everything notable that changed in each release of `sincewhen`.
This project follows [semantic versioning](https://semver.org).

Dataset changes are listed apart from everything else, because they are the changes that can alter what `sincewhen` says about code that did not change.
A corrected version is not a cosmetic fix: it can move the minimum version a file reports.


## Unreleased

Nothing yet.


## 0.2.0 - 2026-07-29

### Dataset

- **441 features have a better answer than 0.1.0 gave**, because their versions now come from CPython's own source rather than from the oldest documentation that happened to describe them.
  Mostly this makes a vague answer exact rather than swapping one exact answer for another.
  Nothing became vaguer, and nothing moved to a *newer* version, so no file can report a higher minimum than it did before:

  | what changed | count | example |
  |---|---|---|
  | a bound became an exact version | 209 | `socket.error` was "1.0 or earlier", is 1.0 |
  | a bound became an exact, older version | 100 | `bisect` was "1.5 or earlier", is 1.0 |
  | a bound stayed a bound, but an older and truer one | 109 | `calendar` was "1.5 or earlier", is "0.9 or earlier" |
  | an exact version was wrong and is now an older exact version | 23 | `turtle` was 2.2, is 1.5 |
  | anything got vaguer | 0 | |

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
