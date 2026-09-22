"""CodePrism CLI — typer-based entry point."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    name="codeprism",
    help="CodePrism — knowledge graph for AI coding agents.",
    add_completion=False,
)
console = Console()


# ── Shared helpers ────────────────────────────────────────────────────────────


async def _open_session(project_path: str):
    """Open storage + graph for an already-indexed project."""
    from .core.graph import GraphEngine
    from .core.paths import get_db_path
    from .core.storage import StorageManager
    from .query.engine import QueryEngine

    db_path = get_db_path(project_path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()
    await graph.load_from_storage(storage)
    return QueryEngine(graph, storage), storage


def _parse_target(target: str) -> tuple[str, str]:
    """Parse 'file.py::symbol' → (file_path, symbol_name)."""
    if "::" not in target:
        console.print("[red]Error:[/red] Use format  file.py::symbol_name")
        raise typer.Exit(1)
    file_path, symbol = target.rsplit("::", 1)
    return file_path, symbol


# ── index ─────────────────────────────────────────────────────────────────────


@app.command()
def index(
    path: str = typer.Argument(..., help="Project directory to index"),
    languages: Optional[str] = typer.Option(
        None, "--languages", "-l",
        help="Comma-separated language list (default: python,javascript,typescript)"
    ),
    embeddings: bool = typer.Option(
        False, "--embeddings", "-e",
        help="Also build semantic vector index (requires codeprism[embeddings])"
    ),
) -> None:
    """Build the knowledge graph for a project directory."""
    asyncio.run(_index(path, languages, embeddings))


async def _index(path: str, languages: Optional[str], embeddings: bool = False) -> None:
    from .core.config import CodePrismConfig
    from .core.graph import GraphEngine
    from .core.paths import get_db_path
    from .core.storage import StorageManager
    from .indexer.project_indexer import ProjectIndexer

    langs = [l.strip() for l in languages.split(",")] if languages else None
    config = CodePrismConfig(languages=langs, enable_embeddings=embeddings) if langs \
        else CodePrismConfig(enable_embeddings=embeddings)

    db_path = get_db_path(path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()

    console.print(f"Indexing [bold]{path}[/bold] ...")
    if embeddings:
        console.print("[dim]Embeddings enabled — will build vector index after parsing...[/dim]")
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(path)
    await storage.close()

    if result.success:
        console.print(
            f"[green]Done.[/green] "
            f"{result.file_count} files · {result.symbol_count} symbols · "
            f"{result.edge_count} edges · {result.duration_seconds:.2f}s"
        )
        if embeddings:
            console.print("[green]Semantic index built.[/green] search_symbol now uses embeddings.")
    else:
        console.print(f"[yellow]Completed with {len(result.errors)} error(s).[/yellow]")
        for err in result.errors:
            console.print(f"  [red]•[/red] {err}")


# ── context ───────────────────────────────────────────────────────────────────


@app.command()
def context(
    target: str = typer.Argument(..., help="file.py::symbol_name"),
    depth: int = typer.Option(2, "--depth", "-d", help="Traversal depth (1-3)"),
    project: str = typer.Option(".", "--project", "-p", help="Project path"),
) -> None:
    """Get structured context for a symbol."""
    asyncio.run(_context(target, depth, project))


async def _context(target: str, depth: int, project: str) -> None:
    file_path, sym_name = _parse_target(target)
    engine, storage = await _open_session(project)
    try:
        result = await engine.get_context(file_path, sym_name, depth)
    finally:
        await storage.close()

    if result is None:
        console.print(f"[red]Not found:[/red] {sym_name} in {file_path}")
        raise typer.Exit(1)

    s = result.symbol
    console.print(Panel(
        f"[bold]{s.name}[/bold]  [{s.kind.value}]\n"
        f"[dim]{s.signature or ''}[/dim]\n\n"
        + (s.docstring or ""),
        title=f"{file_path}  line {s.line_start}–{s.line_end}",
    ))

    if result.direct_callers:
        console.print("\n[bold]Callers:[/bold]")
        for c in result.direct_callers:
            console.print(f"  • {c.name} ({c.kind.value})")

    if result.direct_callees:
        console.print("\n[bold]Callees:[/bold]")
        for c in result.direct_callees:
            console.print(f"  • {c.name} ({c.kind.value})")

    console.print(f"\n[dim]Estimated tokens: {result.estimated_token_count}[/dim]")


# ── impact ────────────────────────────────────────────────────────────────────


@app.command()
def impact(
    target: str = typer.Argument(..., help="file.py::symbol_name"),
    project: str = typer.Option(".", "--project", "-p", help="Project path"),
) -> None:
    """Transitive impact analysis — what breaks if this symbol changes?"""
    asyncio.run(_impact(target, project))


async def _impact(target: str, project: str) -> None:
    file_path, sym_name = _parse_target(target)
    engine, storage = await _open_session(project)
    try:
        result = await engine.get_impact(file_path, sym_name)
    finally:
        await storage.close()

    if result is None:
        console.print(f"[red]Not found:[/red] {sym_name} in {file_path}")
        raise typer.Exit(1)

    severity_colour = {"LOW": "green", "MEDIUM": "yellow", "HIGH": "red", "CRITICAL": "bright_red"}
    colour = severity_colour.get(result.severity, "white")

    console.print(Panel(
        f"Severity: [{colour}][bold]{result.severity}[/bold][/{colour}]\n"
        f"Direct dependents: {len(result.direct_dependents)}\n"
        f"Transitive dependents: {result.estimated_change_surface}\n"
        f"Public API affected: {'yes' if result.public_api_affected else 'no'}\n"
        f"Affected test files: {len(result.affected_test_files)}",
        title=f"Impact: {sym_name}",
    ))

    if result.direct_dependents:
        console.print("\n[bold]Direct dependents:[/bold]")
        for s in result.direct_dependents[:10]:
            console.print(f"  • {s.name} ({s.kind.value})")

    if result.affected_test_files:
        console.print("\n[bold]Affected test files:[/bold]")
        for fp in result.affected_test_files:
            console.print(f"  • {fp}")


# ── summary ───────────────────────────────────────────────────────────────────


@app.command()
def summary(
    file: str = typer.Argument(..., help="Source file path"),
    project: str = typer.Option(".", "--project", "-p", help="Project path"),
) -> None:
    """High-level summary of a source file."""
    asyncio.run(_summary(file, project))


async def _summary(file: str, project: str) -> None:
    engine, storage = await _open_session(project)
    try:
        result = await engine.get_module_summary(file)
    finally:
        await storage.close()

    if result is None:
        console.print(f"[red]Not found:[/red] {file}")
        raise typer.Exit(1)

    console.print(Panel(result.purpose, title=Path(file).name))
    console.print(f"Complexity score: {result.complexity_score:.1f}")

    if result.public_api:
        console.print("\n[bold]Public API:[/bold]")
        for s in result.public_api:
            console.print(f"  • {s.name} ({s.kind.value})")

    if result.key_classes:
        console.print("\n[bold]Key classes:[/bold]")
        for c in result.key_classes:
            console.print(f"  • {c.name}")

    if result.dependencies:
        console.print(f"\n[bold]Dependencies:[/bold] {', '.join(result.dependencies[:8])}")

    if result.test_coverage_file:
        console.print(f"\n[bold]Test file:[/bold] {result.test_coverage_file}")


# ── callers ───────────────────────────────────────────────────────────────────


@app.command()
def callers(
    target: str = typer.Argument(..., help="file.py::function_name"),
    project: str = typer.Option(".", "--project", "-p", help="Project path"),
) -> None:
    """List all functions that call the given function."""
    asyncio.run(_callers(target, project))


async def _callers(target: str, project: str) -> None:
    file_path, sym_name = _parse_target(target)
    engine, storage = await _open_session(project)
    try:
        syms = await engine.get_callers(file_path, sym_name)
    finally:
        await storage.close()

    if not syms:
        console.print(f"No callers found for [bold]{sym_name}[/bold]")
        return

    console.print(f"[bold]Callers of {sym_name}[/bold] ({len(syms)})")
    for s in syms:
        console.print(f"  • {s.name}  line {s.line_start}")


# ── search ────────────────────────────────────────────────────────────────────


@app.command()
def search(
    query: str = typer.Argument(..., help="Symbol name or substring"),
    kind: Optional[str] = typer.Option(None, "--kind", "-k", help="function|class|variable"),
    project: str = typer.Option(".", "--project", "-p", help="Project path"),
) -> None:
    """Find symbols matching a query string."""
    asyncio.run(_search(query, kind, project))


async def _search(query: str, kind: Optional[str], project: str) -> None:
    engine, storage = await _open_session(project)
    try:
        matches = await engine.search_symbols(query, kind)
    finally:
        await storage.close()

    if not matches:
        console.print(f"No matches for [bold]{query}[/bold]")
        return

    table = Table(title=f"Results for '{query}' ({len(matches)} found)")
    table.add_column("Name", style="bold")
    table.add_column("Kind")
    table.add_column("File")
    table.add_column("Line")

    for m in matches[:30]:
        table.add_row(
            m.symbol.name,
            m.symbol.kind.value,
            m.file_path,
            str(m.symbol.line_start or ""),
        )
    console.print(table)


# ── stats ─────────────────────────────────────────────────────────────────────


@app.command()
def stats(
    project: str = typer.Option(".", "--project", "-p", help="Project path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
    json_output: bool = typer.Option(False, "--json", "-j", help="Output stats as JSON"),
) -> None:
    """Show knowledge graph statistics."""
    asyncio.run(_stats(project, verbose, json_output))


async def _stats(project: str, verbose: bool, json_output: bool = False) -> None:
    import json as _json

    engine, storage = await _open_session(project)
    try:
        data = await engine.get_stats()
        file_map = await engine.get_file_map(project) if verbose else None
    finally:
        await storage.close()

    if json_output:
        print(_json.dumps({
            "file_count": data["file_count"],
            "function_count": data["function_count"],
            "class_count": data["class_count"],
            "variable_count": data["variable_count"],
            "import_count": data["import_count"],
            "edge_count": data["edge_count"],
            "languages": data["languages"] or [],
            "last_indexed_at": data.get("last_indexed_at"),
            "coverage_percent": data.get("coverage_percent", 0.0),
        }))
        return

    console.print(Panel(
        f"Files:     {data['file_count']}\n"
        f"Functions: {data['function_count']}\n"
        f"Classes:   {data['class_count']}\n"
        f"Variables: {data['variable_count']}\n"
        f"Imports:   {data['import_count']}\n"
        f"Edges:     {data['edge_count']}\n"
        f"Languages: {', '.join(data['languages'] or ['-'])}",
        title="CodePrism Graph Stats",
    ))

    if verbose and file_map:
        table = Table(title="Files")
        table.add_column("Path")
        table.add_column("Lang")
        table.add_column("Lines", justify="right")
        table.add_column("Symbols", justify="right")
        for e in file_map.entries:
            table.add_row(e.path, e.language, str(e.line_count), str(e.symbol_count))
        console.print(table)


# ── serve ─────────────────────────────────────────────────────────────────────


@app.command()
def serve(
    path: str = typer.Argument(".", help="Indexed project directory"),
    transport: str = typer.Option("stdio", "--transport", "-t", help="stdio | sse"),
    port: int = typer.Option(8765, "--port", help="Port for SSE transport"),
) -> None:
    """Start the MCP server (default: stdio transport for Claude Code etc.)."""
    from .mcp.server import configure, mcp
    configure(path)
    if transport == "sse":
        mcp.run(transport="sse", port=port)
    else:
        mcp.run()


# ── watch ─────────────────────────────────────────────────────────────────────


@app.command()
def watch(
    path: str = typer.Argument(..., help="Project directory to watch"),
) -> None:
    """Watch a project directory and incrementally update the graph on file changes."""
    asyncio.run(_watch(path))


async def _watch(path: str) -> None:
    from .core.graph import GraphEngine
    from .core.paths import get_db_path
    from .core.storage import StorageManager
    from .indexer.incremental_updater import IncrementalUpdater
    from .indexer.watcher import ProjectWatcher

    db_path = get_db_path(path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()
    await graph.load_from_storage(storage)
    updater = IncrementalUpdater(graph, storage)

    def on_update(fp: str, result) -> None:
        console.print(
            f"Updated [bold]{Path(fp).name}[/bold]: "
            f"+{result.nodes_added} −{result.nodes_removed} symbols"
        )

    watcher = ProjectWatcher(updater, on_update=on_update)
    console.print(f"Watching [bold]{path}[/bold]  (Ctrl+C to stop)")
    try:
        await watcher.run(path)
    except (KeyboardInterrupt, asyncio.CancelledError):
        await storage.close()
        console.print("\nStopped.")


# ── setup ─────────────────────────────────────────────────────────────────────


@app.command()
def setup(
    agent: str = typer.Argument("claude", help="Target agent: claude | cursor"),
    project: str = typer.Option(".", "--project", "-p", help="Project path to serve"),
    global_: bool = typer.Option(
        False, "--global", "-g", help="Write to global config (~/.claude/settings.json)"
    ),
) -> None:
    """Configure an AI coding agent to use CodePrism as an MCP server.

    Examples:
        codeprism setup claude --project /path/to/repo
        codeprism setup cursor --project /path/to/repo --global
    """
    _setup(agent, project, global_)


def _setup(agent: str, project: str, global_: bool) -> None:
    import json

    abs_project = str(Path(project).resolve())
    server_entry = {
        "command": "codeprism",
        "args": ["serve", abs_project],
    }

    agent = agent.lower()
    if agent == "claude":
        _write_claude_config(server_entry, global_)
    elif agent == "cursor":
        _write_cursor_config(server_entry, global_)
    else:
        console.print(f"[red]Unknown agent:[/red] {agent!r}. Supported: claude, cursor")
        raise typer.Exit(1)


_CODEPRISM_MARKER = "<!-- codeprism-instructions -->"

_CLAUDE_MD_BLOCK = """\
<!-- codeprism-instructions -->
## CodePrism — Knowledge Graph (auto-injected by `codeprism setup`)

