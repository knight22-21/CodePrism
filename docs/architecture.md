# CodePrism Architecture

CodePrism is structured as five loosely coupled layers. Each layer has a single responsibility
and communicates with adjacent layers through narrow interfaces. Dependencies point downward:
`mcp` and `cli` sit on top and may use any lower layer, `query` and `indexer` use `core` and
`parser`, and nothing in `core` imports upward.

```
┌──────────────────────────────────────────────────────────────────┐
│                        MCP / CLI Layer                           │
│    codeprism serve | index | setup | scan | watch | search ...   │
└──────────────────────────────┬───────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────────┐
│                  Facade (CodePrism, codeprism/__init__.py)       │
│            index() | get_context() | get_impact() | session()    │
└──────┬─────────────────────────────────────────┬─────────────────┘
       │                                         │
┌──────▼──────────────┐               ┌──────────▼────────────────┐
│   Query Engine      │               │   Indexer / Watcher       │
│  get_context        │               │  ProjectIndexer           │
│  get_callers        │               │  IncrementalUpdater       │
│  get_impact         │               │  ProjectWatcher           │
│  get_dependencies   │               │  call_resolver            │
│  search_symbols     │               └──────────┬────────────────┘
│  get_module_summary │                          │
└──────┬──────────────┘               ┌──────────▼────────────────┐
       │                              │   Parser Registry         │
       │                              │  10 languages (see below) │
       │                              └──────────┬────────────────┘
       │                                         │
┌──────▼─────────────────────────────────────────▼─────────────────┐
│                    Storage / Graph Core                          │
│   StorageManager (SQLite)  |  GraphEngine (NetworkX)             │
└──────────────────────────────────────────────────────────────────┘
```

---

## Layer 1 — Parser Registry

**Location:** `codeprism/parser/`, `codeprism/core/languages.py`

Ten languages are supported: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby and
PHP. `codeprism/core/languages.py` is the single source of truth for which extensions belong
to which language. The indexer, the file watcher and the config defaults all derive from it,
and `tests/test_languages.py` asserts that every listed extension has a real parser in
`ParserRegistry`.

Each parser takes a source file and produces a `ParseResult` containing:

- `FileRecord` — path, language, size, checksum, line count
- `SymbolRecord[]` — functions, classes, imports, variables, type aliases
- `EdgeRecord[]` — DEFINES, CALLS, IMPORTS, INHERITS edges that were resolved inside the file
- `UnresolvedRef[]` — CALLS / IMPORTS / INHERITS whose targets are in other files. For Python
  calls, each ref also records its **call style** (`bare` for `f()`, `attribute` for `x.f()`)
  and the **receiver** (`self._storage`, `os.path`), which the cross-file resolver needs.

