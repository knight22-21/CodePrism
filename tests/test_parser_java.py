"""Tests for JavaParser."""

from pathlib import Path

import pytest

from codeprism.core.models import NodeKind
from codeprism.parser.java_parser import JavaParser

FIXTURE = Path(__file__).parent / "fixtures" / "sample_java_project" / "DataProcessor.java"


@pytest.fixture()
def parser():
    return JavaParser()


@pytest.fixture()
def result(parser):
    content = FIXTURE.read_text(encoding="utf-8")
    return parser.parse(str(FIXTURE), content)


# ── FileRecord ────────────────────────────────────────────────────────────────


def test_file_record_language(result):
    assert result.file.language == "java"


def test_file_record_line_count(result):
    assert result.file.line_count > 0


def test_file_record_checksum(result):
    assert len(result.file.checksum) == 64


# ── Symbol kinds ──────────────────────────────────────────────────────────────


def test_class_extracted(result):
    classes = [s for s in result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "DataProcessor" in names


def test_interface_extracted(result):
    classes = [s for s in result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "Processable" in names


def test_methods_extracted(result):
    methods = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [m.name for m in methods]
    assert "process" in names
    assert "transform" in names
    assert "getName" in names


def test_constructor_extracted(result):
    functions = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in functions]
    assert "DataProcessor" in names


def test_fields_extracted(result):
    variables = [s for s in result.symbols if s.kind == NodeKind.VARIABLE]
    names = [v.name for v in variables]
    assert "name" in names
    assert "MAX_SIZE" in names


def test_imports_extracted(result):
    imports = [s for s in result.symbols if s.kind == NodeKind.IMPORT]
    names = [i.name for i in imports]
    assert "List" in names
    assert "ArrayList" in names


def test_package_extracted(result):
    modules = [s for s in result.symbols if s.kind == NodeKind.MODULE]
    assert any("com.example" in m.name for m in modules)


# ── Visibility ────────────────────────────────────────────────────────────────


def test_public_class_is_public(result):
    dp = next(s for s in result.symbols if s.name == "DataProcessor" and s.kind == NodeKind.CLASS)
    assert dp.is_public is True


def test_private_method_not_public(result):
    transform = next(s for s in result.symbols if s.name == "transform")
    assert transform.is_public is False


def test_public_method_is_public(result):
    process = next(
        s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION
    )
    assert process.is_public is True


# ── Signatures ────────────────────────────────────────────────────────────────


def test_class_signature_contains_name(result):
    dp = next(s for s in result.symbols if s.name == "DataProcessor" and s.kind == NodeKind.CLASS)
    assert "DataProcessor" in dp.signature
    assert "class" in dp.signature


def test_method_signature_has_params(result):
    process = next(
        s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION
    )
    assert "(" in process.signature


# ── Complexity ────────────────────────────────────────────────────────────────


def test_process_complexity_greater_than_one(result):
    process = next(
        s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION
    )
    assert process.complexity_score > 1.0


def test_getter_complexity_is_one(result):
    getter = next(s for s in result.symbols if s.name == "getName")
    assert getter.complexity_score == 1.0


# ── Edges ─────────────────────────────────────────────────────────────────────


def test_defines_edges_present(result):
    from codeprism.core.models import EdgeKind

    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    assert len(defines) > 0


def test_calls_refs_present(result):
    # transform() calls toUpperCase / substring — unresolved cross-file refs
    callee_names = [r.ref_name for r in result.unresolved_refs]
    assert any(name in callee_names for name in ("transform", "toUpperCase", "substring", "add"))


# ── Line numbers ──────────────────────────────────────────────────────────────


def test_symbols_have_line_numbers(result):
    for sym in result.symbols:
        assert sym.line_start is not None
        assert sym.line_start > 0


# ── Extension support ─────────────────────────────────────────────────────────


def test_can_parse_java_extension(parser):
    assert parser.can_parse("Foo.java")
    assert not parser.can_parse("Foo.py")
    assert not parser.can_parse("Foo.go")