This project is indexed with [CodePrism](https://github.com/knight22-21/CodePrism).
A live knowledge graph of every file, symbol, and relationship is available via MCP.

### Use CodePrism FIRST — before reading any source file

| Instead of … | Use … |
|---|---|
| Reading a file to understand a function | `get_context(file, symbol, depth=2)` |
| Grepping for who calls a function | `get_callers(file, function)` |
| Reading a file to understand its role | `get_module_summary(file)` |
| Guessing the blast radius of a change | `get_impact(file, symbol)` |
| Searching for a symbol by name | `search_symbol(query)` |
| Reading a file before writing it | `scan_diff(original, proposed, file)` |
| Wondering what you already read | `get_session_context(session_id)` |

### Tool quick-reference

```
get_context(file, symbol, depth=2)      → signature, callers, callees, types (< 400 tokens)
get_module_summary(file)                → purpose, public API, complexity (< 150 tokens)
get_impact(file, symbol)                → severity, dependents, affected tests
get_callers(file, function)             → every call site with line numbers
get_callees(file, function)             → every function this one calls
search_symbol(query, kind=None)         → find symbols by name substring
get_file_map(project_path)              → full file tree with role summaries
get_dependencies(file)                  → imports: internal vs external
scan_diff(original, proposed, file)     → security check before any write
record_read(session_id, file, symbol)   → log what you've already read
record_write(session_id, file, before, after) → log + security gate + graph sync
get_session_context(session_id)         → compact digest of session activity
undo_write(session_id, steps=1)         → roll back agent-authored writes
```

### Rules

1. **Always query the graph before reading files.** `get_context` returns callers,
   callees, and signature in under 400 tokens. Reading the whole file costs 10–100×
   more context for the same information.
2. **Only fall back to `Read`/`Grep` when graph data is provably insufficient** —
   e.g. you need the exact implementation body, not just the structure.
3. **Always call `scan_diff` before writing a file.** A `BLOCK` status means the
   proposed content contains a critical security issue — do not write it.
4. **Use `record_read` / `record_write` to track session state** so you never
   re-fetch context you already have.
<!-- /codeprism-instructions -->"""

_CURSORRULES_BLOCK = """\
# CodePrism — Knowledge Graph (auto-injected by `codeprism setup`)

This project is indexed with CodePrism. A live knowledge graph is available via MCP.

## Use CodePrism FIRST — before reading any source file

- `get_context(file, symbol, depth=2)` — signature, callers, callees in < 400 tokens
- `get_module_summary(file)` — understand a file's purpose without reading it
- `get_impact(file, symbol)` — blast radius of a change (severity + affected tests)
- `get_callers(file, function)` — every call site with line numbers
- `search_symbol(query)` — find symbols by name
- `scan_diff(original, proposed, file)` — security gate before every write
- `record_write(session_id, file, before, after)` — log + security scan + graph sync
- `get_session_context(session_id)` — what you've already read/written this session

## Rules
1. Query the graph before reading files. Graph = 10-100x fewer tokens for same info.
2. Only use file reads when you need the exact implementation body.
3. Always call `scan_diff` before writing. BLOCK status = do not write.
4. Use `record_read`/`record_write` to avoid redundant re-fetches."""


def _write_claude_config(server_entry: dict, global_: bool) -> None:
    import json

    if global_:
        config_dir = Path.home() / ".claude"
    else:
        config_dir = Path(".claude")

    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "settings.json"

    existing: dict = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    servers = existing.setdefault("mcpServers", {})
    servers["codeprism"] = server_entry
    config_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    # Write CLAUDE.md into the project directory (always local — not global)
    claude_md = Path("CLAUDE.md")
    _upsert_agent_instructions(claude_md, _CLAUDE_MD_BLOCK, _CODEPRISM_MARKER)

    scope = "global" if global_ else "project"
    console.print(
        f"[green]Done.[/green] CodePrism MCP server added to "
        f"[bold]{config_file}[/bold] ({scope})."
    )
    console.print(
        f"[green]Done.[/green] Usage instructions written to "
        f"[bold]{claude_md.resolve()}[/bold]."
    )
    console.print("[dim]Restart Claude Code to pick up the change.[/dim]")


def _write_cursor_config(server_entry: dict, global_: bool) -> None:
    import json

    if global_:
        config_dir = Path.home() / ".cursor"
    else:
        config_dir = Path(".cursor")

    config_dir.mkdir(parents=True, exist_ok=True)
    config_file = config_dir / "mcp.json"

    existing: dict = {}
    if config_file.exists():
        try:
            existing = json.loads(config_file.read_text(encoding="utf-8"))
        except Exception:
            pass

    servers = existing.setdefault("mcpServers", {})
    servers["codeprism"] = server_entry
    config_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

    # Write .cursorrules into the project directory
    cursorrules = Path(".cursorrules")
    _upsert_agent_instructions(cursorrules, _CURSORRULES_BLOCK, "# CodePrism")

    scope = "global" if global_ else "project"
    console.print(
        f"[green]Done.[/green] CodePrism MCP server added to "
        f"[bold]{config_file}[/bold] ({scope})."
    )
    console.print(
        f"[green]Done.[/green] Usage instructions written to "
        f"[bold]{cursorrules.resolve()}[/bold]."
    )
    console.print("[dim]Restart Cursor to pick up the change.[/dim]")


def _upsert_agent_instructions(file: Path, block: str, marker: str) -> None:
    """Insert or replace the CodePrism block inside an existing instructions file."""
    if not file.exists():
        file.write_text(block + "\n", encoding="utf-8")
        return

    existing = file.read_text(encoding="utf-8")
    if marker in existing:
        # Replace the old block between opening and closing marker
        import re
        pattern = re.compile(
            re.escape(marker) + r".*?" + re.escape(marker.replace("<!--", "<!--/")),
            re.DOTALL,
        )
        updated = pattern.sub(block, existing)
        if updated == existing:
            # Marker present but closing tag differs — just append updated block
            updated = existing.rstrip() + "\n\n" + block + "\n"
        file.write_text(updated, encoding="utf-8")
    else:
        # Append to the end of whatever is already there
        file.write_text(existing.rstrip() + "\n\n" + block + "\n", encoding="utf-8")


# ── visualize ─────────────────────────────────────────────────────────────────


@app.command()
def visualize(
    path: str = typer.Argument(..., help="Indexed project directory"),
    out: str = typer.Option("graph.html", "--out", "-o", help="Output HTML file"),
) -> None:
    """Generate a self-contained interactive graph visualization (opens in any browser)."""
    asyncio.run(_visualize(path, out))


async def _visualize(path: str, out: str) -> None:
    import json as _json

    from .core.graph import GraphEngine
    from .core.paths import get_db_path
    from .core.storage import StorageManager

    db_path = get_db_path(path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()
    await graph.load_from_storage(storage)
    await storage.close()

    raw = graph.to_json()
    nodes = raw["nodes"]
    edges = raw["edges"]

    _KIND = {
        "NodeKind.FILE": "file", "NodeKind.FUNCTION": "function",
        "NodeKind.CLASS": "class", "NodeKind.VARIABLE": "variable",
        "NodeKind.IMPORT": "import",
    }
    _EKIND = {
        "EdgeKind.CALLS": "calls", "EdgeKind.IMPORTS": "imports",
        "EdgeKind.INHERITS": "inherits", "EdgeKind.CONTAINS": "contains",
    }

    node_list = []
    for n in nodes:
        nd = dict(n)
        kind = _KIND.get(nd.get("kind", ""), nd.get("kind", ""))
        label = Path(nd["name"]).name if kind == "file" else nd.get("name", "")
        node_list.append({
            "id": nd["id"],
            "name": nd.get("name", ""),
            "label": label,
            "kind": kind,
            "file": nd.get("file", ""),
            "line": nd.get("line", 0),
        })

    link_list = []
    for e in edges:
        ed = dict(e)
        kind = _EKIND.get(ed.get("kind", ""), ed.get("kind", ""))
        link_list.append({
            "source": ed.get("source", ""),
            "target": ed.get("target", ""),
            "kind": kind,
        })

    graph_data = {"nodes": node_list, "links": link_list}
    data_json = _json.dumps(graph_data, separators=(",", ":")).replace("</", "<\\/")

    html = _VIZ_HTML_TEMPLATE.replace("__DATA__", data_json).replace(
        "__TITLE__", Path(path).name
    )
    out_path = Path(out)
    out_path.write_text(html, encoding="utf-8")

    console.print(f"[green]Visualization saved:[/green] [bold]{out_path.resolve()}[/bold]")
    console.print(f"[dim]{len(node_list)} nodes, {len(link_list)} edges. Open in any browser.[/dim]")
    if len(node_list) > 2000:
        console.print(
            "[yellow]Large graph (>2000 nodes) — 'Files' or 'Symbols' view recommended.[/yellow]"
        )


_VIZ_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>CodePrism — __TITLE__</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#02030f;overflow:hidden;font-family:'Segoe UI',system-ui,sans-serif;color:#b8c4dc}
/* ── toolbar ── */
#toolbar{
  position:fixed;top:0;left:0;right:0;z-index:30;
  display:flex;align-items:center;gap:10px;padding:10px 18px;
  background:linear-gradient(180deg,rgba(2,4,20,0.97) 0%,rgba(2,4,20,0.85) 100%);
  backdrop-filter:blur(20px);border-bottom:1px solid rgba(56,209,255,0.08)
}
#proj{
  font-weight:700;font-size:14px;letter-spacing:.04em;margin-right:8px;white-space:nowrap;
  background:linear-gradient(90deg,#38d1ff,#a855f7);-webkit-background-clip:text;
  -webkit-text-fill-color:transparent;background-clip:text
}
.vbtn{
  background:rgba(255,255,255,0.04);border:1px solid rgba(255,255,255,0.1);
  color:#667;padding:5px 16px;border-radius:999px;cursor:pointer;font-size:11px;
  letter-spacing:.02em;transition:all .2s;white-space:nowrap
}
.vbtn:hover{background:rgba(56,209,255,0.1);border-color:rgba(56,209,255,0.4);color:#38d1ff}
.vbtn.active{
  background:linear-gradient(135deg,rgba(56,209,255,0.18),rgba(168,85,247,0.18));
  border-color:rgba(56,209,255,0.6);color:#38d1ff;font-weight:600
}
#search{
  background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1);
  color:#bcc;padding:5px 13px;border-radius:999px;font-size:11px;width:160px;outline:none;
  transition:border-color .2s
}
#search::placeholder{color:#445}
#search:focus{border-color:rgba(56,209,255,0.5);background:rgba(56,209,255,0.04)}
.sep{width:1px;height:18px;background:rgba(255,255,255,0.08);flex-shrink:0}
#stats{font-size:10px;color:#445;white-space:nowrap}
#spinbtn{margin-left:auto}
/* ── detail panel ── */
#panel{
  position:fixed;right:0;top:0;bottom:0;width:230px;z-index:20;
  background:rgba(2,4,22,0.94);backdrop-filter:blur(20px);
  border-left:1px solid rgba(56,209,255,0.1);
  padding:58px 14px 14px;overflow-y:auto;
  transform:translateX(100%);transition:transform .25s cubic-bezier(.4,0,.2,1)
}
#panel.open{transform:translateX(0)}
#phdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px}
#phdr h3{
  font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.15em;
  color:#38d1ff
}
#pclose{
  cursor:pointer;color:#445;font-size:16px;line-height:1;padding:2px 4px;
  border-radius:4px;transition:all .15s
}
#pclose:hover{color:#38d1ff;background:rgba(56,209,255,0.1)}
.dr{
  font-size:11px;margin-bottom:8px;padding:6px 8px;
  background:rgba(255,255,255,0.03);border-radius:6px;border:1px solid rgba(255,255,255,0.04)
}
.dk{color:#445;font-size:10px;display:block;margin-bottom:2px;letter-spacing:.04em}
.dv{color:#bcc;word-break:break-all;line-height:1.4}
.pkind{
  display:inline-block;padding:2px 8px;border-radius:999px;font-size:10px;font-weight:600;
  letter-spacing:.04em;margin-top:2px
}
/* ── legend ── */
#legend{
  position:fixed;bottom:16px;left:16px;z-index:30;
  background:rgba(2,4,20,0.75);backdrop-filter:blur(12px);
  border:1px solid rgba(255,255,255,0.06);border-radius:10px;
  padding:10px 14px;display:flex;flex-direction:column;gap:7px
}
#legend-title{font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.12em;color:#334;margin-bottom:1px}
.li{display:flex;align-items:center;gap:8px;font-size:10px;color:#556}
.ld{width:8px;height:8px;border-radius:50%;flex-shrink:0}
/* ── edge legend ── */
#elegend{
  position:fixed;bottom:16px;left:160px;z-index:30;
  background:rgba(2,4,20,0.75);backdrop-filter:blur(12px);
  border:1px solid rgba(255,255,255,0.06);border-radius:10px;
  padding:10px 14px;display:flex;flex-direction:column;gap:7px
}
.el{display:flex;align-items:center;gap:8px;font-size:10px;color:#556}
.elc{width:18px;height:2px;border-radius:1px;flex-shrink:0}
#graph{width:100vw;height:100vh;display:block}
</style>
</head>
<body>
<div id="toolbar">
  <span id="proj">CodePrism</span>
  <div class="sep"></div>
  <button class="vbtn active" id="btn-files" onclick="setView('files')">Files</button>
  <button class="vbtn" id="btn-symbols" onclick="setView('symbols')">Symbols</button>
  <button class="vbtn" id="btn-all" onclick="setView('all')">All</button>
  <div class="sep"></div>
  <input id="search" placeholder="Search nodes..." oninput="doSearch(this.value)"/>
  <span id="stats"></span>
  <button class="vbtn" id="spinbtn" onclick="toggleSpin()">&#9654; Spin</button>
</div>
<div id="panel">
  <div id="phdr">
    <h3>Node Details</h3>
    <span id="pclose" onclick="closePanel()">&times;</span>
  </div>
  <div id="pbody"></div>
</div>
<div id="legend">
  <div id="legend-title">Nodes</div>
  <div class="li"><div class="ld" style="background:#00d4ff;box-shadow:0 0 6px #00d4ff88"></div>file</div>
  <div class="li"><div class="ld" style="background:#a855f7;box-shadow:0 0 6px #a855f788"></div>class</div>
  <div class="li"><div class="ld" style="background:#22c55e;box-shadow:0 0 6px #22c55e88"></div>function</div>
  <div class="li"><div class="ld" style="background:#f97316;box-shadow:0 0 6px #f9731688"></div>variable</div>
</div>
<div id="elegend">
  <div id="legend-title">Edges</div>
  <div class="el"><div class="elc" style="background:#f87171"></div>calls</div>
  <div class="el"><div class="elc" style="background:#38bdf8"></div>imports</div>
  <div class="el"><div class="elc" style="background:#c084fc"></div>inherits</div>
</div>
<div id="graph"></div>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph@1/dist/3d-force-graph.min.js"></script>
<script>
const RAW=__DATA__;

const NC={file:'#00d4ff',class:'#a855f7',function:'#22c55e',variable:'#f97316',import:'#1e2a3a'};
const NS={file:8,class:5,function:3,variable:2,import:1.5};
const KIND_COLOR={file:'#00d4ff',class:'#a855f7',function:'#22c55e',variable:'#f97316'};
// Edge colours — solid, fully opaque so they render visibly in 3D
const LC={calls:'#f87171',imports:'#38bdf8',inherits:'#c084fc',contains:'#1e2a3a'};
const PC={calls:'#ff4466',imports:'#00d4ff',inherits:'#c084fc'};

const nodeById={};
RAW.nodes.forEach(function(n){nodeById[n.id]=Object.assign({},n);});

var hiSet=new Set();

function nodeColor(n){
  if(hiSet.size&&!hiSet.has(n.id))return '#0d0d1e';
  return NC[n.kind]||'#4a5568';
}
function nodeVal(n){
  var base=NS[n.kind]||2;
  return hiSet.size&&hiSet.has(n.id)?base*3:base;
}

function viewData(view){
  var nOk,eOk;
  if(view==='files'){
    nOk=function(n){return n.kind==='file';};
    eOk=function(l){return l.kind==='imports';};
  }else if(view==='symbols'){
    nOk=function(n){return n.kind==='class'||n.kind==='function';};
    eOk=function(l){return l.kind==='calls'||l.kind==='inherits';};
  }else{
    nOk=function(){return true;};
    eOk=function(){return true;};
  }
  var ids=new Set();
  var nodes=RAW.nodes.filter(function(n){
    if(nOk(n)){ids.add(n.id);return true;}return false;
  }).map(function(n){return nodeById[n.id];});
  var links=RAW.links.filter(function(l){
    return eOk(l)&&ids.has(l.source)&&ids.has(l.target);
  }).map(function(l){return{source:l.source,target:l.target,kind:l.kind};});
  return{nodes:nodes,links:links};
}

var Graph,curView='files',spinning=true;

function initGraph(){
  Graph=ForceGraph3D()(document.getElementById('graph'))
    .backgroundColor('#02030f')
    .nodeId('id')
    .nodeLabel(function(n){
      return '<div style="background:rgba(2,4,22,0.92);border:1px solid rgba(56,209,255,0.25);border-radius:6px;padding:6px 10px;font-size:12px;color:#dde;max-width:220px">'
        +'<b style="color:'+(NC[n.kind]||'#aaa')+'">'+escHtml(n.label||n.name||'')+'</b>'
        +'<br><span style="color:#556;font-size:10px">'+n.kind+'</span></div>';
    })
    .nodeColor(nodeColor)
    .nodeVal(nodeVal)
    .nodeOpacity(0.92)
    .linkColor(function(l){return LC[l.kind]||'#1e2a3a';})
    .linkWidth(1.5)
    .linkOpacity(0.7)
    .linkDirectionalArrowLength(4)
    .linkDirectionalArrowRelPos(1)
    .linkDirectionalArrowColor(function(l){return LC[l.kind]||'#1e2a3a';})
    .linkDirectionalParticles(function(l){
      return l.kind==='calls'?4:l.kind==='imports'?3:l.kind==='inherits'?3:0;
    })
    .linkDirectionalParticleSpeed(0.006)
    .linkDirectionalParticleWidth(2.5)
    .linkDirectionalParticleColor(function(l){return PC[l.kind]||'#ffffff';})
    .onNodeClick(openPanel)
    .onBackgroundClick(closePanel);

  Graph.controls().autoRotate=true;
  Graph.controls().autoRotateSpeed=0.8;
  Graph.controls().addEventListener('start',function(){
    spinning=false;
    Graph.controls().autoRotate=false;
    document.getElementById('spinbtn').textContent='▶ Spin';
  });

  setView('files');
}

function escHtml(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function refreshAppearance(){
  Graph.nodeColor(nodeColor).nodeVal(nodeVal);
}

function setView(v){
  curView=v;hiSet.clear();
  document.getElementById('search').value='';
  ['files','symbols','all'].forEach(function(n){
    document.getElementById('btn-'+n).classList.toggle('active',n===v);
  });
  var d=viewData(v);
  Graph.graphData(d);
  var ec=d.links.length;
  document.getElementById('stats').textContent=d.nodes.length+' nodes · '+ec+' edges';
}

function doSearch(q){
  hiSet.clear();
  if(q.trim()){
    var ql=q.toLowerCase();
    Graph.graphData().nodes.forEach(function(n){
      if((n.label||n.name||'').toLowerCase().indexOf(ql)>=0)hiSet.add(n.id);
    });
  }
  refreshAppearance();
}

function toggleSpin(){
  spinning=!spinning;
  Graph.controls().autoRotate=spinning;
  document.getElementById('spinbtn').textContent=spinning?'⏸ Pause':'▶ Spin';
}

function openPanel(node){
  var kc=KIND_COLOR[node.kind]||'#667';
  document.getElementById('pbody').innerHTML=
    '<div class="dr"><span class="dk">NAME</span><span class="dv">'+escHtml(node.name||node.label||'')+'</span></div>'
    +'<div class="dr"><span class="dk">KIND</span><span class="pkind" style="background:'+kc+'22;color:'+kc+';border:1px solid '+kc+'44">'+escHtml(node.kind)+'</span></div>'
    +(node.file?'<div class="dr"><span class="dk">FILE</span><span class="dv">'+escHtml((node.file||'').split('/').pop().split('\\\\').pop())+'</span></div>':'')
    +(node.line?'<div class="dr"><span class="dk">LINE</span><span class="dv">'+node.line+'</span></div>':'');
  document.getElementById('panel').classList.add('open');
}
function closePanel(){document.getElementById('panel').classList.remove('open');}

initGraph();
</script>
</body>
</html>"""


# ── scan ──────────────────────────────────────────────────────────────────────


@app.command()
def scan(
    target: str = typer.Argument(..., help="File path to scan"),
    all_: bool = typer.Option(False, "--all", "-a", help="Scan all indexed files"),
    diff: Optional[str] = typer.Option(
        None, "--diff",
        help="Git diff range to scan, e.g. HEAD~1..HEAD or main..feature",
    ),
    project: str = typer.Option(".", "--project", "-p", help="Project path (for --all)"),
) -> None:
    """Run security detectors on a file (or all indexed files with --all).

    Examples:
        codeprism scan payments/processor.py
        codeprism scan --all --project /path/to/repo
        codeprism scan . --diff HEAD~1..HEAD
    """
    asyncio.run(_scan(target, all_, diff, project))


async def _scan(target: str, all_: bool, diff: Optional[str], project: str) -> None:
    from .security.scanner import SecurityScanner

    scanner = SecurityScanner()

    if diff:
        await _scan_git_diff(diff, scanner)
        return

    if all_:
        engine, storage = await _open_session(project)
        try:
            stats = await engine.get_stats()
            fm = await engine.get_file_map(project)
        finally:
            await storage.close()

        total_issues = 0
        for entry in fm.entries:
            try:
                content = Path(entry.path).read_text(encoding="utf-8")
            except Exception:
                continue
            report = scanner.scan_content(content, entry.path)
            if report.issues:
                total_issues += len(report.issues)
                _print_scan_report(report, entry.path)

        console.print(
            f"\n[bold]Scan complete.[/bold] "
            f"{len(fm.entries)} files · {total_issues} issue(s) found."
        )
        return

    # Single file scan
    try:
        content = Path(target).read_text(encoding="utf-8")
    except FileNotFoundError:
        console.print(f"[red]File not found:[/red] {target}")
        raise typer.Exit(1)

    report = scanner.scan_content(content, target)
    _print_scan_report(report, target)

    if report.is_blocked:
        raise typer.Exit(2)


async def _scan_git_diff(diff_range: str, scanner) -> None:
    """Scan only the files changed in a git diff range (e.g. HEAD~1..HEAD)."""
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", diff_range],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        console.print(f"[red]git diff failed:[/red] {exc.stderr.strip()}")
        raise typer.Exit(1)

    changed_files = [f.strip() for f in proc.stdout.splitlines() if f.strip()]
    if not changed_files:
        console.print(f"[dim]No changed files in {diff_range}[/dim]")
        return

    console.print(f"Scanning [bold]{len(changed_files)}[/bold] changed file(s) in [bold]{diff_range}[/bold]")

    total_issues = 0
    blocked = False
    for rel_path in changed_files:
        fp = Path(rel_path)
        if not fp.exists():
            continue
        try:
            after_content = fp.read_text(encoding="utf-8")
        except Exception:
            continue

        # Retrieve the content before the diff so we only report new issues.
        before_ref = diff_range.split("..")[0] if ".." in diff_range else diff_range + "~1"
        try:
            before_proc = subprocess.run(
                ["git", "show", f"{before_ref}:{rel_path}"],
                capture_output=True,
                text=True,
            )
            before_content = before_proc.stdout if before_proc.returncode == 0 else ""
        except Exception:
            before_content = ""

        report = scanner.scan_diff(before_content, after_content, str(fp))
        if report.issues:
            total_issues += len(report.issues)
            _print_scan_report(report, str(fp))
            if report.is_blocked:
                blocked = True

    console.print(
        f"\n[bold]Diff scan complete.[/bold] "
        f"{len(changed_files)} files · {total_issues} new issue(s)."
    )
    if blocked:
        raise typer.Exit(2)


def _print_scan_report(report, file_path: str) -> None:
    from rich.table import Table

    severity_colour = {"BLOCK": "bright_red", "WARN": "yellow", "INFO": "blue"}
    status_colour = {"BLOCK": "bright_red", "WARN": "yellow", "PASS": "green"}
    colour = status_colour.get(report.status, "white")

    console.print(
        f"\n[bold]{Path(file_path).name}[/bold]  "
        f"[{colour}]{report.status}[/{colour}]  "
        f"({len(report.issues)} issue(s))"
    )

    if not report.issues:
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Line", justify="right", width=6)
    table.add_column("Sev", width=7)
    table.add_column("Category", width=14)
    table.add_column("Description")

    for issue in report.issues:
        sev_col = severity_colour.get(issue.severity, "white")
        table.add_row(
            str(issue.line_number or ""),
            f"[{sev_col}]{issue.severity}[/{sev_col}]",
            issue.category,
            issue.description,
        )
    console.print(table)
