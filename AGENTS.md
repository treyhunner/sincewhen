`sincewhen` is a Python library and CLI tool that reports which Python version introduced each feature used in a piece of code.
See `README.md` for usage, development setup, how to add a feature to the dataset, and the release process.

The question it answers is **"how long has this been in Python?"**, not "what version should I target?".
`minimum_version()` exists in the library because it is a reasonable thing to compute, not because it is the point.

## Commands

This project uses uv and just.
Run `just` to see every available task; no setup step is needed.
Run `just check` (format, lint, typecheck, and test) before finishing a change.

Type hints are enforced by `ty` in `just check` and in CI.
Do not add hints that cannot be checked, and do not silence `ty` where the honest fix is a narrower type.

## Architecture notes

Things the code cannot tell you:

- `features.toml` is the dataset, and the real substance of this project.
  Everything else is machinery for reading and matching it.
- Parsing uses the standard library's `ast` rather than `tree-sitter`, deliberately, to keep the package dependency-free and easy to run under WASM in a browser.
  This is why Python 3.14 is required (the parser only understands syntax the running interpreter understands) and why each new Python feature release needs a `sincewhen` release.
- `features.py` reads the dataset with `importlib.resources`, not `__file__`, so the package works from a zip.
  Keep it that way.
- `scripts/` is the research pipeline that produces the dataset, and it ships with the repo rather than with the package.
  It is stdlib-only and reads from a gitignored `.cache/` whose contents are pinned by SHA-256 in `scripts/sources.sha256`.
  `fetch_docs.py` is the only script that touches the network, and the cache it builds is about 500 MB.
  A release can have both a source tarball and a doc build in there, so `source_root()` and `html_root()` are separate trees.
- `interpreters.py` is the one script that needs more than the cache: a C compiler, and about ten minutes to build fourteen interpreters into `.cache/pythons/`.
  Its output is committed as `scripts/interpreters.json`, so nothing else in the pipeline needs either.

## The research pipeline

Seven independent methods date things, and they cross-check each other.
Where they disagree, the disagreement is the finding, and `dating.py` reports it rather than picking a winner.

- `inventory.py` diffs Sphinx `objects.inv` files from 2.6 to 3.14. Deterministic for anything added in 3.1 or later, with one exception: the members of the builtin types, where it can only ever bound. See below.
- `modindex.py` diffs the module lists and built-in function pages in the doc builds from 0.9.1 to 2.5, reading LaTeX for the three source-only releases and HTML for the rest. This is the only method that reaches the pre-Sphinx era.
- `typemethods.py` diffs the method tables of the builtin types across the same tarballs, which is `source.py`'s argument one level down and the only thing that reaches these names: the docs index 397 members of the builtin types and date 58, because a method older than the "New in version" convention never got a marker. It found that `dict` had `keys` and `has_key` and nothing else in 0.9.1, that `str.split` and 28 more string methods are 1.6, that `dict.setdefault` is 2.0 and `type.mro` is 2.2. Its claim is about instances rather than about the type: see below.
- `source.py` diffs what CPython's own tarballs contain across every release from 0.9.1 to 2.5: the `builtin_methods[]` table in `bltinmodule.c`, the `.py` files in the library directory, and the members of both kinds of module. It outranks every other method for anything it can account for. It found that `map` is 1.0 and `bisect` is 1.0 where the archives could only say "1.2 or earlier" and "1.5 or earlier", that `globals` and `locals` arrived in 1.3, and that `calendar.day_abbr` has been there since 0.9.1 and was merely written down in 2.5. C extension *modules* are deliberately excluded: `Modules/Setup` decides which get compiled, so the tarball cannot say what a release could import.
- `annotations.py` greps the docs' own "Added in version" markers out of the 2.7 and 3.14 text builds. Covers what the diffs cannot, and is the least trustworthy of them: a marker belongs to whatever signature the extractor last saw, which is not always the one it was written under.
- `grammar.py` diffs CPython's grammar at every release tag, from 0.9.1 to 3.14. This is the only source that settles *syntax*, and it is ground truth where a PEP header is intent: PEP 3129 says class decorators are 3.0 and the 2.6 grammar already has them. It found that `lambda` is 1.0, not "1.2 or earlier" as the docs suggested.
- `interpreters.py` builds all fourteen releases from 0.9.1 to 2.5 out of the tarballs already in the corpus and asks each one whether a name resolves. Every other method reads a description of Python; this one reads Python. It is the only method that can speak for a C extension module, and the only one that sees through a star-import, an `#ifdef` or a name bound at runtime. It found that `operator` is 1.4, closing the whole cluster of members the archives could only call "1.5 or earlier". Its claim is narrower than the others': see below.

