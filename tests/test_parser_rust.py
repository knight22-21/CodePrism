"""Tests for RustParser — functions, structs, enums, traits, consts, imports, edges."""

from pathlib import Path

import pytest

from codeprism.core.models import EdgeKind, NodeKind

RUST_FIXTURE = Path(__file__).parent / "fixtures" / "sample_rust_project" / "main.rs"

pytestmark = pytest.mark.skipif(
    not __import__("importlib").util.find_spec("tree_sitter_rust"),
    reason="tree-sitter-rust not installed",
)


@pytest.fixture
def parser():
    from codeprism.parser.rust_parser import RustParser

    return RustParser()


@pytest.fixture
def result(parser):
    content = RUST_FIXTURE.read_text(encoding="utf-8")
    return parser.parse(str(RUST_FIXTURE), content)


# ── File record ────────────────────────────────────────────────────────────────


def test_file_language_is_rust(result):
    assert result.file.language == "rust"


def test_file_line_count_positive(result):
    assert result.file.line_count > 0


def test_file_checksum_set(result):
    assert result.file.checksum


# ── Struct extraction ──────────────────────────────────────────────────────────


def test_struct_server_found(result):
    names = {s.name for s in result.symbols}
    assert "Server" in names


def test_struct_is_class_kind(result):
    server = next(s for s in result.symbols if s.name == "Server")
    assert server.kind == NodeKind.CLASS


def test_struct_signature_contains_struct(result):
    server = next(s for s in result.symbols if s.name == "Server")
    assert "struct" in (server.signature or "")


# ── Enum extraction ────────────────────────────────────────────────────────────


def test_enum_status_found(result):
    names = {s.name for s in result.symbols}
    assert "Status" in names


def test_enum_is_type_kind(result):
    status = next(s for s in result.symbols if s.name == "Status")
    assert status.kind == NodeKind.TYPE


# ── Trait extraction ───────────────────────────────────────────────────────────


def test_trait_handler_found(result):
    names = {s.name for s in result.symbols}
    assert "Handler" in names


def test_trait_is_type_kind(result):
    handler = next(s for s in result.symbols if s.name == "Handler")
    assert handler.kind == NodeKind.TYPE


# ── Function extraction ────────────────────────────────────────────────────────


def test_top_level_function_found(result):
    names = {s.name for s in result.symbols}
    assert "log_request" in names


def test_main_found(result):
    names = {s.name for s in result.symbols}
    assert "main" in names


def test_function_kind(result):
    fn = next(s for s in result.symbols if s.name == "log_request")
    assert fn.kind == NodeKind.FUNCTION


def test_impl_method_new_found(result):
    names = {s.name for s in result.symbols}
    assert "new" in names


def test_impl_method_start_found(result):
    names = {s.name for s in result.symbols}
    assert "start" in names


def test_function_signature_contains_fn(result):
    fn = next(s for s in result.symbols if s.name == "log_request")
    assert "fn" in (fn.signature or "")


# ── Type alias extraction ──────────────────────────────────────────────────────


def test_type_alias_request_id_found(result):
    names = {s.name for s in result.symbols}
    assert "RequestId" in names


def test_type_alias_is_type_kind(result):
    rid = next(s for s in result.symbols if s.name == "RequestId")
    assert rid.kind == NodeKind.TYPE


# ── Const extraction ───────────────────────────────────────────────────────────


def test_const_max_retries_found(result):
    names = {s.name for s in result.symbols}
    assert "MAX_RETRIES" in names


def test_const_is_variable_kind(result):
    c = next(s for s in result.symbols if s.name == "MAX_RETRIES")
    assert c.kind == NodeKind.VARIABLE


# ── Import / use extraction ────────────────────────────────────────────────────


def test_use_import_found(result):
    imports = [s for s in result.symbols if s.kind == NodeKind.IMPORT]
    names = {s.name for s in imports}
    assert "HashMap" in names


# ── Edges ──────────────────────────────────────────────────────────────────────


def test_defines_edges_present(result):
    assert any(e.kind == EdgeKind.DEFINES for e in result.edges)


def test_no_parse_errors(result):
    assert result.file is not None


# ── Integration: index a Rust project ─────────────────────────────────────────


async def test_index_rust_project(storage, graph, tmp_path):
    import shutil

    from codeprism.core.config import CodePrismConfig
    from codeprism.indexer.project_indexer import ProjectIndexer

    proj = tmp_path / "rust_proj"
    shutil.copytree(RUST_FIXTURE.parent, proj)

    config = CodePrismConfig(languages=["rust"])
    indexer = ProjectIndexer(graph, storage, config)
    result = await indexer.index(str(proj))

    assert result.file_count == 1
    syms = await storage.get_all_symbols()
    names = {s.name for s in syms}
    assert "Server" in names
    assert "log_request" in names
