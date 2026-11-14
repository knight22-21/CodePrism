"""Independent tree-sitter ground truth for non-Python Level 3 fixtures.

This module deliberately has its own traversal and symbol classification rather
than importing CodePrism parser implementations. It provides a common oracle
for the language fixtures used by the Level 3 benchmark.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from pathlib import Path


LANGUAGE_MODULES = {
    "javascript": ("tree_sitter_javascript", "language"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "go": ("tree_sitter_go", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "ruby": ("tree_sitter_ruby", "language"),
    "php": ("tree_sitter_php", "language_php"),
}

FUNCTION_TYPES = {
    "javascript": {"function_declaration", "method_definition"},
    "typescript": {"function_declaration", "method_definition"},
    "go": {"function_declaration", "method_declaration"},
    "rust": {"function_item"},
    "java": {"method_declaration", "constructor_declaration"},
    "c": {"function_definition"},
    "cpp": {"function_definition"},
    "ruby": {"method", "singleton_method"},
    "php": {"method_declaration", "function_definition"},
}

CLASS_TYPES = {
    "javascript": {"class_declaration"},
    "typescript": {"class_declaration"},
    "go": set(),
    "rust": {"struct_item", "impl_item"},
    "java": {"class_declaration", "interface_declaration"},
    "c": {"struct_specifier"},
    "cpp": {"class_specifier"},
    "ruby": {"class"},
    "php": {"class_declaration", "interface_declaration", "trait_declaration"},
}

TYPE_TYPES = {
    "javascript": {"interface_declaration", "type_alias_declaration"},
    "typescript": {"interface_declaration", "type_alias_declaration"},
    "go": set(),
    "rust": {"enum_item", "trait_item", "type_item"},
    "java": set(),
    "c": {"enum_specifier", "type_definition"},
    "cpp": {"enum_specifier", "type_definition"},
    "ruby": set(),
    "php": set(),
}

CALL_TYPES = {
    "call_expression",
    "call",
    "method_invocation",
    "function_call_expression",
    "member_call_expression",
}

NAME_TYPES = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "constant",
    "name",
}


@dataclass
class MultiLangGroundTruth:
    path: str
    language: str
    functions: set[str] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)
    types: set[str] = field(default_factory=set)
    caller_map: dict[str, set[str]] = field(default_factory=dict)


def _parser(language: str):
    from tree_sitter import Language, Parser

    module_name, factory_name = LANGUAGE_MODULES[language]
    module = importlib.import_module(module_name)
    return Parser(Language(getattr(module, factory_name)()))


def _text(node) -> str:
    return node.text.decode("utf-8", errors="replace")


def _first_name(node) -> str | None:
    if node.type == "function_definition":
        for child in node.named_children:
            if child.type == "function_declarator":
                names = _leaf_names(child)
                if names and any(n.type == "destructor_name" for n in child.named_children):
                    return "~" + names[-1]
    direct = node.child_by_field_name("name")
    if direct is not None and _text(direct).strip():
        return _text(direct).strip()
    declarator = node.child_by_field_name("declarator")
    if declarator is not None:
        nested = _first_name(declarator)
        if nested:
            return nested
    for child in node.named_children:
        if child.type in NAME_TYPES:
            value = _text(child).strip()
            if value:
                return value
        nested = _first_name(child)
        if nested:
            return nested
    return None


def _declared_name(node) -> str | None:
    """Return a declaration's own name without borrowing a field name."""
    direct = node.child_by_field_name("name")
    if direct is not None and _text(direct).strip():
        return _text(direct).strip()
    for child in node.named_children:
        if child.type in {"type_identifier", "constant", "identifier"}:
            return _text(child).strip()
    return None


def _call_name(node) -> str | None:
    target = node.child_by_field_name("function")
    if target is None:
        target = node.child_by_field_name("method")
    if target is None and node.named_children:
        target = node.named_children[0]
    if target is None:
        return None
    names = [n for n in _leaf_names(target)]
    return names[-1] if names else None


def _leaf_names(node) -> list[str]:
    if node.type in NAME_TYPES:
        value = _text(node).strip()
        return [value] if value else []
    result: list[str] = []
    for child in node.named_children:
        result.extend(_leaf_names(child))
    return result


def extract(file_path: str, language: str) -> MultiLangGroundTruth:
    path = Path(file_path)
    gt = MultiLangGroundTruth(path=file_path, language=language)
    try:
        source = path.read_bytes()
        root = _parser(language).parse(source).root_node
    except (OSError, KeyError, ImportError):
        return gt

    functions = FUNCTION_TYPES[language]
    classes = CLASS_TYPES[language]
    types = TYPE_TYPES[language]
    function_stack: list[str] = []

    def visit(node) -> None:
        if node.type in functions:
            name = _first_name(node)
            if name:
                gt.functions.add(name)
                function_stack.append(name)
                for child in node.named_children:
                    visit(child)
                function_stack.pop()
                return

        if node.type == "type_spec" and language == "go":
            kind = next((child.type for child in node.named_children if child.type in {"struct_type", "interface_type"}), None)
            name = _declared_name(node)
            if name:
                (gt.classes if kind else gt.types).add(name)

        if node.type in classes:
            name = _declared_name(node)
            if name:
                gt.classes.add(name)

        if node.type in types:
            name = _declared_name(node)
            if name:
                gt.types.add(name)

        if node.type in CALL_TYPES and function_stack:
            name = _call_name(node)
            if name:
                gt.caller_map.setdefault(name, set()).add(function_stack[-1])

        for child in node.named_children:
            visit(child)

    visit(root)
    return gt

