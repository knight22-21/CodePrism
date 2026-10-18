# CodePrism Skill - Quick Reference

This folder contains reference documentation for the CodePrism skill. Use these when you need detailed setup instructions or want to understand specific features.

## Quick Start for Agent Testing

### For Codex (OpenAI)

**Setup:**
```bash
# Install CodePrism
pip install codeprism-ai

# Setup for this project only
codeprism setup codex --project /path/to/your/project

# Or globally for all projects
codeprism setup codex --global
```

**Verify Connection:**
```bash
# Start a new Codex session and run:
/mcp
# Or: codex mcp list
```

**Test the Skill:**
Ask Codex:
- "Use the codeprism skill to understand who calls the `process_payment` function"
- "Check the impact of changing `utils/auth.py::verify_token`"
- "Scan my changes for security issues before writing"

### For Cursor

**Setup:**
```bash
# Install CodePrism
pip install codeprism-ai

# Setup for this project
codeprism setup cursor --project /path/to/your/project
```

**Verify Connection:**
1. Restart Cursor
2. Go to **Settings → MCP**
3. Verify `codeprism` is listed as connected

**Test the Skill:**
Ask Cursor (in Composer or Chat):
- "Who calls the `handle_request` function? Use codeprism to find out."
- "What's the impact if I refactor `core/models.py::User`?"
- "Before you write these changes, scan them for security issues using codeprism"

## Testing Checklist

Before submitting to Agensi, verify:

### 1. Skill Activation
- [ ] Agent loads the skill when you mention "codeprism", "graph", "context", "impact", "callers"
- [ ] Agent calls `mcp_list_tools` for codeprism before using tools
- [ ] Agent queries the graph instead of reading files for structural questions

### 2. Tool Usage
- [ ] `get_context` is called before reading files to understand functions
- [ ] `get_callers` is used instead of grep for finding call relationships
- [ ] `get_impact` is called before refactoring
- [ ] `scan_diff` is called before every file write
- [ ] `search_symbol` is used instead of grep for finding symbols

### 3. Security Gate
- [ ] BLOCK status from `scan_diff` prevents file writes
- [ ] Agent explains security issues to the user
- [ ] WARN status allows writes but surfaces issues

### 4. Cross-Agent Compatibility
- [ ] Works on Codex (test with `/mcp` to verify connection)
- [ ] Works on Cursor (test in Settings → MCP)
- [ ] Instructions are clear and agent-agnostic
- [ ] No agent-specific tool calls or features

### 5. Error Handling
- [ ] Agent handles unindexed files gracefully
- [ ] Agent uses longer paths for ambiguous file names
- [ ] Agent checks `get_graph_stats` for index status

## Test Scenarios

### Scenario 1: Understanding a Function
**Prompt:** "Use codeprism to explain what `process_payment` does and who calls it."

**Expected Behavior:**
1. Agent calls `mcp_list_tools` for codeprism
2. Agent calls `get_context` with the file and symbol
3. Agent reads the file only if implementation details are needed
4. Agent provides structured answer with callers, callees, and signature

### Scenario 2: Refactoring Impact
**Prompt:** "I want to rename `utils/helpers.py::format_date`. What would break?"

**Expected Behavior:**
1. Agent calls `get_impact` for the symbol
2. Agent analyzes severity and dependents
3. Agent lists affected files and test files
4. Agent provides blast radius assessment

### Scenario 3: Security Check
**Prompt:** "Write a function that handles user passwords. Use codeprism to check it before writing."

**Expected Behavior:**
1. Agent writes the proposed code
2. Agent calls `scan_diff` with original and proposed content
3. If BLOCK status, agent refuses to write and explains issues
4. If PASS/WARN, agent writes and reports any warnings

### Scenario 4: Symbol Search
**Prompt:** "Find all functions that handle authentication in this codebase."

**Expected Behavior:**
1. Agent calls `search_symbol` with query "auth" and kind "function"
2. Agent gets results from the graph
3. Agent presents findings without grepping through files

## Troubleshooting

### CodePrism not connecting
- Verify `codeprism-ai` is installed: `pip show codeprism-ai`
- Check MCP config file was created correctly
- Restart the agent/editor after setup
- Run `/mcp` (Codex) or check Settings → MCP (Cursor)

### Tools not working
- Verify project is indexed: Check `get_graph_stats` returns `index_status: ready`
- Ensure file paths are relative to project root
- Use longer paths if ambiguous file names are reported

### Security scan blocking everything
- Check if files are in security ignore paths (`.codeprism.toml`)
- Verify scan is using the correct original vs proposed content
- Review specific issues in the scan result

## Performance Tips

- Use `depth=2` for `get_context` (default and recommended)
- Call `get_module_summary` for file-level understanding before reading full files
- Use `search_symbol` with `kind` filter to narrow results
- Record reads with `record_read` to avoid re-fetching in long sessions

## Integration Notes

- CodePrism indexes automatically in the background on first use
- Index respects `.gitignore` — ignored files are not indexed
- Index lives in platform's user-data directory, not in repository
- Editor changes not seen by running server unless using CodePrism write tools