All parsers use [tree-sitter](https://tree-sitter.github.io/tree-sitter/) for AST extraction.
Parsing is pure (path + content in, dataclasses out), so it can run in worker processes.

**Intra-file resolution** (`BaseParser.resolve_intrafile_refs`): after parsing, unresolved refs
are matched against the file's own symbol table. Calls that point at import stubs are
intentionally left unresolved so the cross-file resolver wires them to the real definition.

---

## Layer 2 — Storage / Graph Core

**Location:** `codeprism/core/`

### StorageManager (SQLite)

One SQLite database per project, stored in the platform user-data directory
(`platformdirs`; the file name is a hash of the project's resolved path). Tables:

| Table | Contents |
|---|---|
| `files` | Path, language, checksum, timestamps, line count |
| `symbols` | Name, kind, signature, docstring, line range, complexity |
| `edges` | Kind, from/to symbol ids, file path, line number |
| `security_issues` | Persisted scan results |
| `session_events` | The session journal used for `record_read`/`record_write`/`undo_write` |

Notable behaviour:

- **Paths are stored absolute.** Lookups (`find_files_by_path`) also accept project-relative
  paths, `./`, either separator, and case-insensitive matching on Windows. A path that matches
  several files is reported as ambiguous with its candidates, never guessed.
- **Index format version.** `PRAGMA user_version` holds `INDEX_FORMAT_VERSION`. When a release
  changes parser output, the next index sees the mismatch and re-parses every file once instead
  of trusting checksums.
- **Tuning for bulk writes:** WAL journal, `synchronous=NORMAL` (safe in WAL), a 64 MB page
  cache and in-memory temp store. Indexed lookups exist for symbol names, edge endpoints and
  edge file paths, so single-file updates never scan whole tables.
- Multiple processes may safely write to the same database (WAL). Each keeps its own in-memory
  graph, so one process does not see another's changes until it reloads.

### GraphEngine (NetworkX)

An in-memory `networkx.MultiDiGraph` loaded from SQLite. Nodes carry their `SymbolRecord` or
`FileRecord`; edges carry their `EdgeRecord`. Used for traversal that SQL is awkward for:

- `get_callers` / `get_callees` — direct neighbours over CALLS edges
- `get_impact` — transitive reachability
- Cycle detection for circular-dependency reports

It keeps a `file_path → edges` index, so removing a file's edges does not scan the graph. The
graph is loaded at server start-up (and replaced after each full index); single-file updates
patch it in place.

---

## Layer 3 — Indexer / Watcher

**Location:** `codeprism/indexer/`

### ProjectIndexer

`index(path, force=False)`:

1. **Format check.** An index written by an older format is treated as `force=True` once.
2. **Discover files.** The file list comes from `git ls-files --cached --others
   --exclude-standard`, so `.gitignore` (including nested files and negations) is honoured
   exactly and ignored trees such as `node_modules` are never walked. Outside git, or if git is
   unavailable, or if the requested root is itself ignored, it falls back to a directory walk.
   Default ignore directories and `security.ignore_paths` globs are applied on top.
3. **Purge** records of files that no longer exist (also with `force=True`).
4. **Parse** changed and new files; unchanged files are skipped by SHA-256 checksum. For 200 or
   more files, parsing runs in a **process pool** (one worker per core, batches of 64, because
   parsing is CPU-bound Python and threads are serialized by the GIL); smaller projects, custom
   registries and `parse_workers = 1` use threads. A pool failure falls back to threads.
5. **Replace** the old symbols and outgoing edges of every re-parsed file in one transaction,
   then persist the new records in batches.
6. **Resolve cross-file references** (see below) and drop edges whose endpoint no longer
   exists.
7. **Reload** the in-memory graph, optionally build embeddings, and stamp the format version.

### Cross-file call resolution (`call_resolver.py`)

Shared by the full index and by single-file updates.

- **Python calls follow imports.** `f()` resolves through the caller's import of `f` (including
  package re-exports from `__init__.py`, star imports and function-local imports); `mod.f()`
  resolves `mod` through the imports; builtins and third-party modules link to nothing in the
  project; `obj.f()` and `self.f()` link only when there is exactly one candidate in a file the
  caller imports. Only functions and classes can be call targets.
- **Other languages link calls by name alone** (see *Known limitations*).
- Precision is preferred over recall: a missing edge makes an agent look further, a wrong one
  sends it to the wrong code. On the cross-file benchmark, Python precision is 1.00 on requests,
  flask, httpx and CodePrism (see `benchmark-results.md`).

### IncrementalUpdater

`update_file(path)` for one changed file:

1. Normalize the path (always absolute) and compare the checksum; skip if unchanged.
2. Re-parse, and remember the edges other files have **into** this file.
3. Replace the file's symbols and edges in storage and in the graph.
4. **Reconnect** the remembered inbound edges: restored if the target still exists, re-pointed
   if the symbol kept its name but changed kind, dropped if it is gone.
5. Resolve the file's own references using targeted name lookups (not the whole symbols table).

Cost is independent of repository size: on a 2M-line corpus a single-file update takes roughly
70–90 ms once warm.

### ProjectWatcher

Wraps `watchdog` and feeds changed files to `IncrementalUpdater`, debouncing rapid saves
(500 ms) so a `git checkout` does not trigger hundreds of updates. It ignores gitignored files
and the default ignore directories. **It is started only by `codeprism watch`.** The MCP server
does not run it (see *Known limitations*).

---

## Layer 4 — Query Engine

**Location:** `codeprism/query/`

Translates high-level questions into graph + SQL operations and returns typed results.

| Method | How it works |
|---|---|
| `get_context(file, symbol, depth)` | Symbol lookup by file + name, then BFS to depth N for callers/callees/types |
| `get_callers(file, function)` | Direct predecessors over CALLS edges |
| `get_callees(file, function)` | Direct successors over CALLS edges |
| `get_impact(file, symbol)` | Reverse traversal: all reachable dependents, severity, affected tests |
| `get_dependencies(file)` / `get_dependents(file)` | IMPORTS edges, classified internal vs external |
| `get_module_summary(file)` | File metadata + top public symbols by complexity |
| `get_data_flow(file, symbol)` | Sources and sinks around a symbol |
| `search_symbols(query, kind)` | SQL `LIKE` substring match (capped at 50 rows), case-insensitive `kind`; semantic vector search when embeddings are enabled |

Result types live next to their builders: `ContextResult` (`query/context.py`), `ImpactResult`
(`query/impact.py`), `ModuleSummary` (`query/summary.py`), and `SearchMatch` /
`DependencyResult` (`query/engine.py`).

---

## Layer 5 — Facade + MCP / CLI

### CodePrism facade

**Location:** `codeprism/__init__.py`

The entry point for library use: an async context manager that owns the storage and engine
lifecycle. It exposes `index()`, `get_context()`, `get_impact()`, `get_module_summary()` and
`session(id)`; everything else is reachable via `prism.engine`. `SecurityGate` is exported
alongside it.

```python
async with CodePrism("/path/to/project") as prism:
    await prism.index()
    ctx = await prism.get_context("src/auth.py", "login")
```

### MCP server

**Location:** `codeprism/mcp/`

Built on [FastMCP](https://github.com/jlowin/fastmcp). Transport is **stdio** (default) or
**SSE**. The SSE server binds to `127.0.0.1` only and has no built-in authentication.

- **Project selection.** `codeprism serve` with no path serves the project containing the
  working directory: the nearest ancestor with a `.git` or `.codeprism.toml`. The home directory
  and filesystem roots are never treated as projects. This is why one user-level MCP entry works
  for every repository.
- **Start-up.** The server loads the graph from SQLite, then indexes the project in the
  background (full index on first run, incremental afterwards). `get_graph_stats` reports
  `index_status` (`indexing` / `ready` / `off` / `error: …`) and `project_path`.
- **Paths.** Every file argument may be project-relative; it is resolved against the served
  project root, not the server's working directory.
- **Configuration.** `.codeprism.toml` is read by the server at start-up (see the README).

Tools (21):

| Group | Tools |
|---|---|
| Indexing | `index_project`, `update_file`, `get_graph_stats` |
| Structure | `get_context`, `get_module_summary`, `get_file_map`, `search_symbol` |
| Relationships | `get_callers`, `get_callees`, `get_impact`, `get_dependencies`, `get_dependents`, `get_data_flow` |
| Security | `scan_file`, `scan_diff`, `check_secret_exposure`, `check_dependencies_cve` |
| Session | `record_read`, `record_write`, `get_session_context`, `undo_write` |

### Security Gate

**Location:** `codeprism/security/`

Runs for `scan_diff`, `scan_file`, `record_write` and the `codeprism scan` command. Six detector
categories: secrets (pattern + entropy), injection, weak crypto, environment-variable exposure,
unsafe dependencies, and code safety. It returns a `SecurityReport` of `SecurityIssue` objects
with severity (BLOCK / WARN / INFO), line number and a suggested fix. `record_write` refuses a
BLOCK result before anything reaches disk. The CLI exits with code 2 on BLOCK.

### CLI

**Location:** `codeprism/cli.py`

A thin wrapper over the facade and query engine. Commands: `index`, `serve`, `setup`, `scan`,
`watch`, `context`, `impact`, `callers`, `summary`, `search`, `stats`, `visualize`.
`setup <agent>` registers the server with an agent and writes the shared `AGENTS.md` guide (see
`INTEGRATIONS.md`).

---

## Data Flow: Full Index

```
codeprism index /project   (or the server's background index at start-up)
       │
       ▼
ProjectIndexer._find_source_files — git ls-files (falls back to a directory walk)
       │
       ├─► process pool: ParserRegistry.get(file).parse(file) ──► ParseResult
       │   (unchanged files are skipped by checksum)
       ▼
StorageManager: clear old rows of re-parsed files, then batch-write files/symbols/edges
       │
       ▼
call_resolver.resolve_refs(all UnresolvedRef)
  Python calls: follow imports  |  other languages: match by name
       │
       ▼
StorageManager.delete_dangling_edges()  ──► GraphEngine.load_from_storage()
```

## Data Flow: Single Query

```
get_callers("src/sessions.py", "send")          (relative or absolute path)
       │
       ▼
server._resolve_file  ──► unique indexed file, or an "ambiguous" / "not indexed" error
       │
       ▼
QueryEngine.find_symbol(file, "send")  ──► SymbolRecord
       │
       ▼
GraphEngine.get_callers(symbol.id)  ──► [SymbolRecord, ...]
```

---

## Key Design Decisions

**SQLite over Postgres:** single-file database, zero configuration, ships inside the Python
package. Projects are self-contained, with no external process to manage.

**NetworkX over SQL graph queries:** transitive reachability (BFS for impact analysis) is much
simpler in NetworkX than in recursive SQL CTEs. The trade-off is memory: the graph lives in
RAM. Measured on a synthetic 2M-line, 8.6K-file repository (210K nodes, 445K edges), loading it
takes about 8.7 s and about 1.6 GB per server process. That is comfortable for typical
repositories and heavy for monorepos.

**tree-sitter over regex parsing:** language-aware extraction avoids the false positives and
missed patterns of regexes, and handles nested functions, decorators, async and generics.

**Git as the source of truth for what to index:** asking git for the file list gives exact
`.gitignore` semantics (nested ignores, negations, global excludes) and avoids walking ignored
trees.

**Resolve within a file first, then across files, and prefer precision:** resolving inside a
file avoids a global name-collision problem; across files, import information decides where a
call goes. Linking nothing is better than linking the wrong function.

---

## Known limitations

Tracked as public issues:

| Issue | Limitation |
|---|---|
| [#34](https://github.com/knight22-21/CodePrism/issues/34) | Symbol ids ignore the owning class, so same-named methods and class attributes in different classes of one file collapse into one symbol |
| [#35](https://github.com/knight22-21/CodePrism/issues/35) | The MCP server does not watch files: edits made during a session are not visible until a restart (or until the agent writes through `record_write` / `update_file`). `codeprism watch` updates the database but not a running server's in-memory graph |
| [#36](https://github.com/knight22-21/CodePrism/issues/36) | Embeddings are not updated or cleaned up incrementally, and semantic search filters after taking the top 20 hits |
| [#37](https://github.com/knight22-21/CodePrism/issues/37) | Only Python calls follow imports; other languages link calls by name alone |
| [#38](https://github.com/knight22-21/CodePrism/issues/38) | `search_symbol` returns at most 50 unranked rows and does not say when it truncated |
| [#39](https://github.com/knight22-21/CodePrism/issues/39) | Definitions inside `try` / `if` / `with` blocks are not indexed |
| [#40](https://github.com/knight22-21/CodePrism/issues/40) | The whole graph is loaded before the server answers (8.7 s and 1.6 GB at 2M LOC) |
