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
  `fetch_docs.py` is the only script that touches the network.

## The research pipeline

Three independent methods date things, and they cross-check each other.
Where they disagree, the disagreement is the finding, and `dating.py` reports it rather than picking a winner.

- `inventory.py` diffs Sphinx `objects.inv` files from 2.6 to 3.14. Deterministic for anything added in 3.1 or later.
- `modindex.py` diffs the module lists and built-in function pages in the doc builds from 0.9.1 to 2.5, reading LaTeX for the three source-only releases and HTML for the rest. This is the only method that reaches the pre-Sphinx era.
- `annotations.py` greps the docs' own "Added in version" markers out of the 2.7 and 3.14 text builds. Covers what the other two cannot, and is the least trustworthy of the three.
- `grammar.py` diffs CPython's grammar at every release tag, from 0.9.1 to 3.14. This is the only source that settles *syntax*, and it is ground truth where a PEP header is intent: PEP 3129 says class decorators are 3.0 and the 2.6 grammar already has them. It found that `lambda` is 1.0, not "1.2 or earlier" as the docs suggested.

Two failure modes to keep in mind, both of which the dataset already has examples of:

- The docs can be wrong about their own history. The 2.7 docs date `bisect` to 2.1; the 1.5 module index contains it.
- The inventory and the module index date *documentation*, not shipping. `platform` shipped in 2.3 and was documented in 2.4, and `hashlib.sha3_256` shipped in 3.6 and was given its own inventory entry in 3.11.
- Prose is not a heading. Matching "standard module" anywhere in a doc collects words out of sentences like "standard modules that ...", and a stray comment in the 0.9.1 C source ("this should become a built-in module 'io'") once dated `io` to 1991. Anchor on the section heading.

Presence is strong evidence and absence is weak.
Seeing a symbol in a release proves it was there; not seeing it may only mean that release's docs had a gap.
This is why module members only ever get a floor from the archives: the 2.3 doc build paginates module pages, so it indexes 476 members where 2.2 indexes 1456, and diffing that would invent a thousand additions.

## Curation rules for the dataset

These matter more than the code.
Getting a version wrong is the worst bug this project can have, because the whole value proposition is that the answers are correct.

- **Cite the evidence.** Every entry carries a `[features.evidence]` table saying how its version was established, and `just verify-dataset` re-derives all of them. Never write a version number from memory: run `just whenadded <symbol>` and let the archived docs answer. An LLM is useful for proposing *which* features are worth having and useless as a source for *when* they arrived.
- **`added` is the oldest release it has been available in ever since, ignoring 3.0 and 3.1.** Not the oldest release that ever had it. Nobody shipped code on 3.0 or 3.1, so a gap there does not count: `argparse` shipped in 2.7 and again in 3.2 and is dated 2.7. A gap that reaches 3.2 is real, and takes the later date. When the dates differ, say so in the evidence.
- **Say "or earlier" when that is all the archives support.** A feature already present in the oldest archive that documents it cannot be dated, only bounded. Those entries set `or_earlier = true` and report as "1.2 or earlier".
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
