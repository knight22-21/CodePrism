# CodePrism Skill - Examples

This document provides practical examples of using the CodePrism skill with AI agents.

## Example 1: Understanding a Complex Function

**Scenario:** You want to understand a complex payment processing function.

**Prompt:**
```
Use codeprism to understand the process_payment function in payments/processor.py. Explain what it does, who calls it, what it calls, and any security considerations.
```

**Expected Agent Response:**
1. Calls `search_symbol` to locate the function
2. Calls `get_context(payments/processor.py, process_payment, depth=2)`
3. Provides:
   - Function signature and purpose
   - List of direct callers (which parts of the app use it)
   - List of direct callees (what dependencies it has)
   - Types and parameters
   - Any security-related calls

**Tokens used:** ~250 tokens (vs ~2,000 tokens for reading the file)

---

## Example 2: Refactoring Impact Analysis

**Scenario:** You want to rename a core utility function.

**Prompt:**
```
I want to rename the format_date function in utils/helpers.py. Use codeprism to check the impact before I start. Tell me what will break.
```

**Expected Agent Response:**
1. Calls `get_impact(utils/helpers.py, format_date)`
2. Reports:
   - Severity (HIGH/MEDIUM/LOW)
   - Number of direct dependents
   - List of affected files
   - Affected test files
   - Transitive dependents (files that depend on dependents)

**Tokens used:** ~300 tokens (vs ~5,000 tokens for manual analysis)

---

## Example 3: Security Check Before Commit

**Scenario:** You wrote a new authentication function and want to check for security issues.

**Prompt:**
```
I just wrote a new authentication function in auth/login.py. Use codeprism to scan it for security issues before I commit.
```

**Expected Agent Response:**
1. Calls `scan_file(auth/login.py)` or `scan_diff` with changes
2. Reports:
   - Status (PASS/WARN/BLOCK)
   - Any secrets detected
   - Any injection vulnerabilities
   - Any weak cryptography
   - Any unsafe dependencies

**If BLOCK:**
- Agent refuses to commit
- Explains the specific issues
- Suggests fixes

**If PASS:**
- Agent approves commit
- Reports any warnings

---

## Example 4: Finding All Authentication Functions

**Scenario:** You need to audit all authentication-related code.

**Prompt:**
```
Find all functions in this codebase that handle authentication. Use codeprism to search for them.
```

**Expected Agent Response:**
1. Calls `search_symbol("auth", kind="function")`
2. Presents:
   - List of matching functions
   - Their locations
   - Brief descriptions
   - Ranking by relevance

**Tokens used:** ~200 tokens (vs grepping through all files)

---

## Example 5: Understanding Module Dependencies

**Scenario:** You want to know what a module depends on.

**Prompt:**
```
Use codeprism to analyze the dependencies of the auth module. What does it import and what depends on it?
```

**Expected Agent Response:**
1. Calls `get_dependencies(auth/login.py)` for imports
2. Calls `get_dependents(auth/login.py)` for dependents
3. Reports:
   - Internal dependencies (other project files)
   - External dependencies (libraries)
   - Files that depend on this module
   - Dependency graph overview

---

## Example 6: Data Flow Analysis

**Scenario:** You want to trace where user input flows.

**Prompt:**
```
Trace where data from the handle_request function flows. Use codeprism to find all the sinks.
```

**Expected Agent Response:**
1. Calls `get_data_flow(api/handlers.py, handle_request)`
2. Reports:
   - Data sources
   - Intermediate processing steps
   - Final sinks (database, API calls, file writes)
   - Security-critical paths

---

## Example 7: Module-Level Understanding

**Scenario:** You're exploring a new codebase and want to understand a module quickly.

**Prompt:**
```
Use codeprism to give me a high-level overview of the core module. What does it do and what are its main components?
```

**Expected Agent Response:**
1. Calls `get_module_summary(codeprism/core/__init__.py)`
2. Reports:
   - Module purpose (narrative summary)
   - Public API (main functions/classes)
   - Key classes
   - Dependencies
   - Complexity score

**Tokens used:** ~150 tokens (vs ~1,000 tokens for reading the file)

---

## Example 8: Team Refactoring Coordination

**Scenario:** Your team is planning a large refactoring and needs to coordinate.

**Prompt:**
```
We're planning to refactor the user model. Use codeprism to check the impact and tell me which teams and files will be affected.
```

