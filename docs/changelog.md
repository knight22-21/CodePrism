# Changelog

All notable changes to CodePrism are documented here.
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [Unreleased] — v0.1.5

### Added
- **Level 1 benchmark harness** — token reduction + LLM-as-judge accuracy eval
  - `benchmarks/run_token_benchmark.py` — CLI runner with tiktoken backend
  - `benchmarks/accuracy.py` — Ollama cloud and OpenAI-compatible judge backends
  - `benchmarks/tasks/fixture_tasks.json` — 10 tasks against the fixture project
  - `benchmarks/tasks/requests_tasks.json` — 10 tasks against psf/requests v2.32.3
  - `benchmarks/setup_repos.py` — clones real-world repos for extended benchmark runs
  - `benchmarks/list_models.py` — lists available Ollama judge models with ratings
  - `.env.example` — template for API keys
- **CI: token benchmark workflow** — `.github/workflows/benchmark.yml` runs on every push/PR,
  token-only mode, no API key required, results uploaded as artifact
- **`[bench]` optional dependency group** — `tiktoken`, `openai`, `python-dotenv`
- **`docstring` field in `get_context` output** — symbol docstrings now included in graph
  query results, improving accuracy on symbol_lookup tasks

### Fixed
- **Cross-file call edge bug** (`BaseParser.resolve_intrafile_refs`): CALLS refs that matched
  import stubs were being resolved to the stub instead of the real cross-file target. Fix: skip
  CALLS-to-import-stub resolution intra-file, let `_resolve_cross_file` handle them.
  Impact: `run_payment → compute_checksum` and all similar cross-file calls now wire correctly.
  All 341 tests pass.

### Benchmark results
- Fixture corpus (tiny files): 27% avg token reduction, accuracy baseline=0.89 / CP=0.60
- Requests corpus (real-world, 6k–12k token files): **88.5% avg token reduction**,
  accuracy baseline=0.81 / CP=0.66

---

## [v0.1.4] — 2026-09-06

### Added
- Property-based tests (17 Hypothesis tests) for scanner, graph, and search invariants
- Comprehensive `INTEGRATIONS.md` covering 11 editors and agent frameworks
  (Claude Code, Cursor, Windsurf, Continue.dev, Zed, VS Code Copilot, Cody, Docker Compose,
  CI pipelines, pre-commit hook, OpenAI Agents SDK)
- Compact Integrations section in README linking to `INTEGRATIONS.md`

---

## [v0.1.3] — 2026-09-06

### Added
- Semantic search via embeddings (ChromaDB vector index)
- `--embeddings` flag to `codeprism index` CLI
- `enable_embeddings` config option in `.codeprism.toml`
- `set_embeddings` on QueryEngine; `search_symbols` falls back to substring if no embeddings

### Fixed
- pyproject.toml encoding corruption from UTF-16 write

---

## [v0.1.2] — 2026-09-06

### Added
- `project_path` param to `search_symbol` MCP tool
- `get_graph_stats` path filter

### Fixed
- Author email in pyproject.toml

---

## [v0.1.1] — 2026-09-05

### Added
- MCP server implementation (FastMCP, stdio + SSE transports)
- MCP tools: `get_context`, `get_impact`, `get_module_summary`, `get_callers`, `get_callees`,
  `search_symbol`, `get_file_map`, `get_dependencies`, `scan_diff`, `record_read`,
  `record_write`, `get_session_context`, `undo_write`
- CLI interface: `index`, `serve`, `scan`, `context`, `impact`, `callers`,
  `search`, `summary`, `stats`, `watch`, `setup`
- Query engine: `get_context`, `get_callers`, `get_impact`, `get_dependencies`,
  `get_module_summary`, `search_symbols`
- Security gate: six detector categories (secrets, injection, weak crypto, env exposure,
  unsafe deps, code safety) with BLOCK / WARN / INFO severity
- Incremental indexer + file watcher (watchdog-based, checksum change detection)
- Python, JavaScript/TypeScript, Go parsers (tree-sitter)
- SQLite storage + NetworkX in-memory graph
- `codeprism setup claude` and `codeprism setup cursor` auto-configuration commands

---

## [Initial] — 2026-09-04

- Project scaffolding: pyproject.toml, test fixtures, .gitignore
