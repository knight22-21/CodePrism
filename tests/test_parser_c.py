"""Tests for CParser (C) and CppParser (C++)."""

from pathlib import Path

import pytest

from codeprism.core.models import NodeKind
from codeprism.parser.c_parser import CParser, CppParser

C_FIXTURE = Path(__file__).parent / "fixtures" / "sample_c_project" / "geometry.c"
CPP_FIXTURE = Path(__file__).parent / "fixtures" / "sample_c_project" / "graph.cpp"


# ── C fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def c_parser():
    return CParser()


@pytest.fixture()
def c_result(c_parser):
    content = C_FIXTURE.read_text(encoding="utf-8")
    return c_parser.parse(str(C_FIXTURE), content)


# ── C++ fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def cpp_parser():
    return CppParser()


@pytest.fixture()
def cpp_result(cpp_parser):
    content = CPP_FIXTURE.read_text(encoding="utf-8")
    return cpp_parser.parse(str(CPP_FIXTURE), content)


# ── C: FileRecord ─────────────────────────────────────────────────────────────


def test_c_file_language(c_result):
    assert c_result.file.language == "c"


def test_c_file_line_count(c_result):
    assert c_result.file.line_count > 0


def test_c_file_checksum(c_result):
    assert len(c_result.file.checksum) == 64


# ── C: Functions ──────────────────────────────────────────────────────────────


def test_c_functions_extracted(c_result):
    funcs = [s for s in c_result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "compute_area" in names
    assert "compute_distance" in names
    assert "print_point" in names
    assert "main" in names


def test_c_function_signature_has_return_type(c_result):
    area = next(s for s in c_result.symbols if s.name == "compute_area")
    assert "int" in area.signature
    assert "compute_area" in area.signature


def test_c_function_signature_has_params(c_result):
    area = next(s for s in c_result.symbols if s.name == "compute_area")
    assert "(" in area.signature


# ── C: Structs ────────────────────────────────────────────────────────────────


def test_c_struct_extracted(c_result):
    classes = [s for s in c_result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "Rectangle" in names


def test_c_typedef_struct_extracted(c_result):
    types = [s for s in c_result.symbols if s.kind in (NodeKind.TYPE, NodeKind.CLASS)]
    names = [t.name for t in types]
    assert "Point" in names


def test_c_struct_signature(c_result):
    rect = next(s for s in c_result.symbols if s.name == "Rectangle")
    assert "struct" in rect.signature or "Rectangle" in rect.signature


# ── C: Enums ──────────────────────────────────────────────────────────────────


def test_c_enum_extracted(c_result):
    types = [s for s in c_result.symbols if s.kind == NodeKind.TYPE]
    names = [t.name for t in types]
    assert "Color" in names


def test_c_enum_signature(c_result):
    color = next(s for s in c_result.symbols if s.name == "Color")
    assert "enum" in color.signature


# ── C: Includes ───────────────────────────────────────────────────────────────


def test_c_includes_extracted(c_result):
    imports = [s for s in c_result.symbols if s.kind == NodeKind.IMPORT]
    names = [i.name for i in imports]
    assert "stdio" in names
    assert "stdlib" in names
    assert "math" in names


# ── C: Complexity ─────────────────────────────────────────────────────────────


def test_c_main_has_complexity(c_result):
    main = next(s for s in c_result.symbols if s.name == "main")
    assert main.complexity_score >= 1.0


def test_c_simple_func_complexity_one(c_result):
    pp = next(s for s in c_result.symbols if s.name == "print_point")
    assert pp.complexity_score == 1.0


# ── C: Edges ──────────────────────────────────────────────────────────────────


def test_c_defines_edges(c_result):
    from codeprism.core.models import EdgeKind

    defines = [e for e in c_result.edges if e.kind == EdgeKind.DEFINES]
    assert len(defines) > 0


def test_c_call_refs(c_result):
    callee_names = [r.ref_name for r in c_result.unresolved_refs]
    assert any(n in callee_names for n in ("print_point", "compute_distance", "printf", "sqrt"))


# ── C: Line numbers ───────────────────────────────────────────────────────────


def test_c_symbols_have_line_numbers(c_result):
    for sym in c_result.symbols:
        assert sym.line_start is not None
        assert sym.line_start > 0


# ── C: Extension support ──────────────────────────────────────────────────────


def test_c_parser_extensions(c_parser):
    assert c_parser.can_parse("main.c")
    assert c_parser.can_parse("header.h")
    assert not c_parser.can_parse("main.cpp")


# ── C++: FileRecord ───────────────────────────────────────────────────────────


def test_cpp_file_language(cpp_result):
    assert cpp_result.file.language == "cpp"


def test_cpp_file_checksum(cpp_result):
    assert len(cpp_result.file.checksum) == 64


# ── C++: Classes ──────────────────────────────────────────────────────────────


def test_cpp_classes_extracted(cpp_result):
    classes = [s for s in cpp_result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "Node" in names
    assert "GraphNode" in names


def test_cpp_class_inheritance_ref(cpp_result):
    # GraphNode and Node are in the same file, so the INHERITS ref is resolved
    # to a real edge by resolve_intrafile_refs.
    from codeprism.core.models import EdgeKind

    inherits_edges = [e for e in cpp_result.edges if e.kind == EdgeKind.INHERITS]
    assert len(inherits_edges) > 0


def test_cpp_class_signature(cpp_result):
    node_cls = next(s for s in cpp_result.symbols if s.name == "Node" and s.kind == NodeKind.CLASS)
    assert "class" in node_cls.signature
    assert "Node" in node_cls.signature


# ── C++: Methods ──────────────────────────────────────────────────────────────


def test_cpp_methods_extracted(cpp_result):
    funcs = [s for s in cpp_result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "toString" in names or "addNeighbor" in names or "degree" in names


# ── C++: Namespace ────────────────────────────────────────────────────────────


def test_cpp_namespace_extracted(cpp_result):
    modules = [s for s in cpp_result.symbols if s.kind == NodeKind.MODULE]
    names = [m.name for m in modules]
    assert "prism" in names


# ── C++: Includes ─────────────────────────────────────────────────────────────


def test_cpp_includes_extracted(cpp_result):
    imports = [s for s in cpp_result.symbols if s.kind == NodeKind.IMPORT]
    names = [i.name for i in imports]
    assert "string" in names or "vector" in names or "iostream" in names


# ── C++: Extension support ────────────────────────────────────────────────────


def test_cpp_parser_extensions(cpp_parser):
    assert cpp_parser.can_parse("main.cpp")
    assert cpp_parser.can_parse("graph.cc")
    assert cpp_parser.can_parse("header.hpp")
    assert not cpp_parser.can_parse("main.c")
    assert not cpp_parser.can_parse("Main.java")
