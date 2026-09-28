"""Ruby source parser using tree-sitter."""

from __future__ import annotations

import hashlib
import os
import time

from ..core.models import (
    EdgeKind,
    EdgeRecord,
    FileRecord,
    NodeKind,
    SymbolRecord,
    make_file_id,
)
from .base import BaseParser, ParseResult, UnresolvedRef

_RUBY_BRANCH_TYPES = frozenset(
    {
        "if",
        "elsif",
        "unless",
        "while",
        "until",
        "for",
        "case",
        "when",
        "rescue",
        "conditional",
    }
)

_REQUIRE_METHODS = frozenset({"require", "require_relative"})


class RubyParser(BaseParser):
    """Extracts symbols and edges from Ruby source files via tree-sitter."""

    def __init__(self) -> None:
        try:
            import tree_sitter_ruby as tsruby
            from tree_sitter import Language
            from tree_sitter import Parser as TSParser

            self._language = Language(tsruby.language())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-ruby is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "ruby"

    @property
    def supported_extensions(self) -> list[str]:
        return [".rb", ".rake", ".gemspec"]

    # ── Public entry ─────────────────────────────────────────────────────────

    def parse(self, file_path: str, content: str) -> ParseResult:
        source = content.encode("utf-8")
        tree = self._parser.parse(source)
        file_id = make_file_id(file_path)

        try:
            last_modified = os.path.getmtime(file_path)
        except OSError:
            last_modified = 0.0

        file_rec = FileRecord(
            id=file_id,
            path=file_path,
            language=self.language_name,
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )

        result = ParseResult(file=file_rec)
        name_to_id: dict[str, str] = {}

        self._process_program(tree.root_node, file_path, file_id, result, name_to_id)
        self.resolve_intrafile_refs(result, name_to_id)
        return result

    # ── Top-level traversal ───────────────────────────────────────────────────

    def _process_program(self, root, file_path, file_id, result, name_to_id):
        for node in root.named_children:
            self._dispatch(node, file_path, file_id, result, name_to_id, parent_sym=None)

    def _dispatch(
        self, node, file_path, file_id, result, name_to_id, parent_sym, visibility="public"
    ):
        t = node.type
        if t == "class":
            self._extract_class(node, file_path, file_id, result, name_to_id)
        elif t == "module":
            self._extract_module(node, file_path, file_id, result, name_to_id)
        elif t == "method":
            self._extract_method(
                node, file_path, file_id, result, name_to_id, parent_sym, visibility
            )
        elif t == "singleton_method":
            self._extract_singleton_method(node, file_path, file_id, result, name_to_id, parent_sym)
        elif t == "call":
            self._extract_call_or_import(node, file_path, file_id, result, name_to_id, parent_sym)
        elif t == "assignment":
            self._extract_assignment(node, file_path, file_id, result, name_to_id, parent_sym)

    # ── Class extraction ──────────────────────────────────────────────────────

    def _extract_class(self, node, file_path, file_id, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        superclass_node = node.child_by_field_name("superclass")
        sig = f"class {name}"
        if superclass_node:
            sig += " < " + superclass_node.text.decode("utf-8").lstrip("< ").strip()

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=not name.startswith("_"),
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=file_id,
                to_id=sym.id,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
            )
        )

        # Inheritance ref
        if superclass_node:
            for child in superclass_node.named_children:
                if child.type == "constant":
                    result.unresolved_refs.append(
                        UnresolvedRef(
                            from_id=sym.id,
                            ref_name=child.text.decode("utf-8"),
                            kind=EdgeKind.INHERITS,
                            file_path=file_path,
                            line_number=superclass_node.start_point[0] + 1,
                        )
                    )
                    break

        body_node = node.child_by_field_name("body")
        if body_node:
            self._process_body(body_node, file_path, file_id, result, name_to_id, parent_sym=sym)

    # ── Module extraction ─────────────────────────────────────────────────────

    def _extract_module(self, node, file_path, file_id, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.MODULE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"module {name}",
            is_public=True,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=file_id,
                to_id=sym.id,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
            )
        )

        body_node = node.child_by_field_name("body")
        if body_node:
            self._process_body(body_node, file_path, file_id, result, name_to_id, parent_sym=sym)

    # ── Body traversal with visibility tracking ───────────────────────────────

    def _process_body(self, body_node, file_path, file_id, result, name_to_id, parent_sym):
        visibility = "public"
        for child in body_node.named_children:
            # Bare visibility keywords: private / protected / public
            if child.type == "identifier" and child.text.decode("utf-8") in (
                "private",
                "protected",
                "public",
            ):
                visibility = child.text.decode("utf-8")
                continue
            # call node that is just `private :method_name` or `private def ...`
            if child.type == "call":
                method_node = child.child_by_field_name("method")
                if method_node and method_node.text.decode("utf-8") in (
                    "private",
                    "protected",
                    "public",
                ):
                    # visibility modifier applied to the argument — treat whole call as private
                    visibility = method_node.text.decode("utf-8")
                    # still fall through to process the argument if it's a method def
            self._dispatch(child, file_path, file_id, result, name_to_id, parent_sym, visibility)

    # ── Method extraction ─────────────────────────────────────────────────────

    def _extract_method(self, node, file_path, file_id, result, name_to_id, parent_sym, visibility):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        params_node = node.child_by_field_name("parameters")
        params_text = params_node.text.decode("utf-8") if params_node else "()"
        sig = f"def {name}{params_text}"

        body_node = node.child_by_field_name("body")
        complexity = self._calc_complexity(body_node)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=(visibility == "public"),
            is_method=(parent_sym is not None),
            complexity_score=complexity,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        if parent_sym:
            name_to_id[f"{parent_sym.name}#{name}"] = sym.id

        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=parent_sym.id if parent_sym else file_id,
                to_id=sym.id,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
            )
        )

        if body_node:
            for callee, line in _extract_calls(body_node):
                result.unresolved_refs.append(
                    UnresolvedRef(
                        from_id=sym.id,
                        ref_name=callee,
                        kind=EdgeKind.CALLS,
                        file_path=file_path,
                        line_number=line,
                    )
                )

    # ── Singleton method (def self.xxx) ───────────────────────────────────────

    def _extract_singleton_method(self, node, file_path, file_id, result, name_to_id, parent_sym):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        params_node = node.child_by_field_name("parameters")
        params_text = params_node.text.decode("utf-8") if params_node else "()"
        sig = f"def self.{name}{params_text}"

        body_node = node.child_by_field_name("body")
        complexity = self._calc_complexity(body_node)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=True,
            is_method=(parent_sym is not None),
            complexity_score=complexity,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        if parent_sym:
            name_to_id[f"{parent_sym.name}.{name}"] = sym.id

        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=parent_sym.id if parent_sym else file_id,
                to_id=sym.id,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
            )
        )

        if body_node:
            for callee, line in _extract_calls(body_node):
                result.unresolved_refs.append(
                    UnresolvedRef(
                        from_id=sym.id,
                        ref_name=callee,
                        kind=EdgeKind.CALLS,
                        file_path=file_path,
                        line_number=line,
                    )
                )

    # ── require / include calls ───────────────────────────────────────────────

    def _extract_call_or_import(self, node, file_path, file_id, result, name_to_id, parent_sym):
        method_node = node.child_by_field_name("method")
        if not method_node:
            return
        method_name = method_node.text.decode("utf-8")

        if method_name not in _REQUIRE_METHODS:
            return

        args_node = node.child_by_field_name("arguments")
        if not args_node:
            return

        # First string argument is the module path
        for arg in args_node.named_children:
            if arg.type == "string":
                content_node = next(
                    (c for c in arg.named_children if c.type == "string_content"), None
                )
                raw = (
                    content_node.text.decode("utf-8")
                    if content_node
                    else arg.text.decode("utf-8").strip("'\"")
                )
                pkg_name = raw.split("/")[-1].replace(".rb", "")
                line = node.start_point[0] + 1

                sym = SymbolRecord.create(
                    file_path=file_path,
                    file_id=file_id,
                    name=pkg_name,
                    kind=NodeKind.IMPORT,
                    line_start=line,
                    line_end=line,
                    extra={"is_from_import": False, "source_module": raw},
                )
                result.symbols.append(sym)
                name_to_id[pkg_name] = sym.id
                result.unresolved_refs.append(
                    UnresolvedRef(
                        from_id=file_id,
                        ref_name=raw,
                        kind=EdgeKind.IMPORTS,
                        file_path=file_path,
                        line_number=line,
                    )
                )
                break

    # ── Constants ─────────────────────────────────────────────────────────────

    def _extract_assignment(self, node, file_path, file_id, result, name_to_id, parent_sym):
        lhs = node.named_children[0] if node.named_children else None
        if not lhs or lhs.type != "constant":
            return
        name = lhs.text.decode("utf-8")

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.VARIABLE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"{name} = ...",
            is_public=True,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id

    # ── Complexity ────────────────────────────────────────────────────────────

    def _calc_complexity(self, body_node) -> float:
        if not body_node:
            return 1.0
        count = [1]

        def walk(n):
            if n.type in _RUBY_BRANCH_TYPES:
                count[0] += 1
            for c in n.named_children:
                walk(c)

        walk(body_node)
        return float(count[0])


# ── Module-level helpers ──────────────────────────────────────────────────────


def _extract_calls(body_node) -> list[tuple[str, int]]:
    """Walk a method body and collect (callee_name, line) pairs from call nodes."""
    calls: list[tuple[str, int]] = []

    def walk(n):
        if n.type == "call":
            method_node = n.child_by_field_name("method")
            if method_node and method_node.type == "identifier":
                calls.append((method_node.text.decode("utf-8"), n.start_point[0] + 1))
        for c in n.named_children:
            walk(c)

    walk(body_node)
    return calls
