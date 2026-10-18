# CodePrism Skill - GitHub Publication Plan

## Repository Structure for Skill Distribution

Create a separate repository or use existing CodePrism repo with a dedicated folder:

```
github.com/knight22-21/codeprism-skill/
├── README.md                    # Main README (for users)
├── SKILL.md                     # The skill file
├── INSTALL.md                   # Installation instructions
├── SPONSORS.md                  # GitHub Sponsors tiers
├── docs/
│   ├── getting-started.md
│   ├── examples.md
│   └── troubleshooting.md
└── assets/
    └── logo.png (optional)
```

## README.md Content

```markdown
# CodePrism Knowledge Graph Skill for AI Agents

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![GitHub Stars](https://img.shields.io/github/stars/knight22-21/codeprism-skill?style=social)](https://github.com/knight22-21/codeprism-skill)

**Stop feeding your AI agent the whole codebase. Give it a graph.**

CodePrism builds a persistent knowledge graph of your project — every function, class, import, and data-flow relationship — and teaches AI agents to query it instead of reading entire files.

## 🚀 What It Does

- **91% token reduction** on large codebases (tested on requests, flask, httpx)
- **Security scanning** before every write (blocks secrets, injection, weak crypto)
- **10 languages supported**: Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, PHP
- **Works with**: Claude Code, Cursor, Codex, Windsurf, and any MCP-compatible agent

## 📊 Performance

| Corpus | Baseline | CodePrism | Reduction |
|--------|----------|-----------|-----------|
| psf/requests | 6,406 tokens | 714 tokens | **88.9%** |
| pallets/flask | 9,558 tokens | 805 tokens | **91.6%** |
| encode/httpx | 12,685 tokens | 857 tokens | **93.2%** |

## 💾 Installation

### Prerequisites
```bash
pip install codeprism-ai
```

### Setup for Your Agent

**Claude Code:**
```bash
codeprism setup claude --global
```

**Codex:**
```bash
codeprism setup codex --global
```

**Cursor:**
```bash
codeprism setup cursor --project /path/to/your/project
```

### Install the Skill

1. Clone this repository
2. Copy `SKILL.md` to your project's `.agents/skills/codeprism/` directory
3. Your agent will automatically load it

Or use with MCP directly - CodePrism includes the skill instructions in `AGENTS.md` when you run setup.

## 🎯 Use Cases

- Understanding code structure without reading entire files
- Impact analysis before refactoring
- Finding who calls a function or what a function calls
- Security scanning before writing code
- Searching for symbols by name or type
- Dependency analysis

## 📖 Documentation

- [Getting Started](docs/getting-started.md)
- [Examples](docs/examples.md)
- [Troubleshooting](docs/troubleshooting.md)
- [Full Documentation](https://github.com/knight22-21/CodePrism#readme)

## 🤝 Contributing

Contributions welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details.

## 💖 Support This Project

If you find this skill useful, please:
- ⭐ Star this repository
- 💖 Sponsor me on GitHub
- 🐛 Report issues
- 📝 Contribute improvements

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

## 🔗 Links

- [CodePrism Core](https://github.com/knight22-21/CodePrism)
- [Agensi Marketplace](https://www.agensi.io) (coming soon)
- [SkillsMP](https://skillsmp.com)
```

## SPONSORS.md Content

```markdown
# 💖 Sponsor CodePrism Skill Development

Support continued development of the CodePrism skill for AI agents.

## Why Sponsor?

- **Keep it free and open source** for everyone
- **Fund new features** (more languages, better security, performance improvements)
- **Support maintenance** (bug fixes, compatibility updates)
- **Get priority support** for your issues
- **Feature requests** from sponsors get prioritized

## Sponsorship Tiers

### ☕ Bronze ($5/month)
- Your name in sponsors list
- Early access to beta features
- Priority on bug fixes

### 🚀 Silver ($15/month)
- All Bronze benefits
- Logo in sponsors section
- Monthly development updates
- Direct Discord access

### 💎 Gold ($50/month)
- All Silver benefits
- Featured sponsor placement
- Custom feature requests considered
- 1-hour consultation call per quarter

### 🏆 Platinum ($100/month)
- All Gold benefits
- Priority on all development
- Custom integrations
- Dedicated support channel
- Sponsor shoutout in all releases

## How to Sponsor

Click the "Sponsor" button at the top of this repository, or visit:
https://github.com/sponsors/knight22-21

## Sponsors

Thank you to all our sponsors!

- [List sponsors here as they join]
```

## Submission to Awesome Lists

Submit to these GitHub lists for maximum reach:

1. **ComposioHQ/awesome-claude-skills**
   - Largest Claude skills list
   - Submit via PR or issue
   - Link: https://github.com/ComposioHQ/awesome-claude-skills

2. **philipbankier/awesome-agent-skills**
   - Curated agent skills directory
   - Submit via PR
   - Link: https://github.com/philipbankier/awesome-agent-skills

3. **VoltAgent/awesome-agent-skills**
   - 380+ skills for multiple platforms
   - Submit via PR
   - Link: https://github.com/VoltAgent/awesome-agent-skills

## PR Template for Awesome Lists

```markdown
## Add CodePrism Skill

### Description
CodePrism teaches AI agents to use a knowledge graph instead of reading entire files, achieving 91% token reduction on large codebases.

### Link
https://github.com/knight22-21/codeprism-skill

### Category
Code Quality & Review / Developer Tools

### Platforms
Claude Code, Cursor, Codex, Windsurf, MCP-compatible agents

### Why This Skill?
- 91% token reduction on real-world codebases
- Security scanning before writes
- 10 languages supported
- Open source with MIT license
```

## Next Steps

1. [ ] Create GitHub repository
2. [ ] Add README.md, SKILL.md, SPONSORS.md
3. [ ] Add documentation folder
4. [ ] Submit to awesome lists
5. [ ] Enable GitHub Sponsors
6. [ ] List on SkillsMP
7. [ ] Add to SkillAgent directory
