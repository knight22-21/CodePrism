"""
Level 3 — Symbol Resolution Accuracy Benchmark

Measures precision, recall, and F1 of CodePrism's symbol indexing and caller
resolution against a tree-sitter ground truth oracle.

Run with:
    python -m benchmarks.run_symbol_accuracy
    python -m benchmarks.run_symbol_accuracy --repos requests flask httpx
    python -m benchmarks.run_symbol_accuracy --repos fixture --verbose

Thresholds (from BENCHMARKING.md):
    Symbol precision  >= 0.95
    Symbol recall     >= 0.90
    Symbol F1         >= 0.92
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path

from benchmarks.ground_truth import FileGroundTruth, extract
from codeprism import CodePrism
from codeprism.core.models import NodeKind

# ── data structures ───────────────────────────────────────────────────────────

@dataclass
class FileResult:
    path: str
    # symbol indexing
    gt_functions: int = 0
    cp_functions: int = 0
    matched_functions: int = 0
    gt_classes: int = 0
    cp_classes: int = 0
    matched_classes: int = 0
    # caller resolution (intra-file)
    caller_pairs_gt: int = 0        # GT intra-file (callee, caller) pairs
    caller_pairs_found: int = 0     # pairs CodePrism also found
    caller_pairs_cp_total: int = 0  # total pairs CodePrism returned for these callees

    def symbol_precision(self) -> float:
        return self.matched_functions / self.cp_functions if self.cp_functions else 1.0

    def symbol_recall(self) -> float:
        return self.matched_functions / self.gt_functions if self.gt_functions else 1.0

    def symbol_f1(self) -> float:
        p, r = self.symbol_precision(), self.symbol_recall()
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def caller_precision(self) -> float:
        return self.caller_pairs_found / self.caller_pairs_cp_total if self.caller_pairs_cp_total else 1.0

    def caller_recall(self) -> float:
        return self.caller_pairs_found / self.caller_pairs_gt if self.caller_pairs_gt else 1.0


@dataclass
class RepoResult:
    name: str
    repo_path: str
    files: list[FileResult] = field(default_factory=list)
    skipped: int = 0

    def _agg(self, fn):
        vals = [fn(f) for f in self.files if f.gt_functions > 0]
        return statistics.mean(vals) if vals else 0.0

    def symbol_precision(self): return self._agg(lambda f: f.symbol_precision())
    def symbol_recall(self):    return self._agg(lambda f: f.symbol_recall())
    def symbol_f1(self):        return self._agg(lambda f: f.symbol_f1())

    def _caller_agg(self, fn):
        vals = [fn(f) for f in self.files if f.caller_pairs_gt > 0]
        return statistics.mean(vals) if vals else 0.0

    def caller_precision(self): return self._caller_agg(lambda f: f.caller_precision())
    def caller_recall(self):    return self._caller_agg(lambda f: f.caller_recall())

    def total_gt_functions(self):  return sum(f.gt_functions for f in self.files)
    def total_cp_functions(self):  return sum(f.cp_functions for f in self.files)
    def total_matched(self):       return sum(f.matched_functions for f in self.files)


# ── per-file evaluation ───────────────────────────────────────────────────────

async def evaluate_file(
    db,
    engine,
    file_rec,
    gt: FileGroundTruth,
    verbose: bool,
) -> FileResult | None:
    """Compare CodePrism's indexed symbols vs tree-sitter ground truth for one file."""
    if not gt.functions and not gt.classes:
        return None

    syms = await db.get_symbols_for_file(file_rec.id)
    cp_funcs = {s.name for s in syms if s.kind == NodeKind.FUNCTION}
    cp_classes = {s.name for s in syms if s.kind == NodeKind.CLASS}

    result = FileResult(
        path=file_rec.path,
        gt_functions=len(gt.functions),
        cp_functions=len(cp_funcs),
        matched_functions=len(gt.functions & cp_funcs),
        gt_classes=len(gt.classes),
        cp_classes=len(cp_classes),
        matched_classes=len(gt.classes & cp_classes),
    )

    # Caller resolution — for each function in this file that GT says has intra-file callers
    for callee_name, gt_callers in gt.caller_map.items():
        # only test callees that are also defined in this file
        if callee_name not in gt.functions:
            continue
        gt_caller_names = gt_callers & gt.functions  # intra-file only
        if not gt_caller_names:
            continue

        result.caller_pairs_gt += len(gt_caller_names)

        try:
            cp_callers = await engine.get_callers(file_rec.path, callee_name)
            cp_caller_names = {c["name"] if isinstance(c, dict) else c.name for c in cp_callers}
        except Exception:
            cp_caller_names = set()

        found = cp_caller_names & gt_caller_names
        result.caller_pairs_found += len(found)
        result.caller_pairs_cp_total += len(cp_caller_names)

        if verbose and (len(found) < len(gt_caller_names)):
            missed = gt_caller_names - cp_caller_names
            print(
                f"    MISS  {Path(file_rec.path).name}:{callee_name}"
                f"  GT={sorted(gt_caller_names)}  CP={sorted(cp_caller_names)}"
                f"  missed={sorted(missed)}"
            )

    return result


