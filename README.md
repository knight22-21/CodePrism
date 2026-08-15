# CodePrism

**Stop feeding your AI agent the whole codebase. Give it a graph.**

CodePrism builds a persistent knowledge graph of your project — every function, class, import, and data-flow relationship — and exposes it to any AI coding agent via the [Model Context Protocol (MCP)](https://modelcontextprotocol.io). Instead of your agent reading 40 files to understand one function, it queries the graph and gets exactly what it needs in under 200 tokens.

[![PyPI](https://img.shields.io/pypi/v/codeprism-ai)](https://pypi.org/project/codeprism-ai/)
[![Python](https://img.shields.io/pypi/pyversions/codeprism-ai)](https://pypi.org/project/codeprism-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests](https://github.com/knight22-21/CodePrism/actions/workflows/ci.yml/badge.svg)](https://github.com/knight22-21/CodePrism/actions)

---

## Why CodePrism

| Without CodePrism | With CodePrism |
|---|---|
| Agent reads 30–50 files per task | Agent queries the graph — 1–3 targeted calls |
| 8,000–40,000 tokens per context window | 200–800 tokens for equivalent context |
| Agent re-reads the same files repeatedly | Session overlay tracks what's already been read |
| Security issues discovered after the write | Security gate runs before every write |
| Entire codebase re-sent on every file change | Incremental graph update in milliseconds |

**Token reduction target: 60–80% on large codebases.**

---

## What CodePrism Does

- **Indexes** your codebase using tree-sitter AST parsing (Python, JavaScript, TypeScript, Go)
- **Maintains** a live knowledge graph — updated incrementally when files change
- **Answers** precise structural questions: callers, callees, impact, dependencies, data flow
- **Guards** every write with a security scanner — secrets, injection, weak crypto, and more
- **Tracks** agent sessions — what was read, what was written, undo support
- **Serves** all of the above via MCP to Claude Code, Cursor, and any MCP-compatible agent

---

## Installation

```bash
pip install codeprism-ai
```

Python 3.12+ required.

**Optional: semantic search** (heavier install, enables embedding-based symbol search)
```bash
pip install "codeprism-ai[embeddings]"
```

---

## Quickstart

### 1. Index your project

```bash
codeprism index /path/to/your/project
```

This builds the knowledge graph and stores it in a local SQLite database. On a 50,000-line codebase this takes about 10–20 seconds. Subsequent updates are incremental and instant.

### 2. Connect your AI agent

Pick the agent you use:

**Claude Code**
```bash
codeprism setup claude --project /path/to/your/project
```
Then restart Claude Code. CodePrism appears automatically as an MCP server.

**Cursor**
```bash
codeprism setup cursor --project /path/to/your/project
```
Then restart Cursor.

**Any MCP-compatible agent (manual)**
```bash
codeprism serve /path/to/your/project
```
This starts the MCP server on stdio. Point your agent's MCP config at `codeprism serve <path>`.

### 3. That's it

Your agent can now call tools like `get_context`, `get_impact`, `scan_diff`, and `record_write` instead of reading raw files.

---

## IDE and Agent Setup

### Claude Code

Run the setup command and restart:

```bash
codeprism setup claude --project /path/to/project
# Restart Claude Code
```

For a global installation (applies to all projects):
```bash
codeprism setup claude --project /path/to/project --global
```

Claude Code will pick up the `codeprism` MCP server automatically. You'll see it listed under MCP servers in the session. Ask Claude to `get_context payments/processor.py::process_payment` and it will call CodePrism instead of reading the file.

---

### Cursor

```bash
codeprism setup cursor --project /path/to/project
# Restart Cursor
```

For a global config:
```bash
codeprism setup cursor --project /path/to/project --global
```

Cursor will list CodePrism under **Settings → MCP**. All Cursor Composer and chat sessions automatically get access to the graph tools.

---

### Continue.dev

Add the following to your `~/.continue/config.json`:

```json
{
  "mcpServers": {
    "codeprism": {
      "command": "codeprism",
      "args": ["serve", "/path/to/your/project"]
    }
  }
}
```

---

### Any MCP-compatible agent (programmatic)

Start the server in SSE mode for remote or network-connected agents:

```bash
codeprism serve /path/to/project --transport sse --port 8765
```

Then connect your agent to `http://localhost:8765`.

---

### Python library (embed directly)

If you're building an agent harness or automation script, use CodePrism directly without the MCP layer:

```python
from codeprism import CodePrism, SecurityGate

async with CodePrism("/path/to/project") as prism:
    await prism.index()

    # Get structured context for a symbol — no file reading needed
    ctx = await prism.get_context("payments/processor.py", "process_payment")
    print(ctx.symbol.signature)
    print([c.name for c in ctx.direct_callers])

    # Assess the blast radius of a change
    impact = await prism.get_impact("payments/processor.py", "process_payment")
    print(impact.severity)           # LOW | MEDIUM | HIGH | CRITICAL
    print(impact.affected_test_files)

    # Security gate — check before writing
    gate = SecurityGate()
    report = await gate.check_write("payments/processor.py", new_content)
    if report.is_blocked:
        raise ValueError(report.issues[0].description)

    # Session tracking — prevent re-reads across a long agent chain
    session = prism.session("sess_abc123")
    await session.record_read("payments/processor.py", "process_payment")
    await session.record_write("payments/processor.py", old_content, new_content)
    summary = await session.get_context()   # compact digest for the LLM
    await session.undo(steps=1)             # roll back the write
```

---

## CLI Reference

### Indexing

```bash
# Index a project (first run or full rebuild)
codeprism index /path/to/project

# Index only specific languages
codeprism index /path/to/project --languages python,typescript
```

### Querying

```bash
# Get structured context for a symbol
codeprism context payments/processor.py::process_payment

# Transitive impact analysis
codeprism impact payments/processor.py::process_payment

# Who calls this function?
codeprism callers payments/processor.py::process_payment

# Search for a symbol by name
codeprism search "handle_authentication"

# File-level summary
codeprism summary payments/processor.py

# Graph statistics
codeprism stats
codeprism stats --verbose    # per-file breakdown
```

### Security scanning

```bash
# Scan a single file
codeprism scan payments/processor.py

# Scan every indexed file in the project
codeprism scan --all --project /path/to/project

# Scan only the files changed in a git commit range
codeprism scan . --diff HEAD~1..HEAD
codeprism scan . --diff main..feature-branch
```

Exit codes: `0` = PASS, `2` = BLOCK (use in CI pipelines).

### Watch mode

```bash
# Keep the graph in sync with file changes (foreground process)
codeprism watch /path/to/project
```

### MCP server

```bash
# Stdio transport (for Claude Code, Cursor, Continue)
codeprism serve /path/to/project

# SSE transport (for remote or network agents)
codeprism serve /path/to/project --transport sse --port 8765
```

---

## Security Gate

CodePrism scans every proposed file write before it reaches disk. The scanner runs six detector categories:

| Detector | What it catches | Severity |
|---|---|---|
| **Secrets** | Hardcoded passwords, API keys, AWS credentials, GitHub tokens, OpenAI keys | BLOCK |
| **Injection** | SQL injection via f-strings or string concat, `eval()`, `exec()`, `shell=True` | BLOCK / WARN |
| **Weak crypto** | MD5, SHA-1, DES, RC4, non-cryptographic `random` for secrets | WARN |
| **Env var exposure** | Printing or returning `os.environ` contents | WARN |
| **Unsafe dependencies** | `pickle`, unsafe `yaml.load`, `marshal`, dynamic `__import__` | BLOCK / WARN |
| **Code safety** | Bare `except:`, silent exception swallowing, debugger breakpoints | WARN |

Severity rules:
- **BLOCK** — write is rejected; content never reaches disk
- **WARN** — write proceeds but the issue is surfaced to the agent
- **INFO** — logged only

Scan a file manually:
```bash
codeprism scan payments/processor.py
```

Use in CI to block PRs that introduce new security issues:
```bash
codeprism scan --diff HEAD~1..HEAD || exit 1
```

---

## Use Cases

### AI pair programmer context

Your AI agent is editing a large payment processing module. Without CodePrism it reads 15 files to understand the call graph. With CodePrism:

```
Agent: get_context("payments/processor.py", "charge_card", depth=2)
← 340 tokens: the function signature, its 3 callers, its 6 callees, the types it uses
```

### Pre-write security check

Before the agent writes a file that handles user authentication:

```
Agent: scan_diff(original_content, proposed_content, "auth/login.py")
← status: BLOCK, issues: [Hardcoded API key on line 42]
```

The write is stopped before the key ever touches disk.

### Impact analysis before refactoring

Before renaming a core utility function:

```
Agent: get_impact("utils/hash.py", "compute_checksum")
← severity: HIGH, direct_dependents: 12 functions, affected_test_files: ["tests/test_payments.py", ...]
```

The agent knows the full blast radius before making any changes.

### Session-aware long agent chains

In a multi-step agentic workflow, the agent tracks what it has already read:

```
Agent: get_session_context("sess_abc123")
← "3 reads across 2 files, 1 write to payments/processor.py — no need to re-fetch"
```

---

## Supported Languages

| Language | Status | Features |
|---|---|---|
| Python | Full | Functions, classes, imports, type hints, async, decorators |
| JavaScript | Full | Functions, classes, ES modules, CommonJS require |
| TypeScript | Full | + interfaces, type aliases, generics |
| Go | Full | Functions, structs, interfaces, packages |
| Rust | Planned (v1.2) | — |
| Java | Planned (v2.0) | — |

---

## Configuration

Create a `.codeprism.toml` in your project root to customize behavior:

```toml
[codeprism]
languages = ["python", "typescript"]
enable_embeddings = false
enable_security_gate = true
watch_debounce_ms = 500

[codeprism.security]
block_on_secrets = true
warn_on_weak_crypto = true
check_new_dependencies = true
ignore_paths = ["tests/fixtures/", "*.example.*"]

[codeprism.mcp]
transport = "stdio"
port = 8765
```

---

## Contributing

We welcome contributions of all kinds — bug fixes, new language parsers, additional security detectors, documentation improvements, and more.

Read the **[Contributing Guide](CONTRIBUTING.md)** for:
- How to set up the development environment
- Coding and testing standards
- The PR and review process
- How to add new security detectors or language parsers

Read the **[Code of Conduct](CODE_OF_CONDUCT.md)** before participating in any community space.

---

## License

MIT — see [LICENSE](LICENSE).

---

## Acknowledgements

Built on [tree-sitter](https://tree-sitter.github.io/tree-sitter/) for fast, accurate parsing; [NetworkX](https://networkx.org/) for graph operations; [FastMCP](https://github.com/jlowin/fastmcp) for the MCP server; and [Pydantic](https://docs.pydantic.dev/) for data validation. Security patterns informed by OWASP Top 10 and CWE.
