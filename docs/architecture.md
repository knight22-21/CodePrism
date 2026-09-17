# CodePrism Architecture

CodePrism is structured as five loosely coupled layers. Each layer has a single responsibility
and communicates with adjacent layers through narrow interfaces.

```
┌──────────────────────────────────────────────────────────────────┐
│                        MCP / CLI Layer                           │
│           codeprism serve  |  codeprism index  |  codeprism scan │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                       Facade (CodePrism)                         │
│         index() | get_context() | get_impact() | ...             │
└──────┬─────────────────────────────────────────┬─────────────────┘
       │                                         │
┌──────▼──────────────┐               ┌──────────▼────────────────┐
│   Query Engine      │               │   Indexer / Watcher       │
│  get_context        │               │  ProjectIndexer           │
│  get_callers        │               │  IncrementalUpdater       │
│  get_impact         │               │  FileWatcher              │
│  get_dependencies   │               └──────────┬────────────────┘
│  search_symbols     │                          │
│  get_module_summary │               ┌──────────▼────────────────┐
└──────┬──────────────┘               │   Parser Registry         │
       │                              │  PythonParser             │
       │                              │  JavaScriptParser         │
       │                              │  GoParser                 │
       │                              └──────────┬────────────────┘
       │                                         │
┌──────▼─────────────────────────────────────────▼─────────────────┐
│                    Storage / Graph Core                           │
│   StorageManager (SQLite)  |  GraphEngine (NetworkX)             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Parser Registry

**Location:** `codeprism/parser/`

Each language parser (`PythonParser`, `JavaScriptParser`, `GoParser`) takes a source file
and produces a `ParseResult` containing:

- `FileRecord` — path, language, size, checksum, line count
- `SymbolRecord[]` — functions, classes, imports, variables, type aliases
- `EdgeRecord[]` — DEFINES, CALLS, IMPORTS, INHERITS edges (intra-file, already resolved)
- `UnresolvedRef[]` — CALLS / IMPORTS edges whose targets are in other files

All parsers use [tree-sitter](https://tree-sitter.github.io/tree-sitter/) for AST extraction,
which is language-agnostic and extremely fast (~1ms per file).

**Intra-file resolution** (`BaseParser.resolve_intrafile_refs`):
After parsing, unresolved refs are matched against the file's own symbol table. Refs that point
at import stubs are intentionally left unresolved so the cross-file resolver handles them —
this prevents call edges from being wired to import stubs instead of the real definition.

**Cross-file resolution** (`ProjectIndexer._resolve_cross_file`):
After all files in a project are parsed, the indexer builds a global name → symbol-id map
and resolves all remaining `UnresolvedRef` entries, adding cross-file edges to the graph.

---

## Layer 2 — Storage / Graph Core

**Location:** `codeprism/core/`

Two components work together:

### StorageManager (SQLite)

Stores all data durably in a single SQLite database per project. Schema:

| Table | Contents |
|---|---|
| `files` | FileRecord rows — path, language, checksum, timestamps |
| `symbols` | SymbolRecord rows — name, kind, signature, docstring, line range |
| `edges` | EdgeRecord rows — kind, from_id, to_id, file_path, line_number |

Checksum-based change detection: on incremental updates, unchanged files are skipped entirely.

### GraphEngine (NetworkX)

Maintains an in-memory directed graph (`networkx.DiGraph`) loaded from the SQLite data.
Used for graph traversal operations that SQL is awkward for:
- `get_callers` / `get_callees` — direct neighbor traversal
- `get_impact` — BFS/DFS transitive reachability
- Cycle detection for circular dependency reports

The graph is rebuilt from SQLite on startup and patched incrementally on file changes.

---

## Layer 3 — Indexer / Watcher

**Location:** `codeprism/indexer/`

### ProjectIndexer

Orchestrates a full index of a project:
1. Walk the file tree, filter by supported extensions and `.gitignore`
2. Parse each file via the parser registry
3. Batch-write FileRecords, SymbolRecords, and intra-file EdgeRecords to SQLite
4. Run cross-file ref resolution across all parsed results
5. Reload the GraphEngine from the updated SQLite data

### IncrementalUpdater

On file change events:
1. Read the new file content and compute its checksum
2. If checksum matches stored — skip (no-op)
3. Otherwise re-parse the file, diff symbols and edges vs stored, apply minimal writes
4. Patch the in-memory GraphEngine (add/remove nodes and edges)

### FileWatcher

Wraps `watchdog` to emit file change events to `IncrementalUpdater`. Debounces rapid saves
(configurable, default 500ms) so a single `git checkout` doesn't trigger hundreds of updates.

---

## Layer 4 — Query Engine

**Location:** `codeprism/query/`

Translates high-level questions into graph + SQL operations and returns typed result objects.

| Method | How it works |
|---|---|
| `get_context(file, symbol, depth)` | Symbol lookup by name + file, then BFS to depth N for callers/callees/types |
| `get_callers(file, function)` | Direct predecessors in the graph for the symbol node |
| `get_callees(file, function)` | Direct successors via CALLS edges |
| `get_impact(file, symbol)` | Reverse BFS from the symbol — all reachable dependents |
| `get_dependencies(file)` | All IMPORTS edges from the file node, classified internal vs external |
| `get_module_summary(file)` | File node metadata + top-N public symbols by complexity |
| `search_symbols(query)` | SQL `LIKE` substring match across symbol names + optional kind filter |

Result types are defined in `codeprism/query/models.py`: `ContextResult`, `ImpactResult`,
`ModuleSummary`, `DependencyResult`, `SearchResult`.

---

## Layer 5 — Facade + MCP / CLI

### CodePrism Facade

**Location:** `codeprism/facade.py`

Single entry point for library use. Async context manager that owns the storage and engine
lifecycle. Exposes a curated subset of query engine methods (`get_context`, `get_impact`,
`get_module_summary`). For full query engine access: `prism.engine`.

```python
async with CodePrism("/path/to/project") as prism:
    await prism.index()
    ctx = await prism.get_context("src/auth.py", "login")