Two failure modes to keep in mind, both of which the dataset already has examples of:

- The docs can be wrong about their own history. The 2.7 docs date `bisect` to 2.1; the 1.5 module index contains it.
- A doc-derived floor reports the age of the archive, not the age of the feature. Every builtin used to bottom out at "1.2 or earlier" because 1.2 is the oldest HTML build with a built-in functions page, and reading the interpreter's source dated 16 of the 31 outright.
- A source-derived floor can do the same at the *newest* end. Every member the docs date to 2.5 would report as "2.5 or earlier" purely because 2.5 is where the tarballs stop, which is why a floor never outranks an annotation of the same version.
- The inventory and the module index date *documentation*, not shipping. `platform` shipped in 2.3 and was documented in 2.4, and `hashlib.sha3_256` shipped in 3.6 and was given its own inventory entry in 3.11.
- A member of a builtin type is the worst case of that, and gets its own rule: along the 3.x line the inventory bounds it and never dates it. `stdtypes` describes a whole family of types in one table and Sphinx grew per-name markup for those tables release by release, so the release that first indexes one is the age of the markup. `list.copy` arrived in 3.3 and was first indexed in 3.13, `range.start` in 3.3 and first indexed in 3.5, `bytearray.capitalize` shipped with `bytearray` in 2.6 and was first indexed in 3.4, and `type.mro` predates Python 3 entirely and was first indexed in 3.12. What dates these is the docs' own markers, and for the ones older than the marker convention, the type's own method table: `type.mro` is 2.2. The 2.6-to-2.7 step is exempt, because it is one release of the same era's docs and every type member those two inventories disagree about is a real 2.7 addition.
- A marker attaches to the signature above it, so a signature the extractor cannot see steals one. `classmethod date.fromisoformat(...)` and `static bytes.maketrans(...)` did not match the signature pattern, so their markers landed on whatever came before: `datetime.date` read as 3.7 and `bytearray.join` as 3.1. Both were wrong and both looked like evidence.
- Prose is not a heading. Matching "standard module" anywhere in a doc collects words out of sentences like "standard modules that ...", and a stray comment in the 0.9.1 C source ("this should become a built-in module 'io'") once dated `io` to 1991. Anchor on the section heading.

Presence is strong evidence and absence is weak.
Seeing a symbol in a release proves it was there; not seeing it may only mean that release's docs had a gap.
This is why module members only ever get a floor from the archives: the 2.3 doc build paginates module pages, so it indexes 476 members where 2.2 indexes 1456, and diffing that would invent a thousand additions.

`source.py` is the one exception, and only because of what it reads.
A method table is the list a module registers its functions from rather than a description of one, so a name missing from it is a name that release did not have.
That is why it wins against the docs in both directions, where the archives only win when they show a feature is *older* than the docs claim.
The exception is narrow on purpose: it holds for what a module's own implementation accounts for, it says nothing about names bound into a dict some other way, and a name that is also a module belongs to the module.
`repr` is a builtin from 1.0 and a module from 1.5, and letting the table answer for the module dated it five releases early.

The same argument extends to `Lib/*.py` and stops there.
A `.py` file in the library directory is importable in every build of that release, so its absence means something.
A C extension's availability is a build-time choice: `curses`, `syslog` and `termios` all ship in the 1.1 tarball with their `Modules/Setup` lines commented out, and `select` is documented in 1.0 and commented out there too.
Neither reading the tarball nor filtering on `Setup` gets that right, so C extension *modules* are left to the archives.

### What the source can and cannot settle about a member

The exhaustive-list argument is decided per module, not per language, and getting the tier wrong produces a wrong version number.

