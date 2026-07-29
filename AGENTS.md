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

## Curation rules for the dataset

These matter more than the code.
Getting a version wrong is the worst bug this project can have, because the whole value proposition is that the answers are correct.

- **Cite the evidence.** A feature's version should be traceable to documentation, not to memory. See `PLAN.md` for the provenance work.
- **Leave out what's ambiguous.** `a | b` could be a 3.9 dict merge, a 3.10 union type, or bitwise-or on integers that has worked forever. The AST cannot distinguish them, so the feature is omitted rather than guessed at. A false positive is much worse than a missing entry, because a wrong minimum version is actively misleading while a missing one is merely incomplete.
- **Prefer unambiguous node matches.** `{**a}` (a `Dict` with a `None` key) is safe. A bare `Starred` node is not, because it means different things in different contexts.
- **The minimum version is a lower bound.** The dataset is incomplete by nature, so `minimum_version()` can only ever say "at least this new." Do not phrase it as a guarantee in docs or output.
- **Detection is syntactic, not semantic.** `sincewhen` sees a call to something named `math.isclose`, not the real function. Shadowed builtins are handled; shadowed module attributes are not.

## Testing

When adding a feature to the dataset, add a detection test for it, and add a negative test if the matcher could plausibly over-fire.
`tests/test_features.py` validates the dataset itself (unique ids, exactly one matcher each, known categories) and catches curation mistakes at test time.