# ── per-repo runner ───────────────────────────────────────────────────────────

async def run_repo(repo_name: str, repo_path: str, verbose: bool) -> RepoResult:
    result = RepoResult(name=repo_name, repo_path=repo_path)
    rp = Path(repo_path).resolve()

    async with CodePrism(str(rp)) as prism:
        db = prism.engine._storage
        engine = prism.engine

        stats = await prism.engine.get_stats()
        if not stats.get("edge_count"):
            print(f"  Indexing {repo_name} ...", end=" ", flush=True)
            await prism.index()
            print("done")

        all_files = await db.get_all_files()
        py_files = [f for f in all_files if f.path.endswith(".py")]

        print(f"  {len(py_files)} Python files", end="  ", flush=True)

        for file_rec in py_files:
            abs_path = file_rec.path
            if not Path(abs_path).exists():
                result.skipped += 1
                continue

            gt = extract(abs_path)
            fr = await evaluate_file(db, engine, file_rec, gt, verbose)
            if fr:
                result.files.append(fr)

    return result


# ── reporting ─────────────────────────────────────────────────────────────────

PASS_SYMBOL_PRECISION = 0.95
PASS_SYMBOL_RECALL    = 0.90
PASS_SYMBOL_F1        = 0.92

def _pf(v: float) -> str:
    mark = "PASS" if v >= PASS_SYMBOL_F1 else "FAIL"
    return f"{v:.3f} [{mark}]"


def print_repo_result(r: RepoResult) -> None:
    sp = r.symbol_precision()
    sr = r.symbol_recall()
    sf = r.symbol_f1()
    cp = r.caller_precision()
    cr = r.caller_recall()

    sp_mark = "PASS" if sp >= PASS_SYMBOL_PRECISION else "FAIL"
    sr_mark = "PASS" if sr >= PASS_SYMBOL_RECALL else "FAIL"
    sf_mark = "PASS" if sf >= PASS_SYMBOL_F1 else "FAIL"

    print(f"\n  Repo: {r.name}  ({len(r.files)} files evaluated, {r.skipped} skipped)")
    print(f"  GT functions total : {r.total_gt_functions():,}")
    print(f"  CP functions total : {r.total_cp_functions():,}  (matched: {r.total_matched():,})")
    print(f"  Symbol precision   : {sp:.3f}  [{sp_mark}]  (threshold >= {PASS_SYMBOL_PRECISION})")
    print(f"  Symbol recall      : {sr:.3f}  [{sr_mark}]  (threshold >= {PASS_SYMBOL_RECALL})")
    print(f"  Symbol F1          : {sf:.3f}  [{sf_mark}]  (threshold >= {PASS_SYMBOL_F1})")
    print(f"  Caller precision   : {cp:.3f}  (intra-file calls)")
    print(f"  Caller recall      : {cr:.3f}  (intra-file calls)")


