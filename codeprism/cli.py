"""CodePrism CLI — typer-based entry point."""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

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
    languages: str | None = typer.Option(
        None, "--languages", "-l",
        help="Comma-separated language list (default: python,javascript,typescript,go)"
    ),
    embeddings: bool = typer.Option(
        False, "--embeddings", "-e",
        help="Also build semantic vector index (requires codeprism[embeddings])"
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="Re-parse all files even if unchanged (skip incremental check)"
    ),
) -> None:
    """Build the knowledge graph for a project directory.

    Re-runs are incremental by default: only changed or new files are parsed.
    Use --force to re-parse everything from scratch.
    """
    asyncio.run(_index(path, languages, embeddings, force))


async def _index(
    path: str,
    languages: str | None,
    embeddings: bool = False,
    force: bool = False,
) -> None:
    from .core.config import CodePrismConfig
    from .core.graph import GraphEngine
    from .core.paths import get_db_path
    from .core.storage import StorageManager
    from .indexer.project_indexer import ProjectIndexer

    langs = [lang.strip() for lang in languages.split(",")] if languages else None
    config = CodePrismConfig(languages=langs, enable_embeddings=embeddings) if langs \
        else CodePrismConfig(enable_embeddings=embeddings)

    db_path = get_db_path(path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()

    mode = "[dim](full re-index)[/dim]" if force else "[dim](incremental)[/dim]"
    console.print(f"Indexing [bold]{path}[/bold] {mode}")
    if embeddings:
        console.print("[dim]Embeddings enabled — will build vector index after parsing...[/dim]")
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(path, force=force)
    await storage.close()

    if result.success:
        skipped_note = (
            f" · [dim]{result.files_skipped} unchanged[/dim]"
            if result.files_skipped else ""
        )
        console.print(
            f"[green]Done.[/green] "
            f"{result.file_count} files · {result.symbol_count} symbols · "
            f"{result.edge_count} edges · {result.duration_seconds:.2f}s"
            f"{skipped_note}"
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
    kind: str | None = typer.Option(None, "--kind", "-k", help="function|class|variable"),
    project: str = typer.Option(".", "--project", "-p", help="Project path"),
) -> None:
    """Find symbols matching a query string."""
    asyncio.run(_search(query, kind, project))


async def _search(query: str, kind: str | None, project: str) -> None:
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
*,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
:root{
  --bg:#020818;--surface:rgba(6,12,32,0.94);--border:rgba(255,255,255,0.07);
  --text:#e2e8f0;--dim:#475569;--dim2:#334155;
  --cyan:#22d3ee;--violet:#a78bfa;--green:#4ade80;--orange:#fb923c;
  --red:#f87171;--blue:#60a5fa;--purple:#c084fc;
}
html,body{height:100%;overflow:hidden}
body{
  background:var(--bg);
  font-family:'Segoe UI',system-ui,-apple-system,BlinkMacSystemFont,sans-serif;
  color:var(--text);font-size:13px;line-height:1.5;
}
body::before{
  content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(ellipse 70% 50% at 15% 65%,rgba(34,211,238,.055) 0%,transparent 100%),
    radial-gradient(ellipse 60% 45% at 85% 20%,rgba(167,139,250,.055) 0%,transparent 100%),
    radial-gradient(ellipse 40% 35% at 60% 85%,rgba(74,222,128,.025) 0%,transparent 100%);
}
#tb{
  position:fixed;top:0;left:0;right:0;z-index:50;height:50px;
  display:flex;align-items:center;gap:10px;padding:0 18px;
  background:rgba(2,8,24,0.88);backdrop-filter:blur(24px) saturate(160%);
  border-bottom:1px solid var(--border);
  box-shadow:0 1px 0 rgba(34,211,238,.07),0 4px 32px rgba(0,0,0,.5);
}
.tdiv{width:1px;height:22px;background:var(--border);flex-shrink:0;margin:0 2px}
#logo{display:flex;align-items:center;gap:9px;flex-shrink:0;margin-right:2px}
#logo-mark{
  width:30px;height:30px;border-radius:8px;flex-shrink:0;
  background:linear-gradient(135deg,var(--cyan) 0%,var(--violet) 100%);
  display:flex;align-items:center;justify-content:center;
  font-weight:900;font-size:13px;color:#fff;letter-spacing:-.5px;
  box-shadow:0 0 14px rgba(34,211,238,.35),0 2px 8px rgba(0,0,0,.4);
}
#logo-name{
  font-weight:700;font-size:14px;letter-spacing:.02em;
  background:linear-gradient(90deg,var(--cyan),var(--violet));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
}
#proj-name{font-size:11px;color:var(--dim);font-weight:400;flex-shrink:0}
#views{
  display:flex;gap:2px;padding:3px;
  background:rgba(255,255,255,.04);border:1px solid var(--border);border-radius:999px;
}
.seg{
  border:none;border-radius:999px;padding:4px 13px;cursor:pointer;
  font-size:11px;font-weight:500;letter-spacing:.02em;color:var(--dim);
  background:transparent;transition:all .2s;
  display:flex;align-items:center;gap:5px;font-family:inherit;
}
.seg:hover{color:var(--cyan);background:rgba(34,211,238,.07)}
.seg.active{
  color:#fff;font-weight:600;
  background:linear-gradient(135deg,rgba(34,211,238,.18),rgba(167,139,250,.18));
  box-shadow:0 0 0 1px rgba(34,211,238,.45),0 2px 12px rgba(34,211,238,.12);
}
.badge{
  font-size:9px;font-weight:700;letter-spacing:.01em;
  padding:1px 6px;border-radius:999px;min-width:22px;text-align:center;
  background:rgba(255,255,255,.06);color:var(--dim);font-variant-numeric:tabular-nums;
}
.seg.active .badge{background:rgba(34,211,238,.18);color:var(--cyan)}
#sw{position:relative;flex-shrink:0}
#si{position:absolute;left:11px;top:50%;transform:translateY(-50%);color:var(--dim);font-size:12px;pointer-events:none}
#search{
  background:rgba(255,255,255,.04);border:1px solid var(--border);
  color:var(--text);padding:5px 10px 5px 30px;
  border-radius:999px;font-size:11px;width:175px;outline:none;font-family:inherit;
  transition:all .22s;
}
#search::placeholder{color:var(--dim2)}
#search:focus{
  border-color:rgba(34,211,238,.45);background:rgba(34,211,238,.04);
  width:210px;box-shadow:0 0 0 3px rgba(34,211,238,.08);
}
#stats{
  font-size:10px;color:var(--dim);white-space:nowrap;
  padding:3px 10px;border-radius:999px;border:1px solid var(--border);
  background:rgba(255,255,255,.02);font-variant-numeric:tabular-nums;
}
#spin-btn{
  margin-left:auto;display:flex;align-items:center;gap:7px;
  cursor:pointer;padding:5px 13px;border-radius:999px;
  border:1px solid var(--border);background:rgba(255,255,255,.03);
  transition:all .22s;user-select:none;flex-shrink:0;
}
#spin-btn:hover{border-color:rgba(34,211,238,.35);background:rgba(34,211,238,.07)}
#spin-btn.on{border-color:rgba(34,211,238,.55);background:rgba(34,211,238,.1)}
#spin-pip{
  width:7px;height:7px;border-radius:50%;
  background:var(--dim2);transition:all .3s;flex-shrink:0;
}
#spin-btn.on #spin-pip{
  background:var(--cyan);
  box-shadow:0 0 7px var(--cyan),0 0 14px rgba(34,211,238,.4);
  animation:pip-pulse 1.8s ease-in-out infinite;
}
@keyframes pip-pulse{0%,100%{opacity:1}50%{opacity:.45}}
#spin-lbl{font-size:11px;color:var(--dim);font-weight:500;transition:color .2s}
#spin-btn.on #spin-lbl{color:var(--cyan)}
#panel{
  position:fixed;right:0;top:0;bottom:0;width:265px;z-index:45;
  background:rgba(3,8,24,0.97);backdrop-filter:blur(28px) saturate(150%);
  border-left:1px solid var(--border);
  display:flex;flex-direction:column;
  transform:translateX(100%);transition:transform .28s cubic-bezier(.4,0,.2,1);
  box-shadow:-12px 0 40px rgba(0,0,0,.5);
}
#panel.open{transform:translateX(0)}
#ph{
  padding:56px 16px 16px;border-bottom:1px solid var(--border);
  position:relative;flex-shrink:0;
}
#pclose{
  position:absolute;top:12px;right:12px;cursor:pointer;
  width:26px;height:26px;display:flex;align-items:center;justify-content:center;
  border-radius:7px;color:var(--dim);font-size:16px;
  border:1px solid transparent;transition:all .15s;
}
#pclose:hover{color:var(--cyan);background:rgba(34,211,238,.1);border-color:rgba(34,211,238,.25)}
#p-chip{
  display:inline-flex;align-items:center;gap:5px;
  padding:3px 10px;border-radius:999px;font-size:9px;font-weight:700;
  letter-spacing:.1em;text-transform:uppercase;margin-bottom:10px;
}
#p-chip-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
#p-name{font-size:15px;font-weight:700;color:var(--text);line-height:1.3;word-break:break-word}
#pb{padding:14px 16px;overflow-y:auto;flex:1}
.pr{
  margin-bottom:9px;padding:9px 11px;border-radius:9px;
  background:rgba(255,255,255,.03);border:1px solid rgba(255,255,255,.05);
  transition:background .15s;
}
.pr:hover{background:rgba(255,255,255,.05)}
.pk{font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.1em;color:var(--dim);margin-bottom:3px}
.pv{font-size:11px;color:#cbd5e1;line-height:1.4;word-break:break-all}
.pv.mono{font-family:'Cascadia Code','Fira Code',Consolas,monospace;font-size:10.5px}
#legend{
  position:fixed;bottom:16px;left:16px;z-index:45;
  background:rgba(3,8,24,0.88);backdrop-filter:blur(20px);
  border:1px solid var(--border);border-radius:12px;padding:13px 15px;
  box-shadow:0 8px 32px rgba(0,0,0,.4);
}
.lg-hd{font-size:8px;font-weight:700;text-transform:uppercase;letter-spacing:.14em;color:var(--dim2);margin-bottom:8px}
.lg-r{display:flex;align-items:center;gap:8px;font-size:10px;color:var(--dim);margin-bottom:6px}
.lg-r:last-child{margin-bottom:0}
.lg-dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.lg-line{width:20px;height:2px;border-radius:1px;flex-shrink:0}
.lg-sep{height:1px;background:var(--border);margin:10px 0 9px}
#graph{width:100vw;height:100vh;display:block}
</style>
</head>
<body>
<div id="tb">
  <div id="logo">
    <div id="logo-mark">CP</div>
    <span id="logo-name">CodePrism</span>
  </div>
  <div class="tdiv"></div>
  <span id="proj-name">__TITLE__</span>
  <div class="tdiv"></div>
  <div id="views">
    <button class="seg active" id="btn-files" onclick="setView('files')">Files<span class="badge" id="b-files">—</span></button>
    <button class="seg" id="btn-symbols" onclick="setView('symbols')">Symbols<span class="badge" id="b-symbols">—</span></button>
    <button class="seg" id="btn-all" onclick="setView('all')">All<span class="badge" id="b-all">—</span></button>
  </div>
  <div id="sw"><span id="si">&#x2315;</span><input id="search" placeholder="Search nodes..." oninput="doSearch(this.value)"/></div>
  <span id="stats">loading...</span>
  <div id="spin-btn" class="on" onclick="toggleSpin()">
    <div id="spin-pip"></div><span id="spin-lbl">Spinning</span>
  </div>
