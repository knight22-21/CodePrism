# Changelog

All notable changes to CodePrism are documented here.
Versioning follows [Semantic Versioning](https://semver.org/).

---

## [v0.1.7] — 2026-09-18

### Added
- **Benchmark corpus expansion**: added pallets/flask 3.0.3 and encode/httpx 0.27.2
  as benchmark corpora (10 tasks each — symbol_lookup, call_trace, impact_analysis,
  dependency_map). Token reduction: flask 91.3%, httpx 93.0%. Overall average across
  3 production codebases: **91%**.

### Fixed
- **`get_dependencies` output format** (`python_parser` + `engine`):
  was returning imported symbol names (`HTTPAdapter`, `_basic_auth_str`) instead of
  source modules (`.adapters`, `.auth`). Root cause: `source_module` was stored in
  `extra{}` which is excluded from SQLite persistence. Fix: store `source_module` in
  the `signature` field (persisted). `get_dependencies` now groups import symbols by
  source module and returns deduplicated module paths. Falls back to symbol names for
  DBs indexed before this change (backward compatible). Re-index required for updated output.
- **Benchmark ground truths** (`requests_004`, `requests_006`, `requests_008`):
  updated to match actual tool output — module paths for dependency_map tasks,
  and both callers (`Session.request` and `SessionRedirectMixin.resolve_redirects`)
  for the `get_callers("send")` task.

---

## [v0.1.6] — 2026-09-17

### Added
- **Level 2 latency benchmark** (`benchmarks/run_latency_benchmark.py`)
  - Measures p50/p95/p99 query latency with configurable warmup and reps
  - Holds the CodePrism engine open across all tasks — times pure query latency, not indexing
  - Results on psf/requests: get_context p50=1.2ms, get_impact p50=2.0ms, get_dependencies p50=3.8ms

### Fixed
- **`get_dependencies` latency** (`StorageManager.get_non_import_symbol_names`):
  was calling `SELECT * FROM symbols` (full table scan) to build the internal/external
  classification set. Fixed with `SELECT DISTINCT name WHERE kind != 'import'`, reducing
  latency from 10.7ms → 3.8ms p50 (64% faster). All 341 tests pass.

---

## [v0.1.5] — 2026-09-17

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
