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
) -> None:
    """Build the knowledge graph for a project directory."""
    asyncio.run(_index(path, languages))


async def _index(path: str, languages: Optional[str]) -> None:
    from .core.config import CodePrismConfig
    from .core.graph import GraphEngine
    from .core.paths import get_db_path
    from .core.storage import StorageManager
    from .indexer.project_indexer import ProjectIndexer

    langs = [l.strip() for l in languages.split(",")] if languages else None
    config = CodePrismConfig(languages=langs) if langs else CodePrismConfig()

    db_path = get_db_path(path)
    storage = StorageManager(db_path)
    await storage.initialize()
    graph = GraphEngine()

    console.print(f"Indexing [bold]{path}[/bold] ...")
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(path)
    await storage.close()

    if result.success:
        console.print(
            f"[green]Done.[/green] "
            f"{result.file_count} files · {result.symbol_count} symbols · "
            f"{result.edge_count} edges · {result.duration_seconds:.2f}s"
        )
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
) -> None:
    """Show knowledge graph statistics."""
    asyncio.run(_stats(project, verbose))


async def _stats(project: str, verbose: bool) -> None:
    engine, storage = await _open_session(project)
    try:
        data = await engine.get_stats()
        file_map = await engine.get_file_map(project) if verbose else None
    finally:
        await storage.close()

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

    scope = "global" if global_ else "project"
    console.print(
        f"[green]Done.[/green] CodePrism MCP server added to "
        f"[bold]{config_file}[/bold] ({scope}).\n"
        f"Restart Claude Code to pick up the change."
    )


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

    scope = "global" if global_ else "project"
    console.print(
        f"[green]Done.[/green] CodePrism MCP server added to "
        f"[bold]{config_file}[/bold] ({scope}).\n"
        f"Restart Cursor to pick up the change."
    )


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
