"""
Cross-file call resolution accuracy (Python).

The Level 3 benchmark only scores callers *within* one file. This one scores the
cross-file CALLS edges CodePrism creates, against an oracle built with Python's
own ``ast`` module (independent of tree-sitter) for the calls whose target can be
known without type inference:

  * ``f()``      where ``f`` was imported              -> must point into that module
  * ``mod.f()``  where ``mod`` is an imported module    -> must point into that module
  * a builtin (``str()``, ``len()``) or a call into a third-party module
    (``json.dumps()``, ``os.path.join()``)             -> must not point into the project

Calls on objects (``self.x()``, ``obj.x()``) need types, so they're reported as
"unjudged" rather than scored.

Run:
    python -m benchmarks.run_call_precision
    python -m benchmarks.run_call_precision --repos requests codeprism
"""

from __future__ import annotations

import argparse
import ast
import asyncio
import builtins
import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from codeprism.core.config import CodePrismConfig
from codeprism.core.graph import GraphEngine
from codeprism.core.models import EdgeKind
from codeprism.core.storage import StorageManager
from codeprism.indexer.project_indexer import ProjectIndexer

ROOT = Path(__file__).resolve().parent.parent
CORPORA = {
    "requests": ROOT / "benchmarks" / "repos" / "requests",
    "flask": ROOT / "benchmarks" / "repos" / "flask",
    "httpx": ROOT / "benchmarks" / "repos" / "httpx",
    "codeprism": ROOT / "codeprism",
}
BUILTINS = set(dir(builtins))


# ── module map (oracle side, independent of CodePrism's resolver) ────────────


class Modules:
    def __init__(self, files: list[Path]) -> None:
        self.by_parts: dict[tuple[str, ...], list[Path]] = {}
        for f in files:
            parts = f.with_suffix("").parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
            for i in range(len(parts)):
                self.by_parts.setdefault(parts[i:], []).append(f)

    def resolve(self, module: str, caller: Path) -> list[Path]:
        if module.startswith("."):
            level = len(module) - len(module.lstrip("."))
            base = caller.parent.parts
            base = base[: len(base) - (level - 1)] if level > 1 else base
            rest = tuple(p for p in module.lstrip(".").split(".") if p)
            return [f for f in self.by_parts.get(base + rest, []) if f.with_suffix("").parts[: len(base)] == base]
        return self.by_parts.get(tuple(module.split(".")), [])


def _in_module(target: Path, module_files: list[Path]) -> bool:
    """Target is the module file, or inside the package it names (re-exports)."""
    for m in module_files:
        pkg = m.parent if m.name == "__init__.py" else None
        if target == m or (pkg and pkg in target.parents):
            return True
    return False


@dataclass
class FileFacts:
    imported_names: dict[str, str] = field(default_factory=dict)  # local name -> module
    imported_modules: dict[str, str] = field(default_factory=dict)  # local alias -> module
    # (line, leaf name) -> list of ("bare", None) / ("attr", receiver-head)
    calls: dict[tuple[int, str], list[tuple[str, str | None]]] = field(default_factory=dict)
    # function name -> list of (kind, name, receiver-head) calls in its body
    func_calls: dict[str, list[tuple[str, str, str | None]]] = field(default_factory=dict)


