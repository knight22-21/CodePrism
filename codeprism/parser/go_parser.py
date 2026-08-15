"""Go source parser using tree-sitter."""

from __future__ import annotations

import hashlib
import os
import time
from typing import Optional

from ..core.models import (
    EdgeKind,
    EdgeRecord,
    FileRecord,
    NodeKind,
    SymbolRecord,
    make_file_id,
)
from .base import BaseParser, ParseResult, UnresolvedRef

_GO_BRANCH_TYPES = frozenset({
    "if_statement",
    "for_statement",
    "range_clause",
    "select_statement",
    "switch_statement",
    "expression_case",
    "default_case",
    "type_switch_statement",
})


class GoParser(BaseParser):
    """Extracts symbols and edges from Go source files via tree-sitter."""

    def __init__(self) -> None:
        try:
            import tree_sitter_go as tsg
            from tree_sitter import Language, Parser as TSParser
            self._language = Language(tsg.language())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-go is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "go"

    @property
    def supported_extensions(self) -> list[str]:
        return [".go"]

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
            language="go",
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )

        result = ParseResult(file=file_rec)
        name_to_id: dict[str, str] = {}

        self._process_source_file(tree.root_node, file_path, file_id, source, result, name_to_id)
        self._resolve_intrafile_refs(result, name_to_id)
        return result

    # ── Source file traversal ─────────────────────────────────────────────────

    def _process_source_file(self, root, file_path, file_id, source, result, name_to_id):
        for node in root.named_children:
            t = node.type
            if t == "function_declaration":
                self._extract_function(node, file_path, file_id, source, result, name_to_id, receiver_type=None)
            elif t == "method_declaration":
                self._extract_method(node, file_path, file_id, source, result, name_to_id)
            elif t == "type_declaration":
                self._extract_type_decl(node, file_path, file_id, source, result, name_to_id)
            elif t == "import_declaration":
                self._extract_import(node, file_path, file_id, source, result, name_to_id)
            elif t in ("var_declaration", "const_declaration"):
                self._extract_var_const(node, file_path, file_id, source, result, name_to_id)

    # ── Function extraction ───────────────────────────────────────────────────

    def _extract_function(self, node, file_path, file_id, source, result, name_to_id, receiver_type):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        params_node = node.child_by_field_name("parameters")
        result_node = node.child_by_field_name("result")
        body_node = node.child_by_field_name("body")

        sig = name
        if receiver_type:
            sig = f"({receiver_type}) {sig}"
        if params_node:
            sig += params_node.text.decode("utf-8")
        if result_node:
            sig += " " + result_node.text.decode("utf-8")

        complexity = self._complexity(body_node)
        is_public = name[0].isupper() if name else False

        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=is_public,
            complexity_score=complexity,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        if receiver_type:
            name_to_id[f"{receiver_type}.{name}"] = sym.id

        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES, from_id=file_id, to_id=sym.id,
            file_path=file_path, line_number=node.start_point[0] + 1,
        ))

        if body_node:
            for callee, line in self._extract_call_names(body_node):
                result.unresolved_refs.append(UnresolvedRef(
                    from_id=sym.id, ref_name=callee,
                    kind=EdgeKind.CALLS, file_path=file_path, line_number=line,
                ))

    def _extract_method(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")  # field_identifier
        receiver_node = node.child_by_field_name("receiver")

        if not name_node:
            return

        receiver_type = None
        if receiver_node:
            # parameter_list → parameter_declaration → type (pointer_type or type_identifier)
            for pdecl in receiver_node.named_children:
                if pdecl.type == "parameter_declaration":
                    type_node = pdecl.child_by_field_name("type")
                    if type_node:
                        t = type_node.text.decode("utf-8").lstrip("*").strip()
                        receiver_type = t

        self._extract_function(node, file_path, file_id, source, result, name_to_id, receiver_type)

    # ── Type declaration extraction ───────────────────────────────────────────

    def _extract_type_decl(self, node, file_path, file_id, source, result, name_to_id):
        for spec in node.named_children:
            if spec.type != "type_spec":
                continue
            name_node = spec.child_by_field_name("name")  # type_identifier
            type_node = spec.child_by_field_name("type")
            if not name_node:
                continue
            name = name_node.text.decode("utf-8")
            type_kind = type_node.type if type_node else "unknown"

            # struct and interface → CLASS, others → TYPE
            node_kind = NodeKind.CLASS if type_kind in ("struct_type", "interface_type") else NodeKind.TYPE
            sym = SymbolRecord.create(
                file_path=file_path, file_id=file_id,
                name=name, kind=node_kind,
                line_start=node.start_point[0] + 1,
                line_end=node.end_point[0] + 1,
                signature=f"type {name} {type_kind}",
                is_public=name[0].isupper() if name else False,
                extra={"go_type_kind": type_kind},
            )
            result.symbols.append(sym)
            name_to_id[name] = sym.id
            result.edges.append(EdgeRecord.create(
                kind=EdgeKind.DEFINES, from_id=file_id, to_id=sym.id,
                file_path=file_path, line_number=node.start_point[0] + 1,
            ))

    # ── Import extraction ─────────────────────────────────────────────────────

    def _extract_import(self, node, file_path, file_id, source, result, name_to_id):
        line = node.start_point[0] + 1

        def process_spec(spec):
            path_node = spec.child_by_field_name("path")
            alias_node = spec.child_by_field_name("name")
            if not path_node:
                return
            raw_path = path_node.text.decode("utf-8").strip('"')
            pkg_name = raw_path.split("/")[-1]
            alias = alias_node.text.decode("utf-8") if alias_node else pkg_name
            sym = SymbolRecord.create(
                file_path=file_path, file_id=file_id,
                name=alias, kind=NodeKind.IMPORT,
                line_start=line, line_end=line,
                extra={"is_from_import": False, "source_module": raw_path},
            )
            result.symbols.append(sym)
            name_to_id[alias] = sym.id
            result.unresolved_refs.append(UnresolvedRef(
                from_id=file_id, ref_name=raw_path,
                kind=EdgeKind.IMPORTS, file_path=file_path, line_number=line,
            ))

        for child in node.named_children:
            if child.type == "import_spec":
                process_spec(child)
            elif child.type == "import_spec_list":
                for spec in child.named_children:
                    if spec.type == "import_spec":
                        process_spec(spec)

    # ── Var / const extraction ────────────────────────────────────────────────

    def _extract_var_const(self, node, file_path, file_id, source, result, name_to_id):
        is_const = node.type == "const_declaration"
        for child in node.named_children:
            if child.type not in ("var_spec", "const_spec"):
                continue
            for id_node in child.named_children:
                if id_node.type == "identifier":
                    name = id_node.text.decode("utf-8")
                    sym = SymbolRecord.create(
                        file_path=file_path, file_id=file_id,
                        name=name, kind=NodeKind.VARIABLE,
                        line_start=child.start_point[0] + 1,
                        line_end=child.end_point[0] + 1,
                        is_public=name[0].isupper() if name else False,
                        extra={"is_constant": is_const},
                    )
                    result.symbols.append(sym)
                    name_to_id[name] = sym.id
                    break  # only first identifier in the spec

    # ── Intra-file resolution ─────────────────────────────────────────────────

    def _resolve_intrafile_refs(self, result: ParseResult, name_to_id: dict[str, str]) -> None:
        still: list[UnresolvedRef] = []
        for ref in result.unresolved_refs:
            target_id = name_to_id.get(ref.ref_name)
            if target_id and target_id != ref.from_id:
                result.edges.append(EdgeRecord.create(
                    kind=ref.kind, from_id=ref.from_id, to_id=target_id,
                    file_path=ref.file_path, line_number=ref.line_number,
                ))
            else:
                still.append(ref)
        result.unresolved_refs = still

    # ── AST helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _complexity(body_node) -> float:
        if not body_node:
            return 1.0
        count = [1]

        def walk(n):
            if n.type in _GO_BRANCH_TYPES:
                count[0] += 1
            for c in n.children:
                walk(c)

        walk(body_node)
        return float(count[0])

    @staticmethod
    def _extract_call_names(body_node) -> list[tuple[str, int]]:
        calls: list[tuple[str, int]] = []

        def walk(n):
            if n.type == "call_expression":
                func = n.child_by_field_name("function")
                if func:
                    if func.type == "identifier":
                        calls.append((func.text.decode("utf-8"), n.start_point[0] + 1))
                    elif func.type == "selector_expression":
                        field_node = func.child_by_field_name("field")
                        if field_node:
                            calls.append((field_node.text.decode("utf-8"), n.start_point[0] + 1))
            for c in n.children:
                walk(c)

        walk(body_node)
        return calls