**Expected Agent Response:**
1. Calls `get_impact(models/user.py, User)`
2. Reports:
   - Severity assessment
   - List of affected files grouped by module
   - Test files that need updates
   - Suggested coordination points

---

## Example 9: Finding Similar Functions

**Scenario:** You want to find all validation functions.

**Prompt:**
```
Find all functions that validate input. Use codeprism to search for validation-related functions.
```

**Expected Agent Response:**
1. Calls `search_symbol("validate", kind="function")`
2. Presents:
   - All validation functions
   - Their locations
   - Brief descriptions
   - Can group by validation type

---

## Example 10: Session-Aware Long Task

**Scenario:** A long multi-step task where the agent should remember what it has read.

**Prompt:**
```
I need to refactor the payment system. Use codeprism throughout:
1. First, check the impact of changing process_payment
2. Then understand who calls it
3. Then understand what it calls
4. Then make the changes
5. Finally, scan for security issues before writing

Use session tracking to avoid re-reading the same context.
```

**Expected Agent Response:**
1. Calls `get_context` and `record_read` for each query
2. Uses `get_session_context` to check what's already been read
3. Avoids re-fetching the same information
4. Calls `scan_diff` before writes
5. Calls `record_write` to track changes

**Benefits:**
- Token-efficient (no repeated reads)
- Faster (no re-querying)
- Consistent state tracking

---

## Example 11: Cross-Language Analysis

**Scenario:** Your project has Python and TypeScript code.

**Prompt:**
```
Find all functions that call the Python API from the TypeScript frontend. Use codeprism to trace the cross-language calls.
```

**Expected Agent Response:**
1. Searches for API functions in Python
2. Searches for callers in TypeScript
3. Reports:
   - Cross-language call graph
   - Entry points
   - Integration points

---

## Example 12: Performance Investigation

**Scenario:** A function is slow and you want to understand why.

**Prompt:**
```
The export_data function is slow. Use codeprism to analyze what it calls and identify potential bottlenecks.
```

**Expected Agent Response:**
1. Calls `get_context(export_data, depth=2)`
2. Analyzes callees for:
   - Database operations
   - File I/O
   - Network calls
   - Complex computations
3. Reports:
   - Likely bottlenecks
   - Suggested optimization points

---

## Tips for Effective Prompts

### Be Specific About What You Want

**Good:**
```
Use codeprism to find who calls the process_payment function in the payments module.
```

**Bad:**
```
Use codeprism to tell me about process_payment.
```

### Ask for Analysis, Not Just Data

**Good:**
```
Use codeprism to analyze the impact of changing this function and tell me what tests I need to update.
```

**Bad:**
```
Use codeprism to get the impact of this function.
```

### Use CodePrism for Structural Questions

**Good for:**
- Understanding relationships (callers, callees)
- Impact analysis
- Dependency analysis
- Security scanning
- Symbol search

**Not for:**
- Exact implementation details (read the file after getting context)
- Line-by-line code review
- Business logic verification

### Combine with File Reading When Needed

**Good:**
```
Use codeprism to get the context for this function, then read the file if you need implementation details.
```

---

## Common Patterns

### Pattern 1: Quick Overview
```
Use codeprism to give me a quick overview of [module/file].
```

### Pattern 2: Deep Dive
```
Use codeprism to get context for [function] with depth=2, then read the file for implementation details.
```

### Pattern 3: Before Refactoring
```
Use codeprism to check the impact of changing [symbol] before I start refactoring.
```

### Pattern 4: Security Check
```
Use codeprism to scan [file] for security issues before I commit.
```

### Pattern 5: Find Relationships
```
Use codeprism to find all functions that [condition] in this codebase.
```

---

## Token Savings Summary

| Task | Without CodePrism | With CodePrism | Savings |
|------|------------------|----------------|---------|
| Understand function | ~2,000 tokens | ~250 tokens | 87.5% |
| Find callers | ~3,000 tokens | ~300 tokens | 90% |
| Impact analysis | ~5,000 tokens | ~350 tokens | 93% |
| Security scan | ~1,000 tokens | ~150 tokens | 85% |
| Module summary | ~1,000 tokens | ~150 tokens | 85% |

**Average: 88% token reduction**

---

## Next Steps

- Try these examples in your own codebase
- See [User Guide](skill-guide.md) for detailed instructions
- Read [Full Documentation](README.md) for CodePrism features