</div>
<div id="panel">
  <div id="ph">
    <span id="pclose" onclick="closePanel()">&times;</span>
    <div id="p-chip"><div id="p-chip-dot"></div><span id="p-chip-txt"></span></div>
    <div id="p-name"></div>
  </div>
  <div id="pb"></div>
</div>
<div id="legend">
  <div class="lg-hd">Nodes</div>
  <div class="lg-r"><div class="lg-dot" style="background:#22d3ee;box-shadow:0 0 6px rgba(34,211,238,.6)"></div>File</div>
  <div class="lg-r"><div class="lg-dot" style="background:#a78bfa;box-shadow:0 0 6px rgba(167,139,250,.6)"></div>Class</div>
  <div class="lg-r"><div class="lg-dot" style="background:#4ade80;box-shadow:0 0 6px rgba(74,222,128,.6)"></div>Function</div>
  <div class="lg-r"><div class="lg-dot" style="background:#fb923c;box-shadow:0 0 6px rgba(251,146,60,.6)"></div>Variable</div>
  <div class="lg-sep"></div>
  <div class="lg-hd">Edges</div>
  <div class="lg-r"><div class="lg-line" style="background:#f87171"></div>calls</div>
  <div class="lg-r"><div class="lg-line" style="background:#60a5fa"></div>imports</div>
  <div class="lg-r"><div class="lg-line" style="background:#c084fc"></div>inherits</div>
