# CodePrism Skill - User Guide

This guide provides detailed instructions on using the CodePrism skill with AI agents.

## Table of Contents

1. [Getting Started](#getting-started)
2. [Core Concepts](#core-concepts)
3. [Common Workflows](#common-workflows)
4. [Best Practices](#best-practices)
5. [Advanced Usage](#advanced-usage)
6. [Troubleshooting](#troubleshooting)

## Getting Started

### Prerequisites

- Python 3.12 or higher
- CodePrism installed: `pip install codeprism-ai`
- An AI agent that supports MCP (Claude Code, Cursor, Codex, etc.)

### Initial Setup

1. **Install CodePrism:**
   ```bash
   pip install codeprism-ai
   ```

2. **Configure your agent:**
   ```bash
   # For Claude Code
   codeprism setup claude --global
   
   # For Codex
   codeprism setup codex --global
   
   # For Cursor
   codeprism setup cursor --project /path/to/project
   ```

3. **Restart your agent/editor**

4. **Verify connection:**
   - Claude Code: Run `/mcp`
   - Codex: Run `/mcp` or `codex mcp list`
   - Cursor: Check Settings → MCP

### First Use

Try this prompt:
```
Use codeprism to understand the structure of this codebase.
```

The agent should:
- Query the graph statistics
- Provide an overview of the project
- Explain the main components

## Core Concepts

### Knowledge Graph vs. File Reading

**Traditional approach:**
- Agent reads entire files to understand code
- 8,000-40,000 tokens per context window
- Re-reading the same files repeatedly
- No security checks before writes

**CodePrism approach:**
- Agent queries a pre-built knowledge graph
- 200-800 tokens for equivalent context
- Session tracking avoids re-fetching
- Security gate before every write

### The Graph Structure

CodePrism indexes:
- **Files**: All source files in your project
- **Symbols**: Functions, classes, variables, imports
- **Edges**: Relationships between symbols (calls, imports, inherits)
- **Metadata**: Line numbers, signatures, complexity scores

### Query Depth

When using `get_context`, the `depth` parameter controls how much context to retrieve:

- **depth=1**: The symbol + direct callers/callees
- **depth=2**: Symbol + callers/callees + their neighbors (recommended)
- **depth=3**: Full transitive neighborhood

Use depth=2 for most cases - it provides good context without excessive tokens.

## Common Workflows

### Understanding a Function

**Prompt:**
```
Use codeprism to explain what the process_payment function does, who calls it, and what it calls.
```

**What happens:**
1. Agent calls `search_symbol` to find the function
2. Agent calls `get_context` with depth=2
3. Agent receives: signature, callers, callees, types
4. Agent provides a comprehensive explanation

**Benefits:**
- Only ~250 tokens instead of reading entire file
- Precise call relationships
- Type information included

### Refactoring Planning

**Prompt:**
```
I want to refactor the auth module. Use codeprism to check the impact first.
```

**What happens:**
1. Agent calls `get_impact` for auth-related symbols
2. Agent receives: severity, dependents, affected test files
3. Agent can plan the refactoring with full blast radius knowledge

**Benefits:**
- Know exactly what will break
- Identify affected tests upfront
- Estimate refactoring effort

### Security Check Before Writing

**Prompt:**
```
Write a function that handles user passwords. Use codeprism to scan it before writing.
```

**What happens:**
1. Agent writes the proposed code
2. Agent calls `scan_diff` with original and proposed content
3. If BLOCK status: Agent refuses to write and explains issues
4. If PASS/WARN status: Agent writes and reports warnings

**Benefits:**
- Prevents secrets from reaching disk
- Catches injection vulnerabilities
- Flags weak cryptography

### Finding Symbol Relationships

**Prompt:**
```
Find all functions that handle authentication in this codebase using codeprism.
```

**What happens:**
1. Agent calls `search_symbol` with query "auth" and kind="function"
2. Agent receives a ranked list of matching functions
3. Agent presents results without grepping through files

**Benefits:**
- Fast search across entire codebase
- Ranked by relevance
- No false positives from string matches

## Best Practices

### 1. Always Query Before Reading

**Bad:**
```
Read the auth.py file and explain what it does.
```

**Good:**
```
Use codeprism to get a module summary of auth.py, then read only if you need implementation details.
```

### 2. Use Appropriate Depth

- Use `depth=2` for most queries (default)
- Use `depth=1` for quick lookups
- Use `depth=3` only for complex analysis

### 3. Leverage Security Gate

**Always scan before writing:**
```python
# Agent pattern
original = read(file_path)
proposed = write_new_code(file_path)
scan_result = scan_diff(original, proposed, file_path)
if scan_result["status"] == "BLOCK":
    # Don't write
else:
    write(file_path, proposed)
```

### 4. Use Longer Paths for Ambiguity

If you get "ambiguous path" errors:
```
# Instead of
get_context("utils.py", "function")

# Use
get_context("src/auth/utils.py", "function")
```

### 5. Check Index Status

Before using CodePrism tools:
```
Check that get_graph_stats returns index_status: ready
```

If it's "indexing", wait for it to complete.

## Advanced Usage

### Session Tracking

For long multi-step tasks, use session tracking:

```
# Agent can track what it has already read
get_session_context("session_id")
# Returns: "3 reads across 2 files, 1 write to payments/processor.py"
```

This prevents re-fetching the same context.

### Incremental Updates

When you edit files in your editor:
- Changes are not seen by the running server
- Restart the agent/editor to pick up changes
- Or use CodePrism's write tools (they update the graph)

### Multi-Language Projects

CodePrism supports 10 languages:
- Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, PHP

The graph automatically includes all indexed languages.

### Impact Analysis for Teams

Before team-wide refactoring:
```
Use codeprism to get the impact of changing this core function. Tell me which teams and files will be affected.
```

This helps coordinate refactoring across teams.

## Troubleshooting

### "File not indexed" Error

**Cause:** The file hasn't been indexed yet

**Solution:**
1. Check `get_graph_stats` for index status
2. If "indexing", wait for completion
3. If "unknown", run `codeprism index /path/to/project`

### "Ambiguous path" Error

**Cause:** Multiple files have the same name

**Solution:** Use a longer, more specific path
```
# Instead of
get_context("utils.py", "function")

# Use
get_context("src/auth/utils.py", "function")
```

### Tools Not Available

**Cause:** MCP server not connected

**Solution:**
1. Verify CodePrism is installed
2. Check MCP connection for your agent
3. Restart the agent/editor
4. Run setup command again

### Security Scan Blocking Everything

**Cause:** Test files or example code have issues

**Solution:**
1. Check if files are in security ignore paths
2. Review the specific issues reported
3. Use `.codeprism.toml` to configure ignore patterns

## Performance Tips

### Query Optimization

- Use `depth=2` for most queries
- Call `get_module_summary` for file-level understanding
- Use `search_symbol` with `kind` filter to narrow results

### Index Optimization

- Index respects `.gitignore` - keep it up to date
- Only re-index when files change (automatic)
- Use `--force` only when index format changes

### Token Savings

Typical token savings:
- Understanding a function: 95% reduction
- Finding callers: 90% reduction
- Impact analysis: 85% reduction
- Module summary: 80% reduction

## Next Steps

- Check [Examples](skill-examples.md) for specific use cases
- Read [Full Documentation](README.md) for CodePrism features
- See [Installation Guide](SKILL_DISTRIBUTION.md) for setup details

## Support

- GitHub Issues: https://github.com/knight22-21/CodePrism/issues
- Documentation: https://github.com/knight22-21/CodePrism#readme
