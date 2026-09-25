"""C and C++ source parser using tree-sitter."""

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

_C_BRANCH_TYPES = frozenset(
    {
        "if_statement",
        "for_statement",
        "while_statement",
        "do_statement",
        "switch_statement",
        "case_statement",
        "conditional_expression",
    }
)

_CPP_BRANCH_TYPES = _C_BRANCH_TYPES | frozenset(
    {
        "try_statement",
        "catch_clause",
        "range_based_for_statement",
    }
)


class CParser(BaseParser):
    """Extracts symbols and edges from C source files via tree-sitter."""

    _branch_types = _C_BRANCH_TYPES

    def __init__(self) -> None:
        try:
            import tree_sitter_c as tsc
            from tree_sitter import Language
            from tree_sitter import Parser as TSParser

            self._language = Language(tsc.language())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-c is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "c"

    @property
    def supported_extensions(self) -> list[str]:
        return [".c", ".h"]

    # ── Public entry ─────────────────────────────────────────────────────────

    def parse(self, file_path: str, content: str) -> ParseResult:
        source = content.encode("utf-8")
        tree = self._parser.parse(source)
        file_id = make_file_id(file_path)

        try:
            last_modified = os.path.getmtime(file_path)
        except OSError:
            last_modified = 0.0

        lang = self.language_name
        file_rec = FileRecord(
            id=file_id,
            path=file_path,
            language=lang,
            size_bytes=len(source),
            last_modified=last_modified,
            checksum=hashlib.sha256(source).hexdigest(),
            line_count=content.count("\n") + 1,
            indexed_at=time.time(),
        )

        result = ParseResult(file=file_rec)
        name_to_id: dict[str, str] = {}

        self._process_translation_unit(
            tree.root_node, file_path, file_id, source, result, name_to_id
        )
        self.resolve_intrafile_refs(result, name_to_id)
        return result

    # ── Top-level traversal ───────────────────────────────────────────────────

    def _process_translation_unit(self, root, file_path, file_id, source, result, name_to_id):
        for node in root.named_children:
            self._dispatch(node, file_path, file_id, source, result, name_to_id)

    def _dispatch(self, node, file_path, file_id, source, result, name_to_id):
        t = node.type
        if t == "function_definition":
            self._extract_function(node, file_path, file_id, source, result, name_to_id)
        elif t in ("struct_specifier", "union_specifier"):
            self._extract_struct(node, file_path, file_id, source, result, name_to_id)
        elif t == "enum_specifier":
            self._extract_enum(node, file_path, file_id, source, result, name_to_id)
        elif t == "preproc_include":
            self._extract_include(node, file_path, file_id, source, result, name_to_id)
        elif t == "declaration":
            self._extract_declaration(node, file_path, file_id, source, result, name_to_id)
        elif t == "type_definition":
            self._extract_typedef(node, file_path, file_id, source, result, name_to_id)

    # ── Function extraction ───────────────────────────────────────────────────

    def _extract_function(
        self,
        node,
        file_path,
        file_id,
        source,
        result,
        name_to_id,
        class_sym=None,
    ):
        declarator_node = node.child_by_field_name("declarator")
        body_node = node.child_by_field_name("body")

        name, params_text = _extract_func_name_and_params(declarator_node)
        if not name:
            return

        type_node = node.child_by_field_name("type")
        return_type = type_node.text.decode("utf-8") if type_node else ""
        sig = (
            f"{return_type} {name}{params_text}".strip() if return_type else f"{name}{params_text}"
        )

        complexity = self._calc_complexity(body_node)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.FUNCTION,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=sig,
            is_public=not name.startswith("_"),
            is_method=(class_sym is not None),
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
            for callee, line in _extract_call_names(body_node):
                result.unresolved_refs.append(
                    UnresolvedRef(
                        from_id=sym.id,
                        ref_name=callee,
                        kind=EdgeKind.CALLS,
                        file_path=file_path,
                        line_number=line,
                    )
                )

    # ── Struct / union extraction ─────────────────────────────────────────────

    def _extract_struct(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")
        keyword = node.type.replace("_specifier", "")

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.CLASS,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"{keyword} {name}",
            is_public=not name.startswith("_"),
            extra={"is_struct": True, "keyword": keyword},
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

    # ── Enum extraction ───────────────────────────────────────────────────────

    def _extract_enum(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=name,
            kind=NodeKind.TYPE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"enum {name}",
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

    # ── #include extraction ───────────────────────────────────────────────────

    def _extract_include(self, node, file_path, file_id, source, result, name_to_id):
        line = node.start_point[0] + 1
        path_node = None
        for child in node.named_children:
            if child.type in ("string_literal", "system_lib_string"):
                path_node = child
                break
        if not path_node:
            return

        raw = path_node.text.decode("utf-8").strip('<>"')
        pkg_name = raw.split("/")[-1].replace(".h", "").replace(".hpp", "")

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

    # ── Top-level variable declaration ────────────────────────────────────────

    def _extract_declaration(self, node, file_path, file_id, source, result, name_to_id):
        # Only extract init_declarator with a plain identifier (skip function protos)
        for child in node.named_children:
            if child.type == "init_declarator":
                decl = child.child_by_field_name("declarator")
                if decl and decl.type == "identifier":
                    name = decl.text.decode("utf-8")
                    type_node = node.child_by_field_name("type")
                    sig = (type_node.text.decode("utf-8") + " " if type_node else "") + name
                    sym = SymbolRecord.create(
                        file_path=file_path,
                        file_id=file_id,
                        name=name,
                        kind=NodeKind.VARIABLE,
                        line_start=node.start_point[0] + 1,
                        line_end=node.end_point[0] + 1,
                        signature=sig,
                        is_public=not name.startswith("_"),
                    )
                    result.symbols.append(sym)
                    name_to_id[name] = sym.id

    # ── Typedef extraction ────────────────────────────────────────────────────

    def _extract_typedef(self, node, file_path, file_id, source, result, name_to_id):
        # Find the alias name (last type_identifier/identifier in the node)
        last_id = None
        for child in reversed(node.named_children):
            if child.type in ("type_identifier", "identifier"):
                last_id = child.text.decode("utf-8")
                break
        if not last_id:
            return

        for child in node.named_children:
            if child.type in ("struct_specifier", "union_specifier"):
                self._extract_struct(child, file_path, file_id, source, result, name_to_id)

        sym = SymbolRecord.create(
            file_path=file_path,
            file_id=file_id,
            name=last_id,
            kind=NodeKind.TYPE,
            line_start=node.start_point[0] + 1,
            line_end=node.end_point[0] + 1,
            signature=f"typedef {last_id}",
            is_public=not last_id.startswith("_"),
        )
        result.symbols.append(sym)
        name_to_id[last_id] = sym.id

    # ── Complexity ────────────────────────────────────────────────────────────

    def _calc_complexity(self, body_node) -> float:
        branch_types = self.__class__._branch_types
        if not body_node:
            return 1.0
        count = [1]

        def walk(n):
            if n.type in branch_types:
                count[0] += 1
            for c in n.children:
                walk(c)

        walk(body_node)
        return float(count[0])


# ── C++ parser ────────────────────────────────────────────────────────────────


class CppParser(CParser):
    """Extracts symbols and edges from C++ source files via tree-sitter."""

    _branch_types = _CPP_BRANCH_TYPES

    def __init__(self) -> None:
        try:
            import tree_sitter_cpp as tscpp
            from tree_sitter import Language
            from tree_sitter import Parser as TSParser

            self._language = Language(tscpp.language())
            self._parser = TSParser(self._language)
        except Exception as exc:
            raise ImportError(f"tree-sitter-cpp is required: {exc}") from exc

    @property
    def language_name(self) -> str:
        return "cpp"

    @property
    def supported_extensions(self) -> list[str]:
        return [".cpp", ".cc", ".cxx", ".hpp", ".hh"]

    def _dispatch(self, node, file_path, file_id, source, result, name_to_id):
        t = node.type
        if t == "class_specifier":
            self._extract_class(node, file_path, file_id, source, result, name_to_id)
        elif t == "namespace_definition":
            self._extract_namespace(node, file_path, file_id, source, result, name_to_id)
        elif t == "template_declaration":
            # Unwrap the template: process its inner declaration/class/function
            for child in node.named_children:
                if child.type not in ("template_parameter_list",):
                    self._dispatch(child, file_path, file_id, source, result, name_to_id)
        else:
            super()._dispatch(node, file_path, file_id, source, result, name_to_id)

    # ── Class extraction ──────────────────────────────────────────────────────

    def _extract_class(self, node, file_path, file_id, source, result, name_to_id):
        name_node = node.child_by_field_name("name")
        if not name_node:
            return
        name = name_node.text.decode("utf-8")

        # base_class_clause is an unnamed child (not a field) in tree-sitter-cpp
        base_node = next((c for c in node.named_children if c.type == "base_class_clause"), None)
        sig = f"class {name}"
        if base_node:
            sig += " " + base_node.text.decode("utf-8").strip()

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

        # Inheritance: type_identifier may appear directly in base_class_clause
        # or nested inside a base_specifier depending on grammar version.
        if base_node:
            for child in base_node.named_children:
                if child.type in ("type_identifier", "qualified_identifier"):
                    base_name = child.text.decode("utf-8").split("::")[-1]
                    result.unresolved_refs.append(
                        UnresolvedRef(
                            from_id=sym.id,
                            ref_name=base_name,
                            kind=EdgeKind.INHERITS,
                            file_path=file_path,
                            line_number=child.start_point[0] + 1,
                        )
                    )
                elif child.type == "base_specifier":
                    for gc in child.named_children:
                        if gc.type in ("type_identifier", "qualified_identifier"):
                            base_name = gc.text.decode("utf-8").split("::")[-1]
                            result.unresolved_refs.append(
                                UnresolvedRef(
                                    from_id=sym.id,
                                    ref_name=base_name,
                                    kind=EdgeKind.INHERITS,
                                    file_path=file_path,
                                    line_number=gc.start_point[0] + 1,
                                )
                            )
                            break

        # Class body
        body_node = node.child_by_field_name("body")
        if body_node:
            for child in body_node.named_children:
                ct = child.type
                if ct == "function_definition":
                    self._extract_function(
                        child, file_path, file_id, source, result, name_to_id, class_sym=sym
                    )
                elif ct == "declaration":
                    # Could be a method prototype or field
                    self._extract_class_member_decl(
                        child, file_path, file_id, source, result, name_to_id, class_sym=sym
                    )
                elif ct == "class_specifier":
                    self._extract_class(child, file_path, file_id, source, result, name_to_id)
                elif ct == "template_declaration":
                    self._dispatch(child, file_path, file_id, source, result, name_to_id)

    # ── Class member declaration (field or prototype) ─────────────────────────

    def _extract_class_member_decl(
        self, node, file_path, file_id, source, result, name_to_id, class_sym=None
    ):
        # Check if it's a field declaration (not a function prototype)
        for child in node.named_children:
            if child.type in ("field_identifier", "identifier"):
                name = child.text.decode("utf-8")
                type_node = node.child_by_field_name("type")
                sig = (type_node.text.decode("utf-8") + " " if type_node else "") + name
                sym = SymbolRecord.create(
                    file_path=file_path,
                    file_id=file_id,
                    name=name,
                    kind=NodeKind.VARIABLE,
                    line_start=node.start_point[0] + 1,
                    line_end=node.end_point[0] + 1,
                    signature=sig,
                    is_public=True,
                )
                result.symbols.append(sym)
                name_to_id[name] = sym.id
                return

    # ── Namespace extraction ──────────────────────────────────────────────────

    def _extract_namespace(self, node, file_path, file_id, source, result, name_to_id):
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

        body_node = node.child_by_field_name("body")
        if body_node:
            for child in body_node.named_children:
                self._dispatch(child, file_path, file_id, source, result, name_to_id)


# ── Module-level AST helpers ──────────────────────────────────────────────────


def _extract_func_name_and_params(declarator) -> tuple[str | None, str]:
    """Recursively extract function name and parameter text from a declarator node."""
    if declarator is None:
        return None, "()"
    t = declarator.type
    if t == "function_declarator":
        inner = declarator.child_by_field_name("declarator")
        params = declarator.child_by_field_name("parameters")
        params_text = params.text.decode("utf-8") if params else "()"
        name = _declarator_name(inner)
        return name, params_text
    if t in ("pointer_declarator", "reference_declarator"):
        inner = declarator.child_by_field_name("declarator")
        return _extract_func_name_and_params(inner)
    return None, "()"


def _declarator_name(node) -> str | None:
    """Extract the final identifier from a (possibly nested) declarator."""
    if node is None:
        return None
    t = node.type
    if t == "identifier":
        return node.text.decode("utf-8")
    if t == "type_identifier":
        return node.text.decode("utf-8")
    if t == "field_identifier":
        return node.text.decode("utf-8")
    if t == "qualified_identifier":
        # C++: ClassName::method → take the last part
        name_node = node.child_by_field_name("name")
        if name_node:
            return name_node.text.decode("utf-8")
        for child in reversed(node.named_children):
            if child.type in ("identifier", "destructor_name", "operator_name"):
                return child.text.decode("utf-8")
    if t == "destructor_name":
        return node.text.decode("utf-8")
    if t in ("pointer_declarator", "reference_declarator"):
        inner = node.child_by_field_name("declarator")
        return _declarator_name(inner)
    return None


def _extract_call_names(body_node) -> list[tuple[str, int]]:
    """Walk a function body and collect (callee_name, line) pairs."""
    calls: list[tuple[str, int]] = []

    def walk(n):
        if n.type == "call_expression":
            func = n.child_by_field_name("function")
            if func:
                if func.type == "identifier":
                    calls.append((func.text.decode("utf-8"), n.start_point[0] + 1))
                elif func.type in ("field_expression", "qualified_identifier"):
                    field = func.child_by_field_name("field")
                    if field:
                        calls.append((field.text.decode("utf-8"), n.start_point[0] + 1))
        for c in n.children:
            walk(c)

    walk(body_node)
    return calls