</div>
<div id="graph"></div>
<script src="https://cdn.jsdelivr.net/npm/3d-force-graph@1/dist/3d-force-graph.min.js"></script>
<script>
var RAW=__DATA__;

var NC={file:'#22d3ee',class:'#a78bfa',function:'#4ade80',variable:'#fb923c',import:'#1e293b'};
var NS={file:8,class:5,function:2.5,variable:2,import:1.2};
var LC={calls:'#f87171',imports:'#60a5fa',inherits:'#c084fc',contains:'#1e293b'};
var PC={calls:'#ff6080',imports:'#22d3ee',inherits:'#c084fc'};

var nodeById={};
RAW.nodes.forEach(function(n){nodeById[n.id]=Object.assign({},n);});

var fCt=RAW.nodes.filter(function(n){return n.kind==='file';}).length;
var sCt=RAW.nodes.filter(function(n){return n.kind==='class'||n.kind==='function';}).length;
var aCt=RAW.nodes.length;
function fmt(n){return n>999?(n/1000).toFixed(1)+'k':String(n);}
document.getElementById('b-files').textContent=fmt(fCt);
document.getElementById('b-symbols').textContent=fmt(sCt);
document.getElementById('b-all').textContent=fmt(aCt);

var hiSet=new Set();
function nc(n){if(hiSet.size&&!hiSet.has(n.id))return '#0c1122';return NC[n.kind]||'#334155';}
function nv(n){var b=NS[n.kind]||2;return hiSet.size&&hiSet.has(n.id)?b*3:b;}

