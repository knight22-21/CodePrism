# CodePrism - Marketplace Listing

Ready for submission to Agensi.io

---

## Title
CodePrism Knowledge Graph Assistant - 91% Token Reduction for AI Agents

## Short Description (under 100 chars)
Knowledge graph for AI agents - 91% token reduction on large codebases

## Full Description
CodePrism maintains a persistent knowledge graph of your project — every function, class, import, and data-flow relationship. Instead of your AI agent reading 40 files to understand one function, it queries the graph and gets exactly what it needs in under 200 tokens.

**Achieved 91% token reduction across real-world codebases** (psf/requests, pallets/flask, encode/httpx).

### What It Does
- **Indexes** your codebase using tree-sitter AST parsing (10 languages: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, PHP)
- **Maintains** a knowledge graph per project — built automatically in the background
- **Answers** precise structural questions: callers, callees, impact, dependencies, data flow
- **Guards** every write with a security scanner — secrets, injection, weak crypto, and more
- **Tracks** agent sessions — what was read, what was written, undo support

### Why You Need This
Without CodePrism, your agent reads 30–50 files per task, costing 8,000–40,000 tokens per context window. With CodePrism, it queries the graph in 1–3 targeted calls, using only 200–800 tokens for equivalent context.

### Security Features
Prevents security issues before they reach disk:
- **Secrets**: Hardcoded passwords, API keys, AWS credentials
- **Injection**: SQL injection, eval(), exec(), shell=True
- **Weak crypto**: MD5, SHA-1, DES, RC4
- **Unsafe dependencies**: pickle, unsafe yaml.load, marshal

### Use Cases
- Understanding code structure without reading entire files
- Impact analysis before refactoring
- Finding who calls a function or what a function calls
- Security scanning before writing code
- Searching for symbols by name or type
- Dependency analysis

### Performance Benchmarks
| Corpus | Baseline | CodePrism | Reduction |
|--------|----------|-----------|-----------|
| psf/requests | 6,406 tokens | 714 tokens | **88.9%** |
| pallets/flask | 9,558 tokens | 805 tokens | **91.6%** |
| encode/httpx | 12,685 tokens | 857 tokens | **93.2%** |

### Works With
- Claude Code
- Cursor
- Codex (OpenAI)
- Windsurf
- Continue.dev
- Zed
- VS Code with GitHub Copilot
- Any MCP-compatible agent

### Installation
```bash
pip install codeprism-ai
codeprism setup <your-agent> --global
```

Your agent can now call tools like `get_context`, `get_impact`, `scan_diff` instead of reading raw files.

---

## Category
Code Quality & Review

## Tags
- knowledge-graph
- code-analysis
- security
- token-optimization
- mcp
- ast-parsing
- refactoring
- impact-analysis

## Pricing
$19.99 (one-time purchase)

### Pricing Rationale
- Competitor skills in Code Quality & Review: $9-$24
- Clear value proposition: 91% token reduction = significant cost savings
- One-time purchase (tool, not service)
- Automatic updates to all buyers

## Support
- GitHub Issues: https://github.com/knight22-21/CodePrism/issues
- Documentation: https://github.com/knight22-21/CodePrism#readme

## License
MIT
