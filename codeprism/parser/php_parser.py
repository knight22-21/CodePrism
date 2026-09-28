"""PHP source parser using tree-sitter."""

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

_PHP_BRANCH_TYPES = frozenset(
    {
        "if_statement",
        "else_if_clause",
        "while_statement",
        "do_statement",
        "for_statement",
        "foreach_statement",
        "switch_statement",
        "case_statement",
        "match_expression",
        "catch_clause",
        "conditional_expression",
    }
)


class PhpParser(BaseParser):
    """Extracts symbols and edges from PHP source files via tree-sitter."""

    def __init__(self) -> None:
        try:
            import tree_sitter_php as tsphp
            from tree_sitter import Language
            from tree_sitter import Parser as TSParser

            self._language = Language(tsphp.language_php())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-php is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "php"

    @property
    def supported_extensions(self) -> list[str]:
        return [".php", ".php5", ".phtml"]

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
            self._dispatch(node, file_path, file_id, result, name_to_id)

    def _dispatch(self, node, file_path, file_id, result, name_to_id):
        t = node.type
        if t == "namespace_definition":
            self._extract_namespace(node, file_path, file_id, result, name_to_id)
        elif t == "namespace_use_declaration":
            self._extract_use(node, file_path, file_id, result, name_to_id)
        elif t == "class_declaration":
            self._extract_class(node, file_path, file_id, result, name_to_id, parent_id=file_id)
        elif t == "interface_declaration":
            self._extract_interface(node, file_path, file_id, result, name_to_id)
        elif t == "trait_declaration":
            self._extract_trait(node, file_path, file_id, result, name_to_id)
        elif t == "function_definition":
            self._extract_function(node, file_path, file_id, result, name_to_id, parent_id=file_id)

    # ── Namespace ─────────────────────────────────────────────────────────────

    def _extract_namespace(self, node, file_path, file_id, result, name_to_id):
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
            signature=f"namespace {name}",
            is_public=True,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id

    # ── use statements ────────────────────────────────────────────────────────

    def _extract_use(self, node, file_path, file_id, result, name_to_id):
        for clause in node.named_children:
            if clause.type != "namespace_use_clause":
                continue
            # The last `name` child is the class/alias name being imported
            qname = clause.named_children[0] if clause.named_children else None
            if not qname:
                continue
            raw = qname.text.decode("utf-8")
            # Last component: App\Models\User → User
            short_name = raw.split("\\")[-1]
            line = node.start_point[0] + 1

            sym = SymbolRecord.create(
                file_path=file_path,
                file_id=file_id,
                name=short_name,
                kind=NodeKind.IMPORT,
                line_start=line,
                line_end=line,
                extra={"is_from_import": False, "source_module": raw},
            )
            result.symbols.append(sym)
            name_to_id[short_name] = sym.id
            result.unresolved_refs.append(
                UnresolvedRef(
                    from_id=file_id,
                    ref_name=raw,
                    kind=EdgeKind.IMPORTS,
                    file_path=file_path,
                    line_number=line,
                )
            )

    # ── Class ─────────────────────────────────────────────────────────────────

    def _extract_class(self, node, file_path, file_id, result, name_to_id, parent_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        # base_clause is a named child (not a named field)
        base_clause = next((c for c in node.named_children if c.type == "base_clause"), None)
        sig = f"class {name}"
        if base_clause:
            parent_name_node = next(
                (c for c in base_clause.named_children if c.type == "name"), None
            )
            if parent_name_node:
                sig += f" extends {parent_name_node.text.decode('utf-8')}"

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=True,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=parent_id,
                to_id=sym.id,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
            )
        )

        # Inheritance ref
        if base_clause:
            parent_name_node = next(
                (c for c in base_clause.named_children if c.type == "name"), None
            )
            if parent_name_node:
                result.unresolved_refs.append(
                    UnresolvedRef(
                        from_id=sym.id,
                        ref_name=parent_name_node.text.decode("utf-8"),
                        kind=EdgeKind.INHERITS,
                        file_path=file_path,
                        line_number=base_clause.start_point[0] + 1,
                    )
                )

        # Class body
        body = node.child_by_field_name("body")
        if body:
            self._process_class_body(body, file_path, file_id, result, name_to_id, class_sym=sym)

    # ── Interface / Trait ─────────────────────────────────────────────────────

    def _extract_interface(self, node, file_path, file_id, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"interface {name}",
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

    def _extract_trait(self, node, file_path, file_id, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"trait {name}",
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

    # ── Class body members ────────────────────────────────────────────────────

    def _process_class_body(self, body, file_path, file_id, result, name_to_id, class_sym):
        for child in body.named_children:
            t = child.type
            if t == "method_declaration":
                self._extract_method(child, file_path, file_id, result, name_to_id, class_sym)
            elif t == "property_declaration":
                self._extract_property(child, file_path, file_id, result, name_to_id, class_sym)
            elif t == "const_declaration":
                self._extract_const(child, file_path, file_id, result, name_to_id, class_sym)

    # ── Method ────────────────────────────────────────────────────────────────

    def _extract_method(self, node, file_path, file_id, result, name_to_id, class_sym):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        # Determine visibility from modifiers
        is_public = True
        is_static = False
        for child in node.named_children:
            if child.type == "visibility_modifier":
                txt = child.text.decode("utf-8")
                is_public = txt == "public"
            if child.type == "static_modifier":
                is_static = True

        params_node = node.child_by_field_name("parameters")
        params_text = params_node.text.decode("utf-8") if params_node else "()"
        prefix = "public static" if is_static else ("public" if is_public else "private")
        sig = f"{prefix} function {name}{params_text}"

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
            is_public=is_public,
            complexity_score=complexity,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        if class_sym:
            name_to_id[f"{class_sym.name}::{name}"] = sym.id

        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=class_sym.id if class_sym else file_id,
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

    # ── Top-level function ────────────────────────────────────────────────────

    def _extract_function(self, node, file_path, file_id, result, name_to_id, parent_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        params_node = node.child_by_field_name("parameters")
        params_text = params_node.text.decode("utf-8") if params_node else "()"
        sig = f"function {name}{params_text}"

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
            complexity_score=complexity,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=parent_id,
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

    # ── Property / Const ─────────────────────────────────────────────────────

    def _extract_property(self, node, file_path, file_id, result, name_to_id, class_sym):
        for child in node.named_children:
            if child.type == "property_element":
                var_node = child.named_children[0] if child.named_children else None
                if not var_node or var_node.type != "variable_name":
                    continue
                name_node = var_node.child_by_field_name("name") or (
                    var_node.named_children[0] if var_node.named_children else None
                )
                if not name_node:
                    continue
                name = "$" + name_node.text.decode("utf-8")
                is_public = not any(
                    c.text.decode("utf-8") in ("private", "protected")
                    for c in node.named_children
                    if c.type == "visibility_modifier"
                )
                sym = SymbolRecord.create(
                    file_path=file_path,
                    file_id=file_id,
                    name=name,
                    kind=NodeKind.VARIABLE,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=name,
                    is_public=is_public,
                )
                result.symbols.append(sym)
                name_to_id[name] = sym.id

    def _extract_const(self, node, file_path, file_id, result, name_to_id, class_sym):
        for child in node.named_children:
            if child.type == "const_element":
                name_node = child.child_by_field_name("name") or (
                    child.named_children[0] if child.named_children else None
                )
                if not name_node:
                    continue
                name = name_node.text.decode("utf-8")
                sym = SymbolRecord.create(
                    file_path=file_path,
                    file_id=file_id,
                    name=name,
                    kind=NodeKind.VARIABLE,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=f"const {name}",
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
            if n.type in _PHP_BRANCH_TYPES:
                count[0] += 1
            for c in n.named_children:
                walk(c)

        walk(body_node)
        return float(count[0])


# ── Module-level helpers ──────────────────────────────────────────────────────


def _extract_calls(body_node) -> list[tuple[str, int]]:
    """Walk a function/method body and collect (callee_name, line) pairs."""
    calls: list[tuple[str, int]] = []

    def walk(n):
        if n.type in ("function_call_expression", "member_call_expression"):
            name_node = n.child_by_field_name("function") or n.child_by_field_name("name")
            if name_node and name_node.type == "name":
                calls.append((name_node.text.decode("utf-8"), n.start_point[0] + 1))
        for c in n.named_children:
            walk(c)

    walk(body_node)
    return calls