```

### MCP Server

**Location:** `codeprism/mcp/`

Built on [FastMCP](https://github.com/jlowin/fastmcp). Exposes all query engine methods as
MCP tools plus session tracking tools (`record_read`, `record_write`, `get_session_context`,
`undo_write`) and the security gate (`scan_diff`).

Transport: **stdio** (default, for local agents like Claude Code and Cursor) or **SSE**
(for remote/network agents). Selected via `--transport` CLI flag.

### Security Gate

**Location:** `codeprism/security/`

Runs before every `scan_diff` / `record_write` call. Six detector categories:
secrets, injection, weak crypto, env-var exposure, unsafe dependencies, code safety.

Returns a `SecurityReport` with a list of `SecurityIssue` objects, each with severity
(BLOCK / WARN / INFO), line number, and description. A BLOCK severity means the write is
rejected and never reaches disk.

### CLI

**Location:** `codeprism/cli/`

Thin wrapper around the facade and query engine. Commands: `index`, `serve`, `scan`,
`context`, `impact`, `callers`, `search`, `summary`, `stats`, `watch`, `setup`.

---

## Data Flow: Full Index

```
codeprism index /project
       │
       ▼
FileWalker — list .py / .js / .ts / .go files (respects .gitignore)
       │
       ├─► PythonParser.parse(file)  ──► ParseResult (symbols + edges + unresolved_refs)
       ├─► JavaScriptParser.parse(file)
       └─► GoParser.parse(file)
       │
       ▼
StorageManager.bulk_write(files, symbols, edges)  ──► SQLite
       │
       ▼
ProjectIndexer._resolve_cross_file(all_results)
  build global name→id map
  for each UnresolvedRef:
    find target_id in global map
    write cross-file EdgeRecord to SQLite
       │
       ▼
GraphEngine.reload_from_storage()  ──► in-memory NetworkX DiGraph
```

## Data Flow: Single Query

```
get_callers("src/sessions.py", "send")
       │
       ▼
StorageManager.get_symbol_by_name(file, "send")  ──► SymbolRecord
       │
       ▼
GraphEngine.predecessors(symbol.id, edge_kind=CALLS)  ──► [SymbolRecord, ...]
       │
       ▼
QueryEngine returns List[SymbolRecord] with name, file_path, line_start
```

---

## Key Design Decisions

**SQLite over Postgres:** Single-file database, zero configuration, ships inside the Python
package. Projects are self-contained — no external process to manage.

**NetworkX over SQL graph queries:** Transitive reachability (BFS for impact analysis)
is significantly simpler and faster in NetworkX than recursive SQL CTEs, especially for
large graphs. The tradeoff is memory (the graph lives in RAM); acceptable for codebases
under ~500k LOC.

**tree-sitter over regex parsing:** Language-aware AST extraction avoids the false positives
and missed patterns that regex parsers produce. tree-sitter grammars are maintained by the
community and handle edge cases (nested functions, decorators, async, generics) correctly.

**Separate intra-file and cross-file resolution:** Resolving within a file first, then across
files, avoids a O(n²) global name-collision problem. The import-stub guard in
`resolve_intrafile_refs` is the critical correctness invariant — without it, call edges
resolve to the wrong file's definition.
