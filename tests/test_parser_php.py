"""Tests for PhpParser."""

from pathlib import Path

import pytest

from codeprism.core.models import EdgeKind, NodeKind
from codeprism.parser.php_parser import PhpParser

FIXTURE = Path(__file__).parent / "fixtures" / "sample_php_project" / "DataService.php"


@pytest.fixture()
def parser():
    return PhpParser()


@pytest.fixture()
def result(parser):
    content = FIXTURE.read_text(encoding="utf-8")
    return parser.parse(str(FIXTURE), content)


# ── FileRecord ────────────────────────────────────────────────────────────────


def test_file_language(result):
    assert result.file.language == "php"


def test_file_line_count(result):
    assert result.file.line_count > 0


def test_file_checksum(result):
    assert len(result.file.checksum) == 64


# ── Namespace ─────────────────────────────────────────────────────────────────


def test_namespace_extracted(result):
    modules = [s for s in result.symbols if s.kind == NodeKind.MODULE]
    names = [m.name for m in modules]
    assert any("Services" in n for n in names)


def test_namespace_signature(result):
    mod = next(s for s in result.symbols if s.kind == NodeKind.MODULE)
    assert "namespace" in mod.signature


# ── use imports ───────────────────────────────────────────────────────────────


def test_use_imports_extracted(result):
    imports = [s for s in result.symbols if s.kind == NodeKind.IMPORT]
    names = [i.name for i in imports]
    assert "User" in names
    assert "Processable" in names


# ── Classes ───────────────────────────────────────────────────────────────────


def test_class_extracted(result):
    classes = [s for s in result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "DataService" in names


def test_interface_extracted(result):
    classes = [s for s in result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "Processable" in names


def test_trait_extracted(result):
    classes = [s for s in result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "Loggable" in names


def test_class_signature(result):
    cls = next(s for s in result.symbols if s.name == "DataService")
    assert "class" in cls.signature
    assert "DataService" in cls.signature


def test_class_inheritance_in_signature(result):
    cls = next(s for s in result.symbols if s.name == "DataService")
    assert "BaseService" in cls.signature


def test_class_inheritance_ref(result):
    inherits = [r for r in result.unresolved_refs if r.kind == EdgeKind.INHERITS]
    assert any(r.ref_name == "BaseService" for r in inherits)


# ── Methods ───────────────────────────────────────────────────────────────────


def test_methods_extracted(result):
    funcs = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "process" in names
    assert "validate" in names
    assert "__construct" in names


def test_static_method_extracted(result):
    funcs = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "create" in names


def test_static_method_signature(result):
    create = next(s for s in result.symbols if s.name == "create" and s.kind == NodeKind.FUNCTION)
    assert "static" in create.signature


def test_private_method_not_public(result):
    transform = next(s for s in result.symbols if s.name == "transform")
    assert transform.is_public is False


def test_public_method_is_public(result):
    process = next(s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION)
    assert process.is_public is True


def test_method_signature_has_params(result):
    process = next(s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION)
    assert "(" in process.signature


def test_standalone_function_extracted(result):
    funcs = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "standalone_helper" in names


# ── Constants / Properties ────────────────────────────────────────────────────


def test_const_extracted(result):
    vars_ = [s for s in result.symbols if s.kind == NodeKind.VARIABLE]
    names = [v.name for v in vars_]
    assert "VERSION" in names


def test_property_extracted(result):
    vars_ = [s for s in result.symbols if s.kind == NodeKind.VARIABLE]
    names = [v.name for v in vars_]
    assert "$name" in names


# ── Complexity ────────────────────────────────────────────────────────────────


def test_process_complexity_greater_than_one(result):
    process = next(s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION)
    assert process.complexity_score > 1.0


def test_simple_method_complexity_one(result):
    transform = next(s for s in result.symbols if s.name == "transform")
    assert transform.complexity_score == 1.0


# ── Edges ─────────────────────────────────────────────────────────────────────


def test_defines_edges_present(result):
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    assert len(defines) > 0


def test_call_refs_present(result):
    calls = [r for r in result.unresolved_refs if r.kind == EdgeKind.CALLS]
    names = [r.ref_name for r in calls]
    assert any(n in names for n in ("transform", "empty", "count", "is_array"))


# ── Line numbers ──────────────────────────────────────────────────────────────


def test_symbols_have_line_numbers(result):
    for sym in result.symbols:
        assert sym.line_start is not None
        assert sym.line_start > 0


# ── Extension support ─────────────────────────────────────────────────────────


def test_parser_extensions(parser):
    assert parser.can_parse("index.php")
    assert parser.can_parse("view.phtml")
    assert not parser.can_parse("main.py")
    assert not parser.can_parse("Main.java")