- **A C module's namespace is written down in full.** Every name it binds is a row in the method table its registration call names, or a string literal in a call that inserts it. So absence is proof, and hard dates are sound.
- **A Python module's need not be.** `os.py` is little more than `from posix import *`, so `os.getcwd` is nowhere in it. A module that star-imports is presence-only: good for tightening a floor, never for dating from absence.
- **Presence is read strictly and absence generously.** A member counts as present only where the source binds it outright, and absent only where no reading of the source finds the name at all. Anything in between is a floor. A row inside an `#if 0` is the case that motivates it: 0.9.1 carries `{"fmod", math_fmod}` behind one, so `math.fmod` is neither provably there nor provably missing, and reports as "1.0 or earlier".
- **A C module's dict can be written to from outside its own file.** `sys.ps1` is set in `pythonmain.c`, `sys.last_traceback` in `traceback.c`, `sys.exc_type` in `ceval.c`. The absence check reads the whole tree for that reason, which costs yield and not correctness.
- **A member cannot predate its module.** `signalmodule.c` is in the 1.1 tarball and `signal` is dated 1.2, because of the `Modules/Setup` problem above. Where the two disagree the module is the binding constraint and the source stays quiet.
- **A source floor is not an absence claim**, only a limit on what could be read, so it never outranks a doc that shows the name earlier. `gc.collect` is in a table this cannot follow until 2.3 and the 2.0 docs list it; `random.randrange` reaches `random` by a re-export from `whrandom` until 2.1.
- **A source date newer than an archive is a real disagreement.** Both sides claim proof, so `dating.py` refuses to answer and `verify-dataset` asks for manual evidence rather than picking one.
- **A dated module closes a member's bound.** A member cannot predate its module, so a member bounded at exactly the release its module arrived in is not bounded at all: `weakref` is 2.1, so `weakref.ref` is 2.1 and not "2.1 or earlier". This only follows when the module is dated; a bounded module passes its bound along, which is why `operator.add` stays "1.5 or earlier". Do not generalise it to "a member is as old as its module", which is wrong 79% of the time against the members this dataset has actually dated.

### What a type's method table can and cannot settle

A type's method table is the list the type registers its methods from, so it is exhaustive in the way `builtin_methods[]` is and absence is proof.
Four things had to be decided before any of that can be believed, and each one produces a wrong version number if it is guessed at.

- **A type is a family, and 2.x `str` is not 3.x `str`.** `stringobject.c` is the bytes-ish string, `unicodeobject.c` is what became `str`, and their tables disagree: `encode` is in the unicode table from 1.6 and in the string table from 2.0. So a member is present only where every type in the family binds it, and absent as soon as one of them provably lacks it, which makes `str.encode` 2.0 and agrees with the marker the docs already carry. A member one of the family never has, like `isdecimal`, is reported by `--partial` rather than dated: what makes that a string method is 3.0 renaming unicode to `str`, which this method cannot see.
- **The claim is about instances, not about the type.** `str` was a builtin function and not a class until 2.2, so `"x".encode()` is 2.0 and `str.encode` as an unbound attribute is 2.2. This is why the head of a dotted name is deliberately not consulted here: `dict` the builtin is 2.2 and the `dict` type is in 0.9.1, so using the head as a floor would date `dict.keys` to 2.2 and using it as a ceiling would throw the 0.9.1 evidence away. `_date_the_module` skips type members for that reason.
- **A special method is a slot, not a table row**, so `__lt__` and `__index__` stay with the docs. A dunder can be both, which is worse: `list.__getitem__` has been a slot since 0.9.1 and gained a table row in 2.4 so a list could be pickled, so the row is the age of the row. Every dunder is left out, which costs a few table-only ones like `type.__subclasses__` and buys never dating a slot by its row.
- **Only the method tables, never the getset or member tables.** Those exist from 2.2, and before then an attribute was a `strcmp` inside `tp_getattr`: 1.5 answers `complex.real` that way with no table at all. Reading them would date every attribute to the release that unified the type system, and `float.real` and `int.numerator` are 2.6 and past this corpus anyway.

Four modern types are deliberately outside `LINEAGE`, because no release in this corpus has instances anyone would call by their name.
`bytes` and `bytearray` are 2.6, and the 2.x string type became `bytes` by being renamed, so mapping `bytes` onto it would date `bytes.capitalize` to 1.6, five releases before anything could be spelled `b"..."`.
`range` is 2.x `xrange`, while 2.x `range` returns a list, so `range(3).index` in this era is `list.index`.
`memoryview` is 2.7 and 2.x `buffer` is a different interface.
Those four are what the docs' markers and their types' own dates have to answer for, and `type_is_covered` is what keeps the omission from being silent.

