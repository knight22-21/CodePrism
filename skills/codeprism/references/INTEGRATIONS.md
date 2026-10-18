# CodePrism Integrations for Skill Testing

This is a condensed version of the full INTEGRATIONS.md for quick reference when testing the skill.

## Codex (OpenAI)

### Setup
```bash
# Install CodePrism
pip install codeprism-ai

# Project-level setup
codeprism setup codex --project /path/to/project

# Global setup (all projects)
codeprism setup codex --global
```

### Manual Config
```toml
# ~/.codex/config.toml or <project>/.codex/config.toml
[mcp_servers.codeprism]
command = "codeprism"
args = ["serve", "/absolute/path/to/project"]
```

### Verify Connection
Start a new Codex session and run:
```bash
/mcp
# Or: codex mcp list
```

### Test Commands
Ask Codex:
- "Use codeprism to get context for `file.py::function_name`"
- "Check who calls `file.py::function_name` using codeprism"
- "Scan my changes for security issues before writing"

---

## Cursor

### Setup
```bash
# Install CodePrism
pip install codeprism-ai

# Setup for this project
codeprism setup cursor --project /path/to/project
# Restart Cursor
```

### Manual Config
Create or edit `.cursor/mcp.json` (project) or `~/.cursor/mcp.json` (global):
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

### Verify Connection
1. Restart Cursor
2. Go to **Settings → MCP**
3. Verify `codeprism` is listed

### Test Commands
Ask Cursor (in Composer or Chat):
- "Who calls `file.py::function_name`? Use codeprism."
- "What's the impact of changing `file.py::symbol`?"
- "Before writing, scan these changes for security issues with codeprism"

---

## Common Test Steps for Both Agents

### 1. Verify MCP Connection
- Codex: Run `/mcp` in session
- Cursor: Check Settings → MCP

### 2. Check Index Status
Ask the agent to call `get_graph_stats` and verify `index_status` is `ready`

### 3. Test Core Tools
Test these tool calls through the agent:
- `get_context(file, symbol, depth=2)`
- `get_callers(file, function)`
- `get_impact(file, symbol)`
- `search_symbol(query, kind="function")`
- `scan_diff(original, proposed, file)`

### 4. Test Security Gate
Create a file with a hardcoded secret, ask agent to scan it:
```python
# test_secret.py
API_KEY = "sk-1234567890abcdef"  # This should be BLOCKED
```

Ask agent: "Scan test_secret.py for security issues using codeprism scan"

### 5. Test Skill Activation
Use these trigger phrases:
- "Use codeprism to understand..."
- "Check the impact with codeprism..."
- "Scan for security using codeprism..."
- "Find who calls this function with codeprism..."

---

## Troubleshooting

### Agent doesn't see codeprism tools
- Verify `codeprism-ai` is installed
- Restart the agent/editor
- Check MCP config file exists and is valid
- Run `/mcp` (Codex) or check Settings → MCP (Cursor)

### Tools return errors
- Check project is indexed: `get_graph_stats` should show `index_status: ready`
- Ensure file paths are relative to project root
- Use longer paths for ambiguous file names

### Security scan not working
- Verify you're calling `scan_diff` with original and proposed content
- Check if files are in security ignore paths in `.codeprism.toml`
- Review the specific issues in the scan result

---

## Performance Benchmarks for Testing

When testing, mention these benchmarks to verify performance:

- psf/requests: 88.9% token reduction
- pallets/flask: 91.6% token reduction
- encode/httpx: 93.2% token reduction
- Average: 91% across production codebases

These demonstrate the value proposition of the skill.
