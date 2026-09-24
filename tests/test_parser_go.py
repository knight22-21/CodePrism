"""Tests for GoParser — functions, structs, interfaces, imports, edges."""

from pathlib import Path

import pytest

from codeprism.core.models import EdgeKind, NodeKind

GO_FIXTURE = Path(__file__).parent / "fixtures" / "sample_go_project" / "main.go"

pytestmark = pytest.mark.skipif(
    not __import__("importlib").util.find_spec("tree_sitter_go"),
    reason="tree-sitter-go not installed",
)


@pytest.fixture
def parser():
    from codeprism.parser.go_parser import GoParser

    return GoParser()


@pytest.fixture
def result(parser):
    content = GO_FIXTURE.read_text(encoding="utf-8")
    return parser.parse(str(GO_FIXTURE), content)


# ── File record ────────────────────────────────────────────────────────────────


def test_file_record_language(result):
    assert result.file.language == "go"


def test_file_record_line_count_positive(result):
    assert result.file.line_count > 0


def test_file_record_checksum_set(result):
    assert result.file.checksum


# ── Struct extraction ──────────────────────────────────────────────────────────


def test_struct_server_found(result):
    names = {s.name for s in result.symbols}
    assert "Server" in names


def test_struct_route_found(result):
    names = {s.name for s in result.symbols}
    assert "Route" in names


def test_struct_is_class_kind(result):
    server = next(s for s in result.symbols if s.name == "Server")
    assert server.kind == NodeKind.CLASS


# ── Function extraction ────────────────────────────────────────────────────────


def test_top_level_function_found(result):
    names = {s.name for s in result.symbols}
    assert "NewServer" in names


def test_main_function_found(result):
    names = {s.name for s in result.symbols}
    assert "main" in names


def test_default_handler_found(result):
    names = {s.name for s in result.symbols}
    assert "defaultHandler" in names


def test_function_kind(result):
    fn = next(s for s in result.symbols if s.name == "NewServer")
    assert fn.kind == NodeKind.FUNCTION


def test_method_start_found(result):
    names = {s.name for s in result.symbols}
    assert "Start" in names


# ── Type extraction ────────────────────────────────────────────────────────────


def test_type_alias_handler_found(result):
    names = {s.name for s in result.symbols}
    assert "Handler" in names


# ── Import extraction ──────────────────────────────────────────────────────────


def test_import_fmt_found(result):
    imports = [s for s in result.symbols if s.kind == NodeKind.IMPORT]
    names = {s.name for s in imports}
    assert "fmt" in names


# ── Edges ──────────────────────────────────────────────────────────────────────


def test_defines_edges_present(result):
    assert any(e.kind == EdgeKind.DEFINES for e in result.edges)


def test_no_parse_errors(result):
    # If parse blew up it would raise before returning
    assert result.file is not None


# ── Integration: index a Go project ───────────────────────────────────────────


async def test_index_go_project(storage, graph, tmp_path):
    import shutil

    from codeprism.core.config import CodePrismConfig
    from codeprism.indexer.project_indexer import ProjectIndexer

    proj = tmp_path / "go_proj"
    shutil.copytree(GO_FIXTURE.parent, proj)

    config = CodePrismConfig(languages=["go"])
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(str(proj))

    assert result.file_count == 1
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "Server" in names
    assert "NewServer" in names
