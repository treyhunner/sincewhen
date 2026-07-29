`sincewhen` is a Python library and CLI tool that reports which Python version introduced each feature used in a piece of code.
See `README.md` for usage, development setup, how to add a feature to the dataset, and the release process.

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

## The research pipeline

Five independent methods date things, and they cross-check each other.
Where they disagree, the disagreement is the finding, and `dating.py` reports it rather than picking a winner.

- `inventory.py` diffs Sphinx `objects.inv` files from 2.6 to 3.14. Deterministic for anything added in 3.1 or later.
- `modindex.py` diffs the module lists and built-in function pages in the doc builds from 0.9.1 to 2.5, reading LaTeX for the three source-only releases and HTML for the rest. This is the only method that reaches the pre-Sphinx era.
- `source.py` diffs what CPython's own tarballs contain across every release from 0.9.1 to 2.5: the `builtin_methods[]` table in `bltinmodule.c`, the `.py` files in the library directory, and the members of both kinds of module. It outranks every other method for anything it can account for. It found that `map` is 1.0 and `bisect` is 1.0 where the archives could only say "1.2 or earlier" and "1.5 or earlier", that `globals` and `locals` arrived in 1.3, and that `calendar.day_abbr` has been there since 0.9.1 and was merely written down in 2.5. C extension *modules* are deliberately excluded: `Modules/Setup` decides which get compiled, so the tarball cannot say what a release could import.
- `annotations.py` greps the docs' own "Added in version" markers out of the 2.7 and 3.14 text builds. Covers what the other two cannot, and is the least trustworthy of the three.
- `grammar.py` diffs CPython's grammar at every release tag, from 0.9.1 to 3.14. This is the only source that settles *syntax*, and it is ground truth where a PEP header is intent: PEP 3129 says class decorators are 3.0 and the 2.6 grammar already has them. It found that `lambda` is 1.0, not "1.2 or earlier" as the docs suggested.

Two failure modes to keep in mind, both of which the dataset already has examples of:

- The docs can be wrong about their own history. The 2.7 docs date `bisect` to 2.1; the 1.5 module index contains it.
- A doc-derived floor reports the age of the archive, not the age of the feature. Every builtin used to bottom out at "1.2 or earlier" because 1.2 is the oldest HTML build with a built-in functions page, and reading the interpreter's source dated 16 of the 31 outright.
- A source-derived floor can do the same at the *newest* end. Every member the docs date to 2.5 would report as "2.5 or earlier" purely because 2.5 is where the tarballs stop, which is why a floor never outranks an annotation of the same version.
- The inventory and the module index date *documentation*, not shipping. `platform` shipped in 2.3 and was documented in 2.4, and `hashlib.sha3_256` shipped in 3.6 and was given its own inventory entry in 3.11.
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

The corpus pairs a source tarball and a doc build per feature release, and they have to describe the same build.
`SOURCE_BUILDS` takes the x.y tarball exactly, except where the rest of the corpus means a micro: pairing the 1.5 source with the 1.5.2 docs manufactured fifty false 1.6 additions, because 1.5.1 and 1.5.2 predate the convention that a micro release adds nothing.

## Curation rules for the dataset

These matter more than the code.
Getting a version wrong is the worst bug this project can have, because the whole value proposition is that the answers are correct.

- **Cite the evidence.** Every entry carries a `[features.evidence]` table saying how its version was established, and `just verify-dataset` re-derives all of them. Never write a version number from memory: run `just whenadded <symbol>` and let the archived docs answer. An LLM is useful for proposing *which* features are worth having and useless as a source for *when* they arrived.
- **`added` is the oldest release it has been available in ever since, ignoring 3.0 and 3.1.** Not the oldest release that ever had it. Nobody shipped code on 3.0 or 3.1, so a gap there does not count: `argparse` shipped in 2.7 and again in 3.2 and is dated 2.7. A gap that reaches 3.2 is real, and takes the later date. When the dates differ, say so in the evidence.
- **Say "or earlier" when that is all the sources support.** A feature already present in the oldest source that records it cannot be dated, only bounded. Those entries set `or_earlier = true` and report as "0.9 or earlier" for a builtin in the first public release, or "1.5 or earlier" for a module member no source can account for. `verify-dataset` rechecks the flag as well as the version, because "1.5" and "1.5 or earlier" are different claims. Before adding one, check whether a method that reaches further back can date it outright.
- **Leave out what's ambiguous.** `a | b` could be a 3.9 dict merge, a 3.10 union type, or bitwise-or on integers that has worked forever. The AST cannot distinguish them, so the feature is omitted rather than guessed at. A false positive is much worse than a missing entry, because a wrong minimum version is actively misleading while a missing one is merely incomplete.
- **Prefer unambiguous node matches.** `{**a}` (a `Dict` with a `None` key) is safe. A bare `Starred` node is not, because it means different things in different contexts.
- **The minimum version is a lower bound.** The dataset is incomplete by nature, so `minimum_version()` can only ever say "at least this new." Do not phrase it as a guarantee in docs or output.
- **Detection is syntactic, not semantic.** `sincewhen` sees a call to something named `math.isclose`, not the real function. Shadowed builtins are handled; shadowed module attributes are not.
- **Record it in the changelog.** A new entry, or a corrected version on an existing one, gets a line under `Unreleased` in `CHANGELOG.md`. Dataset changes get their own heading there, apart from tool changes, because they are the ones that alter what `sincewhen` reports about code that did not change. A correction says what the version was, what it is now, and which source settled it.

## Testing

When adding a feature to the dataset, add a detection test for it, and add a negative test if the matcher could plausibly over-fire.
`tests/test_features.py` validates the dataset itself (unique ids, exactly one matcher each, known categories, evidence that carries what its method requires and agrees with the version claimed) and catches curation mistakes at test time.

Those tests read the bundled dataset and need no network.
`just verify-dataset` is the one that goes back to the sources, and it needs the cache from `just fetch-docs`.
