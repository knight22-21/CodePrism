# Security Policy

CodePrism reads source code, stores a graph of it on your machine, and exposes that graph to AI agents
through an MCP server. We take reports about it seriously.

## Supported versions

CodePrism is pre-1.0 and moves quickly. Only the **latest release on
[PyPI](https://pypi.org/project/codeprism-ai/)** receives security fixes. If you are on an older version,
upgrade first (`pip install -U codeprism-ai`) and check whether the problem still exists.

| Version | Supported |
| ------- | --------- |
| Latest release (currently 0.1.x) | Yes |
| Anything older | No, please upgrade |

Once a 1.0 release exists, this table will list the supported minor versions.

## Reporting a vulnerability

**Please do not open a public GitHub issue, discussion or pull request for a security problem.**

Report it privately by either of these routes:

1. **GitHub private vulnerability reporting:** the **Report a vulnerability** button on the
   [Security tab](https://github.com/knight22-21/CodePrism/security/advisories/new), if it is shown.
2. **Email:** krishnatyagibest321@gmail.com with the subject `CodePrism security: <short summary>`.

Please include:

- the CodePrism version (`pip show codeprism-ai`), Python version and operating system;
- a description of the problem and its impact;
- steps to reproduce, ideally a minimal script or sample repository;
- any suggested fix or mitigation, if you have one.

Do not include real secrets or private source code in a report; a synthetic example is enough.

## What to expect

| Step | Target |
| ---- | ------ |
| Acknowledgement of your report | within 3 business days |
| Initial assessment (accepted, need more information, or declined, with a reason) | within 7 days |
| Status updates while we work on it | at least every 14 days |
| Fix released for a confirmed issue | depends on severity; we aim for 30 days for high-severity issues |

This is a volunteer-maintained project, so these are targets, not guarantees. If you hear nothing after
the acknowledgement window, please send a reminder.

If the report is **accepted**, we will fix it in private, release a patched version, publish a GitHub
security advisory and credit you in the release notes unless you prefer to stay anonymous. If it is
**declined** (for example because it is out of scope or not reproducible), we will explain why.

## Coordinated disclosure

Please give us a reasonable chance to release a fix before you share details publicly. We ask for **up to
90 days** from your report, and we will tell you if we need longer. We are happy to agree a shorter or
earlier date with you when a fix is ready sooner, or when the issue is already being exploited.

We will not take legal action against anyone who reports a vulnerability in good faith, follows this
policy, and avoids harming other people's data or systems.

## Scope

**In scope**

- The `codeprism-ai` package: the CLI, the Python API, the parsers and indexer, the query layer.
- The MCP server (`codeprism serve`, stdio and SSE transports) and its tools.
- The security gate and scanner (for example a way to make a `BLOCK` finding pass undetected is a
  vulnerability in a feature we advertise).
- `codeprism setup` and the configuration files it writes.
- Our release and CI pipeline (`.github/workflows`), including how the package is published.

**Out of scope**

- Vulnerabilities in third-party dependencies, unless CodePrism uses them in a way that makes them
  exploitable. Please report those upstream (we still welcome a heads-up).
- Findings that need an attacker who already has local access to your account or can already edit your
  CodePrism data directory or `.codeprism.toml`.
- Missing security detectors, false positives and false negatives in the scanner. These are bugs, not
  vulnerabilities; please open a normal issue.
- Denial of service from indexing an enormous or adversarial repository on your own machine.
- Reports from automated scanners without a demonstrated impact.

## Known security-relevant behaviour

These are documented design choices, not vulnerabilities, so you do not need to report them. They are
worth knowing about when you deploy CodePrism.

- **SSE transport has no authentication and binds to `127.0.0.1` only.** Do not expose it to a network
  without a reverse proxy that authenticates requests. Remote binding and authentication are tracked in
  [#45](https://github.com/knight22-21/CodePrism/issues/45).
- **The index is a local database of your code's structure.** It is stored in your user data directory,
  not encrypted, with the permissions of that directory. Treat it like the source it was built from.
- **`codeprism setup` edits agent and editor configuration files** in your home or project directory.
  Some editors' files are currently not handled safely; see
  [#43](https://github.com/knight22-21/CodePrism/issues/43).
- **MCP tools run with your user's permissions.** An agent connected to CodePrism can read anything the
  index covers and can ask it to record writes. Only connect agents you trust.

## Safe harbour for security research on this repository

Testing against your own installation or a local test project is fine. Please do not test against
other people's systems, and do not run load tests against infrastructure you do not own.

## Questions

For general questions about this policy, open a regular
[discussion or issue](https://github.com/knight22-21/CodePrism/issues) that does not contain vulnerability
details.
