"""Python source parser using tree-sitter."""

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

_BRANCH_TYPES = frozenset({
    "if_statement",
    "elif_clause",
    "for_statement",
    "while_statement",
    "try_statement",
    "except_clause",
    "with_statement",
    "boolean_operator",
    "conditional_expression",
    "match_statement",
    "case_clause",
})


class PythonParser(BaseParser):
    """Extracts symbols and edges from Python source files via tree-sitter."""

    def __init__(self) -> None:
        try:
            import tree_sitter_python as tsp
            from tree_sitter import Language, Parser as TSParser
            self._language = Language(tsp.language())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-python is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "python"

    @property
    def supported_extensions(self) -> list[str]:
        return [".py", ".pyi"]

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
            language="python",
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )

        result = ParseResult(file=file_rec)
        name_to_id: dict[str, str] = {}

        self._process_module(tree.root_node, file_path, file_id, source, result, name_to_id)
        self._resolve_intrafile_refs(result, name_to_id)

        return result

    # ── Module-level traversal ────────────────────────────────────────────────

    def _process_module(self, root, file_path, file_id, source, result, name_to_id):
        for node in root.children:
            self._process_stmt(node, file_path, file_id, source, result, name_to_id, class_sym=None)

    def _process_stmt(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        t = node.type
        if t == "function_definition":
            self._extract_function(node, file_path, file_id, source, result, name_to_id, class_sym)
        elif t == "decorated_definition":
            defn = node.child_by_field_name("definition")
            if defn:
                self._process_stmt(defn, file_path, file_id, source, result, name_to_id, class_sym)
        elif t == "class_definition":
            self._extract_class(node, file_path, file_id, source, result, name_to_id)
        elif t in ("import_statement", "import_from_statement"):
            self._extract_import(node, file_path, file_id, source, result, name_to_id)
        elif t == "expression_statement":
            for child in node.named_children:
                if child.type == "assignment":
                    self._extract_variable(child, file_path, file_id, source, result, name_to_id, class_sym)
        elif t in ("type_alias_statement", "type_statement"):
            self._extract_type_alias(node, file_path, file_id, source, result, name_to_id)

    # ── Function extraction ───────────────────────────────────────────────────

    def _extract_function(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        # async detection: first unnamed child is "async"
        is_async = any(
            not c.is_named and c.type == "async"
            for c in node.children
        )

        params_node = node.child_by_field_name("parameters")
        ret_node = node.child_by_field_name("return_type")
        body_node = node.child_by_field_name("body")

        sig = name
        if params_node:
            sig += params_node.text.decode("utf-8")
        if ret_node:
            sig += " -> " + ret_node.text.decode("utf-8").lstrip("->").strip()

        docstring = self._get_docstring(body_node)
        complexity = self._complexity(body_node)
        is_public = not name.startswith("_") or (name.startswith("__") and name.endswith("__"))

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            docstring=docstring,
            is_async=is_async,
            is_public=is_public,
            complexity_score=complexity,
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        if class_sym:
            name_to_id[f"{class_sym.name}.{name}"] = sym.id

        parent_id = class_sym.id if class_sym else file_id
        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES,
            from_id=parent_id,
            to_id=sym.id,
            file_path=file_path,
            line_number=node.start_point[0] + 1,
        ))

        if body_node:
            for callee_name, line in self._extract_call_names(body_node):
                result.unresolved_refs.append(UnresolvedRef(
                    from_id=sym.id,
                    ref_name=callee_name,
                    kind=EdgeKind.CALLS,
                    file_path=file_path,
                    line_number=line,
                ))

    # ── Class extraction ──────────────────────────────────────────────────────

    def _extract_class(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        body_node = node.child_by_field_name("body")
        docstring = self._get_docstring(body_node)

        base_classes: list[str] = []
        supers_node = node.child_by_field_name("superclasses")
        if supers_node:
            for child in supers_node.named_children:
                if child.type in ("identifier", "dotted_name", "attribute"):
                    base_classes.append(child.text.decode("utf-8"))

        is_abstract = any(b in ("ABC", "ABCMeta") for b in base_classes)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            docstring=docstring,
            is_public=not name.startswith("_"),
            extra={"base_classes": base_classes, "is_abstract": is_abstract},
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id

        result.edges.append(EdgeRecord.create(
            kind=EdgeKind.DEFINES,
            from_id=file_id,
            to_id=sym.id,
            file_path=file_path,
            line_number=node.start_point[0] + 1,
        ))

        for base in base_classes:
            result.unresolved_refs.append(UnresolvedRef(
                from_id=sym.id,
                ref_name=base,
                kind=EdgeKind.INHERITS,
                file_path=file_path,
                line_number=node.start_point[0] + 1,
            ))

        if body_node:
            for child in body_node.children:
                self._process_stmt(child, file_path, file_id, source, result, name_to_id, class_sym=sym)

    # ── Import extraction ─────────────────────────────────────────────────────

    def _extract_import(self, node, file_path, file_id, source, result, name_to_id):
        line = node.start_point[0] + 1

        if node.type == "import_statement":
            for child in node.named_children:
                if child.type == "dotted_name":
                    mod = child.text.decode("utf-8")
                    sym = SymbolRecord.create(
                        file_path=file_path, file_id=file_id,
                        name=mod, kind=NodeKind.IMPORT,
                        line_start=line, line_end=line,
                        extra={"is_from_import": False, "source_module": mod},
                    )
                    result.symbols.append(sym)
                    name_to_id[mod.split(".")[0]] = sym.id
                    result.unresolved_refs.append(UnresolvedRef(
                        from_id=file_id, ref_name=mod,
                        kind=EdgeKind.IMPORTS, file_path=file_path, line_number=line,
                    ))
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if name_node:
                        mod = name_node.text.decode("utf-8")
                        alias = alias_node.text.decode("utf-8") if alias_node else None
                        key = alias or mod.split(".")[0]
                        sym = SymbolRecord.create(
                            file_path=file_path, file_id=file_id,
                            name=key, kind=NodeKind.IMPORT,
                            line_start=line, line_end=line,
                            extra={"is_from_import": False, "source_module": mod, "alias": alias},
                        )
                        result.symbols.append(sym)
                        name_to_id[key] = sym.id

        elif node.type == "import_from_statement":
            module_node = node.child_by_field_name("module_name")
            source_module = module_node.text.decode("utf-8") if module_node else ""

            named = node.named_children
            # First named child is the module; the rest are the imported names
            imported_nodes = named[1:] if len(named) > 1 else []

            for child in imported_nodes:
                if child.type == "wildcard_import":
                    sym = SymbolRecord.create(
                        file_path=file_path, file_id=file_id,
                        name=f"{source_module}.*", kind=NodeKind.IMPORT,
                        line_start=line, line_end=line,
                        extra={"is_from_import": True, "source_module": source_module},
                    )
                    result.symbols.append(sym)
                elif child.type in ("dotted_name", "identifier"):
                    imported = child.text.decode("utf-8")
                    sym = SymbolRecord.create(
                        file_path=file_path, file_id=file_id,
                        name=imported, kind=NodeKind.IMPORT,
                        line_start=line, line_end=line,
                        extra={"is_from_import": True, "source_module": source_module},
                    )
                    result.symbols.append(sym)
                    name_to_id[imported] = sym.id
                elif child.type == "aliased_import":
                    name_node = child.child_by_field_name("name")
                    alias_node = child.child_by_field_name("alias")
                    if name_node:
                        imported = name_node.text.decode("utf-8")
                        alias = alias_node.text.decode("utf-8") if alias_node else imported
                        sym = SymbolRecord.create(
                            file_path=file_path, file_id=file_id,
                            name=alias, kind=NodeKind.IMPORT,
                            line_start=line, line_end=line,
                            extra={"is_from_import": True, "source_module": source_module, "original": imported},
                        )
                        result.symbols.append(sym)
                        name_to_id[alias] = sym.id

    # ── Variable extraction ───────────────────────────────────────────────────

    def _extract_variable(self, node, file_path, file_id, source, result, name_to_id, class_sym):
        left_node = node.child_by_field_name("left")
        if not left_node or left_node.type != "identifier":
            return
        name = left_node.text.decode("utf-8")
        if name.startswith("__") and name.endswith("__"):
            return

        type_node = node.child_by_field_name("type")
        type_annotation = type_node.text.decode("utf-8") if type_node else None
        is_constant = name.isupper()
        scope = "class" if class_sym else "module"

        sym = SymbolRecord.create(
            file_path=file_path, file_id=file_id,
            name=name, kind=NodeKind.VARIABLE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=type_annotation,
            is_public=not name.startswith("_"),
            extra={"scope": scope, "type_annotation": type_annotation, "is_constant": is_constant},
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id

    # ── Type alias extraction ─────────────────────────────────────────────────

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

    # ── Intra-file resolution ─────────────────────────────────────────────────

    def _resolve_intrafile_refs(self, result: ParseResult, name_to_id: dict[str, str]) -> None:
        still_unresolved: list[UnresolvedRef] = []
        for ref in result.unresolved_refs:
            target_id = name_to_id.get(ref.ref_name)
            if target_id and target_id != ref.from_id:
                result.edges.append(EdgeRecord.create(
                    kind=ref.kind,
                    from_id=ref.from_id,
                    to_id=target_id,
                    file_path=ref.file_path,
                    line_number=ref.line_number,
                ))
            else:
                still_unresolved.append(ref)
        result.unresolved_refs = still_unresolved

    # ── AST helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _get_docstring(body_node) -> Optional[str]:
        if not body_node:
            return None
        for child in body_node.named_children:
            if child.type == "expression_statement":
                for sub in child.named_children:
                    if sub.type == "string":
                        raw = sub.text.decode("utf-8")
                        for q in ('"""', "'''", '"', "'"):
                            if raw.startswith(q) and raw.endswith(q) and len(raw) >= 2 * len(q):
                                return raw[len(q) : -len(q)].strip()
                        return raw.strip()
            break
        return None

    @staticmethod
    def _complexity(body_node) -> float:
        if not body_node:
            return 1.0
        count = [1]

        def walk(n):
            if n.type in _BRANCH_TYPES:
                count[0] += 1
            for c in n.children:
                walk(c)

        walk(body_node)
        return float(count[0])

    @staticmethod
    def _extract_call_names(body_node) -> list[tuple[str, int]]:
        calls: list[tuple[str, int]] = []

        def walk(n):
            if n.type == "call":
                func = n.child_by_field_name("function")
                if func:
                    if func.type == "identifier":
                        calls.append((func.text.decode("utf-8"), n.start_point[0] + 1))
                    elif func.type == "attribute":
                        attr = func.child_by_field_name("attribute")
                        if attr:
                            calls.append((attr.text.decode("utf-8"), n.start_point[0] + 1))
            for c in n.children:
                walk(c)

        walk(body_node)
        return calls