def print_summary(results: list[RepoResult]) -> None:
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    header = f"{'Repo':<16} {'Prec':>6} {'Rec':>6} {'F1':>6}  {'CallPrec':>9} {'CallRec':>8}"
    print(header)
    print("-" * len(header))
    for r in results:
        cp_str = f"{r.caller_precision():.3f}" if any(f.caller_pairs_gt > 0 for f in r.files) else "  n/a"
        cr_str = f"{r.caller_recall():.3f}" if any(f.caller_pairs_gt > 0 for f in r.files) else "  n/a"
        print(
            f"{r.name:<16} {r.symbol_precision():>6.3f} {r.symbol_recall():>6.3f}"
            f" {r.symbol_f1():>6.3f}  {cp_str:>9} {cr_str:>8}"
        )
    print("-" * len(header))

    all_prec = statistics.mean(r.symbol_precision() for r in results)
    all_rec  = statistics.mean(r.symbol_recall() for r in results)
    all_f1   = statistics.mean(r.symbol_f1() for r in results)
    all_cp   = [r.caller_precision() for r in results if any(f.caller_pairs_gt > 0 for f in r.files)]
    all_cr   = [r.caller_recall() for r in results if any(f.caller_pairs_gt > 0 for f in r.files)]

    cp_s = f"{statistics.mean(all_cp):.3f}" if all_cp else "  n/a"
    cr_s = f"{statistics.mean(all_cr):.3f}" if all_cr else "  n/a"
    print(f"{'OVERALL':<16} {all_prec:>6.3f} {all_rec:>6.3f} {all_f1:>6.3f}  {cp_s:>9} {cr_s:>8}")

    print()
    p_mark = "PASS" if all_prec >= PASS_SYMBOL_PRECISION else "FAIL"
    r_mark = "PASS" if all_rec  >= PASS_SYMBOL_RECALL else "FAIL"
    f_mark = "PASS" if all_f1   >= PASS_SYMBOL_F1 else "FAIL"
    print(f"  Precision {all_prec:.3f} [{p_mark}]  Recall {all_rec:.3f} [{r_mark}]  F1 {all_f1:.3f} [{f_mark}]")


# ── main ──────────────────────────────────────────────────────────────────────

REPO_MAP = {
    "fixture":  "tests/fixtures/sample_python_project",
    "requests": "benchmarks/repos/requests",
    "flask":    "benchmarks/repos/flask",
    "httpx":    "benchmarks/repos/httpx",
}


async def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Level 3 symbol resolution accuracy")
    parser.add_argument(
        "--repos", nargs="+",
        default=list(REPO_MAP.keys()),
        choices=list(REPO_MAP.keys()),
        help="Which repos to evaluate (default: all)",
    )
    parser.add_argument("--verbose", action="store_true", help="Print missed caller pairs")
    parser.add_argument(
        "--out",
        default="benchmarks/results/symbol_accuracy.json",
        help="Output JSON file",
    )
    args = parser.parse_args(argv)

    root = Path(__file__).parent.parent
    results: list[RepoResult] = []

    for repo_name in args.repos:
        repo_path = str(root / REPO_MAP[repo_name])
        print(f"\n[{repo_name}] {repo_path}")
        r = await run_repo(repo_name, repo_path, args.verbose)
        print_repo_result(r)
        results.append(r)

    print_summary(results)

    # save JSON
    out_path = root / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "repos": [
            {
                "name": r.name,
                "files_evaluated": len(r.files),
                "gt_functions": r.total_gt_functions(),
                "cp_functions": r.total_cp_functions(),
                "matched_functions": r.total_matched(),
                "symbol_precision": round(r.symbol_precision(), 4),
                "symbol_recall": round(r.symbol_recall(), 4),
                "symbol_f1": round(r.symbol_f1(), 4),
                "caller_precision": round(r.caller_precision(), 4),
                "caller_recall": round(r.caller_recall(), 4),
            }
            for r in results
        ],
        "overall": {
            "symbol_precision": round(statistics.mean(r.symbol_precision() for r in results), 4),
            "symbol_recall":    round(statistics.mean(r.symbol_recall() for r in results), 4),
            "symbol_f1":        round(statistics.mean(r.symbol_f1() for r in results), 4),
        },
        "thresholds": {
            "symbol_precision": PASS_SYMBOL_PRECISION,
            "symbol_recall":    PASS_SYMBOL_RECALL,
            "symbol_f1":        PASS_SYMBOL_F1,
        },
    }
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
