# CodePrism Integrations

How to connect CodePrism to AI coding agents, editors, and automated pipelines.

CodePrism speaks [Model Context Protocol (MCP)](https://modelcontextprotocol.io) — the open standard adopted by every major AI editor. If your tool supports MCP, CodePrism works with it. The server runs locally via **stdio** (default) or over a network via **SSE**.

---

## Table of Contents

1. [Claude Code](#claude-code)
2. [Cursor](#cursor)
3. [Windsurf (Codeium)](#windsurf-codeium)
4. [Continue.dev](#continuedev)
5. [Zed](#zed)
6. [VS Code with GitHub Copilot](#vs-code-with-github-copilot)
7. [Cody (Sourcegraph)](#cody-sourcegraph)
8. [Aider](#aider)
9. [Remote / SSE (any network agent)](#remote--sse-any-network-agent)
10. [Python library (embed directly)](#python-library-embed-directly)
11. [OpenAI Agents SDK](#openai-agents-sdk)
12. [CI/CD (GitHub Actions)](#cicd-github-actions)
13. [Pre-commit hook](#pre-commit-hook)

---

## Claude Code

The fastest path — one command wires everything up.

```bash
# Index your project first
codeprism index /path/to/project

# Auto-configure Claude Code
codeprism setup claude --project /path/to/project
```

`codeprism setup claude` writes two things:

- **MCP server entry** to `~/.claude.json` (or `.claude/settings.json` for project-local config)
- **`CLAUDE.md`** in the project root with a usage guide injected into every Claude Code session

**Manual config** (if you prefer to edit directly):

```json
// ~/.claude.json  or  .claude/settings.json
{
  "mcpServers": {
    "codeprism": {
      "command": "codeprism",
      "args": ["serve", "/absolute/path/to/project"]
    }
  }
}
```

Restart Claude Code after any config change. The `codeprism` server appears under **MCP servers** in the session header.

**Global config** (applies to every project):

```bash
codeprism setup claude --project /path/to/project --global
```

**What Claude can now do** — without reading any files:

```
get_context("payments/processor.py", "charge_card", depth=2)
get_impact("utils/auth.py", "verify_token")
scan_diff(original, proposed, "auth/login.py")
search_symbol("handle payment", kind="function")
```

---

## Cursor

```bash
codeprism index /path/to/project
codeprism setup cursor --project /path/to/project
# Restart Cursor
```

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

## Windsurf (Codeium)

Windsurf uses MCP via a global config file.

**Manual config** — create or edit `~/.codeium/windsurf/mcp_config.json`:

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

Restart Windsurf. The server appears under **Cascade → MCP Tools**.

**Per-project config** — Windsurf also respects `.windsurf/mcp.json` in the project root:

```json
{
  "mcpServers": {
    "codeprism": {
      "command": "codeprism",
      "args": ["serve", "${workspaceFolder}"]
    }
  }
}
```

Windsurf Cascade (their agent mode) will automatically use `get_context` and `scan_diff` when editing files in the project.

---

## Continue.dev

Continue.dev is an open-source AI coding assistant for VS Code and JetBrains.

Edit `~/.continue/config.json`:

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

For multiple projects, add a server entry per project with a unique key:

```json
{
  "mcpServers": {
    "codeprism-backend": {
      "command": "codeprism",
      "args": ["serve", "/projects/backend"]
    },
    "codeprism-frontend": {
      "command": "codeprism",
      "args": ["serve", "/projects/frontend"]
    }
  }
}
```

Reload the Continue extension. In the chat panel, Continue will list the CodePrism tools under **@codeprism**.

---

## Zed

Zed has native MCP support. Edit `~/.config/zed/settings.json`:

```json
{
  "context_servers": {
    "codeprism": {
      "command": {
        "path": "codeprism",
        "args": ["serve", "/absolute/path/to/project"]
      }
    }
  }
}
```

Alternatively, use a project-level `.zed/settings.json`:

```json
{
  "context_servers": {
    "codeprism": {
      "command": {
        "path": "codeprism",
        "args": ["serve", "$ZED_WORKTREE_ROOT"]
      }
    }
  }
}
```

Reload the project. The CodePrism tools appear under **Assistant → Context Servers** in Zed's panel.

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

Aider is a CLI coding agent. Use CodePrism via the Python library to pre-load context before an Aider session, or run the MCP server alongside Aider for any MCP-capable orchestrator wrapping it.

**Option A — Python pre-context script:**

```python
# query_context.py  — run before aider to understand the function
import asyncio
from codeprism import CodePrism

async def main():
    async with CodePrism("/path/to/project") as prism:
        ctx = await prism.get_context("payments/processor.py", "charge_card")
        print(ctx.symbol.signature)
        print("Callers:", [c.name for c in ctx.direct_callers])
        impact = await prism.get_impact("payments/processor.py", "charge_card")
        print("Severity:", impact.severity)

asyncio.run(main())
```

**Option B — SSE server alongside Aider** (for MCP-aware orchestrators):

```bash
# Terminal 1
codeprism serve /path/to/project --transport sse --port 8765

# Terminal 2
aider --model claude-sonnet-4-6 payments/processor.py
```

---

## Remote / SSE (any network agent)

Switch to SSE transport to serve the graph over a network — useful for:
- Multi-machine setups (agent on one box, codebase on another)
- Docker containers
- Cloud VMs with no local filesystem access
- Any MCP client that uses HTTP

```bash
# Start the server
codeprism serve /path/to/project --transport sse --port 8765
```

Connect any MCP client to `http://localhost:8765/sse`.

**With authentication (reverse proxy):**

Put Nginx or Caddy in front for TLS + bearer token:

```nginx
location /sse {
    proxy_pass http://127.0.0.1:8765/sse;
    proxy_set_header Authorization "";  # strip; validate upstream
    auth_request /auth;
}
```

**Docker Compose:**

```yaml
services:
  codeprism:
    image: python:3.12-slim
    command: >
      sh -c "pip install codeprism-ai &&
             codeprism index /workspace &&
             codeprism serve /workspace --transport sse --port 8765"
    volumes:
      - ./:/workspace
    ports:
      - "8765:8765"
```

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

    # Security gate before writing
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

Use CodePrism as a tool set in OpenAI's Agents SDK (or any framework that supports MCP tool adapters).

```python
from agents import Agent, MCPServerStdio

async def main():
    async with MCPServerStdio(
        params={
            "command": "codeprism",
            "args": ["serve", "/path/to/project"],
        }
    ) as mcp_server:
        agent = Agent(
            name="CodeAgent",
            model="gpt-4o",
            mcp_servers=[mcp_server],
            instructions=(
                "You are a coding agent. Use get_context to understand code before editing. "
                "Always call scan_diff before writing a file."
            ),
        )
        result = await agent.run("Refactor the charge_card function to handle retries.")
        print(result.final_output)
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

      - name: Index project
        run: codeprism index .

      - name: Scan changed files
        run: |
          codeprism scan . --diff origin/${{ github.base_ref }}..HEAD
        # Exit code 2 = BLOCK finding → PR fails
        # Exit code 0 = PASS → PR continues
```

**Cache the index for faster runs:**

```yaml
      - name: Cache CodePrism index
        uses: actions/cache@v4
        with:
          path: ~/.local/share/codeprism
          key: codeprism-${{ hashFiles('**/*.py', '**/*.ts', '**/*.go') }}
          restore-keys: codeprism-

      - name: Index project (incremental if cached)
        run: codeprism index .
```

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
        args: ["--diff", "HEAD"]
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
set -e
codeprism scan . --diff HEAD 2>&1
STATUS=$?
if [ $STATUS -eq 2 ]; then
    echo "CodePrism: BLOCK-severity security issue found. Commit rejected."
    exit 1
fi
exit 0
```

```bash
chmod +x .git/hooks/pre-commit
```

---

## Quick reference

| Agent / Tool | Transport | Config location | Auto-setup |
|---|---|---|---|
| Claude Code | stdio | `~/.claude.json` | `codeprism setup claude` |
| Cursor | stdio | `.cursor/mcp.json` | `codeprism setup cursor` |
| Windsurf | stdio | `~/.codeium/windsurf/mcp_config.json` | manual |
| Continue.dev | stdio | `~/.continue/config.json` | manual |
| Zed | stdio | `~/.config/zed/settings.json` | manual |
| VS Code + Copilot | stdio | `settings.json` / `.vscode/mcp.json` | manual |
| Cody | stdio | VS Code `settings.json` | manual |
| Any HTTP agent | SSE | `http://host:8765/sse` | `codeprism serve --transport sse` |
| Custom Python agent | library | n/a | `from codeprism import CodePrism` |
| GitHub Actions | CLI | `.github/workflows/` | manual |
| Pre-commit | CLI | `.pre-commit-config.yaml` | manual |