def _facts(path: Path) -> FileFacts:
    facts = FileFacts()
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return facts
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                facts.imported_modules[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            mod = "." * node.level + (node.module or "")
            for a in node.names:
                if a.name != "*":
                    facts.imported_names[a.asname or a.name] = mod
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            if isinstance(f, ast.Name):
                entry = ("bare", f.id, None)
            elif isinstance(f, ast.Attribute):
                head = f.value
                while isinstance(head, ast.Attribute):
                    head = head.value
                entry = ("attr", f.attr, head.id if isinstance(head, ast.Name) else None)
            else:
                continue
            facts.calls.setdefault((node.lineno, entry[1]), []).append((entry[0], entry[2]))
            facts.func_calls.setdefault(fn.name, []).append(entry)
    return facts


# ── scoring ──────────────────────────────────────────────────────────────────


def _judge(kind: str, name: str, head: str | None, facts: FileFacts, caller: Path, mods: Modules):
    """Returns (expected module files or [] for "must not link", None if unjudgeable)."""
    if kind == "bare":
        if name in facts.imported_names:
            return mods.resolve(facts.imported_names[name], caller)
        if name in BUILTINS:
            return []
        return None
    if head and head in facts.imported_modules:
        return mods.resolve(facts.imported_modules[head], caller)
    if head and head in facts.imported_names:  # from pkg import module; module.f()
        base = facts.imported_names[head]
        sep = "" if base.endswith(".") else "."
        return mods.resolve(base + sep + head, caller) or mods.resolve(base, caller)
    return None


async def evaluate(name: str, root: Path) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        storage = StorageManager(Path(tmp) / "idx.db")
        await storage.initialize()
        try:
            cfg = CodePrismConfig(languages=["python"], respect_gitignore=False)
            await ProjectIndexer(GraphEngine(), storage, cfg).index(str(root))
            files = {f.id: Path(f.path) for f in await storage.get_all_files()}
            syms = {s.id: s for s in await storage.get_all_symbols()}
            edges = [e for e in await storage.get_all_edges() if e.kind == EdgeKind.CALLS]
        finally:
            await storage.close()

    mods = Modules(list(files.values()))
    facts_cache: dict[Path, FileFacts] = {}

    def facts(p: Path) -> FileFacts:
        if p not in facts_cache:
            facts_cache[p] = _facts(p)
        return facts_cache[p]

    correct = wrong = unjudged = 0
    wrong_examples: list[str] = []
    found_pairs: set[tuple[str, str, Path]] = set()
    for e in edges:
        src, dst = syms.get(e.from_id), syms.get(e.to_id)
        if not src or not dst or src.file_id == dst.file_id:
            continue  # intra-file edges are the Level 3 benchmark's job
        caller, target = files[src.file_id], files[dst.file_id]
        found_pairs.add((src.name, dst.name, target))
        sites = facts(caller).calls.get((e.line_number, dst.name), [])
        verdicts = [
            _judge(k, dst.name, h, facts(caller), caller, mods) for k, h in sites
        ]
        verdicts = [v for v in verdicts if v is not None]
        if not verdicts:
            unjudged += 1
        elif any(_in_module(target, v) for v in verdicts):
            correct += 1
        else:
            wrong += 1
            if len(wrong_examples) < 8:
                wrong_examples.append(
                    f"{caller.name}:{e.line_number} {src.name} -> {dst.name} @ {target.name}"
                )

    # recall over judgeable internal calls
    defs_by_file: dict[Path, set[str]] = {}
    for s in syms.values():
        if s.kind.value in ("function", "class"):
            defs_by_file.setdefault(files[s.file_id], set()).add(s.name)
    expected = hit = 0
    missed_examples: list[str] = []
    for caller in set(files.values()):
        f = facts(caller)
        for func, calls in f.func_calls.items():
            for kind, cname, head in calls:
                mfiles = _judge(kind, cname, head, f, caller, mods)
                if not mfiles:
                    continue
                targets = [m for m in mfiles if cname in defs_by_file.get(m, set())]
                if not targets:
                    continue  # re-exported or not a function/class: skip
                expected += 1
                if any((func, cname, t) in found_pairs for t in targets):
                    hit += 1
                elif len(missed_examples) < 8:
                    missed_examples.append(f"{caller.name} {func} -> {cname} @ {targets[0].name}")

    judged = correct + wrong
    return {
        "repo": name,
        "cross_file_edges": correct + wrong + unjudged,
        "judged": judged,
        "correct": correct,
        "wrong": wrong,
        "unjudged": unjudged,
        "precision": round(correct / judged, 3) if judged else None,
        "recall": round(hit / expected, 3) if expected else None,
        "expected_calls": expected,
        "wrong_examples": wrong_examples,
        "missed_examples": missed_examples,
    }


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--repos", nargs="*", default=list(CORPORA))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    rows = []
    for name in args.repos:
        root = CORPORA[name]
        if not root.exists():
            print(f"skip {name}: {root} missing (run python -m benchmarks.setup_repos)")
            continue
        rows.append(await evaluate(name, root))
    if args.json:
        print(json.dumps(rows, indent=2))
        return
    print(f"{'repo':10} {'edges':>6} {'judged':>6} {'wrong':>5} {'precision':>9} {'recall':>7}")
    for r in rows:
        print(
            f"{r['repo']:10} {r['cross_file_edges']:6} {r['judged']:6} {r['wrong']:5} "
            f"{r['precision']!s:>9} {r['recall']!s:>7}"
        )
    for r in rows:
        for ex in r["wrong_examples"][:4]:
            print(f"  wrong  [{r['repo']}] {ex}")
        for ex in r["missed_examples"][:4]:
            print(f"  missed [{r['repo']}] {ex}")


if __name__ == "__main__":
    asyncio.run(main())
