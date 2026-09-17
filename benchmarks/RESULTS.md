# Benchmark Results

Results are stored here permanently. Raw JSON files are gitignored (`benchmarks/results/`);
this file is the committed record.

---

## Run 1 — 2026-09-17 | Level 1 Token Reduction | Fixture Corpus

**Corpus:** `tests/fixtures/sample_python_project` (2 files, 16 symbols)
**Token backend:** tiktoken cl100k_base (free, GPT-4 tokenizer)
**Accuracy:** not measured (no LLM API key)
**Tasks:** 10 (4 types: symbol_lookup, call_trace, impact_analysis, dependency_map)

### Results

| Task ID | Type | Baseline | CodePrism | Reduction |
|---|---|---:|---:|---:|
| fixture_001 | symbol_lookup | 274 | 55 | **79.9%** |
| fixture_002 | call_trace | 375 | 84 | **77.6%** |
| fixture_003 | impact_analysis | 380 | 54 | **85.8%** |
| fixture_004 | dependency_map | 270 | 51 | **81.1%** |
| fixture_005 | call_trace | 272 | 53 | **80.5%** |
| fixture_006 | symbol_lookup | 271 | 52 | **80.8%** |
| fixture_007 | impact_analysis | 274 | 55 | **79.9%** |
| fixture_008 | symbol_lookup | 135 | 51 | **62.2%** |
| fixture_009 | call_trace | 131 | 82 | **37.4%** |
| fixture_010 | dependency_map | 377 | 51 | **86.5%** |
| **TOTAL** | | **2,759** | **588** | **78.7%** |

### Notes

- **fixture_009** (37.4%) — `get_callers` returned a list of 2 callers; the response JSON is
  proportionally larger relative to the small file that was the baseline. The baseline file
  (`main.py`) was only 131 tokens, so the overhead of CodePrism's JSON wrapper is visible.
  On larger real-world files this effect disappears.
- **fixture_008** (62.2%) — `main.py` is small (135 token baseline), same overhead effect.
- All other tasks: 78–87% reduction, consistent with the "60-80% claim" in the README.

### Caveats

- Fixture project is tiny (2 files). Results on real-world repos will differ.
- Token backend is tiktoken (GPT-4 tokenizer), not Claude's native tokenizer. Counts may differ
  by ~5-10% from what Claude would report.
- Accuracy (whether CodePrism actually answers the question correctly) is not yet measured.
  Will be enabled once an LLM API key is available (Ollama cloud integration in progress).

### How to reproduce

```bash
pip install tiktoken
python -m benchmarks.run_token_benchmark
# Results written to benchmarks/results/token_benchmark.json
```

---

## Planned future runs

| When | Corpus | Notes |
|---|---|---|
| After Ollama integration | fixture_tasks | Add accuracy scores (LLM-as-judge) |
| After corpus expansion | 5+ real repos (requests, flask, ...) | Full representativeness |
| After Level 2 | Same corpus | Add latency p95 column |
