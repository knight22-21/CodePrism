# Contributing to CodePrism

Thank you for your interest in contributing to CodePrism. This document covers everything you need to get from "I have an idea" to a merged pull request.

If you're new here, start with the [Code of Conduct](CODE_OF_CONDUCT.md). Then come back.

---

## Table of Contents

- [Ways to Contribute](#ways-to-contribute)
- [Before You Start](#before-you-start)
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
ruff check codeprism/         # linting
ruff format --check codeprism/  # formatting
mypy codeprism/                 # type checking
```

---

## Project Structure

```
codeprism/
├── core/           # GraphEngine, StorageManager, Pydantic models, config
├── parser/         # tree-sitter language parsers (one file per language)
├── indexer/        # ProjectIndexer, IncrementalUpdater, file watcher
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
- Type annotations are required on all function signatures (enforced by mypy in strict mode)

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
2. Add the file extension mapping to `codeprism/parser/registry.py`
3. Add a fixture directory under `tests/fixtures/sample_<language>_project/`
4. Write tests covering: function extraction, class extraction, import extraction, and edge (call/import) extraction
5. Handle parse errors gracefully — a broken file must never crash the indexer

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

### Test conventions

- All test files are prefixed `test_` and mirror the module they test
- Use `pytest-asyncio` for async tests — the project is configured with `asyncio_mode = "auto"`
- Use `tmp_path` (pytest built-in) for any tests that touch the filesystem
- Never use `unittest.mock` to mock the database — hit a real in-memory SQLite instance
- Integration tests that index actual code use fixture projects in `tests/fixtures/`

### What to test

Every PR that changes behavior must include tests that:

1. **Cover the happy path** — the thing works correctly
2. **Cover the failure path** — bad input / missing file / parse error is handled
3. **Cover the security gate** — if you change a detector, show it fires and show it doesn't false-positive on clean code

PRs that add code without tests will not be merged.

### Coverage target

We aim for **≥ 85% line coverage** on `codeprism/`. Check before submitting:

```bash
python -m pytest tests/ --cov=codeprism --cov-fail-under=85
```

---

## Submitting a Pull Request

1. **Sync with `main`** before opening a PR:
   ```bash
   git fetch origin
   git rebase origin/main
   ```

2. **Run the full check suite locally:**
   ```bash
   ruff check codeprism/ && ruff format --check codeprism/
   mypy codeprism/
   python -m pytest tests/ -q
   ```
   All checks must pass before you open the PR.

3. **Open the PR against `main`** with:
   - A clear title following the commit message convention
   - A description that explains **what** changed and **why**
   - A link to the related issue (`Closes #123`)
   - A brief test plan — what did you test manually or in the test suite

4. **PR checklist** (include this in your description):

   ```markdown
   - [ ] Tests added or updated for all changed behavior
   - [ ] `ruff check` and `ruff format --check` pass
   - [ ] `mypy codeprism/` passes
   - [ ] All existing tests pass
   - [ ] Docstrings added/updated for public functions
   - [ ] CHANGELOG updated (for user-facing changes)
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

1. **CodePrism version** (`pip show codeprism`)
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

Email the maintainers directly at **krishna.tyagi@futuresmart.ai** with:
- A description of the vulnerability
- Steps to reproduce
- Potential impact
- Any suggested remediation

You will receive a response within 72 hours. We will coordinate a fix and disclosure timeline with you and credit you in the release notes unless you prefer to remain anonymous.

---

## Release Process

Releases are managed by maintainers. The process is:

1. Bump version in `pyproject.toml`
2. Update `CHANGELOG.md` with all user-facing changes since the last release
3. Tag the commit: `git tag vX.Y.Z`
4. Push the tag — CI publishes to PyPI automatically
5. Create a GitHub Release with the changelog entries as the body

Version numbers follow [Semantic Versioning](https://semver.org/):
- **PATCH** (`0.1.x`) — bug fixes, no API changes
- **MINOR** (`0.x.0`) — new features, backward-compatible
- **MAJOR** (`x.0.0`) — breaking changes to the public API or MCP tool signatures

---

## Questions?

- Open a [GitHub Discussion](https://github.com/knight22-21/CodePrism/discussions) for general questions
- Tag an issue `question` if you're unsure whether something is a bug or expected behavior
- For anything else: **krishna.tyagi@futuresmart.ai**

Thank you for making CodePrism better.
