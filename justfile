# Show available commands
_default:
    @printf 'Automation tasks:\n'
    @just --list --unsorted --list-heading '' --list-prefix '  - '

# Run the sincewhen command
run *args='':
    uv run sincewhen {{ args }}

# Run all checks (format, lint, typecheck, test with coverage)
#
# Coverage is part of `check` because CI enforces it and a green local
# run that CI then rejects is worse than a slower local run.
check: format lint typecheck test-cov

# Format code with ruff
format *files='':
    uv run ruff check --fix {{ files }}
    uv run ruff format {{ files }}

# Lint source code
lint *files='':
    uv run ruff check {{ files }}
    uv run ruff format --check {{ files }}

# Type check with ty
typecheck *files='':
    uv run ty check {{ files }}

# Run tests
test *args='':
    uv run pytest -v {{ args }}

# Download the documentation corpus the dataset is derived from
fetch-docs:
    uv run scripts/fetch_docs.py

# Build Python 0.9.1 through 3.14 from the cached tarballs (slow, needs a C compiler)
build-pythons *versions='':
    uv run scripts/interpreters.py --build {{ versions }}

# Ask the built interpreters what each release had, and record it
probe-pythons:
    uv run scripts/interpreters.py --probe

# Show what the built interpreters date
interpreters *args='':
    uv run scripts/interpreters.py --report {{ args }}

# Show where the built interpreters disagree with the dataset
interpreters-vs-dataset:
    uv run scripts/interpreters.py --compare

# Show what the builtin types' own method tables date (usage: just typemethods --compare)
typemethods *args='':
    uv run scripts/typemethods.py {{ args }}

# Re-derive every version claim in the dataset and compare
verify-dataset *args='':
    uv run scripts/release_dates.py --check
    uv run scripts/interpreters.py --check
    uv run scripts/verify_dataset.py {{ args }}

# Look up what the cached docs say about a symbol
whenadded *names='':
    uv run scripts/dating.py {{ names }}

# Draft dataset entries for stdlib symbols, with evidence
propose *names='':
    uv run scripts/propose.py {{ names }}

# Run tests with coverage
test-cov:
    uv run pytest --cov=sincewhen --cov=tests --cov-report=term-missing --cov-report=html

# Check the built wheel ships the feature dataset
check-package: build
    #!/usr/bin/env bash
    set -euo pipefail
    wheel="$(ls -t dist/*.whl | head -1)"
    if ! unzip -l "$wheel" | grep -q 'sincewhen/features.toml'; then
        echo "features.toml is missing from ${wheel}." >&2
        exit 1
    fi
    echo "features.toml is present in ${wheel}."

# Bump version (usage: just bump patch|minor|major)
bump value:
    uv version --bump {{ value }}

# Show the release notes for a version (usage: just changelog 0.2.0)
changelog version:
    uv run scripts/changelog.py {{ version }}

# Build the package
build:
    uv sync  # Force uv version error if applicable
    uv build --clear

# Publish to PyPI (normally done by the release workflow instead)
publish: build
    uv publish

# Tag the current version and push, which publishes to PyPI via GitHub Actions
release: check
    #!/usr/bin/env bash
    set -euo pipefail
    version="$(uv version --short)"
    branch="$(git branch --show-current)"
    if [ "$branch" != "main" ]; then
        echo "Releases happen from main, but HEAD is on $branch." >&2
        exit 1
    fi
    if [ -n "$(git status --porcelain)" ]; then
        echo "Working tree is dirty. Commit the version bump first." >&2
        exit 1
    fi
    # The release workflow builds its notes from this section, so a
    # missing one would ship a release that documents itself as nothing.
    uv run scripts/changelog.py "${version}" --check
    if git rev-parse "v${version}" >/dev/null 2>&1; then
        echo "Tag v${version} already exists. Run 'just bump' first." >&2
        exit 1
    fi
    git tag -a "v${version}" -m "Version ${version}"
    git push origin main "v${version}"
    echo "Pushed v${version}. Watch the release run:"
    echo "  https://github.com/treyhunner/sincewhen/actions"