The rest of the era's churn is not load bearing.
`struct methodlist` becomes `PyMethodDef`, which does not matter because the table is found by the identifier the type points at.
Resolution moves from a `tp_getattr` function calling `findmethod()` to a `tp_methods` slot in 2.2, so both are read.
What ties a table to a type is the `tp_name` string in the type structure, which is the only place the Python-visible name is written down, and it moves too: `dict` is `Mappingtype` spelled `"dictionary"` until 2.2, and `long` is `"long int"`.

Presence is strict and absence generous, exactly as for a module member.
`str.zfill` is the case that earns it: the 1.6 table carries `{"zfill", ...}` inside an `#if 0` and so does 2.2's, because the method really arrived in 2.2.2.
So the source floors it at "2.3 or earlier" and the docs' own 2.2.2 marker outranks the floor, which is the rule that already exists for module members.

`--compare` is the check worth keeping, because comparing a source date against what the docs say for the same name is what caught every mistake the module-member extractor made.
Nine of these agree with a marker exactly, which is the cross-validation, and three disagree.
Two of the three are the stolen-marker failure again: the nearest marker to `dict.values` is the 3.9 one under `d | other`, which is not a signature `annotations.py` can see, and the nearest one to `str.translate` says "New in version 2.6: Support for a `None` *table* argument", which dates an argument.
Neither is a claim about when the method arrived, so the evidence note for a type method says "the nearest marker" rather than "the docs date it".
The third is `str.decode`, present in the string table from 2.2 and the unicode table from 2.4, which is the family rule working and a name Python 3 removed anyway.

### What a built interpreter can and cannot settle

The other five methods read a record of Python and inherit whatever the record left out.
This one runs Python and inherits whatever the build decided.
That is a better trade for everything still bounded, and a different one, so it answers a slightly different question and has to be read as answering it.

- **The claim is "a default build of that release, on a modern Unix".** Not "the release shipped it", which is what the tarball says, and not "the docs wrote it down", which is what the archives say. `Modules/Setup.in` exactly as the release shipped it, with nothing enabled or disabled by hand.
- **Absence is proof here, and its failure mode is the build rather than the record.** The interpreter is the thing being asked, so a name it cannot resolve is a name that build did not have. What it cannot tell you is whether the build is representative: an extension needing a third-party library is absent exactly when that library is absent from the machine that built it. So every absence is cross-checked against whether the release's own tree carries the module's C source, and a module whose source ships in a release that cannot import it is a question for a human, never a date.
- **A platform-guarded name gets a platform answer.** `errno.EACCES` sits behind an `#ifdef`, so what a build settles is "available on Linux", and the dataset claims portable availability. That is why `errno`'s members are a schema question rather than a research one, and why they stay out until the schema can say "where the platform provides it".
- **A release's own `Setup` comments are configuration, not modification.** 1.1 through 1.4 ship `crypt cryptmodule.c # -lcrypt  # crypt(3); needs -lcrypt on some systems`, and this is one of those systems, so enabling it is following the release's own instructions.
- **Only two files are patched, and both are name collisions with a later toolchain rather than behaviour changes.** `getline` was Python's own function until glibc took the name in 2008, and `crypt` left libc. Dustin Ingram's `vintage-python` images, derived independently, carry the same two fixes, which is a useful check that this is the minimum rather than a preference. Everything else is compiler flags. Anything added to that list needs a note explaining why it is not tampering with the evidence.
- **The pre-1.5 releases are built for i386, because 64-bit made them lie.** They were written when `int`, `long` and a pointer were all 32 bits, and 1.0 and 1.1 pass `va_list *` around in `modsupport.c`, which the x86-64 ABI does not permit. Built 64-bit, `chr()` segfaults; `string.py` calls `chr()` at import time, so `import string` takes the interpreter down and every module reports absent. 1.2 through 1.4 survive a 64-bit health check but share that era's argument-parsing code, so they are built 32-bit too rather than trusted to luck.
- **A build has to prove it works before it is believed, and "it imports something" is not proof.** The health battery checks *values*: `chr(65)` really is `'A'`, `math.sqrt(4.0)` really is `2.0`. Two drafts of that check were too weak and two were too strong. `import string` alone passed a 1.1 build that segfaulted on everything else. `int('42')` fails legitimately before 1.5, and `os.getcwd` fails on 0.9.1 because 0.9.1 has no `os` module at all, only `posix`.
- **The table is the artifact, not the builds.** Building fourteen interpreters needs Docker and about ten minutes, and the rest of the pipeline is offline and quick. So the build is an occasional manual step, `scripts/interpreters.json` records what it found along with the image and the recipe, and `verify-dataset` and CI read the table and stay exactly as reproducible as they were. `interpreters.py --check` is the part that runs every time: it fails if the dataset and the table disagree, so drift shows up without anyone needing a compiler.
- **It outranks every method that reads a description of Python, and ties with none.** Availability is what it measures and what the dataset claims; the others infer it. Against `source.py` it is a real disagreement rather than a ranking, because both claim proof about different things: what the text binds, and what the interpreter bound. `dating.py` refuses to answer, exactly as it does for source-against-archive.
- **A re-add still belongs to the 3.x line.** `types.NoneType` resolves from 1.1 to 2.5, and its answer is still 3.10, because the rule is the oldest release it has been available in *ever since*. The existing `readded` guard is what keeps the old era from winning those, and it has to keep doing so.
- **It reads `x.y.0`, so it cannot see a micro release, and a date *newer* than the docs is therefore never believed on its own.** The corpus builds each feature release rather than the last micro of it, so an absence is an absence in 2.2.0. `re.finditer` is the case: `Lib/sre.py` defines it in 2.2.0 behind a `sys.hexversion` guard that passes, `sre.__all__` omits the name, and `re.py` is `from sre import *`, so `re.finditer` does not exist in 2.2.0 or 2.2.1. 2.2.2 added `__all__.append("finditer")`. The docs saying "New in version 2.2" are right about the release, and this method saying 2.3 is right about 2.2.0. So `dating.py` returns `interpreter-contradicts-docs` and refuses, and the entry carries `manual` evidence.

  The direction matters and only one of them is affected. An interpreter date *older* than the docs is believed, because presence proves presence and no micro can undo it. An interpreter date *newer* than the docs is exactly where a micro release could have fixed something, so it needs a human.

  Building the last micro instead would trade this error for its mirror image, and the worse one: a name that arrived in 2.1.3 would be dated 2.1, overstating how long it has been around, which is the direction this project cares most about not getting wrong. The corpus already makes that exception twice for documented reasons, `1.0.1` because 1.0 only ever shipped as 1.0.1, and `1.5.2` to match the doc archive, and both are noted in `sources.py`.

