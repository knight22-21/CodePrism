"""Level 3 multi-language symbol and intra-file caller benchmark.

This runner is deterministic and never calls an LLM. It compares CodePrism's
graph against the independent tree-sitter oracle in ground_truth_multilang.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from pathlib import Path

from benchmarks.ground_truth_multilang import extract
from codeprism import CodePrism
from codeprism.core.models import NodeKind


ROOT = Path(__file__).resolve().parent.parent
CORPORA = {
    "javascript": ("tests/fixtures/sample_js_project", "javascript"),
    "typescript": ("tests/fixtures/sample_ts_project", "typescript"),
    "go": ("tests/fixtures/sample_go_project", "go"),
    "rust": ("tests/fixtures/sample_rust_project", "rust"),
    "java": ("tests/fixtures/sample_java_project", "java"),
    "c": ("tests/fixtures/sample_c_project", "c"),
    "cpp": ("tests/fixtures/sample_c_project", "cpp"),
    "ruby": ("tests/fixtures/sample_ruby_project", "ruby"),
    "php": ("tests/fixtures/sample_php_project", "php"),
}

EXTENSIONS = {
    "javascript": {".js", ".jsx", ".mjs"},
    "typescript": {".ts", ".tsx", ".mts"},
    "go": {".go"},
    "rust": {".rs"},
    "java": {".java"},
    "c": {".c", ".h"},
    "cpp": {".cpp", ".cc", ".cxx", ".hpp", ".hh"},
    "ruby": {".rb"},
    "php": {".php"},
}

THRESHOLDS = {"precision": 0.95, "recall": 0.90, "f1": 0.92}


def _names(symbols, kinds: set[NodeKind]) -> set[str]:
    return {s.name for s in symbols if s.kind in kinds}


def _score(found: int, expected: int, total: int) -> float:
    return found / total if total else 1.0


async def evaluate_file(db, engine, file_rec, gt) -> dict:
    symbols = await db.get_symbols_for_file(file_rec.id)
    gt_functions = set(gt.functions)
    gt_classes = set(gt.classes)
    gt_types = set(gt.types)
    cp_functions = _names(symbols, {NodeKind.FUNCTION})
    cp_classes = _names(symbols, {NodeKind.CLASS})
    cp_types = _names(symbols, {NodeKind.TYPE})

    function_found = len(gt_functions & cp_functions)
    class_found = len(gt_classes & cp_classes)
    type_found = len(gt_types & cp_types)

    caller_expected = 0
    caller_found = 0
    caller_total = 0
    for callee, callers in gt.caller_map.items():
        if callee not in gt_functions:
            continue
        expected_callers = callers & gt_functions
        if not expected_callers:
            continue
        caller_expected += len(expected_callers)
        try:
            rows = await engine.get_callers(file_rec.path, callee)
            cp_callers = {
                row["name"] if isinstance(row, dict) else row.name
                for row in rows
            }
        except (AttributeError, KeyError, TypeError, ValueError, RuntimeError):
            cp_callers = set()
        caller_found += len(expected_callers & cp_callers)
        caller_total += len(cp_callers)

    expected_symbols = gt_functions | gt_classes | gt_types
    found_symbols = (gt_functions & cp_functions) | (gt_classes & cp_classes) | (gt_types & cp_types)
    cp_symbols = cp_functions | cp_classes | cp_types
    return {
        "path": file_rec.path,
        "gt_functions": len(gt_functions),
        "cp_functions": len(cp_functions),
        "matched_functions": function_found,
        "gt_classes": len(gt_classes),
        "cp_classes": len(cp_classes),
        "matched_classes": class_found,
        "gt_types": len(gt_types),
        "cp_types": len(cp_types),
        "matched_types": type_found,
        "symbol_expected": len(expected_symbols),
        "symbol_found": len(found_symbols),
        "symbol_cp_total": len(cp_symbols),
        "caller_expected": caller_expected,
        "caller_found": caller_found,
        "caller_cp_total": caller_total,
    }


async def evaluate_corpus(name: str, relative: str, language: str) -> dict:
    root = (ROOT / relative).resolve()
    async with CodePrism(str(root)) as prism:
        await prism.index()
        db = prism.engine._storage
        files = await db.get_all_files()
        records = []
        for file_rec in files:
            if Path(file_rec.path).suffix.lower() not in EXTENSIONS[language]:
                continue
            gt = extract(file_rec.path, language)
            if gt.functions or gt.classes or gt.types:
                records.append(await evaluate_file(db, prism.engine, file_rec, gt))

    expected = sum(r["symbol_expected"] for r in records)
    found = sum(r["symbol_found"] for r in records)
    cp_total = sum(r["symbol_cp_total"] for r in records)
    caller_expected = sum(r["caller_expected"] for r in records)
    caller_found = sum(r["caller_found"] for r in records)
    caller_total = sum(r["caller_cp_total"] for r in records)
    precision = _score(found, expected, cp_total)
    recall = _score(found, expected, expected)
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    caller_precision = _score(caller_found, caller_expected, caller_total)
    caller_recall = _score(caller_found, caller_expected, caller_expected)
    return {
        "corpus": name,
        "language": language,
        "repo_path": str(root),
        "files_evaluated": len(records),
        "symbol_expected": expected,
        "symbol_found": found,
        "symbol_cp_total": cp_total,
        "symbol_precision": round(precision, 4),
        "symbol_recall": round(recall, 4),
        "symbol_f1": round(f1, 4),
        "caller_expected": caller_expected,
        "caller_found": caller_found,
        "caller_cp_total": caller_total,
        "caller_precision": round(caller_precision, 4) if caller_expected else None,
        "caller_recall": round(caller_recall, 4) if caller_expected else None,
        "files": records,
    }


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Level 3 multi-language accuracy")
    parser.add_argument("--corpora", nargs="*", default=list(CORPORA))
    parser.add_argument(
        "--out",
        default="benchmarks/results/level3_multilang_accuracy.json",
    )
    args = parser.parse_args(argv)
    unknown = sorted(set(args.corpora) - set(CORPORA))
    if unknown:
        parser.error("unknown corpus: " + ", ".join(unknown))

    rows = []
    for name in args.corpora:
        relative, language = CORPORA[name]
        print(f"[{name}] indexing and scoring {language} fixture ...", flush=True)
        rows.append(await evaluate_corpus(name, relative, language))

    precisions = [r["symbol_precision"] for r in rows]
    recalls = [r["symbol_recall"] for r in rows]
    f1s = [r["symbol_f1"] for r in rows]
    caller_rows = [r for r in rows if r["caller_precision"] is not None]
    payload = {
        "level": 3,
        "deterministic": True,
        "llm_calls": 0,
        "oracle": "tree-sitter independent traversal",
        "corpora": rows,
        "overall": {
            "symbol_precision": round(statistics.mean(precisions), 4),
            "symbol_recall": round(statistics.mean(recalls), 4),
            "symbol_f1": round(statistics.mean(f1s), 4),
            "caller_precision": round(
                statistics.mean(r["caller_precision"] for r in caller_rows), 4
            ) if caller_rows else None,
            "caller_recall": round(
                statistics.mean(r["caller_recall"] for r in caller_rows), 4
            ) if caller_rows else None,
        },
        "thresholds": THRESHOLDS,
    }
    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload["overall"], indent=2))
    print(f"Results saved to {out}")


if __name__ == "__main__":
    asyncio.run(main())

