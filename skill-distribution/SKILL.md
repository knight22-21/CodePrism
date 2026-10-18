---
name: codeprism
description: Uses CodePrism knowledge graph to provide efficient codebase context for AI agents. Query symbols, analyze impact, and scan for security before writing. Use when working with large codebases, understanding code structure, or performing refactoring/security checks.
license: MIT
metadata:
  version: "0.1.11"
  author: knight22-21
  repository: https://github.com/knight22-21/CodePrism
  category: code-quality-review
compatibility: Requires codeprism-ai installed and MCP server connected. Works with Claude Code, Cursor, Codex, and any MCP-compatible agent.
---

# CodePrism Knowledge Graph Assistant

CodePrism maintains a persistent knowledge graph of your project — every function, class, import, and data-flow relationship. This skill teaches agents to query the graph instead of reading entire files, achieving 60-80% token reduction on large codebases.

## Core Principles

**Always query the graph before reading source files.** The CodePrism MCP server provides structured context in under 400 tokens, compared to 10-100× more when reading whole files.

## When to Use This Skill

Activate this skill when:
- User asks to understand code structure, relationships, or architecture
- User wants to know who calls a function or what a function calls
- User needs impact analysis before refactoring
- User requests security checks on code changes
- User is working with large codebases (500+ files)
- User asks about dependencies or data flow
- User mentions "graph", "context", "impact", "callers", "callees"

## Tool Usage Patterns

### Before Reading Files
Instead of reading a file to understand a function:
```python
# DON'T: Read the whole file
read(file_path)

# DO: Query the graph
mcp_call_tool(
    server_name="codeprism",
    tool_name="get_context",
    arguments={"file": "path/to/file.py", "symbol": "function_name", "depth": 2}
)
```

### Finding Call Relationships
Instead of grepping for who calls a function:
```python
# DON'T: Grep through files
grep(pattern="function_name", path=".")

# DO: Use the graph
mcp_call_tool(
    server_name="codeprism",
    tool_name="get_callers",
    arguments={"file": "path/to/file.py", "function": "function_name"}
)
```

### Understanding File Purpose
Instead of reading the entire file:
```python
# DON'T: Read full file
read(file_path)

# DO: Get module summary
mcp_call_tool(
    server_name="codeprism",
    tool_name="get_module_summary",
    arguments={"file": "path/to/file.py"}
)
```

### Impact Analysis
Before refactoring or changing a symbol:
```python
mcp_call_tool(
    server_name="codeprism",
    tool_name="get_impact",
    arguments={"file": "path/to/file.py", "symbol": "function_name"}
)
```

### Searching for Symbols
Instead of using grep:
```python
# DON'T: Grep for symbol names
grep(pattern="handle_auth", path=".")

# DO: Search the graph
mcp_call_tool(
    server_name="codeprism",
    tool_name="search_symbol",
    arguments={"query": "handle_auth", "kind": "function"}
)
```

### Security Before Writing
Before any file write operation:
```python
# ALWAYS scan the diff before writing
mcp_call_tool(
    server_name="codeprism",
    tool_name="scan_diff",
    arguments={
        "original": original_content,
        "proposed": proposed_content,
        "file": file_path
    }
)
# If status is BLOCK, do not write the file
```

## Tool Reference

### Required Tools (Call mcp_list_tools first)
Always call `mcp_list_tools` for the codeprism server before using any tools to get the current schema.

### Core Tools

- **get_context(file, symbol, depth=2)**: Get signature, callers, callees, types. Use depth=2 for recommended neighborhood coverage.
- **get_module_summary(file)**: High-level narrative summary of a source file.
- **get_impact(file, symbol)**: Transitive impact analysis — what breaks if this symbol changes.
- **get_callers(file, function)**: All functions that call this function with call-site metadata.
- **get_callees(file, function)**: All functions called by this function.
- **search_symbol(query, kind=None)**: Find symbols by name substring. Filter by kind: function|class|variable|import.
- **get_dependencies(file)**: Internal vs external dependencies for a file.
- **get_dependents(file)**: All files that transitively depend on this file.
- **scan_diff(original, proposed, file)**: Security check before any write. BLOCK status means critical security issue — do not write.
- **record_read(session_id, file, symbol)**: Log what you've already read to avoid re-fetching.
- **record_write(session_id, file, before, after)**: Log writes with security gate.
- **get_session_context(session_id)**: Compact digest of session activity.
- **undo_write(session_id, steps=1)**: Roll back agent-authored writes.

## Workflow Examples

### Understanding a Function
1. Call `get_context(file, symbol, depth=2)` to get the function signature, callers, and callees
2. If you need the exact implementation body, read the specific file (after getting context)
3. Record the read with `record_read` to track session state

### Refactoring Workflow
1. Call `get_impact(file, symbol)` to understand blast radius
2. Call `get_callers` and `get_callees` to see direct relationships
3. Make changes
4. Call `scan_diff` on each changed file before writing
5. If scan passes, write and call `record_write`

### Security Gate Pattern
For every file write:
```python
# 1. Get original content
original = read(file_path)

# 2. Scan the diff
scan_result = mcp_call_tool(
    server_name="codeprism",
    tool_name="scan_diff",
    arguments={"original": original, "proposed": new_content, "file": file_path}
)

# 3. Check status
if scan_result["status"] == "BLOCK":
    # DO NOT WRITE - inform user of security issue
    # Explain the specific issues from scan_result["issues"]
else:
    # Safe to write
    write(file_path, new_content)
    record_write(session_id, file_path, original, new_content)
```

## Integration Notes

- CodePrism automatically indexes projects in the background on first use
- Check `get_graph_stats` for `index_status` (indexing or ready)
- Index respects `.gitignore` — ignored files are not indexed
- Changes made in editor while session runs are not seen until server restart (unless using CodePrism's write tools)
- Index lives in platform's user-data directory, not in the repository

## Supported Languages

CodePrism supports 10 languages with full feature coverage:
- Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, PHP

## Performance Benchmarks

On real-world codebases:
- psf/requests: 88.9% token reduction
- pallets/flask: 91.6% token reduction
- encode/httpx: 93.2% token reduction
- Average: 91% across production codebases

## Known Limitations

- Call linking by import works for Python only; other languages link by name (common names may link incorrectly)
- Methods with same name in different classes of one Python file share one symbol
- Python definitions inside try/if blocks are not indexed
- Editor changes not seen by running server unless using CodePrism write tools

## Error Handling

If CodePrism tools return errors:
- Verify the project is indexed (check `get_graph_stats`)
- Ensure file paths are relative to project root
- Use longer paths for ambiguous file names
- For unindexed files, indexing will be triggered automatically

## When NOT to Use CodePrism

- For tiny projects (<50 files) where reading files is fast enough
- When you need exact implementation bodies (graph provides structure, not full code)
- For non-code files (config, markdown, etc.)
- When working with files that are git-ignored (not indexed)