Four ways a build can quietly answer "absent" for a reason that has nothing to do with the release, all of which happened:

- **The stdlib was never installed.** 1.0 through 1.3 install the library under a separate `libinstall` target, so `make install` alone leaves a working interpreter that can find nothing. It dated `bisect` to 1.4 when the tarball proves 1.0.
- **`configure` was helped, and broke.** Presetting `MACHDEP` to avoid the `Lib/plat-linux6` a 6.x kernel asks for looks like a fix. It is a trap: `configure` computes `ac_sys_system` inside `if test -z "$MACHDEP"`, so the `Linux*)` case that sets `LDSHARED='gcc -shared'` never runs, every extension links against a bare `ld` and fails, and `math` and `time` vanish. Supply the platform directory the release shipped instead and leave `configure` alone.
- **A 2005 `setup.py` cannot find a 2024 library.** Multiarch arrived in 2009. 2.5 does not skip a library it cannot find: having found `sqlite3.h` it calls `os.path.dirname(None)`, raises, and fails `make sharedmods`, losing *every* shared extension. `LDFLAGS` is the supported way to tell it.
- **Half a library is worse than none.** `libgdbm-dev` without `libgdbm-compat-dev` leaves `configure` believing dbm is available while `ndbm.h` is missing, and 2.2 fails to build rather than skipping the module.

The corpus pairs a source tarball and a doc build per feature release, and they have to describe the same build.
`SOURCE_BUILDS` takes the x.y tarball exactly, except where the rest of the corpus means a micro: pairing the 1.5 source with the 1.5.2 docs manufactured fifty false 1.6 additions, because 1.5.1 and 1.5.2 predate the convention that a micro release adds nothing.

## Curation rules for the dataset

These matter more than the code.
Getting a version wrong is the worst bug this project can have, because the whole value proposition is that the answers are correct.