function viewData(view){
  var nOk,eOk;
  if(view==='files'){
    nOk=function(n){return n.kind==='file';};
    eOk=function(l){return l.kind==='imports';};
  }else if(view==='symbols'){
    nOk=function(n){return n.kind==='class'||n.kind==='function';};
    eOk=function(l){return l.kind==='calls'||l.kind==='inherits';};
  }else{nOk=function(){return true;};eOk=function(){return true;};}
  var ids=new Set();
  var nodes=RAW.nodes.filter(function(n){if(nOk(n)){ids.add(n.id);return true;}return false;})
    .map(function(n){return nodeById[n.id];});
  var links=RAW.links.filter(function(l){return eOk(l)&&ids.has(l.source)&&ids.has(l.target);})
    .map(function(l){return{source:l.source,target:l.target,kind:l.kind};});
  return{nodes:nodes,links:links};
}

var Graph,curView='files',spinning=true,spinRAF=null,spinAngle=0;

function spinFrame(){
  if(!spinning){spinRAF=null;return;}
  spinAngle+=0.003;
  var p=Graph.camera().position;
  var r=Math.sqrt(p.x*p.x+p.z*p.z);
  if(r<10)r=400;
  Graph.cameraPosition({x:r*Math.sin(spinAngle),z:r*Math.cos(spinAngle)});
  spinRAF=requestAnimationFrame(spinFrame);
}

function setSpin(on){
  spinning=on;
  var btn=document.getElementById('spin-btn');
  var lbl=document.getElementById('spin-lbl');
  if(on){
    btn.classList.add('on');lbl.textContent='Spinning';
    var p=Graph.camera().position;
    spinAngle=Math.atan2(p.x,p.z);
    if(!spinRAF)spinFrame();
  }else{
    btn.classList.remove('on');lbl.textContent='Paused';
  }
}
function toggleSpin(){setSpin(!spinning);}

