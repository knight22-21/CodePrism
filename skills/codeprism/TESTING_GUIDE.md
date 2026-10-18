# CodePrism Skill - Testing Guide for Codex and Cursor

This guide walks you through testing the CodePrism skill on Codex and Cursor before submitting to Agensi.io.

## Prerequisites

1. **Install CodePrism:**
   ```bash
   pip install codeprism-ai
   ```

2. **Run the test script** (optional but recommended):
   ```bash
   cd skills/codeprism/scripts
   python test_skill.py
   ```

3. **Have a test project ready** - preferably a medium-sized Python project (100+ files) to see the token reduction benefits.

---

## Testing on Codex (OpenAI)

### Step 1: Setup CodePrism for Codex

```bash
# Option A: Global setup (recommended for testing)
codeprism setup codex --global

# Option B: Project-specific setup
codeprism setup codex --project /path/to/your/test/project
```

### Step 2: Verify MCP Connection

Start a new Codex session and run:
```bash
/mcp
```

You should see `codeprism` listed in the output.

### Step 3: Test Skill Activation

Try these prompts to verify the skill loads:

**Prompt 1:**
```
Use codeprism to understand the structure of this codebase.
```

**Expected:**
- Agent should call `mcp_list_tools` for codeprism
- Agent should call `get_graph_stats` to check index status
- Agent should report back about the project structure

**Prompt 2:**
```
Who calls the main function in this project? Use codeprism to find out.
```

**Expected:**
- Agent should call `search_symbol` to find the main function
- Agent should call `get_callers` to get call relationships
- Agent should NOT grep through files

### Step 4: Test Core Tools

**Test get_context:**
```
Use codeprism to get context for a function in this codebase. Pick any function and explain what it does, who calls it, and what it calls.
```

**Verify:**
- Agent calls `get_context(file, symbol, depth=2)`
- Agent provides signature, callers, and callees
- Token usage is low (should mention graph query)

**Test get_impact:**
```
I want to refactor a core function. Use codeprism to check the impact before I start.
```

**Verify:**
- Agent calls `get_impact` for a symbol
- Agent reports severity and dependents
- Agent lists affected test files

**Test search_symbol:**
```
Find all functions that handle authentication in this codebase using codeprism.
```

**Verify:**
- Agent calls `search_symbol` with query "auth" and kind "function"
- Agent presents results without grepping
- Results are structured and accurate

### Step 5: Test Security Gate

Create a test file with a security issue:
```python
# test_security.py
API_KEY = "sk-1234567890abcdef"  # Hardcoded secret
def get_data():
    return API_KEY
```

**Prompt:**
```
Scan test_security.py for security issues using codeprism before I commit it.
```

**Expected:**
- Agent calls `scan_file` or `scan_diff`
- Agent reports BLOCK status
- Agent explains the hardcoded API key issue
- Agent advises not to commit

### Step 6: Test Security Gate on Write

**Prompt:**
```
Write a function that handles user passwords. Use codeprism to scan it before writing.
```

**Expected:**
- Agent writes proposed code
- Agent calls `scan_diff` with original and proposed content
- If security issues found, agent refuses to write and explains why
- If safe, agent writes and reports status

### Step 7: Test Token Reduction

**Prompt:**
```
Explain how this codebase is structured. Compare using codeprism vs reading files directly.
```

**Expected:**
- Agent mentions querying the graph is more efficient
- Agent references the 91% token reduction benchmark
- Agent demonstrates using graph tools instead of reading files

---

## Testing on Cursor

### Step 1: Setup CodePrism for Cursor

```bash
codeprism setup cursor --project /path/to/your/test/project
```

**Restart Cursor** after running this command.

### Step 2: Verify MCP Connection

1. Open Cursor
2. Go to **Settings → MCP**
3. Verify `codeprism` is listed and connected

### Step 3: Test in Cursor Chat

**Prompt:**
```
Use codeprism to understand who calls the main entry point of this project.
```

**Expected:**
- Cursor calls `search_symbol` to find the main function
- Cursor calls `get_callers` to get relationships
- Cursor presents structured results

