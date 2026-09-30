# CodePrism Integrations

How to connect CodePrism to AI coding agents, editors, and automated pipelines.

CodePrism speaks [Model Context Protocol (MCP)](https://modelcontextprotocol.io) — the open standard adopted by every major AI editor. If your tool supports MCP, CodePrism works with it. The server runs locally via **stdio** (default) or via **SSE**, which listens on `127.0.0.1` only.

---

## Table of Contents

1. [Claude Code](#claude-code)
2. [Codex (OpenAI)](#codex-openai)
3. [Cursor](#cursor)
4. [Windsurf](#windsurf)
5. [Continue.dev](#continuedev)
6. [Zed](#zed)
7. [VS Code with GitHub Copilot](#vs-code-with-github-copilot)
8. [Cody (Sourcegraph)](#cody-sourcegraph)
9. [Aider](#aider)
10. [Remote / SSE](#remote--sse)
11. [Python library (embed directly)](#python-library-embed-directly)
12. [OpenAI Agents SDK](#openai-agents-sdk)
13. [CI/CD (GitHub Actions)](#cicd-github-actions)
14. [Pre-commit hook](#pre-commit-hook)

---

## Agent instructions: AGENTS.md first

Every `codeprism setup <agent>` writes the CodePrism usage guide to **`AGENTS.md`** in the
project root. [AGENTS.md](https://agents.md/) is the cross-tool standard, read natively by
Codex, Cursor, Windsurf, Zed, GitHub Copilot and many others, so the guide lives in one place.
Setup only adds or updates the block between `<!-- codeprism-instructions -->` markers; the
rest of your file is left alone.

- **Claude Code** also gets a thin `CLAUDE.md` containing `@AGENTS.md`. Claude Code reads
  `AGENTS.md` by itself only when no `CLAUDE.md` exists, so the import keeps both working.
- **Continue.dev** doesn't read `AGENTS.md` yet, so it gets `.continue/rules/codeprism.md`.

---

## Claude Code

The fastest path: one command wires everything up, and the server indexes each project itself.

```bash
# Every project on this machine (user scope, ~/.claude.json)
codeprism setup claude --global

# Or just one project (.mcp.json in the project)
codeprism setup claude --project /path/to/project
```

You don't need to run `codeprism index`: when the server starts it builds the index in the
background (first time) or refreshes it (later), and `get_graph_stats` reports `index_status`.

`codeprism setup claude` (without `--global`) writes, inside the `--project` directory:

- **`.mcp.json`**: the project-scoped MCP server entry. Commit it so teammates get CodePrism too.
- **`.claude/settings.local.json`**: pre-approves the `codeprism` server for you (`enabledMcpjsonServers`), so Claude Code doesn't prompt. This file is personal; don't commit it.
- **`AGENTS.md`**: the CodePrism usage guide, shared by every coding agent.
- **`CLAUDE.md`**: a thin file that imports `@AGENTS.md`, so Claude Code loads the same guide.

> Claude Code reads MCP servers from `.mcp.json` (project scope) or `~/.claude.json` (user scope), **not** from `.claude/settings.json`. Older CodePrism versions wrote to `settings.json`; re-running setup moves the entry.

**Manual config** (if you prefer to edit directly):

```json
// <project>/.mcp.json
{
  "mcpServers": {
    "codeprism": {
      "type": "stdio",
      "command": "codeprism",
      "args": ["serve", "/absolute/path/to/project"]
    }
  }
}
```

Or run `claude mcp add --scope project codeprism -- codeprism serve /absolute/path/to/project`.

Restart Claude Code after any config change, then run `/mcp` to check that `codeprism` shows as connected.

**User scope, all projects** (written to `~/.claude.json`):

```bash
codeprism setup claude --global
```

The user-scope entry is a path-less `codeprism serve`. Claude Code starts MCP servers in the
directory you launch it from, and `codeprism serve` without a path serves the project
containing that directory (the nearest `.git` or `.codeprism.toml`). So one entry covers every
repo. The first time you open a project, the server builds its index in the background, and
refreshes it incrementally on later sessions. `get_graph_stats` reports `index_status`
(`indexing` / `ready`). Outside a project (for example from your home folder) nothing is
indexed. Pass `--no-auto-index` to `serve` to turn background indexing off, or set
`auto_index = false` in `.codeprism.toml`.

`--global` only changes where the server entry goes (`~/.claude.json`). `AGENTS.md` and `CLAUDE.md` are still
written into the `--project` directory (default: the current one).

**What Claude can now do** — without reading any files:

```
get_context("payments/processor.py", "charge_card", depth=2)
get_impact("utils/auth.py", "verify_token")
scan_diff(original, proposed, "auth/login.py")
search_symbol("handle payment", kind="function")
```

---

## Codex (OpenAI)

```bash
codeprism setup codex --global                  # every project
codeprism setup codex --project /path/to/project   # one project
```

`codeprism setup codex` writes:

- **`.codex/config.toml`** in the project: a `[mcp_servers.codeprism]` table. Codex only loads
  project config in **trusted** projects, so accept the trust prompt the first time you run
  Codex there. Other settings and comments in the file are preserved.
- **`AGENTS.md`**: the CodePrism usage guide, which Codex reads at the start of every session.

Use `--global` to write `~/.codex/config.toml` instead: a path-less `codeprism serve` that
serves whichever project Codex is started in, with no trust prompt needed (see the Claude Code
section above for how project detection and background indexing work).

**Manual config:**

```toml
# ~/.codex/config.toml  or  <project>/.codex/config.toml
[mcp_servers.codeprism]
command = "codeprism"
args = ["serve", "/absolute/path/to/project"]
```

Or run `codex mcp add codeprism -- codeprism serve /absolute/path/to/project`.

Start a new Codex session and run `/mcp` (or `codex mcp list`) to check that `codeprism` is listed.
The same config is shared by the Codex CLI, IDE extension and desktop app.

---

## Cursor

```bash
codeprism setup cursor --project /path/to/project
# Restart Cursor
```

Cursor entries are tied to one project path, so run setup for each project. The server indexes
the project itself when it starts.

Setup writes `.cursor/mcp.json` and the shared `AGENTS.md` guide, which Cursor reads natively.

**Manual config:**

Create or edit `.cursor/mcp.json` (project-local) or `~/.cursor/mcp.json` (global):

```json
{
  "mcpServers": {
    "codeprism": {
      "command": "codeprism",
      "args": ["serve", "/absolute/path/to/project"]
    }
  }
}
```

After restarting Cursor, go to **Settings → MCP** to verify the server is listed. All Cursor Composer and Cursor Chat sessions automatically get access to the graph tools.

**Cursor Agent mode**: In Composer with Agent mode enabled, Cursor will call `get_context` and `get_impact` autonomously as it reasons about changes — no extra prompting needed.

---

## Windsurf

Windsurf reads MCP servers from a user-level `mcp_config.json`. Per the
[current Windsurf docs](https://docs.devin.ai/desktop/cascade/mcp) the file is:

- **macOS / Linux:** `~/.config/devin/mcp_config.json` (or `$XDG_CONFIG_HOME/devin/mcp_config.json`)
- **Windows:** `%APPDATA%\devin\mcp_config.json`

Older Windsurf releases used `~/.codeium/windsurf/mcp_config.json`. Check which one your version
reads (Cascade → MCP settings opens it).

```json
{
  "mcpServers": {
    "codeprism": {
      "command": "codeprism",
      "args": ["serve", "/absolute/path/to/project"],
      "env": {}
    }
  }
}
```

Restart Windsurf. The server appears in Cascade's MCP tools. The Windsurf docs don't describe a
project-level config file, so use one entry per project in the user-level file.

> `codeprism setup windsurf` writes `.windsurf/mcp_config.json` (or `~/.codeium/windsurf/mcp_config.json`
> with `--global`). Those locations are not the ones the current docs list, so prefer the manual
> configuration above and confirm with `Cascade → MCP` ([#42](https://github.com/knight22-21/CodePrism/issues/42)). Setup can also overwrite an
> existing config file it cannot parse ([#43](https://github.com/knight22-21/CodePrism/issues/43)), so back the file up first if you do use it.

---

## Continue.dev

Continue.dev is an open-source AI coding assistant for VS Code and JetBrains. Its
[current docs](https://docs.continue.dev/customize/deep-dives/mcp) configure MCP servers with one
YAML file per server in your workspace. Create `.continue/mcpServers/codeprism.yaml`:

```yaml
name: CodePrism
version: 0.0.1
schema: v1
mcpServers:
  - name: codeprism
    type: stdio
    command: codeprism
    args:
      - serve
      - /absolute/path/to/project
```

Continue picks the file up automatically. For several projects, put a file in each workspace.

The older `~/.continue/config.json` (`"mcpServers": { ... }`) is marked deprecated by Continue. It
may still work on old versions, but use the YAML form on current ones.

> `codeprism setup continue` writes to `~/.continue/config.json` (the deprecated form) plus a
> `.continue/rules/codeprism.md` rule ([#42](https://github.com/knight22-21/CodePrism/issues/42)). Use the manual YAML configuration above on
> current versions. Setup can also overwrite a config file it cannot parse ([#43](https://github.com/knight22-21/CodePrism/issues/43)).

---

## Zed

Zed has native MCP support. Per the [Zed docs](https://zed.dev/docs/ai/mcp), add the server under
`context_servers` in your settings file (run `zed: open settings file`), or use
**Settings → AI → MCP Servers**. The settings file is `~/.config/zed/settings.json` on macOS and
Linux and `%APPDATA%\Zed\settings.json` on Windows. It is JSON **with comments**: keep your comments
and trailing commas when you edit it by hand.

```json
{
  "context_servers": {
    "codeprism": {
      "command": "codeprism",
      "args": ["serve", "/absolute/path/to/project"],
      "env": {}
    }
  }
}
```

Reload the window. Zed also reads a project-level `.zed/settings.json`, but its MCP docs only describe
the user-level file, so use one entry per project there.

> `codeprism setup zed` writes `context_servers.codeprism.command` as an object
> (`{"path": ..., "args": [...]}`), which is not the shape the current docs show, and always to
> `~/.config/zed/settings.json`, which is the wrong file on Windows ([#42](https://github.com/knight22-21/CodePrism/issues/42)). **It also replaces
> a settings file it cannot parse, and Zed's own settings file (JSON with comments) is one of those
> ([#43](https://github.com/knight22-21/CodePrism/issues/43)): it would wipe your settings.** Use the manual configuration above.

---

## VS Code with GitHub Copilot

VS Code added MCP support for GitHub Copilot Chat extensions. Add to your VS Code `settings.json` (`Ctrl+Shift+P` → "Open User Settings JSON"):

```json
{
  "mcp": {
    "servers": {
      "codeprism": {
        "type": "stdio",
        "command": "codeprism",
        "args": ["serve", "/absolute/path/to/project"]
      }
    }
  }
}
```

Or workspace-level (`.vscode/mcp.json`):

```json
{
  "servers": {
    "codeprism": {
      "type": "stdio",
      "command": "codeprism",
      "args": ["serve", "${workspaceFolder}"]
    }
  }
}
```

Reload VS Code. In GitHub Copilot Chat, type `@codeprism` to invoke tools directly, or let Copilot Workspace use them automatically.

---

## Cody (Sourcegraph)

Cody supports MCP via its VS Code extension configuration. Add to VS Code `settings.json`:

```json
{
  "cody.experimental.mcp.servers": {
    "codeprism": {
      "command": "codeprism",
      "args": ["serve", "/absolute/path/to/project"]
    }
  }
}
```

After reloading, Cody can call CodePrism tools during its agentic editing sessions, supplementing Sourcegraph's own code intelligence with CodePrism's local graph and security scanner.

---

## Aider

### Integration overview

Aider and CodePrism are complementary, not competing:

| Tool | Role |
|---|---|
| **Aider** | Applies code changes — tracks edited files, manages git commits, runs tests |
| **CodePrism** | Answers structural questions — callers, callees, impact blast radius, security scan |

Aider does not build a knowledge graph; it reads files on demand, which costs tokens for every context fetch. CodePrism builds the graph once at index time; every subsequent query is a sub-100-token lookup. Together they eliminate the "cold-start" token burn that happens when Aider first encounters an unfamiliar symbol.

**Typical workflow:**
1. Run `codeprism index /path/to/project` once (or on CI push)
2. Query the graph before starting an Aider session — get callers, impact severity, and the symbol signature in ~200 tokens
3. Hand the compact summary to Aider so it starts informed
4. After Aider writes files, run `codeprism scan` to security-gate the output before committing

---

### Option A — Python pre-context script (zero extra infrastructure)

Run this before `aider` to load precise context into your shell or a `--message` flag:

```python
# query_context.py  — run before aider to understand the function
import asyncio
from codeprism import CodePrism

async def main():
    async with CodePrism("/path/to/project") as prism:
        ctx = await prism.get_context("payments/processor.py", "charge_card")
        print("Signature:", ctx.symbol.signature)
        print("Callers:", [c.name for c in ctx.direct_callers])
        impact = await prism.get_impact("payments/processor.py", "charge_card")
        print("Impact severity:", impact.severity)
        print("Dependents:", [d.name for d in impact.direct_dependents])

asyncio.run(main())
```

```bash
# Feed the summary directly into Aider as a message
python query_context.py | aider --message "$(cat -)" payments/processor.py
```

**When to use Option A:** You want zero extra processes. Suitable for one-off sessions or scripted CI pipelines.

---

### Option B — SSE server alongside Aider (persistent graph, live queries)

Run CodePrism as a persistent MCP server; any MCP-aware orchestrator wrapping Aider can call it live:

```bash
# Terminal 1 — knowledge graph server (stays running)
codeprism serve /path/to/project --transport sse --port 8765

# Terminal 2 — Aider session
aider --model claude-sonnet-4-6 payments/processor.py
```

Connect any MCP client to `http://localhost:8765/sse` and call tools:

```python
# In your orchestration layer (e.g. a LangGraph wrapper around Aider)
impact = mcp_client.call("get_impact", {"file": "payments/processor.py", "symbol": "charge_card"})
# → {"symbol": {...}, "severity": "HIGH", "direct_dependents": [...],
#    "transitive_dependents": [...], "affected_test_files": [...], ...}

scan = mcp_client.call("scan_diff", {"original": old_code, "proposed": new_code, "file": "payments/processor.py"})
# → {"status": "PASS", "file": "payments/processor.py", "issues": []}
```

**When to use Option B:** Long-running sessions, multi-agent pipelines, or when your orchestrator already speaks MCP.

---

### Option C — Post-write security gate (recommended for any setup)

After Aider writes files, gate the output through CodePrism before committing. `codeprism scan`
exits with code `2` when it finds a BLOCK-severity issue:

```bash
#!/usr/bin/env bash
# post-edit-gate.sh — run after an aider session, from the project root
for file in $(git diff --name-only); do
    codeprism scan "$file"
    if [ $? -eq 2 ]; then
        echo "BLOCKED: $file has critical security issues — aborting commit"
        exit 1
    fi
done
echo "Security gate: PASS"
```

Or scan the whole change at once:

```bash
codeprism scan . --diff HEAD || { echo "BLOCKED"; exit 1; }
```

Or inline via Python. Aider has already written the files, so use `check_content` (a full scan of
the content); `check_write` compares against the file on disk and would report nothing new:

```python
import asyncio, subprocess
from pathlib import Path
from codeprism import SecurityGate

async def gate() -> None:
    changed = subprocess.check_output(["git", "diff", "--name-only", "HEAD"]).decode().splitlines()
    security = SecurityGate()
    for f in changed:
        report = await security.check_content(Path(f).read_text(encoding="utf-8"), f)
        if report.is_blocked:
            raise SystemExit(f"BLOCKED: {f} — {[i.description for i in report.issues]}")
    print(f"Security gate: PASS ({len(changed)} files checked)")

asyncio.run(gate())
```

---

### Why CodePrism + Aider beats either tool alone

| Capability | Aider alone | CodePrism alone | Together |
|---|---|---|---|
| Apply code changes, manage commits | Yes | No | Yes (Aider) |
| Know callers of a function without reading the file | No | Yes | Yes (CodePrism graph) |
| Blast-radius / impact analysis before editing | No | Yes | Yes |
| Security gate on generated code | No | Yes | Yes |
| Token cost per context fetch | High (reads whole files) | Low (< 400 tokens per query) | Low |
| Works offline / no API | Yes | Yes | Yes |

---

## Remote / SSE

SSE transport serves the graph over HTTP, for MCP clients that speak it.

```bash
codeprism serve /path/to/project --transport sse --port 8765
```

Connect an MCP client to `http://127.0.0.1:8765/sse`.

> **The SSE server listens on `127.0.0.1` only** (there is no `--host` option yet, [#45](https://github.com/knight22-21/CodePrism/issues/45)) and
> has no built-in authentication, so it is reachable only from the machine it runs on.

To use it from another machine, keep it on loopback and expose it yourself:

**SSH tunnel** (simplest; authentication and encryption come from SSH):

```bash
ssh -L 8765:127.0.0.1:8765 user@server      # then connect to http://127.0.0.1:8765/sse locally
```

**Reverse proxy on the same host** (Nginx or Caddy) for TLS and token authentication:

```nginx
location /sse {
    proxy_pass http://127.0.0.1:8765/sse;
    auth_request /auth;            # validate the bearer token upstream
    proxy_buffering off;           # SSE streams must not be buffered
}
```

Inside a container the same applies: a published Docker port cannot reach a server that is bound
to the container's loopback, so run the reverse proxy in the same container or network namespace.

---

## Python library (embed directly)

Skip MCP entirely and use CodePrism as a Python library inside your own agent harness.

```python
from codeprism import CodePrism, SecurityGate

async with CodePrism("/path/to/project") as prism:
    await prism.index()

    # Structural context — no file reading needed
    ctx = await prism.get_context("payments/processor.py", "process_payment")
    print(ctx.symbol.signature)
    print([c.name for c in ctx.direct_callers])

    # Blast radius before a change
    impact = await prism.get_impact("payments/processor.py", "process_payment")
    if impact.severity in ("HIGH", "CRITICAL"):
        print(f"Warning: {len(impact.transitive_dependents)} downstream callers")

    # Security gate before writing. check_write compares the proposed content with the file
    # currently on disk and reports only issues the change introduces; use
    # gate.check_content(text, file) for a full scan of content that is already written.
    gate = SecurityGate()
    report = await gate.check_write("auth/login.py", new_content)
    if report.is_blocked:
        raise ValueError(f"Security issue: {report.issues[0].description}")

    # Session tracking across a multi-step agent chain
    session = prism.session("agent-run-001")
    await session.record_read("payments/processor.py", "process_payment")
    await session.record_write("payments/processor.py", old_content, new_content)
    summary = await session.get_context()
    await session.undo(steps=1)
```

**Async iterator for batch processing:**

```python
from codeprism.core.storage import StorageManager
from codeprism.core.paths import get_db_path

# Access the raw storage layer if you need bulk reads
db = StorageManager(get_db_path("/path/to/project"))
await db.initialize()
all_files = await db.get_all_files()
all_symbols = await db.get_all_symbols()
await db.close()
```

---

## OpenAI Agents SDK

Use CodePrism as a tool set in OpenAI's [Agents SDK](https://openai.github.io/openai-agents-python/mcp/)
(or any framework that supports MCP tool adapters).

```python
import asyncio
from agents import Agent, Runner
from agents.mcp import MCPServerStdio

async def main():
    async with MCPServerStdio(
        name="CodePrism",
        params={
            "command": "codeprism",
            "args": ["serve", "/path/to/project"],
        },
    ) as mcp_server:
        agent = Agent(
            name="CodeAgent",
            instructions=(
                "You are a coding agent. Use get_context to understand code before editing. "
                "Always call scan_diff before writing a file."
            ),
            mcp_servers=[mcp_server],
        )
        result = await Runner.run(agent, "Refactor the charge_card function to handle retries.")
        print(result.final_output)

asyncio.run(main())
```

---

## CI/CD (GitHub Actions)

Use `codeprism scan --diff` in your pipeline to block PRs that introduce new security issues.

```yaml
# .github/workflows/codeprism-security.yml
name: CodePrism Security Scan

on:
  pull_request:
    branches: [main]

jobs:
  security:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 2  # needed for diff

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install CodePrism
        run: pip install codeprism-ai

      - name: Scan changed files
        run: |
          codeprism scan . --diff origin/${{ github.base_ref }}..HEAD
        # Exit code 2 = BLOCK finding → PR fails
        # Exit code 0 = PASS → PR continues
```

`--diff` scans the changed content directly and needs no index. `codeprism scan --all` does:
run `codeprism index .` first, and cache the index directory between runs if that is slow (on
Linux it is `~/.local/share/codeprism`).

---

## Pre-commit hook

Catch issues before they enter git history.

**Using pre-commit framework:**

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: codeprism-scan
        name: CodePrism Security Scan
        language: system
        entry: codeprism scan
        args: [".", "--diff", "HEAD"]
        pass_filenames: false
        stages: [pre-commit]
```

Install:
```bash
pip install pre-commit codeprism-ai
pre-commit install
```

**Raw git hook** (`.git/hooks/pre-commit`):

```bash
#!/usr/bin/env bash
codeprism scan . --diff HEAD
STATUS=$?
if [ $STATUS -eq 2 ]; then
    echo "CodePrism: BLOCK-severity security issue found. Commit rejected."
    exit 1
fi
exit 0
```

`--diff HEAD` compares the working tree with `HEAD`, so staged and unstaged changes are both
scanned.

```bash
chmod +x .git/hooks/pre-commit
```

---

## Supported Languages

CodePrism parses ten languages out of the box. No extra config — the registry picks the right parser from the file extension automatically.

| Language | Extensions | Features |
|---|---|---|
| Python | `.py`, `.pyi` | Functions, classes, imports, type hints, async, decorators |
| JavaScript | `.js`, `.jsx`, `.mjs` | Functions, classes, ES modules, CommonJS require |
| TypeScript | `.ts`, `.tsx`, `.mts` | + interfaces, type aliases, generics |
| Go | `.go` | Functions, structs, interfaces, packages |
| Rust | `.rs` | Functions, structs, traits, impl blocks |
| Java | `.java` | Classes, interfaces, methods, annotations, generics |
| C | `.c`, `.h` | Functions, structs, typedefs, includes |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh` | Classes, methods, inheritance, templates, namespaces |
| Ruby | `.rb`, `.rake`, `.gemspec` | Modules, classes, instance/singleton methods, visibility |
| PHP | `.php`, `.php5`, `.phtml` | Namespaces, classes, traits, interfaces, methods |

Unknown extensions fall back to a line-count generic parser.

---

## Quick reference

| Agent / Tool | Transport | Config location | Auto-setup |
|---|---|---|---|
| Claude Code | stdio | `.mcp.json` (project) / `~/.claude.json` (user) | `codeprism setup claude` |
| Codex | stdio | `.codex/config.toml` (project) / `~/.codex/config.toml` (user) | `codeprism setup codex` |
| Cursor | stdio | `.cursor/mcp.json` | `codeprism setup cursor` |
| Windsurf | stdio | `%APPDATA%\devin\mcp_config.json` / `~/.config/devin/mcp_config.json` | manual |
| Continue.dev | stdio | `.continue/mcpServers/*.yaml` | manual |
| Zed | stdio | `~/.config/zed/settings.json` (`context_servers`) | manual |
| VS Code + Copilot | stdio | `settings.json` / `.vscode/mcp.json` | manual |
| Cody | stdio | VS Code `settings.json` | manual |
| Any HTTP agent | SSE | `http://host:8765/sse` | `codeprism serve --transport sse` |
| Custom Python agent | library | n/a | `from codeprism import CodePrism` |
| GitHub Actions | CLI | `.github/workflows/` | manual |
| Pre-commit | CLI | `.pre-commit-config.yaml` | manual |