- **Cite the evidence.** Every entry carries a `[features.evidence]` table saying how its version was established, and `just verify-dataset` re-derives all of them. Never write a version number from memory: run `just whenadded <symbol>` and let the archived docs answer. An LLM is useful for proposing *which* features are worth having and useless as a source for *when* they arrived.
- **`added` is the oldest release it has been available in ever since, ignoring 3.0 and 3.1.** Not the oldest release that ever had it. Nobody shipped code on 3.0 or 3.1, so a gap there does not count: `argparse` shipped in 2.7 and again in 3.2 and is dated 2.7. A gap that reaches 3.2 is real, and takes the later date. When the dates differ, say so in the evidence.
- **Say "or earlier" when that is all the sources support.** A feature already present in the oldest source that records it cannot be dated, only bounded. Those entries set `or_earlier = true` and report as "1.5 or earlier" for a module member no source can account for. `verify-dataset` rechecks the flag as well as the version, because "1.5" and "1.5 or earlier" are different claims. Before adding one, check whether a method that reaches further back can date it outright.
- **The first public release is a date, not a bound.** A bound says which releases are still candidates, and at 0.9 there are none: nothing older than Python 0.9.1 was ever released, so "0.9 or earlier" leaves open a range that does not exist. Those entries carry `added = "0.9"` with no `or_earlier`, report as "0.9 (first public release)", and keep an evidence note saying the name is at least that old and may predate the public record. `dating.py` applies this to every method, and `verify_dataset.check_grammar` repeats it because the grammar is checked without going through `dating.py`.
- **A keyword is not a symbol.** Every Python keyword is also a `std:label` in the inventories, so asking the doc-derived methods about `in` answers about the reference manual's anchor for it: 3.2, for an operator that is in the 0.9.1 grammar. `dating.py` refuses a bare keyword, `verify-dataset` demands grammar evidence for one, and `grammar.py` is what answers. Soft keywords are deliberately not refused, because `type` is a builtin and `match` and `case` are ordinary names.
- **Leave out what's ambiguous.** `a | b` could be a 3.9 dict merge, a 3.10 union type, or bitwise-or on integers that has worked forever. The AST cannot distinguish them, so the feature is omitted rather than guessed at. A false positive is much worse than a missing entry, because a wrong minimum version is actively misleading while a missing one is merely incomplete.
- **Prefer unambiguous node matches.** `{**a}` (a `Dict` with a `None` key) is safe. A bare `Starred` node is not, because it means different things in different contexts.
- **The minimum version is a lower bound.** The dataset is incomplete by nature, so `minimum_version()` can only ever say "at least this new." Do not phrase it as a guarantee in docs or output.
- **Detection is syntactic, not semantic.** `sincewhen` sees a call to something named `math.isclose`, not the real function. Shadowed builtins are handled; shadowed module attributes are not.
- **A method of a builtin type is searchable first and detectable second.** Search can answer "how long has `str.removeprefix` been in Python" exactly, and detection cannot: `x.removeprefix(...)` is a `str`, a `PurePath`, or a class written this morning, and the AST cannot tell. So the `methods` matcher fires only where the receiver's type is certain, meaning a literal or the type's own unshadowed name, and the entry stays searchable everywhere else. That is what the question this tool asks needs, and it is the only subset a syntactic tool can claim.
- **A method Python 3 removed has no entry**, for the same reason the Python 2 builtins have none: `added` cannot say "and then it was taken away". `str.decode`, `dict.iteritems` and `dict.viewkeys` are all dated by the 2.7 docs and all stay out, and `test_every_dated_method_is_still_there` enforces it by asking the running interpreter. `typemethods.py` dates several of these because the tables carry them, so a name it dates is a candidate for an entry rather than an entry.
- **A method entry from before 2.6 is a claim about instances.** `"x".split()` is 1.6 and `str.split` written as an unbound call needs 2.2, because `str` was a builtin function until then. Detection understates that one spelling, which is the right direction: the alternative claims 2.2 for a method that has worked on strings since 1.6. The same reading is why a type member never inherits a floor or a ceiling from the name in front of the dot.
- **Record it in the changelog.** A new entry, or a corrected version on an existing one, gets a line under `Unreleased` in `CHANGELOG.md`. Dataset changes get their own heading there, apart from tool changes, because they are the ones that alter what `sincewhen` reports about code that did not change. A correction says what the version was, what it is now, and which source settled it.

## Testing

When adding a feature to the dataset, add a detection test for it, and add a negative test if the matcher could plausibly over-fire.
`tests/test_features.py` validates the dataset itself (unique ids, exactly one matcher each, known categories, evidence that carries what its method requires and agrees with the version claimed) and catches curation mistakes at test time.

Those tests read the bundled dataset and need no network.
`just verify-dataset` is the one that goes back to the sources, and it needs the cache from `just fetch-docs`.
