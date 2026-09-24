"""Rust source parser using tree-sitter."""

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

_RUST_BRANCH_TYPES = frozenset(
    {
        "if_expression",
        "match_expression",
        "for_expression",
        "while_expression",
        "loop_expression",
        "match_arm",
    }
)


class RustParser(BaseParser):
    """Extracts symbols and edges from Rust source files via tree-sitter."""

    def __init__(self) -> None:
        try:
            import tree_sitter_rust as tsr
            from tree_sitter import Language
            from tree_sitter import Parser as TSParser

            self._language = Language(tsr.language())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-rust is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "rust"

    @property
    def supported_extensions(self) -> list[str]:
        return [".rs"]

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
            language="rust",
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )

        result = ParseResult(file=file_rec)
        name_to_id: dict[str, str] = {}

        self._walk(tree.root_node, file_path, file_id, source, result, name_to_id)
        self._resolve_intrafile_refs(result, name_to_id)
        return result

    # ── AST walk ─────────────────────────────────────────────────────────────

    def _walk(self, node, file_path, file_id, source, result, name_to_id):
        for child in node.named_children:
            t = child.type
            if t == "function_item":
                self._extract_function(child, file_path, file_id, source, result, name_to_id)
            elif t == "struct_item":
                self._extract_struct(child, file_path, file_id, source, result, name_to_id)
            elif t == "enum_item":
                self._extract_enum(child, file_path, file_id, source, result, name_to_id)
            elif t == "trait_item":
                self._extract_trait(child, file_path, file_id, source, result, name_to_id)
            elif t == "impl_item":
                self._extract_impl(child, file_path, file_id, source, result, name_to_id)
            elif t == "type_item":
                self._extract_type_alias(child, file_path, file_id, source, result, name_to_id)
            elif t in ("use_declaration", "extern_crate_declaration"):
                self._extract_use(child, file_path, file_id, source, result, name_to_id)
            elif t in ("const_item", "static_item"):
                self._extract_const(child, file_path, file_id, source, result, name_to_id)
            elif t == "mod_item":
                # Recurse into inline modules
                body = child.child_by_field_name("body")
                if body:
                    self._walk(body, file_path, file_id, source, result, name_to_id)

    # ── Function extraction ───────────────────────────────────────────────────

    def _extract_function(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        params_node = node.child_by_field_name("parameters")
        ret_node = node.child_by_field_name("return_type")
        body_node = node.child_by_field_name("body")

        sig = f"fn {name}"
        if params_node:
            sig += params_node.text.decode("utf-8")
        if ret_node:
            sig += " -> " + ret_node.text.decode("utf-8")

        complexity = self._complexity(body_node)
        # pub fn → public; bare fn → private
        is_public = any(c.type == "visibility_modifier" for c in node.named_children)

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

        result.edges.append(
            EdgeRecord.create(
                kind=EdgeKind.DEFINES,
                from_id=file_id,
                to_id=sym.id,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
            )
        )

        if body_node:
            for callee, line in self._extract_call_names(body_node):
                result.unresolved_refs.append(
                    UnresolvedRef(
                        from_id=sym.id,
                        ref_name=callee,
                        kind=EdgeKind.CALLS,
                        file_path=file_path,
                        line_number=line,
                    )
                )

    # ── Struct / Enum / Trait ─────────────────────────────────────────────────

    def _extract_struct(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        is_public = any(c.type == "visibility_modifier" for c in node.named_children)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"struct {name}",
            is_public=is_public,
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

    def _extract_enum(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        is_public = any(c.type == "visibility_modifier" for c in node.named_children)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.TYPE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"enum {name}",
            is_public=is_public,
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

    def _extract_trait(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        is_public = any(c.type == "visibility_modifier" for c in node.named_children)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.TYPE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"trait {name}",
            is_public=is_public,
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

        # Extract method signatures inside the trait
        body = node.child_by_field_name("body")
        if body:
            for child in body.named_children:
                if child.type == "function_item":
                    self._extract_function(child, file_path, file_id, source, result, name_to_id)

    def _extract_impl(self, node, file_path, file_id, source, result, name_to_id):
        """Extract methods from impl blocks."""
        body = node.child_by_field_name("body")
        if not body:
            return
        for child in body.named_children:
            if child.type == "function_item":
                self._extract_function(child, file_path, file_id, source, result, name_to_id)

    # ── Type alias ────────────────────────────────────────────────────────────

    def _extract_type_alias(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        is_public = any(c.type == "visibility_modifier" for c in node.named_children)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.TYPE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"type {name}",
            is_public=is_public,
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

    # ── Use / import ─────────────────────────────────────────────────────────

    def _extract_use(self, node, file_path, file_id, source, result, name_to_id):
        text = node.text.decode("utf-8").strip()
        # Grab last path segment as import name
        name = text.rstrip(";").split("::")[-1].strip("{} ")
        if not name or name in ("self", "super", "*"):
            return

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.IMPORT,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=text,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id

    # ── Const / static ────────────────────────────────────────────────────────

    def _extract_const(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        is_public = any(c.type == "visibility_modifier" for c in node.named_children)
        prefix = "const" if node.type == "const_item" else "static"

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.VARIABLE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"{prefix} {name}",
            is_public=is_public,
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

    # ── Call extraction ───────────────────────────────────────────────────────

    def _extract_call_names(self, node) -> list[tuple[str, int]]:
        calls: list[tuple[str, int]] = []
        self._collect_calls(node, calls)
        return calls

    def _collect_calls(self, node, calls: list) -> None:
        if node.type == "call_expression":
            fn_node = node.child_by_field_name("function")
            if fn_node:
                name = fn_node.text.decode("utf-8").split("::")[-1].split(".")[-1]
                if name.isidentifier():
                    calls.append((name, node.start_point[0] + 1))
        for child in node.named_children:
            self._collect_calls(child, calls)

    # ── Complexity ────────────────────────────────────────────────────────────

    def _complexity(self, node) -> int:
        if node is None:
            return 1
        count = 1
        self._count_branches(node, count)
        return count

    def _count_branches(self, node, count: int) -> int:
        for child in node.named_children:
            if child.type in _RUST_BRANCH_TYPES:
                count += 1
            count = self._count_branches(child, count)
        return count

    # ── Intra-file resolution (inherited from base — noop here) ──────────────

    def _resolve_intrafile_refs(self, result: ParseResult, name_to_id: dict) -> None:
        resolved = []
        for ref in result.unresolved_refs:
            if ref.ref_name in name_to_id:
                target_id = name_to_id[ref.ref_name]
                if target_id != ref.from_id:
                    resolved.append(
                        EdgeRecord.create(
                            kind=ref.kind,
                            from_id=ref.from_id,
                            to_id=target_id,
                            file_path=ref.file_path,
                            line_number=ref.line_number,
                        )
                    )
        result.edges.extend(resolved)
        result.unresolved_refs = [r for r in result.unresolved_refs if r.ref_name not in name_to_id]