### Step 4: Test in Cursor Composer (Agent Mode)

**Prompt in Composer:**
```
Refactor the authentication module. Use codeprism to check the impact first, then make the changes. Scan for security issues before writing.
```

**Expected (Agent Mode):**
- Cursor autonomously calls `get_impact` for auth symbols
- Cursor analyzes blast radius
- Cursor makes changes
- Cursor calls `scan_diff` before writing
- Cursor reports security status

### Step 5: Test Security Gate

Same as Codex Step 5 - create test_security.py and ask Cursor to scan it.

### Step 6: Test Skill Activation Triggers

Try these phrases to ensure the skill activates:
- "Use codeprism to..."
- "Check the impact with codeprism..."
- "Scan for security using codeprism..."
- "Find who calls this with codeprism..."
- "Get context for this function using codeprism..."

---

## Testing Checklist

Before submitting to Agensi, verify all items:

### CodePrism Setup
- [ ] `codeprism-ai` is installed
- [ ] MCP server is configured correctly
- [ ] Agent can see codeprism tools (`/mcp` or Settings → MCP)
- [ ] Project is indexed (`get_graph_stats` returns `ready`)

### Skill Activation
- [ ] Agent loads skill on trigger phrases
- [ ] Agent calls `mcp_list_tools` before using tools
- [ ] Agent doesn't fall back to grep/read unnecessarily

### Tool Usage
- [ ] `get_context` is called before reading files
- [ ] `get_callers` is used instead of grep
- [ ] `get_impact` is called before refactoring
- [ ] `search_symbol` is used for finding symbols
- [ ] `scan_diff` is called before writes

### Security Gate
- [ ] BLOCK status prevents writes
- [ ] Agent explains security issues
- [ ] WARN status allows writes with warnings
- [ ] Test with hardcoded secrets is blocked

### Cross-Agent Compatibility
- [ ] Works on Codex
- [ ] Works on Cursor
- [ ] Instructions are agent-agnostic
- [ ] No agent-specific features used

### Error Handling
- [ ] Agent handles unindexed files gracefully
- [ ] Agent uses longer paths for ambiguous names
- [ ] Agent checks index status when tools fail

---

## Common Issues and Solutions

### Issue: Agent doesn't see codeprism tools
**Solution:**
- Verify installation: `pip show codeprism-ai`
- Restart the agent/editor
- Check MCP config file exists
- Run `/mcp` (Codex) or check Settings → MCP (Cursor)

### Issue: Tools return "file not indexed"
**Solution:**
- Check `get_graph_stats` for index status
- If `indexing`, wait for it to complete
- If no index, run `codeprism index /path/to/project`

### Issue: Agent falls back to reading files
**Solution:**
- Verify skill instructions are clear
- Check that agent calls `mcp_list_tools` first
- Ensure trigger phrases match the skill description

### Issue: Security scan not blocking
**Solution:**
- Verify test code actually has security issues
- Check if files are in security ignore paths
- Review scan result for status

---

## Performance Validation

After testing, note these metrics:

**Token Reduction:**
- Without CodePrism: ~8,000-40,000 tokens per task
- With CodePrism: ~200-800 tokens per task
- Reduction: 60-80% (target), 91% (achieved on benchmarks)

**Tool Response Times:**
- `get_context`: < 100ms
- `get_callers`: < 100ms
- `get_impact`: < 200ms
- `search_symbol`: < 100ms
- `scan_diff`: < 500ms

**Indexing Time:**
- Small project (< 100 files): < 2 seconds
- Medium project (100-1000 files): < 10 seconds
- Large project (> 1000 files): < 40 seconds

---

## Ready for Submission?

If all tests pass:
1. Document the test results
2. Take screenshots of successful tool calls
3. Record token reduction metrics
4. Note any edge cases or limitations
5. Proceed to Agensi.io creator application

If tests fail:
1. Review the failure in detail
2. Check the troubleshooting section
3. Fix the issue in the skill
4. Re-test before submission