function initGraph(){
  Graph=ForceGraph3D()(document.getElementById('graph'))
    .backgroundColor('#020818')
    .nodeId('id')
    .nodeLabel(function(n){
      var c=NC[n.kind]||'#94a3b8';
      return '<div style="background:rgba(3,8,28,0.96);border:1px solid rgba(255,255,255,0.1);border-left:3px solid '+c+';border-radius:0 8px 8px 0;padding:8px 12px;min-width:140px;box-shadow:0 8px 32px rgba(0,0,0,.6)">'
        +'<div style="font-size:12px;font-weight:700;color:'+c+';margin-bottom:3px">'+esc(n.label||n.name||'')+'</div>'
        +'<div style="font-size:10px;color:#475569;text-transform:uppercase;letter-spacing:.06em">'+esc(n.kind)+'</div>'
        +'</div>';
    })
    .nodeColor(nc).nodeVal(nv).nodeOpacity(0.92)
    .linkColor(function(l){return LC[l.kind]||'#1e293b';})
    .linkWidth(1.5).linkOpacity(0.75)
    .linkDirectionalArrowLength(5).linkDirectionalArrowRelPos(1)
    .linkDirectionalArrowColor(function(l){return LC[l.kind]||'#1e293b';})
    .linkDirectionalParticles(function(l){
      return l.kind==='calls'?5:l.kind==='imports'?3:l.kind==='inherits'?3:0;
    })
    .linkDirectionalParticleSpeed(0.006)
    .linkDirectionalParticleWidth(2.5)
    .linkDirectionalParticleColor(function(l){return PC[l.kind]||'#fff';})
    .onNodeClick(openPanel)
    .onBackgroundClick(closePanel);

  Graph.d3Force('charge').strength(-120);
  Graph.d3Force('link').distance(40);

  setView('files');
  // Start spin after two frames so camera is positioned
  requestAnimationFrame(function(){requestAnimationFrame(function(){setSpin(true);});});
}

function setView(v){
  curView=v;hiSet.clear();
  document.getElementById('search').value='';
  ['files','symbols','all'].forEach(function(n){
    document.getElementById('btn-'+n).classList.toggle('active',n===v);
  });
  var d=viewData(v);
  Graph.graphData(d);
  document.getElementById('stats').textContent=d.nodes.length+' nodes  ·  '+d.links.length+' edges';
}

function doSearch(q){
  hiSet.clear();
  if(q.trim()){
    var ql=q.toLowerCase();
    Graph.graphData().nodes.forEach(function(n){
      if((n.label||n.name||'').toLowerCase().indexOf(ql)>=0)hiSet.add(n.id);
    });
  }
  Graph.nodeColor(nc).nodeVal(nv);
}

function openPanel(node){
  var c=NC[node.kind]||'#64748b';
  var dot=document.getElementById('p-chip-dot');
  dot.style.background=c;dot.style.boxShadow='0 0 6px '+c;
  document.getElementById('p-chip-txt').textContent=node.kind.toUpperCase();
  var chip=document.getElementById('p-chip');
  chip.style.cssText='display:inline-flex;align-items:center;gap:5px;padding:3px 10px;'
    +'border-radius:999px;font-size:9px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;'
    +'margin-bottom:10px;background:'+c+'1a;color:'+c+';border:1px solid '+c+'44';
  document.getElementById('p-name').textContent=node.name||node.label||'';
  var rows='';
  if(node.file){
    var short=(node.file||'').split('/').pop().split('\\\\').pop()||node.file;
    rows+='<div class="pr"><div class="pk">File</div><div class="pv mono">'+esc(short)+'</div></div>';
  }
  if(node.line)rows+='<div class="pr"><div class="pk">Line</div><div class="pv mono">'+node.line+'</div></div>';
  if(node.name&&node.name!==node.label)
    rows+='<div class="pr"><div class="pk">Full name</div><div class="pv mono">'+esc(node.name)+'</div></div>';
  document.getElementById('pb').innerHTML=rows||
    '<div style="color:var(--dim2);font-size:11px;text-align:center;padding:20px 0">No additional info</div>';
  document.getElementById('panel').classList.add('open');
}
function closePanel(){document.getElementById('panel').classList.remove('open');}

function esc(s){return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

initGraph();
</script>
</body>
</html>"""


# ── scan ──────────────────────────────────────────────────────────────────────


@app.command()
def scan(
    target: str = typer.Argument(..., help="File path to scan"),
    all_: bool = typer.Option(False, "--all", "-a", help="Scan all indexed files"),
    diff: str | None = typer.Option(
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


async def _scan(target: str, all_: bool, diff: str | None, project: str) -> None:
    from .security.scanner import SecurityScanner

    scanner = SecurityScanner()

    if diff:
        await _scan_git_diff(diff, scanner)
        return

    if all_:
        engine, storage = await _open_session(project)
        try:
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
        raise typer.Exit(1) from None

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
        raise typer.Exit(1) from exc

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
