# CodePrism Skill - Installation Guide

This guide explains how to install and use the CodePrism skill for AI agents.

## Quick Installation

### Option 1: Automatic Setup (Recommended)

CodePrism includes the skill instructions automatically when you run setup:

```bash
pip install codeprism-ai
codeprism setup <agent> --global
```

The skill instructions are written to `AGENTS.md` in your project, which most AI agents read automatically.

### Option 2: Manual Installation

If you want to manually install the skill:

**Step 1: Download the skill**
```bash
# From GitHub release
wget https://github.com/knight22-21/CodePrism/releases/download/skill-v1.0.0/SKILL.md

# Or copy from this repository
cp skill-distribution/SKILL.md ~/.agents/skills/codeprism/
```

**Step 2: Configure your agent**

**Claude Code:**
```bash
# The skill will be auto-loaded from AGENTS.md
# No additional configuration needed
```

**Codex:**
```bash
# The skill will be auto-loaded from AGENTS.md
# No additional configuration needed
```

**Cursor:**
```bash
# The skill will be auto-loaded from AGENTS.md
# No additional configuration needed
```

## Installation by Agent Type

### Claude Code

```bash
# Install CodePrism
pip install codeprism-ai

# Setup globally (all projects)
codeprism setup claude --global

# Restart Claude Code
# The skill is now available in all your projects
```

### Codex (OpenAI)

```bash
# Install CodePrism
pip install codeprism-ai

# Setup globally (all projects)
codeprism setup codex --global

# Start a new Codex session
# The skill is now available
```

### Cursor

```bash
# Install CodePrism
pip install codeprism-ai

# Setup for a specific project
codeprism setup cursor --project /path/to/your/project

# Restart Cursor
# The skill is now available for that project
```

### Windsurf

Manual configuration required. See [INTEGRATIONS.md](INTEGRATIONS.md) for details.

### Continue.dev

Manual configuration required. See [INTEGRATIONS.md](INTEGRATIONS.md) for details.

### Zed

Manual configuration required. See [INTEGRATIONS.md](INTEGRATIONS.md) for details.

## Verification

### Verify CodePrism is Connected

**Claude Code:**
```bash
# In Claude Code, run:
/mcp
# Look for "codeprism" in the list
```

**Codex:**
```bash
# In Codex, run:
/mcp
# Or: codex mcp list
# Look for "codeprism" in the list
```

**Cursor:**
```bash
# Go to Settings → MCP
# Verify "codeprism" is listed and connected
```

### Verify the Skill is Loaded

Test with a simple prompt:

```
Use codeprism to understand the structure of this codebase.
```

The agent should:
1. Call `mcp_list_tools` for codeprism
2. Call `get_graph_stats` to check index status
3. Provide a structural overview using graph queries

## Troubleshooting

### Skill Not Loading

**Problem:** Agent doesn't use CodePrism tools

**Solutions:**
1. Verify CodePrism is installed: `pip show codeprism-ai`
2. Check MCP connection (see verification above)
3. Restart your agent/editor
4. Ensure `AGENTS.md` exists in your project
5. Check that skill description matches your prompt

### Tools Not Working

**Problem:** `get_context`, `get_impact`, etc. return errors

**Solutions:**
1. Check project is indexed: `get_graph_stats` should show `index_status: ready`
2. Ensure file paths are relative to project root
3. Use longer paths if ambiguous file names are reported
4. Verify you're in a git repository (for project detection)

### Index Not Building

**Problem:** Project not indexing automatically

**Solutions:**
1. Run manual index: `codeprism index /path/to/project`
2. Check that you're in a git repository
3. Verify `.gitignore` isn't excluding all files
4. Check available disk space

## Uninstallation

To remove the skill:

```bash
# Remove AGENTS.md (or the codeprism section)
rm AGENTS.md

# Or remove just the codeprism section between markers
# The section is between <!-- codeprism-instructions --> markers
```

## Next Steps

- Read the [Skill Guide](docs/skill-guide.md) for detailed usage
- Check [Examples](docs/skill-examples.md) for common workflows
- See [Full Documentation](README.md) for CodePrism features

## Support

- GitHub Issues: https://github.com/knight22-21/CodePrism/issues
- Documentation: https://github.com/knight22-21/CodePrism#readme
