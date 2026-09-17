# CodePrism Benchmark Results

This document records all benchmark runs measuring CodePrism's token reduction and answer accuracy
against reading raw source files.

---

## Methodology

### Level 1 — Token Reduction + Accuracy

**Goal:** Quantify how many fewer tokens an AI agent needs when using CodePrism graph queries
instead of reading raw files.

**Baseline prompt** — simulates an agent without CodePrism:
reads every `relevant_files` entry for the task, concatenates them into a single context block,
appends the natural-language query.

**CodePrism prompt** — simulates an agent using the graph:
calls only the tools listed in `cp_tools` (`get_context`, `get_callers`, `get_impact`,
`get_dependencies`), serializes the JSON result, appends the same query.

**Token counting:** [tiktoken](https://github.com/openai/tiktoken) `cl100k_base` (GPT-4 tokenizer).
Counts may differ from Claude's tokenizer by ±5–10%.

**Accuracy (LLM-as-judge):** Both the baseline prompt and CodePrism prompt are sent to a judge model
with the ground truth. The judge returns a score 0–1 representing how well the answer matches.
Judge model: `gpt-oss:120b` via [Ollama cloud](https://ollama.com). Reasoning model — uses internal
chain-of-thought before outputting the score.

**Task types:**

| Type | What it tests |
|---|---|
| `symbol_lookup` | Signature, docstring, purpose of a specific function |
| `call_trace` | Who calls a function / what a function calls |
| `impact_analysis` | Transitive blast radius if a symbol changes |
| `dependency_map` | What a file imports (internal vs external) |

---

## Results

### Run 4 — 2026-09-17 | psf/requests v2.32.3 | Token + Accuracy

**Corpus:** `benchmarks/repos/requests` — real-world HTTP library (~15k LOC, src/ layout)
**Tasks:** 10 | **Judge:** `gpt-oss:120b`

| Task | Type | Baseline (tokens) | CodePrism (tokens) | Reduction | Acc-Baseline | Acc-CodePrism |
|---|---|---:|---:|---:|---:|---:|
| requests_001 | symbol_lookup | 8,372 | 486 | **94.2%** | 1.00 | **1.00** |
| requests_002 | call_trace | 6,394 | 1,785 | 72.1% | 0.80 | 0.60 |
| requests_003 | impact_analysis | 12,124 | 993 | **91.8%** | 1.00 | 0.70 |
| requests_004 | dependency_map | 6,394 | 348 | **94.6%** | 0.20 | 0.30 |
| requests_005 | symbol_lookup | 7,495 | 746 | **90.0%** | 0.97 | **1.00** |
| requests_006 | call_trace | 6,386 | 104 | **98.4%** | 0.90 | 0.40 |
| requests_007 | impact_analysis | 6,394 | 1,244 | 80.5% | 1.00 | 0.60 |
| requests_008 | dependency_map | 2,367 | 188 | **92.1%** | 0.30 | 0.00 |
| requests_009 | call_trace | 2,377 | 360 | **84.9%** | 1.00 | **1.00** |
| requests_010 | dependency_map | 5,760 | 1,126 | 80.5% | 0.95 | 0.95 |
| **AVG** | | **6,407** | **738** | **88.5%** | **0.81** | **0.66** |

**Key takeaways:**
- **88.5% token reduction** — 6,407 → 738 tokens average. Every single task saves tokens.
- Largest win: `requests_006` (who calls `Session.send`) — **98.4% reduction**, 6,386 → 104 tokens.
- Accuracy gap: **−15 points** (baseline 0.81 → CodePrism 0.66). Smaller than the fixture gap (−28 pts),
  partly because the baseline is also noisier on large files.
- `requests_001` and `requests_005` (symbol_lookup with docstrings): **accuracy parity** (1.00 = 1.00).

**Low-scoring task notes:**
- `requests_006` (0.40 accuracy despite 98.4% reduction): `get_callers` on `Session.send` returned
  empty — intra-class same-file calls (`Session.request` → `Session.send`) not yet wired as call edges.
  Next indexer investigation target.
- `requests_004` / `requests_008` (dependency_map 0.30 / 0.00): `get_dependencies` formats import
  paths differently from what the judge expects. Ground truth needs refinement.

---

### Run 3 — 2026-09-17 | Post cross-file call edge fix | Fixture Corpus

**Corpus:** `tests/fixtures/sample_python_project` (2 files, 16 symbols)
**Tasks:** 10 | **Judge:** `gpt-oss:120b`

| Task | Type | Baseline | CodePrism | Reduction | Acc-Baseline | Acc-CodePrism |
|---|---|---:|---:|---:|---:|---:|
| fixture_001 | symbol_lookup | 274 | 230 | 16.1% | 0.96 | 0.15 |
| fixture_002 | call_trace | 375 | 109 | **70.9%** | 1.00 | **0.90** |
| fixture_003 | impact_analysis | 380 | 209 | 45.0% | 0.96 | 0.60 |
| fixture_004 | dependency_map | 270 | 136 | **49.6%** | 1.00 | 0.97 |
| fixture_005 | call_trace | 272 | 392 | −44.1% | 1.00 | 0.65 |
| fixture_006 | symbol_lookup | 271 | 176 | 35.1% | 1.00 | 0.40 |
| fixture_007 | impact_analysis | 274 | 204 | 25.5% | 1.00 | 0.20 |
| fixture_008 | symbol_lookup | 135 | 331 | −145.2% | 0.10 | 0.60 |
| fixture_009 | call_trace | 131 | 95 | 27.5% | 1.00 | 0.90 |
| fixture_010 | dependency_map | 377 | 133 | **64.7%** | 0.90 | 0.60 |
| **AVG** | | | | **27.0%** | **0.89** | **0.60** |

**Context:** Run 3 came immediately after fixing the cross-file call edge bug. `fixture_002`
(find all callers of `compute_checksum`) jumped from 0.20 to **0.90** — the direct target of the fix.

**Why the small fixture reduces less:** Files are 135–380 tokens. The JSON overhead of a
`get_context` response can exceed the raw file size on tiny files. On real-world files (Run 4),
every task wins.

---

### Run 2 — 2026-09-17 | Level 1 Token + Accuracy | Fixture Corpus

**Context:** First accuracy run. Discovered `gpt-oss:120b` requires `max_tokens=2000` (reasoning
model uses tokens for chain-of-thought before outputting content — low `max_tokens` returns empty).

| Task | Baseline | CodePrism | Reduction | Acc-BL | Acc-CP |
|---|---:|---:|---:|---:|---:|
| fixture_001 | 274 | 185 | 32.5% | 1.00 | 0.60 |
| fixture_002 | 375 | 97 | 74.1% | 1.00 | 0.20 |
| fixture_003 | 380 | 160 | 57.9% | 0.96 | 0.70 |
| fixture_004 | 270 | 114 | 57.8% | 1.00 | **1.00** |
| fixture_005 | 272 | 422 | −55.1% | 1.00 | **1.00** |
| fixture_006 | 271 | 182 | 32.8% | 1.00 | 0.40 |
| fixture_007 | 274 | 160 | 41.6% | 1.00 | 0.50 |
| fixture_008 | 135 | 353 | −161.5% | 0.40 | 0.60 |
| fixture_009 | 131 | 95 | 27.5% | 1.00 | 0.85 |
| fixture_010 | 377 | 111 | 70.6% | 0.90 | 0.60 |
| **AVG** | | | **31.9%** | **0.93** | **0.65** |

---

### Run 1 — 2026-09-17 | Token-only | Fixture Corpus

**Context:** First run. CodePrism was not indexed — graph returned empty results. Numbers are
invalid (included for historical reference only; CodePrism prompts were empty JSON arrays).

Token reduction reported as 78.7% was an artifact of empty responses.

---

## Reproducing Results

### Prerequisites

```bash
pip install -e ".[bench]"
pip install tree-sitter-python   # required for Python parsing
```

Copy `.env.example` to `.env` and fill in `OLLAMA_API_KEY` for accuracy eval.

### Fixture corpus (token-only, no API key needed)

```bash
python -m benchmarks.run_token_benchmark
```

### Fixture corpus with accuracy

```bash
python -m benchmarks.run_token_benchmark --accuracy
```

### Real-world corpus (requests)

```bash
python -m benchmarks.setup_repos            # clones psf/requests v2.32.3
python -m benchmarks.run_token_benchmark \
  --tasks benchmarks/tasks/requests_tasks.json
```

Add `--accuracy` for LLM-as-judge scoring (requires `OLLAMA_API_KEY`).

### CI (GitHub Actions)

The token benchmark runs automatically on every push and PR via
`.github/workflows/benchmark.yml`. No API key required — token-only mode only.

---

## Known Limitations

- **Tiny file overhead:** On files under ~500 tokens, the JSON structure of CodePrism responses
  can exceed the raw file size. This reverses the token savings. Real-world files (1k–15k tokens)
  always benefit.
- **Intra-class same-file call edges:** `get_callers` misses calls between methods in the same
  class within the same file (e.g. `Session.request` → `Session.send`). Under investigation.
- **Dependency map format:** `get_dependencies` returns internal paths in graph-storage format,
  which may differ from what a judge expects (e.g. `requests.compat` vs `from .compat import x`).
- **Token counter mismatch:** Uses tiktoken (GPT-4 tokenizer). Claude's tokenizer may differ
  by ±5–10%.
