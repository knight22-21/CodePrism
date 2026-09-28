"""Tests for RubyParser."""

from pathlib import Path

import pytest

from codeprism.core.models import EdgeKind, NodeKind
from codeprism.parser.ruby_parser import RubyParser

FIXTURE = Path(__file__).parent / "fixtures" / "sample_ruby_project" / "data_processor.rb"


@pytest.fixture()
def parser():
    return RubyParser()


@pytest.fixture()
def result(parser):
    content = FIXTURE.read_text(encoding="utf-8")
    return parser.parse(str(FIXTURE), content)


# ── FileRecord ────────────────────────────────────────────────────────────────


def test_file_language(result):
    assert result.file.language == "ruby"


def test_file_line_count(result):
    assert result.file.line_count > 0


def test_file_checksum(result):
    assert len(result.file.checksum) == 64


# ── Imports ───────────────────────────────────────────────────────────────────


def test_requires_extracted(result):
    imports = [s for s in result.symbols if s.kind == NodeKind.IMPORT]
    names = [i.name for i in imports]
    assert "json" in names
    assert "helpers" in names


# ── Module ────────────────────────────────────────────────────────────────────


def test_module_extracted(result):
    modules = [s for s in result.symbols if s.kind == NodeKind.MODULE]
    names = [m.name for m in modules]
    assert "Processing" in names
    assert "Helpers" in names


def test_module_signature(result):
    mod = next(s for s in result.symbols if s.name == "Processing" and s.kind == NodeKind.MODULE)
    assert "module" in mod.signature
    assert "Processing" in mod.signature


# ── Classes ───────────────────────────────────────────────────────────────────


def test_class_extracted(result):
    classes = [s for s in result.symbols if s.kind == NodeKind.CLASS]
    names = [c.name for c in classes]
    assert "DataProcessor" in names


def test_class_signature(result):
    cls = next(s for s in result.symbols if s.name == "DataProcessor")
    assert "class" in cls.signature
    assert "DataProcessor" in cls.signature


def test_class_inheritance_in_signature(result):
    cls = next(s for s in result.symbols if s.name == "DataProcessor")
    assert "BaseProcessor" in cls.signature


def test_class_inheritance_ref(result):
    inherits = [r for r in result.unresolved_refs if r.kind == EdgeKind.INHERITS]
    assert any(r.ref_name == "BaseProcessor" for r in inherits)


# ── Methods ───────────────────────────────────────────────────────────────────


def test_instance_methods_extracted(result):
    funcs = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "initialize" in names
    assert "process" in names
    assert "validate" in names


def test_class_method_extracted(result):
    funcs = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "create" in names


def test_class_method_signature(result):
    create = next(s for s in result.symbols if s.name == "create" and s.kind == NodeKind.FUNCTION)
    assert "self" in create.signature


def test_private_method_not_public(result):
    transform = next(s for s in result.symbols if s.name == "transform")
    assert transform.is_public is False


def test_public_method_is_public(result):
    process = next(s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION)
    assert process.is_public is True


def test_method_signature_has_params(result):
    process = next(s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION)
    assert "(" in process.signature


def test_top_level_func_extracted(result):
    funcs = [s for s in result.symbols if s.kind == NodeKind.FUNCTION]
    names = [f.name for f in funcs]
    assert "standalone_util" in names


# ── Constants ─────────────────────────────────────────────────────────────────


def test_constant_extracted(result):
    vars_ = [s for s in result.symbols if s.kind == NodeKind.VARIABLE]
    names = [v.name for v in vars_]
    assert "BATCH_SIZE" in names


# ── Complexity ────────────────────────────────────────────────────────────────


def test_process_complexity_greater_than_one(result):
    process = next(s for s in result.symbols if s.name == "process" and s.kind == NodeKind.FUNCTION)
    assert process.complexity_score > 1.0


def test_simple_method_complexity_one(result):
    log = next(s for s in result.symbols if s.name == "log")
    assert log.complexity_score == 1.0


# ── Edges ─────────────────────────────────────────────────────────────────────


def test_defines_edges_present(result):
    defines = [e for e in result.edges if e.kind == EdgeKind.DEFINES]
    assert len(defines) > 0


def test_call_refs_present(result):
    calls = [r for r in result.unresolved_refs if r.kind == EdgeKind.CALLS]
    callee_names = [r.ref_name for r in calls]
    assert any(n in callee_names for n in ("transform", "puts", "map", "to_json"))


# ── Line numbers ──────────────────────────────────────────────────────────────


def test_symbols_have_line_numbers(result):
    for sym in result.symbols:
        assert sym.line_start is not None
        assert sym.line_start > 0


# ── Extension support ─────────────────────────────────────────────────────────


def test_parser_extensions(parser):
    assert parser.can_parse("app.rb")
    assert parser.can_parse("Rakefile.rake")
    assert parser.can_parse("my_gem.gemspec")
    assert not parser.can_parse("main.py")
    assert not parser.can_parse("Main.java")
