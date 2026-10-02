# Contributing to CodePrism

Thank you for your interest in contributing to CodePrism. This document covers everything you need to get from "I have an idea" to a merged pull request.

If you're new here, start with the [Code of Conduct](CODE_OF_CONDUCT.md). Then come back.

---

## Table of Contents

- [Ways to Contribute](#ways-to-contribute)
- [Before You Start](#before-you-start)
- [Quick Start](#quick-start)
- [Development Setup](#development-setup)
- [Project Structure](#project-structure)
- [Making Changes](#making-changes)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Review Process](#review-process)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)
- [Security Vulnerabilities](#security-vulnerabilities)
- [Release Process](#release-process)

---

## Ways to Contribute

You don't have to write code to contribute. Valuable contributions include:

| Type | Examples |
|---|---|
| **Bug reports** | Reproduce and document unexpected behavior with a minimal reproduction |
| **Feature requests** | Propose new CLI commands, MCP tools, language parsers, or detector patterns |
| **Code** | Bug fixes, new security detectors, new language parsers, performance improvements |
| **Documentation** | Fix typos, improve examples, add missing docstrings, translate docs |
| **Tests** | Add missing test cases, improve fixture coverage, add property-based tests |
| **Security rules** | Add patterns to `security/rules/` JSON files for new vulnerability classes |
| **Triage** | Label issues, reproduce bug reports, suggest duplicates |

---

## Before You Start

For anything beyond a typo fix, **open an issue first**. This lets maintainers confirm the direction before you invest time writing code. Mention:

- What you want to change and why
- Any design constraints or alternatives you considered
- Whether you plan to submit a PR yourself

For large changes (new parsers, MCP tools, architectural refactors) a brief design comment in the issue is strongly preferred before any code is written.

**Looking for something to work on?** Browse the [open issues](https://github.com/knight22-21/CodePrism/issues). Several are bugs with a runnable reproduction and a suggested fix, for example the symbol-id collision in [#34](https://github.com/knight22-21/CodePrism/issues/34) or import-aware call resolution for other languages in [#37](https://github.com/knight22-21/CodePrism/issues/37). Comment on the issue first so two people don't do the same work. Issues labelled [`good first issue`](https://github.com/knight22-21/CodePrism/labels/good%20first%20issue) are small and self-contained, each with a reproduction, the files to change and the tests to add.

---

## Quick Start

About two minutes. Python 3.12+ and Git are all you need.

```bash
git clone https://github.com/<your-username>/CodePrism.git   # your fork
cd CodePrism
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

python -m pytest tests/ -q                       # whole suite: ~700 tests, under a minute
ruff check codeprism/ tests/                     # lint (CI runs this)
ruff format --check codeprism/ tests/            # formatting (CI runs this)
```

Then:

1. Comment on the issue you want so nobody duplicates the work.
2. `git checkout -b fix/short-description`
3. Make the change **with a test**. While you work, run one file: `python -m pytest tests/test_cli.py -q`.
4. Run the three commands above, then open a pull request. The PR template lists the checklist.

The sections below cover the details: project layout, commit style, adding parsers and detectors.

---

## Development Setup

### Requirements

- Python 3.12+
- Git

### Clone and install

```bash
git clone https://github.com/knight22-21/CodePrism.git
cd CodePrism

# Create an isolated environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install in editable mode with all dev dependencies
pip install -e ".[dev]"

# Optional: install embeddings support
pip install -e ".[embeddings]"
```

### Verify the setup

```bash
python -m pytest tests/ -q
# All tests should pass before you make any changes.
```

### Run the linter and type checker

```bash
ruff check codeprism/ tests/            # linting (CI runs this)
ruff format --check codeprism/ tests/   # formatting (CI runs this)
mypy codeprism/                         # type checking (advisory, see below)
```

CI runs `ruff` and the test suite. `mypy` is configured in strict mode but is **not** run in CI:
the existing code still has outstanding errors, so it is not a merge requirement yet. Please
don't add new errors to the files you touch.

---

## Project Structure

```
codeprism/
├── core/           # GraphEngine, StorageManager, Pydantic models, config,
│                   #   languages.py (language -> extensions), gitignore.py, paths.py
├── parser/         # tree-sitter language parsers (one file per language) + registry
├── indexer/        # ProjectIndexer, IncrementalUpdater, call_resolver, file watcher
├── query/          # QueryEngine, context/impact/summary builders
├── security/       # SecurityScanner, SecurityGate, all detectors, CVE checker
│   ├── detectors/  # One file per detector category
│   └── rules/      # JSON rule definitions (bandit-style)
├── mcp/            # FastMCP server + session overlay
├── embeddings/     # Optional: sentence-transformers + ChromaDB wrappers
└── cli.py          # typer CLI entry point

tests/
├── fixtures/       # Sample projects and security-issue files for integration tests
└── test_*.py       # One test file per module

benchmarks/         # Token-reduction, latency and accuracy benchmarks (see docs/benchmark-results.md)
docs/               # architecture.md, changelog.md, benchmark-results.md
```

The key invariant: **each layer only imports downward**. `mcp/` imports `query/` and `security/`; `query/` imports `core/`; nothing in `core/` imports from higher layers.

---

## Making Changes

### Branching

Branch off `main` using the following naming convention:

```
fix/<short-description>       # bug fixes
feat/<short-description>      # new features
docs/<short-description>      # documentation only
refactor/<short-description>  # non-functional changes
test/<short-description>      # test-only changes
```

Examples: `fix/session-block-disk-write`, `feat/rust-parser`, `docs/mcp-setup-guide`

### Commit messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short summary in present tense>

[optional body — explain the why, not the what]

[optional footer — breaking changes, issue refs]
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `perf`, `chore`

Scopes (optional but encouraged): `parser`, `indexer`, `query`, `security`, `mcp`, `cli`, `core`

**Examples:**

```
feat(security): add SSRF pattern detector for requests.get calls

fix(parser): handle async generator functions in Python parser

docs: add Cursor MCP setup instructions to README

test(security): add edge cases for yaml.load without Loader

chore(deps): bump tree-sitter to 0.26
```

Keep the summary line under 72 characters. Do not end it with a period.

---

## Coding Standards

### Style

- Formatting and linting are enforced by **ruff** (`line-length = 100`, `target-version = py312`)
- Run `ruff format codeprism/` before committing — CI will reject unformatted code
- All public functions and classes must have a one-line docstring at minimum
- Type annotations are expected on all new function signatures (`mypy` runs in strict mode locally but is not yet enforced in CI)

### Comments

- Write comments to explain **why**, not **what** — the code explains what
- Avoid obvious comments (`# increment counter`)
- Document non-obvious invariants, workarounds for upstream bugs, and subtle constraints

### No new dependencies without discussion

Adding a runtime dependency requires a maintainer sign-off in the issue before the PR. Each new dependency must justify itself against the added install surface. Optional extras (like `embeddings`) are the preferred pattern for heavy optional features.

### Security detectors

When adding a new regex pattern to a detector:

1. Add a test fixture file under `tests/fixtures/sample_security_issues/` that demonstrates the vulnerability
2. Write both a **positive test** (pattern fires) and a **negative test** (clean code does not fire)
3. Include a `fix_suggestion` string that gives the developer a concrete remediation step
4. Set severity conservatively — prefer `WARN` over `BLOCK` unless the issue is unambiguously exploitable

### Language parsers

When adding a new parser:

1. Create `codeprism/parser/<language>_parser.py` extending `BaseParser`
2. Register the language and its extensions in `codeprism/core/languages.py` (the single source of
   truth used by the indexer, the watcher and the config defaults), and map the extensions to the
   parser in `codeprism/parser/registry.py`. `tests/test_languages.py` fails if a listed extension
   has no parser
3. Add the tree-sitter grammar package to the dependencies in `pyproject.toml`
4. Add a fixture directory under `tests/fixtures/sample_<language>_project/`
5. Write tests covering: function extraction, class extraction, import extraction, and edge (call/import) extraction
6. Handle parse errors gracefully — a broken file must never crash the indexer
7. Update the language tables in `README.md` and `INTEGRATIONS.md`, and add a line to `docs/changelog.md`

Calls in a new language are linked **by name** until you add import-aware resolution: record the
call style and receiver on `UnresolvedRef` and add rules for the language in
`codeprism/indexer/call_resolver.py` (see [#37](https://github.com/knight22-21/CodePrism/issues/37) and how Python does it).

### Changing what the index contains

If a change alters parser output or how rows are written, bump `INDEX_FORMAT_VERSION` in
`codeprism/core/storage.py`. Existing indexes are then rebuilt automatically on the next run
instead of silently keeping stale rows.

---

## Testing

### Running tests

```bash
# Full suite
python -m pytest tests/ -q

# Single file
python -m pytest tests/test_security_detectors.py -v

# With coverage
python -m pytest tests/ --cov=codeprism --cov-report=term-missing
```

The test suite runs on Python 3.12 and 3.13 in CI.

### Test conventions

- All test files are prefixed `test_` and mirror the module they test
- Use `pytest-asyncio` for async tests — the project is configured with `asyncio_mode = "auto"`
- Use `tmp_path` (pytest built-in) for any tests that touch the filesystem
- Never use `unittest.mock` to mock the database — hit a real in-memory SQLite instance
- Integration tests that index actual code use fixture projects in `tests/fixtures/`
- The indexer asks `git` which files to index, so a test that needs non-git behaviour should set
  `respect_gitignore=False` on the config, or set `GIT_CEILING_DIRECTORIES` so a repository above
  `tmp_path` isn't picked up

### What to test

Every PR that changes behavior must include tests that:

1. **Cover the happy path** — the thing works correctly
2. **Cover the failure path** — bad input / missing file / parse error is handled
3. **Cover the security gate** — if you change a detector, show it fires and show it doesn't false-positive on clean code

PRs that add code without tests will not be merged.

### Coverage

CI fails if coverage of `codeprism/` drops below **80%**. Check before submitting:

```bash
python -m pytest tests/ --cov=codeprism --cov-fail-under=80
```

New code should be covered by its own tests rather than relying on the existing margin.

### Benchmarks

If you change a parser or how references are resolved, measure the effect and put the before/after
numbers in the PR description:

```bash
python -m benchmarks.setup_repos                 # one-time: clones requests, flask, httpx
python -m benchmarks.run_symbol_accuracy         # symbol + within-file caller accuracy
python -m benchmarks.run_call_precision          # cross-file call precision/recall (Python)
```

Methodology and current numbers are in `docs/benchmark-results.md`.

---

## Submitting a Pull Request

1. **Sync with `main`** before opening a PR:
   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Run the full check suite locally:**
   ```bash
   ruff check codeprism/ tests/ && ruff format --check codeprism/ tests/
   python -m pytest tests/ -q
   ```
   All checks must pass before you open the PR (this is what CI runs).

3. **Open the PR against `main`** with:
   - A clear title following the commit message convention
   - A description that explains **what** changed and **why**
   - A link to the related issue (`Closes #123`)
   - A brief test plan — what did you test manually or in the test suite

4. **PR checklist** (include this in your description):

   ```markdown
   - [ ] Tests added or updated for all changed behavior
   - [ ] `ruff check` and `ruff format --check` pass
   - [ ] No new `mypy` errors in the files you changed (not yet enforced in CI)
   - [ ] All existing tests pass
   - [ ] Docstrings added/updated for public functions
   - [ ] `docs/changelog.md` updated (for user-facing changes)
   ```

5. **Keep PRs focused.** One logical change per PR. If you're fixing a bug and noticed an unrelated issue, open a separate PR for the second fix.

---

## Review Process

- A maintainer will review within **5 business days** for most PRs
- Reviewers will leave inline comments — please address each one with either a code change or a reply explaining why you disagree
- "Resolve conversation" once you've made the change — don't leave threads open
- Maintainers may request changes more than once; this is normal and not a rejection
- Once approved, a maintainer will merge using **squash and merge** to keep the history clean

### What reviewers look for

- Correctness — does the code do what the description says?
- Test coverage — are edge cases handled?
- Layering — does the code respect the `core → query/security → mcp` dependency direction?
- Security — does new code introduce any of the patterns CodePrism itself scans for?
- Performance — does a change to the indexer or graph query degrade on large codebases?

---

## Reporting Bugs

Use the GitHub issue tracker. A good bug report includes:

1. **CodePrism version** (`pip show codeprism-ai`)
2. **Python version** (`python --version`)
3. **Operating system**
4. **Minimal reproduction** — the smallest piece of code or project that triggers the bug
5. **Expected behavior** — what should happen
6. **Actual behavior** — what actually happens, including full error output and stack trace

If the bug involves incorrect security scanner results (false positive or missed detection), include:
- The exact source snippet that was scanned
- The detector output you got vs. what you expected

---

## Requesting Features

Open a GitHub issue with the label `enhancement`. Include:

1. **The problem you're trying to solve** — not just "I want X" but "I'm trying to do Y and currently have to Z"
2. **Your proposed solution** — how you envision it working
3. **Alternatives you considered** — other approaches you ruled out and why
4. **Impact** — who benefits, how often, how much

Feature requests for new **language parsers** should include a sample project of at least 3–5 files that exercises the language features you want to capture.

Feature requests for new **security detectors** should include:
- The vulnerability class (CWE number if available)
- At least one real-world example of the pattern in the wild
- A proposed severity (INFO / WARN / BLOCK) with justification

---

## Security Vulnerabilities

**Do not open a public GitHub issue for security vulnerabilities.**

Follow the [Security Policy](SECURITY.md): it explains how to report privately (by email to
**krishnatyagibest321@gmail.com**), what to include, how quickly you can expect a response, what is in
scope, and how we coordinate a fix, disclosure and credit.

---

## Release Process

Releases are managed by maintainers. The process is:

1. Bump the version in `pyproject.toml`
2. Add an entry to `docs/changelog.md` with all user-facing changes since the last release (note an
   index-format change if `INDEX_FORMAT_VERSION` was bumped)
3. Merge to `main` and wait for CI to pass
4. Tag the commit and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`
5. Create a GitHub Release from the tag with the changelog entry as the body. **Publishing the
   release** is what triggers the `Publish to PyPI` workflow; pushing a tag alone does not

Version numbers follow [Semantic Versioning](https://semver.org/):
- **PATCH** (`0.1.x`) — bug fixes, no API changes
- **MINOR** (`0.x.0`) — new features, backward-compatible
- **MAJOR** (`x.0.0`) — breaking changes to the public API or MCP tool signatures

---

## Questions?

- Open a [GitHub Discussion](https://github.com/knight22-21/CodePrism/discussions) for general questions
- Tag an issue `question` if you're unsure whether something is a bug or expected behavior
- For anything else: **krishnatyagibest321@gmail.com**

Thank you for making CodePrism better.
