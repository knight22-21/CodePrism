# CodePrism Skill

A SKILL.md-formatted skill for the CodePrism knowledge graph tool, designed for submission to Agensi.io.

## What This Skill Does

Teaches AI agents to use CodePrism's knowledge graph instead of reading entire files, achieving 60-80% token reduction on large codebases.

### Key Features
- Query code structure (callers, callees, impact) without reading files
- Security scanning before every write (blocks secrets, injection, weak crypto)
- Session tracking to avoid re-fetching context
- Support for 10 programming languages

### Performance
- **91% token reduction** averaged across real-world codebases (requests, flask, httpx)
- Queries return in < 400 tokens vs 8,000-40,000 tokens for file reading
- Security gate prevents critical issues before they reach disk

---

## Folder Structure

```
codeprism/
├── SKILL.md                    # Main skill file (required)
├── README.md                   # This file
├── MARKETPLACE_LISTING.md      # Draft for Agensi marketplace
├── TESTING_GUIDE.md           # Step-by-step testing instructions
├── references/                 # Supporting documentation
│   ├── README.md              # Quick reference for agents
│   └── INTEGRATIONS.md        # Setup instructions for Codex & Cursor
└── scripts/                    # Helper scripts
    └── test_skill.py          # Automated test suite
```

---

## Quick Start for Testing

### 1. Install CodePrism
```bash
pip install codeprism-ai
```

### 2. Run Test Script (Optional)
```bash
cd scripts
python test_skill.py
```

### 3. Setup for Your Agent

**For Codex:**
```bash
codeprism setup codex --global
# Start new Codex session
# Run: /mcp to verify connection
```

**For Cursor:**
```bash
codeprism setup cursor --project /path/to/project
# Restart Cursor
# Check: Settings → MCP
```

### 4. Test the Skill
See `TESTING_GUIDE.md` for detailed test scenarios.

---

## Testing Checklist

Before submitting to Agensi, verify:

- [ ] Skill activates on trigger phrases ("codeprism", "graph", "context", "impact")
- [ ] Agent calls `mcp_list_tools` before using CodePrism tools
- [ ] Agent queries graph instead of reading files for structural questions
- [ ] `get_context` is called before reading files
- [ ] `get_callers` is used instead of grep
- [ ] `get_impact` is called before refactoring
- [ ] `scan_diff` is called before every file write
- [ ] BLOCK status from security scan prevents writes
- [ ] Works on both Codex and Cursor
- [ ] No agent-specific features used

---

## Submission to Agensi.io

### Step 1: Complete Testing
Follow `TESTING_GUIDE.md` to test on Codex and Cursor.

### Step 2: Prepare Marketplace Listing
Edit `MARKETPLACE_LISTING.md` with your final description and pricing.

### Step 3: Apply as Creator
1. Go to https://www.agensi.io
2. Sign up and apply for creator status
3. Complete vetting process
4. Configure payouts (Stripe or USDC)

### Step 4: Submit Skill
1. Upload the `codeprism/` folder to Agensi
2. Wait for security scan (8-point check)
3. Wait for human review
4. Once approved, it goes live

---

## Skill Contents

### SKILL.md
The main skill file with:
- YAML frontmatter (name, description, license, metadata, compatibility)
- Detailed instructions for agents
- Tool usage patterns and examples
- Workflow examples
- Error handling guidance

### references/
Documentation for agents to reference:
- `README.md` - Quick reference and testing checklist
- `INTEGRATIONS.md` - Setup instructions for Codex and Cursor

### scripts/
Helper scripts:
- `test_skill.py` - Automated test suite to verify CodePrism is working

### Additional Files
- `MARKETPLACE_LISTING.md` - Draft for Agensi marketplace submission
- `TESTING_GUIDE.md` - Detailed testing instructions for Codex and Cursor
- `README.md` - This file

---

## Key Selling Points for Agensi

1. **Clear Value Proposition** - 91% token reduction = significant cost savings
2. **Security Features** - Prevents secrets, injection, weak crypto before writes
3. **Broad Compatibility** - Works with 10 languages and all major agents
4. **Proven Performance** - Benchmarked on real-world codebases
5. **Active Development** - Well-maintained open-source project

---

## Pricing Recommendation

**$19.99 (one-time purchase)**

Rationale:
- Competitor skills in Code Quality & Review: $9-$24
- Clear ROI through token cost savings
- One-time purchase (tool, not service)
- Automatic updates to all buyers

---

## Support

- GitHub: https://github.com/knight22-21/CodePrism
- Issues: https://github.com/knight22-21/CodePrism/issues
- Documentation: https://github.com/knight22-21/CodePrism#readme

---

## License

MIT
