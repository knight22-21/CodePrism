"""Java source parser using tree-sitter."""

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

_JAVA_BRANCH_TYPES = frozenset(
    {
        "if_statement",
        "for_statement",
        "enhanced_for_statement",
        "while_statement",
        "do_statement",
        "switch_expression",
        "switch_block_statement_group",
        "catch_clause",
        "ternary_expression",
        "lambda_expression",
    }
)


class JavaParser(BaseParser):
    """Extracts symbols and edges from Java source files via tree-sitter."""

    def __init__(self) -> None:
        try:
            import tree_sitter_java as tsj
            from tree_sitter import Language
            from tree_sitter import Parser as TSParser

            self._language = Language(tsj.language())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-java is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "java"

    @property
    def supported_extensions(self) -> list[str]:
        return [".java"]

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
            language="java",
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )

        result = ParseResult(file=file_rec)
        name_to_id: dict[str, str] = {}

        self._process_program(tree.root_node, file_path, file_id, source, result, name_to_id)
        self.resolve_intrafile_refs(result, name_to_id)
        return result

    # ── Top-level traversal ───────────────────────────────────────────────────

    def _process_program(self, root, file_path, file_id, source, result, name_to_id):
        for node in root.named_children:
            t = node.type
            if t == "class_declaration":
                self._extract_class(node, file_path, file_id, source, result, name_to_id)
            elif t == "interface_declaration":
                self._extract_class(
                    node, file_path, file_id, source, result, name_to_id, is_interface=True
                )
            elif t == "enum_declaration":
                self._extract_class(
                    node, file_path, file_id, source, result, name_to_id, is_enum=True
                )
            elif t == "import_declaration":
                self._extract_import(node, file_path, file_id, source, result, name_to_id)
            elif t == "package_declaration":
                self._extract_package(node, file_path, file_id, source, result, name_to_id)

    # ── Class / interface / enum extraction ──────────────────────────────────

    def _extract_class(
        self,
        node,
        file_path,
        file_id,
        source,
        result,
        name_to_id,
        is_interface: bool = False,
        is_enum: bool = False,
    ):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        keyword = "interface" if is_interface else "enum" if is_enum else "class"
        sig = f"{keyword} {name}"

        superclass_node = node.child_by_field_name("superclass")
        if superclass_node:
            sig += " " + superclass_node.text.decode("utf-8").strip()

        modifiers_node = _find_modifiers(node)
        is_public = _has_modifier(modifiers_node, "public")

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=is_public,
            extra={"is_interface": is_interface, "is_enum": is_enum},
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

        if superclass_node:
            super_name = _strip_prefix(superclass_node.text.decode("utf-8"), "extends").strip()
            if super_name:
                result.unresolved_refs.append(
                    UnresolvedRef(
                        from_id=sym.id,
                        ref_name=super_name,
                        kind=EdgeKind.INHERITS,
                        file_path=file_path,
                        line_number=superclass_node.start_point[0] + 1,
                    )
                )

        body_node = node.child_by_field_name("body")
        if body_node:
            for child in body_node.named_children:
                ct = child.type
                if ct == "method_declaration":
                    self._extract_method(
                        child, file_path, file_id, source, result, name_to_id, class_sym=sym
                    )
                elif ct == "constructor_declaration":
                    self._extract_method(
                        child,
                        file_path,
                        file_id,
                        source,
                        result,
                        name_to_id,
                        class_sym=sym,
                        is_constructor=True,
                    )
                elif ct == "field_declaration":
                    self._extract_field(child, file_path, file_id, source, result, name_to_id)
                elif ct == "class_declaration":
                    self._extract_class(child, file_path, file_id, source, result, name_to_id)
                elif ct == "interface_declaration":
                    self._extract_class(
                        child, file_path, file_id, source, result, name_to_id, is_interface=True
                    )

    # ── Method / constructor extraction ──────────────────────────────────────

    def _extract_method(
        self,
        node,
        file_path,
        file_id,
        source,
        result,
        name_to_id,
        class_sym=None,
        is_constructor: bool = False,
    ):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        params_node = node.child_by_field_name("parameters")
        type_node = node.child_by_field_name("type")

        sig = ""
        if type_node:
            sig += type_node.text.decode("utf-8") + " "
        sig += name
        if params_node:
            sig += params_node.text.decode("utf-8")

        modifiers_node = _find_modifiers(node)
        is_public = _has_modifier(modifiers_node, "public")

        body_node = node.child_by_field_name("body")
        complexity = self._complexity(body_node)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=is_public,
            is_method=(class_sym is not None),
            complexity_score=complexity,
            extra={"is_constructor": is_constructor},
        )
        result.symbols.append(sym)
        name_to_id[name] = sym.id
        if class_sym:
            name_to_id[f"{class_sym.name}.{name}"] = sym.id

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

    # ── Field extraction ──────────────────────────────────────────────────────

    def _extract_field(self, node, file_path, file_id, source, result, name_to_id):
        # field_declaration: modifiers? type variable_declarator+
        type_node = None
        modifiers_node = _find_modifiers(node)
        is_public = _has_modifier(modifiers_node, "public")
        is_constant = _has_modifier(modifiers_node, "final") and _has_modifier(
            modifiers_node, "static"
        )

        for child in node.named_children:
            if child.type not in (
                "modifiers",
                "variable_declarator",
                "variable_declarator_id",
            ):
                if type_node is None:
                    type_node = child
            if child.type == "variable_declarator":
                name = _declarator_name(child)
                if not name:
                    continue
                sig = (type_node.text.decode("utf-8") + " " if type_node else "") + name
                sym = SymbolRecord.create(
                    file_path=file_path,
                    file_id=file_id,
                    name=name,
                    kind=NodeKind.VARIABLE,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=sig,
                    is_public=is_public,
                    extra={"is_constant": is_constant},
                )
                result.symbols.append(sym)
                name_to_id[name] = sym.id

    # ── Import extraction ─────────────────────────────────────────────────────

    def _extract_import(self, node, file_path, file_id, source, result, name_to_id):
        line = node.start_point[0] + 1
        import_path = None
        is_static = any(c.type == "static" for c in node.children)

        for child in node.named_children:
            if child.type in ("identifier", "scoped_identifier"):
                import_path = child.text.decode("utf-8")
                break
        if not import_path:
            return

        pkg_name = import_path.split(".")[-1]
        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=pkg_name,
            kind=NodeKind.IMPORT,
            line_start=line,
            line_end=line,
            extra={"is_from_import": True, "source_module": import_path, "is_static": is_static},
        )
        result.symbols.append(sym)
        name_to_id[pkg_name] = sym.id
        result.unresolved_refs.append(
            UnresolvedRef(
                from_id=file_id,
                ref_name=import_path,
                kind=EdgeKind.IMPORTS,
                file_path=file_path,
                line_number=line,
            )
        )

    # ── Package extraction ────────────────────────────────────────────────────

    def _extract_package(self, node, file_path, file_id, source, result, name_to_id):
        line = node.start_point[0] + 1
        for child in node.named_children:
            if child.type in ("identifier", "scoped_identifier"):
                pkg_name = child.text.decode("utf-8")
                sym = SymbolRecord.create(
                    file_path=file_path,
                    file_id=file_id,
                    name=pkg_name,
                    kind=NodeKind.MODULE,
                    line_start=line,
                    line_end=line,
                    extra={"is_package": True},
                )
                result.symbols.append(sym)
                name_to_id[pkg_name] = sym.id
                break

    # ── AST helpers ───────────────────────────────────────────────────────────

    @staticmethod
    def _complexity(body_node) -> float:
        if not body_node:
            return 1.0
        count = [1]

        def walk(n):
            if n.type in _JAVA_BRANCH_TYPES:
                count[0] += 1
            for c in n.children:
                walk(c)

        walk(body_node)
        return float(count[0])

    @staticmethod
    def _extract_call_names(body_node) -> list[tuple[str, int]]:
        calls: list[tuple[str, int]] = []

        def walk(n):
            if n.type == "method_invocation":
                name_node = n.child_by_field_name("name")
                if name_node:
                    calls.append((name_node.text.decode("utf-8"), n.start_point[0] + 1))
            elif n.type == "object_creation_expression":
                type_node = n.child_by_field_name("type")
                if type_node:
                    calls.append((type_node.text.decode("utf-8"), n.start_point[0] + 1))
            for c in n.children:
                walk(c)

        walk(body_node)
        return calls


# ── Module-level helpers ──────────────────────────────────────────────────────


def _find_modifiers(node):
    """Return the modifiers node from a declaration node (searched by type, not field name)."""
    return next((c for c in node.named_children if c.type == "modifiers"), None)


def _has_modifier(modifiers_node, modifier: str) -> bool:
    if not modifiers_node:
        return False
    return modifier in modifiers_node.text.decode("utf-8").split()


def _strip_prefix(text: str, prefix: str) -> str:
    stripped = text.strip()
    if stripped.startswith(prefix):
        return stripped[len(prefix) :]
    return stripped


def _declarator_name(vd_node) -> str | None:
    """Extract the identifier from a variable_declarator node."""
    for child in vd_node.named_children:
        if child.type == "identifier":
            return child.text.decode("utf-8")
        if child.type == "variable_declarator_id":
            for gc in child.named_children:
                if gc.type == "identifier":
                    return gc.text.decode("utf-8")
    return None
