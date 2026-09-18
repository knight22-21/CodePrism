"""
Tree-sitter based ground truth extractor for Level 3 symbol resolution accuracy.

Extracts from raw source files (no CodePrism) so it can serve as an independent oracle.
Python only (tree-sitter-python required).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import tree_sitter_python as tspython
from tree_sitter import Language, Parser

_PY = Language(tspython.language())
_PARSER = Parser(_PY)


@dataclass
class FileGroundTruth:
    path: str
    functions: set[str] = field(default_factory=set)   # all function/method names
    classes: set[str] = field(default_factory=set)
    # caller_map[callee_name] = set of caller function names (intra-file only)
    caller_map: dict[str, set[str]] = field(default_factory=dict)


def extract(file_path: str) -> FileGroundTruth:
    """Parse a Python file and return ground-truth symbols + intra-file call graph."""
    path = Path(file_path)
    try:
        src = path.read_bytes()
    except OSError:
        return FileGroundTruth(path=file_path)

    tree = _PARSER.parse(src)
    gt = FileGroundTruth(path=file_path)

    _walk_top(tree.root_node, gt, current_func=None)
    return gt


# ── AST walkers ───────────────────────────────────────────────────────────────

def _walk_top(node, gt: FileGroundTruth, current_func: str | None) -> None:
    """Walk module-level or class-level nodes."""
    for child in node.children:
        t = child.type
        if t == "function_definition":
            name = _name(child)
            if name:
                gt.functions.add(name)
                _walk_body(child, gt, current_func=name)
        elif t == "decorated_definition":
            _walk_top(child, gt, current_func)
        elif t == "class_definition":
            cname = _name(child)
            if cname:
                gt.classes.add(cname)
            # walk class body for methods
            body = child.child_by_field_name("body")
            if body:
                _walk_top(body, gt, current_func)
        elif t == "block":
            _walk_top(child, gt, current_func)


def _walk_body(func_node, gt: FileGroundTruth, current_func: str) -> None:
    """Walk a function body collecting call expressions."""
    body = func_node.child_by_field_name("body")
    if body is None:
        return
    _collect_calls(body, gt, current_func)


def _collect_calls(node, gt: FileGroundTruth, current_func: str) -> None:
    """Recursively collect call targets inside a function body."""
    if node.type == "call":
        func_node = node.child_by_field_name("function")
        if func_node is not None:
            callee = _call_target(func_node)
            if callee:
                gt.caller_map.setdefault(callee, set()).add(current_func)
    # don't recurse into nested function definitions — they have their own scope
    if node.type == "function_definition":
        return
    for child in node.children:
        _collect_calls(child, gt, current_func)


# ── helpers ───────────────────────────────────────────────────────────────────

def _name(node) -> str | None:
    n = node.child_by_field_name("name")
    return n.text.decode("utf-8", errors="replace") if n else None


def _call_target(func_node) -> str | None:
    """
    Extract the leaf name from a call target.
      foo()          → "foo"
      self.foo()     → "foo"
      obj.bar.baz()  → "baz"
      foo.bar()      → "bar"
    Returns None for complex expressions (subscripts, etc.).
    """
    t = func_node.type
    if t == "identifier":
        return func_node.text.decode("utf-8", errors="replace")
    if t == "attribute":
        attr = func_node.child_by_field_name("attribute")
        return attr.text.decode("utf-8", errors="replace") if attr else None
    return None
