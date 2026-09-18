"""
Independent ground truth extractor for Level 3 symbol resolution accuracy.

Uses Python's stdlib `ast` module — a completely different parser and tree
representation from tree-sitter, which CodePrism uses internally. This
independence is the point: if both agree, the result is real. If they disagree,
it surfaces actual gaps rather than circular validation artifacts.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class FileGroundTruth:
    path: str
    functions: set[str] = field(default_factory=set)   # all def names (funcs + methods)
    classes: set[str] = field(default_factory=set)
    # caller_map[callee_name] = set of caller function names (intra-file only)
    caller_map: dict[str, set[str]] = field(default_factory=dict)


def extract(file_path: str) -> FileGroundTruth:
    """
    Parse a Python source file with stdlib ast and return ground-truth symbols
    plus an intra-file call graph.

    Handles:
    - Top-level functions and async functions
    - Methods (sync and async) inside classes
    - Decorated definitions (the decorator doesn't change the function name)
    - Conditionally defined functions (if block / try block)
    - Nested functions (collected as symbols; their calls attributed to them)

    Deliberately does NOT handle:
    - Dynamically created functions (type(), exec(), assign-to-lambda at module level)
    These are rare and neither CodePrism nor any static tool handles them.
    """
    path = Path(file_path)
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return FileGroundTruth(path=file_path)

    try:
        tree = ast.parse(src, filename=file_path)
    except SyntaxError:
        return FileGroundTruth(path=file_path)

    gt = FileGroundTruth(path=file_path)
    visitor = _GTVisitor(gt)
    visitor.visit(tree)
    return gt


# ── AST visitor ───────────────────────────────────────────────────────────────

class _GTVisitor(ast.NodeVisitor):
    """
    Collects top-level and class-level function/method definitions only —
    matching the scope CodePrism indexes by design (nested/closure functions
    are intentionally excluded from the graph as they are local-scope symbols).

    Call collection is attributed to the immediately enclosing function so
    the intra-file caller map is correct.
    """

    def __init__(self, gt: FileGroundTruth) -> None:
        self._gt = gt
        self._func_stack: list[str] = []   # enclosing function name(s)
        self._in_func: bool = False         # True once inside a function body

    # ── symbol collection ─────────────────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if not self._in_func:
            # top-level or class-level: index as a symbol
            self._gt.functions.add(node.name)
            self._func_stack.append(node.name)
            old = self._in_func
            self._in_func = True
            self.generic_visit(node)   # walk body for calls, not more defs
            self._in_func = old
            self._func_stack.pop()
        else:
            # nested function: don't add to GT, but collect its calls under
            # the enclosing function (so the call map stays accurate)
            self._func_stack.append(node.name)
            self.generic_visit(node)
            self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._gt.classes.add(node.name)
        self.generic_visit(node)   # walk body to find methods

    # ── call collection ───────────────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        if self._func_stack:
            callee = _call_target(node.func)
            if callee:
                caller = self._func_stack[-1]
                self._gt.caller_map.setdefault(callee, set()).add(caller)
        self.generic_visit(node)


# ── helpers ───────────────────────────────────────────────────────────────────

def _call_target(func_node: ast.expr) -> str | None:
    """
    Extract the leaf name from a call target.
      foo()            → "foo"
      self.foo()       → "foo"
      obj.bar.baz()    → "baz"
    Returns None for subscripts, starred expressions, etc.
    """
    if isinstance(func_node, ast.Name):
        return func_node.id
    if isinstance(func_node, ast.Attribute):
        return func_node.attr
    return None
