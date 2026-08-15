"""JavaScript and TypeScript parser using tree-sitter."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
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

_JS_BRANCH_TYPES = frozenset({
    "if_statement",
    "for_statement",
    "for_in_statement",
    "while_statement",
    "do_statement",
    "try_statement",
    "catch_clause",
    "switch_case",
    "switch_default",
    "ternary_expression",
})


class JavaScriptParser(BaseParser):
    """Extracts symbols and edges from JavaScript and TypeScript files."""

    def __init__(self) -> None:
        self._js_parser = None
        self._ts_parser = None
        self._tsx_parser = None

    @property
    def language_name(self) -> str:
        return "javascript"

    @property
    def supported_extensions(self) -> list[str]:
        return [".js", ".jsx", ".mjs", ".ts", ".tsx", ".mts"]

    # ── Public entry ─────────────────────────────────────────────────────────

    def parse(self, file_path: str, content: str) -> ParseResult:
        ext = Path(file_path).suffix.lower()
        lang_name = "typescript" if ext in (".ts", ".tsx", ".mts") else "javascript"

        parser = self._get_parser(ext)
        source = content.encode("utf-8")
        tree = parser.parse(source)
        file_id = make_file_id(file_path)

        try:
            last_modified = os.path.getmtime(file_path)
        except OSError:
            last_modified = 0.0

        file_rec = FileRecord(
            id=file_id,
            path=file_path,
            language=lang_name,
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )

        result = ParseResult(file=file_rec)
        name_to_id: dict[str, str] = {}
        root_type = "program"  # js/ts root node

        self._process_program(tree.root_node, file_path, file_id, source, result, name_to_id)
        self._resolve_intrafile_refs(result, name_to_id)
        return result

    # ── Parser construction ───────────────────────────────────────────────────

    def _get_parser(self, ext: str):
        from tree_sitter import Language, Parser as TSParser

        if ext in (".ts", ".mts"):
            if self._ts_parser is None:
                import tree_sitter_typescript as tst
                self._ts_parser = TSParser(Language(tst.language_typescript()))
            return self._ts_parser
        elif ext == ".tsx":
            if self._tsx_parser is None:
                import tree_sitter_typescript as tst
                self._tsx_parser = TSParser(Language(tst.language_tsx()))
            return self._tsx_parser
        else:
            if self._js_parser is None:
                import tree_sitter_javascript as tsj
                self._js_parser = TSParser(Language(tsj.language()))
            return self._js_parser

    # ── Program traversal ─────────────────────────────────────────────────────

    def _process_program(self, root, file_path, file_id, source, result, name_to_id):
        for node in root.named_children:
            self._process_stmt(node, file_path, file_id, source, result, name_to_id, class_sym=None)

    def _process_stmt(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        t = node.type
        if t == "function_declaration":
            self._extract_function(node, file_path, file_id, source, result, name_to_id, class_sym)
        elif t == "class_declaration":
            self._extract_class(node, file_path, file_id, source, result, name_to_id)
        elif t == "import_statement":
            self._extract_import(node, file_path, file_id, source, result, name_to_id)
        elif t == "export_statement":
            # Unwrap the declaration inside the export
            decl = node.child_by_field_name("declaration")
            if decl:
                self._process_stmt(decl, file_path, file_id, source, result, name_to_id, class_sym)
            else:
                # export default function() {} or export default class {}
                for child in node.named_children:
                    if child.type in ("function_declaration", "class_declaration",
                                      "function", "class"):
                        self._process_stmt(child, file_path, file_id, source, result, name_to_id, class_sym)
        elif t in ("lexical_declaration", "variable_declaration"):
            self._extract_variable_decl(node, file_path, file_id, source, result, name_to_id, class_sym)
        # TypeScript-specific
        elif t == "interface_declaration":
            self._extract_interface(node, file_path, file_id, source, result, name_to_id)
        elif t == "type_alias_declaration":
            self._extract_type_alias(node, file_path, file_id, source, result, name_to_id)

    # ── Function extraction ───────────────────────────────────────────────────

    def _extract_function(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        is_async = any(not c.is_named and c.type == "async" for c in node.children)

        params_node = node.child_by_field_name("parameters")
        sig = name + (params_node.text.decode("utf-8") if params_node else "()")

        body_node = node.child_by_field_name("body")
        docstring = self._get_jsdoc(node, source)
        complexity = self._complexity(body_node)

        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            docstring=docstring,
            is_async=is_async,
            is_public=not name.startswith("_"),
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id

        parent_id = class_sym.id if class_sym else file_id
        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES, from_id=parent_id, to_id=sym.id,
            file_path=file_path, line_number=node.start_point[0] + 1,
        ))

        if body_node:
            for callee, line in self._extract_call_names(body_node):
                result.unresolved_refs.append(UnresolvedRef(
                    from_id=sym.id, ref_name=callee,
                    kind=EdgeKind.CALLS, file_path=file_path, line_number=line,
                ))

    def _extract_method(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        is_async = any(not c.is_named and c.type == "async" for c in node.children)

        params_node = node.child_by_field_name("parameters")
        sig = name + (params_node.text.decode("utf-8") if params_node else "()")

        body_node = node.child_by_field_name("body")
        complexity = self._complexity(body_node)

        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_async=is_async,
            is_public=not name.startswith("_"),
            complexity_score=complexity,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        if class_sym:
            name_to_id[f"{class_sym.name}.{name}"] = sym.id

        parent_id = class_sym.id if class_sym else file_id
        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES, from_id=parent_id, to_id=sym.id,
            file_path=file_path, line_number=node.start_point[0] + 1,
        ))

        if body_node:
            for callee, line in self._extract_call_names(body_node):
                result.unresolved_refs.append(UnresolvedRef(
                    from_id=sym.id, ref_name=callee,
                    kind=EdgeKind.CALLS, file_path=file_path, line_number=line,
                ))

    # ── Class extraction ──────────────────────────────────────────────────────

    def _extract_class(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        # Heritage: `extends BaseClass`
        heritage_node = next(
            (c for c in node.named_children if c.type == "class_heritage"), None
        )
        base_classes: list[str] = []
        if heritage_node:
            for child in heritage_node.named_children:
                if child.type in ("identifier", "member_expression"):
                    base_classes.append(child.text.decode("utf-8"))

        docstring = self._get_jsdoc(node, source)

        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=docstring,
            is_public=not name.startswith("_"),
            extra={"base_classes": base_classes},
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id

        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES, from_id=file_id, to_id=sym.id,
            file_path=file_path, line_number=node.start_point[0] + 1,
        ))

        for base in base_classes:
            result.unresolved_refs.append(UnresolvedRef(
                from_id=sym.id, ref_name=base,
                kind=EdgeKind.INHERITS, file_path=file_path,
                line_number=node.start_point[0] + 1,
            ))

        # Process class body
        body_node = next(
            (c for c in node.named_children if c.type == "class_body"), None
        )
        if body_node:
            for child in body_node.named_children:
                if child.type == "method_definition":
                    self._extract_method(child, file_path, file_id, source, result, name_to_id, sym)
                elif child.type in ("public_field_definition", "field_definition"):
                    # Class field / property
                    self._extract_class_field(child, file_path, file_id, source, result, name_to_id, sym)

    def _extract_class_field(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.VARIABLE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            is_public=not name.startswith("_"),
        )
        result.symbols.append(sym)
        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES, from_id=class_sym.id, to_id=sym.id,
            file_path=file_path, line_number=node.start_point[0] + 1,
        ))

    # ── Import extraction ─────────────────────────────────────────────────────

    def _extract_import(self, node, file_path, file_id, source, result, name_to_id):
        line = node.start_point[0] + 1

        # Source module: string literal child (last named child usually)
        source_node = next(
            (c for c in reversed(node.named_children) if c.type == "string"), None
        )
        source_module = ""
        if source_node:
            for c in source_node.named_children:
                if c.type == "string_fragment":
                    source_module = c.text.decode("utf-8")

        # Import clause: named_imports or namespace_import
        clause = next(
            (c for c in node.named_children if c.type == "import_clause"), None
        )
        if not clause:
            return

        for child in clause.named_children:
            if child.type == "named_imports":
                for spec in child.named_children:
                    if spec.type == "import_specifier":
                        name_node = spec.child_by_field_name("name") or (
                            spec.named_children[0] if spec.named_children else None
                        )
                        alias_node = spec.child_by_field_name("alias")
                        if name_node:
                            original = name_node.text.decode("utf-8")
                            alias = alias_node.text.decode("utf-8") if alias_node else original
                            sym = SymbolRecord.create(
                                file_path=file_path, file_id=file_id,
                                name=alias, kind=NodeKind.IMPORT,
                                line_start=line, line_end=line,
                                extra={"is_from_import": True, "source_module": source_module, "original": original},
                            )
                            result.symbols.append(sym)
                            name_to_id[alias] = sym.id
            elif child.type in ("identifier", "namespace_import"):
                # import Foo from '...' or import * as Foo from '...'
                name_text = child.text.decode("utf-8").lstrip("* as ").strip()
                if name_text:
                    sym = SymbolRecord.create(
                        file_path=file_path, file_id=file_id,
                        name=name_text, kind=NodeKind.IMPORT,
                        line_start=line, line_end=line,
                        extra={"is_from_import": False, "source_module": source_module},
                    )
                    result.symbols.append(sym)
                    name_to_id[name_text] = sym.id

    # ── Variable declaration extraction ───────────────────────────────────────

    def _extract_variable_decl(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        for child in node.named_children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                val_node = child.child_by_field_name("value")
                if not name_node or name_node.type not in ("identifier", "shorthand_property_identifier_pattern"):
                    continue
                name = name_node.text.decode("utf-8")

                # Arrow function → treat as function
                if val_node and val_node.type in ("arrow_function", "function"):
                    is_async = any(not c.is_named and c.type == "async" for c in val_node.children)
                    params = val_node.child_by_field_name("parameters") or val_node.child_by_field_name("parameter")
                    sig = name + (params.text.decode("utf-8") if params else "()")
                    body_node = val_node.child_by_field_name("body")
                    complexity = self._complexity(body_node)
                    sym = SymbolRecord.create(
                        file_path=file_path, file_id=file_id,
                        name=name, kind=NodeKind.FUNCTION,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        signature=sig, is_async=is_async,
                        is_public=not name.startswith("_"),
                        complexity_score=complexity,
                    )
                    result.symbols.append(sym)
                    name_to_id[name] = sym.id
                    parent_id = class_sym.id if class_sym else file_id
                    result.edges.append(EdgeRecord.create(
                        kind=EdgeKind.DEFINES, from_id=parent_id, to_id=sym.id,
                        file_path=file_path, line_number=node.start_point[0] + 1,
                    ))
                    if body_node:
                        for callee, line in self._extract_call_names(body_node):
                            result.unresolved_refs.append(UnresolvedRef(
                                from_id=sym.id, ref_name=callee,
                                kind=EdgeKind.CALLS, file_path=file_path, line_number=line,
                            ))
                else:
                    # Regular variable/constant
                    is_const = any(not c.is_named and c.type == "const" for c in node.children)
                    sym = SymbolRecord.create(
                        file_path=file_path, file_id=file_id,
                        name=name, kind=NodeKind.VARIABLE,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        is_public=not name.startswith("_"),
                        extra={"is_constant": is_const},
                    )
                    result.symbols.append(sym)
                    name_to_id[name] = sym.id

    # ── TypeScript interface / type alias ─────────────────────────────────────

    def _extract_interface(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.TYPE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"interface {name}",
            is_public=not name.startswith("_"),
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES, from_id=file_id, to_id=sym.id,
            file_path=file_path, line_number=node.start_point[0] + 1,
        ))

    def _extract_type_alias(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.TYPE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=node.text.decode("utf-8"),
            is_public=not name.startswith("_"),
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES, from_id=file_id, to_id=sym.id,
            file_path=file_path, line_number=node.start_point[0] + 1,
        ))

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
    def _get_jsdoc(node, source: bytes) -> Optional[str]:
        """Extract JSDoc comment immediately preceding the node."""
        start = node.start_byte
        # Look for /** ... */ before the node
        preceding = source[:start].rstrip()
        if preceding.endswith(b"*/"):
            block_start = preceding.rfind(b"/**")
            if block_start >= 0:
                doc = preceding[block_start:].decode("utf-8", errors="replace")
                lines = [
                    line.strip().lstrip("/*").lstrip("* ").rstrip()
                    for line in doc.splitlines()
                ]
                return " ".join(l for l in lines if l)
        return None

    @staticmethod
    def _complexity(body_node) -> float:
        if not body_node:
            return 1.0
        count = [1]

        def walk(n):
            if n.type in _JS_BRANCH_TYPES:
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
                    elif func.type in ("member_expression", "attribute"):
                        prop = func.child_by_field_name("property")
                        if prop:
                            calls.append((prop.text.decode("utf-8"), n.start_point[0] + 1))
            for c in n.children:
                walk(c)

        walk(body_node)
        return calls
